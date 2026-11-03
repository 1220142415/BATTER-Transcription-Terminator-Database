"""Audit a captured live GEM collection against immutable HF file registrations."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import json
from pathlib import Path

from huggingface_hub import HfApi
from prepare_annotation_recovery import annotation_path


def audit(root):
    d1 = json.loads((root / 'd1-gem-before.json').read_text(encoding='utf-8-sig'))
    release, rows = d1[0]['results'][0], d1[1]['results']
    catalogue = json.loads((root / 'live-catalogue.json').read_text())
    old = json.loads((root / 'hf-manifest.json').read_text())
    revision = json.loads((root / 'hf-head.json').read_text())['sha']
    indexed = {r[0]: r for r in catalogue['genomes']}
    assert len(rows) == len(indexed) == release['source_genome_count']
    paths = {}
    for row in rows:
        genome = row['genome_id']
        recovered = annotation_path(genome, indexed[genome][1])
        paths[recovered] = (genome, 'recovered')
        if row['annotation'] == 'Missing':
            paths[recovered.replace('/recovered/genes.gff3', '/batter/genes.gff3.gz')] = (genome, 'original')
    cache = root / 'hf-file-inventory.json'
    found = json.loads(cache.read_text()) if cache.exists() else {}
    completed = root / 'hf-inventory-checked.json'
    checked = set(json.loads(completed.read_text())) if completed.exists() else set()
    pending = sorted(set(paths) - checked)

    def fetch(batch):
        return batch, HfApi().get_paths_info('liurulong/terminator', batch, repo_type='dataset', revision=revision)

    with ThreadPoolExecutor(max_workers=4) as pool:
        tasks = [pool.submit(fetch, pending[i:i+500]) for i in range(0, len(pending), 500)]
        for task in as_completed(tasks):
            batch, files = task.result()
            for item in files:
                found[item.path] = {'bytes': item.size, 'blob_id': item.blob_id,
                                    'lfs_sha256': item.lfs.sha256 if item.lfs else None}
            checked.update(batch)
            cache.write_text(json.dumps(found, indent=2)+'\n')
            completed.write_text(json.dumps(sorted(checked))+'\n')
            print('INVENTORY', len(checked), '/', len(paths), 'found', len(found), flush=True)
    anomalies = []
    for path, item in found.items():
        genome, kind = paths[path]
        if kind == 'recovered' and genome not in old['genomes']:
            anomalies.append({'genome_id': genome, 'reason': 'unregistered_recovered_file', 'path': path})
        if kind == 'original':
            anomalies.append({'genome_id': genome, 'reason': 'original_file_on_missing_genome_requires_validation', 'path': path})
    for genome, entry in old['genomes'].items():
        path = annotation_path(genome, indexed[genome][1])
        if path not in found or found[path]['bytes'] != entry['file']['bytes']:
            anomalies.append({'genome_id': genome, 'reason': 'registered_recovery_missing_or_size_mismatch', 'path': path})
    active = catalogue['annotation_recovery']['genomes']
    assert old['genomes'] == active, 'active_manifest_differs_from_published'
    summary = []
    for source in ['GEM', 'IMG', 'NCBI GenBank', 'NCBI RefSeq', 'Pasolli et al.', 'Almeida et al.', 'Nayfach et al.']:
        selected = [r for r in rows if r['source'] == source]
        counts = Counter('partial' if r['recovered_coverage'] == 'partial' else r['annotation'] for r in selected)
        summary.append({'source': source, 'available_full_or_original': counts['Available'],
                        'available_partial': counts['partial'], 'missing': counts['Missing'], 'total': len(selected)})
    with (root/'annotation-audit.tsv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summary[0]), delimiter='\t')
        writer.writeheader(); writer.writerows(summary)
    (root/'inventory-anomalies.json').write_text(json.dumps(anomalies, indent=2)+'\n')
    report = {'collection_version': release['version'], 'reference_revision': release['reference_revision'],
              'active_annotation_revision': release['annotation_revision'], 'inventory_revision': revision,
              'sources': summary, 'missing': sum(r['missing'] for r in summary),
              'available': sum(r['available_full_or_original']+r['available_partial'] for r in summary),
              'registered_recoveries': len(old['genomes']), 'checked_paths': len(checked), 'anomalies': anomalies}
    (root/'annotation-audit.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    audit(parser.parse_args().output)
