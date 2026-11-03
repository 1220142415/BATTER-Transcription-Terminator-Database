"""Resume exact-sequence recovery of published GEM Prodigal CDS; never predict genes.

Pilot retains source files. Batch keeps checksums, archive byte ranges and contig
maps, removing successful input caches to avoid storing duplicate genome sets.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import time
from urllib.parse import quote, urljoin, urlparse

from audit_annotation_recovery import sequences, matching_contigs, compatible_prodigal_ffn, session
from index_gem_ffn import fetch as archive_fetch, session as gem_session
from prepare_annotation_recovery import annotation_path, MANIFEST_PATH
from verify_annotation_correspondence import fasta_records, features
from annotation_transfer_budget import Budget

REPO = 'https://huggingface.co/datasets/liurulong/terminator/resolve/'
PROXY_BUDGET = None


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2)+'\n', encoding='utf-8')
    temp.replace(path)


def download(url, path):
    if path.exists():
        return path.read_bytes()
    http = gem_session() if url.startswith('https://portal.nersc.gov/') else session(None)
    count = 0
    proxied = not url.startswith('https://portal.nersc.gov/')
    try:
        # Only the HF resolve request needs the proxy. Its official CDN is
        # directly reachable, saving the 9.83 GB reference payload allowance.
        if url.startswith(REPO):
            with http.get(url, timeout=(20, 120), stream=True, allow_redirects=False) as redirect:
                redirect.raise_for_status()
                location = urljoin(url, redirect.headers.get('Location',''))
                host = urlparse(location).hostname or ''
                if redirect.status_code in {301,302,303,307,308} and (host.endswith('.cdn.hf.co') or host=='cdn-lfs.huggingface.co'):
                    http, url, proxied = gem_session(), location, False
                    if PROXY_BUDGET:
                        PROXY_BUDGET.charge(2048)
                        PROXY_BUDGET.record('hf_reference_resolve_allowance',2048)
        with http.get(url, timeout=(20, 120), stream=True) as response:
            response.raise_for_status()
            chunks = []
            for chunk in response.iter_content(256*1024):
                if proxied and PROXY_BUDGET:
                    PROXY_BUDGET.charge(len(chunk))
                count += len(chunk); chunks.append(chunk)
            data = b''.join(chunks)
    finally:
        if proxied and PROXY_BUDGET:
            PROXY_BUDGET.record('hf_reference_download',count)
    gzip.decompress(data)  # Reject interrupted/error payloads before caching.
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.part')
    temporary.write_bytes(data); temporary.replace(path)
    return data


def verify_output(ffn_path, source, reference, mapping, gff):
    """Second parser checks every emitted coordinate, strand, sequence and attribute."""
    for original, registered in mapping.items():
        if source[original] != reference[registered]:
            raise ValueError('independent_contig_sequence_mismatch')
    expected, kept, omitted, seen = [], [], 0, set()
    complement = bytes.maketrans(b'ACGTRYMKBDHVN', b'TGCAYRKMVHDBN')
    for header, sequence in fasta_records(ffn_path):
        identifier, start, end, direction, attrs = header.split(' # ')
        if identifier in seen or direction not in {'1', '-1'}:
            raise ValueError('independent_duplicate_or_invalid_strand')
        seen.add(identifier)
        original = identifier.rsplit('_', 1)[0]
        if original not in mapping:
            omitted += 1
            continue
        registered = mapping[original]
        start, end = int(start), int(end)
        if not 1 <= start <= end <= len(reference[registered]):
            raise ValueError('independent_cds_bounds')
        dna = reference[registered][start-1:end]
        if direction == '-1':
            dna = dna.translate(complement)[::-1]
        if bytes(sequence) != dna:
            raise ValueError('independent_cds_sequence')
        attributes = ['ID='+quote(identifier, safe=':._-')]
        attributes += [a for a in attrs.split(';') if a and not a.startswith('ID=')]
        expected.append([registered, 'Prodigal', 'CDS', str(start), str(end), '.',
                         '+' if direction == '1' else '-', '0', ';'.join(attributes)])
        if gff is None:
            kept.append(('>'+header+'\n').encode()+bytes(sequence)+b'\n')
    if gff is not None and features(gff.decode()) != expected:
        raise ValueError('independent_gff_correspondence')
    # This is an in-memory handoff to the existing parser, never a published
    # source file. Fast compression avoids recompressing millions of CDS twice.
    selected = gzip.compress(b''.join(kept), compresslevel=1, mtime=0) if gff is None else None
    return selected, len(expected), omitted


def recover(row, member, archive, revision, root, metadata_root, keep_inputs):
    genome, batch = row[:2]
    status_path = root/'results'/f'{genome}.json'
    destination = root/'publish'/annotation_path(genome, batch)
    previous = json.loads(status_path.read_text()) if status_path.exists() else None
    provenance_path=destination.with_name('provenance.json')
    if destination.exists() and provenance_path.exists() and (not previous or previous['result']=='failed'):
        previous=json.loads(provenance_path.read_text())
    if previous and previous['result'] in {'full', 'partial'}:
        if (previous['reference_revision']!=revision or previous['batch']!=batch
                or previous['archive']!=archive or previous['archive_member']!=member):
            raise ValueError('checkpoint_inputs_changed:'+genome)
        if not destination.exists() or sha(destination.read_bytes()) != previous['file']['sha256']:
            raise ValueError('previously_verified_output_changed:'+genome)
        if not status_path.exists():
            save_json(status_path,previous)
        return previous
    if destination.exists():
        raise ValueError('untracked_annotation_exists:'+genome)
    work = root/'inputs'/genome
    work.mkdir(parents=True, exist_ok=True)
    result = {'genome_id': genome, 'batch': batch, 'source_collection': 'GEM',
              'source_annotation_type': 'published_Prodigal_CDS', 'reference_revision': revision,
              'archive': archive, 'archive_member': member, 'original_status': row[9]}
    for attempt in range(3):
        try:
            if shutil.disk_usage(root).free < 2*1024**3:
                raise OSError('disk_free_below_2GiB')
            metadata_path = metadata_root/'genomes'/f'batter-{batch}'/genome/'metadata.json'
            wrapper = json.loads(metadata_path.read_text(encoding='utf-8'))
            metadata = wrapper['records']['batter']
            if wrapper['genome_id'] != genome or metadata['genome_id'] != genome or metadata['source_collection'] != 'GEM':
                raise ValueError('metadata_identity_mismatch')
            original_url = f'https://portal.nersc.gov/GEM/genomes/fna/{genome}.fna.gz'
            reference_url = f'{REPO}{revision}/v0.5.0/genomes/batter-{batch}/{genome}/reference/reference.fa.gz'
            ffn_path = work/'original.ffn.gz'
            if not ffn_path.exists():
                data = archive_fetch(member['offset'], member['offset']+member['bytes']-1, archive)
                gzip.decompress(data)
                ffn_path.write_bytes(data)
            ffn = ffn_path.read_bytes()
            if len(ffn) != member['bytes']:
                raise ValueError('ffn_member_size_mismatch')
            original_data = download(original_url, work/'original.fna.gz')
            registered_data = download(reference_url, work/'reference.fa.gz')
            expected = metadata['files']['reference.fa.gz']
            if len(registered_data) != expected['bytes'] or sha(registered_data) != expected['sha256']:
                raise ValueError('registered_reference_checksum_mismatch')
            reference, original = sequences(registered_data), sequences(original_data)
            if len(reference) != metadata['reference']['contigs'] or sum(map(len, reference.values())) != metadata['reference']['bases']:
                raise ValueError('registered_reference_dimensions_mismatch')
            mapping = matching_contigs(reference, original, partial=True)
            selected, expected_count, omitted = verify_output(ffn_path, original, reference, mapping, None)
            gff, count = compatible_prodigal_ffn(selected, reference, mapping)
            verify_output(ffn_path, original, reference, mapping, gff)
            if count != expected_count:
                raise ValueError('cds_count_mismatch')
            result.update(result='full' if len(mapping) == len(reference) else 'partial', features=count,
                omitted_source_cds=omitted, matched_reference_contigs=len(mapping), total_reference_contigs=len(reference),
                unmatched_reference_contigs=sorted(set(reference)-set(mapping.values())), contig_map=mapping,
                source_url=archive['url'], source_reference_url=original_url, registered_reference_url=reference_url,
                source_ffn_sha256=sha(ffn), source_reference_sha256=sha(original_data),
                reference_sha256=expected['sha256'], reference_bytes=expected['bytes'],
                file={'bytes': len(gff), 'sha256': sha(gff)}, independent_correspondence='passed',
                processed_at=datetime.now(timezone.utc).isoformat(), attempts=attempt+1)
            destination.parent.mkdir(parents=True, exist_ok=True)
            save_json(destination.with_name('provenance.json'), result)
            destination.write_bytes(gff)
            save_json(status_path, result)
            if not keep_inputs:
                # Only these three known temporary inputs, never published files.
                for name in ['original.ffn.gz', 'original.fna.gz', 'reference.fa.gz']:
                    (work/name).unlink()
                work.rmdir()
            return result
        except Exception as error:
            result.update(result='failed', reason=f'{type(error).__name__}: {error}', attempts=attempt+1)
            if isinstance(error, (ValueError, AssertionError, FileNotFoundError)):
                break
            time.sleep(2**attempt)
    save_json(status_path, result)
    return result


def run(args):
    global PROXY_BUDGET
    root = args.output
    PROXY_BUDGET = Budget(root/'proxy-transfer.jsonl')
    catalogue = json.loads((root/'live-catalogue.json').read_text())
    existing = json.loads((root/'hf-manifest.json').read_text())
    d1 = json.loads((root/'d1-gem-before.json').read_text(encoding='utf-8-sig'))
    missing = {r['genome_id'] for r in d1[1]['results'] if r['source']=='GEM' and r['annotation']=='Missing'}
    targets = {r[0]: r for r in catalogue['genomes'] if r[0] in missing}
    index_root = root/'ffn-index'
    archive = json.loads((index_root/'archive.json').read_text())
    def indexed_members():
        members = {}
        for path in index_root.glob('part-*.jsonl'):
            for line in path.read_text().splitlines():
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue  # A scanner may still be appending its final line.
                genome = Path(item['member']).name.removesuffix('.ffn.gz')
                if genome in targets:
                    members[genome] = item
        return members
    members = indexed_members()
    if args.all:
        gate = json.loads((root/'pilot-validation.json').read_text())
        assert gate['accepted'] and gate['genomes'] >= 10, 'pilot_not_accepted'
        selected = sorted(targets)
    else:
        pilot_path = root/'pilot-genomes.json'
        selected = json.loads(pilot_path.read_text()) if pilot_path.exists() else sorted(members, key=lambda g: sha(g.encode()))[:args.limit]
        save_json(pilot_path, selected)
    assert not set(selected) & set(existing['genomes']), 'would_overwrite_existing_recovery'
    print('TARGETS',len(targets),'INDEXED',len(members),'SELECTED',len(selected),flush=True)
    results = []
    pilot_genomes = set(json.loads((root/'pilot-genomes.json').read_text()))
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = set(selected)
        while pending:
            ready = sorted(pending & members.keys())
            tasks = [pool.submit(recover,targets[g],members[g],archive,catalogue['revision'],
                                 root,args.metadata_root,not args.all or g in pilot_genomes) for g in ready]
            for task in as_completed(tasks):
                result=task.result(); results.append(result); pending.remove(result['genome_id'])
                if result['result']=='failed' or len(results)%25==0 or not pending:
                    print('RECOVER',len(results),'/',len(selected),result['genome_id'],result['result'],result.get('reason',''),flush=True)
            if not pending:
                break
            members = indexed_members()
            if pending & members.keys():
                continue
            if not args.all or (index_root/'index.json').exists():
                for genome in pending:
                    result={'genome_id':genome,'result':'failed','reason':'archive_member_absent'}
                    save_json(root/'results'/f'{genome}.json',result);results.append(result)
                pending.clear()
            else:
                print('WAIT_INDEX',len(pending),'remaining',flush=True)
                time.sleep(30)
    manifest = json.loads(json.dumps(existing))
    for result in results:
        if result['result'] not in {'full','partial'}:
            continue
        manifest['genomes'][result['genome_id']] = {k: result[k] for k in ['reference_sha256',
            'matched_reference_contigs','total_reference_contigs','features','source_url','source_annotation_type','file']}
        manifest['genomes'][result['genome_id']]['coverage'] = result['result']
    save_json(root/'publish'/MANIFEST_PATH,manifest)
    report = {'reference_revision': catalogue['revision'], 'complete':args.all,
              'target_genomes':len(targets), 'attempted':len(results), 'counts':dict(Counter(r['result'] for r in results)),
              'features':sum(r.get('features',0) for r in results),
              'gff_bytes':sum(r.get('file',{}).get('bytes',0) for r in results),
              'failure_reasons':dict(Counter(r['reason'] for r in results if r['result']=='failed'))}
    save_json(root/('batch-report.json' if args.all else 'pilot-report.json'),report)
    print(json.dumps(report),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--metadata-root',type=Path,required=True)
    parser.add_argument('--limit',type=int,default=16)
    parser.add_argument('--workers',type=int,default=8)
    parser.add_argument('--all',action='store_true')
    run(parser.parse_args())
