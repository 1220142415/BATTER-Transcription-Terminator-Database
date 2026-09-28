"""Serve a local v0.4 site while proxying only its pinned Hugging Face assets."""

from __future__ import annotations

import argparse
import json
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx


HF_URL = re.compile(
    r"^https://huggingface\.co/datasets/liurulong/terminator/resolve/"
    r"([0-9a-f]{40})/(v0\.3\.0|v0\.4\.0)/(.+)$"
)


def serve(root: Path, port: int, proxy: str) -> None:
    root = root.resolve()
    manifest = json.loads((root / "assets/data-release.json").read_text(encoding="utf-8"))
    if manifest.get("releaseVersion") != "v0.4.0":
        raise ValueError("preview requires a staged v0.4.0 site")
    allowed: dict[str, str] = {}
    replacements: dict[bytes, bytes] = {}
    for logical_path, item in manifest["assets"].items():
        url = item["url"]
        match = HF_URL.fullmatch(url)
        if not match or match.group(3) != logical_path:
            raise ValueError(f"unversioned or mismatched asset in preview manifest: {logical_path}")
        revision, version, _ = match.groups()
        allowed[f"/hf/{version}/{logical_path}"] = url
        old_base = f"https://huggingface.co/datasets/liurulong/terminator/resolve/{revision}/{version}"
        replacements[old_base.encode()] = f"http://127.0.0.1:{port}/hf/{version}".encode()
    client = httpx.Client(proxy=proxy, trust_env=False, follow_redirects=True, timeout=120)

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, directory=str(root), **kwargs)

        def do_HEAD(self) -> None:
            self._handle(head_only=True)

        def do_GET(self) -> None:
            self._handle(head_only=False)

        def _handle(self, *, head_only: bool) -> None:
            requested = unquote(urlsplit(self.path).path)
            if requested.startswith("/hf/"):
                remote = allowed.get(requested)
                if not remote:
                    self.send_error(404)
                    return
                headers = {"Range": self.headers["Range"]} if self.headers.get("Range") else {}
                try:
                    with client.stream("HEAD" if head_only else "GET", remote, headers=headers) as upstream:
                        self.send_response(upstream.status_code)
                        for name in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges", "ETag"):
                            if upstream.headers.get(name):
                                self.send_header(name, upstream.headers[name])
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.end_headers()
                        if not head_only:
                            for chunk in upstream.iter_bytes():
                                self.wfile.write(chunk)
                except (httpx.HTTPError, ConnectionError, BrokenPipeError) as exc:
                    print(f"preview proxy error for {requested}: {exc}", flush=True)
                return
            candidate = (root / requested.lstrip("/")).resolve()
            if not candidate.is_relative_to(root):
                self.send_error(403)
                return
            if candidate.is_file() and candidate.suffix.lower() in {".html", ".json", ".js", ".css"}:
                content = candidate.read_bytes()
                for old, new in replacements.items():
                    content = content.replace(old, new)
                self.send_response(200)
                self.send_header("Content-Type", self.guess_type(str(candidate)))
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                if not head_only:
                    self.wfile.write(content)
                return
            if head_only:
                super().do_HEAD()
            else:
                super().do_GET()

    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        print(f"Preview: http://127.0.0.1:{port}/", flush=True)
        server.serve_forever()
    finally:
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8769)
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    args = parser.parse_args()
    serve(args.site, args.port, args.proxy)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
