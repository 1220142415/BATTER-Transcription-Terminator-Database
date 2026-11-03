"""Index the uncompressed official FFN TAR with bounded, resumable HTTP ranges.

Only TAR headers are interpreted; gzip member payloads are not downloaded here.
Partition checkpoints avoid fetching already scanned headers on restart.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import tarfile
import threading
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

URL = 'https://portal.nersc.gov/GEM/genomes/ffn.tar'
LOCAL = threading.local()

def session():
    if not hasattr(LOCAL, 'http'):
        LOCAL.http = requests.Session()
        # The official GEM host is directly reachable; do not spend proxy quota.
        LOCAL.http.trust_env = False
        LOCAL.http.mount('https://', HTTPAdapter(max_retries=Retry(total=4, backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504])))
    return LOCAL.http

def fetch(start, end, identity):
    end = min(end, identity['bytes'] - 1)
    r = session().get(URL, headers={'Range': f'bytes={start}-{end}', 'If-Match': identity['etag']}, timeout=(20, 90))
    r.raise_for_status()
    if r.status_code != 206 or r.headers.get('Content-Range') != f"bytes {start}-{end}/{identity['bytes']}":
        raise ValueError('server_did_not_honor_range')
    if r.headers.get('ETag') != identity['etag'] or len(r.content) != end-start+1:
        raise ValueError('archive_changed_or_incomplete_range')
    return r.content

def header(buf):
    if len(buf) != 512 or buf == bytes(512):
        return None
    try:
        item = tarfile.TarInfo.frombuf(buf, 'utf-8', 'strict')
        if item.size < 0 or not (item.name == 'ffn' or item.name.startswith('ffn/') or item.name.startswith('./PaxHeaders.')):
            return None
        return item
    except (tarfile.TarError, ValueError, UnicodeError):
        return None

def scan(part, start, stop, identity, out):
    checkpoint = out / f'part-{part:03d}.json'
    log = out / f'part-{part:03d}.jsonl'
    state = json.loads(checkpoint.read_text()) if checkpoint.exists() else {'next': start, 'complete': False}
    if state['complete']:
        return part
    pos = state['next']
    buffer = b''
    base = -1
    def get(offset, count=512):
        nonlocal buffer, base
        if not base <= offset or offset+count > base+len(buffer):
            base = offset
            buffer = fetch(base, base + 65536 - 1, identity)
        return buffer[offset-base:offset-base+count]
    # A partition may start inside a compressed member. Search only 512-aligned
    # blocks; TarInfo validates the TAR checksum before trusting size/name.
    while pos < stop and header(get(pos)) is None:
        pos += 512
    with log.open('a', encoding='utf-8') as stream:
        while pos < stop:
            raw = get(pos)
            item = header(raw)
            if item is None:
                if raw == bytes(512) and pos > identity['bytes']-10240:
                    break
                raise ValueError(f'invalid_header_at_{pos}')
            next_pos = pos + 512 + ((item.size + 511)//512)*512
            if item.isfile() and item.name.endswith('.ffn.gz'):
                stream.write(json.dumps({'member': item.name, 'offset': pos+512, 'bytes': item.size})+'\n')
                stream.flush()
            pos = next_pos
            tmp = checkpoint.with_suffix('.tmp')
            tmp.write_text(json.dumps({'next': pos, 'complete': False}))
            tmp.replace(checkpoint)
    checkpoint.write_text(json.dumps({'next': pos, 'complete': True}))
    return part

def build(out, workers=24, partitions=128):
    out.mkdir(parents=True, exist_ok=True)
    r=session().head(URL,timeout=(20,60)); r.raise_for_status()
    identity={'url':URL,'bytes':int(r.headers['Content-Length']),'etag':r.headers['ETag'],
              'last_modified':r.headers.get('Last-Modified'),'partitions':partitions}
    pin=out/'archive.json'
    if pin.exists() and json.loads(pin.read_text()) != identity:
        raise ValueError('archive_identity_changed_use_fresh_output')
    pin.write_text(json.dumps(identity,indent=2)+'\n')
    stride=((identity['bytes']//partitions+511)//512)*512
    started=time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        tasks=[pool.submit(scan,p,p*stride,min((p+1)*stride,identity['bytes']),identity,out) for p in range(partitions)]
        for n,f in enumerate(as_completed(tasks),1):
            print('INDEX_PART',f.result(),'complete',n,'/',partitions,'seconds',round(time.time()-started),flush=True)
    entries={}
    for p in out.glob('part-*.jsonl'):
        for line in p.read_text().splitlines():
            row=json.loads(line)
            if row['member'] in entries and entries[row['member']] != row:
                raise ValueError('conflicting_member_offsets')
            entries[row['member']]=row
    index={'archive':identity,'complete':True,'members':entries}
    (out/'index.json').write_text(json.dumps(index,indent=2)+'\n')
    print('INDEX_COMPLETE',len(entries),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=24)
    args=parser.parse_args()
    build(args.output,args.workers)
