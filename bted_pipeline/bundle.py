"""Verify a deterministic BTED materialization bundle without a database."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping
from urllib.parse import urlparse

from .materialize import MATERIALIZATION_SCHEMA_VERSION, TABLE_ORDER

RELEASE_VERSION_RE = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_TABLES = TABLE_ORDER


class BundleVerificationError(RuntimeError):
    """The materialized bundle is incomplete or inconsistent."""


@dataclass(frozen=True)
class BundleVerification:
    bundle_dir: Path
    manifest: dict[str, Any]
    table_files: dict[str, Path]
    table_metadata: dict[str, dict[str, Any]]

    @property
    def release_version(self) -> str:
        return str(self.manifest["release_version"])

    @property
    def table_counts(self) -> dict[str, int]:
        return {
            table: int(meta["row_count"])
            for table, meta in self.table_metadata.items()
        }


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_nonfinite)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise BundleVerificationError(f"cannot parse bundle metadata: {path.name}") from exc
    if not isinstance(value, dict):
        raise BundleVerificationError(f"bundle metadata must be an object: {path.name}")
    return value


def _sha256_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    try:
        handle = path.open(encoding="utf-8")
    except OSError as exc:
        raise BundleVerificationError(f"cannot open bundle table: {path.name}") from exc
    with handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                raise BundleVerificationError(f"blank JSONL line: {path.name}:{number}")
            try:
                value = json.loads(line, parse_constant=_reject_nonfinite)
            except (json.JSONDecodeError, ValueError) as exc:
                raise BundleVerificationError(f"invalid JSONL: {path.name}:{number}") from exc
            if not isinstance(value, dict):
                raise BundleVerificationError(f"JSONL row must be object: {path.name}:{number}")
            yield value


def _checksum_entries(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise BundleVerificationError("cannot read bundle SHA256SUMS.txt") from exc
    for number, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2 or not SHA256_RE.fullmatch(parts[0]):
            raise BundleVerificationError(f"invalid SHA256SUMS.txt line {number}")
        name = parts[1].lstrip("*")
        if not name or Path(name).name != name or name in entries:
            raise BundleVerificationError(f"invalid or duplicate checksum path: {name!r}")
        entries[name] = parts[0]
    return entries


def verify_bundle(bundle_dir: str | Path) -> BundleVerification:
    """Verify a B1 bundle without opening a database or retaining JSONL rows."""

    root = Path(bundle_dir).expanduser().resolve()
    if not root.is_dir():
        raise BundleVerificationError(f"bundle directory does not exist: {root}")
    manifest_path = root / "manifest.json"
    sums_path = root / "SHA256SUMS.txt"
    if not manifest_path.is_file() or not sums_path.is_file():
        raise BundleVerificationError("bundle must contain manifest.json and SHA256SUMS.txt")
    manifest = _json_object(manifest_path)
    release_version = str(manifest.get("release_version", ""))
    if not RELEASE_VERSION_RE.fullmatch(release_version):
        raise BundleVerificationError("bundle release_version is not semver vMAJOR.MINOR.PATCH")
    if manifest.get("materialization_schema_version") != MATERIALIZATION_SCHEMA_VERSION:
        raise BundleVerificationError("unsupported materialization schema version")
    if not str(manifest.get("materializer_version", "")).startswith("bted-materializer-"):
        raise BundleVerificationError("bundle materializer version is missing or invalid")
    if manifest.get("canonical_validation_status") != "validated":
        raise BundleVerificationError("bundle canonical_validation_status is not validated")
    if manifest.get("postgresql_ready") is not True:
        raise BundleVerificationError("bundle is not marked postgresql_ready")
    if manifest.get("write_mode") != "not_written":
        raise BundleVerificationError("bundle write_mode must be not_written")
    if manifest.get("unresolved") not in ([], None):
        raise BundleVerificationError("bundle contains unresolved items")
    origin = manifest.get("asset_origin")
    if not isinstance(origin, Mapping) or origin.get("asset_origin_status") not in {
        "planned_not_verified",
        "verified",
    }:
        raise BundleVerificationError("bundle asset_origin_status is missing or invalid")
    origin_base = str(origin.get("base", "")).rstrip("/")
    parsed_base = urlparse(origin_base)
    if parsed_base.scheme != "https" or not parsed_base.hostname:
        raise BundleVerificationError("bundle asset origin base must be HTTPS")
    if str(origin.get("host", "")) != parsed_base.hostname:
        raise BundleVerificationError("bundle asset origin host does not match base")
    tables = manifest.get("tables")
    if not isinstance(tables, Mapping) or set(tables) != set(EXPECTED_TABLES):
        raise BundleVerificationError("bundle table set does not match the bundle contract")

    table_files: dict[str, Path] = {}
    table_metadata: dict[str, dict[str, Any]] = {}
    expected_names = {"manifest.json", "SHA256SUMS.txt"}
    for table in EXPECTED_TABLES:
        meta = tables.get(table)
        if not isinstance(meta, Mapping):
            raise BundleVerificationError(f"table metadata is not an object: {table}")
        file_name = str(meta.get("file", ""))
        if not file_name or Path(file_name).name != file_name or not file_name.endswith(".jsonl"):
            raise BundleVerificationError(f"invalid table file name: {table}")
        if not isinstance(meta.get("row_count"), int) or int(meta["row_count"]) < 0:
            raise BundleVerificationError(f"invalid row_count: {table}")
        if (
            not isinstance(meta.get("byte_size"), int)
            or isinstance(meta.get("byte_size"), bool)
            or int(meta["byte_size"]) < 0
        ):
            raise BundleVerificationError(f"invalid byte_size: {table}")
        if not SHA256_RE.fullmatch(str(meta.get("sha256", ""))):
            raise BundleVerificationError(f"invalid table SHA-256: {table}")
        path = root / file_name
        if not path.is_file():
            raise BundleVerificationError(f"missing table file: {file_name}")
        if file_name in expected_names:
            raise BundleVerificationError(f"duplicate bundle file: {file_name}")
        expected_names.add(file_name)
        table_files[table] = path
        table_metadata[table] = dict(meta)

    entries = list(root.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in entries):
        raise BundleVerificationError("bundle root contains a directory or symbolic link")
    actual_names = {path.name for path in entries}
    if actual_names != expected_names:
        extra = sorted(actual_names - expected_names)
        missing = sorted(expected_names - actual_names)
        raise BundleVerificationError(f"bundle file set mismatch; extra={extra}, missing={missing}")
    sums = _checksum_entries(sums_path)
    expected_checksum_names = expected_names - {"SHA256SUMS.txt"}
    if set(sums) != expected_checksum_names:
        extra = sorted(set(sums) - expected_checksum_names)
        missing = sorted(expected_checksum_names - set(sums))
        raise BundleVerificationError(f"bundle checksum file set mismatch; extra={extra}, missing={missing}")
    for name in sorted(expected_checksum_names):
        actual, byte_size = _sha256_and_size(root / name)
        if actual != sums[name]:
            raise BundleVerificationError(f"bundle checksum mismatch: {name}")
        if name == "manifest.json":
            continue
        table = next(table for table, path in table_files.items() if path.name == name)
        meta = table_metadata[table]
        if actual != str(meta["sha256"]) or byte_size != int(meta["byte_size"]):
            raise BundleVerificationError(f"table checksum/byte_size metadata mismatch: {table}")
        count = 0
        for _ in _iter_jsonl(root / name):
            count += 1
        if count != int(meta["row_count"]):
            raise BundleVerificationError(
                f"table row_count mismatch: {table} ({count} != {meta['row_count']})"
            )
    # Release-level counters are part of the B1 manifest and must agree with
    # the table metadata before any SQL is attempted.
    source_count = manifest.get("source_count")
    annotation_count = manifest.get("source_annotation_materialized_row_count")
    if (
        isinstance(source_count, bool)
        or not isinstance(source_count, int)
        or source_count != int(table_metadata["sources"]["row_count"])
    ):
        raise BundleVerificationError("manifest source_count does not match sources table")
    if (
        isinstance(annotation_count, bool)
        or not isinstance(annotation_count, int)
        or annotation_count != int(table_metadata["source_annotations"]["row_count"])
    ):
        raise BundleVerificationError("manifest source annotation count does not match table")
    gene_count = manifest.get("gene_count", 0)
    context_count = manifest.get("endpoint_gene_context_count", 0)
    contig_count = manifest.get("contig_count", int(table_metadata["contigs"]["row_count"]))
    if (
        isinstance(contig_count, bool)
        or not isinstance(contig_count, int)
        or contig_count != int(table_metadata["contigs"]["row_count"])
    ):
        raise BundleVerificationError("manifest contig count does not match contigs table")
    if (
        isinstance(gene_count, bool)
        or not isinstance(gene_count, int)
        or gene_count != int(table_metadata["genes"]["row_count"])
    ):
        raise BundleVerificationError("manifest gene count does not match genes table")
    if (
        isinstance(context_count, bool)
        or not isinstance(context_count, int)
        or context_count != int(table_metadata["endpoint_gene_context"]["row_count"])
    ):
        raise BundleVerificationError("manifest endpoint_gene_context count does not match table")
    return BundleVerification(root, manifest, table_files, table_metadata)


def verify_summary(verification: BundleVerification) -> dict[str, Any]:
    return {
        "release_version": verification.release_version,
        "status": "verified",
        "counts": verification.table_counts,
        "asset_origin_status": verification.manifest["asset_origin"]["asset_origin_status"],
    }
