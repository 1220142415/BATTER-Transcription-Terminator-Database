"""Audit public annotation sources without changing a published data snapshot."""
import argparse
import collections
import concurrent.futures
import csv
import gzip
import hashlib
import json
import re
import threading
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
local = threading.local()


def session(proxy):
    import requests
    if not hasattr(local, 'session'):
        local.session = requests.Session()
        from urllib3.util.retry import Retry
        local.session.mount('https://', requests.adapters.HTTPAdapter(max_retries=Retry(total=2, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])))
        if proxy:
            local.session.proxies.update(http=proxy, https=proxy)
    return local.session


def retrieve(url, target, proxy):
    if target.exists():
        return target.read_bytes()
    response = session(proxy).get(url, timeout=(15, 60))
    response.raise_for_status()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + '.part')
    temporary.write_bytes(response.content)
    temporary.replace(target)
    return response.content


def sequences(data):
    result = {}
    for line in gzip.decompress(data).splitlines():
        if line.startswith(b'>'):
            key = line[1:].split()[0].decode()
            if key in result:
                raise ValueError('duplicate_contig')
            result[key] = bytearray()
        elif line:
            result[key].extend(line.strip().upper())
    if not result:
        raise ValueError('empty_reference')
    return {key: bytes(value) for key, value in result.items()}


def matching_contigs(reference, source, partial=False):
    """Coordinates are reused only on byte-identical contigs, without alignment."""
    hashes = collections.defaultdict(list)
    for name, sequence in source.items():
        hashes[hashlib.sha256(sequence).digest()].append(name)
    mapping = {}
    for name, sequence in reference.items():
        candidates = hashes[hashlib.sha256(sequence).digest()]
        if name in candidates:
            selected = name
        elif len(candidates) == 1:
            selected = candidates[0]
        elif partial:
            continue
        else:
            raise ValueError('sequence_difference_or_ambiguous_contigs')
        if selected in mapping:
            raise ValueError('ambiguous_contig_mapping')
        mapping[selected] = name
    if not mapping:
        raise ValueError('no_identical_reference_contigs')
    return mapping


def compatible_gff(data, reference, mapping):
    """Retain features on the displayed reference; never trim or shift coordinates."""
    lines = gzip.decompress(data).decode().splitlines()
    circular = set()
    for line in lines:
        fields = line.split('\t')
        if len(fields) == 9 and fields[2] == 'region' and 'Is_circular=true' in fields[8].split(';'):
            if fields[0] in mapping:
                circular.add(mapping[fields[0]])
    output = ['##gff-version 3']
    output += [f'##sequence-region {name} 1 {len(sequence)}' for name, sequence in reference.items()]
    features = 0
    omitted = 0
    for line in lines:
        if line.startswith('##FASTA'):
            break
        if not line or line.startswith('#'):
            continue
        fields = line.split('\t')
        if len(fields) != 9:
            raise ValueError('malformed_gff')
        if fields[0] not in mapping:
            omitted += 1
            continue
        fields[0] = mapping[fields[0]]
        # NCBI GFF3 represents origin-spanning circular features beyond the
        # reference length. Preserve these declared coordinates, without clipping.
        limit = len(reference[fields[0]]) * (2 if fields[0] in circular else 1)
        if not 1 <= int(fields[3]) <= int(fields[4]) <= limit:
            raise ValueError('feature_outside_reference')
        features += fields[2] not in {'region'}
        output.append('\t'.join(fields))
    if not features:
        raise ValueError('no_gene_features')
    return ('\n'.join(output) + '\n').encode(), features, omitted


def compatible_prodigal_ffn(data, reference, mapping, protein=False):
    """Recover coordinate-bearing Prodigal FFN/FAA records on verified contigs."""
    output = ['##gff-version 3']
    output += [f'##sequence-region {name} 1 {len(sequence)}' for name, sequence in reference.items()]
    complement = bytes.maketrans(b'ACGTRYMKBDHVN', b'TGCAYRKMVHDBN')
    features = 0
    # FASTA identifiers alone omit Prodigal's coordinate-bearing description.
    records = []
    for line in gzip.decompress(data).splitlines():
        if line.startswith(b'>'):
            records.append([line[1:].decode(), bytearray()])
        elif line:
            if not records:
                raise ValueError('malformed_ffn')
            records[-1][1].extend(line.strip().upper())
    seen = set()
    for header, sequence in records:
        fields = header.split(' # ')
        if len(fields) != 5 or fields[3] not in {'1', '-1'}:
            raise ValueError('missing_cds_coordinates')
        if fields[0] in seen:
            raise ValueError('duplicate_cds')
        seen.add(fields[0])
        original = fields[0].rsplit('_', 1)[0]
        if original not in mapping:
            raise ValueError('cds_contig_not_verified')
        name = mapping[original]
        start, end = int(fields[1]), int(fields[2])
        if not 1 <= start <= end <= len(reference[name]):
            raise ValueError('cds_outside_reference')
        expected = reference[name][start - 1:end]
        if fields[3] == '-1':
            expected = expected.translate(complement)[::-1]
        if protein and len(sequence) * 3 != end - start + 1:
            raise ValueError('cds_protein_length_mismatch')
        if not protein and sequence != expected:
            raise ValueError('cds_sequence_mismatch')
        # Prodigal FFN sequences begin at the coding frame; its published CDS
        # boundaries are retained, including the original partial attributes.
        attributes = ['ID=' + quote(fields[0], safe=':._-')]
        attributes += [item for item in fields[4].split(';') if item and not item.startswith('ID=')]
        output.append('\t'.join([name, 'Prodigal', 'CDS', str(start), str(end), '.',
                                 '+' if fields[3] == '1' else '-', '0', ';'.join(attributes)]))
        features += 1
    if not features:
        raise ValueError('no_cds_features')
    return ('\n'.join(output) + '\n').encode(), features


def published_reference(row, revision, output, proxy):
    accession, batch = row[:2]
    url = f'https://huggingface.co/datasets/liurulong/terminator/resolve/{revision}/v0.5.0/genomes/batter-{batch}/{accession}/reference/reference.fa.gz'
    data = retrieve(url, output / 'reference' / (accession + '.fa.gz'), proxy)
    path = ROOT / 'dist/hf-metadata' / revision / 'genomes' / ('batter-' + batch) / accession / 'metadata.json'
    expected = json.loads(path.read_text(encoding='utf-8'))['records']['batter']['files']['reference.fa.gz']
    if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
        raise ValueError('published_reference_checksum_mismatch')
    return sequences(data), expected['sha256']


def audit_gem(row, revision, output, proxy, ffn_path):
    accession, batch = row[:2]
    result = {'genome_id': accession, 'batch': batch, 'original_status': row[9],
              'source_annotation_type': 'published_Prodigal_CDS',
              'gff_url': 'https://portal.nersc.gov/GEM/genomes/ffn.tar',
              'archive_member': f'ffn/{accession}.ffn.gz'}
    try:
        if row[12] != 'GEM':
            raise ValueError('not_a_gem_genome')
        source_url = f'https://portal.nersc.gov/GEM/genomes/fna/{accession}.fna.gz'
        source = retrieve(source_url, output / 'raw' / (accession + '.fna.gz'), proxy)
        reference, checksum = published_reference(row, revision, output, proxy)
        mapping = matching_contigs(reference, sequences(source))
        ffn = ffn_path.read_bytes()
        restored, features = compatible_prodigal_ffn(ffn, reference, mapping)
        target = output / 'restored-partial' / (accession + '.gff3.gz')
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(gzip.compress(restored, mtime=0))
        result.update(result='verified_restorable', features=features,
                      source_reference_url=source_url, source_reference_sha256=hashlib.sha256(source).hexdigest(),
                      source_ffn_sha256=hashlib.sha256(ffn).hexdigest(), reference_sha256=checksum,
                      matched_reference_contigs=len(mapping), total_reference_contigs=len(reference),
                      contig_map=mapping, output_bytes=target.stat().st_size,
                      output_sha256=hashlib.sha256(target.read_bytes()).hexdigest())
    except Exception as error:
        result.update(result='unresolved', reason=str(error))
    return result


def audit_almeida(row, revision, output, proxy, mapping):
    accession, batch = row[:2]
    result = {'genome_id': accession, 'batch': batch, 'original_status': row[9],
              'source_annotation_type': 'published_Prodigal_CDS'}
    try:
        umgs = mapping.get(accession)
        if not umgs:
            raise ValueError('original_umgs_identifier_not_registered')
        base = 'https://ftp.ebi.ac.uk/pub/databases/metagenomics/umgs_analyses/umgs/'
        source_url = base + 'genomes/' + umgs + '.fa.gz'
        protein_url = base + 'proteins/' + umgs + '_proteins.faa.gz'
        result.update(source_accession=umgs, gff_url=protein_url, source_reference_url=source_url)
        source = retrieve(source_url, output / 'raw' / (accession + '.fna.gz'), proxy)
        protein = retrieve(protein_url, output / 'raw' / (accession + '.faa.gz'), proxy)
        reference, checksum = published_reference(row, revision, output, proxy)
        contigs = matching_contigs(reference, sequences(source))
        restored, features = compatible_prodigal_ffn(protein, reference, contigs, protein=True)
        target = output / 'restored-partial' / (accession + '.gff3.gz')
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(gzip.compress(restored, mtime=0))
        result.update(result='verified_restorable', features=features,
                      source_reference_sha256=hashlib.sha256(source).hexdigest(),
                      source_faa_sha256=hashlib.sha256(protein).hexdigest(), reference_sha256=checksum,
                      matched_reference_contigs=len(contigs), total_reference_contigs=len(reference),
                      contig_map=contigs, output_bytes=target.stat().st_size,
                      output_sha256=hashlib.sha256(target.read_bytes()).hexdigest())
    except Exception as error:
        result.update(result='unresolved', reason=str(error))
    return result


def ftp_location(accession, output, proxy):
    number = accession.split('_')[1].split('.')[0]
    directory = f'https://ftp.ncbi.nlm.nih.gov/genomes/all/{accession[:3]}/{number[:3]}/{number[3:6]}/{number[6:]}/'
    listing = retrieve(directory, output / 'listings' / (accession + '.html'), proxy).decode()
    folders = re.findall(r'href="(' + re.escape(accession) + r'_[^"/]+/)', listing)
    if len(folders) != 1:
        raise ValueError('exact_version_directory_missing')
    return directory + folders[0], folders[0].rstrip('/')


def audit(row, revision, output, proxy, verify, paired=False, partial=False):
    accession, batch = row[:2]
    result = {'genome_id': accession, 'batch': batch, 'original_status': row[9]}
    try:
        base, stem = ftp_location(accession, output, proxy)
        source_accession = accession
        if paired:
            report = retrieve(base + stem + '_assembly_report.txt', output / 'reports' / (accession + '.txt'), proxy).decode()
            match = re.search(r'^# GenBank assembly accession:\s+(GCA_\d+\.\d+)', report, re.M)
            if not match:
                raise ValueError('paired_genbank_accession_not_registered')
            source_accession = match[1]
            base, stem = ftp_location(source_accession, output, proxy)
        result['source_accession'] = source_accession
        listing = retrieve(base, output / 'listings' / (source_accession + '-files.html'), proxy).decode()
        if f'href="{stem}_genomic.gff.gz"' not in listing:
            result['result'] = 'gff_not_published'
            return result
        result.update(result='gff_found_unverified', gff_url=base + stem + '_genomic.gff.gz')
        if not verify:
            return result
        gff = retrieve(result['gff_url'], output / 'raw' / (accession + '.gff.gz'), proxy)
        source = retrieve(base + stem + '_genomic.fna.gz', output / 'raw' / (accession + '.fna.gz'), proxy)
        reference, reference_sha256 = published_reference(row, revision, output, proxy)
        mapping = matching_contigs(reference, sequences(source), partial=partial)
        restored, features, omitted = compatible_gff(gff, reference, mapping)
        circular_features = sum(1 for line in restored.decode().splitlines() if not line.startswith('#')
                                and int(line.split('\t')[4]) > len(reference[line.split('\t')[0]]))
        target = output / ('restored-partial' if partial else 'restored') / (accession + '.gff3.gz')
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(gzip.compress(restored, mtime=0))
        result.update(result='verified_restorable' if len(mapping) == len(reference) else 'verified_partial',
                      features=features, omitted_source_features=omitted,
                      matched_reference_contigs=len(mapping), total_reference_contigs=len(reference),
                      unmatched_reference_contigs=sorted(set(reference) - set(mapping.values())),
                      circular_features=circular_features,
                      contig_map=mapping, source_gff_sha256=hashlib.sha256(gff).hexdigest(),
                      reference_sha256=reference_sha256, output_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                      output_bytes=target.stat().st_size)
    except Exception as error:
        result['result'] = 'unresolved'
        result['reason'] = str(error)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/annotation-recovery-2026-10-14')
    parser.add_argument('--proxy')
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--status', nargs='+', default=['mismatch', 'download_failed', 'invalid_gff', 'unavailable'])
    parser.add_argument('--accession', nargs='+')
    parser.add_argument('--paired', action='store_true', help='Use only GenBank pairs recorded in the official RefSeq assembly report')
    parser.add_argument('--partial', action='store_true', help='Separately report annotations recovered on a subset of identical contigs')
    parser.add_argument('--gem-ffn', type=Path, help='Audit one extracted, published GEM FFN member selected by --accession')
    parser.add_argument('--almeida', action='store_true', help='Audit original UMGS protein headers on identical reference contigs')
    args = parser.parse_args()
    data = json.loads((ROOT / 'dist/worker-site/assets/batter-browser.json').read_text(encoding='utf-8'))
    rows = [row for row in data['genomes'] if row[9] in args.status or args.gem_ffn or args.almeida]
    if args.almeida:
        rows = [row for row in rows if row[12] == 'Almeida et al.']
    if args.accession:
        rows = [row for row in rows if row[0] in args.accession]
    if args.paired:
        rows = [row for row in rows if row[0].startswith('GCF_')]
    args.output.mkdir(parents=True, exist_ok=True)
    if args.gem_ffn:
        if not args.accession or len(rows) != 1:
            parser.error('--gem-ffn requires exactly one indexed --accession')
        result = audit_gem(rows[0], data['revision'], args.output, args.proxy, args.gem_ffn)
        report = {'reference_revision': data['revision'], 'verified_sequences': True,
                  'counts': {result['result']: 1}, 'genomes': [result]}
        (args.output / 'gem-verified-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report['counts']), flush=True)
        return
    results = []
    suffix = 'almeida-verified' if args.almeida else 'partial-verified' if args.partial else 'verified' if args.verify else 'discovery'
    def save_report():
        report = {'reference_revision': data['revision'], 'verified_sequences': args.verify or args.almeida,
                  'complete': len(results) == len(rows), 'audited': len(results), 'total': len(rows),
                  'counts': collections.Counter(x['result'] for x in results),
                  'genomes': sorted(results, key=lambda item: item['genome_id'])}
        target = args.output / f'{suffix}-report.json'
        temporary = target.with_suffix('.json.part')
        temporary.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        temporary.replace(target)
    if args.almeida:
        raw_mapping = retrieve('https://ftp.ebi.ac.uk/pub/databases/metagenomics/umgs_analyses/taxonomy_umgs.tab',
                               args.output / 'non-ncbi/taxonomy_umgs.tab', args.proxy)
        mapping = {row['MAG_ID']: row['UMGS_ID'] for row in csv.DictReader(raw_mapping.decode().splitlines(), delimiter='\t')}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        tasks = {pool.submit(audit_almeida, row, data['revision'], args.output, args.proxy, mapping)
                 if args.almeida else pool.submit(audit, row, data['revision'], args.output, args.proxy, args.verify, args.paired, args.partial): row for row in rows}
        for task in concurrent.futures.as_completed(tasks):
            results.append(task.result())
            if len(results) % 25 == 0 or len(results) == len(rows):
                save_report()
            if len(results) % 100 == 0 or len(results) == len(rows):
                print(json.dumps({'completed': len(results), 'total': len(rows), 'results': collections.Counter(x['result'] for x in results)}), flush=True)
    save_report()


if __name__ == '__main__':
    main()
