"""Cache checksum-verified public HF metadata for D1, without scientific files."""
import argparse
import concurrent.futures
import hashlib
import json
import re
import threading
import time
import urllib.request
from pathlib import Path

from prepare_batter_browser import REVISION, ROOT, build_release
from build_batter_browser import read_browser_catalogue

MANIFEST_SHA256 = '4275151e477eafe63b3b9dbcad3ba751976c98493efff1380c2635696a4f8c6c'


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def sql_value(value):
    return 'NULL' if value is None else "'" + str(value).replace("'", "''") + "'"


def build_sql(cache, release, catalogue, output):
    """Generate resumable inserts only after the complete snapshot passes checks."""
    manifest_path = ROOT / 'dist/hf-catalogue' / REVISION / 'release.json'
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    published_path = manifest_path.parent / 'catalogues/genomes.json'
    published = json.loads(published_path.read_bytes())
    rows = {row[0]: row for row in catalogue['genomes']}
    files = {entry['path']: entry for entry in release['files']}
    if len(published) != release['counts']['genomes'] or len(rows) != release['counts']['batter_genomes']:
        raise ValueError('Incomplete genome catalogue')
    output.mkdir(parents=True, exist_ok=True)
    header = {key: value for key, value in catalogue.items() if key != 'genomes'}
    manifest_header = {key: value for key, value in release.items() if key != 'files'}
    values = [REVISION, release['release_version'], manifest_hash, compact(manifest_header), compact(header),
              len(published), len(rows), len(files), 'loading']
    schema = (ROOT / 'prototype/accession-range/migrations/0004_hf_metadata.sql').read_text(encoding='utf-8')
    (output / '000-schema.sql').write_text(schema + '\nINSERT OR IGNORE INTO hf_metadata_releases VALUES (' + ','.join(map(sql_value, values)) + ');\n', encoding='utf-8', newline='\n')

    chunks, statements, size = [], [], 0

    def append(statement):
        nonlocal statements, size
        if len(statement.encode('utf-8')) > 100000:
            raise ValueError('SQL statement exceeds the D1 limit')
        statements.append(statement)
        size += len(statement.encode('utf-8'))
        if size >= 4 * 1024 * 1024:
            flush()

    def flush():
        nonlocal statements, size
        if not statements:
            return
        path = output / f'{len(chunks) + 1:03d}-data.sql'
        path.write_text('\n'.join(statements) + '\n', encoding='utf-8', newline='\n')
        chunks.append(path.name)
        statements, size = [], 0

    for page, start in enumerate(range(0, len(catalogue['genomes']), 100)):
        values = [REVISION, page, compact(catalogue['genomes'][start:start + 100])]
        append('INSERT OR IGNORE INTO hf_catalogue_pages VALUES (' + ','.join(map(sql_value, values)) + ');')
    for genome in published:
        path = cache / genome['metadata_path']
        entry = files[genome['metadata_path']]
        if not verified(path, entry):
            raise ValueError(f'Missing or invalid metadata: {path}')
        raw = path.read_bytes().decode('utf-8')
        wrapper = json.loads(raw)
        genome_id = genome['genome_id']
        if any(wrapper.get(key) != genome[key] for key in ('genome_id', 'group', 'has_prediction', 'has_experimental')):
            raise ValueError(f'Genome catalogue mismatch: {genome_id}')
        row = rows.get(genome_id)
        if row:
            metadata = wrapper['records']['batter']
            if metadata['batch'] != row[1] or metadata['otu_id'] != row[2]:
                raise ValueError(f'Computational identity mismatch: {genome_id}')
            for field, column in [('otu_augmentation_span', 5), ('otu_augmentation_window', 6), ('rfam_training_span', 7), ('rfam_training_window', 8), ('tes_prediction', 10)]:
                if metadata['feature_counts'][field] != row[column]:
                    raise ValueError(f'Computational count mismatch: {genome_id}')
        values = [REVISION, genome_id, genome['group'], compact(row) if row else None, compact(genome), raw, entry['sha256']]
        append('INSERT OR IGNORE INTO hf_genome_metadata VALUES (' + ','.join(map(sql_value, values)) + ');')
    for entry in release['files']:
        if set(entry) - {'path', 'byte_size', 'sha256', 'source_path', 'generated'}:
            raise ValueError('Unknown file manifest fields')
        values = [REVISION, entry['path'], entry['byte_size'], entry['sha256'], entry.get('source_path'),
                  int(entry['generated']) if 'generated' in entry else None]
        append('INSERT OR IGNORE INTO hf_registered_files VALUES (' + ','.join(map(sql_value, values)) + ');')
    flush()
    report = {'revision': REVISION, 'manifest_sha256': manifest_hash, 'genomes': len(published),
              'computational_genomes': len(rows), 'registered_files': len(files), 'chunks': chunks}
    (output / 'import-manifest.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report), flush=True)


def verified(path, entry):
    if not path.is_file():
        return False
    data = path.read_bytes()
    return len(data) == entry['byte_size'] and hashlib.sha256(data).hexdigest() == entry['sha256']


def cache_metadata(cache, release, workers, limit=0, proxy=None):
    import requests
    entries = [entry for entry in release['files'] if re.fullmatch(r'genomes/[^/]+/[^/]+/metadata\.json', entry['path'])]
    if limit:
        entries = entries[:limit]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({'https': proxy}) if proxy else urllib.request.ProxyHandler())
    evidence = ROOT.parent / 'BTED-metadata-evidence-2026-10-05/hf-refresh-2026-10-07'
    connections = threading.local()

    def get(entry, download):
        relative = entry['path']
        path = cache / relative
        if verified(path, entry):
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        original = evidence / relative
        if verified(original, entry):
            path.write_bytes(original.read_bytes())
            return
        if not hasattr(connections, 'session'):
            connections.session = requests.Session()
            if proxy:
                connections.session.proxies = {'https': proxy}
        for attempt in range(4):
            try:
                response = connections.session.get(download['href'], headers=download.get('header', {}), timeout=(15, 30))
                response.raise_for_status()
                data = response.content
                if len(data) != entry['byte_size'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
                    raise ValueError(f'Checksum mismatch: {relative}')
                wrapper = json.loads(data)
                if wrapper.get('genome_id') != path.parent.name:
                    raise ValueError(f'Genome mismatch: {relative}')
                path.write_bytes(data)
                return
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(min(60, 2 ** attempt))

    started = time.monotonic()
    failed = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        count = 0
        for start in range(0, len(entries), 500):
            chunk = entries[start:start + 500]
            missing = [entry for entry in chunk if not verified(cache / entry['path'], entry)]
            payload = json.dumps({'operation': 'download', 'transfers': ['basic'], 'ref': {'name': REVISION},
                'objects': [{'oid': entry['sha256'], 'size': entry['byte_size']} for entry in missing]}).encode()
            downloads = {}
            if missing:
                req = urllib.request.Request('https://huggingface.co/datasets/liurulong/terminator.git/info/lfs/objects/batch',
                    data=payload, headers={'Content-Type': 'application/vnd.git-lfs+json', 'Accept': 'application/vnd.git-lfs+json'})
                with opener.open(req, timeout=60) as response:
                    downloads = {obj['oid']: obj.get('actions', {}).get('download') for obj in json.load(response)['objects']}
            tasks = {}
            for entry in missing:
                if downloads.get(entry['sha256']):
                    tasks[pool.submit(get, entry, downloads[entry['sha256']])] = entry['path']
                else:
                    failed.append({'path': entry['path'], 'error': 'LFS object unavailable'})
            for task in concurrent.futures.as_completed(tasks):
                try:
                    task.result()
                except Exception as error:
                    failed.append({'path': tasks[task], 'error': type(error).__name__})
            count += len(chunk)
            print(json.dumps({'completed': count, 'total': len(entries), 'failed': len(failed), 'seconds': round(time.monotonic() - started)}), flush=True)
    (cache / 'download-errors.json').write_text(json.dumps(failed, indent=2) + '\n', encoding='utf-8')
    if failed:
        raise RuntimeError(f'{len(failed)} metadata downloads failed; rerun to resume')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', type=int, default=24)
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--proxy')
    parser.add_argument('--sql-output', type=Path)
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.workers <= 48 or args.limit < 0:
        parser.error('workers must be 1..48; limit must be nonnegative')
    catalogue, release = build_release(ROOT / 'dist/hf-catalogue', REVISION)
    manifest = ROOT / 'dist/hf-catalogue' / REVISION / 'release.json'
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != MANIFEST_SHA256:
        raise ValueError('The pinned HF release manifest changed')
    published_catalogue, _ = read_browser_catalogue()
    if catalogue['genomes'] != published_catalogue['genomes']:
        raise ValueError('Website catalogue differs from verified HF snapshot')
    cache = ROOT / 'dist/hf-metadata' / REVISION
    cache.mkdir(parents=True, exist_ok=True)
    if not args.offline:
        cache_metadata(cache, release, args.workers, args.limit, args.proxy)
    if args.sql_output:
        if args.limit:
            parser.error('A partial download cannot be imported')
        build_sql(cache, release, published_catalogue, args.sql_output)


if __name__ == '__main__':
    main()
