"""Serve a local v0.4 site while proxying only its pinned Hugging Face assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx


HF_URL = re.compile(
    r"^https://huggingface\.co/datasets/liurulong/terminator/resolve/"
    r"([0-9a-f]{40})/(v0\.3\.0|v0\.4\.0)/(.+)$"
)


def serve(root: Path, port: int, proxy: str, release_asset_dir: Path | None = None, browser_objects_root: Path | None = None) -> None:
    root = root.resolve()
    manifest = json.loads((root / "assets/data-release.json").read_text(encoding="utf-8"))
    if manifest.get("releaseVersion") != "v0.4.0":
        raise ValueError("preview requires a staged v0.4.0 site")
    allowed: dict[str, str] = {}
    local_assets: dict[str, Path] = {}
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
    if release_asset_dir is not None:
        bundle = release_asset_dir.resolve()
        inventory = json.loads((Path(__file__).resolve().parents[1] / "data/registry/jbrowse_assets.v0.2.0.json").read_text(encoding="utf-8"))
        for row in inventory["rows"]:
            logical = row["object_path"]
            key = f"/hf/v0.3.0/{logical}"
            expected = manifest["assets"].get(logical)
            if key not in allowed or not expected or expected["sha256"] != row["sha256"]:
                continue
            candidate = (bundle / row["bundle_path"]).resolve()
            if not candidate.is_relative_to(bundle) or not candidate.is_file():
                continue
            if candidate.stat().st_size != int(expected["byte_size"]) or hashlib.sha256(candidate.read_bytes()).hexdigest() != expected["sha256"]:
                raise ValueError(f"local preview asset differs from pinned data: {logical}")
            local_assets[key] = candidate
    if browser_objects_root is not None:
        repo = Path(__file__).resolve().parents[1]
        local_roots = (repo / "data/public/v0.4.0", browser_objects_root.resolve() / "v0.4.0")
        for logical, item in manifest["assets"].items():
            key = f"/hf/v0.4.0/{logical}"
            if key not in allowed:
                continue
            for local_root in local_roots:
                candidate = (local_root / logical).resolve()
                if not candidate.is_relative_to(local_root) or not candidate.is_file():
                    continue
                if candidate.stat().st_size != int(item["byte_size"]) or hashlib.sha256(candidate.read_bytes()).hexdigest() != item["sha256"]:
                    raise ValueError(f"local preview asset differs from pinned data: {logical}")
                local_assets[key] = candidate
                break
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
                local = local_assets.get(requested)
                if local is not None:
                    size = local.stat().st_size
                    match = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers.get("Range", "")) if self.headers.get("Range") else None
                    if self.headers.get("Range") and not match:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.end_headers()
                        return
                    start = int(match.group(1)) if match else 0
                    end = min(size - 1, int(match.group(2))) if match and match.group(2) else size - 1
                    if start >= size or end < start:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.end_headers()
                        return
                    self.send_response(206 if match else 200)
                    self.send_header("Content-Type", mimetypes.guess_type(local.name)[0] or "application/octet-stream")
                    self.send_header("Content-Length", str(end - start + 1))
                    self.send_header("Accept-Ranges", "bytes")
                    if match:
                        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    if not head_only:
                        with local.open("rb") as handle:
                            handle.seek(start)
                            self.wfile.write(handle.read(end - start + 1))
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
    parser.add_argument("--release-asset-dir", type=Path, help="Verified unpacked v0.2 JBrowse package for local preview only")
    parser.add_argument("--browser-objects-root", type=Path, help="Verified generated v0.4 browser objects for local preview only")
    args = parser.parse_args()
    serve(args.site, args.port, args.proxy, args.release_asset_dir, args.browser_objects_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
