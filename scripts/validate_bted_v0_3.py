#!/usr/bin/env python3
"""Validate BTED v0.3.0 checksums, archive integrity, and lossless table migration."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import sys
import tarfile
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.v03_tables import (
    ANNOTATION_ATTRIBUTE_PREFIX,
    ENDPOINT_COLUMNS,
    RELATED_TABLE_PMIDS,
    STUDY_METADATA_TSV_COLUMNS,
    iter_annotations,
    iter_endpoints,
    iter_related_rows,
    iter_study_metadata,
    load_source_index,
    source_pmid,
    source_record_count,
    study_metadata_tsv_row,
)


ROOT = Path(__file__).resolve().parents[1]
LEGACY_REL = Path("data/public/v0.2.0")
RELEASE_REL = Path("data/public/v0.3.0")
ARCHIVE_REL = Path("data/archive/BTED-v0.2.0.tar.gz")
ARCHIVE_SUMS_REL = Path("data/archive/BTED-v0.2.0.SHA256SUMS.txt")
ARCHIVE_HASH_REL = Path("data/archive/BTED-v0.2.0.tar.gz.sha256")
EXPECTED_LEGACY_FILES = 153
EXPECTED_ENDPOINTS = 28_399
EXPECTED_UNLINKED_GENE_ASSOCIATIONS = 345
RELEASE_FILES = {"studies", "release.json", "SHA256SUMS.txt"}
STUDY_BASE_FILES = {"endpoints.gff3.gz", "metadata.json", "metadata.tsv"}
EXPECTED_SOURCE_COUNT = 22
EXPECTED_STUDY_COUNT = 13


def _fail(message: str) -> None:
    raise ValueError(message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames:
            _fail(f"Missing TSV header: {path}")
        return list(reader.fieldnames), [dict(row) for row in reader]


def _read_tsv_bytes(payload: bytes, label: str) -> tuple[list[str], list[dict[str, str]]]:
    handle = io.StringIO(payload.decode("utf-8-sig"), newline="")
    reader = csv.DictReader(handle, delimiter="\t")
    if not reader.fieldnames:
        _fail(f"Missing TSV header: {label}")
    return list(reader.fieldnames), [dict(row) for row in reader]


def _read_gzip_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames:
            _fail(f"Missing compressed TSV header: {path}")
        return list(reader.fieldnames), [dict(row) for row in reader]


def _safe_member_name(name: str) -> None:
    parsed = PurePosixPath(name)
    if "\\" in name or parsed.is_absolute() or ".." in parsed.parts or not parsed.parts:
        _fail(f"Unsafe archive path: {name}")
    if parsed.parts[:3] != ("data", "public", "v0.2.0"):
        _fail(f"Archive member is outside the legacy release root: {name}")


def _parse_sum_file(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            checksum, relative = line.split("  ", 1)
        except ValueError as exc:
            raise ValueError(f"Malformed checksum line {path}:{line_number}") from exc
        if (
            len(checksum) != 64
            or any(char not in "0123456789abcdef" for char in checksum)
            or relative in result
        ):
            _fail(f"Invalid checksum entry at {path}:{line_number}")
        result[relative] = checksum
    return result


def _check_release_hashes(
    root: Path,
    release_dir: Path,
    ignored_expanded_duplicates: set[str] | None = None,
) -> dict[str, Any]:
    if not release_dir.is_dir():
        _fail(f"v0.3.0 release directory is missing: {release_dir}")
    ignored_expanded_duplicates = ignored_expanded_duplicates or set()
    for relative in ignored_expanded_duplicates:
        if relative not in {"gene_associations.tsv", "condition_observations.tsv"}:
            _fail(f"Only a verified expanded table duplicate may be ignored: {relative}")
        expanded_dir = release_dir / relative
        table_name = relative.removesuffix(".tsv")
        pmid = RELATED_TABLE_PMIDS[table_name]
        compressed = release_dir / "studies" / f"PMID_{pmid}" / f"{table_name}.tsv.gz"
        child = expanded_dir / relative
        if (
            expanded_dir.is_symlink()
            or not expanded_dir.is_dir()
            or list(expanded_dir.iterdir()) != [child]
            or not child.is_file()
            or child.is_symlink()
            or gzip.decompress(compressed.read_bytes()) != child.read_bytes()
        ):
            _fail(f"Ignored expanded duplicate is not byte-identical to its study table: {relative}")
    entries = list(release_dir.iterdir())
    actual_names = {path.name for path in entries}
    unexpected_names = actual_names - {Path(name).name for name in ignored_expanded_duplicates}
    if unexpected_names != RELEASE_FILES:
        _fail(
            "v0.3.0 root must contain only studies/, release.json, and SHA256SUMS.txt; "
            f"missing={sorted(RELEASE_FILES - unexpected_names)}, "
            f"extra={sorted(unexpected_names - RELEASE_FILES)}"
        )
    for path in entries:
        if path.name in {Path(name).name for name in ignored_expanded_duplicates}:
            continue
        if path.name != "studies" and (path.is_symlink() or not path.is_file()):
            _fail(f"v0.3.0 root release artifact must be a regular file: {path}")
    studies_root = release_dir / "studies"
    if studies_root.is_symlink() or not studies_root.is_dir():
        _fail("v0.3.0 studies path must be a regular directory")
    study_dirs = sorted(studies_root.iterdir())
    if len(study_dirs) != EXPECTED_STUDY_COUNT:
        _fail(f"Expected {EXPECTED_STUDY_COUNT} study folders, found {len(study_dirs)}")
    for study_dir in study_dirs:
        if study_dir.is_symlink() or not study_dir.is_dir() or not study_dir.name.startswith("PMID_"):
            _fail(f"Invalid v0.3.0 study folder: {study_dir}")
        expected_children = set(STUDY_BASE_FILES)
        for table_name, pmid in RELATED_TABLE_PMIDS.items():
            if study_dir.name == f"PMID_{pmid}":
                expected_children.add(f"{table_name}.tsv.gz")
        children = list(study_dir.iterdir())
        actual_children = {path.name for path in children}
        if actual_children != expected_children or any(path.is_symlink() or not path.is_file() for path in children):
            _fail(
                f"{study_dir.name} must contain {sorted(expected_children)} only; "
                f"missing={sorted(expected_children - actual_children)}, "
                f"extra={sorted(actual_children - expected_children)}"
            )

    sums_path = release_dir / "SHA256SUMS.txt"
    sums = _parse_sum_file(sums_path)
    actual_files = {
        path.relative_to(release_dir).as_posix(): _sha256(path)
        for path in release_dir.rglob("*")
        if path.is_file() and path != sums_path
        and not any(
            path.relative_to(release_dir).as_posix() == ignored
            or path.relative_to(release_dir).as_posix().startswith(ignored + "/")
            for ignored in ignored_expanded_duplicates
        )
    }
    if sums != actual_files:
        missing = sorted(set(actual_files) - set(sums))
        extra = sorted(set(sums) - set(actual_files))
        mismatched = sorted(name for name in set(sums).intersection(actual_files) if sums[name] != actual_files[name])
        _fail(f"v0.3.0 SHA256SUMS mismatch: missing={missing}, extra={extra}, mismatched={mismatched}")
    forbidden = []
    for path in release_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(release_dir).as_posix()
        if any(rel == ignored or rel.startswith(ignored + "/") for ignored in ignored_expanded_duplicates):
            continue
        if path.suffix.lower() in {".csv", ".bed"} or (path.suffix.lower() == ".tsv" and path.name != "metadata.tsv"):
            forbidden.append(rel)
    if forbidden:
        _fail(f"v0.3.0 contains retired tabular endpoint formats: {sorted(forbidden)}")
    for gzip_path in (path for path in release_dir.rglob("*.gz") if path.is_file()):
        header = gzip_path.read_bytes()[:10]
        if len(header) < 10 or header[:3] != b"\x1f\x8b\x08" or header[3] != 0 or header[4:8] != b"\0\0\0\0":
            _fail(f"Gzip header is not deterministic (no mtime or filename): {gzip_path.relative_to(release_dir)}")
    release_doc = _read_json(release_dir / "release.json")
    if release_doc.get("release_version") != "v0.3.0" or not release_doc.get("summary"):
        _fail("release.json lacks the v0.3.0 version or summary")
    counts = release_doc.get("counts", {})
    if counts.get("source_count") != EXPECTED_SOURCE_COUNT or counts.get("study_count") != EXPECTED_STUDY_COUNT:
        _fail("release.json source_count or study_count does not match the v0.3.0 contract")
    release_files = release_doc.get("files")
    payload_paths = set(actual_files) - {"release.json"}
    if not isinstance(release_files, dict) or set(release_files) != payload_paths:
        _fail("release.json files must enumerate every study and table asset")
    for relative, info in release_files.items():
        path = release_dir / relative
        if (
            not isinstance(info, dict)
            or info.get("path") != relative
            or not path.is_file()
            or info.get("sha256") != _sha256(path)
            or info.get("byte_size") != path.stat().st_size
        ):
            _fail(f"release.json file metadata mismatch: {relative}")
    return release_doc


def _verify_archive(root: Path) -> tuple[dict[str, bytes], int]:
    archive = root / ARCHIVE_REL
    archive_hash_path = root / ARCHIVE_HASH_REL
    sums_path = root / ARCHIVE_SUMS_REL
    if not archive.is_file() or not archive_hash_path.is_file() or not sums_path.is_file():
        _fail("Legacy v0.2.0 archive or checksum sidecar is missing")
    sidecar = archive_hash_path.read_text(encoding="ascii").strip().split()
    if len(sidecar) != 2 or sidecar[0] != _sha256(archive) or sidecar[1] != archive.name:
        _fail("Legacy archive SHA-256 sidecar mismatch")
    expected = _parse_sum_file(sums_path)
    if len(expected) != EXPECTED_LEGACY_FILES:
        _fail(f"Expected {EXPECTED_LEGACY_FILES} entries in legacy checksum list, found {len(expected)}")

    payloads: dict[str, bytes] = {}
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        if len(members) != EXPECTED_LEGACY_FILES:
            _fail(f"Expected {EXPECTED_LEGACY_FILES} archive members, found {len(members)}")
        names: set[str] = set()
        for member in members:
            _safe_member_name(member.name)
            if not member.isfile() or member.name in names:
                _fail(f"Archive contains a non-file or duplicate path: {member.name}")
            names.add(member.name)
        if names != set(expected):
            _fail("Archive member paths do not match the legacy checksum list")
        for member in members:
            stream = bundle.extractfile(member)
            if stream is None:
                _fail(f"Archive member could not be read: {member.name}")
            payload = stream.read()
            if hashlib.sha256(payload).hexdigest() != expected[member.name]:
                _fail(f"Legacy file SHA-256 mismatch: {member.name}")
            payloads[member.name] = payload

    original = root / LEGACY_REL
    if original.is_dir():
        original_files = {path.relative_to(root).as_posix(): path for path in original.rglob("*") if path.is_file()}
        if set(original_files) != set(expected):
            _fail("Current legacy tree paths differ from its archive")
        for relative, checksum in expected.items():
            if _sha256(original_files[relative]) != checksum:
                _fail(f"Current legacy file differs from archive: {relative}")
    return payloads, len(expected)


def _group(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        result[str(row.get(key, ""))].append(row)
    return result


def _check_lossless_tables(root: Path, legacy_files: dict[str, bytes], release_dir: Path) -> dict[str, int]:
    record_prefix = "data/public/v0.2.0/records/"
    endpoint_paths = sorted(path for path in legacy_files if path.startswith(record_prefix) and path.endswith("/endpoints.tsv"))
    core_rows = list(iter_endpoints(release_dir))
    if len(core_rows) != EXPECTED_ENDPOINTS:
        _fail(f"Expected {EXPECTED_ENDPOINTS} endpoints, found {len(core_rows)}")
    new_by_source = _group(core_rows, "source_id")
    endpoint_by_key: dict[tuple[str, str], dict[str, str]] = {}
    for row in core_rows:
        key = (row.get("source_id", ""), row.get("end_id", ""))
        if not all(key) or key in endpoint_by_key:
            _fail(f"Invalid or duplicate endpoint composite key: {key}")
        endpoint_by_key[key] = row

    old_source_ids: set[str] = set()
    annotation_expectations: dict[str, list[dict[str, str]]] = {}
    annotation_headers: dict[str, list[str]] = {}
    expected_annotation_count = 0
    for old_path in endpoint_paths:
        source_id = PurePosixPath(old_path).parts[4]
        old_source_ids.add(source_id)
        old_header, old_rows = _read_tsv_bytes(legacy_files[old_path], old_path)
        if old_header != list(ENDPOINT_COLUMNS):
            _fail(f"Unexpected archived endpoint schema for {source_id}")
        if new_by_source.get(source_id, []) != old_rows:
            _fail(f"Endpoint rows changed for {source_id}")

        annotation_path = f"{record_prefix}{source_id}/source_annotations.tsv"
        if annotation_path not in legacy_files:
            annotation_expectations[source_id] = []
            continue
        annotation_header, annotation_rows = _read_tsv_bytes(legacy_files[annotation_path], annotation_path)
        annotation_headers[source_id] = annotation_header
        annotation_expectations[source_id] = annotation_rows
        expected_annotation_count += len(annotation_rows)

    # Annotation rows are reconstructed from each study GFF3 and the source
    # field map in its metadata.json; no separate annotations table is needed.
    annotations = list(iter_annotations(release_dir))
    new_annotations = _group(annotations, "source_id")
    seen_annotation_keys: set[tuple[str, str]] = set()
    for source_id, expected_rows in annotation_expectations.items():
        observed_rows = new_annotations.get(source_id, [])
        if len(observed_rows) != len(expected_rows):
            _fail(f"Annotation row count changed for {source_id}")
        for expected, observed in zip(expected_rows, observed_rows):
            key = (source_id, expected.get("end_id", ""))
            if key in seen_annotation_keys:
                _fail(f"Duplicate annotation composite key: {key}")
            seen_annotation_keys.add(key)
            if observed.get("source_id") != source_id or observed.get("end_id") != expected.get("end_id"):
                _fail(f"Annotation order/key changed for {key}")
            extra_fields = observed.get("fields")
            overrides = observed.get("overrides")
            old_header = annotation_headers[source_id]
            if not isinstance(extra_fields, dict) or not isinstance(overrides, dict):
                _fail(f"Invalid reconstructed annotation fields for {key}")
            endpoint = endpoint_by_key.get(key)
            if endpoint is None:
                _fail(f"Annotation points to an unknown endpoint: {key}")
            rebuilt: dict[str, str] = {}
            for name in old_header:
                if name == "end_id":
                    rebuilt[name] = key[1]
                elif name == "source_id":
                    rebuilt[name] = source_id
                elif name in overrides:
                    rebuilt[name] = overrides[name]
                elif name in extra_fields:
                    rebuilt[name] = extra_fields[name]
                elif name in endpoint:
                    rebuilt[name] = endpoint[name]
                else:
                    _fail(f"Annotation field has no reconstruction mapping for {key}.{name}")
            if set(rebuilt) != set(old_header):
                _fail(f"Annotation columns changed for {source_id}: {sorted(set(rebuilt) ^ set(old_header))}")
            if rebuilt != expected:
                _fail(f"Annotation field values changed for {key}")
    if sum(map(len, new_annotations.values())) != expected_annotation_count:
        _fail("Annotation rows include unexpected source records")

    table_counts: dict[str, int] = {"endpoint_count": len(core_rows), "annotation_count": len(annotations)}
    for table_name, release_table, old_table_name in (
        ("gene_association_count", "gene_associations", "gene_associations.tsv"),
        ("condition_observation_count", "condition_observations", "condition_observations.tsv"),
    ):
        merged_rows = list(iter_related_rows(release_dir, release_table))
        merged_by_source = _group(merged_rows, "source_id")
        expected_count = 0
        old_suffix = f"/{old_table_name}"
        old_table_files = sorted(path for path in legacy_files if path.startswith(record_prefix) and path.endswith(old_suffix))
        for old_path in old_table_files:
            source_id = PurePosixPath(old_path).parts[4]
            old_header, old_rows = _read_tsv_bytes(legacy_files[old_path], old_path)
            current_rows = merged_by_source.get(source_id, [])
            if current_rows != old_rows:
                _fail(f"{release_table}.tsv.gz rows or fields changed for {source_id}")
            if any(set(row) != set(old_header) for row in current_rows):
                _fail(f"Restored {release_table}.tsv.gz schema changed for {source_id}")
            expected_count += len(old_rows)
        if sum(map(len, merged_by_source.values())) != expected_count:
            _fail(f"{release_table}.tsv.gz contains unexpected rows")
        table_counts[table_name] = expected_count
        if release_table == "gene_associations":
            unlinked_count = sum(1 for row in merged_rows if not row.get("end_id"))
            if unlinked_count != EXPECTED_UNLINKED_GENE_ASSOCIATIONS:
                _fail(
                    f"Expected {EXPECTED_UNLINKED_GENE_ASSOCIATIONS} unlinked gene rows "
                    f"with their own coordinates, found {unlinked_count}"
                )
            table_counts["unlinked_gene_association_count"] = unlinked_count
    return table_counts


def _check_source_metadata(root: Path, legacy_files: dict[str, bytes], release_dir: Path) -> int:
    by_id: dict[str, dict[str, Any]] = {}
    studies: list[dict[str, Any]] = []
    sources_by_pmid: dict[str, list[dict[str, Any]]] = {}
    for study_dir, document in iter_study_metadata(release_dir):
        pmid = document["pmid"]
        if document.get("schema_version") != "1.0":
            _fail(f"{study_dir.name}/metadata.json has an unsupported schema_version")
        sources = document["sources"]
        for source in sources:
            source_id = source.get("source_id")
            if not isinstance(source_id, str) or not source_id or source_id in by_id:
                _fail(f"Study metadata has a missing or duplicate source_id: {source_id!r}")
            by_id[source_id] = source
            sources_by_pmid.setdefault(pmid, []).append(source)

        metadata_tsv = study_dir / "metadata.tsv"
        header, rows = _read_tsv(metadata_tsv)
        expected_rows = [study_metadata_tsv_row(source) for source in sources]
        if header != list(STUDY_METADATA_TSV_COLUMNS) or rows != expected_rows:
            _fail(f"{study_dir.name}/metadata.tsv differs from its source metadata.json values")

    if len(by_id) != EXPECTED_SOURCE_COUNT:
        _fail(f"Expected {EXPECTED_SOURCE_COUNT} source datasets, found {len(by_id)}")
    observed_counts = {pmid: 0 for pmid in sources_by_pmid}
    for endpoint in iter_endpoints(release_dir):
        observed_counts[source_pmid(by_id[endpoint["source_id"]])] += 1
    for study_dir, document in iter_study_metadata(release_dir):
        pmid = document["pmid"]
        record_count = document.get("record_count")
        observed = observed_counts.get(pmid, 0)
        audit_only = observed == 0
        if type(record_count) is not int or record_count != observed:
            _fail(f"{study_dir.name}/metadata.json record_count differs from its GFF3 feature count")
        expected_source_count = sum(source_record_count(source) for source in document["sources"])
        if expected_source_count != observed:
            _fail(f"{study_dir.name}/metadata.json source counts differ from its GFF3 feature count")
        if document.get("audit_only") is not audit_only or document.get("study_status") != ("audit_only" if audit_only else "published"):
            _fail(f"{study_dir.name}/metadata.json does not label its evidence status correctly")
        table_counts = document.get("related_table_counts")
        if not isinstance(table_counts, dict) or set(table_counts) != set(RELATED_TABLE_PMIDS):
            _fail(f"{study_dir.name}/metadata.json has invalid related_table_counts")
        for table_name, table_pmid in RELATED_TABLE_PMIDS.items():
            if type(table_counts.get(table_name)) is not int or table_counts[table_name] < 0:
                _fail(f"{study_dir.name}/metadata.json has an invalid {table_name} count")
            if (table_counts[table_name] > 0) != (pmid == table_pmid):
                _fail(f"{study_dir.name}/metadata.json assigns {table_name} to the wrong study")
        studies.append(
            {
                "pmid": pmid,
                "path": f"studies/{study_dir.name}",
                "source_count": len(document["sources"]),
                "record_count": observed,
                "audit_only": audit_only,
                "related_table_counts": table_counts,
            }
        )
    if len(studies) != EXPECTED_STUDY_COUNT:
        _fail(f"Expected {EXPECTED_STUDY_COUNT} study metadata files, found {len(studies)}")

    for table_name, table_pmid in RELATED_TABLE_PMIDS.items():
        actual_rows = list(iter_related_rows(release_dir, table_name))
        for study in studies:
            expected_count = len(actual_rows) if study["pmid"] == table_pmid else 0
            if study["related_table_counts"][table_name] != expected_count:
                _fail(f"PMID_{study['pmid']} metadata count for {table_name} does not match its table")

    release_doc = _read_json(release_dir / "release.json")
    if release_doc.get("studies") != studies:
        _fail("release.json study summaries do not match study metadata")
    if release_doc.get("source_table_provenance") is None:
        _fail("release.json is missing source_table_provenance")

    record_prefix = "data/public/v0.2.0/records/"
    expected_ids = {
        PurePosixPath(path).parts[4]
        for path in legacy_files
        if path.startswith(record_prefix) and len(PurePosixPath(path).parts) >= 6
    }
    if set(by_id) != expected_ids:
        _fail(f"Study metadata source set mismatch: missing={sorted(expected_ids-set(by_id))}; extra={sorted(set(by_id)-expected_ids)}")
    for source_id, entry in by_id.items():
        registry_manifest = entry.get("registry_manifest")
        if not isinstance(registry_manifest, dict) or registry_manifest.get("source_id") != source_id:
            _fail(f"Missing or inconsistent registry_manifest for {source_id}")
        release_path = f"{record_prefix}{source_id}/manifest.json"
        fields_path = f"{record_prefix}{source_id}/fields.json"
        if release_path not in legacy_files or fields_path not in legacy_files:
            _fail(f"Archived source manifest or fields.json is missing for {source_id}")
        expected_release = json.loads(legacy_files[release_path].decode("utf-8-sig"))
        expected_fields = json.loads(legacy_files[fields_path].decode("utf-8-sig"))
        if not isinstance(expected_release, dict) or not isinstance(expected_fields, dict):
            _fail(f"Invalid archived source metadata for {source_id}")
        if "release_manifest" in entry or "fields" in entry:
            _fail(f"Redundant archived metadata copied into study metadata for {source_id}")
        expected_facts = {
            "known_limitations": expected_release.get("known_limitations", ""),
            "has_jbrowse": expected_release.get("has_jbrowse", False),
        }
        if entry.get("release_facts") != expected_facts:
            _fail(f"Current release facts differ from archived source manifest for {source_id}")

        annotation_path = f"{record_prefix}{source_id}/source_annotations.tsv"
        field_map = entry.get("annotation_field_map")
        annotation_defaults = entry.get("annotation_defaults", {})
        if annotation_path in legacy_files:
            annotation_header, _ = _read_tsv_bytes(legacy_files[annotation_path], annotation_path)
            expected_annotation_fields = set(annotation_header) - {"end_id", "source_id"}
            if not isinstance(field_map, dict) or not isinstance(annotation_defaults, dict):
                _fail(f"Missing annotation reconstruction metadata for {source_id}")
            default_fields = annotation_defaults.get("fields", {})
            if (
                not isinstance(default_fields, dict)
                or any(not isinstance(value, str) for value in default_fields.values())
            ):
                _fail(f"Invalid annotation defaults for {source_id}")
            default_overrides = annotation_defaults.get("overrides", {})
            if (
                not isinstance(default_overrides, dict)
                or any(not isinstance(value, str) for value in default_overrides.values())
                or not set(default_overrides).issubset(set(ENDPOINT_COLUMNS) - {"end_id", "source_id"})
            ):
                _fail(f"Invalid endpoint annotation overrides for {source_id}")
            covered_fields = set(field_map) | set(default_fields) | set(default_overrides)
            implicit_endpoint_fields = expected_annotation_fields - covered_fields
            if (
                set(field_map).intersection(default_fields)
                or set(field_map).intersection(default_overrides)
                or set(default_fields).intersection(default_overrides)
                or not implicit_endpoint_fields.issubset(ENDPOINT_COLUMNS)
                or covered_fields | implicit_endpoint_fields != expected_annotation_fields
            ):
                _fail(f"Annotation field map does not cover the archived schema for {source_id}")
            for field_name, mapping in field_map.items():
                if not isinstance(mapping, dict):
                    _fail(f"Invalid annotation field mapping for {source_id}.{field_name}")
                if mapping.get("from") == "endpoint":
                    if set(mapping) != {"from", "field"} or mapping.get("field") not in ENDPOINT_COLUMNS:
                        _fail(f"Invalid endpoint annotation mapping for {source_id}.{field_name}")
                elif mapping.get("from") == "attribute":
                    expected_attribute = ANNOTATION_ATTRIBUTE_PREFIX + field_name
                    if set(mapping) != {"from", "attribute"} or mapping.get("attribute") != expected_attribute:
                        _fail(f"Invalid GFF3 annotation mapping for {source_id}.{field_name}")
                else:
                    _fail(f"Unknown annotation field mapping for {source_id}.{field_name}")
        elif field_map is not None or annotation_defaults:
            _fail(f"Unexpected annotation reconstruction metadata for {source_id}")

        historical = registry_manifest.get("repository_release")
        manifest_sha = registry_manifest.get("legacy_manifest_sha256", "")
        if not isinstance(historical, dict) or historical.get("release_version") != "v0.1-local-snapshot":
            _fail(f"Missing historical repository release for {source_id}")
        if not isinstance(manifest_sha, str) or len(manifest_sha) != 64 or any(char not in "0123456789abcdef" for char in manifest_sha):
            _fail(f"Invalid historical manifest SHA-256 for {source_id}")
        if historical.get("record_count") != expected_release.get("record_count"):
            _fail(f"Historical record count differs from archived release for {source_id}")
        if any(key in historical for key in ("public_asset", "source_processed_table")):
            _fail(f"Retired v0.1 file path in historical release for {source_id}")
        checksums = historical.get("published_file_checksums", [])
        if not isinstance(checksums, list) or any(
            not isinstance(item, dict)
            or not isinstance(item.get("filename"), str)
            or "/" in item["filename"] or "\\" in item["filename"]
            or not isinstance(item.get("sha256"), str)
            or len(item["sha256"]) != 64
            or any(char not in "0123456789abcdef" for char in item["sha256"])
            for item in checksums
        ):
            _fail(f"Invalid historical file checksums for {source_id}")
        for name in ("registry_row", "license_status", "publication_status"):
            value = entry.get(name)
            if value is not None and (not isinstance(value, dict) or value.get("source_id") != source_id):
                _fail(f"Invalid {name} for {source_id}")
        redistribution = entry.get("asset_redistribution", [])
        if not isinstance(redistribution, list) or any(row.get("source_id") != source_id for row in redistribution):
            _fail(f"Invalid asset_redistribution rows for {source_id}")

    return len(by_id)


def validate_release(
    root: Path | None = None,
    check_archive: bool = True,
    ignored_expanded_duplicates: set[str] | None = None,
) -> dict[str, Any]:
    """Validate v0.3.0 and prove its table rows can be losslessly reconstructed.

    Args:
        root: Repository root. Defaults to the repository containing this file.
        check_archive: Retained for callers that need to disable full archive verification.

    Returns:
        A compact count summary for callers such as the D1 import adapter.
    """
    root = Path(root or ROOT).resolve()
    release_dir = root / RELEASE_REL
    release_doc = _check_release_hashes(root, release_dir, ignored_expanded_duplicates)
    legacy_files, archive_count = _verify_archive(root)
    if check_archive:
        counts = _check_lossless_tables(root, legacy_files, release_dir)
        source_count = _check_source_metadata(root, legacy_files, release_dir)
    else:
        endpoint_rows = list(iter_endpoints(release_dir))
        annotations = list(iter_annotations(release_dir))
        gene_rows = list(iter_related_rows(release_dir, "gene_associations"))
        condition_rows = list(iter_related_rows(release_dir, "condition_observations"))
        counts = {
            "endpoint_count": len(endpoint_rows),
            "annotation_count": len(annotations),
            "gene_association_count": len(gene_rows),
            "unlinked_gene_association_count": sum(1 for row in gene_rows if not row.get("end_id")),
            "condition_observation_count": len(condition_rows),
        }
        source_count = len(load_source_index(release_dir))

    expected_counts = release_doc.get("counts", {})
    for name, value in counts.items():
        if expected_counts.get(name) != value:
            _fail(f"release.json count mismatch for {name}: expected {expected_counts.get(name)}, found {value}")
    if expected_counts.get("source_count") != source_count:
        _fail("release.json source_count does not match study metadata")
    return {
        "release_version": "v0.3.0",
        "source_count": source_count,
        "study_count": expected_counts.get("study_count"),
        **counts,
        "archive_file_count": archive_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository root (defaults to this script's repository).")
    parser.add_argument("--skip-lossless", action="store_true", help="Check checksums and archive only; skip row-by-row reconstruction.")
    args = parser.parse_args()
    print(json.dumps(validate_release(args.root, check_archive=not args.skip_lossless), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
