"""Keep one local preview URL while activating verified HF snapshot backends."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import socket
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


def get_json(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def stop_candidate(candidate):
    """Release only an owned candidate Worker; preserve its snapshot files."""
    area = Path(__file__).resolve().parents[1] / 'dist/v05-hf-preview/snapshots'
    candidate = candidate.resolve()
    if not candidate.is_relative_to(area.resolve()) or not (candidate / 'worker.pid').is_file():
        return
    try:
        import psutil
        process = psutil.Process(int((candidate / 'worker.pid').read_text()))
        command = process.cmdline()
        configured = Path(command[command.index('--config') + 1]).resolve()
        if configured != candidate / 'wrangler.json': return
        descendants = process.children(recursive=True)
        process.terminate()
        for child in reversed(descendants):
            try: child.terminate()
            except psutil.NoSuchProcess: pass
    except (ImportError, OSError, ValueError):
        pass
    except psutil.Error:
        pass


def activate(candidate, backend, pointer):
    parsed = urlsplit(backend)
    if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise ValueError('Preview backend must be loopback')
    expected = json.loads((candidate / 'site/assets/data-release.json').read_text(encoding='utf-8'))
    actual = get_json(backend + '/assets/data-release.json')
    health = get_json(backend + '/api/health')
    if actual != expected or health['release']['canonical_manifest_sha256'] != expected['releaseManifestSha256']:
        raise ValueError('Preview backend does not match the candidate')
    old = json.loads(pointer.read_text(encoding='utf-8')) if pointer.exists() else None
    ids = actual['batterBrowser']['preparedGenomeIds']
    newly_available = old.get('available_genomes', 0) if old else 0
    genome = ids[newly_available] if newly_available < len(ids) else ids[0]
    detail = get_json(backend + '/api/genomes/' + genome)['data']
    file = next(f for f in detail['batter']['downloads'] if f['filename'] == 'reference.fa.gz.fai')
    with urllib.request.urlopen(urllib.request.Request(file['url'], method='HEAD'), timeout=90) as response:
        if response.status != 200 or int(response.headers['Content-Length']) != file['byte_size']:
            raise ValueError('HF HEAD acceptance failed')
    end = min(63, file['byte_size'] - 1)
    with urllib.request.urlopen(urllib.request.Request(file['url'], headers={'Range': 'bytes=0-%d' % end}), timeout=90) as response:
        range_bytes = response.read()
        if response.status != 206 or response.headers['Content-Range'] != 'bytes 0-%d/%d' % (end, file['byte_size']) or len(range_bytes) != end + 1:
            raise ValueError('HF Range acceptance failed')
    with urllib.request.urlopen(file['url'], timeout=90) as response:
        downloaded = response.read()
        if len(downloaded) != file['byte_size'] or downloaded[:end+1] != range_bytes or hashlib.sha256(downloaded).hexdigest() != file['sha256']:
            raise ValueError('HF download SHA acceptance failed')
    report = dict(status='verified_preview', available_genomes=expected['availableGenomeCount'],
                  release_manifest_sha256=expected['releaseManifestSha256'], sample=file,
                  head_verified=True, range_verified=True, download_sha256_verified=True)
    (candidate / 'activation.acceptance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    pointer.parent.mkdir(parents=True, exist_ok=True)
    record = dict(backend=backend, candidate=str(candidate.resolve()), available_genomes=expected['availableGenomeCount'],
                  publication_status=expected['publicationStatus'], release_manifest_sha256=expected['releaseManifestSha256'],
                  revision=expected['releaseRevision'], previous=({k: v for k, v in old.items() if k != 'previous'} if old else None))
    temp = pointer.with_suffix('.partial')
    temp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(str(temp), str(pointer))
    if old and old.get('previous'):
        obsolete = Path(old['previous']['candidate'])
        if obsolete.resolve() not in (candidate.resolve(), Path(old['candidate']).resolve()): stop_candidate(obsolete)
    return record


def serve(pointer, port):
    import httpx
    client = httpx.Client(trust_env=False, timeout=120)
    public = 'http://127.0.0.1:' + str(port)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def do_GET(self): self.forward(False)
        def do_HEAD(self): self.forward(True)

        def forward(self, head):
            record = json.loads(pointer.read_text(encoding='utf-8'))
            backend = record['backend']
            if not re.fullmatch(r'http://127\.0\.0\.1:\d+', backend):
                self.send_error(503)
                return
            headers = {k: self.headers[k] for k in ('Range', 'If-Range', 'If-None-Match', 'If-Modified-Since') if self.headers.get(k)}
            headers['Accept-Encoding'] = 'identity'
            mutable = self.path.startswith('/assets/data-release.json') or (self.path.startswith('/api/') and '/files/' not in self.path and not self.path.startswith('/api/assets/'))
            if mutable:
                headers.pop('If-None-Match', None)
                headers.pop('If-Modified-Since', None)
            started = False
            try:
                with client.stream('HEAD' if head else 'GET', backend + self.path, headers=headers) as upstream:
                    metadata = 'application/json' in upstream.headers.get('content-type', '') and not head
                    data = upstream.read().replace(backend.encode(), public.encode()) if metadata else None
                    self.send_response(upstream.status_code)
                    for key, value in upstream.headers.items():
                        if key.lower() not in ('connection', 'transfer-encoding', 'content-length', 'content-encoding'):
                            if mutable and key.lower() in ('cache-control', 'etag', 'last-modified'): continue
                            self.send_header(key, value.replace(backend, public))
                    if mutable: self.send_header('Cache-Control', 'no-store')
                    size = str(len(data)) if metadata else upstream.headers.get('content-length')
                    if size: self.send_header('Content-Length', size)
                    else: self.send_header('Connection', 'close'); self.close_connection = True
                    self.end_headers()
                    started = True
                    if not head:
                        if metadata: self.wfile.write(data)
                        else:
                            for chunk in upstream.iter_raw(): self.wfile.write(chunk)
            except (httpx.HTTPError, OSError):
                if not started:
                    self.send_response(502)
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                self.close_connection = True

    print('HF preview:', public, flush=True)
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()


def refresh(pointer, gateway, snapshot_path=None, force=False):
    """Build/test a fresh backend; replace only the verified frontend pointer."""
    import gzip
    import shutil
    import bted_hf_preview as builder
    root = Path(__file__).resolve().parents[1]
    area = root / 'dist/v05-hf-preview'
    if snapshot_path is None:
        snapshot_path = area / 'snapshot.next.json.gz'
        subprocess.run([sys.executable, str(root / 'scripts/bted_hf_preview.py'), 'fetch', '--output', str(snapshot_path)], check=True)
    snapshot = json.loads(gzip.decompress(snapshot_path.read_bytes()))
    builder.validate_snapshot(snapshot)
    old = json.loads(pointer.read_text(encoding='utf-8')) if pointer.exists() else None
    full = bool(snapshot.get('complete_release_proof'))
    desired_sha = snapshot['migration']['plan']['manifest_sha256'] if snapshot.get('migration') else snapshot['release_manifest_sha256']
    if not force and old and old['available_genomes'] == snapshot['available_genomes'] and (old['publication_status'] == 'public_download') == full and old.get('release_manifest_sha256', desired_sha) == desired_sha:
        print('No newly verified preview data')
        return
    candidate = area / 'snapshots' / time.strftime('%Y%m%d-%H%M%S')
    baseline_db = next(p for p in (root / 'dist/v05-preview/state/v3/d1/miniflare-D1DatabaseObject').glob('*.sqlite') if p.name != 'metadata.sqlite')
    builder.stage_preview(snapshot, root / 'dist/v05-worker-site-r3', baseline_db, candidate)
    if gateway:
        builder.install_gateway(snapshot_path)
        folder = area / 'gateway-snapshots'
        folder.mkdir(exist_ok=True)
        shutil.copyfile(snapshot_path, folder / (hashlib.sha256(snapshot_path.read_bytes()).hexdigest()[:16] + '.snapshot.gz'))
        config = json.loads((candidate / 'wrangler.json').read_text(encoding='utf-8'))
        config['vars']['HF_PREVIEW_GATEWAY'] = gateway
        (candidate / 'wrangler.json').write_text(json.dumps(config), encoding='utf-8')
    with socket.socket() as free:
        free.bind(('127.0.0.1', 0))
        port = free.getsockname()[1]
    # Find the installed Node runtime rather than relying on the shell PATH.
    node = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
    log = (candidate / 'worker.log').open('ab')
    child = subprocess.Popen([str(node), str(root / 'dist/wrangler/node_modules/wrangler/bin/wrangler.js'), 'dev', '--local',
        '--config', str(candidate / 'wrangler.json'), '--persist-to', str(candidate / 'state'), '--ip', '127.0.0.1', '--port', str(port),
        '--inspector-port', '0'], stdin=subprocess.DEVNULL, stdout=log, stderr=log,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    (candidate / 'worker.pid').write_text(str(child.pid))
    backend = 'http://127.0.0.1:' + str(port)
    for _ in range(45):
        if child.poll() is not None: raise RuntimeError('Candidate Worker stopped; previous preview remains active')
        try:
            get_json(backend + '/api/health')
            break
        except (OSError, ValueError): time.sleep(1)
    try:
        activate(candidate, backend, pointer)
    except Exception:
        stop_candidate(candidate)
        raise
    print('Preview snapshot activated:', snapshot['available_genomes'], 'genomes')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    server = sub.add_parser('serve')
    server.add_argument('--pointer', type=Path, required=True)
    server.add_argument('--port', type=int, default=8797)
    activation = sub.add_parser('activate')
    activation.add_argument('--candidate', type=Path, required=True)
    activation.add_argument('--backend', required=True)
    activation.add_argument('--pointer', type=Path, required=True)
    update = sub.add_parser('refresh')
    update.add_argument('--pointer', type=Path, required=True)
    update.add_argument('--gateway')
    update.add_argument('--snapshot', type=Path, help='Revalidate a previously fetched receipt snapshot')
    update.add_argument('--force', action='store_true', help='Rebuild UI even when no new batch is available')
    a = p.parse_args()
    if a.command == 'serve': serve(a.pointer, a.port)
    elif a.command == 'activate': print(activate(a.candidate, a.backend, a.pointer))
    else: refresh(a.pointer, a.gateway, a.snapshot, a.force)
