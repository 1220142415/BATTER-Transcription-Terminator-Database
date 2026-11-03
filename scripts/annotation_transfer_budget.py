"""Count proxied HTTP bodies and stop at a shared per-run byte allowance."""
import json
from pathlib import Path
import threading

CAP = 20_000_000_000  # Leave at least 5 GB of the user's remaining quota untouched.


class Budget:
    def __init__(self, path, cap=CAP):
        self.path, self.cap = Path(path), cap
        self.lock = threading.Lock()
        self.used = sum(json.loads(line)['bytes'] for line in self.path.read_text().splitlines()) if self.path.exists() else 0

    def charge(self, count):
        with self.lock:
            if self.used+count > self.cap:
                raise RuntimeError('proxy_transfer_budget_exhausted')
            self.used += count

    def record(self, kind, count):
        if count:
            with self.lock, self.path.open('a') as stream:
                stream.write(json.dumps({'kind':kind,'bytes':count})+'\n')

    def client(self):
        """Official HF client factory; credentials remain managed by huggingface_hub."""
        import httpx
        meter = self

        class Counted(httpx.SyncByteStream):
            def __init__(self, stream, kind):
                self.stream, self.kind, self.count = stream, kind, 0
                self.recorded = False

            def __iter__(self):
                try:
                    for chunk in self.stream:
                        meter.charge(len(chunk)); self.count += len(chunk)
                        yield chunk
                finally:
                    self.finish()

            def finish(self):
                if not self.recorded:
                    meter.record(self.kind,self.count); self.recorded=True

            def close(self):
                self.finish(); self.stream.close()

        def request_hook(request):
            request.stream = Counted(request.stream,'hf_upload_or_api_request')

        def response_hook(response):
            response.stream = Counted(response.stream,'hf_download_or_api_response')

        return httpx.Client(follow_redirects=True, timeout=httpx.Timeout(180,connect=30),
                            event_hooks={'request':[request_hook],'response':[response_hook]})
