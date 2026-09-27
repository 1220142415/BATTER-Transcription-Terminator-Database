#!/usr/bin/env python3
"""Shared canonicalization helpers for BTED versioned data releases."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent

ENDPOINT_COLUMNS = [
    "end_id", "source_id", "sample_id", "assay", "evidence_class",
    "author_endpoint_id", "published_reference_accession",
    "reference_assembly", "reference_name", "replicon_label",
    "biological_coordinate_1based", "bed_start_0based", "bed_end_0based",
    "strand", "signal_or_score", "author_category",
    "associated_gene_or_locus", "pmid", "doi", "source_table_or_file",
    "coordinate_interpretation", "original_row_reference", "qc_status", "note",
]

PUBLIC_EVIDENCE = {
    "observed_signal",
    "called_endpoint",
    "author_called_endpoint",
    "curated_record",
}


def clean(value: str | None, fallback: str = "NA") -> str:
    value = (value or "").strip()
    return value if value else fallback


def first_value(row: dict[str, str], names: Iterable[str], fallback: str = "NA") -> str:
    for name in names:
        value = clean(row.get(name), "")
        if value and value.upper() != "NA":
            return value
    return fallback


def id_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_]+", "-", value.strip()).strip("-")
    return token or "NA"


def read_registry() -> dict[str, dict[str, str]]:
    path = REPO_ROOT / "data/registry/batter_s1_source_registry.tsv"
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["source_id"]: row for row in csv.DictReader(handle, delimiter="\t")}


def canonical_row(
    source_id: str,
    row: dict[str, str],
    row_number: int,
    config: dict[str, str],
    registry_row: dict[str, str],
    source_input_rel: str,
) -> dict[str, str]:
    sample = first_value(row, ["sample_id"], config["sample"])
    assay = first_value(row, ["assay"], config["assay"])
    reference_name = first_value(row, ["reference_name", "chrom", "published_replicon", "published_sequence_label", "chromosome_label"])
    replicon = first_value(row, ["replicon_label", "published_replicon", "published_sequence_label", "chromosome_label"], reference_name)
    position = first_value(row, ["biological_coordinate_1based", "published_coordinate_1based"])
    strand = first_value(row, ["strand"])
    author_id = first_value(
        row,
        ["author_endpoint_id", "author_tts_id", "author_tep_id", "genomic_site_id", "literature_end_id", "site_id", "end_id", "record_id"],
        f"row_{row_number}",
    )
    canonical_id = "_".join(
        [
            "BTED", id_token(source_id), id_token(sample), id_token(reference_name),
            "plus" if strand == "+" else "minus", id_token(position), f"r{row_number:06d}",
        ]
    )
    score = first_value(
        row,
        ["signal_or_score", "z_score", "score", "coverage", "intensity", "abundance", "base_mean", "conditions_detected", "log_average_read_count", "signal_at_published_coordinate"],
    )
    category = first_value(row, ["author_category", "category", "literature_category", "classification", "tts_class", "location_class"])
    gene = first_value(row, ["associated_gene_or_locus", "associated_gene", "locus", "upstream_gene", "gene_upstream", "locus_details", "gene_details"])
    coordinate_interpretation = first_value(
        row,
        ["coordinate_interpretation"],
        "Author/local table coordinate treated as 1-based biological position; BED is [position-1, position).",
    )
    return {
        "end_id": canonical_id,
        "source_id": source_id,
        "sample_id": sample,
        "assay": assay,
        "evidence_class": config["evidence"],
        "author_endpoint_id": author_id,
        "published_reference_accession": first_value(row, ["published_reference_accession"], reference_name),
        "reference_assembly": registry_row["reference_genome"],
        "reference_name": reference_name,
        "replicon_label": replicon,
        "biological_coordinate_1based": position,
        "bed_start_0based": str(int(position) - 1),
        "bed_end_0based": position,
        "strand": strand,
        "signal_or_score": score,
        "author_category": category,
        "associated_gene_or_locus": gene,
        "pmid": first_value(row, ["pmid"], registry_row["pmid"]),
        "doi": first_value(row, ["doi"], registry_row["doi"]),
        "source_table_or_file": first_value(row, ["source_table", "source_table_or_file"], Path(source_input_rel).name),
        "coordinate_interpretation": coordinate_interpretation,
        "original_row_reference": f"{source_input_rel}:row={row_number}",
        "qc_status": "migrated_coordinate_and_bed_checked",
        "note": config["note"],
    }


def validate_input_row(source_id: str, canonical: dict[str, str]) -> None:
    if canonical["evidence_class"] not in PUBLIC_EVIDENCE:
        raise ValueError(f"{source_id}: public evidence class is invalid: {canonical['evidence_class']}")
    try:
        position = int(canonical["biological_coordinate_1based"])
    except ValueError as exc:
        raise ValueError(f"{source_id}: non-integer coordinate: {canonical['biological_coordinate_1based']!r}") from exc
    if position < 1:
        raise ValueError(f"{source_id}: biological coordinate must be >= 1, got {position}")
    if canonical["strand"] not in {"+", "-"}:
        raise ValueError(f"{source_id}: invalid strand: {canonical['strand']!r}")
    if canonical["bed_start_0based"] != str(position - 1) or canonical["bed_end_0based"] != str(position):
        raise ValueError(f"{source_id}: BED conversion mismatch at {canonical['end_id']}")
    if canonical["reference_name"] == "NA":
        raise ValueError(f"{source_id}: reference_name is missing at {canonical['end_id']}")


def write_bed(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        for row in rows:
            handle.write(
                "\t".join(
                    [
                        row["reference_name"], row["bed_start_0based"], row["bed_end_0based"],
                        row["end_id"], "0", row["strand"],
                    ]
                ) + "\n"
            )
