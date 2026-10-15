"""Independently check packaged annotations against cached original publications."""
import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path
from urllib.parse import quote
from prepare_annotation_recovery import annotation_path, MANIFEST_PATH

ROOT = Path(__file__).resolve().parents[1]


def fasta_records(path):
    records = []
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        for line in stream:
            line = line.strip()
            if line.startswith('>'):
                records.append([line[1:], bytearray()])
            elif line:
                assert records, 'sequence_without_header'
                records[-1][1].extend(line.upper().encode())
    assert records, 'empty_fasta'
    return records


def contigs(path):
    records = fasta_records(path)
    result = {header.split()[0]: bytes(sequence) for header, sequence in records}
    assert len(result) == len(records), 'duplicate_contig'
    return result


def features(text):
    result = []
    for line in text.splitlines():
        if line.startswith('##FASTA'):
            break
        if line and not line.startswith('#'):
            fields = line.split('\t')
            assert len(fields) == 9, 'invalid_gff_columns'
            result.append(fields)
    return result


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(audit_root):
    package = audit_root / 'publish'
    manifest = json.loads((package / MANIFEST_PATH).read_text(encoding='utf-8'))
    catalogue = json.loads((ROOT / 'data/registry/batter-browser.json').read_text(encoding='utf-8'))
    assert manifest['reference_revision'] == catalogue['revision'], 'reference_revision_mismatch'
    indexed = {row[0]: row for row in catalogue['genomes']}
    taxonomy = audit_root / 'non-ncbi/taxonomy_umgs.tab'
    with taxonomy.open(encoding='utf-8', newline='') as stream:
        identifiers = {row['MAG_ID']: row['UMGS_ID'] for row in csv.DictReader(stream, delimiter='\t')}
    results = []
    complement = bytes.maketrans(b'ACGTRYMKBDHVN', b'TGCAYRKMVHDBN')
    for genome, entry in manifest['genomes'].items():
        row = indexed[genome]
        gff_path = package / annotation_path(genome, row[1])
        provenance = json.loads(gff_path.with_name('provenance.json').read_text(encoding='utf-8'))
        assert provenance['genome_id'] == genome and provenance['batch'] == row[1], genome
        assert provenance['original_status'] == row[9], genome
        metadata_path = ROOT / 'dist/hf-metadata' / catalogue['revision'] / 'genomes' / ('batter-' + row[1]) / genome / 'metadata.json'
        wrapper = json.loads(metadata_path.read_text(encoding='utf-8'))
        metadata = wrapper['records']['batter']
        assert wrapper['genome_id'] == metadata['genome_id'] == genome, genome
        reference_path = audit_root / 'reference' / (genome + '.fa.gz')
        assert checksum(reference_path) == entry['reference_sha256'] == metadata['files']['reference.fa.gz']['sha256'], genome
        assert reference_path.stat().st_size == metadata['files']['reference.fa.gz']['bytes'], genome
        reference = contigs(reference_path)
        original_reference_path = audit_root / 'raw' / (genome + '.fna.gz')
        original = contigs(original_reference_path)
        mapping = provenance['contig_map']
        assert len(mapping) == len(set(mapping.values())) == entry['matched_reference_contigs'], genome
        assert len(reference) == entry['total_reference_contigs'] == metadata['reference']['contigs'], genome
        for old, new in mapping.items():
            assert original[old] == reference[new], f'{genome}: reference_sequence_mismatch'
        assert (set(mapping.values()) == set(reference)) == (entry['coverage'] == 'full'), genome
        if 'source_reference_sha256' in provenance:
            assert checksum(original_reference_path) == provenance['source_reference_sha256'], genome
        assert gff_path.stat().st_size == entry['file']['bytes'] and checksum(gff_path) == entry['file']['sha256'], genome
        published = features(gff_path.read_text(encoding='utf-8'))
        source_kind = entry['source_annotation_type']
        if source_kind == 'published_NCBI_GFF3':
            source_path = audit_root / 'raw' / (genome + '.gff.gz')
            assert checksum(source_path) == provenance['source_gff_sha256'], genome
            with gzip.open(source_path, 'rt', encoding='utf-8') as stream:
                source_features = features(stream.read())
            expected = []
            for fields in source_features:
                if fields[0] in mapping:
                    expected.append([mapping[fields[0]], *fields[1:]])
            assert len(source_features) - len(expected) == provenance['omitted_source_features'], genome
            assert provenance['source_accession'] == genome, 'unregistered_source_accession'
        else:
            assert source_kind == 'published_Prodigal_CDS', genome
            is_gem = row[12] == 'GEM'
            if is_gem:
                source_path = audit_root / 'non-ncbi' / (genome + '.ffn.gz')
                assert provenance['archive_member'] == 'ffn/' + genome + '.ffn.gz', genome
                assert checksum(source_path) == provenance['source_ffn_sha256'], genome
            else:
                assert row[12] == 'Almeida et al.' and identifiers[genome] == provenance['source_accession'], genome
                assert provenance['gff_url'].endswith('/' + identifiers[genome] + '_proteins.faa.gz'), genome
                assert provenance['source_reference_url'].endswith('/' + identifiers[genome] + '.fa.gz'), genome
                source_path = audit_root / 'raw' / (genome + '.faa.gz')
                assert checksum(source_path) == provenance['source_faa_sha256'], genome
            expected = []
            identifiers_seen = set()
            for header, sequence in fasta_records(source_path):
                identifier, start, end, direction, attributes = header.split(' # ')
                assert identifier not in identifiers_seen and direction in {'1', '-1'}, genome
                identifiers_seen.add(identifier)
                old_contig = identifier.rsplit('_', 1)[0]
                new_contig = mapping[old_contig]
                start, end = int(start), int(end)
                assert 1 <= start <= end <= len(reference[new_contig]), genome
                if is_gem:
                    expected_sequence = reference[new_contig][start - 1:end]
                    if direction == '-1':
                        expected_sequence = expected_sequence.translate(complement)[::-1]
                    assert bytes(sequence) == expected_sequence, f'{genome}: CDS_sequence_mismatch'
                else:
                    assert len(sequence) * 3 == end - start + 1, genome
                attributes = ['ID=' + quote(identifier, safe=':._-')] + [value for value in attributes.split(';') if value and not value.startswith('ID=')]
                expected.append([new_contig, 'Prodigal', 'CDS', str(start), str(end), '.', '+' if direction == '1' else '-', '0', ';'.join(attributes)])
        assert published == expected, f'{genome}: source_coordinate_or_attribute_mismatch'
        circular = {f[0] for f in published if f[2] == 'region' and 'Is_circular=true' in f[8].split(';')}
        for fields in published:
            maximum = len(reference[fields[0]]) * (2 if fields[0] in circular else 1)
            assert 1 <= int(fields[3]) <= int(fields[4]) <= maximum, genome
        count = sum(fields[2] != 'region' for fields in published)
        assert count == entry['features'] == provenance['features'], genome
        results.append({'genome_id': genome, 'source_collection': row[12], 'coverage': entry['coverage'],
            'matched_reference_contigs': len(mapping), 'total_reference_contigs': len(reference), 'features': count,
            'reference_sha256': entry['reference_sha256'], 'source_reference_sha256': checksum(original_reference_path),
            'annotation_sha256': entry['file']['sha256'], 'original_annotation_sha256': checksum(source_path),
            'sequence_identity': 'exact', 'source_coordinates_and_attributes': 'retained',
            'annotation_scope': 'published_GFF3' if source_kind == 'published_NCBI_GFF3' else 'published_CDS_coordinates'})
        if len(results) % 50 == 0:
            print('VERIFIED_CORRESPONDENCE', len(results), '/', len(manifest['genomes']), flush=True)
    report = {'reference_revision': manifest['reference_revision'], 'manifest_sha256': checksum(package / MANIFEST_PATH),
        'complete': True, 'genomes_verified': len(results), 'matched_contigs': sum(row['matched_reference_contigs'] for row in results),
        'features_verified': sum(row['features'] for row in results), 'coverage': dict(Counter(row['coverage'] for row in results)),
        'annotation_scope': dict(Counter(row['annotation_scope'] for row in results)), 'genomes': results}
    (audit_root / 'correspondence-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit-root', type=Path, default=ROOT / 'dist/annotation-recovery-2026-10-14')
    args = parser.parse_args()
    report = verify(args.audit_root)
    print(json.dumps({key: value for key, value in report.items() if key != 'genomes'}))
