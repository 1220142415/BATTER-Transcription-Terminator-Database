#!/usr/bin/env python3
"""Build the compact, provenance-preserving BTED v0.3.0 data release."""

from __future__ import annotations

import argparse
import copy
import csv
import gzip
import hashlib
import io
import json
import os
import stat
import shutil
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from v03_tables import (
    ANNOTATION_ATTRIBUTE_PREFIX,
    ENDPOINT_COLUMNS,
    STUDY_METADATA_TSV_COLUMNS,
    format_endpoint_gff3,
    source_pmid,
    source_record_count,
    study_metadata_tsv_row,
)


ROOT = Path(__file__).resolve().parents[1]
LEGACY_REL = Path("data/public/v0.2.0")
RELEASE_REL = Path("data/public/v0.3.0")
ARCHIVE_REL = Path("data/archive/BTED-v0.2.0.tar.gz")
RELATED_TABLE_PMIDS = {
    "gene_associations": "31594819",
    "condition_observations": "37402717",
}
EXPECTED_LEGACY_FILES = 153
CORE_ENDPOINT_COUNT = 28_399
EXPECTED_SOURCE_COUNT = 22
EXPECTED_STUDY_COUNT = 13

COMPACT_ENDPOINT_COLUMNS = [
    "end_id",
    "source_id",
    "author_endpoint_id",
    "published_reference_accession",
    "reference_name",
    "replicon_label",
    "biological_coordinate_1based",
    "strand",
    "signal_or_score",
    "author_category",
    "associated_gene_or_locus",
    "original_row_reference",
]
ENDPOINT_DEFAULT_COLUMNS = [
    "sample_id",
    "assay",
    "evidence_class",
    "reference_assembly",
    "pmid",
    "doi",
    "source_table_or_file",
    "coordinate_interpretation",
    "qc_status",
    "note",
]
GENE_DEFAULT_COLUMNS = [
    "species",
    "evidence_class",
    "pmid",
    "doi",
    "source_table",
    "count_discrepancy_warning",
]
CONDITION_DEFAULT_COLUMNS = [
    "link_status",
    "species",
    "assay",
    "evidence_class",
    "pmid",
    "doi",
    "coordinate_interpretation",
]
BED_DERIVED_COLUMNS = ["bed_start_0based", "bed_end_0based"]


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def existing_legacy_archive_info(root: Path) -> dict[str, Any]:
    archive = root / ARCHIVE_REL
    if not archive.is_file():
        raise FileNotFoundError(f"The preserved v0.2.0 archive is missing: {archive}")
    with tarfile.open(archive, "r:gz") as bundle:
        file_count = sum(member.isfile() for member in bundle.getmembers())
    return {
        "path": ARCHIVE_REL.as_posix(),
        "sha256": sha256_file(archive),
        "file_manifest": "data/archive/BTED-v0.2.0.SHA256SUMS.txt",
        "file_count": file_count,
    }


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.name + ".tmp")
    temp_path.write_bytes(data)
    os.replace(temp_path, path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames:
            raise ValueError(f"Missing TSV header: {path}")
        return list(reader.fieldnames), [dict(row) for row in reader]


def write_tsv_bytes(header: list[str], rows: Iterable[dict[str, Any]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=header,
        delimiter="\t",
        lineterminator="\n",
        extrasaction="ignore",
        quoting=csv.QUOTE_MINIMAL,
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({name: row.get(name, "") for name in header})
    return buffer.getvalue().encode("utf-8")


def write_gff3_bytes(
    rows: Iterable[dict[str, str]], annotations_by_key: dict[tuple[str, str], dict[str, str]] | None = None
) -> bytes:
    lines = ["##gff-version 3"]
    annotations_by_key = annotations_by_key or {}
    lines.extend(
        format_endpoint_gff3(row, annotations_by_key.get((row["source_id"], row["end_id"])))
        for row in rows
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def deterministic_gzip(data: bytes) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=output, compresslevel=9, mtime=0) as zipped:
        zipped.write(data)
    return output.getvalue()


def _safe_tar_member_name(path: str) -> None:
    member = PurePosixPath(path)
    if member.is_absolute() or ".." in member.parts or not member.parts:
        raise ValueError(f"Unsafe legacy archive path: {path}")


def _legacy_tree(root: Path) -> tuple[Path, Path | None]:
    existing = root / LEGACY_REL
    if existing.is_dir():
        return existing, None
    archive = root / ARCHIVE_REL
    if not archive.is_file():
        raise FileNotFoundError(f"Neither legacy data nor archive exists: {existing} / {archive}")
    destination = root / "data/archive/.bted-v03-build-input"
    if destination.exists():
        raise FileExistsError(f"Refusing to reuse an existing build scratch path: {destination}")
    destination.mkdir(parents=True)
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            _safe_tar_member_name(member.name)
            if not member.isfile():
                raise ValueError(f"Unexpected non-file archive member: {member.name}")
        for member in bundle.getmembers():
            target = destination.joinpath(*PurePosixPath(member.name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            content = bundle.extractfile(member)
            if content is None:
                raise ValueError(f"Cannot read archive member: {member.name}")
            target.write_bytes(content.read())
    extracted = destination / LEGACY_REL
    if not extracted.is_dir():
        raise ValueError(f"Legacy archive does not contain {LEGACY_REL.as_posix()}")
    return extracted, destination


def build_legacy_archive(root: Path, legacy_root: Path) -> dict[str, Any]:
    archive = root / ARCHIVE_REL
    archive.parent.mkdir(parents=True, exist_ok=True)
    paths = sorted(path for path in legacy_root.rglob("*") if path.is_file())
    if len(paths) != EXPECTED_LEGACY_FILES:
        raise ValueError(f"Expected {EXPECTED_LEGACY_FILES} v0.2.0 files, found {len(paths)}")

    temp_archive = archive.with_name(archive.name + ".tmp")
    with temp_archive.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w", format=tarfile.USTAR_FORMAT) as bundle:
                for path in paths:
                    rel = (LEGACY_REL / path.relative_to(legacy_root)).as_posix()
                    info = tarfile.TarInfo(rel)
                    info.size = path.stat().st_size
                    info.mode = 0o644
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    info.mtime = 0
                    with path.open("rb") as content:
                        bundle.addfile(info, content)
    os.replace(temp_archive, archive)

    file_lines: list[str] = []
    for path in paths:
        rel = (LEGACY_REL / path.relative_to(legacy_root)).as_posix()
        file_lines.append(f"{sha256_file(path)}  {rel}\n")
    file_manifest = root / "data/archive/BTED-v0.2.0.SHA256SUMS.txt"
    atomic_write(file_manifest, "".join(file_lines).encode("utf-8"))
    archive_hash = sha256_file(archive)
    archive_sidecar = root / "data/archive/BTED-v0.2.0.tar.gz.sha256"
    atomic_write(archive_sidecar, f"{archive_hash}  {archive.name}\n".encode("ascii"))
    return {
        "path": ARCHIVE_REL.as_posix(),
        "sha256": archive_hash,
        "file_manifest": "data/archive/BTED-v0.2.0.SHA256SUMS.txt",
        "file_count": len(paths),
    }


def _rows_by_source(path: Path) -> tuple[list[str], dict[str, list[dict[str, str]]]]:
    header, rows = read_tsv(path)
    if "source_id" not in header:
        raise ValueError(f"Missing source_id in {path}")
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["source_id"], []).append(row)
    return header, grouped


def _union_headers(headers: Iterable[list[str]], ensure_source_id: bool = True) -> list[str]:
    result: list[str] = []
    for header in headers:
        for field in header:
            if field not in result:
                result.append(field)
    if ensure_source_id and "source_id" not in result:
        result.insert(0, "source_id")
    return result


def _read_registry_table(path: Path) -> tuple[list[str], dict[str, list[dict[str, str]]]]:
    if not path.is_file():
        return [], {}
    header, rows = read_tsv(path)
    if "source_id" not in header:
        raise ValueError(f"Missing source_id in registry table {path}")
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["source_id"], []).append(row)
    return header, grouped


def build_sources(root: Path, legacy_root: Path) -> dict[str, Any]:
    registry = root / "data/registry"
    record_root = legacy_root / "records"
    source_table_names = {
        "registry_row": "batter_s1_source_registry.tsv",
        "publication_status": "batter_s1_publication_status.v0.2.0.tsv",
        "license_status": "batter_s1_license_status.v0.2.0.tsv",
        "asset_redistribution": "batter_s1_asset_redistribution.v0.3.tsv",
    }
    source_tables: dict[str, dict[str, list[dict[str, str]]]] = {}
    table_provenance: dict[str, dict[str, Any]] = {}
    for key, filename in source_table_names.items():
        path = registry / filename
        header, rows = _read_registry_table(path)
        source_tables[key] = rows
        if path.is_file():
            table_provenance[key] = {
                "source_path": f"data/registry/{filename}",
                "sha256": sha256_file(path),
                "columns": header,
            }

    manifest_dir = registry / "manifests"
    registry_manifests: dict[str, dict[str, Any]] = {}
    if manifest_dir.is_dir():
        for path in sorted(manifest_dir.glob("BATTER_S1_*.json")):
            value = read_json(path)
            registry_manifests[value["source_id"]] = value

    # Rebuilds after pruning use the already consolidated metadata objects.
    existing_sources_path = root / RELEASE_REL / "sources.json"
    existing_sources: dict[str, dict[str, Any]] = {}
    existing_provenance: dict[str, Any] = {}
    if existing_sources_path.is_file():
        existing = read_json(existing_sources_path)
        existing_sources = {item["source_id"]: item for item in existing.get("sources", [])}
        existing_provenance = existing.get("source_table_provenance", {})
    else:
        studies_root = root / RELEASE_REL / "studies"
        if studies_root.is_dir():
            for metadata_path in sorted(studies_root.glob("PMID_*/metadata.json")):
                metadata = read_json(metadata_path)
                for item in metadata.get("sources", []):
                    source_id = item.get("source_id")
                    if not source_id or source_id in existing_sources:
                        raise ValueError(f"Missing or duplicate source ID in existing study metadata: {source_id!r}")
                    existing_sources[source_id] = item
        release_manifest_path = root / RELEASE_REL / "release.json"
        if release_manifest_path.is_file():
            existing_provenance = read_json(release_manifest_path).get("source_table_provenance", {})

    if existing_provenance:
        table_provenance = existing_provenance
    if not registry_manifests:
        registry_manifests = {
            source_id: value["registry_manifest"]
            for source_id, value in existing_sources.items()
            if value.get("registry_manifest") is not None
        }

    source_ids = set(registry_manifests)
    source_ids.update(existing_sources)
    for rows in source_tables.values():
        source_ids.update(rows)
    source_ids.update(path.name for path in record_root.iterdir() if path.is_dir())
    source_ids = {value for value in source_ids if value.startswith("BATTER_S1_")}
    items: list[dict[str, Any]] = []

    for source_id in sorted(source_ids):
        record_dir = record_root / source_id
        registry_manifest = registry_manifests.get(source_id)
        prior = existing_sources.get(source_id, {})
        release_manifest_path = record_dir / "manifest.json"
        release_manifest = read_json(release_manifest_path)
        if registry_manifest is None:
            registry_manifest = prior.get("registry_manifest")

        entry: dict[str, Any] = {
            "source_id": source_id,
            "registry_manifest": registry_manifest,
            # The full v0.2.0 manifest and fields.json remain in the verified
            # archive. Only release-specific facts needed by today's site are
            # repeated here.
            "release_facts": {
                "known_limitations": release_manifest.get("known_limitations", ""),
                "has_jbrowse": release_manifest.get("has_jbrowse", False),
            },
        }
        for key, rows in source_tables.items():
            source_rows = rows.get(source_id)
            if key == "asset_redistribution":
                entry[key] = source_rows if source_rows is not None else prior.get(key, [])
            else:
                if source_rows is not None and len(source_rows) > 1:
                    raise ValueError(f"Expected one {key} row for {source_id}; found {len(source_rows)}")
                entry[key] = source_rows[0] if source_rows else prior.get(key)
        items.append(entry)

    source_doc = {
        "schema_version": "1.0",
        "release_version": "v0.3.0",
        "source_count": len(items),
        "source_table_provenance": table_provenance,
        "sources": items,
    }
    return source_doc


def build_endpoints(legacy_root: Path) -> tuple[list[str], list[dict[str, str]]]:
    inputs = sorted((legacy_root / "records").glob("*/endpoints.tsv"))
    headers: list[str] = []
    rows: list[dict[str, str]] = []
    key_counts: dict[tuple[str, str], int] = {}
    for path in inputs:
        header, source_rows = read_tsv(path)
        if not headers:
            headers = header
        elif header != headers:
            raise ValueError(f"Endpoint columns differ for {path}")
        for row in source_rows:
            key = (row.get("source_id", ""), row.get("end_id", ""))
            if not all(key):
                raise ValueError(f"Endpoint row has empty (source_id, end_id) in {path}")
            if key in key_counts:
                raise ValueError(f"Duplicate endpoint key {key} in {path}")
            key_counts[key] = 1
            rows.append(row)
    if len(rows) != CORE_ENDPOINT_COUNT:
        raise ValueError(f"Expected {CORE_ENDPOINT_COUNT} core endpoint rows, found {len(rows)}")
    return headers, rows


def _source_entries(source_doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["source_id"]: item for item in source_doc["sources"]}


def _install_table_defaults(
    source_doc: dict[str, Any], source_id: str, table_name: str, values: dict[str, str]
) -> None:
    entry = _source_entries(source_doc).get(source_id)
    if entry is None:
        raise ValueError(f"Cannot attach {table_name} defaults to unknown source {source_id}")
    table_defaults = entry.setdefault("table_defaults", {})
    table = table_defaults.setdefault(table_name, {})
    for name, value in values.items():
        prior = table.get(name)
        if prior is not None and prior != value:
            raise ValueError(f"Conflicting {table_name}.{name} defaults for {source_id}")
        table[name] = value


def _constant_source_values(
    rows: list[dict[str, str]], columns: list[str], source_id: str, table_name: str
) -> dict[str, str]:
    if not rows:
        return {}
    result: dict[str, str] = {}
    for name in columns:
        values = {row.get(name, "") for row in rows}
        if len(values) != 1:
            raise ValueError(f"{table_name}.{name} is not constant within source {source_id}")
        result[name] = next(iter(values))
    return result


def _validate_bed_derivation(row: dict[str, str], table_name: str) -> None:
    try:
        position = int(row["biological_coordinate_1based"])
        start = int(row["bed_start_0based"])
        end = int(row["bed_end_0based"])
    except (KeyError, ValueError) as error:
        raise ValueError(f"Invalid {table_name} biological/BED coordinate: {row}") from error
    if position < 1 or start != position - 1 or end != position:
        raise ValueError(f"Inconsistent {table_name} BED coordinates: {row}")


def compact_endpoints(
    core_header: list[str],
    endpoints: list[dict[str, str]],
    source_doc: dict[str, Any],
) -> tuple[list[str], list[dict[str, str]]]:
    expected = set(COMPACT_ENDPOINT_COLUMNS + ENDPOINT_DEFAULT_COLUMNS + BED_DERIVED_COLUMNS)
    if set(core_header) != expected:
        raise ValueError(f"Unexpected endpoint schema: {core_header}")

    by_source: dict[str, list[dict[str, str]]] = {}
    for row in endpoints:
        _validate_bed_derivation(row, "endpoint")
        by_source.setdefault(row["source_id"], []).append(row)

    for source_id, source_rows in by_source.items():
        defaults = _constant_source_values(source_rows, ENDPOINT_DEFAULT_COLUMNS, source_id, "endpoints")
        _install_table_defaults(source_doc, source_id, "endpoints", defaults)

    compact_rows = [
        {name: row.get(name, "") for name in COMPACT_ENDPOINT_COLUMNS}
        for row in endpoints
    ]
    return COMPACT_ENDPOINT_COLUMNS.copy(), compact_rows


def compact_gene_associations(
    gene_header: list[str],
    gene_rows: list[dict[str, str]],
    endpoints_by_key: dict[tuple[str, str], dict[str, str]],
    source_doc: dict[str, Any],
) -> tuple[list[str], list[dict[str, str]]]:
    removed = set(GENE_DEFAULT_COLUMNS + BED_DERIVED_COLUMNS)
    compact_header = [name for name in gene_header if name not in removed]
    required = {"end_id", "link_status", "record_id", "source_id", "reference_name", "biological_coordinate_1based", "strand"}
    if not required.issubset(compact_header):
        raise ValueError(f"Gene-association table is missing required columns: {sorted(required - set(compact_header))}")
    if not set(GENE_DEFAULT_COLUMNS + BED_DERIVED_COLUMNS).issubset(gene_header):
        raise ValueError("Gene-association table does not match the expected v0.2.0 schema")

    by_source: dict[str, list[dict[str, str]]] = {}
    for row in gene_rows:
        _validate_bed_derivation(row, "gene association")
        by_source.setdefault(row["source_id"], []).append(row)
    for source_id, source_rows in by_source.items():
        defaults = _constant_source_values(source_rows, GENE_DEFAULT_COLUMNS, source_id, "gene_associations")
        _install_table_defaults(source_doc, source_id, "gene_associations", defaults)

    compact_rows: list[dict[str, str]] = []
    for row in gene_rows:
        compact = {name: row.get(name, "") for name in compact_header}
        if row.get("link_status") == "linked":
            key = (row.get("source_id", ""), row.get("end_id", ""))
            endpoint = endpoints_by_key.get(key)
            if endpoint is None:
                raise ValueError(f"Linked gene association has no endpoint {key}: {row.get('record_id')}")
            for name in ("reference_name", "biological_coordinate_1based", "strand"):
                if not row.get(name) or row[name] != endpoint.get(name, ""):
                    raise ValueError(f"Linked gene association {key} disagrees with endpoint field {name}")
                compact[name] = ""
        elif row.get("link_status") == "unlinked_author_annotation":
            if row.get("end_id", ""):
                raise ValueError(f"Unlinked author gene association unexpectedly has end_id: {row.get('record_id')}")
            if not all(row.get(name, "") for name in ("reference_name", "biological_coordinate_1based", "strand")):
                raise ValueError(f"Unlinked author gene association lacks its own genomic coordinate: {row.get('record_id')}")
        else:
            raise ValueError(f"Unexpected gene-association link status: {row.get('link_status')}")
        compact_rows.append(compact)
    return compact_header, compact_rows


def compact_condition_observations(
    condition_header: list[str],
    condition_rows: list[dict[str, str]],
    endpoints_by_key: dict[tuple[str, str], dict[str, str]],
    source_doc: dict[str, Any],
) -> tuple[list[str], list[dict[str, str]]]:
    linked_coordinate_columns = {
        "reference_name",
        "biological_coordinate_1based",
        "strand",
        *BED_DERIVED_COLUMNS,
    }
    removed = linked_coordinate_columns.union(CONDITION_DEFAULT_COLUMNS)
    removed.update(("site_id", "published_replicon"))
    compact_header = [name for name in condition_header if name not in removed]
    required = {"end_id", "observation_id", "source_id", "sample_id", "source_table"}
    if not required.issubset(compact_header):
        raise ValueError(f"Condition-observation table is missing required columns: {sorted(required - set(compact_header))}")
    if not removed.issubset(condition_header):
        raise ValueError("Condition-observation table does not match the expected v0.2.0 schema")

    by_source: dict[str, list[dict[str, str]]] = {}
    for row in condition_rows:
        _validate_bed_derivation(row, "condition observation")
        by_source.setdefault(row["source_id"], []).append(row)
    for source_id, source_rows in by_source.items():
        defaults = _constant_source_values(source_rows, CONDITION_DEFAULT_COLUMNS, source_id, "condition_observations")
        _install_table_defaults(source_doc, source_id, "condition_observations", defaults)

    compact_rows: list[dict[str, str]] = []
    for row in condition_rows:
        if row.get("link_status") != "linked":
            raise ValueError(f"Condition observation is not linked to a core endpoint: {row.get('observation_id')}")
        key = (row.get("source_id", ""), row.get("end_id", ""))
        endpoint = endpoints_by_key.get(key)
        if endpoint is None:
            raise ValueError(f"Condition observation has no endpoint {key}: {row.get('observation_id')}")
        for name in ("reference_name", "biological_coordinate_1based", "strand"):
            if not row.get(name) or row[name] != endpoint.get(name, ""):
                raise ValueError(f"Condition observation {key} disagrees with endpoint field {name}")
        if row.get("site_id") != endpoint.get("author_endpoint_id"):
            raise ValueError(f"Condition observation {key} disagrees with endpoint site_id")
        if row.get("published_replicon") != endpoint.get("replicon_label"):
            raise ValueError(f"Condition observation {key} disagrees with endpoint published_replicon")
        compact_rows.append({name: row.get(name, "") for name in compact_header})
    return compact_header, compact_rows


def hoist_annotation_defaults(
    annotation_rows: list[dict[str, Any]], source_doc: dict[str, Any]
) -> list[dict[str, Any]]:
    by_source: dict[str, list[dict[str, Any]]] = {}
    for row in annotation_rows:
        by_source.setdefault(row["source_id"], []).append(row)

    source_by_id = _source_entries(source_doc)
    for source_id, source_rows in by_source.items():
        defaults: dict[str, dict[str, str]] = {"fields": {}, "overrides": {}}
        for section in ("fields", "overrides"):
            keys: list[str] = []
            for row in source_rows:
                for name in row[section]:
                    if name not in keys:
                        keys.append(name)
            for name in keys:
                if not all(name in row[section] for row in source_rows):
                    continue
                values = {row[section][name] for row in source_rows}
                if len(values) == 1:
                    defaults[section][name] = next(iter(values))
                    for row in source_rows:
                        row[section].pop(name)
        defaults = {section: fields for section, fields in defaults.items() if fields}
        if defaults:
            source_by_id[source_id]["annotation_defaults"] = defaults
    return annotation_rows


def merge_annotations_into_gff3(
    annotation_rows: list[dict[str, Any]],
    endpoints: list[dict[str, str]],
    source_doc: dict[str, Any],
) -> dict[tuple[str, str], dict[str, str]]:
    """Store only annotation values not already present in endpoint fields/defaults."""

    endpoints_by_key = {(row["source_id"], row["end_id"]): row for row in endpoints}
    by_source: dict[str, list[dict[str, Any]]] = {}
    for annotation in annotation_rows:
        key = (annotation["source_id"], annotation["end_id"])
        if key not in endpoints_by_key:
            raise ValueError(f"Annotation has no matching endpoint: {key}")
        if annotation["overrides"]:
            raise ValueError(f"Annotation overrides must be empty before merging into GFF3: {key}")
        by_source.setdefault(annotation["source_id"], []).append(annotation)

    attributes_by_key: dict[tuple[str, str], dict[str, str]] = {}
    for source_id, rows in by_source.items():
        entry = _source_entries(source_doc)[source_id]
        defaults = entry.get("annotation_defaults", {}).get("fields", {})
        field_names = list(rows[0]["fields"])
        if any(list(row["fields"]) != field_names for row in rows):
            raise ValueError(f"Annotation field layout varies within {source_id}")
        mapping: dict[str, dict[str, str]] = {}
        for field in field_names:
            if field in defaults:
                raise ValueError(f"Annotation field is repeated in defaults for {source_id}: {field}")
            matched = next(
                (
                    endpoint_field
                    for endpoint_field in ENDPOINT_COLUMNS
                    if all(
                        row["fields"][field]
                        == endpoints_by_key[(source_id, row["end_id"])][endpoint_field]
                        for row in rows
                    )
                ),
                None,
            )
            if matched is not None:
                mapping[field] = {"from": "endpoint", "field": matched}
            else:
                attribute = ANNOTATION_ATTRIBUTE_PREFIX + field
                if not attribute.isidentifier():
                    raise ValueError(f"Cannot encode annotation field as GFF3 attribute: {field}")
                mapping[field] = {"from": "attribute", "attribute": attribute}
        entry["annotation_field_map"] = mapping
        for row in rows:
            key = (source_id, row["end_id"])
            if key in attributes_by_key:
                raise ValueError(f"Duplicate annotation for endpoint: {key}")
            attributes_by_key[key] = {
                mapping[field]["attribute"]: value
                for field, value in row["fields"].items()
                if mapping[field]["from"] == "attribute"
            }
    return attributes_by_key


def build_annotations(legacy_root: Path, core_header: list[str], endpoints: list[dict[str, str]]) -> list[dict[str, Any]]:
    endpoint_by_key = {(row["source_id"], row["end_id"]): row for row in endpoints}
    annotations: list[dict[str, Any]] = []
    for path in sorted((legacy_root / "records").glob("*/source_annotations.tsv")):
        header, rows = read_tsv(path)
        for row in rows:
            key = (row.get("source_id", ""), row.get("end_id", ""))
            endpoint = endpoint_by_key.get(key)
            if endpoint is None:
                raise ValueError(f"Annotation has no core endpoint key {key} in {path}")
            extra_fields = {name: row.get(name, "") for name in header if name not in core_header}
            overrides = {
                name: row.get(name, "")
                for name in header
                if name in core_header and name not in ("end_id", "source_id") and row.get(name, "") != endpoint.get(name, "")
            }
            annotations.append({"end_id": key[1], "source_id": key[0], "fields": extra_fields, "overrides": overrides})
    return annotations


def build_consolidated_table(legacy_root: Path, filename: str) -> tuple[list[str], list[dict[str, str]]]:
    files = sorted((legacy_root / "records").glob(f"*/{filename}"))
    table_headers: list[list[str]] = []
    all_rows: list[dict[str, str]] = []
    for path in files:
        header, rows = read_tsv(path)
        table_headers.append(header)
        all_rows.extend(rows)
    return _union_headers(table_headers), all_rows


def compare_and_remove_old_endpoint_tsv(
    release_dir: Path,
    legacy_header: list[str],
    legacy_rows: list[dict[str, str]],
) -> bool:
    """Remove the one retired untracked full TSV only after exact row comparison."""

    retired_dir = release_dir / "endpoints.tsv"
    if not retired_dir.exists():
        return False
    if retired_dir.is_symlink() or not retired_dir.is_dir():
        raise ValueError(f"Unexpected retired endpoint path; refusing to remove: {retired_dir}")
    retired_file = retired_dir / "endpoints.tsv"
    children = list(retired_dir.iterdir())
    if children != [retired_file] or not retired_file.is_file() or retired_file.is_symlink():
        raise ValueError(f"Unexpected contents in retired endpoint directory: {retired_dir}")
    old_header, old_rows = read_tsv(retired_file)
    if old_header != legacy_header:
        raise ValueError("Retired 24-column endpoint TSV header does not match the v0.2.0 source schema")
    if old_rows != legacy_rows:
        mismatch = next(
            (index for index, (old, current) in enumerate(zip(old_rows, legacy_rows), 1) if old != current),
            min(len(old_rows), len(legacy_rows)) + 1,
        )
        raise ValueError(
            "Retired 24-column endpoint TSV differs from the immutable v0.2.0 source rows "
            f"(first differing row {mismatch}; old={len(old_rows)}, source={len(legacy_rows)})"
        )
    retired_file.unlink()
    retired_dir.rmdir()
    return True


def remove_obsolete_compressed_tsvs(release_dir: Path) -> list[str]:
    """Remove only the retired compressed endpoint table."""

    removed: list[str] = []
    for name in ("endpoints.tsv.gz",):
        path = release_dir / name
        if path.is_symlink():
            raise ValueError(f"Refusing to remove symlinked obsolete release object: {path}")
        if path.is_file():
            path.unlink()
            removed.append(name)
        elif path.exists():
            raise ValueError(f"Unexpected obsolete release object path: {path}")
    return removed


def unlinked_gene_association_count(rows: Iterable[dict[str, str]]) -> int:
    return sum(1 for row in rows if not row.get("end_id"))


def build_study_payloads(
    source_doc: dict[str, Any],
    endpoints: list[dict[str, str]],
    annotation_attributes: dict[tuple[str, str], dict[str, str]],
    related_tables: dict[str, tuple[list[str], list[dict[str, str]]]],
) -> tuple[dict[str, bytes], list[dict[str, Any]]]:
    """Build one deterministic study folder per PMID with source-level metadata."""

    sources_by_pmid: dict[str, list[dict[str, Any]]] = {}
    source_by_id = _source_entries(source_doc)
    for source in source_doc["sources"]:
        sources_by_pmid.setdefault(source_pmid(source), []).append(source)
    if len(source_doc["sources"]) != EXPECTED_SOURCE_COUNT:
        raise ValueError(f"Expected {EXPECTED_SOURCE_COUNT} source datasets, found {len(source_doc['sources'])}")
    if len(sources_by_pmid) != EXPECTED_STUDY_COUNT:
        raise ValueError(f"Expected {EXPECTED_STUDY_COUNT} studies, found {len(sources_by_pmid)}")

    endpoints_by_pmid: dict[str, list[dict[str, str]]] = {pmid: [] for pmid in sources_by_pmid}
    for row in endpoints:
        source = source_by_id.get(row.get("source_id", ""))
        if source is None:
            raise ValueError(f"Endpoint refers to unknown source {row.get('source_id')!r}")
        pmid = source_pmid(source)
        if row.get("pmid") != pmid:
            raise ValueError(f"Endpoint PMID disagrees with its source metadata: {row.get('end_id')}")
        endpoints_by_pmid[pmid].append(row)

    related_rows_by_table: dict[str, dict[str, list[dict[str, str]]]] = {}
    for table_name, (_header, rows) in related_tables.items():
        table_by_pmid: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            source = source_by_id.get(row.get("source_id", ""))
            if source is None:
                raise ValueError(f"{table_name} row refers to unknown source {row.get('source_id')!r}")
            table_by_pmid.setdefault(source_pmid(source), []).append(row)
        expected_pmid = RELATED_TABLE_PMIDS[table_name]
        unexpected_pmids = set(table_by_pmid) - {expected_pmid}
        if unexpected_pmids:
            raise ValueError(f"{table_name} contains rows outside PMID {expected_pmid}: {sorted(unexpected_pmids)}")
        related_rows_by_table[table_name] = table_by_pmid

    payloads: dict[str, bytes] = {}
    study_summaries: list[dict[str, Any]] = []
    for pmid in sorted(sources_by_pmid):
        study_sources = sources_by_pmid[pmid]
        study_rows = endpoints_by_pmid[pmid]
        expected_count = sum(source_record_count(source) for source in study_sources)
        if expected_count != len(study_rows):
            raise ValueError(
                f"PMID {pmid}: source metadata declares {expected_count} endpoints, "
                f"but the GFF3 rows contain {len(study_rows)}"
            )
        folder = f"studies/PMID_{pmid}"
        table_counts = {
            table_name: len(related_rows_by_table.get(table_name, {}).get(pmid, []))
            for table_name in related_tables
        }
        audit_only = len(study_rows) == 0
        metadata = {
            "schema_version": "1.0",
            "release_version": "v0.3.0",
            "pmid": pmid,
            "study_status": "audit_only" if audit_only else "published",
            "audit_only": audit_only,
            "source_count": len(study_sources),
            "record_count": len(study_rows),
            "related_table_counts": table_counts,
            "sources": study_sources,
        }
        feature_attributes = {
            (row["source_id"], row["end_id"]): annotation_attributes.get((row["source_id"], row["end_id"]), {})
            for row in study_rows
        }
        payloads[f"{folder}/endpoints.gff3.gz"] = deterministic_gzip(
            write_gff3_bytes(study_rows, feature_attributes)
        )
        payloads[f"{folder}/metadata.json"] = json_bytes(metadata)
        metadata_rows = [study_metadata_tsv_row(source) for source in study_sources]
        payloads[f"{folder}/metadata.tsv"] = write_tsv_bytes(STUDY_METADATA_TSV_COLUMNS, metadata_rows)
        for table_name, (header, _rows) in related_tables.items():
            table_rows = related_rows_by_table.get(table_name, {}).get(pmid, [])
            if table_rows:
                payloads[f"{folder}/{table_name}.tsv.gz"] = deterministic_gzip(write_tsv_bytes(header, table_rows))
        study_summaries.append(
            {
                "pmid": pmid,
                "path": folder,
                "source_count": len(study_sources),
                "record_count": len(study_rows),
                "audit_only": audit_only,
                "related_table_counts": table_counts,
            }
        )
    return payloads, study_summaries


def update_jbrowse_registry(root: Path) -> None:
    registry = root / "data/registry"

    contig_tsv = registry / "reference_contigs.v0.2.0.tsv"
    contig_json = registry / "reference_contigs.v0.2.0.json"
    if contig_tsv.is_file() and contig_json.is_file():
        header, rows = read_tsv(contig_tsv)
        doc = read_json(contig_json)
        embedded_rows = doc.get("rows")
        exact_rows = [{name: row.get(name, "") for name in header} for row in rows]
        if embedded_rows != exact_rows:
            raise ValueError("Reference-contig JSON rows do not match the paired TSV")
        doc["table_columns"] = header
        doc["embedded_table_provenance"] = {
            "source_path": "data/registry/reference_contigs.v0.2.0.tsv",
            "source_sha256": sha256_file(contig_tsv),
            "reason": "The original TSV rows are already embedded in this JSON alongside the generation metadata.",
        }
        atomic_write(contig_json, json_bytes(doc))

    tsv_path = registry / "jbrowse_assets.v0.2.0.tsv"
    json_path = registry / "jbrowse_assets.v0.2.0.json"
    if not json_path.is_file():
        return
    doc = read_json(json_path)
    if tsv_path.is_file():
        header, rows = read_tsv(tsv_path)
        doc["rows"] = [{name: row.get(name, "") for name in header} for row in rows]
        doc["table_columns"] = header
        doc["embedded_table_provenance"] = {
            "source_path": "data/registry/jbrowse_assets.v0.2.0.tsv",
            "source_sha256": sha256_file(tsv_path),
            "reason": "The original TSV rows are embedded in this JSON so the inventory and its generation rationale stay together.",
        }
    elif "rows" not in doc:
        raise ValueError("JBrowse inventory TSV is missing and JSON has no embedded rows")
    atomic_write(json_path, json_bytes(doc))


def _remove_verified_expanded_copy(
    release_dir: Path,
    directory_name: str,
    filename: str,
    expected: bytes,
    pending_cleanup: list[str],
) -> bool:
    """Remove an exact decompressed convenience copy after byte comparison."""

    directory = release_dir / directory_name
    if not directory.exists():
        return False
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f"Unexpected expanded release path; refusing to remove: {directory}")
    child = directory / filename
    children = list(directory.iterdir())
    if children != [child] or not child.is_file() or child.is_symlink():
        raise ValueError(f"Unexpected contents in expanded release directory: {directory}")
    if child.read_bytes() != expected:
        raise ValueError(f"Expanded release copy does not match its compressed payload: {child}")
    try:
        child.unlink()
        directory.rmdir()
    except PermissionError as exc:
        if getattr(exc, "winerror", None) != 32:
            raise
        pending_cleanup.append(directory.relative_to(release_dir).as_posix())
        return False
    return True


def _retire_flat_release_files(
    release_dir: Path,
    source_doc: dict[str, Any],
    global_gff3: bytes,
    related_tsv_bytes: dict[str, bytes],
) -> list[str]:
    """Remove only verified flat v0.3.0 duplicates replaced by study folders."""

    removed: list[str] = []
    pending_cleanup: list[str] = []
    flat_gff3 = release_dir / "endpoints.gff3.gz"
    if flat_gff3.exists():
        if flat_gff3.is_symlink() or not flat_gff3.is_file():
            raise ValueError(f"Unexpected flat endpoint release path: {flat_gff3}")
        if gzip.decompress(flat_gff3.read_bytes()) != global_gff3:
            raise ValueError("Flat endpoint GFF3 does not match the source rows being moved into study folders")
        flat_gff3.unlink()
        removed.append("endpoints.gff3.gz")
    _remove_verified_expanded_copy(
        release_dir, "endpoints.gff3", "endpoints.gff3", global_gff3, pending_cleanup
    )

    for table_name, expected in related_tsv_bytes.items():
        flat_table = release_dir / f"{table_name}.tsv.gz"
        if flat_table.exists():
            if flat_table.is_symlink() or not flat_table.is_file():
                raise ValueError(f"Unexpected flat table release path: {flat_table}")
            if gzip.decompress(flat_table.read_bytes()) != expected:
                raise ValueError(f"Flat {table_name}.tsv.gz does not match the table being moved into its study folder")
            flat_table.unlink()
            removed.append(flat_table.name)
        _remove_verified_expanded_copy(
            release_dir, f"{table_name}.tsv", f"{table_name}.tsv", expected, pending_cleanup
        )

    flat_sources = release_dir / "sources.json"
    if flat_sources.exists():
        if flat_sources.is_symlink() or not flat_sources.is_file():
            raise ValueError(f"Unexpected flat source metadata path: {flat_sources}")
        if read_json(flat_sources) != source_doc:
            raise ValueError("Flat sources.json differs from the source objects being moved into study metadata")
        flat_sources.unlink()
        removed.append("sources.json")
    return pending_cleanup


def build_release(root: Path, prune: bool = False) -> dict[str, Any]:
    scratch: Path | None = None
    try:
        legacy_root, scratch = _legacy_tree(root)
        # The archived v0.2.0 snapshot is an immutable build input.
        archive_info = existing_legacy_archive_info(root)

        release_dir = root / RELEASE_REL
        release_dir.mkdir(parents=True, exist_ok=True)
        legacy_core_header, endpoints = build_endpoints(legacy_root)
        annotation_rows = build_annotations(legacy_root, legacy_core_header, endpoints)
        gene_header, gene_rows = build_consolidated_table(legacy_root, "gene_associations.tsv")
        condition_header, condition_rows = build_consolidated_table(legacy_root, "condition_observations.tsv")
        source_doc = build_sources(root, legacy_root)

        core_header, compact_endpoint_rows = compact_endpoints(legacy_core_header, endpoints, source_doc)
        endpoints_by_key = {(row["source_id"], row["end_id"]): row for row in compact_endpoint_rows}
        gene_header, compact_gene_rows = compact_gene_associations(
            gene_header, gene_rows, endpoints_by_key, source_doc
        )
        condition_header, compact_condition_rows = compact_condition_observations(
            condition_header, condition_rows, endpoints_by_key, source_doc
        )
        original_annotation_rows = copy.deepcopy(annotation_rows)
        annotation_rows = hoist_annotation_defaults(annotation_rows, source_doc)
        annotation_attributes = merge_annotations_into_gff3(annotation_rows, endpoints, source_doc)

        gene_tsv_bytes = write_tsv_bytes(gene_header, compact_gene_rows)
        condition_tsv_bytes = write_tsv_bytes(condition_header, compact_condition_rows)
        related_tables = {
            "gene_associations": (gene_header, compact_gene_rows),
            "condition_observations": (condition_header, compact_condition_rows),
        }
        payloads, study_summaries = build_study_payloads(
            source_doc, endpoints, annotation_attributes, related_tables
        )
        for relative, payload in payloads.items():
            atomic_write(release_dir / PurePosixPath(relative), payload)

        from v03_tables import iter_annotations, iter_endpoints, iter_related_rows

        restored_endpoints = list(iter_endpoints(release_dir))
        original_by_key = {(row["source_id"], row["end_id"]): row for row in endpoints}
        restored_by_key = {(row["source_id"], row["end_id"]): row for row in restored_endpoints}
        if len(original_by_key) != len(endpoints) or restored_by_key != original_by_key:
            raise ValueError("Per-study GFF3 did not restore every original endpoint row")
        expected_annotations = {(row["source_id"], row["end_id"]): row for row in original_annotation_rows}
        restored_annotations = {
            (row["source_id"], row["end_id"]): row for row in iter_annotations(release_dir)
        }
        if len(expected_annotations) != len(original_annotation_rows) or restored_annotations != expected_annotations:
            raise ValueError("Study GFF3 and metadata did not restore every original annotation")
        if list(iter_related_rows(release_dir, "gene_associations")) != gene_rows:
            raise ValueError("Study gene-association TSV did not restore every original row")
        if list(iter_related_rows(release_dir, "condition_observations")) != condition_rows:
            raise ValueError("Study condition-observation TSV did not restore every original row")
        for retired_name in (
            "annotations.jsonl.gz",
            "gene_associations.jsonl.gz",
            "condition_observations.jsonl.gz",
        ):
            retired = release_dir / retired_name
            if retired.is_symlink():
                raise ValueError(f"Refusing to remove symlinked release file: {retired}")
            if retired.is_file():
                retired.unlink()
        compare_and_remove_old_endpoint_tsv(release_dir, legacy_core_header, endpoints)
        remove_obsolete_compressed_tsvs(release_dir)

        pending_cleanup = _retire_flat_release_files(
            release_dir,
            source_doc,
            write_gff3_bytes(endpoints, annotation_attributes),
            {
                "gene_associations": gene_tsv_bytes,
                "condition_observations": condition_tsv_bytes,
            },
        )

        release_doc = {
            "schema_version": "1.0",
            "release_version": "v0.3.0",
            "summary": "Per-study GFF3 and metadata folders, with gene associations and condition observations stored with their source studies.",
            "counts": {
                "source_count": len(source_doc["sources"]),
                "study_count": len(study_summaries),
                "endpoint_count": len(endpoints),
                "annotation_count": len(annotation_rows),
                "gene_association_count": len(gene_rows),
                "unlinked_gene_association_count": unlinked_gene_association_count(gene_rows),
                "condition_observation_count": len(condition_rows),
            },
            "legacy_archive": archive_info,
            "source_table_provenance": source_doc.get("source_table_provenance", {}),
            "studies": study_summaries,
            "files": {
                relative: {
                    "path": relative,
                    "sha256": sha256_bytes(payload),
                    "byte_size": len(payload),
                }
                for relative, payload in sorted(payloads.items())
            },
        }
        release_payload = json_bytes(release_doc)
        atomic_write(release_dir / "release.json", release_payload)
        check_paths = sorted(
            path for path in release_dir.rglob("*")
            if path.is_file()
            and path.name != "SHA256SUMS.txt"
            and not any(
                path.relative_to(release_dir).as_posix() == pending
                or path.relative_to(release_dir).as_posix().startswith(pending + "/")
                for pending in pending_cleanup
            )
        )
        sum_lines = [
            f"{sha256_file(path)}  {path.relative_to(release_dir).as_posix()}\n"
            for path in check_paths
        ]
        atomic_write(release_dir / "SHA256SUMS.txt", "".join(sum_lines).encode("utf-8"))

        # Validate while the immutable archive is available. A verified expanded
        # duplicate may be ignored here if Windows keeps it open; the default
        # validator remains strict when validating the release independently.
        from validate_bted_v0_3 import validate_release

        if pending_cleanup:
            summary = validate_release(root, ignored_expanded_duplicates=set(pending_cleanup))
            summary["cleanup_pending"] = pending_cleanup
        else:
            summary = validate_release(root)
        if prune:
            legacy_abs = (root / LEGACY_REL).resolve()
            root_abs = root.resolve()
            if root_abs not in legacy_abs.parents or legacy_abs != root_abs / LEGACY_REL:
                raise ValueError(f"Refusing to prune unexpected path: {legacy_abs}")
            if legacy_abs.exists():
                shutil.rmtree(legacy_abs)
            for path in sorted((root / "data/registry/manifests").glob("BATTER_S1_*.json")):
                path.unlink()
            for relative in (
                "data/registry/reference_contigs.v0.2.0.tsv",
                "data/registry/jbrowse_assets.v0.2.0.tsv",
                "data/registry/batter_s1_source_registry.tsv",
                "data/registry/batter_s1_publication_status.v0.2.0.tsv",
                "data/registry/batter_s1_license_status.v0.2.0.tsv",
                "data/registry/batter_s1_asset_redistribution.v0.3.tsv",
            ):
                path = root / relative
                if path.exists():
                    path.unlink()
            summary = validate_release(root)
        return summary
    finally:
        if scratch is not None and scratch.exists():
            scratch_abs = scratch.resolve()
            archive_abs = (root / "data/archive").resolve()
            if archive_abs not in scratch_abs.parents:
                raise ValueError(f"Refusing to clean unexpected scratch path: {scratch_abs}")
            def clear_readonly(operation, failed_path, _error):
                os.chmod(failed_path, stat.S_IWRITE)
                operation(failed_path)

            shutil.rmtree(scratch_abs, onexc=clear_readonly)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository root (defaults to this script's repository).")
    parser.add_argument("--prune-legacy", action="store_true", help="Remove unpacked legacy inputs after building (the v0.2.0 archive is retained).")
    args = parser.parse_args()
    summary = build_release(args.root.resolve(), prune=args.prune_legacy)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
