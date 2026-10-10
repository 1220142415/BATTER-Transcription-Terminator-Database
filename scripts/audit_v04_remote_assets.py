"""Verify pinned public assets by downloading their bytes and checking Range reads."""

import argparse
import csv
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(row):
    result = {"logical_path": row["logical_path"], "url": row["url"]}
    try:
        require(re.fullmatch(
            r"https://huggingface\.co/datasets/liurulong/terminator/resolve/[0-9a-f]{40}/v0\.[34]\.0/[^?#]+",
            row["url"],
        ), "asset URL must be pinned")
        digest = hashlib.sha256()
        size = 0
        with urlopen(row["url"], timeout=90) as response:
            require(response.status == 200, "full download must return 200")
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        require(size == int(row["byte_size"]), "byte size mismatch")
        require(digest.hexdigest() == row["sha256"], "SHA-256 mismatch")
        result.update(byte_size=size, sha256=digest.hexdigest())
        if row["asset_kind"] in {"fasta", "gff3", "bigwig", "tbi"}:
            request = Request(row["url"] + "?bted_range_audit=1", headers={"Range": "bytes=0-0", "Origin": "https://bted.workers.dev"})
            with urlopen(request, timeout=90) as response:
                require(response.status == 206, "Range must return 206")
                require(response.headers.get("Content-Range") == f"bytes 0-0/{size}", "Range length mismatch")
                require(len(response.read()) == 1, "Range body mismatch")
                require(response.headers.get("Access-Control-Allow-Origin") in {"*", "https://bted.workers.dev"}, "cross-origin read unavailable")
            result["range_status"] = 206
        result["status"] = "verified"
    except Exception as error:
        result.update(status="failed", error=str(error))
    print(result["status"], row["logical_path"], result.get("error", ""), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("data/registry/browser_assets.v0.4.0.tsv"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.manifest.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(verify, rows))
    failed = sum(row["status"] != "verified" for row in results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"checked_at": datetime.now(timezone.utc).isoformat(), "manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(), "failed": failed, "assets": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Verified {len(results) - failed}/{len(results)} assets")
    return bool(failed)


if __name__ == "__main__":
    raise SystemExit(main())
