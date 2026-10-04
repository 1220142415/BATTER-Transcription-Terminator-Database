"""Private loopback gateway for immutable HF files; contains no genome payload.

Run behind SSH on the relay host when the Windows preview cannot reach HF.
Only paths from validated successful batch receipts can pass through.
"""
import argparse
import gzip
import json
import sys
import threading
import subprocess
import shlex
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def snapshot_allowlist(path):
    """Validate one snapshot and release its metadata before loading the next."""
    import bted_hf_preview as preview
    result = {}
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        snapshot = json.load(stream)
    groups = preview.validate_snapshot(snapshot)
    if snapshot.get('migration'):
        migration = snapshot['migration']
        from bted_hf_migrate import effective_revision
        revision = effective_revision(migration)
        for row in migration['plan']['files']:
            key = '/datasets/' + preview.REPO + '/resolve/' + revision + '/' + preview.VERSION + '/' + urllib.parse.quote(row['path'], safe='/')
            result[key] = row['byte_size']
        return result
    full = snapshot.get('complete_release_proof')
    for genome in snapshot['genomes']:
        revision = full['hf_revision'] if full else groups['batter-' + genome['batch']]['revision']
        for file in genome['files'].values():
            key = '/datasets/' + preview.REPO + '/resolve/' + revision + '/' + preview.VERSION + '/' + urllib.parse.quote(file['logical_path'], safe='/')
            result[key] = file['byte_size']
    for group in ('experimental', 'release-controls'):
        if group not in groups:
            continue
        revision = full['hf_revision'] if full else groups[group]['revision']
        for name, row in groups[group]['inventory'].items():
            if name == 'README.md':
                continue
            key = '/datasets/' + preview.REPO + '/resolve/' + revision + '/' + preview.VERSION + '/' + urllib.parse.quote(name, safe='/')
            result[key] = row['bytes']
    return result


class SnapshotAllowlist:
    def __init__(self, snapshot_dir):
        self.snapshot_dir = Path(snapshot_dir)
        self.allowed = {}
        self.loaded = set()
        self.lock = threading.Lock()

    def lookup(self, request_path):
        with self.lock:
            if request_path in self.allowed:
                return self.allowed[request_path]
            # A current receipt snapshot also contains earlier verified batches.
            # Read history only when the requested fixed revision needs it.
            paths = sorted(self.snapshot_dir.glob('*.snapshot.gz'), key=lambda p: p.stat().st_mtime_ns, reverse=True)
            for path in paths:
                if path.name in self.loaded:
                    continue
                self.allowed.update(snapshot_allowlist(path))
                self.loaded.add(path.name)
                if request_path in self.allowed:
                    return self.allowed[request_path]
            return None


def serve(snapshot_dir, port, ssh_bridge=False):
    allowlist = SnapshotAllowlist(snapshot_dir)
    relay_slots = threading.BoundedSemaphore(4)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def do_GET(self): self.handle_file(False)
        def do_HEAD(self): self.handle_file(True)

        def error(self, status):
            self.send_response(status)
            self.send_header('Content-Length', '0')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()

        def handle_file(self, head):
            # Exact URL path allowlist: no caller-selected origins or credentials.
            total = allowlist.lookup(self.path)
            if total is None:
                return self.error(404)
            if ssh_bridge:
                return self.bridge_file(head)
            headers = {'Accept-Encoding': 'identity'}
            if self.headers.get('Range'):
                headers['Range'] = self.headers['Range']
            try:
                req = urllib.request.Request('https://huggingface.co' + self.path, headers=headers, method='HEAD' if head else 'GET')
                with urllib.request.urlopen(req, timeout=90) as upstream:
                    if upstream.status not in (200, 206):
                        return self.error(502)
                    size = upstream.headers.get('Content-Length')
                    if upstream.status == 200 and size and int(size) != total:
                        return self.error(502)
                    self.send_response(upstream.status)
                    for name in ('Content-Type', 'Content-Length', 'Content-Range', 'Accept-Ranges'):
                        if upstream.headers.get(name): self.send_header(name, upstream.headers[name])
                    if not size: self.send_header('Content-Length', str(total))
                    self.end_headers()
                    if not head:
                        while True:
                            data = upstream.read(65536)
                            if not data: break
                            self.wfile.write(data)
            except urllib.error.HTTPError as error:
                self.error(503 if error.code in (429, 503) else 502)
            except (OSError, urllib.error.URLError):
                self.close_connection = True

        def bridge_file(self, head):
            with relay_slots:
                return self.stream_bridge(head)

        def stream_bridge(self, head):
            # Some relay SSH frontends expose exec channels only. Stream the
            # private gateway's HTTP response over an authenticated exec channel.
            code = '''import json,sys,urllib.request,urllib.error
spec=json.load(sys.stdin)
if not spec['path'].startswith('/datasets/liurulong/terminator/resolve/') or '?' in spec['path']:raise ValueError('Unknown asset')
req=urllib.request.Request('http://127.0.0.1:17997'+spec['path'],method=spec['method'],headers=spec['headers'])
try:r=urllib.request.urlopen(req,timeout=90)
except urllib.error.HTTPError as e:r=e
headers={k:v for k,v in r.headers.items() if k.lower() in ('content-length','content-range','content-type','accept-ranges','cache-control')}
sys.stdout.buffer.write((json.dumps({'status':r.status,'headers':headers})+'\\n').encode())
sys.stdout.buffer.flush()
if spec['method']!='HEAD':
 while True:
  b=r.read(65536)
  if not b:break
  sys.stdout.buffer.write(b)
  sys.stdout.buffer.flush()
'''
            hop = ['ssh', '-p', '10383', '-i', '/home/liurulong/.ssh/id_ed25519', '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3', '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
                   '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=/home/liurulong/terminator/release_bted_v05_state/sftpdrop_known_hosts',
                   'sshlogin@ts3.zocomputer.io', 'python3 -c ' + shlex.quote(code)]
            command = ['C:/Windows/System32/OpenSSH/ssh.exe', '-o', 'UpdateHostKeys=no', '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3', '-o', 'BatchMode=yes', 'labx-cu010', shlex.join(hop)]
            spec = json.dumps(dict(path=self.path, method='HEAD' if head else 'GET',
                                   headers={'Range': self.headers['Range']} if self.headers.get('Range') else {})).encode()
            child, metadata = None, None
            for attempt in range(3):
                child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                         creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                try:
                    child.stdin.write(spec)
                    child.stdin.close()
                    metadata = json.loads(child.stdout.readline(16384))
                    if metadata['status'] not in (429, 502, 503, 504): break
                except (ValueError, OSError, KeyError):
                    metadata = None
                child.stdout.close()
                if child.poll() is None: child.terminate()
                child.wait()
                if attempt < 2: time.sleep(2 ** attempt)
            if metadata is None or metadata['status'] in (429, 502, 503, 504):
                return self.error(503)
            try:
                self.send_response(metadata['status'])
                for key, value in metadata['headers'].items(): self.send_header(key, value)
                self.end_headers()
                if not head:
                    while True:
                        data = child.stdout.read(65536)
                        if not data: break
                        self.wfile.write(data)
            except (ValueError, OSError):
                self.close_connection = True
            finally:
                child.stdout.close()
                if child.poll() is None: child.terminate()
                child.wait()

    print('HF receipt gateway listening on loopback:', port, flush=True)
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshots', type=Path, required=True)
    p.add_argument('--port', type=int, default=17997)
    p.add_argument('--relay-code', type=Path)
    p.add_argument('--ssh-bridge', action='store_true')
    a = p.parse_args()
    if a.relay_code: sys.path.insert(0, str(a.relay_code))
    serve(a.snapshots, a.port, a.ssh_bridge)
