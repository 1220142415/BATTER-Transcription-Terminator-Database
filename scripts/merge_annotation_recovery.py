"""Move the verified annotation supplement into v0.5.0 without changing its bytes."""
import concurrent.futures
import getpass
import hashlib
import json
import os
from pathlib import Path

import httpx
from huggingface_hub import HfApi, CommitOperationAdd, CommitOperationDelete
from huggingface_hub.utils import disable_progress_bars
from prepare_annotation_recovery import annotation_path, MANIFEST_PATH

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / 'dist/annotation-recovery-2026-10-14'
OLD_PREFIX = 'v0.5.1/annotation-recovery/2026-10-14'
REPO = 'liurulong/terminator'


def merge():
    old = json.loads((ROOT / 'data/registry/annotation-recovery.json').read_text(encoding='utf-8'))
    if old.get('path_prefix') == 'v0.5.0/genomes':
        print('ALREADY_MERGED', old['annotation_revision'])
        return
    new = json.loads((AUDIT / 'publish' / MANIFEST_PATH).read_text(encoding='utf-8'))
    catalogue = json.loads((ROOT / 'data/registry/batter-browser.json').read_text(encoding='utf-8'))
    batches = {row[0]: row[1] for row in catalogue['genomes']}
    assert old['reference_revision'] == new['reference_revision'] == catalogue['revision']
    assert old['genomes'].keys() == new['genomes'].keys() and len(new['genomes']) == 257
    assert json.loads((AUDIT / 'correspondence-report.json').read_text())['complete'] is True
    destinations, old_paths = {}, []
    for genome, entry in new['genomes'].items():
        previous = old['genomes'][genome]
        expected = {**previous, 'file': {k: v for k, v in previous['file'].items() if k != 'path'}}
        assert entry == expected, genome
        path = annotation_path(genome, batches[genome])
        for source, target in [(previous['file']['path'], path),
                               (previous['file']['path'].rsplit('/', 1)[0] + '/provenance.json', path.rsplit('/', 1)[0] + '/provenance.json')]:
            original = AUDIT / 'publish' / source
            destination = AUDIT / 'publish' / target
            assert original.read_bytes() == destination.read_bytes(), genome
            destinations[target] = destination
            old_paths.append(source)
    destinations[MANIFEST_PATH] = AUDIT / 'publish' / MANIFEST_PATH
    old_paths.append(OLD_PREFIX + '/manifest.json')
    checks = {path: (file.stat().st_size, hashlib.sha256(file.read_bytes()).hexdigest()) for path, file in destinations.items()}
    os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:7997'
    os.environ['HF_HUB_DISABLE_PROGRESS_BARS'] = '1'
    disable_progress_bars()
    api = HfApi(token=getpass.getpass('HF token (hidden, not saved): '))
    api.auth_check(REPO, repo_type='dataset', write=True)
    head = api.repo_info(REPO, repo_type='dataset').sha
    with httpx.Client(proxy=os.environ['HTTPS_PROXY'], timeout=120, follow_redirects=True) as client:
        response = client.get(f'https://huggingface.co/datasets/{REPO}/resolve/{head}/{OLD_PREFIX}/manifest.json')
        response.raise_for_status()
        remote = response.json()
        assert remote == {k: v for k, v in old.items() if k != 'annotation_revision'}
    actual = {entry.path for entry in api.list_repo_tree(REPO, path_in_repo='v0.5.1', recursive=True, repo_type='dataset', revision=head) if hasattr(entry, 'size')}
    assert actual == set(old_paths), 'unexpected_files_in_v051'
    paths = list(destinations)
    for start in range(0, len(paths), 50):
        assert not api.get_paths_info(REPO, paths[start:start + 50], repo_type='dataset', revision=head), 'destination_already_exists'
    print('CHECKED', len(destinations), 'files; original assets unchanged', flush=True)
    operations = [CommitOperationAdd(path_in_repo=path, path_or_fileobj=file) for path, file in destinations.items()]
    operations += [CommitOperationDelete(path_in_repo=path) for path in old_paths]
    commit = api.create_commit(REPO, repo_type='dataset', parent_commit=head, operations=operations,
                               commit_message='Merge verified recovered annotations into v0.5.0 genome directories')
    revision = commit.oid
    receipt = AUDIT / 'merge-receipt.json'
    result = {'annotation_revision': revision, 'parent_revision': head, 'remote_verified': False,
              'files': len(checks), 'manifest_sha256': checks[MANIFEST_PATH][1]}
    receipt.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print('MERGED', revision, flush=True)

    def verify(item):
        path, expected = item
        for attempt in range(3):
            try:
                with httpx.Client(proxy=os.environ['HTTPS_PROXY'], timeout=120, follow_redirects=True) as client:
                    response = client.get(f'https://huggingface.co/datasets/{REPO}/resolve/{revision}/{path}')
                    response.raise_for_status()
                    assert (len(response.content), hashlib.sha256(response.content).hexdigest()) == expected, path
                return path
            except (httpx.HTTPError, AssertionError):
                if attempt == 2:
                    raise

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for count, _ in enumerate(pool.map(verify, checks.items()), 1):
            if count % 50 == 0 or count == len(checks):
                print('REMOTE_VERIFIED', count, '/', len(checks), flush=True)
    assert 'v0.5.1' not in {entry.path for entry in api.list_repo_tree(REPO, repo_type='dataset', revision=revision)}
    result['remote_verified'] = True
    receipt.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    new['annotation_revision'] = revision
    (ROOT / 'data/registry/annotation-recovery.json').write_text(json.dumps(new, indent=2) + '\n', encoding='utf-8')
    print('VERIFIED_REGISTRY_READY', revision, flush=True)


if __name__ == '__main__':
    merge()
