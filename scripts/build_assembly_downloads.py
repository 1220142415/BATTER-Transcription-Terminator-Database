#!/usr/bin/env python3
"""Build source and assembly GFF3 files for site and JBrowse compatibility."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

from v03_tables import iter_endpoint_feature_lines


REPO_ROOT = Path(__file__).resolve().parent.parent
RELEASE_ROOT = REPO_ROOT / "data/public/v0.3.0"
STUDIES_PATH = RELEASE_ROOT / "studies"
RELEASE_VERSION = "v0.3.0"
GFF3_HEADER = "##gff-version 3\n"
SOURCE_METADATA_CONTEXT = (
    "This object keeps the source decisions needed to read the current data. "
    "The complete v0.2.0 source manifest and field template are in the repository archive. "
    "Historical file names here are not v0.3.0 download paths."
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_metadata(source_entry: dict[str, Any]) -> dict[str, Any]:
    """Flatten only fields needed in a user-facing assembly metadata document."""
    source_id = str(source_entry["source_id"])
    release = source_entry.get("release_facts") or {}
    registry_manifest = source_entry.get("registry_manifest") or {}
    registry_row = source_entry.get("registry_row") or {}
    publication = source_entry.get("publication_status") or {}
    license_status = source_entry.get("license_status") or {}

    def first(*values: Any, default: Any = "") -> Any:
        return next((value for value in values if value not in (None, "", "NA")), default)

    def as_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"true", "1", "yes"}

    status = str(first(
        release.get("release_status"),
        registry_manifest.get("release_status"),
        publication.get("release_status"),
        publication.get("status"),
        default="audit_only",
    ))
    raw_accessions = first(
        release.get("raw_data_accessions"),
        registry_manifest.get("raw_data_accessions"),
        registry_row.get("raw_data_accessions"),
        default="",
    )
    if isinstance(raw_accessions, str):
        raw_accessions = [item.strip() for item in raw_accessions.replace(",", ";").split(";") if item.strip()]
    elif not isinstance(raw_accessions, list):
        raw_accessions = []

    merged = {
        "source_id": source_id,
        "dataset_id": first(release.get("dataset_id"), registry_manifest.get("dataset_id"), default="NA"),
        "species": first(release.get("species"), registry_manifest.get("species"), registry_row.get("species"), default=""),
        "year": first(release.get("published_year"), registry_manifest.get("published_year"), registry_row.get("published_year"), default=""),
        "assembly": first(release.get("reference_genome"), registry_manifest.get("reference_genome"), registry_row.get("reference_genome"), default=""),
        "pmid": first(release.get("pmid"), registry_manifest.get("pmid"), registry_row.get("pmid"), default=""),
        "title": first(release.get("paper_title"), registry_manifest.get("paper_title"), registry_row.get("paper_title"), default=""),
        "doi": first(release.get("doi"), registry_manifest.get("doi"), registry_row.get("doi"), default=""),
        "pmc": first(release.get("pmc"), registry_manifest.get("pmc"), registry_row.get("pmc"), default=""),
        "assay": first(release.get("assay_family"), registry_manifest.get("assay_family"), registry_row.get("assay_family"), default=""),
        "raw_data_accessions": raw_accessions,
        "raw_data_url": first(release.get("raw_data_url"), registry_manifest.get("raw_data_url"), default=""),
        "pubmed_url": first(release.get("pubmed_url"), registry_manifest.get("pubmed_url"), default=""),
        "doi_url": first(release.get("doi_url"), registry_manifest.get("doi_url"), default=""),
        "pmc_url": first(release.get("pmc_url"), registry_manifest.get("pmc_url"), default=""),
        "known_limitations": first(release.get("known_limitations"), registry_manifest.get("known_limitations"), registry_row.get("blocker_or_note"), default=""),
        "evidence_class": first(release.get("evidence_class"), registry_manifest.get("evidence_class"), publication.get("evidence_class"), default="audit_only" if status == "audit_only" else ""),
        "release_status": status,
        "record_count": int(first(release.get("record_count"), publication.get("record_count"), default=0)),
        "has_jbrowse": as_bool(first(release.get("has_jbrowse"), registry_manifest.get("has_jbrowse"), publication.get("has_jbrowse"), default=False)),
        "article_license": first(license_status.get("article_license"), registry_manifest.get("redistribution", {}).get("article_license"), default=""),
        "redistribution_status": first(license_status.get("redistribution_status"), registry_manifest.get("redistribution", {}).get("redistribution_status"), default=""),
        "endpoint_field_defaults": (source_entry.get("table_defaults") or {}).get("endpoints", {}),
        "source_metadata": source_entry,
    }
    if status == "audit_only":
        merged["evidence_class"] = "audit_only"
    if not merged["assembly"]:
        raise ValueError(f"{source_id}: missing reference assembly accession in source metadata")
    return merged


def load_study_metadata(studies_path: Path = STUDIES_PATH) -> list[dict[str, Any]]:
    """Read the canonical per-PMID packages and their original source objects."""
    if not studies_path.is_dir():
        raise ValueError(f"Study package directory does not exist: {studies_path}")
    study_metadata: list[dict[str, Any]] = []
    for metadata_path in sorted(studies_path.glob("PMID_*/metadata.json")):
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        if payload.get("release_version") != RELEASE_VERSION:
            raise ValueError(f"{metadata_path}: expected release_version {RELEASE_VERSION}")
        pmid = str(payload.get("pmid", "")).strip()
        if not pmid.isdigit() or metadata_path.parent.name != f"PMID_{pmid}":
            raise ValueError(f"{metadata_path}: folder name and PMID metadata do not match")
        sources = payload.get("sources")
        if not isinstance(sources, list) or not sources:
            raise ValueError(f"{metadata_path}: sources must be a non-empty list")
        study_metadata.append(payload)
    if not study_metadata:
        raise ValueError(f"No study metadata found under {studies_path}")
    return study_metadata


def load_sources(studies_path: Path = STUDIES_PATH) -> list[dict[str, Any]]:
    """Flatten original source objects from study metadata for compatibility views."""
    raw_sources = [
        source
        for study in load_study_metadata(studies_path)
        for source in study["sources"]
    ]
    sources = sorted((_source_metadata(entry) for entry in raw_sources), key=lambda item: item["source_id"])
    source_ids = [source["source_id"] for source in sources]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("Study metadata contains duplicate source_id values")
    return sources


def _gff3_document(features: list[str]) -> bytes:
    feature_body = "\n".join(features)
    body = f"{feature_body}\n" if features else ""
    return (GFF3_HEADER + body).encode("utf-8")


def build(
    output_dir: Path,
    *,
    studies_path: Path = STUDIES_PATH,
) -> dict[str, Any]:
    """Build derived per-source and per-assembly files for site/JBrowse use."""
    sources = load_sources(studies_path)
    output_dir = output_dir.resolve()
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    source_by_id = {source["source_id"]: source for source in sources}
    endpoints_by_source: dict[str, list[dict[str, str]]] = defaultdict(list)
    feature_lines_by_source: dict[str, list[str]] = defaultdict(list)
    for row, feature_line in iter_endpoint_feature_lines(studies_path.parent):
        source_id = row.get("source_id", "")
        if source_id not in source_by_id:
            raise ValueError(f"Endpoint row references unknown source_id {source_id!r}")
        endpoints_by_source[source_id].append(row)
        feature_lines_by_source[source_id].append(feature_line)

    for source in sources:
        source_id = source["source_id"]
        rows = endpoints_by_source.get(source_id, [])
        if len(rows) != source["record_count"]:
            raise ValueError(
                f"{source_id}: GFF3 reader found {len(rows)} records, "
                f"study metadata declares {source['record_count']}"
            )
        source_dir = output_dir / "records" / source_id
        source_dir.mkdir(parents=True)
        source_files: dict[str, Any] = {}
        if rows:
            gff3_bytes = _gff3_document(feature_lines_by_source[source_id])
            (source_dir / "endpoints.gff3").write_bytes(gff3_bytes)
            source_files["endpoints_gff3"] = {
                "path": "endpoints.gff3",
                "format": "GFF3",
                "record_count": len(rows),
                "sha256": sha256_bytes(gff3_bytes),
            }
        source_metadata = {
            "schema_version": "1.0",
            "release_version": RELEASE_VERSION,
            "source_id": source_id,
            "assembly_accession": source["assembly"],
            "record_count": len(rows),
            "files": source_files,
            "source_metadata_context": SOURCE_METADATA_CONTEXT,
            "source_metadata": source["source_metadata"],
        }
        (source_dir / "metadata.json").write_text(
            json.dumps(source_metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source in sources:
        grouped[source["assembly"]].append(source)

    catalog: dict[str, Any] = {
        "release_version": RELEASE_VERSION,
        "assembly_count": len(grouped),
        "assemblies": {},
    }
    for assembly, assembly_sources in grouped.items():
        assembly_dir = output_dir / "assemblies" / assembly
        assembly_dir.mkdir(parents=True)
        rows = [
            endpoint
            for source in assembly_sources
            for endpoint in endpoints_by_source.get(source["source_id"], [])
        ]
        feature_lines = [
            feature_line
            for source in assembly_sources
            for feature_line in feature_lines_by_source.get(source["source_id"], [])
        ]
        total_records = len(rows)
        source_entries: list[dict[str, Any]] = []
        for source in assembly_sources:
            source_entries.append({
                "source_id": source["source_id"],
                "dataset_id": source["dataset_id"],
                "species": source["species"],
                "year": source["year"],
                "assay": source["assay"],
                "evidence_class": source["evidence_class"],
                "release_status": source["release_status"],
                "record_count": source["record_count"],
                "paper": {
                    "title": source["title"],
                    "pmid": source["pmid"],
                    "pubmed_url": source["pubmed_url"],
                    "doi": source["doi"],
                    "doi_url": source["doi_url"],
                },
                "raw_data": {"accessions": source["raw_data_accessions"], "url": source["raw_data_url"]},
                "license": {
                    "article_license": source["article_license"],
                    "redistribution_status": source["redistribution_status"],
                },
                "known_limitations": source["known_limitations"],
                "endpoint_field_defaults": source["endpoint_field_defaults"],
                "source_metadata_context": SOURCE_METADATA_CONTEXT,
                "source_metadata": source["source_metadata"],
            })

        files: dict[str, Any] = {}
        if rows:
            gff3_bytes = _gff3_document(feature_lines)
            (assembly_dir / "endpoints.gff3").write_bytes(gff3_bytes)
            files["endpoints_gff3"] = {
                "path": "endpoints.gff3",
                "format": "GFF3",
                "record_count": total_records,
                "sha256": sha256_bytes(gff3_bytes),
            }
        metadata = {
            "schema_version": "1.0",
            "release_version": RELEASE_VERSION,
            "assembly_accession": assembly,
            "organisms": sorted({source["species"] for source in assembly_sources}),
            "track_count": len(assembly_sources),
            "published_track_count": sum(source["release_status"] != "audit_only" for source in assembly_sources),
            "record_count": total_records,
            "aggregation_policy": (
                "Sources are grouped only when the exact reference assembly accession matches. "
                "GFF3 retains source-specific IDs and attributes without deduplication."
            ),
            "coordinate_convention": "GFF3 uses 1-based closed single-base features.",
            "score_policy": "The GFF3 score column is '.', and each paper-specific original score is retained in signal_or_score.",
            "files": files,
            "sources": source_entries,
        }
        metadata_bytes = (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        (assembly_dir / "metadata.json").write_bytes(metadata_bytes)
        catalog["assemblies"][assembly] = {
            "metadata": f"assemblies/{assembly}/metadata.json",
            "gff3": f"assemblies/{assembly}/endpoints.gff3" if rows else None,
            "source_ids": [source["source_id"] for source in assembly_sources],
            "record_count": total_records,
        }

    (output_dir / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return catalog


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("dist/site/downloads/v0.3.0"))
    parser.add_argument("--studies-dir", type=Path, default=STUDIES_PATH)
    args = parser.parse_args()
    catalog = build(args.output_dir.expanduser(), studies_path=args.studies_dir.expanduser())
    published = sum(entry["gff3"] is not None for entry in catalog["assemblies"].values())
    print(
        f"PASS  {catalog['assembly_count']} v0.3.0 assembly metadata packages; "
        f"{published} GFF3 packages; source endpoint GFF3 generated"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
