"""Build the v0.4 asset allowlist from release files and verified browser inputs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OLD_REVISION = "90651318aedf5a5ca26b8308070927d36fd3d6c9"
HF_PREFIX = "https://huggingface.co/datasets/liurulong/terminator/resolve"
SHARED_ROLES = {
    "reference_fai", "reference_fasta", "reference_gff3", "reference_tbi",
    "raw_bigwig_forward", "raw_bigwig_reverse",
}
COLUMNS = ("logical_path", "url", "byte_size", "sha256", "revision", "asset_kind")


def _kind(path: str) -> str:
    lower = path.lower()
    if lower.endswith((".gff3", ".gff3.gz")):
        return "gff3"
    if lower.endswith((".tsv", ".tsv.gz")):
        return "tsv"
    if lower.endswith(".fna"):
        return "fasta"
    if lower.endswith(".fai"):
        return "fai"
    if lower.endswith(".bw"):
        return "bigwig"
    if lower.endswith(".tbi"):
        return "tbi"
    if lower.endswith(".json"):
        return "json"
    if lower.endswith("sha256sums.txt"):
        return "checksum"
    raise ValueError(f"Unknown public asset kind: {path}")


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(release_root: Path, objects_root: Path, revision: str) -> list[dict[str, object]]:
    if revision != "local" and not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("v0.4 revision must be 'local' or a pinned 40-character commit")
    inventory = json.loads((ROOT / "data/registry/jbrowse_assets.v0.2.0.json").read_text(encoding="utf-8"))
    rows: dict[str, dict[str, object]] = {}
    for item in inventory["rows"]:
        if item["asset_role"] not in SHARED_ROLES or item["is_public"] != "true":
            continue
        logical_path = item["object_path"]
        if not logical_path or logical_path in rows:
            raise ValueError(f"Missing or duplicate shared asset path: {logical_path}")
        rows[logical_path] = {
            "logical_path": logical_path,
            "url": f"{HF_PREFIX}/{OLD_REVISION}/v0.3.0/{logical_path}",
            "byte_size": int(item["byte_size"]),
            "sha256": item["sha256"],
            "revision": OLD_REVISION,
            "asset_kind": item["asset_kind"],
        }
    if len(rows) != 84:
        raise ValueError(f"Expected 84 shared reference/signal assets, got {len(rows)}")

    for base in (release_root, objects_root / "v0.4.0"):
        if not base.is_dir():
            raise FileNotFoundError(base)
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            logical_path = path.relative_to(base).as_posix()
            if logical_path in rows:
                raise ValueError(f"Duplicate logical asset path: {logical_path}")
            url = (
                f"downloads/v0.4.0/{logical_path}"
                if revision == "local"
                else f"{HF_PREFIX}/{revision}/v0.4.0/{logical_path}"
            )
            rows[logical_path] = {
                "logical_path": logical_path,
                "url": url,
                "byte_size": path.stat().st_size,
                "sha256": _hash(path),
                "revision": revision,
                "asset_kind": _kind(logical_path),
            }
    return [rows[key] for key in sorted(rows)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-root", type=Path, default=ROOT / "data/public/v0.4.0")
    parser.add_argument("--objects-root", type=Path, default=ROOT / "dist/v04-browser-objects")
    parser.add_argument("--revision", default="local")
    parser.add_argument("--output", type=Path, default=ROOT / "data/registry/browser_assets.v0.4.0.tsv")
    args = parser.parse_args()
    rows = build_manifest(args.release_root, args.objects_root, args.revision)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"PASS: {len(rows)} pinned/local assets -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
