"""Read the compact GFF3 and TSV tables in the public v0.3.0 release."""

from __future__ import annotations

import csv
import gzip
import json
import re
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote, unquote


ENDPOINT_COLUMNS = (
    "end_id", "source_id", "sample_id", "assay", "evidence_class",
    "author_endpoint_id", "published_reference_accession", "reference_assembly",
    "reference_name", "replicon_label", "biological_coordinate_1based",
    "bed_start_0based", "bed_end_0based", "strand", "signal_or_score",
    "author_category", "associated_gene_or_locus", "pmid", "doi",
    "source_table_or_file", "coordinate_interpretation", "original_row_reference",
    "qc_status", "note",
)

# GFF3's standard columns and study metadata defaults carry the other endpoint fields.
GFF3_ROW_ATTRIBUTE_COLUMNS = (
    "author_endpoint_id",
    "published_reference_accession",
    "replicon_label",
    "signal_or_score",
    "author_category",
    "associated_gene_or_locus",
    "original_row_reference",
)

RELATED_TABLES = {"gene_associations", "condition_observations"}
RELATED_TABLE_PMIDS = {
    "gene_associations": "31594819",
    "condition_observations": "37402717",
}
ANNOTATION_ATTRIBUTE_PREFIX = "ann_"

GENE_COLUMNS = (
    "end_id", "link_status", "record_id", "source_id", "species",
    "evidence_class", "reference_name", "biological_coordinate_1based",
    "bed_start_0based", "bed_end_0based", "strand", "locus",
    "gene_start_1based", "gene_end_1based", "gene_annotation", "tts_counts",
    "three_prime_utr_length", "begins_operon", "operon_id", "pmid", "doi",
    "source_table", "count_discrepancy_warning",
)
CONDITION_COLUMNS = (
    "end_id", "link_status", "observation_id", "site_id", "source_id",
    "species", "sample_id", "assay", "evidence_class", "published_replicon",
    "reference_name", "biological_coordinate_1based", "bed_start_0based",
    "bed_end_0based", "strand", "average_read_count", "classification",
    "gene_details", "locus_details", "ncbi_description", "uniprot_description",
    "three_prime_end_region", "terminator_score", "predicted_utr_length",
    "kinefold_structure", "a_tract", "pmid", "doi", "source_table",
    "coordinate_interpretation",
)
RELATED_COLUMNS = {
    "gene_associations": GENE_COLUMNS,
    "condition_observations": CONDITION_COLUMNS,
}
CONDITION_ENDPOINT_ALIASES = {
    "site_id": "author_endpoint_id",
    "published_replicon": "replicon_label",
}
STUDY_METADATA_TSV_COLUMNS = (
    "source_id",
    "species",
    "assembly",
    "pmid",
    "title",
    "assay",
    "record_count",
    "evidence_class",
    "release_status",
    "article_license",
    "redistribution_status",
    "raw_data_accessions",
    "known_limitations",
)


def source_pmid(source: dict) -> str:
    values = {
        str(value).strip()
        for section, field in (
            ("registry_manifest", "pmid"),
            ("registry_row", "pmid"),
            ("publication_status", "pmid"),
            ("license_status", "pmid"),
        )
        if (value := (source.get(section) or {}).get(field)) not in (None, "", "NA")
    }
    if len(values) != 1:
        raise ValueError(f"Source {source.get('source_id')!r} has missing or conflicting PMID metadata")
    return next(iter(values))


def source_record_count(source: dict) -> int:
    value = (source.get("publication_status") or {}).get("record_count")
    if value in (None, ""):
        value = (((source.get("registry_manifest") or {}).get("repository_release") or {}).get("record_count"))
    try:
        count = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid record_count for source {source.get('source_id')!r}: {value!r}") from exc
    if count < 0:
        raise ValueError(f"Negative record_count for source {source.get('source_id')!r}")
    return count


def _metadata_source_value(source: dict, paths: tuple[tuple[str, str], ...], default: Any = "") -> Any:
    for section, field in paths:
        value = (source.get(section) or {}).get(field)
        if value not in (None, "", "NA"):
            return value
    return default


def study_metadata_tsv_row(source: dict) -> dict[str, str]:
    """Flatten one full source object into its readable per-study TSV row."""

    raw_accessions = _metadata_source_value(
        source,
        (("registry_manifest", "raw_data_accessions"), ("registry_row", "raw_data_accessions")),
    )
    if isinstance(raw_accessions, list):
        raw_accessions = ";".join(str(value) for value in raw_accessions)
    row: dict[str, Any] = {
        "source_id": source.get("source_id", ""),
        "species": _metadata_source_value(source, (("registry_manifest", "species"), ("registry_row", "species"))),
        "assembly": _metadata_source_value(source, (("registry_manifest", "reference_genome"), ("registry_row", "reference_genome"))),
        "pmid": source_pmid(source),
        "title": _metadata_source_value(source, (("registry_manifest", "paper_title"), ("registry_row", "paper_title"))),
        "assay": _metadata_source_value(source, (("registry_manifest", "assay_family"), ("registry_row", "assay_family"))),
        "record_count": str(source_record_count(source)),
        "evidence_class": _metadata_source_value(source, (("publication_status", "evidence_class"),)),
        "release_status": _metadata_source_value(source, (("publication_status", "release_status"),)),
        "article_license": _metadata_source_value(source, (("license_status", "article_license"),)),
        "redistribution_status": _metadata_source_value(source, (("license_status", "redistribution_status"), ("publication_status", "redistribution_status"))),
        "raw_data_accessions": raw_accessions,
        "known_limitations": (source.get("release_facts") or {}).get("known_limitations", ""),
    }
    return {name: str(row.get(name, "")) for name in STUDY_METADATA_TSV_COLUMNS}


def iter_study_metadata(release_root: Path):
    """Yield study directories and their full metadata in stable folder order."""

    studies_root = release_root / "studies"
    if not studies_root.is_dir():
        raise ValueError(f"Study metadata directory is missing: {studies_root}")
    study_dirs = sorted(path for path in studies_root.iterdir() if path.is_dir())
    if not study_dirs:
        raise ValueError(f"No study folders found in {studies_root}")
    for study_dir in study_dirs:
        if study_dir.is_symlink() or not study_dir.name.startswith("PMID_"):
            raise ValueError(f"Invalid study folder: {study_dir}")
        metadata_path = study_dir / "metadata.json"
        if not metadata_path.is_file() or metadata_path.is_symlink():
            raise ValueError(f"Study metadata is missing or symlinked: {metadata_path}")
        document = json.loads(metadata_path.read_text(encoding="utf-8"))
        if document.get("release_version") != "v0.3.0":
            raise ValueError(f"{metadata_path} must describe v0.3.0")
        pmid = str(document.get("pmid", ""))
        if not pmid or study_dir.name != f"PMID_{pmid}":
            raise ValueError(f"Study folder and metadata PMID do not match: {study_dir}")
        sources = document.get("sources")
        if not isinstance(sources, list) or not sources:
            raise ValueError(f"{metadata_path} must contain a non-empty sources list")
        if document.get("source_count") != len(sources):
            raise ValueError(f"{metadata_path} source_count does not match its sources list")
        for source in sources:
            if not isinstance(source, dict) or source_pmid(source) != pmid:
                raise ValueError(f"{metadata_path} contains a source from another PMID")
        yield study_dir, document


def load_source_index(release_root: Path) -> dict[str, dict]:
    """Index losslessly preserved per-source objects from study metadata."""

    by_id: dict[str, dict] = {}
    for _study_dir, document in iter_study_metadata(release_root):
        for source in document["sources"]:
            source_id = source.get("source_id")
            if not isinstance(source_id, str) or not source_id or source_id in by_id:
                raise ValueError(f"Study metadata has a missing or duplicate source ID: {source_id!r}")
            by_id[source_id] = source
    return by_id


def _gff3_escape(value: str) -> str:
    """Encode UTF-8 values using the same rules as the BTED browser tracks."""

    return quote(value, safe="._:-|")


def _gff3_unescape(value: str) -> str:
    if re.search(r"%(?![0-9A-Fa-f]{2})", value):
        raise ValueError(f"Malformed GFF3 percent escape: {value!r}")
    return unquote(value, encoding="utf-8", errors="strict")


def _parse_attributes(value: str, label: str) -> dict[str, str]:
    if value == ".":
        return {}
    result: dict[str, str] = {}
    for item in value.split(";"):
        if not item or "=" not in item:
            raise ValueError(f"{label}: malformed GFF3 attribute {item!r}")
        key, encoded = item.split("=", 1)
        if not key or key in result:
            raise ValueError(f"{label}: empty or duplicate GFF3 attribute key {key!r}")
        result[key] = _gff3_unescape(encoded)
    return result


def format_endpoint_gff3(row: dict[str, str], annotation_attributes: dict[str, str] | None = None) -> str:
    """Format one restored 24-column endpoint as a one-base GFF3 feature.

    Source constants are represented once in per-study metadata.json. The standard GFF3
    columns encode endpoint ID, source, reference, position, and strand; only
    the remaining row-varying original fields appear in attributes. Score is
    always '.' because scores from different papers are not comparable.
    """

    missing = set(ENDPOINT_COLUMNS) - set(row)
    if missing:
        raise ValueError(f"Endpoint row is missing fields: {sorted(missing)}")
    if any(not isinstance(row[name], str) for name in ENDPOINT_COLUMNS):
        raise ValueError("Endpoint values must remain strings")
    try:
        position = int(row["biological_coordinate_1based"])
    except ValueError as exc:
        raise ValueError(f"Invalid endpoint coordinate: {row['biological_coordinate_1based']!r}") from exc
    if position < 1 or str(position) != row["biological_coordinate_1based"]:
        raise ValueError(f"Endpoint coordinate is not canonical 1-based integer text: {row['biological_coordinate_1based']!r}")
    if row["strand"] not in {"+", "-", ".", "?"}:
        raise ValueError(f"Invalid GFF3 strand for {row['end_id']}: {row['strand']!r}")
    attributes = [f"ID={_gff3_escape(row['end_id'])}"]
    attributes.extend(
        f"{name}={_gff3_escape(row[name])}"
        for name in GFF3_ROW_ATTRIBUTE_COLUMNS
    )
    for name, value in (annotation_attributes or {}).items():
        if not name.startswith(ANNOTATION_ATTRIBUTE_PREFIX) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ValueError(f"Invalid annotation attribute name: {name!r}")
        if not isinstance(value, str):
            raise ValueError(f"Annotation attribute {name} is not a string")
        attributes.append(f"{name}={_gff3_escape(value)}")
    columns = (
        _gff3_escape(row["reference_name"]),
        _gff3_escape(row["source_id"]),
        "terminator_endpoint",
        str(position),
        str(position),
        ".",
        row["strand"],
        ".",
        ";".join(attributes),
    )
    return "\t".join(columns)


def iter_endpoint_gff3(release_root: Path) -> Iterator[dict[str, str]]:
    """Decode each study GFF3 and restore its original 24 endpoint fields."""

    for row, _feature_line in iter_endpoint_feature_lines(release_root):
        yield row


def iter_endpoints(release_root: Path) -> Iterator[dict[str, str]]:
    """Yield exact original endpoint values reconstructed from study files."""

    yield from iter_endpoint_gff3(release_root)


def iter_endpoint_feature_lines(release_root: Path) -> Iterator[tuple[dict[str, str], str]]:
    """Return validated endpoint rows with their original GFF3 feature lines."""

    sources = load_source_index(release_root)
    seen_ids: set[str] = set()
    for study_dir, study_metadata in iter_study_metadata(release_root):
        gff3_path = study_dir / "endpoints.gff3.gz"
        if not gff3_path.is_file() or gff3_path.is_symlink():
            raise ValueError(f"Study GFF3 is missing or symlinked: {gff3_path}")
        study_record_count = 0
        with gzip.open(gff3_path, "rt", encoding="utf-8", newline="") as handle:
            header_seen = False
            for line_number, raw_line in enumerate(handle, 1):
                line = raw_line.rstrip("\r\n")
                if line_number == 1:
                    if line != "##gff-version 3":
                        raise ValueError(f"{gff3_path}: must start with ##gff-version 3")
                    header_seen = True
                    continue
                if not line or line.startswith("#"):
                    continue
                if not header_seen:
                    raise ValueError(f"{gff3_path}: GFF3 version header is missing")
                columns = line.split("\t")
                label = f"{gff3_path}:{line_number}"
                if len(columns) != 9:
                    raise ValueError(f"{label}: expected 9 GFF3 columns, found {len(columns)}")
                seqid, source, feature_type, start_text, end_text, score, strand, phase, raw_attributes = columns
                seqid = _gff3_unescape(seqid)
                source = _gff3_unescape(source)
                if feature_type != "terminator_endpoint" or score != "." or phase != ".":
                    raise ValueError(f"{label}: invalid endpoint feature type, score, or phase")
                try:
                    start = int(start_text)
                    end = int(end_text)
                except ValueError as exc:
                    raise ValueError(f"{label}: invalid 1-based GFF3 coordinate") from exc
                if start < 1 or start != end or str(start) != start_text or str(end) != end_text:
                    raise ValueError(f"{label}: endpoint must be a canonical 1-based single-base feature")
                if strand not in {"+", "-", ".", "?"}:
                    raise ValueError(f"{label}: invalid GFF3 strand {strand!r}")
                attributes = _parse_attributes(raw_attributes, label)
                if not source:
                    raise ValueError(f"{label}: missing source ID")
                source_defaults = sources.get(source)
                if source_defaults is None:
                    raise ValueError(f"{label}: unknown GFF3 source ID {source!r}")
                if source_pmid(source_defaults) != study_metadata["pmid"]:
                    raise ValueError(f"{label}: source belongs to a different study PMID")
                annotation_map = source_defaults.get("annotation_field_map", {})
                if not isinstance(annotation_map, dict):
                    raise ValueError(f"{label}: invalid annotation field map for {source}")
                expected_extra = {
                    value["attribute"]
                    for value in annotation_map.values()
                    if isinstance(value, dict) and value.get("from") == "attribute" and isinstance(value.get("attribute"), str)
                }
                if any(not isinstance(value, dict) or value.get("from") not in {"attribute", "endpoint"} for value in annotation_map.values()):
                    raise ValueError(f"{label}: invalid annotation field mapping for {source}")
                expected_attributes = {"ID", *GFF3_ROW_ATTRIBUTE_COLUMNS, *expected_extra}
                if set(attributes) != expected_attributes:
                    raise ValueError(f"{label}: endpoint attributes do not match the v0.3.0 schema")
                end_id = attributes["ID"]
                if not end_id or end_id in seen_ids:
                    raise ValueError(f"{label}: missing or duplicate endpoint ID {end_id!r}")
                seen_ids.add(end_id)
                defaults = source_defaults.get("table_defaults", {}).get("endpoints")
                if not isinstance(defaults, dict) or any(not isinstance(value, str) for value in defaults.values()):
                    raise ValueError(f"{label}: missing or invalid endpoint defaults for {source}")
                if set(defaults).intersection(attributes):
                    raise ValueError(f"{label}: endpoint attributes overlap source defaults")
                row = {
                    **defaults,
                    **{name: attributes[name] for name in GFF3_ROW_ATTRIBUTE_COLUMNS},
                    "end_id": end_id,
                    "source_id": source,
                    "reference_name": seqid,
                    "biological_coordinate_1based": start_text,
                    "bed_start_0based": str(start - 1),
                    "bed_end_0based": end_text,
                    "strand": strand,
                }
                if set(row) != set(ENDPOINT_COLUMNS):
                    raise ValueError(f"{label}: reconstructed fields differ from the 24-column endpoint schema")
                study_record_count += 1
                yield {name: row[name] for name in ENDPOINT_COLUMNS}, line
        if study_record_count != study_metadata.get("record_count"):
            raise ValueError(
                f"{gff3_path}: metadata record_count is {study_metadata.get('record_count')}, "
                f"found {study_record_count} GFF3 features"
            )


def endpoint_index(release_root: Path) -> dict[tuple[str, str], dict[str, str]]:
    rows: dict[tuple[str, str], dict[str, str]] = {}
    for row in iter_endpoints(release_root):
        key = (row["source_id"], row["end_id"])
        if not all(key) or key in rows:
            raise ValueError(f"Duplicate or missing endpoint key: {key}")
        rows[key] = row
    return rows


def _validate_bed_position(row: dict[str, str], label: str) -> None:
    try:
        position = int(row["biological_coordinate_1based"])
        start = int(row["bed_start_0based"])
        end = int(row["bed_end_0based"])
    except (KeyError, ValueError) as exc:
        raise ValueError(f"{label}: invalid biological/BED coordinate") from exc
    if position < 1 or start != position - 1 or end != position:
        raise ValueError(f"{label}: inconsistent 1-based biological and BED coordinates")


def _iter_tsv_rows(release_root: Path, table: str) -> Iterator[dict[str, str]]:
    path = release_root / "studies" / f"PMID_{RELATED_TABLE_PMIDS[table]}" / f"{table}.tsv.gz"
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{table}.tsv.gz is missing or symlinked: {path}")
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError(f"{table}.tsv.gz has a missing or duplicate header")
        for line_number, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"{table}.tsv.gz:{line_number}: invalid column count")
            yield row


def iter_related_rows(release_root: Path, table: str) -> Iterator[dict[str, str]]:
    """Yield exact source rows for gene associations or condition observations."""

    if table not in RELATED_TABLES:
        raise ValueError(f"Unknown related table: {table}")
    sources = load_source_index(release_root)
    endpoints = endpoint_index(release_root)
    for compact in _iter_tsv_rows(release_root, table):
        source_id = compact.get("source_id", "")
        source = sources.get(source_id)
        if source is None:
            raise ValueError(f"{table} row has unknown source ID: {source_id!r}")
        defaults = source.get("table_defaults", {}).get(table, {})
        if not isinstance(defaults, dict) or any(not isinstance(value, str) for value in defaults.values()):
            raise ValueError(f"{table} has invalid source defaults for {source_id}")
        if set(defaults).intersection(compact):
            raise ValueError(f"{table} row repeats source defaults for {source_id}")
        row = {**defaults, **compact}
        end_id = row.get("end_id", "")
        status = row.get("link_status", "")
        if end_id:
            if status != "linked":
                raise ValueError(f"{table} row with end_id is not marked linked: {end_id}")
            parent = endpoints.get((source_id, end_id))
            if parent is None:
                raise ValueError(f"{table} points to an unknown endpoint: {(source_id, end_id)}")
            for name in ("reference_name", "biological_coordinate_1based", "strand"):
                if table == "gene_associations" and row.get(name, ""):
                    raise ValueError(f"{table} linked {name} duplicates endpoint {end_id}")
                row[name] = parent[name]
            if table == "condition_observations":
                for name, endpoint_name in CONDITION_ENDPOINT_ALIASES.items():
                    row[name] = parent[endpoint_name]
        elif table == "condition_observations":
            raise ValueError("Every condition observation must link to an endpoint")
        elif status != "unlinked_author_annotation":
            raise ValueError("Gene association without end_id needs unlinked status")
        elif not all(row.get(name, "") for name in ("reference_name", "biological_coordinate_1based", "strand")):
            raise ValueError("Unlinked gene association must retain its own genomic coordinate")
        row["bed_start_0based"] = str(int(row["biological_coordinate_1based"]) - 1)
        row["bed_end_0based"] = row["biological_coordinate_1based"]
        expected = RELATED_COLUMNS[table]
        if set(row) != set(expected):
            raise ValueError(f"{table} restored fields differ from the original table")
        _validate_bed_position(row, f"{table} row {row.get('record_id') or row.get('observation_id')}")
        yield {name: row[name] for name in expected}


def iter_annotations(release_root: Path) -> Iterator[dict]:
    """Restore source annotations from GFF3 attributes and source metadata."""
    sources = load_source_index(release_root)
    for endpoint, line in iter_endpoint_feature_lines(release_root):
        source_id = endpoint["source_id"]
        source = sources[source_id]
        field_map = source.get("annotation_field_map")
        if field_map is None:
            continue
        defaults = source.get("annotation_defaults", {})
        if not isinstance(field_map, dict) or not isinstance(defaults, dict):
            raise ValueError(f"Invalid annotation metadata for {source_id}")
        fields = dict(defaults.get("fields", {}))
        overrides = defaults.get("overrides", {})
        if not isinstance(overrides, dict) or any(not isinstance(value, str) for value in overrides.values()):
            raise ValueError(f"Invalid annotation override defaults for {source_id}")
        attributes = _parse_attributes(line.split("\t", 8)[8], endpoint["end_id"])
        for name, mapping in field_map.items():
            if mapping.get("from") == "endpoint":
                field = mapping.get("field")
                if field not in endpoint:
                    raise ValueError(f"Invalid endpoint annotation alias {source_id}.{name}")
                fields[name] = endpoint[field]
            elif mapping.get("from") == "attribute":
                attribute = mapping.get("attribute")
                if attribute not in attributes:
                    raise ValueError(f"Missing GFF3 annotation attribute {source_id}.{name}")
                fields[name] = attributes[attribute]
            else:
                raise ValueError(f"Invalid annotation field mapping {source_id}.{name}")
        yield {"end_id": endpoint["end_id"], "source_id": source_id, "fields": fields, "overrides": dict(overrides)}
