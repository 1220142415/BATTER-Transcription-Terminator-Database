"""Build the v0.4.0 D1 staging bundle from its public GFF3 and internal provenance."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, unquote, urlparse

from bted_pipeline.materialize import (
    MATERIALIZATION_SCHEMA_VERSION,
    TABLE_ORDER,
    _accession_namespace,
    _accession_url,
    _atomic_write_bundle,
    _mime_type,
)


RELEASE_VERSION = "v0.4.0"
CASCINO_REFERENCE_ALIAS = ("GCF_000012525.1", "CP000100.1", "NC_007604.1")
CASCINO_REFERENCE_SHA256 = "5fb438ec6391898e01a7774c114b37d7852c64cd115de2c1628cefecb6d5f4a6"
METADATA_COLUMNS = {
    "source_id", "pmid", "species", "assembly", "title", "assay", "record_count",
    "evidence_class", "release_status", "article_license", "redistribution_status",
    "raw_data_accessions", "known_limitations", "study_gff3", "gene_associations",
    "condition_observations",
}
ENDPOINT_COLUMNS = (
    "end_id", "source_id", "sample_id", "assay", "evidence_class",
    "author_endpoint_id", "published_reference_accession", "reference_assembly",
    "reference_name", "replicon_label", "biological_coordinate_1based",
    "bed_start_0based", "bed_end_0based", "strand", "signal_or_score",
    "author_category", "associated_gene_or_locus", "pmid", "doi",
    "source_table_or_file", "coordinate_interpretation", "original_row_reference",
    "qc_status", "note",
)
GFF_ROW_ATTRIBUTES = (
    "author_endpoint_id", "published_reference_accession", "replicon_label",
    "signal_or_score", "author_category", "associated_gene_or_locus",
    "original_row_reference",
)
BASE_ATTRIBUTES = {"ID", *GFF_ROW_ATTRIBUTES}
DYNAMIC_ENDPOINT_FIELDS = {
    "end_id", "source_id", "reference_name", "biological_coordinate_1based",
    "bed_start_0based", "bed_end_0based", "strand", *GFF_ROW_ATTRIBUTES,
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
HF_ASSET_RE = re.compile(
    r"^https://huggingface\.co/datasets/liurulong/terminator/resolve/"
    r"([0-9a-f]{40})/(v0\.3\.0|v0\.4\.0)/(.+)$"
)
LOCAL_ASSET_RE = re.compile(r"^downloads/(v0\.3\.0|v0\.4\.0)/(.+)$")
ASSET_MANIFEST_COLUMNS = ("logical_path", "url", "byte_size", "sha256", "revision", "asset_kind")


class V04ImportError(ValueError):
    """Raised when v0.4 files cannot be imported without changing their meaning."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_relative(value: str, label: str) -> str:
    path = PurePosixPath(value)
    if (
        not value or "\\" in value or path.is_absolute() or ".." in path.parts
        or "." in path.parts or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise V04ImportError(f"unsafe {label} path: {value!r}")
    return path.as_posix()


def _read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
                raise V04ImportError(f"missing or duplicate TSV columns: {path}")
            rows = []
            for number, row in enumerate(reader, 2):
                if None in row or any(value is None for value in row.values()):
                    raise V04ImportError(f"invalid TSV column count: {path}:{number}")
                rows.append({str(key): str(value) for key, value in row.items()})
            return list(reader.fieldnames), rows
    except OSError as exc:
        raise V04ImportError(f"cannot read TSV: {path}") from exc


def _parse_checksum_file(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            digest, name = raw.split("  ", 1)
        except ValueError as exc:
            raise V04ImportError(f"malformed checksum entry: {path}:{number}") from exc
        name = _safe_relative(name, "checksum")
        if not SHA256_RE.fullmatch(digest) or name in result:
            raise V04ImportError(f"invalid or duplicate checksum entry: {path}:{number}")
        result[name] = digest
    return result


def _validate_release(release_root: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    manifest_path = release_root / "release.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise V04ImportError(f"cannot read v0.4.0 release manifest: {manifest_path}") from exc
    if not isinstance(manifest, dict) or manifest.get("release_version") != RELEASE_VERSION:
        raise V04ImportError("release.json must identify v0.4.0")
    if not isinstance(manifest.get("summary"), str) or not manifest["summary"].strip():
        raise V04ImportError("release.json is missing a readable summary")
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise V04ImportError("release.json files must be a non-empty array")
    file_index: dict[str, dict[str, Any]] = {}
    ordered_paths: list[str] = []
    for entry in raw_files:
        if not isinstance(entry, dict):
            raise V04ImportError("release.json contains a non-object file entry")
        path = _safe_relative(str(entry.get("path", "")), "release file")
        if path.lower().endswith(".json") or path.lower().endswith(".jsonl"):
            raise V04ImportError(f"public release payload must not contain raw JSON files: {path}")
        size = entry.get("byte_size")
        digest = str(entry.get("sha256", ""))
        if path in file_index or isinstance(size, bool) or not isinstance(size, int) or size < 0 or not SHA256_RE.fullmatch(digest):
            raise V04ImportError(f"invalid or duplicate release file metadata: {path}")
        target = release_root / Path(*PurePosixPath(path).parts)
        if target.is_symlink() or not target.is_file():
            raise V04ImportError(f"release file is missing or symlinked: {path}")
        if target.stat().st_size != size or _sha256(target) != digest:
            raise V04ImportError(f"release file size/SHA-256 mismatch: {path}")
        file_index[path] = dict(entry)
        ordered_paths.append(path)
    if ordered_paths != sorted(ordered_paths):
        raise V04ImportError("release.json files must be sorted by path")

    sums_path = release_root / "SHA256SUMS.txt"
    sums = _parse_checksum_file(sums_path)
    if set(sums) not in (set(file_index), set(file_index) | {"release.json"}):
        raise V04ImportError("SHA256SUMS.txt file set does not match the release payload")
    for path, expected in sums.items():
        if path == "release.json":
            actual = _sha256(manifest_path)
        else:
            actual = _sha256(release_root / Path(*PurePosixPath(path).parts))
        if actual != expected:
            raise V04ImportError(f"SHA256SUMS.txt mismatch: {path}")
    counts = manifest.get("counts")
    if not isinstance(counts, dict):
        raise V04ImportError("release.json counts must be an object")
    return manifest, file_index


def _source_provenance(path: Path) -> tuple[dict[str, dict[str, Any]], str]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise V04ImportError(f"cannot read internal source provenance: {path}") from exc
    if not isinstance(document, dict) or not isinstance(document.get("sources"), list):
        raise V04ImportError("source_provenance.json must contain a sources array")
    source_index: dict[str, dict[str, Any]] = {}
    for source in document["sources"]:
        if not isinstance(source, dict):
            raise V04ImportError("source provenance has a non-object source")
        source_id = str(source.get("source_id", ""))
        if not source_id or source_id in source_index:
            raise V04ImportError(f"missing or duplicate source provenance ID: {source_id!r}")
        source_index[source_id] = source
    sums_path = path.parent / "SHA256SUMS.txt"
    sums = _parse_checksum_file(sums_path)
    if sums != {path.name: _sha256(path)}:
        raise V04ImportError("internal source provenance checksum sidecar mismatch")
    return source_index, _sha256(path)


def _asset_manifest(
    path: Path,
    release_root: Path,
    release_files: dict[str, dict[str, Any]],
    *,
    origin_verified: bool,
) -> tuple[list[dict[str, Any]], str, str, str]:
    columns, rows = _read_tsv(path)
    if tuple(columns) != ASSET_MANIFEST_COLUMNS:
        raise V04ImportError(f"asset manifest columns must be {','.join(ASSET_MANIFEST_COLUMNS)}")
    assets: list[dict[str, Any]] = []
    by_path: dict[str, dict[str, Any]] = {}
    v04_base: str | None = None
    has_local = False
    for number, row in enumerate(rows, 2):
        logical_path = _safe_relative(row["logical_path"], f"asset manifest line {number}")
        url = row["url"]
        kind = row["asset_kind"].strip()
        try:
            size = int(row["byte_size"])
        except ValueError as exc:
            raise V04ImportError(f"invalid byte_size on asset manifest line {number}") from exc
        digest = row["sha256"].strip()
        if logical_path in by_path or size < 0 or not SHA256_RE.fullmatch(digest):
            raise V04ImportError(f"invalid/duplicate asset manifest entry at line {number}")
        if kind not in {"fasta", "fai", "gff3", "tbi", "bigwig", "bed", "config", "metadata", "tsv", "checksum", "archive", "json"}:
            raise V04ImportError(f"unsupported asset kind at line {number}: {kind}")
        remote = HF_ASSET_RE.fullmatch(url)
        local = LOCAL_ASSET_RE.fullmatch(url)
        if remote:
            revision, version, encoded_path = remote.groups()
            try:
                decoded_path = unquote(encoded_path, errors="strict")
            except UnicodeError as exc:
                raise V04ImportError(f"invalid remote path at asset line {number}") from exc
            if decoded_path != logical_path or row["revision"] != revision:
                raise V04ImportError(f"asset URL/revision mismatch at line {number}")
            if version == RELEASE_VERSION:
                v04_base = f"https://huggingface.co/datasets/liurulong/terminator/resolve/{revision}/{RELEASE_VERSION}"
        elif local:
            version, encoded_path = local.groups()
            try:
                decoded_path = unquote(encoded_path, errors="strict")
            except UnicodeError as exc:
                raise V04ImportError(f"invalid local path at asset line {number}") from exc
            if decoded_path != logical_path or row["revision"] not in {"", "local"}:
                raise V04ImportError(f"local asset URL/revision mismatch at line {number}")
            has_local = True
        else:
            raise V04ImportError(f"asset URL is not a pinned BTED object at line {number}")
        if version == RELEASE_VERSION:
            expected = release_files.get(logical_path)
            if logical_path == "SHA256SUMS.txt":
                checksum_file = release_root / logical_path
                expected_size = checksum_file.stat().st_size
                expected_sha = _sha256(checksum_file)
            elif logical_path == "release.json":
                release_manifest_path = release_root / logical_path
                expected_size = release_manifest_path.stat().st_size
                expected_sha = _sha256(release_manifest_path)
            elif expected is not None:
                expected_size = expected["byte_size"]
                expected_sha = expected["sha256"]
            elif logical_path.startswith(("browser/", "tracks/")):
                expected_size, expected_sha = size, digest
            else:
                raise V04ImportError(f"unrecognized v0.4.0 asset path: {logical_path}")
            if size != expected_size or digest != expected_sha:
                raise V04ImportError(f"v0.4.0 asset does not match canonical release file: {logical_path}")
        elif version == "v0.3.0":
            parts = PurePosixPath(logical_path).parts
            shared_reference = (
                len(parts) == 4 and parts[0] == "assemblies" and parts[2] == "reference"
                and parts[3] in {"reference.fna", "reference.fna.fai", "genes.gff3.gz", "genes.gff3.gz.tbi"}
            )
            shared_signal = (
                len(parts) == 3 and parts[0] == "tracks"
                and parts[1] in {"BATTER_S1_001", "BATTER_S1_003", "BATTER_S1_004", "BATTER_S1_005"}
                and parts[2] in {"signal.forward.bw", "signal.reverse.bw"}
            )
            if not (shared_reference or shared_signal):
                raise V04ImportError(f"only immutable shared v0.3.0 reference and raw-signal assets may be reused: {logical_path}")
        item = {
            "logical_path": logical_path,
            "url": url,
            "revision": row["revision"] if row["revision"] not in {"", "local"} else None,
            "asset_kind": "metadata" if kind == "tsv" else kind,
            "byte_size": size,
            "sha256": digest,
        }
        by_path[logical_path] = item
        # release.json is machine metadata only. Keep it in the URL allowlist
        # used by Pages, but never expose it through the D1 asset proxy.
        if logical_path != "release.json":
            assets.append(item)
    missing_release_assets = sorted(set(release_files) - set(by_path))
    if missing_release_assets:
        raise V04ImportError(f"asset manifest omits public release files: {missing_release_assets[:5]}")
    if not assets:
        raise V04ImportError("asset manifest has no assets")
    if origin_verified and (has_local or v04_base is None):
        raise V04ImportError("verified D1 bundle requires every asset to use a fixed Hugging Face URL")
    if v04_base is None:
        v04_base = "https://huggingface.co/datasets/liurulong/terminator"
    parsed = urlparse(v04_base)
    return assets, v04_base, parsed.hostname or "huggingface.co", "verified" if origin_verified else "planned_not_verified"


def _read_contigs(repo_root: Path, additional_tsv: Path | None = None) -> dict[tuple[str, str], dict[str, Any]]:
    rows_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    old_registry = repo_root / "data/registry/reference_contigs.v0.2.0.json"
    if old_registry.is_file():
        try:
            document = json.loads(old_registry.read_text(encoding="utf-8"))
            rows = document["rows"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise V04ImportError(f"cannot read existing contig registry: {old_registry}") from exc
        for row in rows:
            key = (str(row.get("assembly_accession", "")), str(row.get("contig_accession", "")))
            if not all(key):
                raise V04ImportError("existing contig registry contains an invalid row")
            rows_by_key[key] = {
                "assembly_accession": key[0], "contig_accession": key[1],
                "contig_name": key[1], "length_bp": int(row["length_bp"]),
                "sequence_sha256": None, "provenance_json": dict(row),
            }
    extra = additional_tsv or repo_root / "data/registry/browser_refs/contigs.tsv"
    if extra.is_file():
        columns, rows = _read_tsv(extra)
        required = {"assembly_accession", "contig_accession", "length_bp", "sequence_sha256"}
        if not required.issubset(columns):
            raise V04ImportError(f"browser contig registry must contain {sorted(required)}")
        for row in rows:
            key = (row["assembly_accession"].strip(), row["contig_accession"].strip())
            digest = row["sequence_sha256"].strip()
            try:
                length = int(row["length_bp"])
            except ValueError as exc:
                raise V04ImportError(f"invalid reference length for {key}") from exc
            if not all(key) or length < 1 or not SHA256_RE.fullmatch(digest):
                raise V04ImportError(f"invalid verified browser contig row: {key}")
            value = {
                "assembly_accession": key[0], "contig_accession": key[1],
                "contig_name": key[1], "length_bp": length,
                "sequence_sha256": digest, "provenance_json": {"source": extra.name, **row},
            }
            previous = rows_by_key.get(key)
            if previous and (previous["length_bp"] != length or previous.get("sequence_sha256") not in (None, digest)):
                raise V04ImportError(f"reference contig registry conflict: {key}")
            rows_by_key[key] = value
    if not rows_by_key:
        raise V04ImportError("no verified contig registry rows are available")
    return rows_by_key


def _parse_gff_attributes(value: str, label: str) -> dict[str, str]:
    if value == ".":
        return {}
    result: dict[str, str] = {}
    for item in value.split(";"):
        if not item or "=" not in item:
            raise V04ImportError(f"{label}: malformed GFF3 attribute {item!r}")
        key, encoded = item.split("=", 1)
        if not key or key in result or re.search(r"%(?![0-9A-Fa-f]{2})", encoded):
            raise V04ImportError(f"{label}: invalid/duplicate GFF3 attribute key {key!r}")
        result[key] = unquote(encoded, encoding="utf-8", errors="strict")
    return result


def _read_metadata(release_root: Path, release_files: dict[str, dict[str, Any]]) -> tuple[list[dict[str, str]], dict[str, Path], dict[str, str]]:
    genome_root = release_root / "genomes"
    if not genome_root.is_dir() or genome_root.is_symlink():
        raise V04ImportError("v0.4.0 genomes directory is missing or symlinked")
    sources: list[dict[str, str]] = []
    source_metadata_paths: dict[str, Path] = {}
    source_sha: dict[str, str] = {}
    for genome_dir in sorted(genome_root.iterdir()):
        if genome_dir.is_symlink() or not genome_dir.is_dir() or not genome_dir.name.startswith("GCF_"):
            raise V04ImportError(f"invalid genome directory: {genome_dir}")
        metadata_path = genome_dir / "metadata.tsv"
        relative_metadata = f"genomes/{genome_dir.name}/metadata.tsv"
        if relative_metadata not in release_files:
            raise V04ImportError(f"genome metadata is not listed in release.json: {relative_metadata}")
        columns, rows = _read_tsv(metadata_path)
        if not METADATA_COLUMNS.issubset(columns):
            raise V04ImportError(f"metadata.tsv is missing required columns: {metadata_path}")
        file_sha = _sha256(metadata_path)
        for row in rows:
            source_id = row["source_id"].strip()
            if not source_id or source_id in source_metadata_paths:
                raise V04ImportError(f"missing or duplicate public source ID: {source_id!r}")
            if row["assembly"].strip() != genome_dir.name:
                raise V04ImportError(f"metadata assembly does not match folder for {source_id}")
            if not row["pmid"].strip() or not row["species"].strip() or not row["title"].strip():
                raise V04ImportError(f"required source metadata is empty for {source_id}")
            try:
                record_count = int(row["record_count"])
            except ValueError as exc:
                raise V04ImportError(f"invalid record_count for {source_id}") from exc
            if record_count < 0:
                raise V04ImportError(f"negative record_count for {source_id}")
            row = {key: value.strip() for key, value in row.items()}
            row["record_count"] = str(record_count)
            sources.append(row)
            source_metadata_paths[source_id] = metadata_path
            source_sha[source_id] = file_sha
    if not sources:
        raise V04ImportError("v0.4.0 has no genome metadata rows")
    return sources, source_metadata_paths, source_sha


def _validate_supplementary_tables(
    release_root: Path,
    release_files: dict[str, dict[str, Any]],
    sources: list[dict[str, str]],
    release_counts: dict[str, Any],
) -> dict[str, int]:
    observed = {"gene_associations": 0, "unlinked_gene_associations": 0, "condition_observations": 0}
    seen_paths: set[tuple[str, str]] = set()
    for source in sources:
        for table in ("gene_associations", "condition_observations"):
            relative = _metadata_path(source["assembly"], source.get(table, ""), table)
            if not relative or (table, relative) in seen_paths:
                continue
            seen_paths.add((table, relative))
            if relative not in release_files:
                raise V04ImportError(f"metadata references an unlisted supplementary file: {relative}")
            path = release_root / Path(*PurePosixPath(relative).parts)
            try:
                with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
                    reader = csv.DictReader(handle, delimiter="\t")
                    if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
                        raise V04ImportError(f"supplementary TSV has a missing or duplicate header: {relative}")
                    if table == "gene_associations" and not {"link_status", "end_id"}.issubset(reader.fieldnames):
                        raise V04ImportError(f"gene association TSV lacks link status/endpoint fields: {relative}")
                    count = 0
                    for number, row in enumerate(reader, 2):
                        if None in row or any(value is None for value in row.values()):
                            raise V04ImportError(f"invalid supplementary TSV row: {relative}:{number}")
                        count += 1
                        if table == "gene_associations" and str(row.get("link_status", "")).strip().lower().startswith("unlinked"):
                            observed["unlinked_gene_associations"] += 1
                    observed[table] += count
            except (OSError, EOFError, UnicodeError) as exc:
                raise V04ImportError(f"cannot read supplementary TSV: {relative}") from exc
    for key in ("gene_association_count", "unlinked_gene_association_count", "condition_observation_count"):
        if key in release_counts and int(release_counts[key]) != observed[
            "unlinked_gene_associations" if key == "unlinked_gene_association_count" else key.removesuffix("_count") + "s"
        ]:
            raise V04ImportError(f"release {key} does not match supplementary TSV rows")
    return observed


def _source_manifest_fields(source: dict[str, Any]) -> dict[str, Any]:
    for key in ("registry_manifest", "source_manifest"):
        value = source.get(key)
        if isinstance(value, dict):
            return value
    return source


def _metadata_path(genome: str, relative_value: str, label: str) -> str | None:
    value = relative_value.strip()
    if not value:
        return None
    relative = _safe_relative(value, label)
    return f"genomes/{genome}/{relative}"


def _endpoint_rows(
    release_root: Path,
    sources: list[dict[str, str]],
    source_provenance: dict[str, dict[str, Any]],
    contigs: dict[tuple[str, str], dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    source_by_id = {row["source_id"]: row for row in sources}
    counts: dict[str, int] = defaultdict(int)
    samples_by_source: dict[str, set[str]] = defaultdict(set)
    endpoints: list[dict[str, Any]] = []
    seen_ids: set[tuple[str, str]] = set()
    for source in sources:
        if source["source_id"] not in source_provenance:
            raise V04ImportError(f"internal provenance is missing public source {source['source_id']}")
    for genome_dir in sorted((release_root / "genomes").iterdir()):
        for row in (source for source in sources if source["assembly"] == genome_dir.name):
            if row["release_status"] != "published_standardized" or int(row["record_count"]) == 0:
                continue
            relative_gff = _metadata_path(genome_dir.name, row.get("study_gff3", ""), "study GFF3")
            if not relative_gff:
                raise V04ImportError(f"published source {row['source_id']} has no study_gff3 path")
            gff_path = release_root / Path(*PurePosixPath(relative_gff).parts)
            if not gff_path.is_file() or gff_path.is_symlink():
                raise V04ImportError(f"study GFF3 is missing or symlinked: {relative_gff}")
            metadata = source_provenance[row["source_id"]]
            defaults = metadata.get("table_defaults", {}).get("endpoints")
            expected_defaults = set(ENDPOINT_COLUMNS) - DYNAMIC_ENDPOINT_FIELDS
            if not isinstance(defaults, dict) or set(defaults) != expected_defaults:
                missing = sorted(expected_defaults - set(defaults or {}))
                extra = sorted(set(defaults or {}) - expected_defaults)
                raise V04ImportError(f"invalid endpoint defaults for {row['source_id']}: missing={missing}, extra={extra}")
            if set(defaults).intersection(BASE_ATTRIBUTES):
                raise V04ImportError(f"endpoint defaults overlap GFF3 attributes for {row['source_id']}")
            annotation_map = metadata.get("annotation_field_map", {})
            expected_annotations = set()
            if isinstance(annotation_map, dict):
                for value in annotation_map.values():
                    if isinstance(value, dict) and value.get("from") == "attribute" and isinstance(value.get("attribute"), str):
                        expected_annotations.add(value["attribute"])
            source_count = 0
            try:
                handle = gzip.open(gff_path, "rt", encoding="utf-8", newline="")
                with handle:
                    for number, raw_line in enumerate(handle, 1):
                        line = raw_line.rstrip("\r\n")
                        if number == 1:
                            if line != "##gff-version 3":
                                raise V04ImportError(f"{relative_gff}: missing GFF3 version header")
                            continue
                        if not line or line.startswith("#"):
                            continue
                        fields = line.split("\t")
                        label = f"{relative_gff}:{number}"
                        if len(fields) != 9:
                            raise V04ImportError(f"{label}: expected 9 GFF3 columns")
                        seqid, source_id, feature, start_raw, end_raw, score, strand, phase, raw_attrs = fields
                        try:
                            seqid = unquote(seqid, encoding="utf-8", errors="strict")
                            source_id = unquote(source_id, encoding="utf-8", errors="strict")
                            start, end = int(start_raw), int(end_raw)
                        except (UnicodeError, ValueError) as exc:
                            raise V04ImportError(f"{label}: invalid source, seqid, or coordinate") from exc
                        if source_id not in source_by_id or source_by_id[source_id]["assembly"] != genome_dir.name:
                            raise V04ImportError(f"{label}: source does not belong to this assembly")
                        if source_id != row["source_id"]:
                            # Files are per study and can contain multiple source IDs from one PMID.
                            if source_by_id[source_id]["pmid"] != row["pmid"]:
                                raise V04ImportError(f"{label}: source PMID differs from study directory metadata")
                            continue
                        if feature != "terminator_endpoint" or score != "." or phase != "." or start < 1 or start != end or str(start) != start_raw or strand not in {"+", "-", ".", "?"}:
                            raise V04ImportError(f"{label}: invalid endpoint feature/coordinates")
                        resolved_seqid = seqid
                        if (genome_dir.name, seqid) == CASCINO_REFERENCE_ALIAS[:2]:
                            resolved_seqid = CASCINO_REFERENCE_ALIAS[2]
                        key = (source_id, resolved_seqid)
                        contig = contigs.get((genome_dir.name, resolved_seqid))
                        if contig is None:
                            raise V04ImportError(f"{label}: reference contig has no verified length: {genome_dir.name}/{seqid}")
                        if resolved_seqid != seqid and contig.get("sequence_sha256") != CASCINO_REFERENCE_SHA256:
                            raise V04ImportError(f"{label}: Cascino reference alias lacks verified sequence identity")
                        if start > int(contig["length_bp"]):
                            raise V04ImportError(f"{label}: endpoint coordinate exceeds verified contig length")
                        attributes = _parse_gff_attributes(raw_attrs, label)
                        if not BASE_ATTRIBUTES.issubset(attributes):
                            raise V04ImportError(f"{label}: required endpoint attributes are missing")
                        if resolved_seqid != seqid and attributes["published_reference_accession"] != seqid:
                            raise V04ImportError(f"{label}: original Cascino reference accession was not preserved")
                        extras = set(attributes) - BASE_ATTRIBUTES
                        if any(not name.startswith("ann_") for name in extras) or not extras.issubset(expected_annotations):
                            raise V04ImportError(f"{label}: unknown endpoint annotation attributes: {sorted(extras - expected_annotations)}")
                        end_id = attributes["ID"]
                        endpoint_key = (source_id, end_id)
                        if not end_id or endpoint_key in seen_ids:
                            raise V04ImportError(f"{label}: missing or duplicate endpoint ID")
                        seen_ids.add(endpoint_key)
                        endpoint = dict(defaults)
                        endpoint.update({
                            "end_id": end_id,
                            "source_id": source_id,
                            "reference_assembly": genome_dir.name,
                            "reference_name": resolved_seqid,
                            "biological_coordinate_1based": str(start),
                            "bed_start_0based": str(start - 1),
                            "bed_end_0based": str(end),
                            "strand": strand,
                            **{name: attributes[name] for name in GFF_ROW_ATTRIBUTES},
                        })
                        if set(endpoint) != set(ENDPOINT_COLUMNS):
                            raise V04ImportError(f"{label}: reconstructed endpoint columns differ from the D1 schema")
                        source_assay = str(_source_manifest_fields(metadata).get("assay_family", defaults["assay"]))
                        if endpoint["pmid"] != row["pmid"] or row["assay"] not in {endpoint["assay"], source_assay}:
                            raise V04ImportError(f"{label}: reconstructed PMID/assay differs from metadata.tsv")
                        if endpoint["evidence_class"] != row["evidence_class"]:
                            raise V04ImportError(f"{label}: evidence class differs from metadata.tsv")
                        try:
                            position = int(endpoint["biological_coordinate_1based"])
                            bed_start, bed_end = int(endpoint["bed_start_0based"]), int(endpoint["bed_end_0based"])
                        except ValueError as exc:
                            raise V04ImportError(f"{label}: non-integer endpoint coordinates") from exc
                        if bed_start != position - 1 or bed_end != position:
                            raise V04ImportError(f"{label}: invalid BED coordinate conversion")
                        endpoint.update({
                            "release_version": RELEASE_VERSION,
                            "source_id_ref": source_id,
                            "contig_id_ref": {"assembly_accession": genome_dir.name, "contig_accession": resolved_seqid},
                            "sample_id_ref": {"source_id": source_id, "sample_id": endpoint["sample_id"]},
                            "source_pk_ref": source_id,
                        })
                        if endpoint["sample_id"]:
                            samples_by_source[source_id].add(endpoint["sample_id"])
                        endpoints.append(endpoint)
                        counts[source_id] += 1
                        source_count += 1
            except (OSError, EOFError, UnicodeError) as exc:
                raise V04ImportError(f"cannot read study GFF3: {relative_gff}") from exc
            if source_count != int(row["record_count"]):
                raise V04ImportError(f"GFF3 count differs for {row['source_id']}: {source_count} != {row['record_count']}")
    for source in sources:
        if source["release_status"] == "published_standardized" and counts[source["source_id"]] != int(source["record_count"]):
            raise V04ImportError(f"release endpoint count differs for {source['source_id']}")
    return endpoints, samples_by_source


def _source_accessions(raw: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ordinal, value in enumerate((part.strip() for part in raw.split(";")), 1):
        if not value or value in seen:
            continue
        namespace, _alias = _accession_namespace(value)
        result.append({
            "accession_namespace": namespace, "accession": value, "raw_value": value,
            "accession_type": "study", "ordinal": ordinal, "external_url": _accession_url(namespace, value),
        })
        seen.add(value)
    return result


def _make_bundle_tables(
    release_root: Path,
    release_doc: dict[str, Any],
    release_files: dict[str, dict[str, Any]],
    sources: list[dict[str, str]],
    source_paths: dict[str, Path],
    source_file_shas: dict[str, str],
    source_provenance: dict[str, dict[str, Any]],
    source_provenance_sha: str,
    asset_rows: list[dict[str, Any]],
    contig_registry: dict[tuple[str, str], dict[str, Any]],
    origin_status: str,
    citations: dict[str, dict[str, str]],
) -> dict[str, list[dict[str, Any]]]:
    endpoints, samples_by_source = _endpoint_rows(release_root, sources, source_provenance, contig_registry)
    release_sha = _sha256(release_root / "release.json")
    assets: list[dict[str, Any]] = []
    asset_id_by_path: dict[str, str] = {}
    source_by_id = {row["source_id"]: row for row in sources}
    sources_by_assembly: dict[str, list[dict[str, str]]] = defaultdict(list)
    for source in sources:
        sources_by_assembly[source["assembly"]].append(source)
    for item in sorted(asset_rows, key=lambda value: value["logical_path"]):
        path = item["logical_path"]
        parts = PurePosixPath(path).parts
        assembly: str | None = None
        source_id: str | None = None
        if len(parts) >= 2 and parts[0] == "genomes":
            assembly = parts[1]
            if assembly not in sources_by_assembly:
                raise V04ImportError(f"asset references assembly absent from metadata.tsv: {path}")
        elif len(parts) >= 2 and parts[0] in {"assemblies", "browser"}:
            assembly = parts[1]
            if assembly not in sources_by_assembly:
                raise V04ImportError(f"browser asset references assembly absent from metadata.tsv: {path}")
        elif len(parts) == 3 and parts[0] == "tracks":
            candidate = parts[1]
            if candidate not in source_by_id or parts[2] not in {"endpoints.gff3", "signal.forward.bw", "signal.reverse.bw"}:
                raise V04ImportError(f"source-specific browser asset has an invalid path: {path}")
            source_id = candidate
            assembly = source_by_id[candidate]["assembly"]
        elif path in {"SHA256SUMS.txt", "release.json"}:
            pass
        else:
            raise V04ImportError(f"asset path is not a genome, source track, or shared browser object: {path}")
        asset_id = f"v0.4.0--{hashlib.sha256(path.encode('utf-8')).hexdigest()}"
        asset_id_by_path[path] = asset_id
        mime = _mime_type(path, item["asset_kind"])
        origin_host = urlparse(item["url"]).hostname or "huggingface.co"
        redistribution = "verified_redistributable" if item["url"].startswith("https://") else "planned_not_verified"
        assets.append({
            "asset_id": asset_id,
            "release_version": RELEASE_VERSION,
            "source_id_ref": source_id,
            "assembly_id_ref": assembly,
            "asset_kind": item["asset_kind"],
            "logical_path": path,
            "origin_url": item["url"],
            "origin_host": origin_host,
            "byte_size": item["byte_size"],
            "sha256": item["sha256"],
            "mime_type": mime,
            "supports_range": origin_status == "verified",
            "redistribution_status": redistribution,
            "is_public": True,
        })

    publication_by_pmid: dict[str, dict[str, Any]] = {}
    for row in sources:
        internal = source_provenance[row["source_id"]]
        paper = _source_manifest_fields(internal)
        pmid = row["pmid"]
        citation = citations.get(pmid)
        if citation is None:
            raise V04ImportError(f"verified PubMed citation is missing for PMID {pmid}")
        raw_doi = str(paper.get("doi") or row.get("doi") or "")
        if raw_doi and raw_doi.casefold() != citation["doi"].casefold():
            raise V04ImportError(f"verified PubMed DOI differs for PMID {pmid}")
        title = row["title"]
        candidate = {
            "pmid": pmid,
            "doi": paper.get("doi") or row.get("doi") or None,
            "pmc": paper.get("pmc") or row.get("pmc") or None,
            "published_year": int(citation["year"]),
            "journal": citation["journal"],
            "paper_title": title,
            "citation_json": {
                "pmid": pmid,
                "doi": citation["doi"],
                "pmc": paper.get("pmc") or row.get("pmc") or "",
                "published_year": int(citation["year"]),
                "journal": citation["journal"],
                "paper_title": citation["title"],
                "authors": citation["authors"],
                "pubmed_url": citation["pubmed_url"],
            },
        }
        previous = publication_by_pmid.get(pmid)
        if previous and any(previous.get(key) != candidate.get(key) for key in ("doi", "pmc", "published_year", "paper_title")):
            raise V04ImportError(f"publication metadata conflicts for PMID {pmid}")
        publication_by_pmid[pmid] = candidate

    assembly_members: dict[str, list[dict[str, str]]] = defaultdict(list)
    for source in sources:
        assembly_members[source["assembly"]].append(source)
    assemblies: list[dict[str, Any]] = []
    for accession, members in sorted(assembly_members.items()):
        species = {row["species"] for row in members}
        if len(species) != 1:
            raise V04ImportError(f"shared assembly has conflicting species metadata: {accession}")
        internals = [_source_manifest_fields(source_provenance[row["source_id"]]) for row in members]
        strains = {str(value.get("strain", "")).strip() for value in internals if value.get("strain")}
        assembly_names = {str(value.get("assembly_name", "")).strip() for value in internals if value.get("assembly_name")}
        organisms = {str(value.get("organism_name", "")).strip() for value in internals if value.get("organism_name")}
        taxon_ids = {str(value.get("taxon_id", "")).strip() for value in internals if value.get("taxon_id")}
        if any(len(values) > 1 for values in (strains, assembly_names, organisms, taxon_ids)):
            raise V04ImportError(f"shared assembly metadata conflict: {accession}")
        assemblies.append({
            "assembly_accession": accession,
            "assembly_name": next(iter(assembly_names), accession),
            "organism_name": next(iter(organisms), next(iter(species))),
            "strain": next(iter(strains), None),
            "taxon_id": next(iter(taxon_ids), None),
            "reference_url": f"https://www.ncbi.nlm.nih.gov/datasets/genome/{accession}/",
            "source_ids": sorted(row["source_id"] for row in members),
        })

    endpoint_keys = {(row["reference_assembly"], row["reference_name"]) for row in endpoints}
    contigs: list[dict[str, Any]] = []
    for assembly, contig_name in sorted(endpoint_keys):
        reference = contig_registry.get((assembly, contig_name))
        if reference is None:
            raise V04ImportError(f"no verified contig length for {assembly}/{contig_name}")
        contigs.append({
            "assembly_id_ref": assembly,
            "assembly_accession": assembly,
            "contig_accession": contig_name,
            "contig_name": reference["contig_name"],
            "length_bp": reference["length_bp"],
            "sequence_sha256": reference.get("sequence_sha256"),
            "provenance_json": reference.get("provenance_json"),
        })

    source_rows: list[dict[str, Any]] = []
    source_accessions: list[dict[str, Any]] = []
    for row in sources:
        source_id, assembly = row["source_id"], row["assembly"]
        internal = source_provenance[source_id]
        manifest = _source_manifest_fields(internal)
        registry_row = internal.get("registry_row") or {}
        publication = internal.get("publication_status") or {}
        facts = internal.get("release_facts") or {}
        gff_path = _metadata_path(assembly, row.get("study_gff3", ""), "study GFF3")
        source_count = int(row["record_count"])
        release_status = row["release_status"]
        evidence_class = row["evidence_class"]
        redistribution = row["redistribution_status"] or "verified_redistributable"
        if release_status == "published_standardized" and evidence_class not in {
            "observed_signal", "called_endpoint", "author_called_endpoint", "curated_record"
        }:
            raise V04ImportError(f"public source has unsupported endpoint evidence class: {source_id}")
        if release_status not in {"published_standardized", "audit_only", "to_review", "blocked"}:
            raise V04ImportError(f"unsupported release status for {source_id}: {release_status}")
        has_fasta = any(asset["logical_path"] in {
            f"assemblies/{assembly}/reference/reference.fna", f"browser/{assembly}/reference.fna"
        } for asset in asset_rows)
        has_fai = any(asset["logical_path"] in {
            f"assemblies/{assembly}/reference/reference.fna.fai", f"browser/{assembly}/reference.fna.fai"
        } for asset in asset_rows)
        has_jbrowse = bool(gff_path and source_count and has_fasta and has_fai)
        source_rows.append({
            "release_version": RELEASE_VERSION,
            "source_id": source_id,
            "publication_id_ref": row["pmid"],
            "assembly_id_ref": assembly,
            "species": row["species"],
            "phylum": manifest.get("phylum") or None,
            "assay_family": row["assay"],
            "article_license": row["article_license"],
            "release_status": release_status,
            "evidence_class": evidence_class or "NA",
            "redistribution_status": redistribution,
            "accessibility_status": manifest.get("accessibility_status", ""),
            "coordinate_status": manifest.get("coordinate_status", ""),
            "processing_status": manifest.get("processing_status", ""),
            "used_for_batter_augmentation": str(registry_row.get("used_for_batter_augmentation", "")).upper() == "TRUE",
            "record_count": source_count,
            "has_jbrowse": has_jbrowse,
            "manifest_path": f"genomes/{assembly}/metadata.tsv#source={source_id}",
            "manifest_sha256": source_file_shas[source_id],
            "record_root": gff_path,
            "source_note": manifest.get("blocker_or_note") or facts.get("source_note") or None,
            "decision_note": manifest.get("decision_note") or facts.get("decision_note") or None,
            "known_limitations": row.get("known_limitations") or facts.get("known_limitations") or None,
            "metadata_json": dict(row),
        })
        for accession in _source_accessions(row.get("raw_data_accessions", "")):
            source_accessions.append({"source_id_ref": source_id, **accession})

    samples = [
        {
            "source_id_ref": source_id, "sample_id": sample_id, "sample_label": None,
            "biological_condition": None, "replicate_label": None,
            "sample_accession": None, "metadata_json": {},
        }
        for source_id, values in sorted(samples_by_source.items())
        for sample_id in sorted(values)
    ]
    for endpoint in endpoints:
        endpoint.setdefault("release_version", RELEASE_VERSION)
    tables: dict[str, list[dict[str, Any]]] = {
        "release_versions": [{
            "release_version": RELEASE_VERSION,
            "release_date": release_doc.get("release_date"),
            "canonical_manifest_path": "data/public/v0.4.0/release.json",
            "canonical_manifest_sha256": release_sha,
            "status": "validated", "is_current": True,
        }],
        "import_runs": [{
            "release_version": RELEASE_VERSION, "importer_name": "bted-v04-d1-import",
            "importer_version": "bted-materializer-0.4.0", "input_manifest_path": "data/public/v0.4.0/release.json",
            "input_manifest_sha256": release_sha, "staging_location": "deterministic-v0.4.0-bundle",
            "run_status": "validated", "started_at": None, "finished_at": None,
            "validation_summary": {"canonical_validation_status": "validated", "postgresql_ready": True, "write_mode": "not_written"},
            "error_summary": None,
        }],
        "publications": [publication_by_pmid[key] for key in sorted(publication_by_pmid)],
        "assemblies": assemblies,
        "contigs": contigs,
        "sources": sorted(source_rows, key=lambda item: item["source_id"]),
        "source_accessions": sorted(source_accessions, key=lambda item: (item["source_id_ref"], item["ordinal"], item["accession"])),
        "samples": samples,
        "endpoints": sorted(endpoints, key=lambda item: (item["source_id_ref"], item["end_id"])),
        "source_annotations": [],
        "genes": [],
        "endpoint_gene_context": [],
        "assets": sorted(assets, key=lambda item: item["asset_id"]),
    }
    return tables


def _generated_at(value: str | None) -> str:
    if value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise V04ImportError("generated-at-utc must include a timezone")
    else:
        parsed = datetime.now(timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def materialize_v04_d1(
    *,
    release_root: str | Path,
    source_provenance_path: str | Path,
    asset_manifest_path: str | Path,
    output_dir: str | Path,
    repo_root: str | Path,
    contig_registry_path: str | Path | None = None,
    origin_verified: bool = False,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    root = Path(release_root).expanduser().resolve()
    repo = Path(repo_root).expanduser().resolve()
    release_doc, release_files = _validate_release(root)
    provenance_path = Path(source_provenance_path).expanduser().resolve()
    source_provenance, provenance_sha = _source_provenance(provenance_path)
    source_rows, source_paths, source_shas = _read_metadata(root, release_files)
    release_counts = release_doc["counts"]
    expected_sources = release_counts.get("source_count")
    if expected_sources is not None and int(expected_sources) != len(source_rows):
        raise V04ImportError("genome metadata source count differs from release.json")
    genome_studies = {(row["assembly"], row["pmid"]) for row in source_rows}
    if "genome_count" in release_counts and int(release_counts["genome_count"]) != len({row["assembly"] for row in source_rows}):
        raise V04ImportError("genome count differs from release.json")
    if "genome_study_count" in release_counts and int(release_counts["genome_study_count"]) != len(genome_studies):
        raise V04ImportError("genome-study count differs from release.json")
    if "study_count" in release_counts and int(release_counts["study_count"]) != len({row["pmid"] for row in source_rows}):
        raise V04ImportError("unique PMID study count differs from release.json")
    supplementary_counts = _validate_supplementary_tables(root, release_files, source_rows, release_counts)
    assets, origin_base, origin_host, origin_status = _asset_manifest(
        Path(asset_manifest_path).expanduser().resolve(), root, release_files, origin_verified=origin_verified,
    )
    contigs = _read_contigs(
        repo,
        Path(contig_registry_path).expanduser().resolve() if contig_registry_path else None,
    )
    citation_path = repo / "data/registry/study_citations.v0.4.0.tsv"
    citation_columns, citation_rows = _read_tsv(citation_path)
    required_citation_columns = {"pmid", "title", "authors", "journal", "year", "doi", "pubmed_url"}
    if not required_citation_columns.issubset(citation_columns):
        raise V04ImportError("verified study citation table has missing columns")
    citations = {row["pmid"]: row for row in citation_rows}
    if len(citations) != 14 or len(citation_rows) != 14:
        raise V04ImportError("expected 14 distinct verified PubMed citations")
    tables = _make_bundle_tables(
        root, release_doc, release_files, source_rows, source_paths, source_shas,
        source_provenance, provenance_sha, assets, contigs, origin_status, citations,
    )
    release_entry = release_doc["counts"]
    expected_endpoint_count = release_entry.get("endpoint_count")
    if expected_endpoint_count is not None and int(expected_endpoint_count) != len(tables["endpoints"]):
        raise V04ImportError("reconstructed endpoint count differs from release.json")
    if len(tables["sources"]) != len(source_rows):
        raise V04ImportError("source row count changed during D1 materialization")

    release_sha = _sha256(root / "release.json")
    contig_registry_digest = hashlib.sha256()
    for path in (repo / "data/registry/reference_contigs.v0.2.0.json", Path(contig_registry_path).resolve() if contig_registry_path else repo / "data/registry/browser_refs/contigs.tsv"):
        if path.is_file():
            contig_registry_digest.update(path.read_bytes())
    manifest = {
        "materialization_schema_version": MATERIALIZATION_SCHEMA_VERSION,
        "materializer_version": "bted-materializer-0.4.0",
        "release_version": RELEASE_VERSION,
        "generated_at_utc": _generated_at(generated_at_utc),
        "canonical_validation_status": "validated",
        "postgresql_ready": True,
        "write_mode": "not_written",
        "canonical_manifest": {"path": "data/public/v0.4.0/release.json", "sha256": release_sha},
        "contig_registry": {
            "path": "data/registry/reference_contigs.v0.2.0.json + data/registry/browser_refs/contigs.tsv",
            "sha256": contig_registry_digest.hexdigest(),
        },
        "asset_origin": {"base": origin_base, "host": origin_host, "asset_origin_status": origin_status},
        "foreign_key_mode": "natural_key_refs",
        "unresolved": [],
        "source_count": len(tables["sources"]),
        "source_annotation_input_row_count": 0,
        "source_annotation_materialized_row_count": 0,
        "contig_count": len(tables["contigs"]),
        "gene_count": 0,
        "endpoint_gene_context_count": 0,
        "gene_import": {"enabled": False, "reason": "The Worker does not query gene association rows."},
        "annotation_field_provenance": [],
        "published_source_count": sum(row["release_status"] == "published_standardized" for row in tables["sources"]),
        "audit_only_source_ids": [row["source_id"] for row in tables["sources"] if row["release_status"] == "audit_only"],
        "v04_source_provenance": {"sha256": provenance_sha, "source_count": len(source_provenance)},
        "v04_study_citations": {"path": "data/registry/study_citations.v0.4.0.tsv", "sha256": _sha256(citation_path), "study_count": len(citations)},
        "v04_release_payload_count": len(release_files),
        "v04_supplementary_row_counts": supplementary_counts,
        "v04_browser_asset_manifest": {"path": str(Path(asset_manifest_path).name), "asset_count": len(assets)},
    }
    return _atomic_write_bundle(Path(output_dir).expanduser().resolve(), tables, manifest)
