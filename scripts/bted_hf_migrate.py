"""Genome-first HF migration, gated by the immutable original full proof.

Run on cu10 to build metadata only; run publish/promote on the HF relay host.
Scientific payloads are copied between fixed HF commits without re-uploading.
No sender state or source payload is modified.
"""
from __future__ import annotations
import argparse
import collections
import hashlib
import io
import json
import re
import os
import subprocess
from pathlib import Path, PurePosixPath

VERSION = 'v0.5.0'
REPO = 'liurulong/terminator'
ORIGINAL_SHA = 'f5c55e9f129fd66722e2b18ca2e146ee189bf8fec44fa39ce239225c95852265'
GROUPS = ['batter-%03d' % n for n in range(43)] + ['experimental', 'catalogues', 'release-controls']


def encode(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')) + '\n').encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.partial')
    temp.write_bytes(encode(value))
    temp.replace(path)


def safe(path):
    if (not isinstance(path, str) or not path or '\\' in path or path.startswith('/')
            or any(p in ('', '.', '..') for p in path.split('/'))):
        raise ValueError('Unsafe migration path')
    return path


def validate_original(manifest, proof, manifest_bytes):
    if (digest(manifest_bytes) != ORIGINAL_SHA or proof.get('status') != 'complete'
            or proof.get('release_manifest_sha256') != ORIGINAL_SHA
            or proof.get('hf_repo') != REPO or proof.get('hf_branch') != 'v05-preparation-' + ORIGINAL_SHA[:12]
            or proof.get('hf_sha256_verified') is not True or proof.get('hf_file_count') != 371963
            or len(manifest['files']) + 3 != 371963 or proof.get('genome_count') != 42904
            or proof.get('completed_groups') != GROUPS
            or not re.fullmatch('[0-9a-f]{40}', proof.get('hf_revision', ''))):
        raise ValueError('Original whole-release proof required; batch preview is insufficient')


def path_map(files):
    """Exact IDs and existing groups only. Unknown files are retained as provenance."""
    groups = {}
    for row in files:
        pieces = safe(row['path']).split('/')
        if pieces[:2] == ['batter', 'batches'] and len(pieces) >= 6 and pieces[3] == 'genomes':
            genome = pieces[4]
            group = 'batter-' + pieces[2]
            if genome in groups and groups[genome] != group:
                raise ValueError('Genome assigned to multiple batches')
            groups[genome] = group
    references = collections.defaultdict(dict)
    for row in files:
        p = row['path'].split('/')
        if p[:2] == ['experimental', 'genomes'] and p[-1].startswith('reference.fa.gz'):
            references[p[2]].setdefault('experimental', {})[p[-1]] = (row['byte_size'], row['sha256'])
        elif p[:2] == ['batter', 'batches'] and len(p) == 6 and p[-1].startswith('reference.fa.gz'):
            references[p[4]].setdefault('batter', {})[p[-1]] = (row['byte_size'], row['sha256'])
    distinct_references = {g for g, origins in references.items() if 'batter' in origins and 'experimental' in origins and origins['batter'] != origins['experimental']}
    mapped, inventory = {}, {}
    for row in files:
        old = row['path']
        pieces = old.split('/')
        experimental = pieces[:2] == ['experimental', 'genomes']
        batter = pieces[:2] == ['batter', 'batches'] and len(pieces) >= 6 and pieces[3] == 'genomes'
        if experimental or batter:
            genome = pieces[2] if experimental else pieces[4]
            tail = '/'.join(pieces[3:] if experimental else pieces[5:])
            root = 'genomes/' + groups.get(genome, 'experimental-only') + '/' + genome + '/'
            origin = 'experimental' if experimental else 'batter'
            if tail.startswith('reference.fa.gz'):
                target = root + 'reference/' + ('experimental/' if experimental and genome in distinct_references else '') + tail
            elif tail.startswith('genes.gff3'):
                target = root + 'annotations/' + origin + '/' + tail
            elif tail.startswith('prediction.'):
                target = root + 'predictions/' + tail
            elif tail.startswith('augmentation.'):
                target = root + 'training/' + tail
            elif tail.startswith('studies/'):
                target = root + tail
            else:
                target = root + 'provenance/' + origin + '/' + tail
        else:
            # Keep all original tables/controls for lossless audit, below catalogues.
            target = 'catalogues/provenance/' + old
        safe(target)
        existing = inventory.get(target)
        if existing and (existing['sha256'], existing['byte_size']) != (row['sha256'], row['byte_size']):
            # Nonidentical references must not overwrite the displayed canonical reference.
            if '/reference/' not in target or not experimental:
                raise ValueError('Migration destination collision: ' + target)
            target = root + 'reference/experimental/' + tail
            existing = inventory.get(target)
        if existing and (existing['sha256'], existing['byte_size']) != (row['sha256'], row['byte_size']):
            raise ValueError('Conflicting duplicate destination')
        inventory.setdefault(target, dict(path=target, byte_size=row['byte_size'], sha256=row['sha256'], source_path=old))
        mapped[old] = target
    return mapped, inventory, groups


def build(release, proof_path, output):
    original_bytes = (release / 'release.json').read_bytes()
    manifest = json.loads(original_bytes)
    proof_bytes = proof_path.read_bytes()
    proof = json.loads(proof_bytes)
    validate_original(manifest, proof, original_bytes)
    if output.exists():
        raise ValueError('Use a fresh migration output; source and original proofs are immutable')
    # BATTER first selects its canonical reference; experimental identical copies deduplicate.
    files = sorted(manifest['files'], key=lambda row: (row['path'].startswith('experimental/'), row['path']))
    mapping, inventory, groups = path_map(files)
    original_index = {r['path']: r for r in files}
    controls = {}
    def generated(path, data):
        controls[path] = data
        inventory[path] = dict(path=path, byte_size=len(data), sha256=digest(data), generated=True)
    generated('catalogues/provenance/original-release.json', original_bytes)
    generated('catalogues/provenance/original-release.complete.json', proof_bytes)
    generated('catalogues/provenance/original-SHA256SUMS.txt', (release / 'SHA256SUMS.txt').read_bytes())
    by_genome = collections.defaultdict(dict)
    for old, target in mapping.items():
        parts = old.split('/')
        if target.startswith('genomes/') and old.endswith('/metadata.json'):
            genome = target.split('/')[2]
            origin = 'experimental' if parts[0] == 'experimental' else 'batter'
            data = (release / old).read_bytes()
            expected = original_index[old]
            if digest(data) != expected['sha256'] or len(data) != expected['byte_size']:
                raise ValueError('Source metadata changed: ' + old)
            by_genome[genome][origin] = json.loads(data)
    def transform(value):
        if isinstance(value, dict): return {k: transform(v) for k, v in value.items()}
        if isinstance(value, list): return [transform(v) for v in value]
        if isinstance(value, str): return mapping.get(value, value)
        return value
    for genome, records in sorted(by_genome.items()):
        root = 'genomes/' + groups.get(genome, 'experimental-only') + '/' + genome + '/'
        metadata = dict(genome_id=genome, group=groups.get(genome, 'experimental-only'),
                        has_experimental='experimental' in records, has_prediction='batter' in records,
                        records=transform(records), provenance={origin: root + 'provenance/' + origin + '/metadata.json' for origin in records})
        generated(root + 'metadata.json', encode(metadata))
        generated(root + 'metadata.tsv', ('genome_id\thas_experimental\thas_prediction\tmetadata_path\n' + genome + '\t' + str(metadata['has_experimental']).lower() + '\t' + str(metadata['has_prediction']).lower() + '\t' + root + 'metadata.json\n').encode())
    mapping_rows = [dict(source_path=old, target_path=new, byte_size=next_row['byte_size'], sha256=next_row['sha256'])
                    for old, new in sorted(mapping.items()) for next_row in [inventory[new]]]
    generated('catalogues/path-mapping.json', encode(dict(schema='bted-v5-path-map-v1', original_manifest_sha256=ORIGINAL_SHA, files=mapping_rows)))
    generated('catalogues/genomes.json', encode([dict(genome_id=g, group=groups.get(g, 'experimental-only'),
              has_experimental='experimental' in r, has_prediction='batter' in r,
              metadata_path='genomes/' + groups.get(g, 'experimental-only') + '/' + g + '/metadata.json') for g, r in sorted(by_genome.items())]))
    # Deduplication is permitted only for identical reference bytes and indexes.
    validate_mapping(manifest['files'], mapping_rows, list(inventory.values()))
    new_manifest = dict(schema='bted-genome-first-v5-v1', release_version=VERSION, hf_repo=REPO,
                        original_release_manifest_sha256=ORIGINAL_SHA, original_revision=proof['hf_revision'],
                        original_proof_sha256=digest(proof_bytes), files=sorted(inventory.values(), key=lambda r: r['path']),
                        counts=dict(files=len(inventory) + 2, genomes=len(by_genome), batter_genomes=len(groups)),
                        original_experimental_asset_mapping=manifest['experimental_asset_mapping'])
    manifest_data = encode(new_manifest)
    manifest_sha = digest(manifest_data)
    controls['release.json'] = manifest_data
    controls['SHA256SUMS.txt'] = ''.join('%s  %s\n' % (r['sha256'], r['path']) for r in new_manifest['files']).encode() + (manifest_sha + '  release.json\n').encode()
    output.mkdir(parents=True)
    for path, data in controls.items():
        target = output / 'controls' / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    save(output / 'migration.json', dict(schema='bted-v5-migration-plan-v1', hf_repo=REPO,
        original_proof=proof, original_proof_sha256=digest(proof_bytes), original_manifest_sha256=ORIGINAL_SHA,
        original_file_count=len(manifest['files']), original_files=manifest['files'],
        branch='v05-genome-first-' + manifest_sha[:12], manifest_sha256=manifest_sha,
        manifest=new_manifest, mapping=mapping_rows,
        files=new_manifest['files'] + [dict(path=n, byte_size=len(controls[n]), sha256=digest(controls[n]), generated=True) for n in ('release.json', 'SHA256SUMS.txt')]))
    return manifest_sha


def validate_mapping(original_files, mapping, new_files):
    source = {r['path']: r for r in original_files}
    target = {r['path']: r for r in new_files}
    if len(source) != len(original_files) or len(target) != len(new_files):
        raise ValueError('Duplicate manifest paths')
    if len(mapping) != len(source) or {r['source_path'] for r in mapping} != set(source):
        raise ValueError('Path mapping does not cover every original scientific file')
    destinations = collections.defaultdict(list)
    for row in mapping:
        old, new = safe(row['source_path']), safe(row['target_path'])
        if new not in target or any(row[k] != source[old][k] or row[k] != target[new][k] for k in ('byte_size', 'sha256')):
            raise ValueError('Migration changes content: ' + old)
        destinations[new].append(old)
    for new, originals in destinations.items():
        if len(originals) > 1 and ('/reference/' not in new or not new.endswith(('reference.fa.gz', 'reference.fa.gz.fai', 'reference.fa.gz.gzi'))):
            raise ValueError('Only identical reference/index files may deduplicate')
    if any(not r.get('generated') and r['path'] not in destinations for r in new_files):
        raise ValueError('Unexplained migrated payload')
    children = collections.defaultdict(set)
    for path in target:
        parts = path.split('/')
        for n in range(len(parts)):
            children['/'.join(parts[:n])].add(parts[n])
    if any(len(entries) > 9999 for entries in children.values()):
        raise ValueError('HF directory entry limit exceeded')


def load_plan(root):
    plan = json.loads((root / 'migration.json').read_text())
    manifest_bytes = (root / 'controls/release.json').read_bytes()
    if digest(manifest_bytes) != plan['manifest_sha256'] or json.loads(manifest_bytes) != plan['manifest']:
        raise ValueError('Migration manifest changed')
    original_bytes = (root / 'controls/catalogues/provenance/original-release.json').read_bytes()
    original = json.loads(original_bytes)
    validate_original(original, plan['original_proof'], original_bytes)
    if plan['original_files'] != original['files']:
        raise ValueError('Original inventory changed')
    proof_bytes = (root / 'controls/catalogues/provenance/original-release.complete.json').read_bytes()
    if digest(proof_bytes) != plan['original_proof_sha256'] or json.loads(proof_bytes) != plan['original_proof']:
        raise ValueError('Original full proof changed')
    validate_mapping(plan['original_files'], plan['mapping'], plan['files'])
    expected = plan['manifest']['files'] + [dict(path=n, byte_size=(root / 'controls' / n).stat().st_size,
        sha256=digest((root / 'controls' / n).read_bytes()), generated=True) for n in ('release.json', 'SHA256SUMS.txt')]
    if expected != plan['files'] or len(expected) != plan['manifest']['counts']['files']:
        raise ValueError('Migration file inventory changed')
    if plan['branch'] != 'v05-genome-first-' + plan['manifest_sha256'][:12] or plan['hf_repo'] != REPO:
        raise ValueError('Migration identity changed')
    for row in expected:
        if row.get('generated'):
            data = (root / 'controls' / row['path']).read_bytes()
            if len(data) != row['byte_size'] or digest(data) != row['sha256']:
                raise ValueError('Generated control changed')
    return plan


def hf_context():
    from huggingface_hub import HfApi, get_token
    token = get_token()
    if not token: raise ValueError('HF authentication required on relay host')
    return HfApi(token=token), token


def verify_remote(api, token, rows, revision, root):
    import bted_hf_relay as relay
    from huggingface_hub import hf_hub_download
    result = []
    for start in range(0, len(rows), 500):
        chunk = rows[start:start + 500]
        paths = [VERSION + '/' + r['path'] for r in chunk]
        actual = {item.path: item for item in relay.retry(lambda: api.get_paths_info(REPO, paths=paths, repo_type='dataset', revision=revision), 'migration_metadata')}
        for row, path in zip(chunk, paths):
            item = actual.get(path)
            if item is None or item.size != row['byte_size']:
                raise ValueError('HF migration size mismatch: ' + path)
            lfs = getattr(item, 'lfs', None)
            sha = lfs.get('sha256') if isinstance(lfs, dict) else getattr(lfs, 'sha256', None)
            if sha is None:
                cached = relay.retry(lambda: hf_hub_download(REPO, path, repo_type='dataset', revision=revision, token=token, cache_dir=str(root / 'verify-cache')), 'migration_blob')
                sha = relay.digest(cached)
            if sha != row['sha256']:
                raise ValueError('HF migration SHA mismatch: ' + path)
        result.extend(r['path'] for r in chunk)
        print('Verified', len(result), '/', len(rows), 'at', revision, flush=True)
    return len(result)


def tree_paths(api, revision):
    import bted_hf_relay as relay
    from huggingface_hub import RepoFile
    return {item.path for item in relay.retry(lambda: list(api.list_repo_tree(REPO, repo_type='dataset', revision=revision, recursive=True)), 'migration_tree') if isinstance(item, RepoFile)}


def deletion_scope(obsolete, expected):
    """Collapse only directories that contain no accepted paths."""
    scopes = {}
    allowed = ('v0.3.0/', 'v0.4.0/', VERSION + '/batter/', VERSION + '/experimental/')
    if any(not item.startswith(allowed) for item in obsolete):
        raise ValueError('Unexpected obsolete paths; inspect before expanding cleanup scope')
    protected = set()
    for path in expected:
        parts = path.split('/')
        protected.update('/'.join(parts[:n]) for n in range(1, len(parts) + 1))
    for item in sorted(obsolete):
        safe(item)
        parts = item.split('/')
        for n in range(1, len(parts) + 1):
            prefix = '/'.join(parts[:n])
            if prefix not in protected:
                scopes[prefix] = n < len(parts)
                break
    return [dict(path=prefix, is_folder=folder) for prefix, folder in sorted(scopes.items())]


def publish(root):
    """Prepare independent branch; never changes main."""
    from huggingface_hub import CommitOperationAdd, CommitOperationCopy, CommitOperationDelete
    import bted_hf_relay as relay
    plan = load_plan(root)
    api, token = hf_context()
    branch = plan['branch']
    progress_path = root / 'publish.state.json'
    progress = json.loads(progress_path.read_text()) if progress_path.exists() else None
    if progress is None:
        # An existing unrelated branch is an error, not permission to resume it.
        api.create_branch(REPO, branch=branch, revision=plan['original_proof']['hf_revision'], repo_type='dataset', exist_ok=False)
        parent = api.repo_info(REPO, revision=branch, repo_type='dataset').sha
        progress = dict(branch=branch, manifest_sha256=plan['manifest_sha256'], revision=parent, completed_groups=[], status='copying')
        save(progress_path, progress)
    if progress['manifest_sha256'] != plan['manifest_sha256'] or progress['branch'] != branch:
        raise ValueError('Migration resume identity mismatch')
    if api.repo_info(REPO, revision=branch, repo_type='dataset').sha != progress['revision']:
        raise ValueError('Migration branch changed concurrently; inspect before resuming')
    if progress.get('status') == 'complete':
        proof = json.loads((root / 'migration.complete.json').read_text())
        validate_migration(plan, proof)
        return proof
    grouped = collections.defaultdict(list)
    for row in plan['files']:
        parts = row['path'].split('/')
        grouped[parts[1] if parts[0] == 'genomes' else 'controls'].append(row)
    for group, rows in sorted(grouped.items()):
        if group in progress['completed_groups']: continue
        for start in range(0, len(rows), 800):
            operations = []
            chunk = rows[start:start + 800]
            for row in chunk:
                destination = VERSION + '/' + row['path']
                operations.append(CommitOperationAdd(destination, str(root / 'controls' / row['path'])) if row.get('generated') else
                    CommitOperationCopy(src_path_in_repo=VERSION + '/' + row['source_path'], path_in_repo=destination, src_revision=plan['original_proof']['hf_revision']))
            # A failed response may already have committed. Do not blindly retry commits.
            info = api.create_commit(REPO, repo_type='dataset', revision=branch, parent_commit=progress['revision'], operations=operations,
                                     commit_message='v5 genome layout: ' + group + ' ' + str(start))
            progress['revision'] = info.oid
            save(progress_path, progress)
        verify_remote(api, token, rows, progress['revision'], root)
        progress['completed_groups'].append(group)
        save(progress_path, progress)
    expected = {VERSION + '/' + row['path'] for row in plan['files']} | {'README.md', '.gitattributes'}
    current = tree_paths(api, progress['revision'])
    obsolete = deletion_scope(current - expected, expected)
    # Branch-only cleanup retains history. Main remains on its previous tree.
    for start in range(0, len(obsolete), 800):
        info = api.create_commit(REPO, repo_type='dataset', revision=branch, parent_commit=progress['revision'],
            operations=[CommitOperationDelete(row['path'], is_folder=row['is_folder']) for row in obsolete[start:start+800]], commit_message='v5 migration: remove superseded layout from candidate')
        progress['revision'] = info.oid
        save(progress_path, progress)
    info = api.create_commit(REPO, repo_type='dataset', revision=branch, parent_commit=progress['revision'], operations=[CommitOperationAdd('README.md', io.BytesIO(
        ('# BTED · 最新版 v5\n\nGenome directory: `v0.5.0/genomes/<group>/<genome_id>/`.\nExperimental studies, predictions and training retain their provenance.\nSee v0.5.0/release.json and SHA256SUMS.txt.\n').encode()))], commit_message='Document the complete genome-first v5 release')
    progress['revision'] = info.oid
    save(progress_path, progress)
    count = verify_remote(api, token, plan['files'], info.oid, root)
    if tree_paths(api, info.oid) != expected: raise ValueError('Candidate tree differs from accepted migration inventory')
    proof = dict(schema='bted-v5-migration-proof-v1', status='complete', hf_repo=REPO, hf_branch=branch,
                 hf_revision=info.oid, hf_sha256_verified=True, hf_file_count=count,
                 release_manifest_sha256=plan['manifest_sha256'], original_release_manifest_sha256=ORIGINAL_SHA,
                 original_proof_sha256=plan['original_proof_sha256'], original_revision=plan['original_proof']['hf_revision'],
                 mapping_sha256=digest((root / 'controls/catalogues/path-mapping.json').read_bytes()))
    save(root / 'migration.complete.json', proof)
    progress['status'] = 'complete'
    save(progress_path, progress)
    return proof


def validate_migration(plan, proof):
    if (proof.get('status') != 'complete' or proof.get('hf_sha256_verified') is not True
            or proof.get('hf_repo') != REPO or proof.get('hf_branch') != plan['branch']
            or proof.get('release_manifest_sha256') != plan['manifest_sha256']
            or proof.get('original_proof_sha256') != plan['original_proof_sha256']
            or proof.get('original_revision') != plan['original_proof']['hf_revision']
            or proof.get('original_release_manifest_sha256') != ORIGINAL_SHA
            or proof.get('hf_file_count') != len(plan['files'])
            or proof.get('mapping_sha256') != next(r['sha256'] for r in plan['files'] if r['path'] == 'catalogues/path-mapping.json')
            or not re.fullmatch('[0-9a-f]{40}', proof.get('hf_revision', ''))):
        raise ValueError('Migration proof does not match full inventory')


def snapshot_migration(snapshot):
    migration = snapshot.get('migration')
    if migration is None: return None
    plan, proof = migration['plan'], migration['proof']
    validate_migration(plan, proof)
    if plan['original_proof'] != snapshot.get('complete_release_proof') or digest(encode(plan['manifest'])) != plan['manifest_sha256']:
        raise ValueError('Migration is not linked to the verified original release')
    original = {}
    for group in snapshot['groups']:
        if group['envelope']['group'] == 'release-controls': continue
        prefix = group['envelope']['hf_destination_prefix'][len(VERSION) + 1:]
        for row in group['payload']:
            original[prefix + row['name']] = dict(path=prefix + row['name'], byte_size=row['bytes'], sha256=row['sha256'])
    if {r['path']: r for r in plan['original_files']} != original:
        raise ValueError('Migration original inventory differs from verified batch receipts')
    validate_mapping(plan['original_files'], plan['mapping'], plan['files'])
    final = migration.get('main_proof')
    if final:
        if (final.get('status') != 'complete' or final.get('hf_repo') != REPO or final.get('hf_sha256_verified') is not True
                or final.get('release_manifest_sha256') != plan['manifest_sha256']
                or final.get('migration_revision') != proof['hf_revision'] or final.get('original_proof_sha256') != plan['original_proof_sha256']
                or final.get('hf_file_count') != len(plan['files']) or not re.fullmatch('[0-9a-f]{40}', final.get('hf_revision', ''))):
            raise ValueError('Final main proof does not match verified migration')
    return migration


def effective_revision(migration):
    return migration.get('main_proof', migration['proof'])['hf_revision']


def merge_tree(root, repo_url, parent, source, branch, environment=None):
    """Create an ordinary merge commit with the verified tree, without checkout/LFS downloads."""
    bare = root / 'history.git'
    if not bare.exists(): subprocess.run(['git', 'init', '--bare', str(bare)], check=True, capture_output=True)
    def git(*args):
        return subprocess.run(['git', '--git-dir=' + str(bare), *args], env=environment,
                              check=True, capture_output=True, text=True).stdout.strip()
    git('fetch', '--no-tags', repo_url, 'main', branch)
    git('cat-file', '-e', parent + '^{commit}')
    git('cat-file', '-e', source + '^{commit}')
    tree = git('rev-parse', source + '^{tree}')
    merged = git('-c', 'user.name=BTED release', '-c', 'user.email=bted-release@users.noreply.huggingface.co',
                 'commit-tree', tree, '-p', parent, '-p', source, '-m', 'Publish verified genome-first v5; retain release history')
    if not re.fullmatch('[0-9a-f]{40}', merged): raise ValueError('Invalid Git merge identity')
    if git('rev-parse', merged + '^{tree}') != tree: raise ValueError('Merge changed the verified candidate tree')
    return merged


def git_environment(root, api, token):
    # The token stays on the receiver. It is never put into a URL or command output.
    askpass = root / 'hf-askpass.sh'
    askpass.write_text('#!/bin/sh\ncase "$1" in *Username*) printf "%s" "$BTED_HF_GIT_USER" ;; *) printf "%s" "$BTED_HF_GIT_TOKEN" ;; esac\n')
    askpass.chmod(0o700)
    return dict(os.environ, GIT_ASKPASS=str(askpass.resolve()), GIT_TERMINAL_PROMPT='0', GIT_LFS_SKIP_SMUDGE='1',
                BTED_HF_GIT_USER=api.whoami()['name'], BTED_HF_GIT_TOKEN=token)


def promote(root, acceptance):
    """Atomically fast-forward main to an ordinary merge; no history rewriting."""
    plan = load_plan(root)
    proof = json.loads((root / 'migration.complete.json').read_text())
    validate_migration(plan, proof)
    accepted = json.loads(acceptance.read_text())
    required = ('head_verified', 'range_verified', 'download_sha256_verified', 'unified_directory_verified',
                'filters_verified', 'legacy_redirects_verified', 'jbrowse_verified', 'no_local_fallback_verified')
    if (accepted.get('status') != 'verified_complete_preview' or accepted.get('hf_revision') != proof['hf_revision']
            or accepted.get('release_manifest_sha256') != plan['manifest_sha256'] or any(accepted.get(k) is not True for k in required)):
        raise ValueError('Complete migrated website/browser acceptance required before main cleanup')
    api, token = hf_context()
    expected = {VERSION + '/' + r['path'] for r in plan['files']} | {'README.md', '.gitattributes'}
    if tree_paths(api, proof['hf_revision']) != expected: raise ValueError('Candidate layout is not final')
    verify_remote(api, token, plan['files'], proof['hf_revision'], root)
    state_path = root / 'main.state.json'
    if state_path.exists():
        state = json.loads(state_path.read_text())
        if state['manifest_sha256'] != plan['manifest_sha256'] or state['source_revision'] != proof['hf_revision']:
            raise ValueError('Main resume identity mismatch')
    else:
        parent = api.repo_info(REPO, repo_type='dataset', revision='main').sha
        state = dict(main_before=parent, revision=parent, source_revision=proof['hf_revision'], manifest_sha256=plan['manifest_sha256'],
                     delete_paths=deletion_scope(tree_paths(api, parent) - expected, expected))
        save(state_path, state)
    actual = api.repo_info(REPO, repo_type='dataset', revision='main').sha
    if actual not in (state['main_before'], state.get('merge_commit')):
        raise ValueError('Main changed concurrently; inspect before resuming')
    if actual == state['main_before']:
        environment = git_environment(root, api, token)
        url = 'https://huggingface.co/datasets/' + REPO
        if 'merge_commit' not in state:
            state['merge_commit'] = merge_tree(root, url, state['main_before'], proof['hf_revision'], proof['hf_branch'], environment)
            save(state_path, state)
        # Non-force push rejects a concurrent main change. Source history is an ancestor.
        subprocess.run(['git', '--git-dir=' + str(root / 'history.git'), 'push', url, state['merge_commit'] + ':refs/heads/main'],
                       env=environment, check=True)
        state['revision'] = state['merge_commit']
        save(state_path, state)
    else:
        # A lost push response is resolved from the exact live commit, never replayed blindly.
        state['revision'] = actual
        save(state_path, state)
    verify_remote(api, token, plan['files'], state['revision'], root)
    if tree_paths(api, state['revision']) != expected: raise ValueError('Final main layout differs')
    result = dict(status='complete', hf_repo=REPO, hf_revision=state['revision'], main_before=state['main_before'],
                  migration_revision=proof['hf_revision'], release_manifest_sha256=plan['manifest_sha256'],
                  original_revision=plan['original_proof']['hf_revision'], original_proof_sha256=plan['original_proof_sha256'],
                  deleted_paths=state['delete_paths'], hf_sha256_verified=True, hf_file_count=len(plan['files']),
                  preview_acceptance_sha256=digest(acceptance.read_bytes()))
    save(root / 'main.complete.json', result)
    # Branch removal is deferred until final main download/JBrowse acceptance.
    return result


def finalize(root, acceptance):
    """Preserve fixed commits using tags, then remove only owned temporary branches."""
    plan = load_plan(root)
    migration = json.loads((root / 'migration.complete.json').read_text())
    validate_migration(plan, migration)
    final = json.loads((root / 'main.complete.json').read_text())
    accepted = json.loads(acceptance.read_text())
    required = ('head_verified', 'range_verified', 'download_sha256_verified', 'unified_directory_verified',
                'filters_verified', 'legacy_redirects_verified', 'jbrowse_verified', 'no_local_fallback_verified')
    if (accepted.get('status') != 'verified_complete_preview' or accepted.get('hf_revision') != final['hf_revision']
            or accepted.get('release_manifest_sha256') != plan['manifest_sha256'] or any(accepted.get(k) is not True for k in required)):
        raise ValueError('Final main preview acceptance required to close release')
    api, token = hf_context()
    if api.repo_info(REPO, repo_type='dataset', revision='main').sha != final['hf_revision']:
        raise ValueError('Main changed before final acceptance')
    expected = {VERSION + '/' + r['path'] for r in plan['files']} | {'README.md', '.gitattributes'}
    if tree_paths(api, final['hf_revision']) != expected: raise ValueError('Final tree differs')
    verify_remote(api, token, plan['files'], final['hf_revision'], root)
    references = dict(api_source=('v0.5.0-original-' + ORIGINAL_SHA[:12], plan['original_proof']['hf_revision']),
                      migration=('v0.5.0-genome-first-' + plan['manifest_sha256'][:12], migration['hf_revision']))
    for tag, revision in references.values():
        api.create_tag(REPO, tag=tag, revision=revision, repo_type='dataset', exist_ok=True)
        if api.repo_info(REPO, repo_type='dataset', revision=tag).sha != revision:
            raise ValueError('Archive tag differs from the verified fixed commit')
    removed = []
    refs = api.list_repo_refs(REPO, repo_type='dataset')
    branches = {item.name: item.target_commit for item in refs.branches}
    for branch, revision in [(plan['branch'], migration['hf_revision']), (plan['original_proof']['hf_branch'], plan['original_proof']['hf_revision'])]:
        if branch not in branches: continue
        if branches[branch] != revision: raise ValueError('Temporary branch changed before cleanup')
        api.delete_branch(REPO, branch=branch, repo_type='dataset')
        removed.append(branch)
    record = dict(status='complete', final_proof=final, preserved_tags=references, removed_branches=removed,
                  final_preview_acceptance_sha256=digest(acceptance.read_bytes()))
    save(root / 'release.final.complete.json', record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('build')
    p.add_argument('--release', type=Path, required=True)
    p.add_argument('--original-proof', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    for name in ('publish', 'promote', 'finalize'):
        p = sub.add_parser(name)
        p.add_argument('--root', type=Path, required=True)
        if name in ('promote', 'finalize'): p.add_argument('--acceptance', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'build': print(build(args.release, args.original_proof, args.output))
    elif args.command == 'publish': print(json.dumps(publish(args.root)))
    elif args.command == 'promote': print(json.dumps(promote(args.root, args.acceptance)))
    else: print(json.dumps(finalize(args.root, args.acceptance)))


if __name__ == '__main__': main()
