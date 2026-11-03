"""Remove the three user-authorized GEM metadata copies, retaining pinned history.

Only exact paths from the current GEM catalogue and its published inventory are
eligible. Scientific files, experimental metadata and recovered provenance are
never deletion candidates. No D1 writes or force pushes are used.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from huggingface_hub import HfApi, CommitOperationDelete, CommitOperationAdd, hf_hub_download, set_client_factory

from annotation_transfer_budget import Budget
from recover_gem_cds import save_json

REPO = 'liurulong/terminator'
KINDS = {'metadata.tsv', 'metadata.json', 'provenance/batter/metadata.json'}
PATTERN = re.compile(r'^v0\.5\.0/genomes/batter-([0-9]{3})/([^/]+)/(metadata\.tsv|metadata\.json|provenance/batter/metadata\.json)$')
NOTE = '## GEM per-genome metadata cleanup (2026-10-27)'


def candidates(root):
    catalogue = json.loads((root/'live-catalogue.json').read_text(encoding='utf-8'))
    membership = {row[0]: row[1] for row in catalogue['genomes']}
    expected = {}
    with (root/'metadata-review/cleanup-candidates.tsv').open(encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream, delimiter='\t'):
            match = PATTERN.fullmatch(row['path'])
            if (not match or match[2] != row['genome_id'] or match[3] != row['kind']
                    or membership.get(match[2]) != match[1] or row['path'] in expected):
                raise ValueError('candidate_outside_authorized_scope:'+row['path'])
            expected[row['path']] = int(row['bytes'])
    assert len(membership) == 42904
    assert len(expected) == 42904*3
    assert Counter(PATTERN.fullmatch(path)[3] for path in expected) == {kind: 42904 for kind in KINDS}
    return catalogue['revision'], expected


def inventory(api, paths, revision, label):
    paths = list(paths)
    chunks = [paths[start:start+500] for start in range(0, len(paths), 500)]
    found = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(api.get_paths_info, REPO, chunk, repo_type='dataset', revision=revision) for chunk in chunks]
        for count, future in enumerate(as_completed(futures), 1):
            for item in future.result():
                if type(item).__name__ != 'RepoFile':
                    raise ValueError('candidate_is_not_a_file:'+item.path)
                found[item.path] = item.size
            if count % 32 == 0 or count == len(chunks):
                print(label, count, '/', len(chunks), 'found', len(found), flush=True)
    return found


def run(root, apply=False, per_commit=4000):
    if not 1 <= per_commit <= 25000:
        raise ValueError('invalid_commit_size')
    reference, expected = candidates(root)
    work = root/'metadata-cleanup'
    work.mkdir(exist_ok=True)
    # Separate ledger: recovery is still running in another process.
    budget = Budget(work/'proxy-transfer.jsonl', cap=500_000_000)
    set_client_factory(budget.client)
    api = HfApi()
    parent = api.repo_info(REPO, repo_type='dataset').sha
    api.auth_check(REPO, repo_type='dataset', write=apply)
    history_path = work/'start.json'
    history = json.loads(history_path.read_text()) if history_path.exists() else None
    if history and (history['reference_revision'] != reference or history['candidate_count'] != len(expected)):
        raise ValueError('cleanup_scope_changed')
    if not history:
        history = dict(before_sha=parent, reference_revision=reference, candidate_count=len(expected),
            authorized_kinds=sorted(KINDS), started_at=datetime.now(timezone.utc).isoformat())
        save_json(history_path, history)
    previous_preflight = json.loads((work/'preflight.json').read_text()) if (work/'preflight.json').exists() else None
    existing = inventory(api, expected, parent, 'PREFLIGHT')
    if any(expected[path] != size for path, size in existing.items()):
        raise ValueError('current_metadata_differs_from_published_inventory')
    if 'initial_existing_count' not in history:
        history['initial_existing_count'] = previous_preflight['found'] if previous_preflight else len(existing)
        history['initial_missing_count'] = previous_preflight['already_absent'] if previous_preflight else len(expected)-len(existing)
        save_json(history_path, history)
    save_json(work/'preflight.json', dict(revision=parent, found=len(existing), already_absent=len(expected)-len(existing)))
    pending = sorted(existing)
    print('DELETE_READY', len(pending), 'metadata files', 'parent', parent, flush=True)
    if not apply:
        return
    log_path = work/'commits.jsonl'
    receipts = [json.loads(line) for line in log_path.read_text().splitlines()] if log_path.exists() else []
    logged = {path for record in receipts for path in record.get('paths', [])}
    if history['initial_missing_count'] == 0:
        # A request interrupted after server acceptance may lack a local receipt.
        # Reconcile only exact candidates proven present at the original parent.
        unlogged = sorted(set(expected)-set(existing)-logged)
        if unlogged:
            with log_path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(dict(commit=parent, paths=unlogged,
                    reconciled='confirmed absent at resumed parent; present at original parent'))+'\n')
    for start in range(0, len(pending), per_commit):
        group = pending[start:start+per_commit]
        operations = [CommitOperationDelete(path_in_repo=path, is_folder=False) for path in group]
        commit = api.create_commit(REPO, repo_type='dataset', parent_commit=parent, operations=operations,
            commit_message=f'Remove redundant GEM metadata copies: {start+len(group)}/{len(pending)}',
            commit_description='User-authorized exact metadata paths only. Fixed reference and annotation commits, sequences, scientific files and recovered provenance are retained.')
        receipt = dict(parent=parent, commit=commit.oid, paths=group)
        with log_path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(receipt)+'\n')
        parent = commit.oid
        save_json(work/'state.json', dict(commit=parent, deleted_this_run=start+len(group), complete=False))
        print('DELETED', start+len(group), '/', len(pending), parent, flush=True)

    # Existing release manifests remain historical snapshots. Document the
    # reference revision rather than silently claiming they describe main.
    readme_path = hf_hub_download(REPO, 'README.md', repo_type='dataset', revision=parent, cache_dir=str(root/'hf-cache'))
    readme = Path(readme_path).read_text(encoding='utf-8')
    if NOTE not in readme:
        text = (readme.rstrip()+'\n\n'+NOTE+'\n\n'
            'The three metadata copies under the 42,904 GEM Legacy `v0.5.0/genomes/batter-*` genome folders '
            '(`metadata.tsv`, `metadata.json`, and `provenance/batter/metadata.json`) were removed from main '
            'to reduce the repository file count. Scientific files and recovered CDS provenance remain in place.\n\n'
            f'The original GEM release manifest and genome catalogue describe the immutable reference snapshot `{reference}`, '
            'not the metadata-pruned main tree. Resolve their historical metadata paths at that revision. '
            'The BTED website reads its current metadata from D1 and keeps scientific files pinned to their registered commits. '
            f'The complete pre-cleanup tree is retained at `{history["before_sha"]}`.\n')
        commit = api.create_commit(REPO, repo_type='dataset', parent_commit=parent,
            operations=[CommitOperationAdd(path_in_repo='README.md', path_or_fileobj=text.encode('utf-8'))],
            commit_message='Document immutable metadata snapshot after GEM copy cleanup')
        with log_path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(dict(parent=parent, commit=commit.oid, updated=['README.md']))+'\n')
        parent = commit.oid
    remaining = inventory(api, expected, parent, 'VERIFY_ABSENT')
    if remaining:
        raise ValueError('metadata_paths_still_present')
    # Old commit and unaffected scientific paths must both remain accessible.
    first, middle, last = [sorted(expected)[i] for i in [0, len(expected)//2, -1]]
    old_sample = inventory(api, [first, middle, last], history['before_sha'], 'VERIFY_HISTORY')
    if old_sample != {path: expected[path] for path in [first, middle, last]}:
        raise ValueError('historical_metadata_unavailable')
    genome_bases = sorted({path.rsplit('/', 1)[0] for path in expected if path.endswith('/metadata.tsv')})
    science = [base+'/'+suffix for base in [genome_bases[0], genome_bases[len(genome_bases)//2], genome_bases[-1]]
        for suffix in ['reference/reference.fa.gz', 'reference/reference.fa.gz.fai', 'reference/reference.fa.gz.gzi',
                       'predictions/prediction.gff3.gz', 'predictions/prediction.gff3.gz.tbi']]
    before = inventory(api, science, history['before_sha'], 'SCIENCE_BEFORE')
    after = inventory(api, science, parent, 'SCIENCE_AFTER')
    if before != after or len(after) != len(science):
        raise ValueError('scientific_file_sample_changed')
    records = [json.loads(line) for line in log_path.read_text(encoding='utf-8').splitlines()]
    deleted = [path for record in records for path in record.get('paths', [])]
    assert len(deleted) == len(set(deleted))
    assert set(deleted) <= expected.keys()
    report = dict(before_sha=history['before_sha'], commit=parent, reference_revision=reference,
        deleted_files=len(deleted), deleted_by_kind=dict(Counter(PATTERN.fullmatch(path)[3] for path in deleted)),
        verified_absent=len(expected), history_samples_verified=len(old_sample), scientific_samples_verified=len(after),
        complete=True, proxy_body_bytes=budget.used, completed_at=datetime.now(timezone.utc).isoformat())
    save_json(work/'complete.json', report)
    print('CLEANUP_COMPLETE', json.dumps(report), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--per-commit', type=int, default=4000)
    args = parser.parse_args()
    run(args.output, args.apply, args.per_commit)
