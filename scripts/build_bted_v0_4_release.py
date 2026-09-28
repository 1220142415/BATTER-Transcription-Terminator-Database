#!/usr/bin/env python3
"""Build the genome-organized, checksum-verifiable BTED v0.4.0 data release."""

from __future__ import annotations

import argparse
import copy
import csv
import gzip
import io
import json
import os
import shutil
import sys
import tarfile
import uuid
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any

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
    V03_ARCHIVE_SHA_REL,
    V03_ARCHIVE_SUMS_REL,
    V03_REL,
    V04_REL,
    atomic_write,
    deterministic_gzip,
    json_bytes,
    load_json,
    sha256_bytes,
    sha256_file,
    table_columns,
    tsv_bytes,
)
from v03_tables import (
    ENDPOINT_COLUMNS,
    GFF3_ROW_ATTRIBUTE_COLUMNS,
    format_endpoint_gff3,
    iter_endpoint_feature_lines,
    iter_related_rows,
    iter_study_metadata,
    source_pmid,
    source_record_count,
    study_metadata_tsv_row,
)


EXPECTED_V03_ARCHIVE_FILES = 43
EXPECTED_SOURCE_COUNT = 25
EXPECTED_AUDIT_ONLY_SOURCE_COUNT = 1
EXPECTED_PUBLIC_STUDY_COUNT = 14
EXPECTED_CASCINO_INPUT_COUNTS = {
    "BTED_EXT_2026_102": 474,
    "BTED_EXT_2026_103": 384,
    "BTED_EXT_2026_104": 399,
}
EXPECTED_ENDPOINTS = EXPECTED_OLD_ENDPOINTS + sum(EXPECTED_CASCINO_COUNTS.values())
EXPECTED_CASCINO_PMID = "42148773"
EXPECTED_CASCINO_ASSEMBLY = "GCF_000012525.1"
EXPECTED_CASCINO_REFERENCE = "CP000100.1"
EXPECTED_CASCINO_EVIDENCE = "author_called_endpoint"
EXPECTED_EXTERNAL_ARCHIVE_REL = Path("data/archive/BTED-external-intake-2026-08-10.tar.gz")


def _safe_tar_name(name: str) -> None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"Unsafe archive member path: {name!r}")


def _list_release_files(directory: Path) -> list[Path]:
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError(f"Release source directory is missing or symlinked: {directory}")
    paths: list[Path] = []
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Symlink in release tree: {path}")
        if path.is_file():
            paths.append(path)
    return sorted(paths, key=lambda path: path.relative_to(directory).as_posix())


def verify_v03_tree(directory: Path) -> list[Path]:
    paths = _list_release_files(directory)
    release_path = directory / "release.json"
    checksums_path = directory / "SHA256SUMS.txt"
    if not release_path.is_file() or not checksums_path.is_file():
        raise ValueError("The v0.3.0 source tree is missing release.json or SHA256SUMS.txt")
    release = load_json(release_path)
    if release.get("release_version") != "v0.3.0":
        raise ValueError("The previous release directory is not v0.3.0")
    if len(paths) != EXPECTED_V03_ARCHIVE_FILES:
        raise ValueError(f"Expected {EXPECTED_V03_ARCHIVE_FILES} v0.3.0 files, found {len(paths)}")
    if not (directory / "studies").is_dir():
        raise ValueError("v0.3.0 study tree is missing")
    return paths


def build_v03_archive(root: Path, release_dir: Path) -> dict[str, Any]:
    """Write a reproducible tar.gz and separate per-file/hash sidecars."""

    paths = verify_v03_tree(release_dir)
    archive = root / V03_ARCHIVE_REL
    archive.parent.mkdir(parents=True, exist_ok=True)
    temporary = archive.with_name(archive.name + ".tmp")
    with temporary.open("wb") as raw:
        import gzip as gzip_module

        with gzip_module.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w", format=tarfile.USTAR_FORMAT) as bundle:
                for path in paths:
                    relative = path.relative_to(release_dir).as_posix()
                    member_name = (V03_REL / relative).as_posix()
                    _safe_tar_name(member_name)
                    info = tarfile.TarInfo(member_name)
                    info.size = path.stat().st_size
                    info.mode = 0o644
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    info.mtime = 0
                    with path.open("rb") as source:
                        bundle.addfile(info, source)
    os.replace(temporary, archive)

    file_lines = []
    for path in paths:
        relative = path.relative_to(release_dir).as_posix()
        member_name = (V03_REL / relative).as_posix()
        file_lines.append(f"{sha256_file(path)}  {member_name}\n")
    atomic_write(root / V03_ARCHIVE_SUMS_REL, "".join(file_lines).encode("utf-8"))
    archive_hash = sha256_file(archive)
    atomic_write(root / V03_ARCHIVE_SHA_REL, f"{archive_hash}  {archive.name}\n".encode("ascii"))
    return {
        "path": V03_ARCHIVE_REL.as_posix(),
        "sha256": archive_hash,
        "file_manifest": V03_ARCHIVE_SUMS_REL.as_posix(),
        "archive_checksum": V03_ARCHIVE_SHA_REL.as_posix(),
        "file_count": len(paths),
        "uncompressed_bytes": sum(path.stat().st_size for path in paths),
    }


def verify_v03_archive(root: Path) -> dict[str, Any]:
    archive = root / V03_ARCHIVE_REL
    sums_path = root / V03_ARCHIVE_SUMS_REL
    sidecar = root / V03_ARCHIVE_SHA_REL
    if not archive.is_file() or not sums_path.is_file() or not sidecar.is_file():
        raise FileNotFoundError("v0.3.0 deterministic archive or its checksum files are missing")
    archive_hash = sha256_file(archive)
    expected_sidecar = f"{archive_hash}  {archive.name}\n"
    if sidecar.read_text(encoding="ascii") != expected_sidecar:
        raise ValueError("v0.3.0 archive checksum sidecar is incorrect")
    expected: dict[str, str] = {}
    for number, line in enumerate(sums_path.read_text(encoding="utf-8").splitlines(), 1):
        parts = line.split("  ", 1)
        if len(parts) != 2 or len(parts[0]) != 64 or parts[1] in expected:
            raise ValueError(f"Malformed or duplicate v0.3.0 archive manifest line {number}")
        expected[parts[1]] = parts[0]
    if len(expected) != EXPECTED_V03_ARCHIVE_FILES:
        raise ValueError(f"Expected {EXPECTED_V03_ARCHIVE_FILES} v0.3.0 archive hashes, found {len(expected)}")

    actual: dict[str, str] = {}
    uncompressed_bytes = 0
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            _safe_tar_name(member.name)
            if not member.isfile():
                raise ValueError(f"Unexpected non-file in v0.3.0 archive: {member.name}")
            if member.name in actual:
                raise ValueError(f"Duplicate v0.3.0 archive member: {member.name}")
            uncompressed_bytes += member.size
            content = bundle.extractfile(member)
            if content is None:
                raise ValueError(f"Cannot read v0.3.0 archive member: {member.name}")
            actual[member.name] = sha256_bytes(content.read())
            if member.mtime != 0 or member.mode != 0o644 or member.uid != 0 or member.gid != 0:
                raise ValueError(f"Non-deterministic tar metadata in v0.3.0 archive: {member.name}")
    if actual != expected:
        raise ValueError("v0.3.0 archive contents differ from its per-file checksum manifest")
    if archive.read_bytes()[4:8] != b"\x00\x00\x00\x00":
        raise ValueError("v0.3.0 archive gzip timestamp is not deterministic")
    return {
        "path": V03_ARCHIVE_REL.as_posix(),
        "sha256": archive_hash,
        "file_manifest": V03_ARCHIVE_SUMS_REL.as_posix(),
        "archive_checksum": V03_ARCHIVE_SHA_REL.as_posix(),
        "file_count": len(actual),
        "uncompressed_bytes": uncompressed_bytes,
    }


def _extract_v03_archive(root: Path, destination: Path) -> Path:
    verify_v03_archive(root)
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(root / V03_ARCHIVE_REL, "r:gz") as bundle:
        for member in bundle.getmembers():
            _safe_tar_name(member.name)
            if not member.isfile():
                raise ValueError(f"Unexpected non-file in v0.3.0 archive: {member.name}")
            target = destination.joinpath(*PurePosixPath(member.name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            content = bundle.extractfile(member)
            if content is None:
                raise ValueError(f"Cannot read v0.3.0 member {member.name}")
            target.write_bytes(content.read())
    extracted = destination.joinpath(*V03_REL.parts)
    verify_v03_tree(extracted)
    return extracted


def _source_assembly(source: dict[str, Any]) -> str:
    values = {
        str(value).strip()
        for section in ("registry_manifest", "registry_row")
        if (value := (source.get(section) or {}).get("reference_genome")) not in (None, "", "NA")
    }
    if len(values) != 1:
        raise ValueError(f"Source {source.get('source_id')!r} has missing/conflicting reference assembly")
    assembly = next(iter(values))
    if not assembly.startswith(("GCF_", "GCA_")):
        raise ValueError(f"Invalid assembly accession for {source.get('source_id')}: {assembly}")
    return assembly


def _archived_external_file(root: Path, member_name: str) -> bytes | None:
    archive = root / EXPECTED_EXTERNAL_ARCHIVE_REL
    if not archive.is_file():
        return None
    with tarfile.open(archive, "r:gz") as bundle:
        try:
            member = bundle.getmember(member_name)
        except KeyError:
            return None
        if not member.isfile():
            raise ValueError(f"External archive member is not a file: {member_name}")
        content = bundle.extractfile(member)
        if content is None:
            raise ValueError(f"Cannot read external archive member: {member_name}")
        return content.read()


def _find_external_intake(root: Path) -> tuple[str, bytes]:
    archive_candidates = (
        "data/external_source_draft/external_literature_source_intake_final.tsv",
        "data/registry/submissions/2026-08-09_fuchs-cascino-termite_source_intake.tsv",
    )
    for member_name in archive_candidates:
        payload = _archived_external_file(root, member_name)
        if payload is not None:
            return member_name, payload
    candidates = (
        root / "data/external_source_draft/external_literature_source_intake_final.tsv",
        root / "data/registry/submissions/2026-08-09_fuchs-cascino-termite_source_intake.tsv",
    )
    for path in candidates:
        if path.is_file():
            return path.relative_to(root).as_posix(), path.read_bytes()
    raise FileNotFoundError("No external literature source intake TSV is available")


def _external_intake(root: Path) -> tuple[str, bytes, list[str], list[dict[str, str]]]:
    original_path, payload = _find_external_intake(root)
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig"), newline=""), delimiter="\t")
    if not reader.fieldnames:
        raise ValueError(f"External intake TSV has no header: {original_path}")
    header = list(reader.fieldnames)
    rows = []
    for line_number, row in enumerate(reader, 2):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"Invalid intake row width at {original_path}:{line_number}")
        rows.append({str(key): str(value) for key, value in row.items()})
    if "source_id" not in header or "processing_status" not in header:
        raise ValueError("External intake TSV is missing source_id or processing_status")
    if len({row["source_id"] for row in rows}) != len(rows):
        raise ValueError("External intake TSV has duplicate source IDs")
    return original_path, payload, header, rows


def _cascino_tsv_source(root: Path, source_id: str) -> tuple[str, bytes]:
    member_name = f"data/records/{source_id}/{source_id}_endpoints.tsv"
    archived = _archived_external_file(root, member_name)
    if archived is not None:
        return member_name, archived
    expected = root / "data/records" / source_id / f"{source_id}_endpoints.tsv"
    if expected.is_file():
        return expected.relative_to(root).as_posix(), expected.read_bytes()
    raise FileNotFoundError(f"Cannot locate standardized Cascino endpoint TSV for {source_id}")


def _build_cascino_source(
    source_id: str,
    intake: dict[str, str],
    rows: list[dict[str, str]],
) -> dict[str, Any]:
    expected_count = EXPECTED_CASCINO_COUNTS[source_id]
    if len(rows) != expected_count:
        raise ValueError(f"{source_id}: expected {expected_count} author-called endpoints, found {len(rows)}")
    ids: set[str] = set()
    for row_number, row in enumerate(rows, 2):
        if set(row) != set(ENDPOINT_COLUMNS):
            raise ValueError(f"{source_id}: endpoint TSV columns differ from the canonical 24-column schema")
        if row["source_id"] != source_id or row["pmid"] != EXPECTED_CASCINO_PMID:
            raise ValueError(f"{source_id}:{row_number}: source ID or PMID differs")
        if row["reference_assembly"] != EXPECTED_CASCINO_ASSEMBLY or row["reference_name"] != EXPECTED_CASCINO_REFERENCE:
            raise ValueError(f"{source_id}:{row_number}: reference assembly/sequence differs")
        if row["evidence_class"] != EXPECTED_CASCINO_EVIDENCE:
            raise ValueError(f"{source_id}:{row_number}: non-author-called candidate entered v0.4.0")
        if row["author_category"] != "defined end":
            raise ValueError(f"{source_id}:{row_number}: non-defined-end candidate entered v0.4.0")
        if row["end_id"] in ids:
            raise ValueError(f"{source_id}:{row_number}: duplicate end_id {row['end_id']}")
        ids.add(row["end_id"])
        position = int(row["biological_coordinate_1based"])
        if position < 1 or row["bed_start_0based"] != str(position - 1) or row["bed_end_0based"] != str(position):
            raise ValueError(f"{source_id}:{row_number}: inconsistent GFF3/BED coordinates")
        if row["strand"] not in {"+", "-"}:
            raise ValueError(f"{source_id}:{row_number}: invalid strand")

    constants = {}
    for column in ENDPOINT_COLUMNS:
        values = {row[column] for row in rows}
        if column in GFF3_ROW_ATTRIBUTE_COLUMNS or column in {
            "end_id", "source_id", "reference_name", "biological_coordinate_1based", "strand",
            "bed_start_0based", "bed_end_0based",
        }:
            continue
        if len(values) != 1:
            raise ValueError(f"{source_id}: endpoint default {column!r} is not constant")
        constants[column] = next(iter(values))

    assembly = intake["reference_assembly"]
    sample_text = intake.get("sample_id_or_condition", "")
    sample_id = sample_text.split(" (", 1)[0]
    publication_status = {
        "source_id": source_id,
        "release_status": "published_standardized",
        "record_count": str(expected_count),
        "evidence_class": EXPECTED_CASCINO_EVIDENCE,
        "has_jbrowse": False,
        "source_annotations_status": "not_republished_as_a_separate_table",
        "redistribution_status": "verified_redistributable",
        "record_root": f"data/records/{source_id}",
    }
    license_status = {
        "source_id": source_id,
        "pmid": EXPECTED_CASCINO_PMID,
        "article_license": "CC BY 4.0",
        "redistribution_status": "verified_redistributable",
        "license_source": intake.get("pmc_or_fulltext_url", ""),
        "note": intake.get("license_or_reuse_note", ""),
    }
    registry_row = {
        "source_id": source_id,
        "published_year": intake.get("paper_publication_year", ""),
        "species": intake.get("species", ""),
        "reference_genome": assembly,
        "pmid": EXPECTED_CASCINO_PMID,
        "paper_title": intake.get("paper_title", ""),
        "doi": intake.get("doi", ""),
        "pmc": "",
        "raw_data_accessions": intake.get("raw_data_accessions", ""),
        "assay_family": intake.get("assay", ""),
        "processing_status": "published_standardized",
        "coordinate_status": "verified_1based_single_base",
        "blocker_or_note": intake.get("blocker_or_note", ""),
    }
    registry_manifest = {
        "schema_version": "1.0",
        "source_id": source_id,
        "dataset_id": intake.get("dataset_id", ""),
        "published_year": intake.get("paper_publication_year", ""),
        "species": intake.get("species", ""),
        "strain": intake.get("strain", ""),
        "taxonomy_id": intake.get("taxonomy_id", ""),
        "reference_genome": assembly,
        "reference_sequence_accession_or_contigs": intake.get("reference_sequence_accession_or_contigs", ""),
        "pmid": EXPECTED_CASCINO_PMID,
        "doi": intake.get("doi", ""),
        "doi_url": f"https://doi.org/{intake.get('doi', '')}",
        "paper_title": intake.get("paper_title", ""),
        "full_text_url": intake.get("pmc_or_fulltext_url", ""),
        "raw_data_accessions": intake.get("raw_data_accessions", ""),
        "raw_data_url": intake.get("raw_or_supplement_url", ""),
        "assay_family": intake.get("assay", ""),
        "evidence_policy": EXPECTED_CASCINO_EVIDENCE,
        "coordinate_status": "verified_1based_single_base",
        "processing_status": "published_standardized",
        "used_for_batter_augmentation": "no",
        "repository_release": {"record_count": expected_count, "license": "CC BY 4.0"},
    }
    return {
        "source_id": source_id,
        "registry_manifest": registry_manifest,
        "registry_row": registry_row,
        "publication_status": publication_status,
        "license_status": license_status,
        "asset_redistribution": [],
        "release_facts": {
            "known_limitations": "Only author-defined 'defined end' rows are included. The 196 diffuse-peak/undetermined rows remain in the internal review archive.",
            "has_jbrowse": False,
        },
        "table_defaults": {"endpoints": constants},
        "annotation_field_map": {},
        "annotation_defaults": {},
        "raw_intake_record": copy.deepcopy(intake),
        "sample_id": sample_id,
    }


def _external_archive_inventory(root: Path) -> dict[str, Any]:
    archive_path = root / EXPECTED_EXTERNAL_ARCHIVE_REL
    if archive_path.is_file():
        sidecar = archive_path.with_name(archive_path.name + ".sha256")
        if not sidecar.is_file() or sidecar.read_text(encoding="ascii") != f"{sha256_file(archive_path)}  {archive_path.name}\n":
            raise ValueError("External intake archive checksum sidecar is missing or incorrect")
        member_rows = []
        with tarfile.open(archive_path, "r:gz") as bundle:
            for member in bundle.getmembers():
                _safe_tar_name(member.name)
                if not member.isfile():
                    raise ValueError(f"External intake archive contains non-file member {member.name}")
                payload = bundle.extractfile(member)
                if payload is None:
                    raise ValueError(f"Cannot read external intake archive member {member.name}")
                data = payload.read()
                member_rows.append({
                    "member": member.name,
                    "byte_size": len(data),
                    "sha256": sha256_bytes(data),
                })
        return {
            "path": EXPECTED_EXTERNAL_ARCHIVE_REL.as_posix(),
            "sha256": sha256_file(archive_path),
            "status": "archived",
            "members": sorted(member_rows, key=lambda row: row["member"]),
        }

    prefixes = (
        root / "data/external_source_draft",
        root / "data/records",
        root / "data/audit/excluded_assets",
        root / "data/registry/submissions",
        root / "docs/sources/integration",
    )
    rows = []
    for directory in prefixes:
        if not directory.exists() or directory.is_symlink():
            continue
        for path in sorted(p for p in directory.rglob("*") if p.is_file() and not p.is_symlink()):
            relative = path.relative_to(root).as_posix()
            if not (relative.startswith("data/external_source_draft/")
                    or relative.startswith("data/records/BTED_EXT_")
                    or relative.startswith("data/audit/excluded_assets/BTED_EXT_")
                    or relative.startswith("data/registry/submissions/")
                    or relative.startswith("docs/sources/integration/")):
                continue
            rows.append({"member": relative, "byte_size": path.stat().st_size, "sha256": sha256_file(path)})
    return {
        "path": EXPECTED_EXTERNAL_ARCHIVE_REL.as_posix(),
        "status": "awaiting_archive",
        "members": sorted(rows, key=lambda row: row["member"]),
    }


def _audit_documents(root: Path) -> list[dict[str, Any]]:
    candidates = (
        "data/external_source_draft/cascino_exclusion_report.txt",
        "data/external_source_draft/cascino_reclassification_changelog.md",
        "data/external_source_draft/termite_endpoints_summary.txt",
        "data/external_source_draft/Wrapup.md",
    )
    documents = []
    for relative in candidates:
        path = root / relative
        payload = _archived_external_file(root, relative)
        if payload is None and path.is_file():
            payload = path.read_bytes()
        if payload is not None:
            documents.append({
                "original_path": relative,
                "sha256": sha256_bytes(payload),
                "byte_size": len(payload),
                "utf8_text": payload.decode("utf-8-sig"),
            })
    return documents


def _write_internal_provenance(
    root: Path,
    sources: dict[str, dict[str, Any]],
    intake_path: str,
    intake_bytes: bytes,
    intake_header: list[str],
    intake_rows: list[dict[str, str]],
    cascino_inputs: dict[str, tuple[str, bytes, int, int]],
    old_release: dict[str, Any],
    v03_archive_info: dict[str, Any],
) -> dict[str, Any]:
    cascino_ids = set(EXPECTED_CASCINO_COUNTS)
    published_ids = set(sources)
    review_rows = [row for row in intake_rows if row["source_id"] not in cascino_ids]
    candidate_files = []
    for source_id, (original_path, raw, raw_count, included_count) in sorted(cascino_inputs.items()):
        candidate_files.append({
            "source_id": source_id,
            "original_path": original_path,
            "byte_size": len(raw),
            "sha256": sha256_bytes(raw),
            "raw_row_count": raw_count,
            "included_row_count": included_count,
            "excluded_row_count": raw_count - included_count,
        })
    internal = {
        "schema_version": "1.0",
        "release_version": "v0.4.0",
        "description": "Complete source-level provenance and review references used to build v0.4.0. Not a public user entry point.",
        "counts": {
            "source_count": len(sources),
            "audit_only_source_ids": [source_id for source_id, source in sorted(sources.items())
                                      if (source.get("publication_status") or {}).get("release_status") == "audit_only"],
            "published_endpoint_source_count": len(sources) - EXPECTED_AUDIT_ONLY_SOURCE_COUNT,
            "endpoint_default_schema": list(ENDPOINT_COLUMNS),
        },
        "sources": [sources[source_id] for source_id in sorted(sources)],
        "external_source_intake": {
            "original_path": intake_path,
            "byte_size": len(intake_bytes),
            "sha256": sha256_bytes(intake_bytes),
            "columns": intake_header,
            "rows": intake_rows,
            "review_only_rows": review_rows,
        },
        "cascino_decision": {
            "pmid": EXPECTED_CASCINO_PMID,
            "assembly": EXPECTED_CASCINO_ASSEMBLY,
            "included_source_counts": EXPECTED_CASCINO_COUNTS,
            "included_total": sum(EXPECTED_CASCINO_COUNTS.values()),
            "included_evidence_class": EXPECTED_CASCINO_EVIDENCE,
            "excluded_secondary_rows": 196,
            "excluded_categories": ["diffuse end (diffuse peak)", "unclear"],
            "excluded_author_categories": ["diffuse end (diffuse peak)", "undetermined"],
            "excluded_evidence_class": "called_endpoint",
            "excluded_sources_are_not_public": True,
            "raw_source_tables": candidate_files,
            "included_selector": {
                "evidence_class": EXPECTED_CASCINO_EVIDENCE,
                "author_category": "defined end",
            },
            "independent_original_table_audit": {
                "status": "pass",
                "supplementary_zip_url": "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC13289151/supplementaryFiles",
                "supplementary_zip_sha256": "141c5eaf5d7e1923ec89d8ebf2db5d70255ded2b1e1a11f560375ee759b11071",
                "original_workbook": "msystems.01581-25-s0003.xlsx",
                "original_workbook_sha256": "2fd20543f7b68c791b194628f5801133a6ff185e397bc7909952a76315ee5be7",
                "source_sheet_row_comparison": {
                    "BTED_EXT_2026_102": {"sheet": "Syn_WT", "rows_matched": 388},
                    "BTED_EXT_2026_103": {"sheet": "Syn_∆mfd_rep1", "rows_matched": 331},
                    "BTED_EXT_2026_104": {"sheet": "Syn_∆mfd_rep2", "rows_matched": 342},
                },
                "fields_checked": [
                    "original row reference",
                    "author category",
                    "strand",
                    "1-based peak coordinate",
                    "numeric signal/readthrough score",
                ],
                "missing_rows": 0,
                "extra_rows": 0,
                "license_verification": {
                    "status": "pass",
                    "license": "CC BY 4.0",
                    "source": "Europe PMC full-text XML for PMC13289151",
                    "source_url": "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC13289151/fullTextXML",
                },
            },
            "audit_documents": _audit_documents(root),
        },
        "external_review_archive": _external_archive_inventory(root),
        "previous_releases": {
            "v0.2.0": old_release.get("legacy_archive", {}),
            "v0.3.0": v03_archive_info,
        },
    }
    destination = root / INTERNAL_REL
    destination.mkdir(parents=True, exist_ok=True)
    payload = json_bytes(internal)
    manifest_path = destination / "source_provenance.json"
    atomic_write(manifest_path, payload)
    sidecar_line = f"{sha256_bytes(payload)}  source_provenance.json\n"
    atomic_write(destination / "SHA256SUMS.txt", sidecar_line.encode("ascii"))
    return internal


def _read_cascino_rows(root: Path, source_id: str) -> tuple[str, bytes, list[dict[str, str]], list[dict[str, str]]]:
    original_path, payload = _cascino_tsv_source(root, source_id)
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig"), newline=""), delimiter="\t")
    if not reader.fieldnames:
        raise ValueError(f"Cascino endpoint TSV has no header: {original_path}")
    header = list(reader.fieldnames)
    raw_rows = []
    for line_number, row in enumerate(reader, 2):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"Invalid Cascino row width at {original_path}:{line_number}")
        raw_rows.append({str(key): str(value) for key, value in row.items()})
    if tuple(header) != tuple(ENDPOINT_COLUMNS):
        raise ValueError(f"{original_path}: column order is not the canonical endpoint schema")
    if len(raw_rows) != EXPECTED_CASCINO_INPUT_COUNTS[source_id]:
        raise ValueError(
            f"{source_id}: expected {EXPECTED_CASCINO_INPUT_COUNTS[source_id]} rows in the preserved candidate TSV, "
            f"found {len(raw_rows)}"
        )
    included_rows = [
        row for row in raw_rows
        if row["evidence_class"] == EXPECTED_CASCINO_EVIDENCE and row["author_category"] == "defined end"
    ]
    excluded_rows = [
        row for row in raw_rows
        if not (row["evidence_class"] == EXPECTED_CASCINO_EVIDENCE and row["author_category"] == "defined end")
    ]
    if len(included_rows) != EXPECTED_CASCINO_COUNTS[source_id]:
        raise ValueError(f"{source_id}: selected primary endpoint count differs from the release contract")
    if len(excluded_rows) != EXPECTED_CASCINO_INPUT_COUNTS[source_id] - EXPECTED_CASCINO_COUNTS[source_id]:
        raise ValueError(f"{source_id}: excluded candidate count differs from the audit record")
    if any(
        row["evidence_class"] != "called_endpoint"
        or row["author_category"] not in {"diffuse end (diffuse peak)", "undetermined"}
        for row in excluded_rows
    ):
        raise ValueError(f"{source_id}: candidate rows outside the approved secondary categories were found")
    return original_path, payload, raw_rows, included_rows


def _metadata_row(source: dict[str, Any], assembly: str, pmid: str, study_payloads: dict[tuple[str, str], dict[str, bytes]]) -> dict[str, str]:
    row = study_metadata_tsv_row(source)
    row["assembly"] = assembly
    payload = study_payloads.get((assembly, pmid), {})
    for column, key in (
        ("study_gff3", "endpoints.gff3.gz"),
        ("gene_associations", "gene_associations.tsv.gz"),
        ("condition_observations", "condition_observations.tsv.gz"),
    ):
        row[column] = f"studies/PMID_{pmid}/{key}" if key in payload else ""
    return {column: str(row.get(column, "")) for column in GENOME_METADATA_COLUMNS}


def _write_payload_files(stage: Path, payloads: dict[str, bytes]) -> list[dict[str, Any]]:
    entries = []
    for relative in sorted(payloads):
        target = stage / Path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payloads[relative])
        entries.append({"path": relative, "byte_size": len(payloads[relative]), "sha256": sha256_bytes(payloads[relative])})
    return entries


def build_release(root: Path = ROOT, *, retire_v03: bool = False) -> dict[str, Any]:
    root = root.resolve()
    v03_path = root / V03_REL
    if v03_path.is_dir():
        archive_info = build_v03_archive(root, v03_path)
        v03_root = v03_path
        temp_context = None
    else:
        archive_info = verify_v03_archive(root)
        temp_root = root / "tmp"
        temp_root.mkdir(exist_ok=True)
        temp_context = temp_root / f"bted-v03-verify-{uuid.uuid4().hex}"
        temp_context.mkdir()
        v03_root = _extract_v03_archive(root, temp_context / "archive")

    try:
        old_release = load_json(v03_root / "release.json")
        old_counts = old_release.get("counts", {})
        if old_counts.get("endpoint_count") != EXPECTED_OLD_ENDPOINTS:
            raise ValueError("v0.3.0 baseline endpoint count differs from 28,399")
        if old_counts.get("gene_association_count") != EXPECTED_GENE_ASSOCIATIONS:
            raise ValueError("v0.3.0 baseline gene association count differs from 805")
        if old_counts.get("unlinked_gene_association_count") != EXPECTED_UNLINKED_GENE_ASSOCIATIONS:
            raise ValueError("v0.3.0 baseline unlinked gene count differs from 345")
        if old_counts.get("condition_observation_count") != EXPECTED_CONDITION_OBSERVATIONS:
            raise ValueError("v0.3.0 baseline condition observation count differs from 2,277")

        sources: dict[str, dict[str, Any]] = {}
        for _study_dir, metadata in iter_study_metadata(v03_root):
            for source in metadata["sources"]:
                source_id = source["source_id"]
                if source_id in sources:
                    raise ValueError(f"Duplicate v0.3.0 source ID: {source_id}")
                sources[source_id] = copy.deepcopy(source)

        intake_path, intake_bytes, intake_header, intake_rows = _external_intake(root)
        intake_by_id = {row["source_id"]: row for row in intake_rows}
        cascino_sources: dict[str, dict[str, Any]] = {}
        cascino_inputs: dict[str, tuple[str, bytes, int, int]] = {}
        cascino_rows: dict[str, list[dict[str, str]]] = {}
        for source_id, count in EXPECTED_CASCINO_COUNTS.items():
            if source_id not in intake_by_id:
                raise ValueError(f"Cascino source {source_id} is missing from the source intake TSV")
            original_path, raw_bytes, raw_rows, rows = _read_cascino_rows(root, source_id)
            cascino_inputs[source_id] = (original_path, raw_bytes, len(raw_rows), len(rows))
            cascino_rows[source_id] = rows
            cascino_sources[source_id] = _build_cascino_source(source_id, intake_by_id[source_id], rows)
            if len(rows) != count:
                raise ValueError(f"{source_id}: source intake and endpoint TSV counts differ")
        if set(sources).intersection(cascino_sources):
            raise ValueError("Cascino source IDs overlap the v0.3.0 source IDs")
        sources.update(cascino_sources)
        if len(sources) != EXPECTED_SOURCE_COUNT:
            raise ValueError(f"Expected {EXPECTED_SOURCE_COUNT} released source rows, found {len(sources)}")

        # Preserve every prior GFF3 feature line byte-for-byte after decompression.
        study_features: dict[tuple[str, str], list[str]] = defaultdict(list)
        source_key: dict[str, tuple[str, str]] = {}
        source_record_counts = Counter()
        for source_id, source in sources.items():
            source_key[source_id] = (_source_assembly(source), source_pmid(source))
        for row, original_line in iter_endpoint_feature_lines(v03_root):
            assembly, pmid = source_key[row["source_id"]]
            study_features[(assembly, pmid)].append(original_line)
            source_record_counts[row["source_id"]] += 1
        if sum(source_record_counts.values()) != EXPECTED_OLD_ENDPOINTS:
            raise ValueError("The v0.3.0 GFF3 rows do not reconstruct exactly 28,399 endpoints")

        for source_id, rows in cascino_rows.items():
            source = sources[source_id]
            assembly, pmid = source_key[source_id]
            if assembly != EXPECTED_CASCINO_ASSEMBLY or pmid != EXPECTED_CASCINO_PMID:
                raise ValueError(f"{source_id}: intake assembly or PMID differs from the release contract")
            for row in rows:
                study_features[(assembly, pmid)].append(format_endpoint_gff3(row))
                source_record_counts[source_id] += 1
        if sum(source_record_counts.values()) != EXPECTED_ENDPOINTS:
            raise ValueError(f"Expected {EXPECTED_ENDPOINTS} total endpoints, found {sum(source_record_counts.values())}")

        related_rows: dict[str, dict[tuple[str, str], list[dict[str, str]]]] = {
            name: defaultdict(list) for name in RELATED_TABLE_FILES
        }
        for table in RELATED_TABLE_FILES:
            for row in iter_related_rows(v03_root, table):
                assembly, pmid = source_key[row["source_id"]]
                related_rows[table][(assembly, pmid)].append(row)

        if sum(map(len, related_rows["gene_associations"].values())) != EXPECTED_GENE_ASSOCIATIONS:
            raise ValueError("Gene association row count changed during migration")
        unlinked_count = sum(
            row["link_status"] == "unlinked_author_annotation"
            for rows in related_rows["gene_associations"].values()
            for row in rows
        )
        linked_count = sum(
            row["link_status"] == "linked"
            for rows in related_rows["gene_associations"].values()
            for row in rows
        )
        if (linked_count, unlinked_count) != (EXPECTED_LINKED_GENE_ASSOCIATIONS, EXPECTED_UNLINKED_GENE_ASSOCIATIONS):
            raise ValueError(f"Gene association split changed: linked={linked_count}, unlinked={unlinked_count}")
        if sum(map(len, related_rows["condition_observations"].values())) != EXPECTED_CONDITION_OBSERVATIONS:
            raise ValueError("Condition observation row count changed during migration")

        assemblies = sorted({_source_assembly(source) for source in sources.values()})
        if len(assemblies) != 21:
            raise ValueError(f"Expected 21 genome assemblies including Cascino, found {len(assemblies)}")
        all_study_keys = set(source_key.values())
        all_study_keys.update(study_features)
        for table_rows in related_rows.values():
            all_study_keys.update(table_rows)

        payloads: dict[str, bytes] = {}
        study_payloads: dict[tuple[str, str], dict[str, bytes]] = defaultdict(dict)
        for (assembly, pmid), lines in sorted(study_features.items()):
            relative = f"genomes/{assembly}/studies/PMID_{pmid}/endpoints.gff3.gz"
            content = ("##gff-version 3\n" + "\n".join(lines) + "\n").encode("utf-8")
            packed = deterministic_gzip(content)
            payloads[relative] = packed
            study_payloads[(assembly, pmid)]["endpoints.gff3.gz"] = packed
        for table, grouped in related_rows.items():
            for (assembly, pmid), rows in sorted(grouped.items()):
                if not rows:
                    continue
                filename = RELATED_TABLE_FILES[table]
                relative = f"genomes/{assembly}/studies/PMID_{pmid}/{filename}"
                packed = deterministic_gzip(tsv_bytes(table_columns(table), rows))
                payloads[relative] = packed
                study_payloads[(assembly, pmid)][filename] = packed

        sources_by_assembly: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for source in sources.values():
            sources_by_assembly[_source_assembly(source)].append(source)
        for assembly in assemblies:
            metadata_rows = []
            for source in sorted(sources_by_assembly[assembly], key=lambda item: (source_pmid(item), item["source_id"])):
                metadata_rows.append(_metadata_row(source, assembly, source_pmid(source), study_payloads))
            relative = f"genomes/{assembly}/metadata.tsv"
            payloads[relative] = tsv_bytes(GENOME_METADATA_COLUMNS, metadata_rows)

        stage_parent = root / "data/public"
        stage_parent.mkdir(parents=True, exist_ok=True)
        stage = stage_parent / ".v0.4.0.build"
        if stage.exists():
            raise FileExistsError(f"Refusing to reuse release staging directory: {stage}")
        stage.mkdir()
        file_entries = _write_payload_files(stage, payloads)
        checksum_lines = [f"{entry['sha256']}  {entry['path']}\n" for entry in file_entries]
        sums_payload = "".join(checksum_lines).encode("utf-8")
        atomic_write(stage / "SHA256SUMS.txt", sums_payload)

        genome_documents = []
        for assembly in assemblies:
            assembly_sources = sorted(sources_by_assembly[assembly], key=lambda item: (source_pmid(item), item["source_id"]))
            study_docs = []
            for key in sorted(study_key for study_key in all_study_keys if study_key[0] == assembly):
                _, pmid = key
                scoped_sources = sorted(
                    [source for source in assembly_sources if source_pmid(source) == pmid],
                    key=lambda item: item["source_id"],
                )
                study_rows = study_features.get(key, [])
                table_gene_count = len(related_rows["gene_associations"].get(key, []))
                table_condition_count = len(related_rows["condition_observations"].get(key, []))
                study_docs.append({
                    "pmid": pmid,
                    "path": f"studies/PMID_{pmid}",
                    "source_ids": [source["source_id"] for source in scoped_sources],
                    "source_count": len(scoped_sources),
                    "endpoint_count": len(study_rows),
                    "gene_association_count": table_gene_count,
                    "condition_observation_count": table_condition_count,
                    "status": "audit_only" if not study_rows and scoped_sources and all(
                        (source.get("publication_status") or {}).get("release_status") == "audit_only"
                        for source in scoped_sources
                    ) else "published_standardized",
                })
            genome_documents.append({
                "assembly": assembly,
                "metadata_path": f"genomes/{assembly}/metadata.tsv",
                "source_count": len(assembly_sources),
                "study_count": len(study_docs),
                "endpoint_count": sum(source_record_counts[source["source_id"]] for source in assembly_sources),
                "studies": study_docs,
            })

        file_count_by_source = {source_id: source_record_counts[source_id] for source_id in sources}
        published_ids = [source_id for source_id, source in sources.items()
                         if (source.get("publication_status") or {}).get("release_status") != "audit_only"]
        if sum(file_count_by_source.values()) != EXPECTED_ENDPOINTS:
            raise ValueError("Per-source endpoint counts do not sum to the expected release count")
        release_doc = {
            "schema_version": "1.0",
            "release_version": "v0.4.0",
            "summary": "Genome-organized, source-attributed experimental transcription endpoint release.",
            "counts": {
                "source_count": len(sources),
                "published_source_count": len(published_ids),
                "audit_only_source_count": len(sources) - len(published_ids),
                "study_count": len({pmid for _, pmid in all_study_keys}),
                "genome_study_count": len(all_study_keys),
                "genome_count": len(assemblies),
                "endpoint_count": EXPECTED_ENDPOINTS,
                "old_endpoint_count": EXPECTED_OLD_ENDPOINTS,
                "cascino_endpoint_count": sum(EXPECTED_CASCINO_COUNTS.values()),
                "annotation_count": old_counts.get("annotation_count", 0),
                "gene_association_count": EXPECTED_GENE_ASSOCIATIONS,
                "linked_gene_association_count": linked_count,
                "unlinked_gene_association_count": unlinked_count,
                "condition_observation_count": EXPECTED_CONDITION_OBSERVATIONS,
            },
            "legacy_archive": {
                "v0.2.0": old_release.get("legacy_archive", {}),
                "v0.3.0": archive_info,
            },
            "genomes": genome_documents,
            "files": file_entries,
        }
        atomic_write(stage / "release.json", json_bytes(release_doc))

        # Commit the staged release to its sole canonical public path.
        output = root / V04_REL
        if output.exists():
            if output.is_symlink() or not output.is_dir():
                raise ValueError(f"Unexpected generated release path: {output}")
            marker = output / "release.json"
            if not marker.is_file() or load_json(marker).get("release_version") != "v0.4.0":
                raise ValueError(f"Refusing to replace a non-v0.4.0 directory: {output}")
            shutil.rmtree(output)
        os.replace(stage, output)

        _write_internal_provenance(
            root,
            sources,
            intake_path,
            intake_bytes,
            intake_header,
            intake_rows,
            cascino_inputs,
            old_release,
            archive_info,
        )

        if retire_v03:
            _retire_verified_v03_tree(root, output)
        return release_doc
    finally:
        if temp_context is not None:
            shutil.rmtree(temp_context)


def _retire_verified_v03_tree(root: Path, release_dir: Path) -> None:
    from validate_bted_v0_4 import validate_release

    validate_release(root, release_dir=release_dir)
    old = root / V03_REL
    expected = (root / "data/public/v0.3.0").resolve()
    if old.is_symlink() or old.resolve() != expected or not old.is_dir():
        raise ValueError(f"Refusing to remove unexpected v0.3.0 path: {old}")
    verify_v03_archive(root)
    shutil.rmtree(old)


def refresh_provenance(root: Path = ROOT) -> None:
    """Refresh archived external-review references after their deterministic archive is created."""

    release_dir = root / V04_REL
    if not release_dir.is_dir():
        raise FileNotFoundError(f"v0.4.0 release is missing: {release_dir}")
    release_doc = load_json(release_dir / "release.json")
    if release_doc.get("release_version") != "v0.4.0":
        raise ValueError("The public release path does not contain v0.4.0")
    source_manifest = root / INTERNAL_REL / "source_provenance.json"
    old_internal = load_json(source_manifest)
    archive_info = _external_archive_inventory(root)
    if archive_info.get("status") != "archived":
        raise FileNotFoundError(f"External review archive is not ready: {EXPECTED_EXTERNAL_ARCHIVE_REL}")
    old_internal["external_review_archive"] = archive_info
    payload = json_bytes(old_internal)
    atomic_write(source_manifest, payload)
    atomic_write(source_manifest.parent / "SHA256SUMS.txt",
                 f"{sha256_bytes(payload)}  source_provenance.json\n".encode("ascii"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository root (default: this checkout)")
    parser.add_argument("--retire-v0-3", action="store_true", help="Remove data/public/v0.3.0 after archive and release validation")
    parser.add_argument("--refresh-provenance-only", action="store_true", help="Refresh internal archive member hashes after external review files are archived")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        if args.refresh_provenance_only:
            refresh_provenance(root)
            print("PASS refreshed v0.4.0 internal provenance archive references")
            return 0
        release = build_release(root, retire_v03=args.retire_v0_3)
        print(json.dumps({"release_version": "v0.4.0", "counts": release["counts"]}, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:  # CLI error boundary
        print(f"FAIL {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
