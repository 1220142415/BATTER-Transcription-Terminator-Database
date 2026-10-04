"""Read verified relay receipts and build an isolated, HF-only local preview.

The export command is read-only on cu10. It never starts a sender, publishes
files, or creates release.complete.json. Batch commits remain immutable.
"""
import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import io
import shlex
import tarfile
import time
from pathlib import Path

VERSION = 'v0.5.0'
REPO = 'liurulong/terminator'
FILES = ('reference.fa.gz', 'reference.fa.gz.fai', 'reference.fa.gz.gzi',
         'prediction.gff3.gz', 'prediction.gff3.gz.tbi', 'augmentation.gff3.gz',
         'augmentation.gff3.gz.tbi', 'genes.gff3.gz', 'genes.gff3.gz.tbi')


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True).encode('utf-8')


def export_snapshot(release, state):
    sys.path.insert(0, str(release.parents[1] / 'scripts'))
    import bted_hf_relay as relay
    import bted_v05 as source
    if source.sha256(release / 'release.json') != relay.RELEASE_SHA:
        raise ValueError('Source release differs from the accepted manifest')
    doc = json.loads((release / 'release.json').read_text(encoding='utf-8'))
    by_group = {}
    for item in doc['files']:
        parts = item['path'].split('/')
        group = 'batter-' + parts[2] if parts[:2] == ['batter', 'batches'] else ('experimental' if parts[0] == 'experimental' else 'catalogues')
        prefix = 'batter/batches/' + parts[2] + '/' if group.startswith('batter-') else ''
        by_group.setdefault(group, []).append(dict(name=item['path'][len(prefix):], bytes=item['byte_size'], sha256=item['sha256']))
    snapshot = dict(schema='bted-hf-preview-v1', release_version=VERSION, hf_repo=REPO,
                    release_manifest_sha256=relay.RELEASE_SHA, total_genomes=doc['counts']['batter']['genomes'],
                    groups=[], genomes=[])
    if (state / 'release.complete.json').is_file():
        by_group['release-controls'] = [dict(name=name, bytes=path.stat().st_size, sha256=source.sha256(path)) for name, path in
            [('release.json', release / 'release.json'), ('SHA256SUMS.txt', release / 'SHA256SUMS.txt'), ('README.md', release.parent / 'README.md')]]
    for group, payload in sorted(by_group.items()):
        receipt_path = state / group / 'complete.json'
        if not receipt_path.is_file():
            continue
        envelope = json.loads((state / group / 'transport.json').read_text())
        proof = json.loads(receipt_path.read_text())
        relay.validate_envelope(envelope)
        relay.proof_matches(proof, envelope)
        if proof.get('group') != group or proof.get('hf_branch') != relay.BRANCH:
            raise ValueError('Receipt group/branch mismatch')
        manifest_sha = hashlib.sha256(relay.manifest_text(payload).encode('utf-8')).hexdigest()
        if manifest_sha != envelope['manifest_sha256'] or len(payload) != envelope['payload_file_count']:
            raise ValueError('Batch manifest differs from transport/receipt: ' + group)
        # Keep the complete inventory for identity checks, but no data payload.
        identity = {k: envelope[k] for k in ('group', 'batch', 'upload_id', 'manifest_sha256',
                    'archive_sha256', 'release_manifest_sha256', 'hf_repo', 'hf_destination_prefix',
                    'genome_count', 'payload_file_count') if k in envelope}
        snapshot['groups'].append(dict(envelope=identity, receipt=proof, payload=payload))
        if not group.startswith('batter-'):
            continue
        batch = group[7:]
        prefix = 'batter/batches/' + batch + '/'
        index = {item['name']: item for item in payload}
        for row in source.rows(release / prefix / 'genomes.tsv'):
            genome = row['genome_id']
            package = 'genomes/' + genome + '/'
            def read_checked(name):
                data = (release / prefix / package / name).read_bytes()
                expected = index[package + name]
                if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
                    raise ValueError('Source metadata/index changed: ' + genome)
                return data
            meta = json.loads(read_checked('metadata.json'))
            fai = read_checked('reference.fa.gz.fai').decode('utf-8')
            contigs = [dict(seqid=line.split('\t')[0], length_bp=int(line.split('\t')[1])) for line in fai.splitlines()]
            files = {name: dict(logical_path=prefix + package + name, byte_size=index[package + name]['bytes'],
                                sha256=index[package + name]['sha256']) for name in FILES if package + name in index}
            shared = release / 'experimental/genomes' / genome / 'metadata.json'
            shared_verified = False
            if shared.is_file():
                shared_bytes = shared.read_bytes()
                shared_row = next((r for r in by_group.get('experimental', []) if r['name'] == shared.relative_to(release).as_posix()), None)
                if not shared_row or len(shared_bytes) != shared_row['bytes'] or hashlib.sha256(shared_bytes).hexdigest() != shared_row['sha256']:
                    raise ValueError('Shared reference metadata changed: ' + genome)
                shared_verified = json.loads(shared_bytes)['reference_validation']['status'] == 'experimental_contigs_sequence_identical_to_GEM'
            snapshot['genomes'].append(dict(genome_id=genome, batch=batch, reference_contigs=contigs,
                annotation=meta['annotation'], validation=meta['validation'], files=files,
                shared_reference_verified=shared_verified))
    snapshot['available_genomes'] = len(snapshot['genomes'])
    final = state / 'release.complete.json'
    if final.is_file():
        snapshot['complete_release_proof'] = json.loads(final.read_text())
        migration_root = state.parent / 'hf-genome-first'
        if (migration_root / 'migration.complete.json').is_file():
            snapshot['migration'] = dict(plan=json.loads((migration_root / 'migration.json').read_text()),
                                         proof=json.loads((migration_root / 'migration.complete.json').read_text()))
            if (migration_root / 'main.complete.json').is_file():
                snapshot['migration']['main_proof'] = json.loads((migration_root / 'main.complete.json').read_text())
            from bted_hf_migrate import snapshot_migration
            snapshot_migration(snapshot)
    return snapshot


def validate_snapshot(snapshot):
    import bted_hf_relay as relay
    if (snapshot.get('schema') != 'bted-hf-preview-v1' or snapshot.get('release_version') != VERSION
            or snapshot.get('hf_repo') != REPO or snapshot.get('release_manifest_sha256') != relay.RELEASE_SHA):
        raise ValueError('Unknown HF preview identity')
    groups = {}
    for item in snapshot['groups']:
        e, proof, payload = item['envelope'], item['receipt'], item['payload']
        group = relay.validate_envelope(e)
        relay.proof_matches(proof, e)
        if group in groups or proof.get('group') != group or proof.get('hf_branch') != relay.BRANCH:
            raise ValueError('Duplicate or mismatched receipt')
        text = relay.manifest_text(payload).encode('utf-8')
        parsed = relay.parse_manifest(text)
        if hashlib.sha256(text).hexdigest() != e['manifest_sha256'] or len(parsed) != e['payload_file_count']:
            raise ValueError('Preview manifest differs from receipt')
        groups[group] = dict(revision=proof['hf_revision'], inventory={r['name']: r for r in parsed}, receipt=proof)
    seen = set()
    counts = {}
    for genome in snapshot['genomes']:
        genome_id, batch = genome['genome_id'], genome['batch']
        if not re.fullmatch(r'[A-Za-z0-9._-]{1,96}', genome_id) or genome_id in seen:
            raise ValueError('Invalid or duplicate genome')
        seen.add(genome_id)
        group = groups.get('batter-' + batch)
        if group is None:
            raise ValueError('Genome has no verified receipt')
        counts[batch] = counts.get(batch, 0) + 1
        if not all(name in genome['files'] for name in FILES[:5]):
            raise ValueError('Incomplete reference/prediction package')
        for name, file in genome['files'].items():
            logical = 'batter/batches/' + batch + '/genomes/' + genome_id + '/' + name
            expected = group['inventory'].get('genomes/' + genome_id + '/' + name)
            if name not in FILES or file['logical_path'] != logical or not expected or file['sha256'] != expected['sha256'] or file['byte_size'] != expected['bytes']:
                raise ValueError('Asset differs from verified inventory')
        if not genome['reference_contigs'] or any(not c['seqid'] or c['length_bp'] <= 0 for c in genome['reference_contigs']):
            raise ValueError('Invalid reference contigs')
    for key, item in groups.items():
        if key.startswith('batter-') and counts.get(key[7:], 0) != item['receipt']['genome_count']:
            raise ValueError('Incomplete preview batch')
    if len(seen) != snapshot['available_genomes'] or snapshot['total_genomes'] != 42904:
        raise ValueError('Preview count mismatch')
    full = snapshot.get('complete_release_proof')
    if 'complete_release_proof' in snapshot:
        expected_groups = ['batter-%03d' % n for n in range(43)] + ['experimental', 'catalogues', 'release-controls']
        if (not isinstance(full, dict) or full.get('status') != 'complete' or full.get('hf_repo') != REPO or full.get('release_manifest_sha256') != relay.RELEASE_SHA
                or full.get('hf_branch') != relay.BRANCH or full.get('hf_sha256_verified') is not True
                or full.get('hf_file_count') != 371963 or full.get('genome_count') != 42904
                or full.get('completed_groups') != expected_groups or set(groups) != set(expected_groups)
                or sum(len(g['inventory']) for g in groups.values()) != 371963
                or not re.fullmatch('[0-9a-f]{40}', full.get('hf_revision', '')) or snapshot['available_genomes'] != 42904):
            raise ValueError('Invalid complete release proof')
    if snapshot.get('migration'):
        from bted_hf_migrate import snapshot_migration
        snapshot_migration(snapshot)
    return groups


def project_snapshot(snapshot, database):
    import bted_v05_web as web
    groups = validate_snapshot(snapshot)
    full = snapshot.get('complete_release_proof')
    migration = snapshot.get('migration')
    mapping = {r['source_path']: r['target_path'] for r in migration['plan']['mapping']} if migration else {}
    from bted_hf_migrate import effective_revision
    final_revision = effective_revision(migration) if migration else full['hf_revision'] if full else None
    manifest_sha = migration['plan']['manifest_sha256'] if migration else snapshot['release_manifest_sha256']
    values = []
    for genome in snapshot['genomes']:
        revision = final_revision if full else groups['batter-' + genome['batch']]['revision']
        data = {k: v for k, v in genome.items() if k not in ('genome_id', 'batch')}
        data['batch'] = genome['batch']
        data['group'] = 'batter-' + genome['batch']
        data['files'] = {name: dict(file, logical_path=mapping.get(file['logical_path'], file['logical_path']),
                                 url=web.data_url(mapping.get(file['logical_path'], file['logical_path']), revision)) for name, file in genome['files'].items()}
        values.append((genome['genome_id'], VERSION, 'public_download' if full else 'hf_preview', json.dumps(data)))
    assets = {}
    experimental = groups.get('experimental')
    if experimental:
        revision = final_revision if full else experimental['revision']
        for path, row in experimental['inventory'].items():
            assets[path] = dict(url=web.data_url(mapping.get(path, path), revision), byte_size=row['bytes'], sha256=row['sha256'],
                                revision=revision, asset_kind=web.kind(path))
    if full and not migration:
        for path, row in groups['release-controls']['inventory'].items():
            if path == 'README.md':
                continue
            assets[path] = dict(url=web.data_url(path, full['hf_revision']), byte_size=row['bytes'], sha256=row['sha256'],
                                revision=full['hf_revision'], asset_kind=web.kind(path))
    if migration:
        for name in ('release.json', 'SHA256SUMS.txt'):
            row = next(r for r in migration['plan']['files'] if r['path'] == name)
            assets[name] = dict(url=web.data_url(name, final_revision), byte_size=row['byte_size'], sha256=row['sha256'], revision=final_revision, asset_kind=web.kind(name))
    conn = sqlite3.connect(str(database))
    with conn:
        conn.execute('CREATE TABLE IF NOT EXISTS batter_release_assets (genome_id TEXT NOT NULL, release_version TEXT NOT NULL, publication_status TEXT NOT NULL, metadata_json TEXT NOT NULL, PRIMARY KEY(genome_id,release_version))')
        held = conn.execute("SELECT * FROM batter_release_assets WHERE release_version=? AND publication_status='held'", (VERSION,)).fetchall()
        conn.execute('DELETE FROM batter_release_assets WHERE release_version=?', (VERSION,))
        conn.executemany('INSERT INTO batter_release_assets VALUES (?,?,?,?)', values)
        conn.executemany('INSERT INTO batter_release_assets VALUES (?,?,?,?)', held)
        conn.execute('UPDATE assets SET is_public=0 WHERE release_version=?', (VERSION,))
        for path, file in assets.items():
            existing = conn.execute('SELECT asset_key FROM assets WHERE release_version=? AND logical_path=?', (VERSION, path)).fetchone()
            if existing:
                file['asset_key'] = existing[0]
            conn.execute('UPDATE assets SET is_public=1, origin_url=?,origin_host=?,byte_size=?,sha256=? WHERE release_version=? AND logical_path=?',
                         (file['url'], 'huggingface.co', file['byte_size'], file['sha256'], VERSION, path))
        if migration:
            for old, new in mapping.items():
                if not old.startswith('experimental/'): continue
                conn.execute('UPDATE assets SET logical_path=? WHERE release_version=? AND logical_path=?', (new, VERSION, old))
                conn.execute('UPDATE sources SET record_root=? WHERE release_version=? AND record_root=?', (new, VERSION, old))
            assets = {mapping.get(path, path): value for path, value in assets.items()}
        conn.execute('UPDATE tracks SET is_public=? WHERE release_version=?', (1 if experimental else 0, VERSION))
        conn.execute('UPDATE release_versions SET canonical_manifest_sha256=?,asset_origin_status=? WHERE release_version=?',
                     (manifest_sha, 'verified' if full else 'planned_not_verified', VERSION))
    conn.close()
    return dict(releaseVersion=VERSION, releaseLabel='v5', releaseDisplayName='Latest · v5',
                releaseRevision=final_revision, publicationStatus='public_download' if full else 'hf_preview',
                releaseManifestSha256=manifest_sha, experimentalAvailable=bool(experimental),
                layout='genome-first-v1' if migration else 'collection-v1',
                genomeMetadataPaths={path.split('/')[2]: path for path in assets if path.endswith('/metadata.tsv') and path.startswith('genomes/')},
                experimentalRevision=(final_revision if full else experimental['revision']) if experimental else None,
                availableGenomeCount=len(values), totalGenomeCount=snapshot['total_genomes'],
                batchRevisions={key[7:]: final_revision if full else value['revision'] for key, value in groups.items() if key.startswith('batter-')},
                batterBrowser=dict(route='/api/genomes/{genome_id}/jbrowse-config', preparedGenomeIds=[v[0] for v in values]), assets=assets)


def present_hf_page(html, manifest, relative):
    """Keep legacy experimental pages within the same verified availability."""
    import bted_v05_web as web
    from urllib.parse import quote
    html = web.present_site_page(html, relative)
    def download_link(match):
        file = manifest['assets'].get(match.group(1))
        if file and file.get('asset_key'):
            return '/api/assets/' + file['asset_key'] + '?revision=' + file['revision']
        return '#data-preparing'
    html = re.sub(r'(?:https://huggingface\.co/datasets/liurulong/terminator/resolve/[^/]+/|(?:\.\./)*downloads/)(?:v0\.[345]\.0)/([^\s\"\'<>]+)', download_link, html)
    pending = 'href="#data-preparing"' in html
    html = re.sub(r'<a\b[^>]*href="#data-preparing"[^>]*>(.*?)</a>', r'<span class="download-card">\1 · Data preparing</span>', html, flags=re.S)
    if pending:
        html = re.sub(r'<button\b[^>]*data-download-genome-package[^>]*>.*?</button>', '<span class="button">Data preparing</span>', html, flags=re.S)
    if relative.parent.name == 'genomes':
        genome = relative.stem
        available = genome in manifest['batterBrowser']['preparedGenomeIds'] or manifest['experimentalAvailable']
        if available:
            config = '/api/genomes/' + quote(genome, safe='') + '/jbrowse-config'
            html = re.sub(r'data-config="[^"]+"', 'data-config="' + config + '"', html)
            html = re.sub(r'href="[^\"]*jbrowse/index\.html\?config=[^\"]+"', 'href="../jbrowse/index.html?config=' + quote(config, safe='') + '"', html)
        else:
            html = re.sub(r'<iframe\b[^>]*data-browser-frame[^>]*>.*?</iframe>', '<p>Data preparing</p>', html, flags=re.S)
            html = re.sub(r'<a\b[^>]*href="[^\"]*jbrowse/index\.html\?config=[^\"]+"[^>]*>.*?</a>', '<span>Data preparing</span>', html, flags=re.S)
    if relative.name != 'batter-genomes.html':
        status = '<p role="status">Latest · v5 · {:,} / {:,} genomes available'.format(manifest['availableGenomeCount'], manifest['totalGenomeCount'])
        if not manifest['experimentalAvailable']: status += ' · Experimental data preparing'
        status += '</p>'
        html = html.replace('<main>', '<main>' + status, 1)
    return html.replace('Local browser', 'Genome browser').replace('Local preview', 'Latest · v5')


def stage_preview(snapshot, baseline, database, output):
    """Build fresh artifacts. A failed build never replaces the working preview."""
    import bted_v05_web as web
    validate_snapshot(snapshot)
    if output.exists():
        raise ValueError('Choose a fresh snapshot output directory')
    output.mkdir(parents=True)
    site = output / 'site'
    shutil.copytree(baseline, site, ignore=shutil.ignore_patterns('downloads', 'batter-preview-catalog.json'))
    # Generated legacy configs are unnecessary: the API produces HF configs.
    for folder in (site / 'jbrowse/assemblies', site / 'assemblies'):
        if folder.is_dir():
            for config in folder.glob('*.json'):
                config.unlink()
    db = output / 'catalog.sqlite'
    source = sqlite3.connect('file:' + database.resolve().as_posix() + '?mode=ro', uri=True)
    destination = sqlite3.connect(str(db))
    source.backup(destination)
    destination.close()
    source.close()
    manifest = project_snapshot(snapshot, db)
    from bted_unified_site import directory_page, redirect_page
    (site / 'batter-genomes.html').write_text(directory_page(), encoding='utf-8')
    # Home is the same directory, with no second experimental catalogue.
    (site / 'index.html').write_text(directory_page(), encoding='utf-8')
    for name in ('catalog.html', 'catalogue.html', 'experimental.html'):
        (site / name).write_text(redirect_page(Path(name)), encoding='utf-8')
    for path in site.rglob('*.html'):
        if 'jbrowse' in path.relative_to(site).parts:
            continue
        html = present_hf_page(path.read_text(encoding='utf-8'), manifest, path.relative_to(site))
        path.write_text(html, encoding='utf-8')
        if path.parent.name in ('genomes', 'assemblies') or path.name in ('catalog.html', 'catalogue.html', 'experimental.html', 'browser.html'):
            path.write_text(redirect_page(path.relative_to(site)), encoding='utf-8')
    for name in ('batter-catalog.js', 'genome-page.js'):
        shutil.copyfile(Path(__file__).resolve().parents[1] / 'site/assets' / name, site / 'assets' / name)
    shutil.copyfile(Path(__file__).resolve().parents[1] / 'site/css/batter-catalog.css', site / 'css/batter-catalog.css')
    (site / 'assets/data-release.json').write_bytes(encode(manifest))
    (output / 'hf-preview.proof.json').write_bytes(encode({k: v for k, v in snapshot.items() if k not in ('genomes', 'groups')} | {'groups': [{k: v for k, v in group.items() if k != 'payload'} for group in snapshot['groups']]}))
    state = output / 'state/v3/d1/miniflare-D1DatabaseObject'
    state.mkdir(parents=True)
    shutil.copyfile(db, state / '9f2862f974ccfef58df965667dba7297341bf1a5ba8491f159d479f9b6ec469b.sqlite')
    config = dict(name='bted-v05-hf-preview', compatibility_date='2026-08-22',
                  main=str(Path(__file__).resolve().parents[1] / 'prototype/accession-range/src/worker.js'),
                  vars=dict(BTED_RELEASE_VERSION=VERSION, ALLOWED_ORIGIN_HOST='huggingface.co'),
                  d1_databases=[dict(binding='BTED_DB', database_name='bted-v05-local', database_id='5cb7131a-a937-4a41-9da6-bde22d605000')],
                  assets=dict(directory=str(site.resolve()), binding='ASSETS', run_worker_first=['/api/*', '/downloads/*']))
    (output / 'wrangler.json').write_bytes(encode(config))
    return manifest


def install_gateway(snapshot_path):
    """Install only preview code/receipt metadata; SSH keys stay on cu10."""
    data = snapshot_path.read_bytes()
    validate_snapshot(json.loads(gzip.decompress(data)))
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as archive:
        for name, content in [('bted_hf_gateway.py', Path(__file__).with_name('bted_hf_gateway.py').read_bytes()),
                              ('bted_hf_migrate.py', Path(__file__).with_name('bted_hf_migrate.py').read_bytes()),
                              ('bted_hf_preview.py', Path(__file__).read_bytes()),
                              (hashlib.sha256(data).hexdigest()[:16] + '.snapshot.gz', data)]:
            item = tarfile.TarInfo(name)
            item.size = len(content)
            archive.addfile(item, io.BytesIO(content))
    code = '''import io,json,os,subprocess,sys,tarfile
from pathlib import Path
root=Path('/home/sshlogin/bted_v05/preview')
changed=False
(root/'code').mkdir(parents=True,exist_ok=True,mode=0o700)
(root/'snapshots').mkdir(exist_ok=True,mode=0o700)
with tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read())) as archive:
 for item in archive:
  if item.name not in ('bted_hf_gateway.py','bted_hf_preview.py','bted_hf_migrate.py') and not __import__('re').fullmatch('[0-9a-f]{16}\\.snapshot\\.gz',item.name):raise ValueError('Unexpected gateway artifact')
  target=root/('snapshots' if item.name.endswith('.gz') else 'code')/item.name
  content=archive.extractfile(item).read()
  if item.name.endswith('.py') and (not target.exists() or target.read_bytes()!=content):changed=True
  temp=target.with_suffix('.partial')
  temp.write_bytes(content)
  os.replace(str(temp),str(target))
pidfile=root/'gateway.pid'
active=False
if pidfile.exists():
 pid=int(pidfile.read_text())
 try:
  cmd=Path('/proc/%d/cmdline'%pid).read_bytes()
  active=str(root/'code/bted_hf_gateway.py').encode() in cmd
 except OSError:pass
if active and changed:
 import signal,time
 os.kill(pid,signal.SIGTERM)
 for _ in range(50):
  if not Path('/proc/%d'%pid).exists():break
  time.sleep(.1)
 active=False
if not active:
 log=(root/'gateway.log').open('ab')
 child=subprocess.Popen(['/home/sshlogin/bted_v05/venv/bin/python','-u',str(root/'code/bted_hf_gateway.py'),'--snapshots',str(root/'snapshots'),'--relay-code','/home/sshlogin/bted_v05/code','--port','17997'],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
 pidfile.write_text(str(child.pid))
import socket,time
for attempt in range(120):
 try:
  with socket.create_connection(('127.0.0.1',17997),timeout=1):break
 except OSError:
  if attempt==119:raise RuntimeError('Private HF gateway did not become ready')
  time.sleep(1)
print('Read-only HF gateway ready; relay sender unchanged')
'''
    hop = ['ssh', '-p', '10383', '-i', '/home/liurulong/.ssh/id_ed25519', '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
           '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=/home/liurulong/terminator/release_bted_v05_state/sftpdrop_known_hosts',
           'sshlogin@ts3.zocomputer.io', 'python3 -c ' + shlex.quote(code)]
    subprocess.run(['C:/Windows/System32/OpenSSH/ssh.exe', '-o', 'UpdateHostKeys=no', '-o', 'BatchMode=yes', 'labx-cu010', shlex.join(hop)], input=buffer.getvalue(), check=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    export = sub.add_parser('export')
    export.add_argument('--release', type=Path, required=True)
    export.add_argument('--state', type=Path, required=True)
    fetch = sub.add_parser('fetch')
    fetch.add_argument('--host', default='labx-cu010')
    fetch.add_argument('--output', type=Path, required=True)
    build = sub.add_parser('build')
    build.add_argument('--snapshot', type=Path, required=True)
    build.add_argument('--baseline', type=Path, required=True)
    build.add_argument('--database', type=Path, required=True)
    build.add_argument('--output', type=Path, required=True)
    gateway = sub.add_parser('gateway-install')
    gateway.add_argument('--snapshot', type=Path, required=True)
    a = p.parse_args()
    if a.command == 'export':
        sys.stdout.buffer.write(gzip.compress(encode(export_snapshot(a.release, a.state))))
    elif a.command == 'fetch':
        a.output.parent.mkdir(parents=True, exist_ok=True)
        command = '/home/liurulong/soft/conda/envs/batter_env/bin/python - export --release /home/liurulong/terminator/release_bted_v05/v0.5.0 --state /home/liurulong/terminator/release_bted_v05_state/hf-relay-ts3'
        result = subprocess.run(['C:/Windows/System32/OpenSSH/ssh.exe', '-o', 'UpdateHostKeys=no', '-o', 'BatchMode=yes', a.host, command], input=Path(__file__).read_bytes(), stdout=subprocess.PIPE, check=True)
        snapshot = json.loads(gzip.decompress(result.stdout))
        validate_snapshot(snapshot)
        temp = a.output.with_suffix('.partial')
        temp.write_bytes(result.stdout)
        os.replace(str(temp), str(a.output))
        print('Verified receipt snapshot:', snapshot['available_genomes'], 'genomes')
    elif a.command == 'gateway-install':
        install_gateway(a.snapshot)
    else:
        snapshot = json.loads(gzip.decompress(a.snapshot.read_bytes()))
        manifest = stage_preview(snapshot, a.baseline, a.database, a.output)
        print('HF-only preview staged:', manifest['availableGenomeCount'], 'genomes')


if __name__ == '__main__':
    main()
