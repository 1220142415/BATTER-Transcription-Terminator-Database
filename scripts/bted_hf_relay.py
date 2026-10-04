#!/usr/bin/env python3
"""Sequential cu10 -> private SSH inbox -> verified HF preparation branch relay.

Only temporary receiver data is deleted, after immutable HF SHA-256 proof.
Source release, receipts, old HF versions and main are preserved.
"""
import argparse
import csv
import datetime
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import tarfile
import time
import uuid
from pathlib import Path, PurePosixPath

VERSION = 'v0.5.0'
REPO = 'liurulong/terminator'
RELEASE_SHA = 'f5c55e9f129fd66722e2b18ca2e146ee189bf8fec44fa39ce239225c95852265'
BRANCH = 'v05-preparation-' + RELEASE_SHA[:12]
DEFAULT_REMOTE = '/home/sshlogin/bted_v05'
PRIVATE_MODE = 0o700 if os.name != 'nt' else 0o777


class RemoteTransportError(RuntimeError):
    """Temporary SSH/SFTP loss; durable state must be resumed, not abandoned."""


def reconnect(operation, label, seconds=60):
    while True:
        try:
            return operation()
        except RemoteTransportError:
            emit('remote_reconnect', operation=label, wait_seconds=seconds)
            time.sleep(seconds)


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def emit(event, **fields):
    print(json.dumps(dict(event=event, at=stamp(), **fields)), flush=True)


def digest(path):
    h = hashlib.sha256()
    with open(str(path), 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def prefix_digest(path, size):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        while size:
            block = f.read(min(1024 * 1024, size))
            if not block:
                raise ValueError('Local file is shorter than remote prefix')
            h.update(block)
            size -= len(block)
    return h.hexdigest()


def save(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w', encoding='utf-8') as handle:
        handle.write(json.dumps(doc, indent=2) + '\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(str(tmp), 0o600)
    os.replace(str(tmp), str(path))


def transport_identity(e):
    return hashlib.sha256(json.dumps(e, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def prepare_parts(archive, e, directory, chunk_bytes):
    """Legacy first tar stays compatible; new batches use checksum-addressed parts."""
    if e.get('transport') != 'tar_chunks':
        return [(archive, dict(name='payload.tar', bytes=e['archive_byte_size'], sha256=e['archive_sha256']))]
    if chunk_bytes < 1024 * 1024:
        raise ValueError('Transport chunks must be at least 1 MiB')
    parts_dir = directory / 'parts'
    parts_dir.mkdir(parents=True, exist_ok=True)
    expected = e.get('archive_parts')
    if expected and all((parts_dir / p['name']).is_file() and (parts_dir / p['name']).stat().st_size == p['bytes']
                        and digest(parts_dir / p['name']) == p['sha256'] for p in expected):
        return [(parts_dir / p['name'], p) for p in expected]
    if not archive.is_file() or digest(archive) != e['archive_sha256']:
        raise ValueError('Source archive missing or changed before splitting')
    parts = []
    with archive.open('rb') as src:
        index = 0
        while True:
            first = src.read(min(1024 * 1024, chunk_bytes))
            if not first:
                break
            name = 'part-%05d' % index
            path = parts_dir / name
            tmp = path.with_suffix('.partial')
            h = hashlib.sha256()
            size = 0
            with tmp.open('wb') as dst:
                block = first
                while block:
                    dst.write(block)
                    h.update(block)
                    size += len(block)
                    block = src.read(min(1024 * 1024, chunk_bytes - size)) if size < chunk_bytes else b''
            os.replace(str(tmp), str(path))
            parts.append(dict(name=name, bytes=size, sha256=h.hexdigest()))
            index += 1
    if expected and expected != parts:
        raise ValueError('Regenerated transport parts differ from persisted identity')
    e.update(archive_parts=parts, ready_required=True, transport_chunk_bytes=chunk_bytes)
    save(directory / 'transport.json', e)
    return [(parts_dir / p['name'], p) for p in parts]


def assemble_parts(stage, e):
    if e.get('ready_required'):
        ready = json.loads((stage / 'transport.ready.json').read_text())
        for key in ('upload_id', 'manifest_sha256', 'archive_sha256'):
            if ready.get(key) != e[key]:
                raise ValueError('Transport READY identity mismatch')
        if ready.get('transport_identity') != transport_identity(e):
            raise ValueError('Transport READY belongs to different metadata')
    archive = stage / 'payload.tar'
    if e.get('transport') != 'tar_chunks':
        return archive
    parts = e['archive_parts']
    if not parts or sum(p['bytes'] for p in parts) != e['archive_byte_size']:
        raise ValueError('Transport part sizes differ from archive')
    tmp = stage / 'payload.tar.partial'
    complete_hash = hashlib.sha256()
    with tmp.open('wb') as dst:
        for index, part in enumerate(parts):
            if part['name'] != 'part-%05d' % index:
                raise ValueError('Invalid transport part order/name')
            src = stage / part['name']
            if src.is_symlink() or src.stat().st_size != part['bytes']:
                raise ValueError('Missing or invalid transport part')
            part_hash = hashlib.sha256()
            with src.open('rb') as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b''):
                    dst.write(block)
                    part_hash.update(block)
                    complete_hash.update(block)
            if part_hash.hexdigest() != part['sha256']:
                raise ValueError('Transport part checksum mismatch: ' + part['name'])
    if complete_hash.hexdigest() != e['archive_sha256']:
        raise ValueError('Reassembled archive SHA-256 mismatch')
    os.replace(str(tmp), str(archive))
    return archive


def safe_name(name):
    p = PurePosixPath(name)
    if (not name or p.is_absolute() or '..' in p.parts or p.as_posix() != name
            or any(c in name for c in '\\\t\r\n:') or name.startswith('.')):
        raise ValueError('Unsafe payload name: ' + name)
    return name


def manifest_text(rows):
    return ''.join('%s\t%d\t%s\n' % (r['name'], r['bytes'], r['sha256']) for r in rows)


def parse_manifest(content):
    rows = []
    names = set()
    for name, size, sha in csv.reader(io.StringIO(content.decode('utf-8')), delimiter='\t'):
        safe_name(name)
        if name in names or not re.fullmatch('[0-9a-f]{64}', sha) or int(size) < 0:
            raise ValueError('Invalid or duplicate manifest row')
        names.add(name)
        rows.append({'name': name, 'bytes': int(size), 'sha256': sha})
    if not rows:
        raise ValueError('Empty manifest')
    return rows


def validate_envelope(e):
    if e['release_manifest_sha256'] != RELEASE_SHA or e['hf_repo'] != REPO:
        raise ValueError('Unknown release/repository')
    if not re.fullmatch('[0-9a-f]{32}', e['upload_id']):
        raise ValueError('Invalid upload ID')
    group = e.get('group') or 'batter-' + (e.get('batch') or '')
    if re.fullmatch('batter-[0-9]{3}', group):
        batch = group[7:]
        if int(batch) > 42 or e['batch'] != batch or e['hf_destination_prefix'] != VERSION + '/batter/batches/' + batch + '/':
            raise ValueError('Invalid BATTER destination')
        if e['genome_count'] != (904 if batch == '042' else 1000):
            raise ValueError('Unexpected genome count')
    elif group not in ('experimental', 'catalogues', 'release-controls') or e['hf_destination_prefix'] != VERSION + '/':
        raise ValueError('Invalid release group')
    for key in ('manifest_sha256', 'archive_sha256'):
        if not re.fullmatch('[0-9a-f]{64}', e[key]):
            raise ValueError('Invalid digest')
    return group


def repo_path(e, name):
    safe_name(name)
    group = validate_envelope(e)
    if group == 'release-controls' and name == 'README.md':
        return name
    if group == 'experimental' and not name.startswith('experimental/'):
        raise ValueError('Experimental file outside collection')
    if group == 'catalogues' and name not in ('batter/genomes.tsv', 'batter/held_genomes.tsv', 'batter/prediction_end_corrections.tsv'):
        raise ValueError('Unexpected catalogue')
    if group == 'release-controls' and name not in ('README.md', 'release.json', 'SHA256SUMS.txt'):
        raise ValueError('Unexpected control file')
    return e['hf_destination_prefix'] + name


def extract_verified(archive_path, target, e):
    """Reject links/traversal/duplicates; hash before replacing any payload file."""
    if archive_path.stat().st_size != e['archive_byte_size'] or digest(archive_path) != e['archive_sha256']:
        raise ValueError('Transport archive SHA-256/size mismatch')
    with tarfile.open(str(archive_path), 'r') as tar:
        members = tar.getmembers()
        inventory = {}
        for member in members:
            safe_name(member.name)
            if not member.isfile() or member.name in inventory:
                raise ValueError('Transport contains link/directory/duplicate')
            inventory[member.name] = member
        manifest = tar.extractfile(inventory['manifest.tsv']).read()
        if hashlib.sha256(manifest).hexdigest() != e['manifest_sha256']:
            raise ValueError('Manifest digest mismatch')
        rows = parse_manifest(manifest)
        meta = json.loads(tar.extractfile(inventory['upload_metadata.json']).read())
        for key in ('upload_id', 'manifest_sha256'):
            if meta[key] != e[key]:
                raise ValueError('Package identity mismatch')
        if set(inventory) != {r['name'] for r in rows} | {'manifest.tsv', 'upload_metadata.json'} or len(rows) != e['payload_file_count']:
            raise ValueError('Package inventory mismatch')
        target.mkdir(parents=True, exist_ok=True, mode=PRIVATE_MODE)
        for row in rows:
            repo_path(e, row['name'])
            member = inventory[row['name']]
            if member.size != row['bytes']:
                raise ValueError('Payload size mismatch')
            path = target / row['name']
            if any(p.is_symlink() for p in [path] + list(path.parents)):
                raise ValueError('Symlink in extraction path')
            path.parent.mkdir(parents=True, exist_ok=True, mode=PRIVATE_MODE)
            tmp = path.with_name(path.name + '.partial')
            h = hashlib.sha256()
            with tar.extractfile(member) as src, tmp.open('wb') as dst:
                for block in iter(lambda: src.read(1024 * 1024), b''):
                    h.update(block)
                    dst.write(block)
            if h.hexdigest() != row['sha256']:
                tmp.unlink()
                raise ValueError('Payload SHA-256 mismatch: ' + row['name'])
            os.replace(str(tmp), str(path))
    group = validate_envelope(e)
    if group.startswith('batter-'):
        folders = {r['name'].split('/')[1] for r in rows if r['name'].startswith('genomes/')}
        if len(folders) != e['genome_count']:
            raise ValueError('Genome directory count mismatch')
        with (target / 'genomes.tsv').open(encoding='utf-8') as h:
            if len(list(csv.DictReader(h, delimiter='\t'))) != e['genome_count']:
                raise ValueError('Genome catalogue count mismatch')
    return rows


def check_indexes(root, rows):
    import pysam
    fasta_count = tabix_count = 0
    names = {r['name'] for r in rows}
    for name in sorted(names):
        if name.endswith('reference.fa.gz'):
            if name + '.fai' not in names or name + '.gzi' not in names:
                raise ValueError('Missing reference indexes')
            with pysam.FastaFile(str(root / name)) as fa:
                if not fa.references:
                    raise ValueError('Empty reference')
                for contig in fa.references:
                    length = fa.get_reference_length(contig)
                    if length < 1 or len(fa.fetch(contig, 0, 1)) != 1 or len(fa.fetch(contig, length - 1, length)) != 1:
                        raise ValueError('FASTA random access failed')
            fasta_count += 1
        elif name.endswith('.tbi'):
            with pysam.TabixFile(str(root / name[:-4])) as track:
                for contig in track.contigs:
                    next(track.fetch(contig, 0, 1), None)
            tabix_count += 1
    return dict(fasta_indexes=fasta_count, tabix_indexes=tabix_count)


def retry(operation, label, attempts=12):
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as error:
            response = getattr(error, 'response', None)
            status = getattr(response, 'status_code', None)
            if status in (400, 401, 403, 404, 422) or attempt == attempts - 1:
                raise
            delay = min(300, 10 * 2 ** min(attempt, 5))
            if status == 429:
                headers = getattr(response, 'headers', {})
                try:
                    delay = max(delay, min(3600, int(headers.get('retry-after', 0))))
                except ValueError:
                    pass
                reset = re.search(r'(?:^|;)t=([0-9]+)', headers.get('ratelimit', '').replace(' ', ''))
                if reset:
                    delay = max(delay, min(3600, int(reset.group(1)) + 3))
            emit('network_retry', operation=label, status=status, attempt=attempt + 1, wait_seconds=delay)
            time.sleep(delay)


def hf_verify(api, token, e, rows, revision, cache):
    from huggingface_hub import hf_hub_download
    paths = [repo_path(e, r['name']) for r in rows]
    actual = {}
    for offset in range(0, len(paths), 400):
        requested = paths[offset:offset + 400]
        info = retry(lambda: api.get_paths_info(REPO, paths=requested, repo_type='dataset', revision=revision), 'metadata')
        actual.update({r.path: r for r in info})
    verified = set()
    for row, path in zip(rows, paths):
        remote = actual.get(path)
        if remote is None or remote.size != row['bytes']:
            continue
        lfs = getattr(remote, 'lfs', None)
        sha = lfs.get('sha256') if isinstance(lfs, dict) else getattr(lfs, 'sha256', None)
        if sha:
            if sha == row['sha256']:
                verified.add(row['name'])
        else:
            downloaded = retry(lambda: hf_hub_download(REPO, path, repo_type='dataset', revision=revision,
                                                       token=token, cache_dir=str(cache)), 'download_blob')
            if digest(downloaded) == row['sha256']:
                verified.add(row['name'])
    return verified


def setup_hf(api, token, root):
    from huggingface_hub import CommitOperationAdd, hf_hub_download
    from huggingface_hub.utils import EntryNotFoundError
    retry(lambda: api.create_branch(REPO, branch=BRANCH, repo_type='dataset', exist_ok=True), 'branch')
    parent = retry(lambda: api.repo_info(REPO, repo_type='dataset', revision=BRANCH).sha, 'revision')
    try:
        p = retry(lambda: hf_hub_download(REPO, '.gitattributes', repo_type='dataset', revision=parent,
                                         token=token, cache_dir=str(root / 'state' / 'attr-cache')), 'attributes')
        attrs = Path(p).read_text(encoding='utf-8')
    except EntryNotFoundError:
        attrs = ''
    rule = VERSION + '/** filter=lfs diff=lfs merge=lfs -text'
    if rule not in attrs.splitlines():
        content = (attrs.rstrip('\n') + '\n' + rule + '\n').encode('utf-8')
        retry(lambda: api.create_commit(REPO, repo_type='dataset', revision=BRANCH, parent_commit=parent,
                                        commit_message='Store v0.5 assets with verifiable LFS SHA-256',
                                        operations=[CommitOperationAdd('.gitattributes', content)]), 'attributes_commit')
    return parent


def proof_matches(proof, e):
    for key in ('upload_id', 'manifest_sha256', 'release_manifest_sha256', 'hf_repo', 'hf_destination_prefix'):
        if proof.get(key) != e.get(key):
            raise ValueError('HF receipt identity mismatch: ' + key)
    if (proof.get('status') != 'complete' or not proof.get('hf_sha256_verified')
            or not re.fullmatch('[0-9a-f]{40}', proof.get('hf_revision', ''))
            or proof.get('hf_file_count') != e['payload_file_count']):
        raise ValueError('Incomplete HF proof')


def clean_stage(root, stage, e, proof):
    proof_matches(proof, e)
    allowed = root.resolve() / 'inbox' / (validate_envelope(e) + '.' + e['upload_id'])
    if stage.is_symlink() or stage.resolve() != allowed:
        raise ValueError('Cleanup path outside exact batch inbox')
    if stage.exists():
        shutil.rmtree(str(stage))


def receive(args):
    import fcntl
    root = args.root.resolve()
    e = json.loads(args.envelope.read_text(encoding='utf-8'))
    group = validate_envelope(e)
    stage = root / 'inbox' / (group + '.' + e['upload_id'])
    if args.envelope.resolve() != stage / 'transport.json':
        raise ValueError('Envelope must reside in its private batch inbox')
    # Xet's transfer cache also belongs to this batch and is removed with scratch.
    os.environ['HF_XET_CACHE'] = str(stage / 'xet-cache')
    os.environ['HF_HUB_DISABLE_PROGRESS_BARS'] = '1'
    from huggingface_hub import HfApi, CommitOperationAdd
    os.umask(0o077)
    for name in ('state', 'receipts', 'logs'):
        (root / name).mkdir(exist_ok=True, mode=0o700)
    with (root / 'state' / 'receiver.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state_path = root / 'state' / (group + '.json')
        receipt_path = root / 'receipts' / (group + '.' + e['upload_id'] + '.complete.json')
        cache = stage / 'hf-cache'
        token = (Path.home() / '.config/bted_hf/token').read_text().strip()
        api = HfApi(token=token)
        state = dict(group=group, upload_id=e['upload_id'], manifest_sha256=e['manifest_sha256'],
                     release_manifest_sha256=RELEASE_SHA, hf_repo=REPO, branch=BRANCH, started_at=stamp(), pid=os.getpid())
        try:
            save(root / 'state' / (group + '.transport.json'), e)
            if receipt_path.exists():
                proof = json.loads(receipt_path.read_text())
                proof_matches(proof, e)
                # Persistent SHA proof already exists; cleaning a leftover inbox is idempotent.
                clean_stage(root, stage, e, proof)
                proof.update(remote_scratch_deleted=True, cleanup_completed_at=stamp())
                save(receipt_path, proof)
                return proof
            state.update(status='validating_archive')
            save(state_path, state)
            payload = stage / 'unpacked'
            rows = extract_verified(assemble_parts(stage, e), payload, e)
            indexes = check_indexes(payload, rows)
            save(root / 'state' / (group + '.manifest.json'), rows)
            emit('remote_payload_verified', group=group, files=len(rows), **indexes)
            setup_hf(api, token, root)
            revision = retry(lambda: api.repo_info(REPO, repo_type='dataset', revision=BRANCH).sha, 'revision')
            verified = hf_verify(api, token, e, rows, revision, cache)
            pending = [r for r in rows if r['name'] not in verified]
            state.update(status='publishing', total_files=len(rows), verified_files=len(verified), indexes=indexes)
            save(state_path, state)
            for offset in range(0, len(pending), args.chunk_size):
                chunk = pending[offset:offset + args.chunk_size]
                def commit_chunk():
                    parent = api.repo_info(REPO, repo_type='dataset', revision=BRANCH).sha
                    missing = [r for r in chunk if r['name'] not in hf_verify(api, token, e, chunk, parent, cache)]
                    if not missing:
                        return parent
                    result = api.create_commit(REPO, repo_type='dataset', revision=BRANCH, parent_commit=parent,
                                               commit_message='BTED v0.5 %s %d/%d' % (group, offset, len(pending)),
                                               operations=[CommitOperationAdd(repo_path(e, r['name']), str(payload / r['name'])) for r in missing])
                    return result.oid
                revision = retry(commit_chunk, 'payload_commit')
                checked = hf_verify(api, token, e, chunk, revision, cache)
                if checked != {r['name'] for r in chunk}:
                    raise ValueError('Committed chunk failed immutable SHA-256 verification')
                verified.update(checked)
                state.update(verified_files=len(verified), hf_revision=revision, updated_at=stamp())
                save(state_path, state)
                emit('hf_progress', group=group, verified_files=len(verified), total_files=len(rows), revision=revision)
            revision = retry(lambda: api.repo_info(REPO, repo_type='dataset', revision=BRANCH).sha, 'final_revision')
            if hf_verify(api, token, e, rows, revision, cache) != {r['name'] for r in rows}:
                raise ValueError('Final immutable HF batch SHA verification failed')
            proof = {key: e[key] for key in ('upload_id', 'manifest_sha256', 'release_manifest_sha256', 'hf_repo', 'hf_destination_prefix')}
            proof.update(status='complete', group=group, batch=e.get('batch'), genome_count=e.get('genome_count', 0),
                         archive_sha256=e['archive_sha256'], hf_branch=BRANCH, hf_revision=revision,
                         hf_file_count=len(rows), hf_sha256_verified=True, completed_at=stamp(), indexes=indexes,
                         remote_scratch_deleted=False, promoted_main=False, old_versions_deleted=False)
            # Durable proof precedes deletion. Receipts/state/logs remain outside scratch.
            save(receipt_path, proof)
            clean_stage(root, stage, e, proof)
            proof.update(remote_scratch_deleted=True, cleanup_completed_at=stamp())
            save(receipt_path, proof)
            state.update(status='complete', verified_files=len(rows), hf_revision=revision, remote_scratch_deleted=True)
            save(state_path, state)
            emit('batch_complete_and_cleaned', **proof)
            return proof
        except Exception as error:
            state.update(status='failed', error_type=type(error).__name__, updated_at=stamp())
            save(state_path, state)
            failure = dict(state, status='failed', error=str(error))
            save(root / 'receipts' / (group + '.' + e['upload_id'] + '.failed.json'), failure)
            emit('batch_failed_retained', group=group, error_type=type(error).__name__)
            raise


def finalize(args):
    """Verify all groups at one final immutable revision, without publishing main."""
    import fcntl
    from huggingface_hub import HfApi
    root = args.root.resolve()
    os.umask(0o077)
    with (root / 'state' / 'receiver.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        token = (Path.home() / '.config/bted_hf/token').read_text().strip()
        api = HfApi(token=token)
        revision = retry(lambda: api.repo_info(REPO, repo_type='dataset', revision=BRANCH).sha, 'final_release_revision')
        total = 0
        groups = ['batter-%03d' % n for n in range(43)] + ['experimental', 'catalogues', 'release-controls']
        state_path = root / 'state' / 'final-verification.json'
        state = dict(status='verifying', hf_revision=revision, release_manifest_sha256=RELEASE_SHA,
                     completed_groups=[], started_at=stamp())
        save(state_path, state)
        cache = root / 'state' / 'final-cache'
        for group in groups:
            e = json.loads((root / 'state' / (group + '.transport.json')).read_text())
            receipt = json.loads((root / 'receipts' / (group + '.' + e['upload_id'] + '.complete.json')).read_text())
            proof_matches(receipt, e)
            if not receipt.get('remote_scratch_deleted'):
                raise ValueError('Uncleaned batch during final verification')
            rows = json.loads((root / 'state' / (group + '.manifest.json')).read_text())
            if hashlib.sha256(manifest_text(rows).encode('utf-8')).hexdigest() != e['manifest_sha256']:
                raise ValueError('Saved verification manifest changed')
            if hf_verify(api, token, e, rows, revision, cache) != {r['name'] for r in rows}:
                raise ValueError('Whole-release fixed revision SHA mismatch: ' + group)
            total += len(rows)
            state['completed_groups'].append(group)
            state['verified_files'] = total
            save(state_path, state)
            emit('final_group_verified', group=group, revision=revision, verified_files=total)
        if total != 371963:
            raise ValueError('Whole release file count differs from acceptance')
        proof = dict(status='complete', hf_repo=REPO, hf_branch=BRANCH, hf_revision=revision,
                     release_manifest_sha256=RELEASE_SHA, hf_sha256_verified=True, hf_file_count=total,
                     genome_count=42904, completed_groups=groups, completed_at=stamp(),
                     main_promoted=False, old_versions_deleted=False)
        save(root / 'receipts' / 'release.complete.json', proof)
        state.update(status='complete', completed_at=stamp())
        save(state_path, state)
        if cache.exists():
            shutil.rmtree(str(cache))
        emit('whole_release_verified', **proof)
        return proof


def receiver_snapshot(root, group, upload_id, manifest_sha256, pid_hint=None):
    if (group not in ['batter-%03d' % n for n in range(43)] + ['experimental', 'catalogues', 'release-controls']
            or not re.fullmatch('[0-9a-f]{32}', upload_id) or not re.fullmatch('[0-9a-f]{64}', manifest_sha256)):
        raise ValueError('Invalid receiver status identity')
    stage = root / 'inbox' / (group + '.' + upload_id)
    receipt_root = root / 'receipts'
    out = dict(status='idle', stage_exists=stage.exists(), active=False, pid=None)
    for suffix, status in (('complete', 'complete'), ('failed', 'failed')):
        path = receipt_root / (group + '.' + upload_id + '.' + suffix + '.json')
        if path.exists():
            proof = json.loads(path.read_text())
            if proof.get('upload_id') != upload_id or proof.get('manifest_sha256') != manifest_sha256:
                raise ValueError('Receiver receipt identity mismatch')
            out.update(status=status, receipt=proof)
            if status == 'complete':
                break
            break
    candidates = []
    if pid_hint:
        candidates.append(str(pid_hint))
    for filename in (group + '.process.json', group + '.json'):
        p = root / 'state' / filename
        if p.exists():
            state = json.loads(p.read_text())
            if state.get('upload_id') != upload_id or state.get('manifest_sha256') != manifest_sha256:
                raise ValueError('Receiver state belongs to another transaction')
            out['worker_status'] = state.get('status')
            if state.get('pid'):
                candidates.append(str(state['pid']))
    # Covers a lost launch reply or crash between Popen and persisted PID.
    candidates += [p.name for p in Path('/proc').iterdir() if p.name.isdigit()]
    expected_code = str(root / 'code/bted_hf_relay.py')
    expected_envelope = str(stage / 'transport.json')
    for pid in dict.fromkeys(candidates):
        if not pid.isdigit():
            continue
        try:
            argv = (Path('/proc') / pid / 'cmdline').read_bytes().split(b'\0')
            argv = [v.decode('utf-8', errors='replace') for v in argv]
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if expected_code in argv and 'receive' in argv and '--envelope' in argv:
            if argv[argv.index('--envelope') + 1] == expected_envelope:
                out.update(active=True, pid=pid)
                if out['status'] == 'idle':
                    out['status'] = 'running'
                break
    return out


def launch(args):
    """Durably record a detached receiver before returning; repeated launch is safe."""
    import fcntl
    root = args.root.resolve()
    e = json.loads(args.envelope.read_text())
    group = validate_envelope(e)
    stage = root / 'inbox' / (group + '.' + e['upload_id'])
    if args.envelope.resolve() != stage / 'transport.json':
        raise ValueError('Invalid receiver envelope path')
    (root / 'state').mkdir(exist_ok=True)
    with (root / 'state' / (group + '.launch.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = receiver_snapshot(root, group, e['upload_id'], e['manifest_sha256'])
        if current['status'] == 'failed':
            raise ValueError('Receiver has a terminal failed receipt')
        if current['status'] == 'complete' or current['active']:
            return current
        if not (stage / 'transport.ready.json').is_file():
            raise ValueError('Receiver launch requires verified transport READY')
        code = root / 'code/bted_hf_relay.py'
        command = [str(root / 'venv/bin/python'), str(code), 'receive', '--root', str(root),
                   '--envelope', str(stage / 'transport.json'), '--chunk-size', '100']
        with (root / 'logs' / (group + '.log')).open('a') as log:
            child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                     start_new_session=True)
        doc = dict(status='launched', pid=child.pid, upload_id=e['upload_id'], manifest_sha256=e['manifest_sha256'],
                   release_manifest_sha256=RELEASE_SHA, started_at=stamp())
        save(root / 'state' / (group + '.process.json'), doc)
        return dict(status='running', active=True, pid=str(child.pid), stage_exists=True)


def inspect_receiver(args, e, directory):
    hint = directory / 'receiver.json'
    pid = str(json.loads(hint.read_text())['pid']) if hint.exists() else ''
    command = '%s %s status --root %s --group %s --upload-id %s --manifest-sha256 %s' % (
        shlex.quote(args.remote_root + '/venv/bin/python'), shlex.quote(args.remote_root + '/code/bted_hf_relay.py'),
        shlex.quote(args.remote_root), shlex.quote(validate_envelope(e)), e['upload_id'], e['manifest_sha256'])
    if pid.isdigit():
        command += ' --pid ' + pid
    return json.loads(reconnect(lambda: remote_command(args, command), 'receiver_status', args.remote_retry_seconds))


def launch_receiver(args, e, stage, directory):
    command = '%s %s launch --root %s --envelope %s' % (
        shlex.quote(args.remote_root + '/venv/bin/python'), shlex.quote(args.remote_root + '/code/bted_hf_relay.py'),
        shlex.quote(args.remote_root), shlex.quote(stage + '/transport.json'))
    result = json.loads(reconnect(lambda: remote_command(args, command), 'receiver_launch', args.remote_retry_seconds))
    if result.get('pid'):
        save(directory / 'receiver.json', dict(pid=str(result['pid']), stage=stage, started_at=stamp()))
    return result


def process_group(args, group, rows, prefix, genomes, summary):
    directory = args.state / group
    directory.mkdir(parents=True, exist_ok=True)
    state_path = directory / 'state.json'
    old = json.loads(state_path.read_text()) if state_path.exists() else {}
    envelope_path = directory / 'transport.json'
    # Preserve identity and check the remote worker/receipt before ANY re-upload.
    if envelope_path.exists():
        e = json.loads(envelope_path.read_text())
        validate_envelope(e)
    else:
        e, _ = make_package(args, group, rows, prefix, genomes)
    stage = args.remote_root + '/inbox/' + group + '.' + e['upload_id']
    state = dict(group=group, upload_id=e['upload_id'], manifest_sha256=e['manifest_sha256'],
                 release_manifest_sha256=RELEASE_SHA, stage=stage, status=old.get('status', 'staging'))
    deadline = time.monotonic() + args.completion_timeout_seconds if args.completion_timeout_seconds else None
    while True:
        snapshot = inspect_receiver(args, e, directory)
        if snapshot['status'] == 'failed':
            raise ValueError('Remote worker reported terminal failure: ' + str(snapshot['receipt'].get('error_type', 'unknown')))
        if snapshot['status'] == 'complete':
            proof = snapshot['receipt']
            proof_matches(proof, e)
            if not proof.get('remote_scratch_deleted'):
                if snapshot['active']:
                    # Receipt was persisted just before cleanup. Let receiver finish it.
                    if deadline and time.monotonic() > deadline:
                        raise TimeoutError('Timed out waiting for receiver cleanup')
                    time.sleep(args.poll_seconds)
                    continue
                # Matching SHA proof permits recovery of an interrupted receiver cleanup.
                code = '''import json,sys
from pathlib import Path
sys.path.insert(0,CODE)
import bted_hf_relay as r
p=Path(RECEIPT)
d=json.loads(p.read_text())
e=json.loads((Path(ROOT)/'state'/TRANSPORT).read_text())
r.clean_stage(Path(ROOT),Path(STAGE),e,d)
d.update(remote_scratch_deleted=True,cleanup_completed_at=r.stamp())
r.save(p,d)
'''.replace('CODE', repr(args.remote_root + '/code')).replace('RECEIPT', repr(args.remote_root + '/receipts/' + group + '.' + e['upload_id'] + '.complete.json')).replace('STAGE', repr(stage)).replace('ROOT', repr(args.remote_root)).replace('TRANSPORT', repr(group + '.transport.json'))
                reconnect(lambda: remote_python(args, code), 'reconcile_cleanup_receipt', args.remote_retry_seconds)
                continue
            if snapshot['stage_exists']:
                raise ValueError('Success receipt conflicts with remaining staging')
            save(directory / 'complete.json', proof)
            reconnect(lambda: cleanup_first_sftp_copies(args, e, proof), 'legacy_staging_cleanup', args.remote_retry_seconds)
            state.update(status='complete', hf_revision=proof['hf_revision'], remote_scratch_deleted=True, updated_at=stamp())
            save(state_path, state)
            return proof
        waiting = snapshot['active'] or state['status'] in ('launching_receiver', 'waiting_remote', 'transport_verified', 'complete')
        if snapshot['active']:
            state.update(status='waiting_remote', pid=snapshot['pid'], updated_at=stamp())
            save(state_path, state)
        elif waiting and not snapshot['stage_exists']:
            # Like GTDB: absent data is not success and may precede an atomic receipt.
            state.update(status='waiting_remote', updated_at=stamp())
            save(state_path, state)
        else:
            if waiting and snapshot['stage_exists']:
                # Exact owned stage remains: checksum-resume before relaunching it.
                state.update(status='staging', updated_at=stamp())
                save(state_path, state)
            archive_location = directory / 'archive-location.json'
            if archive_location.exists():
                archive = Path(json.loads(archive_location.read_text())['path'])
            else:
                e, archive = make_package(args, group, rows, prefix, genomes)
            records = prepare_parts(archive, e, directory, args.transport_chunk_bytes)
            reconnect(lambda: remote_command(args, 'umask 077; mkdir -p ' + shlex.quote(stage)), 'staging_directory', args.remote_retry_seconds)
            state.update(status='staging', updated_at=stamp())
            save(state_path, state)
            emit('transfer_start', group=group, genomes=genomes, bytes=e['archive_byte_size'], parts=len(records))
            transfer_parts(args, stage, records, directory, e)
            publish_transport(args, stage, directory, e)
            state.update(status='launching_receiver', updated_at=stamp())
            save(state_path, state)
            snapshot = launch_receiver(args, e, stage, directory)
            state.update(status='waiting_remote', updated_at=stamp())
            save(state_path, state)
            emit('receiver_started', group=group, pid=snapshot.get('pid'))
            continue
        if deadline and time.monotonic() > deadline:
            raise TimeoutError('No matching completion/cleanup receipt; next batch blocked')
        time.sleep(args.poll_seconds)


def ssh_args(args):
    return ['ssh', '-p', str(args.port), '-i', str(args.key), '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
            '-o', 'ConnectTimeout=30', '-o', 'ServerAliveInterval=30', '-o', 'ServerAliveCountMax=5',
            '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(args.known_hosts), args.host]


def remote_command(args, command, input_bytes=None, timeout=300):
    try:
        p = subprocess.run(ssh_args(args) + [command], input=input_bytes, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise RemoteTransportError('SSH command timed out') from error
    if p.returncode:
        message = p.stderr.decode('utf-8', errors='replace')[-1000:]
        if any(s in message.lower() for s in ('permission denied', 'host key verification failed', 'identification has changed')):
            raise RuntimeError('SSH authentication/host verification failed')
        if p.returncode == 255:
            raise RemoteTransportError('SSH connection interrupted')
        raise RuntimeError('Remote command failed (%s): %s' % (p.returncode, message))
    return p.stdout.decode('utf-8')


def remote_python(args, code):
    return remote_command(args, 'python3 -c ' + shlex.quote(code))


def stage_inventory(args, stage, records):
    code = '''import hashlib,json
from pathlib import Path
stage=Path(STAGE)
out={}
for name in NAMES:
 p=stage/name
 if p.is_symlink(): raise ValueError('Symlink in transport staging')
 if not p.exists():
  out[name]=None
  continue
 if not p.is_file(): raise ValueError('Non-file in transport staging')
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 out[name]={'bytes':p.stat().st_size,'sha256':h.hexdigest()}
print(json.dumps(out))
'''.replace('STAGE', repr(stage)).replace('NAMES', repr([p['name'] for _, p in records]))
    return json.loads(remote_python(args, code))


def sftp_command(args):
    return ['sftp', '-P', str(args.port), '-i', str(args.key), '-R', '128', '-B', '131072', '-b', '-',
            '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'ConnectTimeout=30', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=4',
            '-o', 'UserKnownHostsFile=' + str(args.known_hosts), args.host]


def sftp_session(args, commands, log_path):
    try:
        with log_path.open('a') as log:
            p = subprocess.run(sftp_command(args), input='\n'.join(commands) + '\n', universal_newlines=True,
                               stdout=log, stderr=subprocess.STDOUT, timeout=args.sftp_session_timeout)
    except subprocess.TimeoutExpired as error:
        raise RemoteTransportError('SFTP session timed out; rescan before resume') from error
    if p.returncode:
        with log_path.open('rb') as f:
            f.seek(max(0, log_path.stat().st_size - 4096))
            message = f.read().decode('utf-8', errors='replace').lower()
        if any(s in message for s in ('permission denied', 'host key verification failed', 'identification has changed',
                                      'no space left', 'disk quota exceeded')):
            raise RuntimeError('SFTP authentication, host verification or storage failure; see transfer.log')
        if p.returncode == 255 or p.returncode < 0 or any(s in message for s in (
                'connection', 'broken pipe', 'timed out', 'closed by remote', 'couldn\'t read packet')):
            raise RemoteTransportError('SFTP connection interrupted; rescan before resume')
        raise RuntimeError('SFTP failed; see transfer.log')


def transfer_parts(args, stage, records, directory, e):
    """Short SFTP sessions; rescan/hash after EVERY reconnect and successful put."""
    transferred = 0
    for start in range(0, len(records), args.sftp_files_per_session):
        group = records[start:start + args.sftp_files_per_session]
        while True:
            inventory = reconnect(lambda: stage_inventory(args, stage, group), 'transport_checksum_scan', args.remote_retry_seconds)
            pending = []
            for local, row in group:
                actual = inventory[row['name']]
                if actual and actual['bytes'] == row['bytes'] and actual['sha256'] == row['sha256']:
                    continue
                resume = bool(actual and 0 < actual['bytes'] < row['bytes']
                              and prefix_digest(local, actual['bytes']) == actual['sha256'])
                if actual and not resume:
                    # Do not append to a corrupt prefix; preserve it in this batch's quarantine.
                    code = '''import os,uuid
from pathlib import Path
stage=Path(STAGE)
src=stage/NAME
if src.is_symlink() or src.parent.resolve()!=stage.resolve():raise ValueError('Unsafe quarantine path')
q=stage/'quarantine'
q.mkdir(exist_ok=True,mode=0o700)
if src.exists():os.replace(str(src),str(q/(src.name+'.'+uuid.uuid4().hex)))
'''.replace('STAGE', repr(stage)).replace('NAME', repr(row['name']))
                    reconnect(lambda: remote_python(args, code), 'quarantine_corrupt_part', args.remote_retry_seconds)
                    emit('corrupt_part_quarantined', group=validate_envelope(e), part=row['name'])
                pending.append('put %s%s %s' % ('-a ' if resume else '', shlex.quote(str(local)),
                                              shlex.quote(stage + '/' + row['name'])))
            if not pending:
                break
            try:
                sftp_session(args, pending, directory / 'transfer.log')
            except RemoteTransportError:
                emit('sftp_reconnect', group=validate_envelope(e), wait_seconds=args.remote_retry_seconds)
                time.sleep(args.remote_retry_seconds)
            # A successful process is still followed by remote SHA verification.
        transferred += len(group)
        save(directory / 'transfer-progress.json', dict(status='staging', verified_parts=transferred,
             total_parts=len(records), upload_id=e['upload_id'], manifest_sha256=e['manifest_sha256'], updated_at=stamp()))
        emit('transport_parts_verified', group=validate_envelope(e), verified_parts=transferred, total_parts=len(records))


def publish_transport(args, stage, directory, e):
    """Publish controls atomically only after verified payload; lost replies are harmless."""
    def controls():
        sftp_session(args, ['put %s %s' % (shlex.quote(str(directory / 'transport.json')),
            shlex.quote(stage + '/transport.json.partial')),
            'rename %s %s' % (shlex.quote(stage + '/transport.json.partial'), shlex.quote(stage + '/transport.json'))],
            directory / 'transfer.log')
    reconnect(controls, 'transport_controls', args.remote_retry_seconds)
    code = '''import json,sys
from pathlib import Path
sys.path.insert(0,CODE)
import bted_hf_relay as r
stage=Path(STAGE)
e=json.loads((stage/'transport.json').read_text())
if r.transport_identity(e)!=IDENTITY:raise ValueError('Transport controls differ from sender')
r.save(stage/'transport.ready.json',dict(upload_id=e['upload_id'],manifest_sha256=e['manifest_sha256'],
 archive_sha256=e['archive_sha256'],transport_identity=r.transport_identity(e),completed_at=r.stamp()))
'''.replace('CODE', repr(args.remote_root + '/code')).replace('STAGE', repr(stage)).replace('IDENTITY', repr(transport_identity(e)))
    reconnect(lambda: remote_python(args, code), 'publish_transport_READY', args.remote_retry_seconds)


def groups_for_release(release):
    doc = json.loads((release / 'release.json').read_text())
    result = []
    for batch in range(43):
        prefix = 'batter/batches/%03d/' % batch
        rows = [{'name': r['path'][len(prefix):], 'bytes': r['byte_size'], 'sha256': r['sha256'],
                 'source': str(release / r['path'])} for r in doc['files'] if r['path'].startswith(prefix)]
        result.append(('batter-%03d' % batch, rows, VERSION + '/' + prefix, 904 if batch == 42 else 1000))
    for group in ('experimental', 'catalogues'):
        if group == 'experimental':
            selected = [r for r in doc['files'] if r['path'].startswith('experimental/')]
        else:
            selected = [r for r in doc['files'] if r['path'].startswith('batter/') and not r['path'].startswith('batter/batches/')]
        rows = [{'name': r['path'], 'bytes': r['byte_size'], 'sha256': r['sha256'], 'source': str(release / r['path'])} for r in selected]
        result.append((group, rows, VERSION + '/', 0))
    rows = [{'name': n, 'bytes': (release / n).stat().st_size, 'sha256': digest(release / n), 'source': str(release / n)} for n in ('release.json', 'SHA256SUMS.txt')]
    readme = release.parent / 'README.md'
    rows.append({'name': 'README.md', 'bytes': readme.stat().st_size, 'sha256': digest(readme), 'source': str(readme)})
    result.append(('release-controls', rows, VERSION + '/', 0))
    return result


def make_package(args, group, rows, prefix, genomes):
    directory = args.state / group
    directory.mkdir(parents=True, exist_ok=True)
    envelope_path = directory / 'transport.json'
    archive_path = directory / 'payload.tar'
    # Preserve the existing BATTER uploader's path-component ordering.
    rows = sorted(rows, key=lambda r: PurePosixPath(r['name']))
    manifest = manifest_text(rows).encode('utf-8')
    msha = hashlib.sha256(manifest).hexdigest()
    if envelope_path.exists():
        e = json.loads(envelope_path.read_text())
        if e['manifest_sha256'] != msha:
            raise ValueError('Source manifest changed during relay')
        validate_envelope(e)
        if archive_path.exists() and digest(archive_path) != e['archive_sha256']:
            raise ValueError('Local transport archive changed')
        return e, archive_path
    # Reuse the already validated first transport, preserving its upload ID.
    legacy = args.release.parent.parent / 'release_bted_v05_state/sftp-ts3'
    if group == 'batter-000' and (legacy / '000.transport.json').exists():
        e = json.loads((legacy / '000.transport.json').read_text())
        if e['manifest_sha256'] != msha:
            raise ValueError('First transport differs from accepted release')
        archive_path = legacy / '000.payload.tar'
        if digest(archive_path) != e['archive_sha256']:
            raise ValueError('First transport archive mismatch')
        e['group'] = group
        save(envelope_path, e)
        save(directory / 'archive-location.json', {'path': str(archive_path)})
        return e, archive_path
    e = dict(group=group, batch=group[7:] if group.startswith('batter-') else None,
             upload_id=uuid.uuid4().hex, manifest_sha256=msha, release_manifest_sha256=RELEASE_SHA,
             genome_count=genomes, hf_repo=REPO, hf_destination_prefix=prefix, created_at=stamp(),
             payload_file_count=len(rows), transport='tar_chunks', archive_filename='payload.tar', READY_sent=False)
    temporary = archive_path.with_suffix('.tar.partial')
    with tarfile.open(str(temporary), 'w', format=tarfile.PAX_FORMAT) as tar:
        for row in rows:
            path = Path(row['source'])
            if path.is_symlink() or path.stat().st_size != row['bytes'] or digest(path) != row['sha256']:
                raise ValueError('Accepted source changed: ' + row['name'])
            tar.add(str(path), arcname=safe_name(row['name']), recursive=False)
        controls = {'manifest.tsv': manifest, 'upload_metadata.json': (json.dumps(e) + '\n').encode('utf-8')}
        for name, content in controls.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            tar.addfile(member, io.BytesIO(content))
    os.replace(str(temporary), str(archive_path))
    e.update(archive_byte_size=archive_path.stat().st_size, archive_sha256=digest(archive_path))
    save(envelope_path, e)
    return e, archive_path


def cleanup_legacy_stage(remote, stage, rows, progress=None):
    """SFTP rmdir does not expand globs: remove explicit, manifest-owned paths."""
    allowed_root = {'genomes', 'payload.tar', 'transport.json', 'manifest.tsv',
                    'upload_metadata.json', 'genomes.tsv', 'files.tsv'}
    entries = remote.directory_entries(stage)
    if not entries <= allowed_root:
        raise ValueError('Unexpected legacy staging root entries; preserved')
    commands = ['-rm ' + shell_path(stage + '/' + name) for name in sorted(entries - {'genomes'})]
    if commands:
        remote.run_sftp_capture(commands)
    allowed = {}
    for row in rows:
        pieces = row['name'].split('/')
        if len(pieces) == 3 and pieces[0] == 'genomes':
            allowed.setdefault(pieces[1], set()).add(pieces[2])
    if 'genomes' in entries:
        parent = stage + '/genomes'
        children = remote.directory_entries(parent)
        if not children <= set(allowed):
            raise ValueError('Unexpected legacy genome directory; preserved')
        names = sorted(children)
        for offset in range(0, len(names), 50):
            remote.run_sftp_capture(['-rmdir ' + shell_path(parent + '/' + name) for name in names[offset:offset + 50]])
            if progress:
                progress(min(offset + 50, len(names)), len(names))
        # Usually all are empty now. Inspect only any nonempty survivors.
        for name in sorted(remote.directory_entries(parent)):
            if name not in allowed:
                raise ValueError('Unexpected leftover legacy directory; preserved')
            path = parent + '/' + name
            files = remote.directory_entries(path)
            if not files <= allowed[name]:
                raise ValueError('Unexpected leftover legacy file; preserved')
            remote.run_sftp_capture(['-rm ' + shell_path(path + '/' + f) for f in sorted(files)]
                                    + ['-rmdir ' + shell_path(path)])
        remote.run_sftp_capture(['-rmdir ' + shell_path(parent)])
    remote.run_sftp_capture(['-rmdir ' + shell_path(stage)])


def shell_path(path):
    # SFTP accepts quoted literal paths; no wildcard expansion is needed here.
    return '"' + path.replace('\\', '\\\\').replace('"', '\\"') + '"'


def cleanup_first_sftp_copies(args, e, proof):
    """Remove only our two legacy first-batch stages, using their owning account."""
    if validate_envelope(e) != 'batter-000':
        return
    proof_matches(proof, e)
    if not proof.get('remote_scratch_deleted'):
        raise ValueError('Receiver cleanup incomplete')
    marker = args.state / 'batter-000' / 'legacy-sftp-cleanup.json'
    if marker.exists() and json.loads(marker.read_text()).get('complete'):
        return
    import upload_batter_batches as u
    legacy = args.release.parent.parent / 'release_bted_v05_state/sftp-ts3'
    sources = [legacy / '000.package.json', legacy / '000.json']
    stages = []
    inventories = {}
    for source in sources:
        if not source.exists():
            continue
        state = json.loads(source.read_text())
        if state['manifest_sha256'] != e['manifest_sha256'] or state['release_manifest_sha256'] != RELEASE_SHA:
            raise ValueError('Legacy staging belongs to another payload')
        stage = state['remote_stage_dir']
        expected = '/incoming/terminator/v0.5.0/.staging/000.' + state['upload_id']
        if stage != expected or not re.fullmatch('[0-9a-f]{32}', state['upload_id']):
            raise ValueError('Unexpected legacy staging cleanup path')
        if stage not in stages:
            stages.append(stage)
        inventories[stage] = state['manifest']
    class PinnedRemote(u.Remote):
        def sftp_command(self):
            command = super().sftp_command()
            return command[:-1] + ['-o', 'StrictHostKeyChecking=yes', '-o',
                'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=4', '-o',
                'UserKnownHostsFile=' + str(args.known_hosts)] + command[-1:]
    remote = PinnedRemote('sftpdrop@ts3.zocomputer.io', args.key, args.port)
    def sftp_operation(operation):
        try:
            return operation()
        except u.RemoteTransportError as error:
            raise RemoteTransportError('Legacy SFTP staging temporarily unreachable') from error
    for stage in stages:
        if sftp_operation(lambda: remote.path_exists(stage)):
            def progress(done, total):
                save(marker.with_name('legacy-sftp-cleanup-progress.json'), dict(stage=stage,
                     directories_attempted=done, total_directories=total, hf_revision=proof['hf_revision'], updated_at=stamp()))
                emit('legacy_cleanup_progress', directories_attempted=done, total_directories=total)
            sftp_operation(lambda: cleanup_legacy_stage(remote, stage, inventories[stage], progress))
        if sftp_operation(lambda: remote.path_exists(stage)):
            raise ValueError('Legacy batch staging remains; next batch blocked')
    save(marker, dict(complete=True, deleted_stages=stages, hf_revision=proof['hf_revision'],
                     manifest_sha256=e['manifest_sha256'], completed_at=stamp()))
    emit('legacy_first_staging_cleaned', stages=stages)


def send(args):
    import fcntl
    os.umask(0o077)
    args.state.mkdir(parents=True, exist_ok=True)
    with (args.state / 'sender.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if digest(args.release / 'release.json') != RELEASE_SHA:
            raise ValueError('Release has changed since full acceptance')
        reports = args.release.parent.parent / 'logs'
        for name in ('verify_bted_v05_full.json', 'audit_bted_v05_full_sources.json'):
            r = json.loads((reports / name).read_text())
            if not r.get('complete') or r.get('release_manifest_sha256') != RELEASE_SHA:
                raise ValueError('Release acceptance proof missing')
        if not args.allow_recommended_file_count:
            raise ValueError('371963 files exceed the HF recommendation; explicit override required')
        save(args.state / 'policy.json', dict(release_manifest_sha256=RELEASE_SHA, repository_files=371963,
             official_recommended_files=99999, recommendation_override=True,
             authorization='User explicitly requested full sequential batch publication after limitation report',
             hard_platform_limits_overridden=False, old_versions_deleted=False, main_promoted=False))
        groups = groups_for_release(args.release)
        summary = dict(status='running', total_groups=len(groups), completed_groups=[], started_at=stamp())
        save(args.state / 'summary.json', summary)
        # Install exactly this version of the receiver; no source data or key is copied.
        code_path = args.remote_root + '/code/bted_hf_relay.py'
        content = Path(__file__).read_bytes()
        install_code = '''import hashlib,os,sys
from pathlib import Path
os.umask(0o077)
b=sys.stdin.buffer.read()
if hashlib.sha256(b).hexdigest()!=EXPECTED:raise ValueError('Receiver installation interrupted')
p=Path(DESTINATION)
p.parent.mkdir(parents=True,exist_ok=True)
t=p.with_suffix('.upload')
t.write_bytes(b)
os.replace(str(t),str(p))
'''.replace('EXPECTED', repr(hashlib.sha256(content).hexdigest())).replace('DESTINATION', repr(code_path))
        install = 'python3 -c ' + shlex.quote(install_code)
        reconnect(lambda: remote_command(args, install, content), "install_receiver", args.remote_retry_seconds)
        try:
            for group, rows, prefix, genomes in groups:
                summary.update(current_group=group, updated_at=stamp())
                save(args.state / 'summary.json', summary)
                proof = process_group(args, group, rows, prefix, genomes, summary)
                summary['completed_groups'].append(group)
                summary.update(updated_at=stamp(), completed_genomes=sum(
                    1000 if g != 'batter-042' else 904 for g in summary['completed_groups'] if g.startswith('batter-')))
                save(args.state / 'summary.json', summary)
                emit('sender_batch_verified_and_cleaned', group=group, genomes=genomes, revision=proof['hf_revision'])
                directory = args.state / group
                archive = directory / 'payload.tar'
                if archive.exists():
                    archive.unlink()
                parts = directory / 'parts'
                if parts.exists():
                    if parts.is_symlink() or directory.resolve() not in parts.resolve().parents:
                        raise ValueError('Local part cleanup outside batch state')
                    shutil.rmtree(str(parts))
                if args.stop_after and len(summary['completed_groups']) >= args.stop_after:
                    summary.update(status='stopped_at_requested_group_count')
                    save(args.state / 'summary.json', summary)
                    return
            summary.update(status='final_verification', updated_at=stamp())
            save(args.state / 'summary.json', summary)
            command = '%s %s finalize --root %s' % (shlex.quote(args.remote_root + '/venv/bin/python'),
                        shlex.quote(code_path), shlex.quote(args.remote_root))
            reconnect(lambda: remote_command(args, command, timeout=48 * 3600), "final_verification", args.remote_retry_seconds)
            final_proof = json.loads(reconnect(lambda: remote_command(args, 'cat ' + shlex.quote(args.remote_root + '/receipts/release.complete.json')), 'final_receipt', args.remote_retry_seconds))
            if (final_proof.get('release_manifest_sha256') != RELEASE_SHA or not final_proof.get('hf_sha256_verified')
                    or final_proof.get('hf_file_count') != 371963 or not re.fullmatch('[0-9a-f]{40}', final_proof.get('hf_revision', ''))):
                raise ValueError('Incomplete whole-release proof')
            save(args.state / 'release.complete.json', final_proof)
            summary.update(status='all_groups_verified', completed_at=stamp(), main_promoted=False, old_versions_deleted=False,
                           hf_revision=final_proof['hf_revision'], verified_files=final_proof['hf_file_count'])
            save(args.state / 'summary.json', summary)
            emit('release_relay_complete', **summary)
        except Exception as error:
            summary.update(status='failed_retained', error_type=type(error).__name__, error=str(error), updated_at=stamp())
            save(args.state / 'summary.json', summary)
            emit('relay_stopped', error_type=type(error).__name__)
            raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='mode', required=True)
    r = sub.add_parser('receive')
    r.add_argument('--root', type=Path, default=Path(DEFAULT_REMOTE))
    r.add_argument('--envelope', type=Path, required=True)
    r.add_argument('--chunk-size', type=int, default=100)
    f = sub.add_parser('finalize')
    f.add_argument('--root', type=Path, default=Path(DEFAULT_REMOTE))
    l = sub.add_parser('launch')
    l.add_argument('--root', type=Path, default=Path(DEFAULT_REMOTE))
    l.add_argument('--envelope', type=Path, required=True)
    q = sub.add_parser('status')
    q.add_argument('--root', type=Path, default=Path(DEFAULT_REMOTE))
    q.add_argument('--group', required=True)
    q.add_argument('--upload-id', required=True)
    q.add_argument('--manifest-sha256', required=True)
    q.add_argument('--pid')
    s = sub.add_parser('send')
    s.add_argument('--release', type=Path, required=True)
    s.add_argument('--state', type=Path, required=True)
    s.add_argument('--host', default='sshlogin@ts3.zocomputer.io')
    s.add_argument('--port', type=int, default=10383)
    s.add_argument('--key', type=Path, default=Path('/home/liurulong/.ssh/id_ed25519'))
    s.add_argument('--known-hosts', type=Path, default=Path('/home/liurulong/terminator/release_bted_v05_state/sftpdrop_known_hosts'))
    s.add_argument('--remote-root', default=DEFAULT_REMOTE)
    s.add_argument('--allow-recommended-file-count', action='store_true')
    s.add_argument('--stop-after', type=int)
    s.add_argument('--transport-chunk-bytes', type=int, default=64 * 1024 * 1024)
    s.add_argument('--sftp-files-per-session', type=int, default=4)
    s.add_argument('--sftp-session-timeout', type=int, default=300)
    s.add_argument('--remote-retry-seconds', type=int, default=60)
    s.add_argument('--poll-seconds', type=int, default=30)
    s.add_argument('--completion-timeout-seconds', type=int, default=48 * 3600)
    a = p.parse_args()
    if a.mode == 'receive':
        if not 1 <= a.chunk_size <= 100:
            p.error('Commit size must be 1..100')
        receive(a)
    elif a.mode == 'finalize':
        finalize(a)
    elif a.mode == 'launch':
        print(json.dumps(launch(a)))
    elif a.mode == 'status':
        print(json.dumps(receiver_snapshot(a.root.resolve(), a.group, a.upload_id, a.manifest_sha256, a.pid)))
    else:
        if (a.transport_chunk_bytes < 1024 * 1024 or a.sftp_files_per_session < 1 or a.sftp_session_timeout < 1
                or a.remote_retry_seconds < 1 or a.poll_seconds < 1 or a.completion_timeout_seconds < 0):
            p.error('Invalid chunk, connection or polling settings')
        send(a)


if __name__ == '__main__':
    main()
