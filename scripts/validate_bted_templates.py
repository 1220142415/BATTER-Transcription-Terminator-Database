#!/usr/bin/env python3
"""Validate the 26-column source and 24-column endpoint TSV templates.

Checks exact column names/order, required columns and duplicates.
Usage: python scripts/validate_bted_templates.py [sources.tsv endpoints.tsv]
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_SOURCE = REPO_ROOT / "data/registry/templates/external_literature_source_intake.tsv"
DEFAULT_ENDPOINT = REPO_ROOT / "data/registry/templates/external_literature_endpoint_schema.tsv"

SOURCE_EXPECTED = [
    "source_id", "dataset_id", "paper_title", "paper_publication_year",
    "pmid", "doi", "pmc_or_fulltext_url", "species", "strain",
    "taxonomy_id", "assay", "primary_evidence_class",
    "sample_id_or_condition", "raw_data_accessions",
    "raw_or_supplement_url", "endpoint_source_file",
    "published_reference_accession", "reference_assembly",
    "reference_sequence_accession_or_contigs", "coordinate_convention",
    "strand_definition", "license_or_reuse_note", "processing_status",
    "curator", "intake_date", "blocker_or_note",
]

ENDPOINT_EXPECTED = [
    "end_id", "source_id", "sample_id", "assay", "evidence_class",
    "author_endpoint_id", "published_reference_accession",
    "reference_assembly", "reference_name", "replicon_label",
    "biological_coordinate_1based", "bed_start_0based", "bed_end_0based",
    "strand", "signal_or_score", "author_category",
    "associated_gene_or_locus", "pmid", "doi", "source_table_or_file",
    "coordinate_interpretation", "original_row_reference", "qc_status",
    "note",
]

# Required intake and normalization fields (a subset of the full schema).
SOURCE_REQUIRED = [
    "source_id", "dataset_id", "paper_title", "species", "strain",
    "assay", "primary_evidence_class", "processing_status",
    "published_reference_accession", "reference_assembly",
    "coordinate_convention", "strand_definition",
]

ENDPOINT_REQUIRED = [
    "end_id", "source_id", "sample_id", "assay", "evidence_class",
    "reference_name", "biological_coordinate_1based",
    "bed_start_0based", "bed_end_0based", "strand", "qc_status",
]


def check_template(label: str, path: Path, expected: list[str], required: list[str]) -> list[str]:
    """Return template problems; an empty list means success."""
    problems: list[str] = []

    if not path.is_file():
        return [f"{label}: File not found: {path}"]
    try:
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
    except (UnicodeDecodeError, IndexError):
        return [f"{label}: Empty file or invalid UTF-8: {path}"]

    header = first_line.split("\t")
    if len(header) == 1 and "," in first_line:
        problems.append(f"{label}: Header appears comma-separated; expected tab-separated values (TSV)")

    # 1. Column count
    if len(header) != len(expected):
        problems.append(f"{label}: Column count is {len(header)}; expected {len(expected)}")

    # 2. Duplicate column
    seen: set[str] = set()
    for col in header:
        if col in seen:
            problems.append(f"{label}: Duplicate column: {col}")
        seen.add(col)

    # 3. Required columns
    for col in required:
        if col not in header:
            problems.append(f"{label}: Missing required column: {col}")

    # 4. Unexpected columns
    for col in header:
        if col not in expected:
            problems.append(f"{label}: Unexpected column: {col!r} (check spelling)")

    # 5. Column order
    if header != expected and not any("Column count is" in p or "Unexpected column" in p for p in problems):
        for i, (got, want) in enumerate(zip(header, expected)):
            if got != want:
                problems.append(
                    f"{label}: Column {i + 1} has {got!r}; expected {want!r}"
                )
                break

    return problems


def main() -> int:
    source_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    endpoint_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_ENDPOINT

    print("=" * 60)
    print("BTED intake template validation")
    print("Checks: header / 26 and 24 columns / duplicates / required columns / names and order")
    print("=" * 60)

    all_problems: list[str] = []
    for label, path, expected, required in [
        ("Source intake template", source_path, SOURCE_EXPECTED, SOURCE_REQUIRED),
        ("Endpoint template", endpoint_path, ENDPOINT_EXPECTED, ENDPOINT_REQUIRED),
    ]:
        problems = check_template(label, path, expected, required)
        if problems:
            for p in problems:
                print(f"FAIL  {p}")
            all_problems.extend(problems)
        else:
            print(f"PASS  {label}: {path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path} ({len(expected)} columns)")

    print("=" * 60)
    if all_problems:
        print(f"FAIL  {len(all_problems)} problems; correct them and retry.")
        return 1
    print("PASS  Both templates passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
