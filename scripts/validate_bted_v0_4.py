#!/usr/bin/env python3
"""Validate the BTED v0.4.0 genome-organized release and its v0.3 archive."""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import re
import shutil
import sys
import tarfile
import uuid
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from bted_v04_common import (
    EXPECTED_CASCINO_COUNTS,
    EXPECTED_CONDITION_OBSERVATIONS,
    EXPECTED_GENE_ASSOCIATIONS,
    EXPECTED_LINKED_GENE_ASSOCIATIONS,
    EXPECTED_OLD_ENDPOINTS,
    EXPECTED_UNLINKED_GENE_ASSOCIATIONS,
    GENOME_METADATA_COLUMNS,
    INTERNAL_REL,
    RELATED_TABLE_FILES,
    ROOT,
    V03_ARCHIVE_REL,
    V03_REL,
    V04_REL,
    endpoint_expected_default_fields,
    load_json,
    read_tsv,
    sha256_bytes,
    sha256_file,
    table_columns,
)
from v03_tables import (
    ENDPOINT_COLUMNS,
    GFF3_ROW_ATTRIBUTE_COLUMNS,
    iter_endpoints,
    iter_endpoint_feature_lines,
    iter_related_rows,
    iter_study_metadata,
    _gff3_unescape,
    _parse_attributes,
)
from build_bted_v0_4_release import (
    EXPECTED_CASCINO_ASSEMBLY,
    EXPECTED_CASCINO_EVIDENCE,
    EXPECTED_CASCINO_PMID,
    EXPECTED_EXTERNAL_ARCHIVE_REL,
    _safe_tar_name,
    verify_v03_archive,
    verify_v03_tree,
)


EXPECTED_ENDPOINTS = EXPECTED_OLD_ENDPOINTS + sum(EXPECTED_CASCINO_COUNTS.values())
EXPECTED_COUNTS = {
    "source_count": 25,
    "published_source_count": 24,
    "audit_only_source_count": 1,
    "study_count": 14,
    "genome_study_count": 23,
    "genome_count": 21,
    "endpoint_count": EXPECTED_ENDPOINTS,
    "old_endpoint_count": EXPECTED_OLD_ENDPOINTS,
    "cascino_endpoint_count": sum(EXPECTED_CASCINO_COUNTS.values()),
    "gene_association_count": EXPECTED_GENE_ASSOCIATIONS,
    "linked_gene_association_count": EXPECTED_LINKED_GENE_ASSOCIATIONS,
    "unlinked_gene_association_count": EXPECTED_UNLINKED_GENE_ASSOCIATIONS,
    "condition_observation_count": EXPECTED_CONDITION_OBSERVATIONS,
}


def _fail(message: str) -> None:
    raise ValueError(message)


def _read_checksum_file(path: Path) -> dict[str, str]:
    if not path.is_file() or path.is_symlink():
        _fail(f"Checksum file is missing or symlinked: {path}")
    result: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        pieces = line.split("  ", 1)
        if len(pieces) != 2 or not re.fullmatch(r"[0-9a-f]{64}", pieces[0]):
            _fail(f"Malformed checksum at {path}:{number}")
        if pieces[1] in result:
            _fail(f"Duplicate checksum path at {path}:{number}: {pieces[1]}")
        result[pieces[1]] = pieces[0]
    return result


def _verify_external_archive(root: Path, manifest: dict[str, Any]) -> None:
    archive = root / EXPECTED_EXTERNAL_ARCHIVE_REL
    sidecar = archive.with_name(archive.name + ".sha256")
    if not archive.is_file() or not sidecar.is_file():
        _fail("The archived external source/audit materials are missing")
    archive_hash = sha256_file(archive)
    expected_sidecar = f"{archive_hash}  {archive.name}\n"
    if sidecar.read_text(encoding="ascii") != expected_sidecar:
        _fail("External review archive SHA-256 sidecar mismatch")
    external = manifest.get("external_review_archive", {})
    if external.get("status") != "archived" or external.get("sha256") != archive_hash:
        _fail("Internal provenance does not identify the verified external review archive")
    actual = []
    with tarfile.open(archive, "r:gz") as bundle:
        seen = set()
        for member in bundle.getmembers():
            _safe_tar_name(member.name)
            if not member.isfile() or member.name in seen:
                _fail(f"External archive has an invalid or duplicate member: {member.name}")
            if member.mtime != 0 or member.mode != 0o644 or member.uid != 0 or member.gid != 0:
                _fail(f"External archive metadata is not deterministic for {member.name}")
            seen.add(member.name)
            content = bundle.extractfile(member)
            if content is None:
                _fail(f"Cannot read archived external input: {member.name}")
            data = content.read()
            actual.append({"member": member.name, "byte_size": len(data), "sha256": sha256_bytes(data)})
    if len(actual) != 91:
        _fail(f"Expected 91 preserved external intake/audit files, found {len(actual)}")
    if archive.read_bytes()[4:8] != b"\x00\x00\x00\x00":
        _fail("External archive gzip timestamp is not deterministic")
    actual.sort(key=lambda row: row["member"])
    if actual != external.get("members"):
        _fail("Internal external-archive member checksums do not match the archive")


def _verify_internal_provenance(root: Path, public_source_ids: set[str]) -> dict[str, Any]:
    internal_dir = root / INTERNAL_REL
    manifest_path = internal_dir / "source_provenance.json"
    sidecar_path = internal_dir / "SHA256SUMS.txt"
    if not manifest_path.is_file() or not sidecar_path.is_file():
        _fail("Internal source provenance or checksum sidecar is missing")
    raw = manifest_path.read_bytes()
    sums = _read_checksum_file(sidecar_path)
    if sums != {"source_provenance.json": sha256_bytes(raw)}:
        _fail("Internal source provenance checksum mismatch")
    manifest = json.loads(raw.decode("utf-8"))
    if manifest.get("release_version") != "v0.4.0":
        _fail("Internal source provenance does not describe v0.4.0")
    sources = manifest.get("sources")
    if not isinstance(sources, list):
        _fail("Internal provenance sources must be an array")
    source_index = {}
    for source in sources:
        source_id = source.get("source_id")
        if not source_id or source_id in source_index:
            _fail(f"Missing or duplicate source in internal provenance: {source_id!r}")
        source_index[source_id] = source
    if set(source_index) != public_source_ids:
        _fail("Internal provenance source IDs differ from the public genome metadata")
    if not all("table_defaults" in source and "endpoints" in source["table_defaults"] for source in sources if source.get("publication_status", {}).get("release_status") != "audit_only"):
        _fail("A published source is missing endpoint defaults")
    _verify_external_archive(root, manifest)
    archived_members = {
        row["member"]: row for row in manifest["external_review_archive"]["members"]
    }
    intake = manifest.get("external_source_intake", {})
    intake_member = archived_members.get(intake.get("original_path"))
    if not intake_member or intake_member.get("sha256") != intake.get("sha256") or intake_member.get("byte_size") != intake.get("byte_size"):
        _fail("Original source intake checksum is not tied to the preserved review archive")
    intake_bytes = _archive_member(root, intake["original_path"])
    intake_reader = csv.DictReader(io.StringIO(intake_bytes.decode("utf-8-sig"), newline=""), delimiter="\t")
    intake_rows_from_archive = [{name: str(value) for name, value in row.items()} for row in intake_reader]
    if list(intake_reader.fieldnames or []) != intake.get("columns") or intake_rows_from_archive != intake.get("rows"):
        _fail("Internal source intake rows differ from the archived original TSV")
    expected_review_rows = [row for row in intake_rows_from_archive if row.get("source_id") not in EXPECTED_CASCINO_COUNTS]
    if expected_review_rows != intake.get("review_only_rows"):
        _fail("Review-only Fuchs, TERMITe, or duplicate-source intake rows were not preserved")
    source_tables = manifest.get("cascino_decision", {}).get("raw_source_tables", [])
    if {row.get("source_id") for row in source_tables} != set(EXPECTED_CASCINO_COUNTS):
        _fail("Internal provenance lacks one or more original Cascino endpoint TSVs")
    if sum(row.get("included_row_count", 0) for row in source_tables) != 1_061 or sum(row.get("excluded_row_count", 0) for row in source_tables) != 196:
        _fail("Internal Cascino source-table included/excluded row totals are incorrect")
    for item in source_tables:
        if item.get("included_row_count") != EXPECTED_CASCINO_COUNTS[item["source_id"]]:
            _fail(f"Internal Cascino inclusion count differs for {item['source_id']}")
        member = archived_members.get(item.get("original_path"))
        if not member or member.get("sha256") != item.get("sha256") or member.get("byte_size") != item.get("byte_size"):
            _fail(f"Original Cascino TSV checksum is not tied to the review archive: {item.get('source_id')}")
    decision = manifest.get("cascino_decision", {})
    for document in decision.get("audit_documents", []):
        member = archived_members.get(document.get("original_path"))
        if not member or member.get("sha256") != document.get("sha256") or member.get("byte_size") != document.get("byte_size"):
            _fail(f"Cascino audit document checksum is not tied to the review archive: {document.get('original_path')}")
    table_audit = decision.get("independent_original_table_audit", {})
    expected_sheets = {
        "BTED_EXT_2026_102": ("Syn_WT", 388),
        "BTED_EXT_2026_103": ("Syn_∆mfd_rep1", 331),
        "BTED_EXT_2026_104": ("Syn_∆mfd_rep2", 342),
    }
    actual_sheets = table_audit.get("source_sheet_row_comparison", {})
    if table_audit.get("status") != "pass" or table_audit.get("missing_rows") != 0 or table_audit.get("extra_rows") != 0:
        _fail("Independent original-table audit is missing or incomplete")
    if any(
        actual_sheets.get(source_id, {}).get("sheet") != sheet
        or actual_sheets.get(source_id, {}).get("rows_matched") != count
        for source_id, (sheet, count) in expected_sheets.items()
    ):
        _fail("Independent original-table comparison does not cover all selected Cascino rows")
    if table_audit.get("license_verification", {}).get("license") != "CC BY 4.0" or table_audit.get("license_verification", {}).get("status") != "pass":
        _fail("Cascino license verification is absent from internal provenance")
    return manifest


def _archive_member(root: Path, member_name: str) -> bytes:
    archive_path = root / EXPECTED_EXTERNAL_ARCHIVE_REL
    with tarfile.open(archive_path, "r:gz") as bundle:
        member = bundle.getmember(member_name)
        if not member.isfile():
            _fail(f"External archive member is not a file: {member_name}")
        content = bundle.extractfile(member)
        if content is None:
            _fail(f"Cannot read external archive member: {member_name}")
        return content.read()


def _cascino_input_rows(root: Path, manifest: dict[str, Any], source_id: str) -> list[dict[str, str]]:
    table_entry = next(
        (item for item in manifest["cascino_decision"]["raw_source_tables"] if item["source_id"] == source_id),
        None,
    )
    if table_entry is None:
        _fail(f"Internal provenance has no original Cascino endpoint table for {source_id}")
    live_path = root / table_entry["original_path"]
    data = _archive_member(root, table_entry["original_path"])
    if data is None and live_path.is_file():
        data = live_path.read_bytes()
    if data is None:
        _fail(f"Original Cascino table is not present in source archive or checkout: {source_id}")
    if len(data) != table_entry["byte_size"] or sha256_bytes(data) != table_entry["sha256"]:
        _fail(f"Original Cascino table checksum mismatch for {source_id}")
    import io

    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""), delimiter="\t")
    if tuple(reader.fieldnames or ()) != tuple(ENDPOINT_COLUMNS):
        _fail(f"Original Cascino table schema mismatch for {source_id}")
    raw_rows = [{name: str(value) for name, value in row.items()} for row in reader]
    if len(raw_rows) != table_entry.get("raw_row_count"):
        _fail(f"Original Cascino table raw row count mismatch for {source_id}")
    included_rows = [
        row for row in raw_rows
        if row["evidence_class"] == EXPECTED_CASCINO_EVIDENCE and row["author_category"] == "defined end"
    ]
    excluded_rows = [
        row for row in raw_rows
        if not (row["evidence_class"] == EXPECTED_CASCINO_EVIDENCE and row["author_category"] == "defined end")
    ]
    if len(included_rows) != table_entry.get("included_row_count") or len(excluded_rows) != table_entry.get("excluded_row_count"):
        _fail(f"Original Cascino included/excluded row counts mismatch for {source_id}")
    if any(
        row["evidence_class"] != "called_endpoint"
        or row["author_category"] not in {"diffuse end (diffuse peak)", "undetermined"}
        for row in excluded_rows
    ):
        _fail(f"Original Cascino secondary candidates have unexpected categories for {source_id}")
    return included_rows


def _public_file_entries(release_dir: Path, release_doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = release_doc.get("files")
    if not isinstance(entries, list):
        _fail("release.json files must be an array")
    actual_entries: dict[str, dict[str, Any]] = {}
    for item in entries:
        if not isinstance(item, dict) or set(item) != {"path", "byte_size", "sha256"}:
            _fail(f"Malformed release file entry: {item!r}")
        relative = item["path"]
        if not isinstance(relative, str) or relative in actual_entries:
            _fail(f"Missing or duplicate public file path: {relative!r}")
        if relative.startswith("/") or ".." in PurePosixPath(relative).parts:
            _fail(f"Unsafe path in release.json: {relative}")
        path = release_dir / Path(*PurePosixPath(relative).parts)
        if not path.is_file() or path.is_symlink():
            _fail(f"Manifest file is missing or symlinked: {relative}")
        if path.stat().st_size != item["byte_size"] or sha256_file(path) != item["sha256"]:
            _fail(f"Public release file size/SHA-256 mismatch: {relative}")
        actual_entries[relative] = item
    if list(actual_entries) != sorted(actual_entries):
        _fail("release.json file entries are not sorted by path")
    actual_tree = {}
    for path in release_dir.rglob("*"):
        if path.is_symlink():
            _fail(f"Symlink in public release tree: {path}")
        if path.is_file() and path.name not in {"release.json", "SHA256SUMS.txt"}:
            relative = path.relative_to(release_dir).as_posix()
            actual_tree[relative] = path
    if set(actual_tree) != set(actual_entries):
        _fail("Public release files differ from release.json files")
    sums = _read_checksum_file(release_dir / "SHA256SUMS.txt")
    expected_sums = {path: entry["sha256"] for path, entry in actual_entries.items()}
    if sums != expected_sums:
        _fail("SHA256SUMS.txt does not match the public release file list")
    return actual_entries


def _metadata_index(release_dir: Path, release_doc: dict[str, Any], files: dict[str, dict[str, Any]]) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    genomes = release_doc.get("genomes")
    if not isinstance(genomes, list) or len(genomes) != EXPECTED_COUNTS["genome_count"]:
        _fail("release.json genome list does not contain 21 assemblies")
    sources: dict[str, dict[str, str]] = {}
    source_assembly: dict[str, str] = {}
    seen_assemblies = set()
    genome_study_count = 0
    distinct_pmids = set()
    for genome in genomes:
        assembly = genome.get("assembly", "")
        if assembly in seen_assemblies or not assembly.startswith(("GCF_", "GCA_")):
            _fail(f"Missing, duplicate, or invalid genome assembly: {assembly!r}")
        seen_assemblies.add(assembly)
        metadata_path = genome.get("metadata_path")
        expected_path = f"genomes/{assembly}/metadata.tsv"
        if metadata_path != expected_path or metadata_path not in files:
            _fail(f"Genome metadata path mismatch for {assembly}")
        header, rows = read_tsv(release_dir / metadata_path)
        if tuple(header) != tuple(GENOME_METADATA_COLUMNS):
            _fail(f"{metadata_path}: metadata.tsv header mismatch")
        if len(rows) != genome.get("source_count"):
            _fail(f"{metadata_path}: source count differs from release.json")
        for row in rows:
            source_id = row["source_id"]
            if not source_id or source_id in sources:
                _fail(f"Missing or duplicate genome metadata source ID: {source_id!r}")
            if row["assembly"] != assembly:
                _fail(f"{metadata_path}: row assembly mismatch for {source_id}")
            if not row["pmid"] or not row["record_count"].isdigit():
                _fail(f"{metadata_path}: invalid PMID or record_count for {source_id}")
            if row["release_status"] == "audit_only" and row["record_count"] != "0":
                _fail(f"Audit-only source has endpoint records: {source_id}")
            sources[source_id] = row
            source_assembly[source_id] = assembly
        studies = genome.get("studies")
        if not isinstance(studies, list):
            _fail(f"{assembly}: release.json studies must be an array")
        if len(studies) != genome.get("study_count"):
            _fail(f"{assembly}: study_count differs from nested study list")
        genome_study_count += len(studies)
        seen_pmids = set()
        for study in studies:
            pmid = study.get("pmid", "")
            if not pmid or pmid in seen_pmids or study.get("path") != f"studies/PMID_{pmid}":
                _fail(f"{assembly}: missing/duplicate PMID or invalid study path")
            seen_pmids.add(pmid)
            distinct_pmids.add(pmid)
            expected_source_ids = sorted(
                source_id for source_id, row in sources.items()
                if source_assembly[source_id] == assembly and row["pmid"] == pmid
            )
            if study.get("source_ids") != expected_source_ids or study.get("source_count") != len(expected_source_ids):
                _fail(f"{assembly}/{pmid}: source IDs do not match metadata.tsv")
            for source_id in expected_source_ids:
                row = sources[source_id]
                for column, filename in (
                    ("study_gff3", "endpoints.gff3.gz"),
                    ("gene_associations", RELATED_TABLE_FILES["gene_associations"]),
                    ("condition_observations", RELATED_TABLE_FILES["condition_observations"]),
                ):
                    stored = row[column]
                    target = f"{study['path']}/{filename}"
                    if stored and stored != target:
                        _fail(f"{source_id}: {column} path does not match its study")
                    if stored and f"genomes/{assembly}/{stored}" not in files:
                        _fail(f"{source_id}: referenced {column} file is absent from the release")
            for source_id in expected_source_ids:
                if sources[source_id]["release_status"] != "audit_only" and sources[source_id]["record_count"] != "0":
                    expected_gff = f"studies/PMID_{pmid}/endpoints.gff3.gz"
                    if sources[source_id]["study_gff3"] != expected_gff:
                        _fail(f"Published source has no endpoint GFF3 path: {source_id}")
            count = sum(int(sources[source_id]["record_count"]) for source_id in expected_source_ids)
            if count != study.get("endpoint_count"):
                _fail(f"{assembly}/{pmid}: endpoint count differs from metadata.tsv")
            if study.get("status") == "audit_only" and count != 0:
                _fail(f"Audit-only study contains endpoint records: {assembly}/{pmid}")
    if len(sources) != EXPECTED_COUNTS["source_count"]:
        _fail(f"Expected 25 source metadata rows, found {len(sources)}")
    if len(distinct_pmids) != EXPECTED_COUNTS["study_count"]:
        _fail(f"Expected 14 unique study PMIDs, found {len(distinct_pmids)}")
    if genome_study_count != EXPECTED_COUNTS["genome_study_count"]:
        _fail(f"Expected 23 genome-study relationships, found {genome_study_count}")
    return sources, source_assembly


def _decode_endpoint_features(release_dir: Path, genomes: list[dict[str, Any]], source_rows: dict[str, dict[str, str]], source_assembly: dict[str, str], source_index: dict[str, dict[str, Any]]) -> tuple[dict[tuple[str, str], dict[str, str]], Counter[str]]:
    endpoints: dict[tuple[str, str], dict[str, str]] = {}
    counts: Counter[str] = Counter()
    for genome in genomes:
        assembly = genome["assembly"]
        for study in genome["studies"]:
            pmid = study["pmid"]
            gff_relative = f"genomes/{assembly}/{study['path']}/endpoints.gff3.gz"
            path = release_dir / Path(*PurePosixPath(gff_relative).parts)
            if not path.exists():
                expected_rows = sum(
                    int(row["record_count"]) for source_id, row in source_rows.items()
                    if source_assembly[source_id] == assembly and row["pmid"] == pmid
                )
                if expected_rows != 0:
                    _fail(f"GFF3 file is missing for {assembly}/{pmid}")
                continue
            if path.is_symlink() or not path.is_file():
                _fail(f"GFF3 path is symlinked or not a file: {gff_relative}")
            source_counts: Counter[str] = Counter()
            with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
                for line_number, raw_line in enumerate(handle, 1):
                    line = raw_line.rstrip("\r\n")
                    if line_number == 1:
                        if line != "##gff-version 3":
                            _fail(f"{gff_relative}: missing GFF3 version line")
                        continue
                    if not line or line.startswith("#"):
                        continue
                    cols = line.split("\t")
                    label = f"{gff_relative}:{line_number}"
                    if len(cols) != 9:
                        _fail(f"{label}: expected 9 GFF3 columns")
                    seqid, source_id, feature, start, end, score, strand, phase, raw_attrs = cols
                    seqid = _gff3_unescape(seqid)
                    source_id = _gff3_unescape(source_id)
                    meta = source_rows.get(source_id)
                    source = source_index.get(source_id)
                    if meta is None or source is None:
                        _fail(f"{label}: source is missing from metadata/provenance")
                    if source_assembly.get(source_id) != assembly or meta["pmid"] != pmid:
                        _fail(f"{label}: source is assigned to another assembly or PMID")
                    if feature != "terminator_endpoint" or score != "." or phase != ".":
                        _fail(f"{label}: invalid GFF3 feature, score, or phase")
                    if not start.isdigit() or start != end or int(start) < 1:
                        _fail(f"{label}: endpoint must be a canonical 1-based single-base feature")
                    if strand not in {"+", "-", ".", "?"}:
                        _fail(f"{label}: invalid strand")
                    attrs = _parse_attributes(raw_attrs, label)
                    annotation_map = source.get("annotation_field_map", {})
                    extra = {
                        item["attribute"] for item in annotation_map.values()
                        if isinstance(item, dict) and item.get("from") == "attribute" and isinstance(item.get("attribute"), str)
                    }
                    if set(attrs) != {"ID", *GFF3_ROW_ATTRIBUTE_COLUMNS, *extra}:
                        _fail(f"{label}: GFF3 attributes differ from the source schema")
                    defaults = (source.get("table_defaults") or {}).get("endpoints", {})
                    if not endpoint_expected_default_fields().issubset(defaults):
                        _fail(f"{label}: source defaults omit endpoint fields")
                    row = {name: str(defaults.get(name, "")) for name in ENDPOINT_COLUMNS}
                    row.update({name: attrs[name] for name in GFF3_ROW_ATTRIBUTE_COLUMNS})
                    row.update({
                        "end_id": attrs["ID"],
                        "source_id": source_id,
                        "reference_name": seqid,
                        "biological_coordinate_1based": start,
                        "bed_start_0based": str(int(start) - 1),
                        "bed_end_0based": end,
                        "strand": strand,
                    })
                    key = (source_id, row["end_id"])
                    if not row["end_id"] or key in endpoints:
                        _fail(f"{label}: missing or duplicate source/end ID")
                    if row["pmid"] != pmid or row["reference_assembly"] != assembly:
                        _fail(f"{label}: source defaults disagree with file location")
                    endpoints[key] = {name: row[name] for name in ENDPOINT_COLUMNS}
                    source_counts[source_id] += 1
                    counts[source_id] += 1
            for source_id in source_counts:
                if source_counts[source_id] != int(source_rows[source_id]["record_count"]):
                    _fail(f"{source_id}: metadata record_count differs from GFF3 feature count")
            if sum(source_counts.values()) != study.get("endpoint_count"):
                _fail(f"{assembly}/{pmid}: study endpoint count differs from GFF3")
    for source_id, row in source_rows.items():
        if counts[source_id] != int(row["record_count"]):
            _fail(f"{source_id}: total source record count mismatch")
    if sum(counts.values()) != EXPECTED_ENDPOINTS:
        _fail(f"Expected {EXPECTED_ENDPOINTS} public endpoints, found {sum(counts.values())}")
    return endpoints, counts


def _table_rows(release_dir: Path, source_rows: dict[str, dict[str, str]], source_assembly: dict[str, str], endpoints: dict[tuple[str, str], dict[str, str]], table: str) -> list[dict[str, str]]:
    filename = RELATED_TABLE_FILES[table]
    result = []
    allowed_columns = table_columns(table)
    files_to_read: set[Path] = set()
    for source_id, source in source_rows.items():
        path_value = source["gene_associations"] if table == "gene_associations" else source["condition_observations"]
        if not path_value:
            continue
        assembly = source_assembly[source_id]
        full_path = release_dir / "genomes" / assembly / Path(*PurePosixPath(path_value).parts)
        if full_path.name != filename:
            _fail(f"Unexpected related-table filename for {source_id}: {path_value}")
        files_to_read.add(full_path)
    for full_path in sorted(files_to_read):
        path_value = full_path.relative_to(release_dir).as_posix()
        with gzip.open(full_path, "rt", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            if tuple(reader.fieldnames or ()) != allowed_columns:
                _fail(f"{path_value}: related table schema differs from the full source schema")
            for line_number, row in enumerate(reader, 2):
                if None in row or any(value is None for value in row.values()):
                    _fail(f"{path_value}:{line_number}: invalid row width")
                values = {name: str(row[name]) for name in allowed_columns}
                source_id = values["source_id"]
                source = source_rows.get(source_id)
                if source is None or source_assembly[source_id] != full_path.parts[-4]:
                    _fail(f"{path_value}:{line_number}: source is not assigned to this genome")
                study_pmid = full_path.parts[-2].removeprefix("PMID_")
                if values["pmid"] != source["pmid"] or values["pmid"] != study_pmid:
                    _fail(f"{path_value}:{line_number}: source/PMID mismatch")
                end_id = values["end_id"]
                if end_id:
                    if values["link_status"] != "linked" or (source_id, end_id) not in endpoints:
                        _fail(f"{path_value}:{line_number}: linked row points to absent endpoint")
                    parent = endpoints[(source_id, end_id)]
                    for name in ("reference_name", "biological_coordinate_1based", "strand"):
                        if table == "gene_associations" and values[name] not in {"", parent[name]}:
                            _fail(f"{path_value}:{line_number}: linked gene row conflicts with endpoint {name}")
                        if table == "condition_observations" and values[name] != parent[name]:
                            _fail(f"{path_value}:{line_number}: condition row conflicts with endpoint {name}")
                elif table == "condition_observations":
                    _fail(f"{path_value}:{line_number}: condition observation has no endpoint link")
                elif values["link_status"] != "unlinked_author_annotation":
                    _fail(f"{path_value}:{line_number}: gene row without endpoint is not marked unlinked")
                elif not all(values[name] for name in ("reference_name", "biological_coordinate_1based", "strand")):
                    _fail(f"{path_value}:{line_number}: unlinked gene row lost its own coordinates")
                try:
                    position = int(values["biological_coordinate_1based"])
                    bed_start = int(values["bed_start_0based"])
                    bed_end = int(values["bed_end_0based"])
                except ValueError:
                    _fail(f"{path_value}:{line_number}: invalid coordinate fields")
                if position < 1 or bed_start != position - 1 or bed_end != position:
                    _fail(f"{path_value}:{line_number}: invalid 1-based/BED coordinate mapping")
                result.append(values)
    return result


def _multiset(rows: Iterable[dict[str, str]], columns: Iterable[str]) -> Counter[tuple[str, ...]]:
    fields = tuple(columns)
    return Counter(tuple(row[name] for name in fields) for row in rows)


def _verify_old_release_equality(root: Path, release_dir: Path, current: dict[tuple[str, str], dict[str, str]], current_tables: dict[str, list[dict[str, str]]]) -> dict[str, Any]:
    archive_info = verify_v03_archive(root)
    temporary_root = root / "tmp"
    temporary_root.mkdir(exist_ok=True)
    temporary = temporary_root / f"bted-v03-audit-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        from build_bted_v0_4_release import _extract_v03_archive

        old_root = _extract_v03_archive(root, temporary / "previous")
        old_rows = list(iter_endpoints(old_root))
        if len(old_rows) != EXPECTED_OLD_ENDPOINTS:
            _fail(f"v0.3.0 archive reconstructs {len(old_rows)} endpoints, expected {EXPECTED_OLD_ENDPOINTS}")
        old_index = {(row["source_id"], row["end_id"]): row for row in old_rows}
        if len(old_index) != len(old_rows):
            _fail("v0.3.0 archive contains duplicate source/end IDs")
        current_old = {key: row for key, row in current.items() if not key[0].startswith("BTED_EXT_")}
        if set(old_index) != set(current_old):
            _fail("v0.4.0 does not preserve the v0.3.0 endpoint keys exactly")
        changed = [key for key in old_index if old_index[key] != current_old[key]]
        if changed:
            _fail(f"v0.4.0 changed old endpoint field values, first key: {changed[0]}")

        old_table_rows = {
            table: list(iter_related_rows(old_root, table))
            for table in RELATED_TABLE_FILES
        }
        for table, columns in (("gene_associations", table_columns("gene_associations")),
                               ("condition_observations", table_columns("condition_observations"))):
            if _multiset(old_table_rows[table], columns) != _multiset(current_tables[table], columns):
                _fail(f"v0.4.0 changed source table values from v0.3.0: {table}")
        old_source_objects = {
            source["source_id"]: source
            for _study_dir, metadata in iter_study_metadata(old_root)
            for source in metadata["sources"]
        }
        old_release_doc = load_json(old_root / "release.json")
        return {
            "archive": archive_info,
            "old_endpoint_count": len(old_rows),
            "old_source_ids": set(old_source_objects),
            "old_source_objects": old_source_objects,
            "old_legacy_archive": old_release_doc.get("legacy_archive", {}),
        }
    finally:
        shutil.rmtree(temporary)


def validate_release(root: Path = ROOT, *, release_dir: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    release_dir = (release_dir or (root / V04_REL)).resolve()
    expected_release = (root / V04_REL).resolve()
    if release_dir != expected_release:
        _fail(f"Release directory must be exactly {expected_release}")
    if not release_dir.is_dir() or release_dir.is_symlink():
        _fail(f"v0.4.0 public release directory is missing or symlinked: {release_dir}")
    release_doc = load_json(release_dir / "release.json")
    if release_doc.get("release_version") != "v0.4.0" or release_doc.get("schema_version") != "1.0":
        _fail("release.json does not identify BTED v0.4.0 schema 1.0")
    counts = release_doc.get("counts", {})
    for name, expected in EXPECTED_COUNTS.items():
        if counts.get(name) != expected:
            _fail(f"release.json count mismatch for {name}: {counts.get(name)!r} != {expected}")

    files = _public_file_entries(release_dir, release_doc)
    allowed_root = {"genomes", "release.json", "SHA256SUMS.txt"}
    actual_root = {path.name for path in release_dir.iterdir()}
    if actual_root != allowed_root:
        _fail(f"Unexpected public release root files: {sorted(actual_root)}")
    for path in release_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() == ".json" and path.name != "release.json":
            _fail(f"Public user payload contains a JSON file: {path.relative_to(release_dir)}")
        if path.is_file() and (path.suffix.lower() in {".bed", ".csv"}):
            _fail(f"Public v0.4.0 release contains a non-contract format: {path.relative_to(release_dir)}")

    source_rows, source_assembly = _metadata_index(release_dir, release_doc, files)
    source_ids = set(source_rows)
    internal = _verify_internal_provenance(root, source_ids)
    source_index = {source["source_id"]: source for source in internal["sources"]}
    if set(source_index) != source_ids:
        _fail("Internal source index IDs differ from public metadata")

    cascino_ids = set(EXPECTED_CASCINO_COUNTS)
    if cascino_ids - source_ids:
        _fail("One or more approved Cascino sources are missing")
    if source_ids & {"BTED_EXT_2026_101", "BTED_EXT_2026_105", *[f"BTED_EXT_2026_{n}" for n in range(106, 114)]}:
        _fail("A Fuchs or TERMITe review-only source is present in the public release")
    old_source_ids = source_ids - cascino_ids
    if len(old_source_ids) != 22:
        _fail(f"Expected 22 v0.3.0 source records, found {len(old_source_ids)}")

    endpoints, endpoint_counts = _decode_endpoint_features(
        release_dir,
        release_doc["genomes"],
        source_rows,
        source_assembly,
        source_index,
    )
    if len(endpoints) != EXPECTED_ENDPOINTS:
        _fail("Reconstructed endpoint row total differs from the release count")
    for source_id, expected in EXPECTED_CASCINO_COUNTS.items():
        source_features = [row for key, row in endpoints.items() if key[0] == source_id]
        if endpoint_counts[source_id] != expected or any(
            row["evidence_class"] != EXPECTED_CASCINO_EVIDENCE or row["author_category"] != "defined end"
            for row in source_features
        ):
            _fail(f"{source_id}: released rows/count/evidence differ from the approved 1061-row selection")
    if sum(endpoint_counts[source_id] for source_id in cascino_ids) != 1_061:
        _fail("Cascino v0.4.0 endpoint total is not 1,061")

    tables = {
        table: _table_rows(release_dir, source_rows, source_assembly, endpoints, table)
        for table in RELATED_TABLE_FILES
    }
    gene_rows = tables["gene_associations"]
    linked = [row for row in gene_rows if row["link_status"] == "linked"]
    unlinked = [row for row in gene_rows if row["link_status"] == "unlinked_author_annotation"]
    if len(gene_rows) != EXPECTED_GENE_ASSOCIATIONS:
        _fail(f"Expected {EXPECTED_GENE_ASSOCIATIONS} gene rows, found {len(gene_rows)}")
    if (len(linked), len(unlinked)) != (EXPECTED_LINKED_GENE_ASSOCIATIONS, EXPECTED_UNLINKED_GENE_ASSOCIATIONS):
        _fail(f"Gene association counts differ: linked={len(linked)}, unlinked={len(unlinked)}")
    if len(tables["condition_observations"]) != EXPECTED_CONDITION_OBSERVATIONS:
        _fail("Condition observation count differs from 2,277")

    equality = _verify_old_release_equality(root, release_dir, endpoints, tables)
    expected_source_ids = set(equality["old_source_ids"]) | cascino_ids
    if source_ids != expected_source_ids:
        _fail("Public source IDs differ from the archived v0.3.0 set plus the three approved Cascino sources")
    if any(source_index[source_id] != old_source for source_id, old_source in equality["old_source_objects"].items()):
        _fail("Internal provenance changed a v0.3.0 source metadata field")
    if source_rows.get("BATTER_S1_002", {}).get("release_status") != "audit_only" or source_rows["BATTER_S1_002"]["record_count"] != "0":
        _fail("BATTER_S1_002 is not preserved as an audit-only source")
    # Compare each selected Cascino row back to its exact source TSV, including IDs and all original columns.
    for source_id, expected_count in EXPECTED_CASCINO_COUNTS.items():
        original_rows = _cascino_input_rows(root, internal, source_id)
        current_rows = [row for key, row in endpoints.items() if key[0] == source_id]
        if len(original_rows) != expected_count or _multiset(original_rows, ENDPOINT_COLUMNS) != _multiset(current_rows, ENDPOINT_COLUMNS):
            _fail(f"{source_id}: v0.4.0 GFF3 does not round-trip the included source TSV")

    source_table_rows = internal.get("external_source_intake", {}).get("rows", [])
    intake_by_id = {row.get("source_id"): row for row in source_table_rows}
    if any(source_id not in intake_by_id for source_id in cascino_ids):
        _fail("Internal manifest lost the original Cascino source intake rows")
    decision = internal.get("cascino_decision", {})
    if decision.get("excluded_secondary_rows") != 196 or decision.get("included_total") != 1_061:
        _fail("Internal Cascino selection/exclusion decision counts are incorrect")
    audit_docs = {item["original_path"]: item.get("utf8_text", "") for item in decision.get("audit_documents", [])}
    exclusion_text = audit_docs.get("data/external_source_draft/cascino_exclusion_report.txt", "")
    if "最高置信度 1061" not in exclusion_text or "次级置信度 196" not in exclusion_text:
        _fail("Internal provenance does not preserve the Cascino exclusion count evidence")
    if decision.get("excluded_sources_are_not_public") is not True:
        _fail("Internal Cascino decision does not state that the 196 secondary rows are excluded")

    old_archive = release_doc.get("legacy_archive", {}).get("v0.2.0", {})
    old_archive_path = root / "data/archive/BTED-v0.2.0.tar.gz"
    if old_archive != equality["old_legacy_archive"].get("v0.2.0", equality["old_legacy_archive"]):
        _fail("The v0.2.0 archive reference differs from v0.3.0")
    if not old_archive_path.is_file() or sha256_file(old_archive_path) != old_archive.get("sha256"):
        _fail("The v0.2.0 archive changed or does not match its preserved hash")
    if old_archive.get("path") != "data/archive/BTED-v0.2.0.tar.gz":
        _fail("The v0.2.0 archive path changed")

    return {
        "release_version": "v0.4.0",
        "files": len(files),
        "counts": counts,
        "old_endpoint_rows_compared": equality["old_endpoint_count"],
        "cascino_source_counts": EXPECTED_CASCINO_COUNTS,
        "gene_rows": len(gene_rows),
        "linked_gene_rows": len(linked),
        "unlinked_gene_rows": len(unlinked),
        "condition_observations": len(tables["condition_observations"]),
        "v03_archive_sha256": equality["archive"]["sha256"],
        "external_archive_sha256": internal["external_review_archive"]["sha256"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository root (default: this checkout)")
    args = parser.parse_args(argv)
    try:
        report = validate_release(args.root)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print("PASS v0.4.0 release validated")
        return 0
    except Exception as exc:  # CLI error boundary
        print(f"FAIL {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
