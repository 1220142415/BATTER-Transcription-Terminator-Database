#!/usr/bin/env python3
"""Render the BTED v0.4.0 genome-first static website from release files."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import html
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Iterable
from urllib.parse import quote


RELEASE_VERSION = "v0.4.0"
TAXONOMY_REGISTRY = Path(__file__).resolve().parents[1] / "data/registry/genome_taxonomy.tsv"
TAXONOMY_RANKS = ("phylum", "class", "order", "family", "genus")
REQUIRED_METADATA_COLUMNS = (
    "source_id", "pmid", "species", "assembly", "title", "assay", "record_count",
    "evidence_class", "release_status", "article_license", "redistribution_status",
    "raw_data_accessions", "known_limitations", "study_gff3", "gene_associations",
    "condition_observations",
)
SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
ASSEMBLY_RE = re.compile(r"^GCF_[0-9]+\.[0-9]+$")
PMID_RE = re.compile(r"^[0-9]+$")
# The verified main chromosome in the NCBI v0.4 browser reference is byte-for-
# byte sequence-identical to Cascino's author reference CP000100.1. This mapping
# is used only for derived browser tracks; canonical GFF3 keeps its raw seqid.
BROWSER_SEQID_MAPS = {
    "GCF_000012525.1": {"CP000100.1": "NC_007604.1"},
}


class SiteBuildError(RuntimeError):
    """Raised when release data cannot safely produce a v0.4.0 site."""


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def safe_relative_path(raw: str, *, label: str) -> PurePosixPath:
    value = raw.strip().replace("\\", "/")
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ":" in value or ".." in path.parts or any(part in {"", "."} for part in path.parts):
        raise SiteBuildError(f"Unsafe {label} path: {raw!r}")
    return path


def release_file_path(release_root: Path, raw: str, *, label: str) -> Path:
    relative = safe_relative_path(raw, label=label)
    target = (release_root / Path(*relative.parts)).resolve()
    try:
        target.relative_to(release_root.resolve())
    except ValueError as exc:
        raise SiteBuildError(f"{label} path escapes release root: {raw!r}") from exc
    return target


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_release(release_root: Path) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    manifest_path = release_root / "release.json"
    try:
        release = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SiteBuildError(f"Could not read v0.4.0 release manifest: {manifest_path}") from exc
    if not isinstance(release, dict) or release.get("release_version") != RELEASE_VERSION:
        raise SiteBuildError("Release manifest is not BTED v0.4.0")
    files = release.get("files")
    if not isinstance(files, list):
        raise SiteBuildError("release.json must contain a files array")
    indexed: dict[str, dict[str, object]] = {}
    for row in files:
        if not isinstance(row, dict):
            raise SiteBuildError("release.json files must contain objects")
        raw_path = str(row.get("path", ""))
        relative = safe_relative_path(raw_path, label="release file").as_posix()
        if relative in indexed:
            raise SiteBuildError(f"Duplicate release file path: {relative}")
        path = release_file_path(release_root, relative, label="release file")
        if not path.is_file():
            raise SiteBuildError(f"Release file is missing: {relative}")
        try:
            expected_size = int(row["byte_size"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SiteBuildError(f"Release file has an invalid byte_size: {relative}") from exc
        expected_hash = str(row.get("sha256", "")).lower()
        if expected_size != path.stat().st_size:
            raise SiteBuildError(f"Release file size mismatch: {relative}")
        if not re.fullmatch(r"[0-9a-f]{64}", expected_hash) or sha256_file(path) != expected_hash:
            raise SiteBuildError(f"Release file SHA-256 mismatch: {relative}")
        indexed[relative] = row
    return release, indexed


def read_tsv(path: Path, required: Iterable[str] = ()) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            fields = reader.fieldnames or []
            missing = sorted(set(required) - set(fields))
            if missing:
                raise SiteBuildError(f"{path}: missing TSV columns {missing}")
            return [{str(k): (v or "") for k, v in row.items() if k is not None} for row in reader]
    except OSError as exc:
        raise SiteBuildError(f"Could not read TSV: {path}") from exc


def load_genome_taxonomy(path: Path, genomes: list[dict[str, object]]) -> dict[str, dict[str, str]]:
    taxonomy: dict[str, dict[str, str]] = {}
    for row in read_tsv(path, ("assembly", "phylum", "genus")):
        assembly = row["assembly"].strip()
        if not ASSEMBLY_RE.fullmatch(assembly) or assembly in taxonomy:
            raise SiteBuildError(f"Invalid or duplicate taxonomy assembly: {assembly!r}")
        taxonomy[assembly] = {rank: row.get(rank, "").strip() for rank in TAXONOMY_RANKS}
    missing = sorted(str(genome["assembly"]) for genome in genomes if str(genome["assembly"]) not in taxonomy)
    if missing:
        raise SiteBuildError(f"Genome taxonomy is missing assemblies: {', '.join(missing)}")
    return taxonomy


def load_genomes(release_root: Path, release: dict[str, object], files: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    manifest_genomes = release.get("genomes")
    if not isinstance(manifest_genomes, list):
        raise SiteBuildError("release.json must contain a genomes array")
    genomes: list[dict[str, object]] = []
    seen: set[str] = set()
    for manifest_genome in manifest_genomes:
        if not isinstance(manifest_genome, dict):
            raise SiteBuildError("release.json genomes must contain objects")
        assembly = str(manifest_genome.get("assembly", ""))
        if not ASSEMBLY_RE.fullmatch(assembly) or assembly in seen:
            raise SiteBuildError(f"Invalid or duplicate assembly accession: {assembly!r}")
        seen.add(assembly)
        metadata_path = str(manifest_genome.get("metadata_path", ""))
        relative_metadata = safe_relative_path(metadata_path, label="genome metadata").as_posix()
        if relative_metadata not in files:
            raise SiteBuildError(f"Genome metadata is absent from release.json files: {relative_metadata}")
        metadata_rows = read_tsv(
            release_file_path(release_root, relative_metadata, label="genome metadata"),
            REQUIRED_METADATA_COLUMNS,
        )
        if not metadata_rows:
            raise SiteBuildError(f"Genome metadata has no source rows: {relative_metadata}")
        for row in metadata_rows:
            if row["assembly"] != assembly:
                raise SiteBuildError(f"{relative_metadata}: row assembly does not match {assembly}")
            if not SOURCE_ID_RE.fullmatch(row["source_id"]):
                raise SiteBuildError(f"{relative_metadata}: invalid source_id {row['source_id']!r}")
            if not PMID_RE.fullmatch(row["pmid"]):
                raise SiteBuildError(f"{relative_metadata}: invalid PMID {row['pmid']!r}")
            try:
                row["record_count_number"] = int(row["record_count"])
            except ValueError as exc:
                raise SiteBuildError(f"{relative_metadata}: invalid record_count for {row['source_id']}") from exc
            for column in ("study_gff3", "gene_associations", "condition_observations"):
                value = row[column].strip()
                if not value:
                    continue
                genome_dir = PurePosixPath(relative_metadata).parent
                file_path = (genome_dir / safe_relative_path(value, label=column)).as_posix()
                if file_path not in files:
                    raise SiteBuildError(f"{relative_metadata}: {column} path is absent from release.json: {file_path}")
                if PurePosixPath(file_path).parts[:3] != ("genomes", assembly, "studies"):
                    raise SiteBuildError(f"{relative_metadata}: {column} must stay under this genome's studies directory")
            if is_published_status(row["release_status"]) and row["record_count_number"] > 0 and not row["study_gff3"].strip():
                raise SiteBuildError(f"{relative_metadata}: published source {row['source_id']} has no study GFF3")
        genomes.append({
            "assembly": assembly,
            "metadata_path": relative_metadata,
            "metadata_rows": metadata_rows,
            "manifest": manifest_genome,
        })
    return sorted(genomes, key=lambda item: str(item["assembly"]))


def is_published_status(value: object) -> bool:
    status = str(value or "").strip().casefold()
    return status == "published" or status.startswith("published_")


def evidence_label(value: str) -> str:
    labels = {
        "observed_signal": "Experimental signal",
        "author_called_endpoint": "Author-reported endpoint",
        "curated_record": "Literature-curated endpoint",
        "experimentally_supported_endpoint": "Experimentally supported endpoint",
        "predicted_candidate": "Predicted candidate",
    }
    return labels.get(value, value.replace("_", " ").strip().capitalize() or "Evidence not specified")


SOURCE_PAGE_CAVEATS = {
    "BATTER_S1_004": "The coordinates use CP001340.1; an unrelated GEO reference label was excluded.",
    "BATTER_S1_006": "Multiple gene rows can share one genomic position; the study rows were retained.",
    "BATTER_S1_007": "The paper does not distinguish termination from RNA processing at every site.",
    "BATTER_S1_008": "The separate gene association table is not part of the 3′ end count.",
    "BATTER_S1_009": "Prediction-only sites are excluded from the published 3′ ends.",
    "BATTER_S1_015": "This study stays separate from the later study on the same reference.",
    "BATTER_S1_016": "The paper and current NCBI assembly use different species names; the reference sequence matches.",
    "BATTER_S1_017": "This study stays separate from the earlier study on the same reference.",
    "BATTER_S1_020": "Prediction-only and mixed-evidence tables are excluded from the published 3′ ends.",
    "BATTER_S1_021": "Some condition annotations disagree; the original observations remain in the supplementary table.",
    "BATTER_S1_022": "Prediction-only sites are excluded from the published 3′ ends.",
    **{f"BTED_EXT_2026_{number}": "Only the study's defined ends are included; uncertain peaks remain under review."
       for number in (102, 103, 104)},
}


def raw_data_links(raw: str) -> str:
    links: list[str] = []
    seen: set[str] = set()
    for accession in re.split(r"[;,\s]+", raw.strip()):
        accession = accession.strip()
        if not accession or accession in seen:
            continue
        seen.add(accession)
        if re.fullmatch(r"GSE\d+", accession):
            url = f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={quote(accession)}"
        elif re.fullmatch(r"SR[APRX]\d+", accession):
            url = f"https://www.ncbi.nlm.nih.gov/sra/?term={quote(accession)}"
        elif re.fullmatch(r"PRJNA\d+", accession):
            url = f"https://www.ncbi.nlm.nih.gov/bioproject/{quote(accession)}"
        elif re.fullmatch(r"PRJEB\d+", accession):
            url = f"https://www.ebi.ac.uk/ena/browser/view/{quote(accession)}"
        else:
            continue
        links.append(f'<a href="{esc(url)}" target="_blank" rel="noopener">{esc(accession)}</a>')
    if not links:
        return '<span class="muted">No raw-data accession recorded</span>'
    return " · ".join(links)


def site_href(asset_url: str, page_depth: int) -> str:
    if asset_url.startswith(("https://", "http://", "/")):
        return esc(asset_url)
    prefix = "../" * page_depth
    return esc(prefix + asset_url.removeprefix("./"))


def get_asset_url(asset_map: dict[str, dict[str, object]], logical_path: str, *, optional: bool = False) -> str | None:
    item = asset_map.get(logical_path)
    if item is None:
        if optional:
            return None
        raise SiteBuildError(f"Asset URL is not allowlisted: {logical_path}")
    return str(item["url"])


def nav(current: str = "home", depth: int = 0) -> str:
    active_home = ' aria-current="page"' if current == "home" else ""
    active_genomes = ' aria-current="page"' if current == "genomes" else ""
    active_notes = ' aria-current="page"' if current == "notes" else ""
    active_usage = ' aria-current="page"' if current == "usage" else ""
    prefix = "../" * depth
    return f'''<header class="site-header"><div class="header-inner">
  <a class="brand" href="{prefix}index.html"><span class="brand-mark">BTED</span><span class="brand-name">Bacterial Transcript 3′ End Database</span></a>
  <nav class="site-nav" aria-label="Primary navigation"><a href="{prefix}index.html"{active_home}>Home</a><a href="{prefix}genomes.html"{active_genomes}>Genomes</a><a href="{prefix}methodology.html"{active_notes}>Data notes</a><a href="{prefix}usage.html"{active_usage}>Usage</a></nav>
</div></header>'''


def page(title: str, content: str, *, current: str = "", scripts: tuple[str, ...] = (), depth: int = 0) -> str:
    version_counts = "BTED v0.4.0 · Bacterial transcript 3′ ends"
    prefix = "../" * depth
    script_tags = "".join(f'<script src="{esc(src)}" defer></script>' for src in scripts)
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="BTED v0.4.0 genome-first bacterial transcript 3′ end data"><title>{esc(title)} · BTED</title>
<link rel="icon" href="{prefix}assets/favicon.svg" type="image/svg+xml"><link rel="stylesheet" href="{prefix}css/style.css"></head>
<body>{nav(current, depth)}{content}<footer class="site-footer"><div class="footer-inner"><span>{esc(version_counts)}</span><div class="footer-links"><a href="{prefix}usage.html">Usage</a><a href="https://github.com/1220142415/BATTER-Transcription-Terminator-Database">GitHub</a></div></div></footer>{script_tags}</body></html>
'''


def _publication_link(pmid: str) -> str:
    return f"https://pubmed.ncbi.nlm.nih.gov/{quote(pmid)}/"


def _asset_exists(asset_map: dict[str, dict[str, object]], predicate) -> bool:
    return any(predicate(path, item) for path, item in asset_map.items())


def _search_blob(assembly: str, rows: list[dict[str, str]]) -> str:
    values = [assembly]
    for row in rows:
        values.extend(row.get(key, "") for key in ("species", "title", "pmid", "source_id", "assay", "raw_data_accessions"))
    return " ".join(values).casefold()


def home_content(genomes: list[dict[str, object]]) -> str:
    rows = [row for genome in genomes for row in genome["metadata_rows"]]
    published = [row for row in rows if is_published_status(row.get("release_status"))]
    metrics = ((len(genomes), "Reference genomes"), (len({row["pmid"] for row in rows}), "Source publications"), (len(published), "Published sources"), (sum(int(row["record_count_number"]) for row in published), "3′ end records"))
    summary = "".join(f'<div><strong>{count:,}</strong><span>{label}</span></div>' for count, label in metrics)
    return f'''<main class="home-page">
<section class="hero hero-compact"><div class="page-shell hero-inner"><div class="hero-copy"><p class="eyebrow">BTED · {RELEASE_VERSION}</p><h1>Bacterial transcript<br>3′-end database</h1><p>Explore published 3′ ends, compare studies, and download data by genome.</p><div class="hero-actions"><a class="button primary" href="genomes.html">Browse genomes <span aria-hidden="true">→</span></a><a class="button" href="#batter-reference">BATTER paper</a></div></div>
<div class="hero-diagram"><svg viewBox="0 0 440 210" role="img" aria-labelledby="track-diagram-title"><title id="track-diagram-title">Schematic of a gene, experimental signal and transcript 3′ ends</title><text x="24" y="29">Reference gene</text><path class="diagram-baseline" d="M24 64H416"/><path class="diagram-gene" d="M54 52H280L297 64L280 76H54Z"/><text x="24" y="108">Experimental signal</text><path class="diagram-baseline" d="M24 151H416"/><path class="diagram-signal" d="M24 151H68V147H92V141H117V145H144V138H170V143H194V132H218V138H243V125H265V132H288V98H298V130H314V144H340V149H416"/><text x="24" y="187">Transcript 3′ ends</text><path class="diagram-endpoint" d="M293 172V202M308 178V202M329 184V202"/></svg><p>Schematic · not measured data</p></div></div></section>
<section class="page-shell home-summary" aria-label="Release statistics">{summary}</section>
<div class="page-shell home-content"><p class="home-data-note">{RELEASE_VERSION} · Source publications include review-only studies. Endpoint counts cover published sources.</p>
<section class="home-reference" id="batter-reference"><div><p class="eyebrow">Reference</p><h2>BATTER</h2><p>Paper and source code for bacterial transcription termination analysis.</p></div>
<div class="home-reference-content"><p class="home-citation">Jin, Y., Cui, J., Liu, R. et al. <a href="https://doi.org/10.1186/s40168-026-02454-1">Conserved 3′ stem-loop structures enable comprehensive analysis of bacterial transcription termination in metagenomes.</a> <em>Microbiome</em> <strong>14</strong>, 222 (2026).</p><p class="home-doi">DOI: <a href="https://doi.org/10.1186/s40168-026-02454-1">10.1186/s40168-026-02454-1</a></p>
<div class="home-reference-links"><a class="button" href="https://doi.org/10.1186/s40168-026-02454-1">Read paper ↗</a><a class="button" href="https://github.com/xu-research-lab/BATTER">BATTER code ↗</a><a class="button" href="https://github.com/1220142415/BATTER-Transcription-Terminator-Database">BTED repository ↗</a></div></div></section></div>
</main>'''


def index_content(genomes: list[dict[str, object]], asset_map: dict[str, dict[str, object]], taxonomy: dict[str, dict[str, str]]) -> str:
    count = len(genomes)
    table_rows: list[str] = []
    for genome in genomes:
        assembly = str(genome["assembly"])
        genome_taxonomy = taxonomy[assembly]
        rows = genome["metadata_rows"]
        published = [row for row in rows if is_published_status(row.get("release_status"))]
        species = next((row.get("species", "") for row in rows if row.get("species")), "")
        study_count = len({row["pmid"] for row in published})
        endpoint_count = sum(int(row["record_count_number"]) for row in published)
        source_tags = []
        signal_count = 0
        for row in rows:
            sid = row["source_id"]
            has_signal = _asset_exists(
                asset_map,
                lambda logical, _asset, source_id=sid: logical.startswith(f"tracks/{source_id}/")
                and logical.lower().endswith((".bw", ".bigwig")),
            )
            signal_count += int(has_signal)
            source_search = " ".join(row.get(key, "") for key in
                                     ("title", "pmid", "source_id", "assay", "raw_data_accessions")).casefold()
            source_tags.append(
                f'<span hidden data-source-filter data-search="{esc(source_search)}" '
                f'data-study="{esc(row["pmid"])}" data-assay="{esc(row.get("assay", ""))}" '
                f'data-published="{"yes" if is_published_status(row.get("release_status")) else "no"}" '
                f'data-evidence="{esc(row.get("evidence_class") or "audit_only")}" '
                f'data-signal="{"yes" if has_signal else "no"}"></span>'
            )
        methods = sorted({row.get("assay", "") for row in published if row.get("assay")})
        method_text = methods[0] if len(methods) == 1 else f"{methods[0]} +{len(methods) - 1}" if methods else "—"
        signal_text = f"{signal_count} source{'s' if signal_count != 1 else ''}" if signal_count else "No signal"
        genome_search = " ".join((assembly, species, *genome_taxonomy.values())).casefold()
        taxonomy_attributes = " ".join(
            f'data-taxonomy-{rank}="{esc(value)}"' for rank, value in genome_taxonomy.items()
        )
        href = f"genomes/{quote(assembly)}.html"
        table_rows.append(f'''<tr data-genome-row data-genome-search="{esc(genome_search)}"
  {taxonomy_attributes}
  data-sort-accession="{esc(assembly.casefold())}" data-sort-organism="{esc(species.casefold())}"
  data-sort-studies="{study_count}" data-sort-endpoints="{endpoint_count}" data-sort-signal="{signal_count}">
  <td data-label="Organism"><a class="genome-table-name" href="{href}">{esc(species or assembly)}</a></td>
  <td data-label="Assembly"><code>{esc(assembly)}</code></td>
  <td data-label="Phylum">{esc(genome_taxonomy['phylum'] or 'Not assigned')}</td>
  <td data-label="Studies">{study_count}</td>
  <td data-label="Methods">{esc(method_text)}</td>
  <td data-label="Endpoints" class="number">{endpoint_count:,}</td>
  <td data-label="Signal"><span class="signal-availability {'available' if signal_count else 'unavailable'}">{signal_text}</span></td>
  <td data-label="Open"><a class="row-action" href="{href}">Open genome</a>{''.join(source_tags)}</td>
</tr>''')
    content = f'''<main>
<section class="page-shell genome-results" id="genome-directory"><div class="page-heading"><div><p class="eyebrow">BTED {RELEASE_VERSION}</p><h1>Genomes</h1><p>Search by organism, assembly, or study.</p></div></div>
  <div class="genome-directory-panel"><form class="genome-filters-form" role="search" aria-label="Search and filter genomes" data-genome-search-form><div class="genome-filter-bar">
    <label class="genome-filter-search"><span>Search genomes</span><span class="genome-filter-search-field"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 5 5"/></svg><input type="search" placeholder="Assembly or species" title="Also searches study titles and PMID" autocomplete="off" data-genome-search></span></label>
    <label class="mobile-sort">Sort by<select data-sort-select><option value="accession">Assembly</option><option value="organism">Organism</option><option value="studies">Studies</option><option value="endpoints">Endpoints</option><option value="signal">Signal</option></select></label>
    <button class="mobile-sort-direction" type="button" data-sort-direction aria-label="Reverse sort direction">Ascending</button>
    <button class="genome-filter-reset" type="button" data-clear-filters aria-label="Clear filters" title="Clear filters"><span aria-hidden="true">↺</span></button>
  </div><fieldset class="genome-taxonomy-panel"><legend>Taxonomy</legend><div class="genome-taxonomy-fields">
    {''.join(f'<label>{rank.capitalize()}<select data-taxonomy-rank="{rank}"{" disabled" if rank != "phylum" else ""}><option value="">All</option></select></label>' for rank in TAXONOMY_RANKS)}
  </div></fieldset></form>
  <div class="genome-result-count" role="status"><span data-visible-count>{count}</span> of {count} genomes</div>
  <div class="genome-table-scroll"><table class="genome-directory-table"><thead><tr>
    <th aria-sort="none"><button type="button" data-sort="organism">Organism</button></th>
    <th aria-sort="ascending"><button type="button" data-sort="accession">Assembly</button></th>
    <th>Phylum</th>
    <th aria-sort="none"><button type="button" data-sort="studies">Studies</button></th>
    <th>Methods</th>
    <th aria-sort="none"><button type="button" data-sort="endpoints">Endpoints</button></th>
    <th aria-sort="none"><button type="button" data-sort="signal">Signal</button></th>
    <th>Open</th>
  </tr></thead><tbody data-genome-results>{''.join(table_rows)}</tbody></table></div>
  <p class="search-empty" data-empty hidden>No genomes match these filters. Clear filters to see all genomes.</p></div>
</section>
</main>'''
    return content


def _group_studies(rows: list[dict[str, str]]) -> list[tuple[str, list[dict[str, str]]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["pmid"], []).append(row)
    return sorted(grouped.items(), key=lambda item: item[0])


def genome_content(
    genome: dict[str, object],
    asset_map: dict[str, dict[str, object]],
    track_ids: dict[str, str],
    jbrowse_config: str | None,
) -> str:
    assembly = str(genome["assembly"])
    rows: list[dict[str, str]] = genome["metadata_rows"]
    published = [row for row in rows if is_published_status(row.get("release_status"))]
    species = next((row.get("species", "") for row in published if row.get("species")), "")
    studies = _group_studies(published)
    total_records = sum(int(row["record_count_number"]) for row in published)
    metadata_url = get_asset_url(asset_map, str(genome["metadata_path"]))
    signal_sources = {
        row["source_id"] for row in published
        if _asset_exists(
            asset_map,
            lambda logical, _item, sid=row["source_id"]: logical.startswith(f"tracks/{sid}/")
            and logical.lower().endswith((".bw", ".bigwig")),
        )
    }

    source_cards: list[str] = []
    for pmid, study_rows in studies:
        title = next((row.get("title", "") for row in study_rows if row.get("title")), f"Study PMID {pmid}")
        study_path = next((row.get("study_gff3", "").strip() for row in study_rows if row.get("study_gff3", "").strip()), "")
        genome_dir = PurePosixPath(str(genome["metadata_path"])).parent
        gff3_path = (genome_dir / study_path).as_posix() if study_path else ""
        gff3_url = get_asset_url(asset_map, gff3_path, optional=True) if gff3_path else None
        source_lines: list[str] = []
        for row in study_rows:
            source_id = row["source_id"]
            record_count = int(row["record_count_number"])
            evidence = row.get("evidence_class", "")
            source_has_signal = source_id in signal_sources
            raw_accessions = row.get("raw_data_accessions", "").strip()
            raw_link = f'<span class="source-raw">Raw data: {raw_data_links(raw_accessions)}</span>' if raw_accessions else ""
            caveat = SOURCE_PAGE_CAVEATS.get(source_id, "")
            caveat_html = f'<p class="source-caveat">{esc(caveat)}</p>' if caveat else ""
            signal_html = '<span class="signal-present">Experimental signal</span>' if source_has_signal else ""
            facts = "".join(
                f'<div><dt>{esc(label)}</dt><dd>{esc(row.get(field))}</dd></div>'
                for field, label in (("article_license", "Article license"), ("redistribution_status", "Redistribution"), ("release_status", "Release status"), ("known_limitations", "Limitations"))
                if row.get(field)
            )
            source_lines.append(f'''<div class="source-evidence" id="source-{esc(source_id)}" data-source-card="{esc(source_id)}">
  <div class="source-heading"><h4>{esc(source_id)}</h4><strong>{record_count:,} 3′ ends</strong></div>
  <p class="source-summary">{esc(row.get('assay', ''))} · {esc(evidence_label(evidence))}</p>
  {caveat_html}<p class="source-links">{raw_link}{signal_html}</p>
  <details class="source-notes"><summary>Source notes</summary><dl>{facts}</dl></details>
</div>''')
        supplementary: list[str] = []
        seen_paths: set[str] = set()
        if gff3_path and gff3_url:
            seen_paths.add(gff3_path)
            zip_member = "/".join(PurePosixPath(gff3_path).parts[1:])
            supplementary.append(f'<a class="download-card featured" data-package-file data-zip-path="{esc(zip_member)}" href="{site_href(gff3_url, 1)}">Study GFF3</a>')
        for field, label in (
            ("gene_associations", "Gene associations"),
            ("condition_observations", "Condition observations"),
        ):
            raw_value = next((row.get(field, "").strip() for row in study_rows if row.get(field, "").strip()), "")
            if not raw_value:
                continue
            logical_path = (genome_dir / raw_value).as_posix()
            if logical_path in seen_paths:
                continue
            link_url = get_asset_url(asset_map, logical_path, optional=True)
            if link_url:
                seen_paths.add(logical_path)
                zip_member = "/".join(PurePosixPath(logical_path).parts[1:])
                supplementary.append(f'<a class="download-card" data-package-file data-zip-path="{esc(zip_member)}" href="{site_href(link_url, 1)}">{esc(label)} TSV</a>')
        if not supplementary:
            downloads_html = '<p class="muted">No downloadable endpoint file is published for this study.</p>'
        else:
            downloads_html = f'<div class="download-grid">{"".join(supplementary)}</div>'
        source_cards.append(f'''<article class="study-card" id="study-{esc(pmid)}">
  <header><div><p class="eyebrow">PMID {esc(pmid)}</p><h3><a href="{esc(_publication_link(pmid))}" target="_blank" rel="noopener">{esc(title)}</a></h3></div></header>
  <div class="study-source-list">{''.join(source_lines)}</div><div class="study-downloads">{downloads_html}</div>
</article>''')

    all_source_rows = rows
    unpublished_cards = []
    for pmid, audit_rows in _group_studies([row for row in all_source_rows if not is_published_status(row.get("release_status"))]):
        title = next((row.get("title", "") for row in audit_rows if row.get("title")), f"Study PMID {pmid}")
        ids = ", ".join(row["source_id"] for row in audit_rows)
        unpublished_cards.append(f'''<article class="study-card audit-card"><header><div><p class="eyebrow">Study PMID {esc(pmid)}</p><h3>{esc(title)}</h3></div><span class="badge badge-review">No endpoint file</span></header><p>{esc(ids)} is listed so its source can be checked. Its observations are not included in the downloadable endpoint release or JBrowse tracks.</p></article>''')

    if jbrowse_config:
        signal_intro = "Explore endpoints and signal tracks. Track menus provide study details and downloads."
        if not signal_sources:
            signal_intro += " No experimental signal is available for this genome."
        frame_height = min(1050, 510 + 65 * len(published) + 190 * len(signal_sources))
        browser_html = f'''<section class="browser-panel" id="genome-browser" data-genome-browser data-assembly="{esc(assembly)}" style="--browser-frame-height:{frame_height}px">
  <div class="browser-panel-heading"><div><p class="eyebrow">Genome browser</p><h2>Explore this genome</h2><p>{signal_intro}</p></div><div class="browser-actions"><button class="browser-open" type="button" data-share-view disabled>Share view</button><button class="browser-open" type="button" data-retry-browser>Reload</button><a class="browser-open" href="../jbrowse/index.html?config={quote(jbrowse_config, safe='')}&amp;bted_default=1">Open full browser ↗</a></div></div>
  <p class="browser-share-status" data-browser-status role="status" aria-live="polite">Loading browser…</p>
  <p class="browser-share-status" data-share-status role="status" aria-live="polite"></p><input class="browser-share-manual" data-share-manual aria-label="Share link" readonly hidden>
  <iframe data-browser-frame data-config="{esc(jbrowse_config)}" title="{esc(assembly)} genome browser" loading="lazy" referrerpolicy="no-referrer"></iframe>
</section>'''
    else:
        browser_html = '<section class="browser-panel browser-unavailable"><p class="eyebrow">Genome browser</p><h2>JBrowse is not available for this assembly</h2><p>Study downloads and evidence notes are available below.</p></section>'

    metadata_link = f'<a class="button" data-package-file data-zip-path="{esc(assembly)}/metadata.tsv" href="{site_href(str(metadata_url), 1)}">Genome metadata.tsv</a>'
    genome_downloads = f'''<section class="genome-downloads" aria-labelledby="genome-downloads-title"><div><p class="eyebrow">Genome files</p><h2 id="genome-downloads-title">Download this genome</h2><p>Study files and genome metadata in one ZIP.</p></div><div class="genome-download-actions"><button class="button primary" type="button" data-download-genome-package>Download genome ZIP</button>{metadata_link}<a class="button" href="https://www.ncbi.nlm.nih.gov/datasets/genome/{quote(assembly)}/" target="_blank" rel="noopener">NCBI reference</a><p class="package-status" data-package-status role="status" aria-live="polite"></p></div></section>'''
    content = f'''<main class="page-shell genome-page" data-genome-page data-assembly="{esc(assembly)}">
<p class="breadcrumbs"><a href="../genomes.html">Genomes</a><span aria-hidden="true">/</span><span>{esc(assembly)}</span></p>
<section class="genome-title"><div><p class="eyebrow">Reference genome</p><h1>{esc(species or assembly)}</h1><p class="assembly-id">{esc(assembly)}</p></div></section>
<section class="genome-summary" aria-label="Genome data summary"><div><strong>{len(studies)}</strong><span>published {'study' if len(studies) == 1 else 'studies'}</span></div><div><strong>{len(published)}</strong><span>source {'record' if len(published) == 1 else 'records'}</span></div><div><strong>{total_records:,}</strong><span>3′ end records</span></div></section>
{browser_html}
<section class="genome-studies"><div class="section-heading"><div><p class="eyebrow">Research and downloads</p><h2>Studies on this genome</h2></div></div>{''.join(source_cards) if source_cards else '<p class="empty-state">No published study records are available for this genome.</p>'}{''.join(unpublished_cards)}</section>
{genome_downloads}
</main>'''
    return content


def redirect_html(title: str, *, destination: str, query_script: str) -> str:
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex"><title>{esc(title)} · BTED</title></head><body><p>This page moved to the genome view. <a href="{esc(destination)}">Continue to BTED</a>.</p><script>{query_script}</script></body></html>'''


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def build_site(
    site_root: Path,
    release_root: Path,
    asset_map: dict[str, dict[str, object]],
    browser_configs: dict[str, str],
    track_ids: dict[str, str],
    taxonomy_path: Path = TAXONOMY_REGISTRY,
) -> dict[str, object]:
    release, files = read_release(release_root)
    genomes = load_genomes(release_root, release, files)
    taxonomy = load_genome_taxonomy(taxonomy_path, genomes)
    for relative in files:
        if relative not in asset_map:
            raise SiteBuildError(f"Published release file is missing from the browser allowlist: {relative}")

    site_root.mkdir(parents=True, exist_ok=True)
    _write(site_root / "index.html", page("Home", home_content(genomes), current="home", scripts=("assets/home.js",)))
    _write(site_root / "genomes.html", page("Genomes", index_content(genomes, asset_map, taxonomy), current="genomes", scripts=("assets/genome-index.js",)))
    genome_files = 0
    for genome in genomes:
        assembly = str(genome["assembly"])
        config = browser_configs.get(assembly)
        _write(
            site_root / "genomes" / f"{assembly}.html",
            page(
                f"{next((row.get('species', '') for row in genome['metadata_rows'] if row.get('species')), assembly)} · {assembly}",
                genome_content(genome, asset_map, track_ids, config),
                current="genomes",
                scripts=("../assets/genome-page.js",),
                depth=1,
            ),
        )
        genome_files += 1

    # Legacy entry points keep source and coordinate query parameters, then land
    # on the matching genome page.
    legacy_browser_script = '''
const q = new URLSearchParams(location.search);
const assembly = q.get("assembly") || q.get("accession") || q.get("genome") || "";
const target = new URL(assembly ? `genomes/${encodeURIComponent(assembly)}.html` : "genomes.html", document.baseURI);
["source_id", "loc", "session", "tracks", "highlight"].forEach((key) => { const value = q.get(key); if (value) target.searchParams.set(key, value); });
location.replace(target.href);
'''.strip()
    source_redirect_script = '''
const q = new URLSearchParams(location.search);
const source = q.get("source_id") || "";
const target = new URL("../genomes.html", document.baseURI);
if (source) target.searchParams.set("source_id", source);
location.replace(target.href);
'''.strip()
    _write(site_root / "browser.html", redirect_html("Genome browser", destination="genomes.html", query_script=legacy_browser_script))
    _write(site_root / "sources.html", redirect_html("Genome directory", destination="genomes.html", query_script="""const q=new URLSearchParams(location.search);const assembly=q.get('assembly')||q.get('accession');const target=new URL(assembly?`genomes/${encodeURIComponent(assembly)}.html`:"genomes.html",document.baseURI);const search=q.get('search')||q.get('query')||q.get('accession');if(!assembly&&search)target.searchParams.set('search',search);location.replace(target.href);"""))
    _write(site_root / "catalog.html", redirect_html("Downloads", destination="genomes.html", query_script="location.replace(new URL('genomes.html', document.baseURI).href);"))

    old_assembly_root = site_root / "assemblies"
    old_assembly_root.mkdir(parents=True, exist_ok=True)
    for genome in genomes:
        assembly = str(genome["assembly"])
        script = f'''const q=new URLSearchParams(location.search);const target=new URL("../genomes/{quote(assembly)}.html",document.baseURI);["source_id","loc","session","tracks","highlight"].forEach(k=>{{const v=q.get(k);if(v)target.searchParams.set(k,v);}});location.replace(target.href);'''
        _write(old_assembly_root / f"{assembly}.html", redirect_html("Genome page", destination=f"../genomes/{assembly}.html", query_script=script))

    old_records = site_root / "records"
    old_records.mkdir(parents=True, exist_ok=True)
    source_to_assembly = {
        row["source_id"]: str(genome["assembly"])
        for genome in genomes
        for row in genome["metadata_rows"]
    }
    for source_id, assembly in sorted(source_to_assembly.items()):
        script = f'''const q=new URLSearchParams(location.search);const target=new URL("../genomes/{quote(assembly)}.html",document.baseURI);target.searchParams.set("source_id",{json.dumps(source_id)});["loc","session","tracks","highlight"].forEach(k=>{{const v=q.get(k);if(v)target.searchParams.set(k,v);}});location.replace(target.href);'''
        _write(old_records / f"{source_id}.html", redirect_html("Genome page", destination=f"../genomes/{assembly}.html", query_script=script))

    methodology = '''<main class="page-shell prose"><p class="breadcrumbs"><a href="index.html">Home</a><span aria-hidden="true">/</span><span>Data notes</span></p><div class="page-heading"><div><p class="eyebrow">BTED v0.4.0</p><h1>Data notes</h1></div></div>
<section><h2>Genome-first release</h2><p>BTED v0.4.0 groups public study records by reference assembly. Each genome page combines study descriptions, evidence notes, downloadable GFF3 and TSV files, and the JBrowse view.</p></section>
<section><h2>Coordinates and evidence</h2><p>Study GFF3 files preserve separate source observations and use 1-based coordinates. An endpoint reported in a paper is not automatically a functional validation of a terminator. BigWig tracks show experimental signal and are labelled separately from endpoint features.</p></section>
<section><h2>Downloads</h2><p>Use the genome page to download <code>metadata.tsv</code>, per-study <code>endpoints.gff3.gz</code>, and available supplementary TSV files. The release manifest and checksum list support programmatic verification and are not user-facing data downloads.</p></section>
</main>'''
    _write(site_root / "methodology.html", page("Data notes", methodology, current="notes"))
    usage = '''<main class="page-shell usage-page">
<p class="breadcrumbs"><a href="index.html">Home</a><span aria-hidden="true">/</span><span>Usage</span></p>
<div class="page-heading"><div><p class="eyebrow">BTED</p><h1>Website usage</h1><p>Page views by country and city. IP addresses are not stored.</p></div></div>
<form class="usage-range"><label for="usage-days">Period</label><select id="usage-days" name="days"><option value="7">7 days</option><option value="30" selected>30 days</option><option value="90">90 days</option><option value="365">12 months</option><option value="0">Available history</option></select><button class="button" type="submit">Apply</button></form>
<p id="usage-status" role="status">Loading usage…</p><noscript><p>Enable JavaScript to view usage statistics.</p></noscript>
<div id="usage-report" hidden>
<section class="usage-metrics" aria-label="Summary"><div><span>Page views</span><strong id="usage-views">0</strong></div><div><span>Countries / regions</span><strong id="usage-countries">0</strong></div><div><span>Active days</span><strong id="usage-active">0</strong></div></section>
<section class="usage-panel"><h2>Where BTED is used</h2><figure class="usage-map"><div id="usage-map"></div><figcaption><span>No views</span><span class="usage-map-scale" aria-hidden="true"></span><span id="usage-map-max"></span></figcaption></figure></section>
<section class="usage-panel"><h2>Daily page views</h2><figure class="usage-trend"><div id="usage-trend"></div><figcaption><span id="usage-start"></span><span>Page views · UTC</span><span id="usage-end"></span></figcaption></figure></section>
<div class="usage-columns"><section class="usage-panel"><h2>Countries / regions</h2><div class="usage-table-wrap"><table><thead><tr><th scope="col">Country / region</th><th scope="col">Views</th><th scope="col">Share</th></tr></thead><tbody id="usage-country-rows"></tbody></table></div></section>
<section class="usage-panel"><h2>Cities</h2><p id="usage-no-cities" hidden>No city data for this period.</p><div class="usage-table-wrap"><table><thead><tr><th scope="col">City</th><th scope="col">Views</th></tr></thead><tbody id="usage-city-rows"></tbody></table></div></section></div>
<section class="usage-panel"><h2>Pages</h2><div class="usage-table-wrap"><table><thead><tr><th scope="col">Page</th><th scope="col">Views</th></tr></thead><tbody id="usage-path-rows"></tbody></table></div></section>
<p id="usage-period" class="usage-footnote"></p></div>
<p class="usage-footnote">Full page loads only. API, downloads, embedded JBrowse and known crawlers are excluded. Locations are approximate. History is kept for 400 days.</p>
</main>'''
    _write(site_root / "usage.html", page("Website usage", usage, current="usage", scripts=("assets/usage.js",)))
    _write(site_root / "about.html", redirect_html("Data notes", destination="methodology.html", query_script="location.replace(new URL('methodology.html', document.baseURI).href);"))
    _write(site_root / "accession-range-demo.html", redirect_html(
        "Genome search", destination="genomes.html",
        query_script="""const params=new URLSearchParams(location.search);const value=params.get("accession")||params.get("search");const target=new URL("genomes.html",document.baseURI);if(value)target.searchParams.set("search",value);location.replace(target.href);""",
    ))

    return {
        "release_version": RELEASE_VERSION,
        "genome_count": len(genomes),
        "genome_pages": genome_files,
        "source_count": sum(len(genome["metadata_rows"]) for genome in genomes),
        "endpoint_count": sum(
            int(row["record_count_number"])
            for genome in genomes for row in genome["metadata_rows"]
            if is_published_status(row.get("release_status"))
        ),
        "release_files": len(files),
    }


def materialize_browser_tracks(release_root: Path, output_root: Path) -> list[dict[str, object]]:
    """Split study GFF3 records by source_id into deterministic plain browser files."""
    release, files = read_release(release_root)
    genomes = load_genomes(release_root, release, files)
    output_root.mkdir(parents=True, exist_ok=True)
    object_root = output_root / RELEASE_VERSION
    object_root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for genome in genomes:
        assembly = str(genome["assembly"])
        metadata_dir = PurePosixPath(str(genome["metadata_path"])).parent
        for source in genome["metadata_rows"]:
            if not is_published_status(source.get("release_status")) or int(source["record_count_number"]) <= 0:
                continue
            source_id = source["source_id"]
            relative_gff3 = (metadata_dir / safe_relative_path(source["study_gff3"], label="study GFF3")).as_posix()
            source_path = release_file_path(release_root, relative_gff3, label="study GFF3")
            record_count = 0
            target_rel = PurePosixPath("tracks") / source_id / "endpoints.gff3"
            target = object_root.joinpath(*target_rel.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(source_path, "rt", encoding="utf-8", newline="") as handle, target.open("w", encoding="utf-8", newline="\n") as output:
                for line in handle:
                    if not line.strip():
                        continue
                    if line.startswith("#"):
                        if line.startswith("##FASTA"):
                            break
                        if line.startswith("##sequence-region "):
                            parts = line.rstrip("\r\n").split(" ")
                            mapping = BROWSER_SEQID_MAPS.get(assembly, {})
                            if len(parts) > 1 and parts[1] in mapping:
                                parts[1] = mapping[parts[1]]
                                line = " ".join(parts) + "\n"
                        output.write(line if line.endswith("\n") else line + "\n")
                        continue
                    columns = line.rstrip("\r\n").split("\t")
                    if len(columns) != 9:
                        raise SiteBuildError(f"Malformed GFF3 feature in {relative_gff3}: expected 9 columns")
                    if columns[1] != source_id:
                        continue
                    columns[0] = BROWSER_SEQID_MAPS.get(assembly, {}).get(columns[0], columns[0])
                    line = "\t".join(columns) + "\n"
                    output.write(line if line.endswith("\n") else line + "\n")
                    record_count += 1
            expected = int(source["record_count_number"])
            if record_count != expected:
                target.unlink(missing_ok=True)
                raise SiteBuildError(f"{assembly}/{source_id}: filtered GFF3 has {record_count} records, expected {expected}")
            logical_path = (PurePosixPath("tracks") / source_id / "endpoints.gff3").as_posix()
            rows.append({
                "logical_path": logical_path,
                "local_path": (PurePosixPath(RELEASE_VERSION) / target_rel).as_posix(),
                "byte_size": target.stat().st_size,
                "sha256": sha256_file(target),
                "asset_kind": "gff3",
                "source_id": source_id,
                "assembly": assembly,
                "record_count": record_count,
            })
    rows.sort(key=lambda row: str(row["logical_path"]))
    manifest = output_root / "browser_tracks.tsv"
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("logical_path", "local_path", "byte_size", "sha256", "asset_kind", "source_id", "assembly", "record_count"),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-root", type=Path, default=Path("data/public/v0.4.0"))
    parser.add_argument("--output-root", type=Path, default=Path("dist/v04-browser-objects"))
    args = parser.parse_args()
    try:
        rows = materialize_browser_tracks(args.release_root.resolve(), args.output_root.resolve())
    except (SiteBuildError, OSError, EOFError, gzip.BadGzipFile, ValueError) as exc:
        print(f"FAIL  {exc}", file=sys.stderr)
        return 1
    print(f"PASS  Materialized {len(rows)} source-specific browser GFF3 assets under {args.output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
