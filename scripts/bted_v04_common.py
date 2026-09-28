"""Shared schemas and deterministic I/O for the BTED v0.4.0 release."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
from typing import Any, Iterable

from v03_tables import ENDPOINT_COLUMNS, RELATED_COLUMNS


ROOT = Path(__file__).resolve().parents[1]
V03_REL = Path("data/public/v0.3.0")
V03_ARCHIVE_REL = Path("data/archive/BTED-v0.3.0.tar.gz")
V03_ARCHIVE_SUMS_REL = Path("data/archive/BTED-v0.3.0.SHA256SUMS.txt")
V03_ARCHIVE_SHA_REL = Path("data/archive/BTED-v0.3.0.tar.gz.sha256")
V04_REL = Path("data/public/v0.4.0")
INTERNAL_REL = Path("data/registry/internal/v0.4.0")

GENOME_METADATA_COLUMNS = (
    "source_id",
    "pmid",
    "species",
    "assembly",
    "title",
    "assay",
    "record_count",
    "evidence_class",
    "release_status",
    "article_license",
    "redistribution_status",
    "raw_data_accessions",
    "known_limitations",
    "study_gff3",
    "gene_associations",
    "condition_observations",
)

RELATED_TABLE_FILES = {
    "gene_associations": "gene_associations.tsv.gz",
    "condition_observations": "condition_observations.tsv.gz",
}

EXPECTED_OLD_ENDPOINTS = 28_399
EXPECTED_CASCINO_COUNTS = {
    "BTED_EXT_2026_102": 388,
    "BTED_EXT_2026_103": 331,
    "BTED_EXT_2026_104": 342,
}
EXPECTED_GENE_ASSOCIATIONS = 805
EXPECTED_LINKED_GENE_ASSOCIATIONS = 460
EXPECTED_UNLINKED_GENE_ASSOCIATIONS = 345
EXPECTED_CONDITION_OBSERVATIONS = 2_277


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames:
            raise ValueError(f"TSV has no header: {path}")
        rows: list[dict[str, str]] = []
        for line_number, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Invalid TSV row width at {path}:{line_number}")
            rows.append({str(key): str(value) for key, value in row.items()})
        return list(reader.fieldnames), rows


def tsv_bytes(header: Iterable[str], rows: Iterable[dict[str, Any]]) -> bytes:
    fields = list(header)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=fields,
        delimiter="\t",
        lineterminator="\n",
        extrasaction="ignore",
        quoting=csv.QUOTE_MINIMAL,
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in fields})
    return buffer.getvalue().encode("utf-8")


def deterministic_gzip(data: bytes) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=output, compresslevel=9, mtime=0) as zipped:
        zipped.write(data)
    return output.getvalue()


def canonical_row(row: dict[str, Any], expected_columns: Iterable[str], label: str) -> dict[str, str]:
    expected = tuple(expected_columns)
    if set(row) != set(expected):
        raise ValueError(f"{label}: columns do not match the expected schema")
    values = {name: str(row[name]) for name in expected}
    if any("\x00" in value for value in values.values()):
        raise ValueError(f"{label}: NUL byte in value")
    return values


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def check_safe_relative(path: str) -> Path:
    relative = Path(path)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError(f"Unsafe relative path: {path!r}")
    return relative


def endpoint_expected_default_fields() -> set[str]:
    """Fields that cannot be reconstructed from standard GFF3 columns/attributes."""

    from v03_tables import GFF3_ROW_ATTRIBUTE_COLUMNS

    encoded = {
        *GFF3_ROW_ATTRIBUTE_COLUMNS,
        "end_id",
        "source_id",
        "reference_name",
        "biological_coordinate_1based",
        "bed_start_0based",
        "bed_end_0based",
        "strand",
    }
    return set(ENDPOINT_COLUMNS) - encoded


def table_columns(table: str) -> tuple[str, ...]:
    if table not in RELATED_COLUMNS:
        raise ValueError(f"Unknown related table: {table}")
    return tuple(RELATED_COLUMNS[table])
