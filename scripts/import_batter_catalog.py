#!/usr/bin/env python3
"""Validate and import the full BATTER genome catalogue into local Wrangler D1."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "data/derived/batter_gff3/full_run_cu10-current-20260929"
MIGRATION = ROOT / "prototype/accession-range/migrations/0003_add_batter_genome_catalog.sql"
REQUIRED_MANIFEST = {
    "batch_rank", "otu_id", "genome_id", "tes_prediction", "otu_augmentation_window",
    "otu_augmentation_span", "rfam_training_window", "rfam_training_span", "prediction_gff3_path",
    "prediction_gff3_sha256", "augmentation_gff3_path", "augmentation_gff3_sha256", "augmentation_status",
}
REQUIRED_TAXONOMY = {
    "otu_id", "genome_id", "genome_type", "source_collection", "taxonomy", "domain", "phylum",
    "class", "order", "family", "genus", "species",
}
REQUIRED_REFERENCE = {
    "otu_id", "representative_genome_id", "cohort", "fasta_path", "compressed_bytes", "sha256", "contigs", "bases",
}
TAXONOMY_COLUMNS = ("domain", "phylum", "class", "order", "family", "genus", "species")
INTEGER_COLUMNS = (
    "batch_rank", "tes_prediction", "otu_augmentation_window", "otu_augmentation_span",
    "rfam_training_window", "rfam_training_span",
)
INSERT_COLUMNS = (
    "genome_id", "otu_id", "batch_rank", "genome_type", "source_collection", "taxonomy", "domain",
    "phylum", "class", "order", "family", "genus", "species", "tes_prediction",
    "otu_augmentation_window", "otu_augmentation_span", "rfam_training_window", "rfam_training_span",
    "augmentation_status", "prediction_gff3_path", "prediction_gff3_sha256", "augmentation_gff3_path",
    "augmentation_gff3_sha256", "reference_cohort", "reference_genome_id", "reference_fasta_path",
    "reference_compressed_bytes", "reference_sha256", "reference_contigs", "reference_bases", "search_text",
)


class ImportError(RuntimeError):
    pass


def read_tsv(path: Path, required: set[str]) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            missing = required - set(reader.fieldnames or [])
            if missing:
                raise ImportError(f"{path}: missing columns {', '.join(sorted(missing))}")
            return [{key: (value or "").strip() for key, value in row.items() if key is not None} for row in reader]
    except OSError as exc:
        raise ImportError(f"Could not read {path}") from exc


def index_unique(rows: list[dict[str, str]], key: str, label: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        value = row[key]
        if not value or value in result:
            raise ImportError(f"{label}: empty or duplicate {key}: {value!r}")
        result[value] = row
    return result


def positive_integer(value: str, label: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ImportError(f"Invalid integer for {label}: {value!r}") from exc
    if result < 0:
        raise ImportError(f"Negative count for {label}: {value!r}")
    return result


def build_rows(data_dir: Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    manifest_path = data_dir / "batch_manifest.tsv"
    taxonomy_path = data_dir / "taxonomy_by_genome.tsv"
    reference_path = data_dir / "gem_references_manifest.tsv"
    audit_path = data_dir / "audit.json"
    manifest = read_tsv(manifest_path, REQUIRED_MANIFEST)
    taxonomy = index_unique(read_tsv(taxonomy_path, REQUIRED_TAXONOMY), "genome_id", "taxonomy")
    references = index_unique(read_tsv(reference_path, REQUIRED_REFERENCE), "otu_id", "GEM references")
    if len(manifest) != len(taxonomy):
        raise ImportError(f"Manifest has {len(manifest):,} genomes but taxonomy has {len(taxonomy):,}")
    if len({row["genome_id"] for row in manifest}) != len(manifest):
        raise ImportError("batch_manifest.tsv contains duplicate genome IDs")

    audit: dict[str, Any] = {}
    if audit_path.is_file():
        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ImportError(f"Could not parse current audit: {audit_path}") from exc
        if int(audit.get("genomes", -1)) != len(manifest):
            raise ImportError("Audit genome count does not match the batch manifest")

    output: list[dict[str, Any]] = []
    totals = {column: 0 for column in INTEGER_COLUMNS if column != "batch_rank"}
    reference_matches = 0
    genome_types: set[str] = set()
    for row in manifest:
        genome_id = row["genome_id"]
        tax = taxonomy.get(genome_id)
        if tax is None:
            raise ImportError(f"Missing taxonomy row for {genome_id}")
        if row["otu_id"] != tax["otu_id"]:
            raise ImportError(f"OTU mismatch for {genome_id}: manifest={row['otu_id']} taxonomy={tax['otu_id']}")
        if tax["genome_type"] not in {"MAG", "isolate", "SAG"}:
            raise ImportError(f"Unexpected genome type for {genome_id}: {tax['genome_type']!r}")
        genome_types.add(tax["genome_type"])
        numbers = {column: positive_integer(row[column], f"{genome_id}.{column}") for column in INTEGER_COLUMNS}
        for column in totals:
            totals[column] += numbers[column]
        reference = references.get(row["otu_id"])
        if reference:
            reference_matches += 1
            if reference["representative_genome_id"] != genome_id:
                raise ImportError(
                    f"GEM representative genome mismatch for {row['otu_id']}: "
                    f"manifest={genome_id} GEM={reference['representative_genome_id']}"
                )
            if reference["sha256"] and not re.fullmatch(r"[0-9a-fA-F]{64}", reference["sha256"]):
                raise ImportError(f"Invalid GEM reference SHA-256 for {row['otu_id']}")
        fields: dict[str, Any] = {
            "genome_id": genome_id,
            "otu_id": row["otu_id"],
            "batch_rank": numbers["batch_rank"],
            "genome_type": tax["genome_type"],
            "source_collection": tax["source_collection"],
            "taxonomy": tax["taxonomy"],
            **{column: tax.get(column, "") for column in TAXONOMY_COLUMNS},
            **{column: numbers[column] for column in INTEGER_COLUMNS if column != "batch_rank"},
            "augmentation_status": row["augmentation_status"] or "no_records_in_source",
            "prediction_gff3_path": row["prediction_gff3_path"],
            "prediction_gff3_sha256": row["prediction_gff3_sha256"],
            "augmentation_gff3_path": row["augmentation_gff3_path"],
            "augmentation_gff3_sha256": row["augmentation_gff3_sha256"],
            "reference_cohort": reference.get("cohort") if reference else None,
            "reference_genome_id": reference.get("representative_genome_id") if reference else None,
            "reference_fasta_path": reference.get("fasta_path") if reference else None,
            "reference_compressed_bytes": positive_integer(reference["compressed_bytes"], f"{row['otu_id']}.compressed_bytes") if reference else None,
            "reference_sha256": reference.get("sha256") if reference else None,
            "reference_contigs": positive_integer(reference["contigs"], f"{row['otu_id']}.contigs") if reference else None,
            "reference_bases": positive_integer(reference["bases"], f"{row['otu_id']}.bases") if reference else None,
        }
        fields["search_text"] = " ".join(str(fields[key]) for key in (
            "genome_id", "otu_id", "genome_type", "source_collection", "taxonomy", *TAXONOMY_COLUMNS,
        ) if fields.get(key)).casefold()
        if fields["augmentation_status"] not in {"has_features", "no_records_in_source"}:
            raise ImportError(f"Unexpected augmentation status for {genome_id}: {fields['augmentation_status']!r}")
        augmentation_count = sum(numbers[column] for column in (
            "otu_augmentation_window", "otu_augmentation_span", "rfam_training_window", "rfam_training_span",
        ))
        if fields["augmentation_status"] == "no_records_in_source" and augmentation_count:
            raise ImportError(f"No-records status conflicts with augmentation counts for {genome_id}")
        if fields["augmentation_status"] == "has_features" and not augmentation_count:
            raise ImportError(f"Feature status has no augmentation counts for {genome_id}")
        for hash_column in ("prediction_gff3_sha256", "augmentation_gff3_sha256"):
            if not re.fullmatch(r"[0-9a-fA-F]{64}", str(fields[hash_column])):
                raise ImportError(f"Invalid {hash_column} for {genome_id}")
        output.append(fields)

    if audit:
        expected = audit.get("feature_totals", {})
        mismatches = [f"{key}={totals[key]} expected {expected.get(key)}" for key in totals if expected.get(key) is not None and int(expected[key]) != totals[key]]
        if mismatches:
            raise ImportError("The manifest does not match audit.json: " + "; ".join(mismatches))
        expected_types = audit.get("genome_types", {})
        observed_types = {kind: sum(1 for row in output if row["genome_type"] == kind) for kind in genome_types}
        if expected_types and observed_types != expected_types:
            raise ImportError("Genome-type counts do not match audit.json")

    metrics = {
        "genomes": len(output),
        "reference_matches": reference_matches,
        "prediction_records": totals["tes_prediction"],
        "otu_augmentation_spans": totals["otu_augmentation_span"],
        "rfam_training_spans": totals["rfam_training_span"],
        "no_augmentation_genomes": sum(1 for row in output if row["augmentation_status"] == "no_records_in_source"),
    }
    if audit and metrics["genomes"] != int(audit.get("genomes", 0)):
        raise ImportError("Genome total failed audit validation")
    if reference_matches != len(output):
        raise ImportError(f"GEM reference manifest matched {reference_matches:,} of {len(output):,} genomes")
    if audit.get("otus_with_training_records") is not None:
        expected_empty = len(output) - int(audit["otus_with_training_records"])
        if metrics["no_augmentation_genomes"] != expected_empty:
            raise ImportError("No-augmentation genome count does not match the current audit")
    return output, metrics


def sql_value(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, int):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def write_import_sql(rows: list[dict[str, Any]], output_dir: Path, batch_size: int = 500) -> list[Path]:
    marker = output_dir / "import-manifest.json"
    if output_dir.exists():
        if output_dir.is_symlink():
            raise ImportError(f"Refusing to write through a symlink: {output_dir}")
        if marker.is_file():
            try:
                owner = json.loads(marker.read_text(encoding="utf-8")).get("generated_by")
            except (OSError, json.JSONDecodeError) as exc:
                raise ImportError(f"Invalid import directory marker: {marker}") from exc
            if owner != "scripts/import_batter_catalog.py":
                raise ImportError(f"Refusing to overwrite an import directory owned by another tool: {output_dir}")
        else:
            if any(output_dir.iterdir()):
                raise ImportError(f"Refusing to overwrite an existing unmarked import directory: {output_dir}")
    else:
        output_dir.mkdir(parents=True)

    quoted_columns = [f'"{column}"' for column in INSERT_COLUMNS]
    clear_file = output_dir / "0000-clear-catalogue.sql"
    clear_file.write_text("DELETE FROM batter_genomes;\n", encoding="utf-8", newline="\n")
    header = f"INSERT INTO batter_genomes ({', '.join(quoted_columns)}) VALUES\n"
    chunk_paths = [clear_file]
    for start in range(0, len(rows), batch_size):
        path = output_dir / f"{start // batch_size + 1:04d}-genomes.sql"
        values = [
            "(" + ", ".join(sql_value(row.get(column)) for column in INSERT_COLUMNS) + ")"
            for row in rows[start : start + batch_size]
        ]
        path.write_text(header + ",\n".join(values) + ";\n", encoding="utf-8", newline="\n")
        chunk_paths.append(path)
    marker.write_text(json.dumps({
        "generated_by": "scripts/import_batter_catalog.py",
        "genome_rows": len(rows),
        "chunk_size": batch_size,
        "chunk_count": len(chunk_paths) - 1,
    }, indent=2) + "\n", encoding="utf-8", newline="\n")
    return chunk_paths


def validate_local_db_path(database: Path) -> Path:
    database = database.resolve(strict=True)
    d1_root = (ROOT / "prototype/accession-range/.wrangler/state/v3/d1/miniflare-D1DatabaseObject").resolve()
    try:
        database.relative_to(d1_root)
    except ValueError as exc:
        raise ImportError(f"Local D1 file must be inside {d1_root}") from exc
    if database.suffix.lower() != ".sqlite" or database.name == "metadata.sqlite":
        raise ImportError(f"Not a Wrangler local D1 database file: {database}")
    return database


def apply_local_sqlite(database: Path, rows: list[dict[str, Any]], expected: dict[str, int]) -> dict[str, int]:
    database = validate_local_db_path(database)

    quoted_columns = ", ".join(f'"{column}"' for column in INSERT_COLUMNS)
    placeholders = ", ".join("?" for _ in INSERT_COLUMNS)
    insert_sql = f"INSERT INTO batter_genomes ({quoted_columns}) VALUES ({placeholders})"
    connection = sqlite3.connect(database, timeout=10)
    try:
        connection.execute("PRAGMA busy_timeout = 10000")
        migration = MIGRATION.read_text(encoding="utf-8")
        try:
            connection.executescript("BEGIN IMMEDIATE;\n" + migration + "\nCOMMIT;")
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'batter_genomes'"
        ).fetchone()
        if not table:
            raise ImportError("The local D1 catalogue migration has not been applied")
        columns = {row[1] for row in connection.execute('PRAGMA table_info("batter_genomes")')}
        missing_columns = set(INSERT_COLUMNS) - columns
        if missing_columns:
            raise ImportError("Local D1 table is missing columns: " + ", ".join(sorted(missing_columns)))

        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute("DELETE FROM batter_genomes")
            connection.executemany(
                insert_sql,
                [tuple(row.get(column) for column in INSERT_COLUMNS) for row in rows],
            )
            observed_row = connection.execute(
                "SELECT COUNT(*) AS genomes, COALESCE(SUM(tes_prediction), 0) AS prediction_records, "
                "COALESCE(SUM(otu_augmentation_span), 0) AS otu_augmentation_spans, "
                "COALESCE(SUM(rfam_training_span), 0) AS rfam_training_spans, "
                "COALESCE(SUM(CASE WHEN augmentation_status = 'no_records_in_source' THEN 1 ELSE 0 END), 0) AS no_augmentation_genomes, "
                "COALESCE(SUM(CASE WHEN reference_genome_id IS NOT NULL THEN 1 ELSE 0 END), 0) AS reference_matches "
                "FROM batter_genomes"
            ).fetchone()
            observed_keys = (
                "genomes", "prediction_records", "otu_augmentation_spans", "rfam_training_spans",
                "no_augmentation_genomes", "reference_matches",
            )
            observed = dict(zip(observed_keys, observed_row))
            if observed != expected:
                raise ImportError(f"Local D1 totals do not match the validated manifest: {observed!r}")
            connection.commit()
            return observed
        except Exception:
            connection.rollback()
            raise
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="Directory with current manifest, taxonomy, audit, and GEM reference manifest TSVs")
    parser.add_argument("--sql-dir", type=Path, default=ROOT / "dist/batter-genomes-import-chunks", help="Generated import SQL chunks (kept under dist by default)")
    parser.add_argument("--local-db", type=Path, help="Exact Wrangler local D1 SQLite file to update; stop `wrangler dev` first")
    parser.add_argument("--apply", action="store_true", help="Apply the local D1 schema and transactionally replace rows in the specified SQLite file")
    args = parser.parse_args()
    try:
        rows, metrics = build_rows(args.data_dir.resolve())
        sql_dir = args.sql_dir.resolve()
        try:
            sql_dir.relative_to((ROOT / "dist").resolve())
        except ValueError as exc:
            raise ImportError("SQL output directory must stay inside dist/") from exc
        sql_files = write_import_sql(rows, sql_dir)
        print("PASS  BATTER import validated:")
        print(json.dumps(metrics, indent=2))
        total_bytes = sum(path.stat().st_size for path in sql_files)
        print(f"SQL chunks: {len(sql_files) - 1} inserts, {total_bytes:,} bytes in {sql_dir}")
        if args.apply:
            if not args.local_db:
                raise ImportError("--apply requires --local-db with the exact Wrangler local D1 SQLite path")
            apply_local_sqlite(args.local_db, rows, metrics)
            print("PASS  BATTER genome catalogue applied to local D1")
        else:
            print("Run with --apply to load the local D1 binding.")
        return 0
    except (ImportError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
        print(f"FAIL  {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
