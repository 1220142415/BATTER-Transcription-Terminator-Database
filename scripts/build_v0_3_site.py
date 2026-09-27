#!/usr/bin/env python3
"""Generate versioned BTED v0.3.0 HTML and JSON into a staging site directory."""

from __future__ import annotations

import argparse
import gzip
import html
import json
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

from build_assembly_downloads import RELEASE_VERSION, load_sources, load_study_metadata


REPO_ROOT = Path(__file__).resolve().parent.parent
SITE_ROOT = REPO_ROOT / "site"
RELEASE_ROOT = REPO_ROOT / "data/public/v0.3.0"
STUDIES_PATH = RELEASE_ROOT / "studies"
JBROWSE_CONFIG_ROOT = REPO_ROOT / "dist/BTED-v0.2.0-jbrowse"
REPOSITORY_URL = "https://github.com/seu-yolo/BATTER-Transcription-Terminator-Database"
SITE_ASSET_VERSION = "20260817-core-fields-v2"
HF_DATA_BASE_URL = f"downloads/{RELEASE_VERSION}"
SITE_COVERAGE_EN = "20 assemblies · 22 source datasets · 28,399 endpoint records"
SITE_COVERAGE_ZH = "20 个参考组装 · 22 个来源数据集 · 28,399 条端点记录"

EVIDENCE_LABELS = {
    "author_called_endpoint": "Author-called experimental endpoint",
    "curated_record": "Literature-curated record",
    "audit_only": "Source metadata audit only",
}


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def bi(en: str, _future_translation: str = "") -> str:
    """Emit English only while retaining a stable hook for future translations."""
    return f'<span class="i18n" data-i18n-key="{esc(en)}">{esc(en)}</span>'


def assembly_accession_url(assembly: str) -> str:
    return f"https://www.ncbi.nlm.nih.gov/datasets/genome/{quote(assembly)}/"


def split_accessions(value: object) -> list[str]:
    return [item for item in re.split(r"[;,\s]+", str(value).strip()) if item and item != "NA"]


def accession_destination(accession: str, fallback_url: str = "") -> tuple[str, str]:
    """Return a stable public landing page and repository label for an accession."""
    if re.fullmatch(r"GSE\d+", accession):
        return f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={quote(accession)}", "NCBI GEO"
    if re.fullmatch(r"SR[APRX]\d+", accession):
        return f"https://www.ncbi.nlm.nih.gov/sra/?term={quote(accession)}", "NCBI SRA"
    if re.fullmatch(r"PRJNA\d+", accession):
        return f"https://www.ncbi.nlm.nih.gov/bioproject/{quote(accession)}", "NCBI BioProject"
    if re.fullmatch(r"PRJEB\d+", accession):
        return f"https://www.ebi.ac.uk/ena/browser/view/{quote(accession)}", "ENA"
    if re.fullmatch(r"E-MTAB-\d+", accession):
        return f"https://www.ebi.ac.uk/biostudies/arrayexpress/studies/{quote(accession)}", "BioStudies"
    return fallback_url, "Source repository"


def accession_links(accessions: object, fallback_url: str = "", compact: bool = False) -> str:
    items = []
    for accession in split_accessions(accessions):
        url, repository = accession_destination(accession, fallback_url)
        label = f'<code>{esc(accession)}</code><span>{esc(repository)}</span>'
        if url:
            label = f'<a href="{esc(url)}" target="_blank" rel="noopener" data-accession="{esc(accession)}">{label}</a>'
        items.append(f"<li>{label}</li>")
    class_name = "accession-list compact" if compact else "accession-list"
    return f'<ul class="{class_name}">{"".join(items)}</ul>' if items else "—"


def nav(current: str, depth: int = 0) -> str:
    prefix = "../" * depth
    items = [
        ("index", "index.html", "Home", "首页"),
        ("sources", "sources.html", "Genomes", "基因组"),
        ("catalog", "catalog.html", "Download", "下载"),
        ("methodology", "methodology.html", "Data notes", "数据说明"),
        ("browser", "browser.html", "JBrowse", "JBrowse"),
    ]
    links = "".join(
        f'<a href="{prefix}{path}"' + (' aria-current="page"' if key == current else "")
        + f'>{bi(en, zh)}</a>'
        for key, path, en, zh in items
    )
    return f"""
<header class="site-header"><div class="header-inner">
  <a class="brand" href="{prefix}index.html"><span class="brand-mark">BTED</span><span class="brand-name">Bacterial Transcript 3′ End Database</span></a>
  <nav class="site-nav" aria-label="Primary navigation">{links}</nav>
</div></header>"""


def page(
    title: str,
    current: str,
    content: str,
    depth: int = 0,
    description: str = "BTED v0.3.0",
    extra_scripts: str = "",
) -> str:
    prefix = "../" * depth
    coverage = bi(SITE_COVERAGE_EN, SITE_COVERAGE_ZH)
    coverage_attribute = ' data-browser-coverage' if current == "browser" else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{esc(description)}"><title>{esc(title)} · BTED</title>
<link rel="icon" href="{prefix}assets/favicon.svg" type="image/svg+xml"><link rel="stylesheet" href="{prefix}css/style.css"></head>
<body>{nav(current, depth)}{content}
<footer class="site-footer"><div class="footer-inner"><span>BTED v0.3.0</span><span{coverage_attribute}>{coverage}</span><a href="{REPOSITORY_URL}">GitHub</a></div></footer>
<script src="{prefix}assets/site.js"></script>{extra_scripts}</body></html>"""


def external_link(url: str, label: str) -> str:
    if not url or url == "NA":
        return "—"
    return f'<a href="{esc(url)}" target="_blank" rel="noopener">{esc(label)}</a>'


def status_badge(status: str) -> str:
    if status == "audit_only":
        return f'<span class="badge badge-audit">{bi("Metadata only", "仅元数据")}</span>'
    return f'<span class="badge badge-published">{bi("Data available", "数据可用")}</span>'


def jbrowse_config_url(assembly: str, source_id: str | None = None) -> str:
    path = f"/api/assemblies/{quote(assembly, safe='')}/jbrowse-config"
    if source_id:
        path += f"?source_id={quote(source_id, safe='')}"
    return path


def assembly_browser_config(assembly: str, records: list[dict[str, object]]) -> str | None:
    published = [record for record in records if record["has_jbrowse"]]
    if not published:
        return None
    if len(published) > 1:
        return jbrowse_config_url(assembly)
    return jbrowse_config_url(assembly, str(published[0]["source_id"]))


def assembly_download_url(assembly: str, filename: str, prefix: str = "") -> str:
    return release_download_url(f"assemblies/{quote(assembly)}/{filename}", prefix)


def record_download_url(source_id: str, filename: str, prefix: str = "") -> str:
    return release_download_url(f"records/{quote(source_id)}/{filename}", prefix)


def study_download_url(pmid: str, filename: str, prefix: str = "") -> str:
    return release_download_url(f"studies/PMID_{quote(pmid)}/{filename}", prefix)


def release_download_url(relative_path: str, prefix: str = "") -> str:
    base = HF_DATA_BASE_URL.rstrip("/")
    if re.match(r"^https?://", base):
        return f"{base}/{relative_path.lstrip('/')}"
    return f"{prefix}{base}/{relative_path.lstrip('/')}"


def release_revision(base_url: str) -> str | None:
    match = re.search(r"/resolve/([^/]+)/", f"{base_url.rstrip('/')}/")
    return match.group(1) if match else None


def validate_release_base_url(value: str) -> str:
    base = value.rstrip("/")
    if not re.fullmatch(
        r"https://huggingface\.co/datasets/liurulong/terminator/resolve/[0-9a-f]{40}/v0\.3\.0",
        base,
    ):
        raise ValueError(
            "--hf-data-base-url must be the fixed v0.3.0 resolve URL for a 40-character commit SHA"
        )
    return base


def legacy_redirect_page(title: str, destination: str, query_key: str | None = None) -> str:
    """Keep old public links useful while sending visitors to the consolidated pages."""
    query_script = ""
    if query_key:
        query_script = f"""
  const params = new URLSearchParams(window.location.search);
  const value = params.get({json.dumps(query_key)}) || params.get("q") || params.get("query") || params.get("accession") || params.get("assembly") || params.get("search") || "";
  if (value) target.searchParams.set("search", value);
"""
    refresh = "" if query_key else f'<meta http-equiv="refresh" content="0;url={esc(destination)}">'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>{esc(title)} · BTED</title>
<link rel="canonical" href="{esc(destination)}">{refresh}</head>
<body><p>This page has moved to <a href="{esc(destination)}">{esc(destination)}</a>.</p>
<script>
  const target = new URL({json.dumps(destination)}, window.location.href);
{query_script}  window.location.replace(target.href);
</script></body></html>"""


def jbrowse_href(assembly: str, prefix: str = "", source_id: str | None = None) -> str:
    """Return the user-facing browser wrapper URL.

    The bundled JBrowse application remains at ``jbrowse/index.html``.  Public
    catalogue links go through the small wrapper so users see the organism,
    source, publication, raw accession and download links before entering the
    browser.

    The wrapper uses static assembly metadata for its controls and a same-origin
    Worker route to load the matching JBrowse configuration.
    """
    parts = [f"assembly={quote(assembly, safe='')}"]
    if source_id:
        parts.append(f"source_id={quote(source_id, safe='')}")
    return f"{prefix}browser.html?{'&amp;'.join(parts)}"


def browser_reading_guide(assays: list[str]) -> str:
    """Explain the strand-aware Rend-seq view only where that view exists."""

    if not any("rend-seq" in assay.lower() for assay in assays):
        return ""
    return """
    <section class="panel browser-guide"><div class="panel-header"><div><p class="eyebrow">Genome browser guide</p><h2>Compare raw signal with reported endpoints</h2></div><span class="browser-guide-hint">Track menu: paper and raw-data links</span></div>
      <div class="strand-legend" aria-label="Strand track legend"><div><span class="strand-swatch plus"></span><strong>+ strand signal</strong><span>raw repository values in a dedicated track</span></div><div><span class="strand-swatch minus"></span><strong>− strand signal</strong><span>raw repository values in a dedicated track</span></div></div>
      <p class="section-note"><strong>Important:</strong> BTED does not normalize the displayed signal. The endpoint track remains separate from the two signal tracks. Open a source track menu to find the paper, PubMed/DOI, raw-data accession and BTED record links.</p>
    </section>"""


def browser_page_content() -> str:
    return """
<main class="page-shell browser-page" data-browser-wrapper>
  <nav class="breadcrumbs"><a href="sources.html">Genomes</a><span>/</span><span>JBrowse</span></nav>
  <section class="panel browser-info">
    <div class="browser-info-heading"><div><p class="eyebrow">JBrowse</p><h1 data-browser-organism>Choose a genome</h1><p class="browser-assembly-line"><span data-browser-assembly>—</span><span data-browser-reference></span></p></div><div class="browser-info-actions"><a data-browser-assembly-link target="_blank" rel="noopener" hidden>NCBI</a><a class="button" data-browser-genome hidden>Genome details</a></div></div>
    <div class="browser-source-row"><label for="browser-assembly-select">Reference assembly</label><select id="browser-assembly-select" data-browser-assembly-select><option value="">Choose a reference assembly</option></select></div>
    <div class="browser-source-row"><label for="browser-source-select">Source track</label><select id="browser-source-select" data-browser-source disabled><option value="">All source tracks</option></select><span class="browser-study" data-browser-study>Choose a reference assembly to see its tracks.</span></div>
    <p class="browser-source-note" data-browser-source-note>Each study is shown as a separate track.</p>
    <div class="browser-link-row"><a data-browser-paper hidden></a><a data-browser-pubmed hidden></a><a data-browser-doi hidden></a><a data-browser-gff3 hidden></a><a data-browser-record hidden></a></div>
    <div class="browser-study-links" data-browser-studies hidden></div>
    <div class="browser-raw-links" data-browser-raw></div>
    <p class="browser-status" data-browser-status role="status" aria-live="polite">Choose a genome assembly to open its browser tracks.</p>
  </section>
  <section class="panel browser-frame-panel"><iframe data-browser-frame title="JBrowse genome browser" loading="lazy"></iframe></section>
</main>"""


def record_page(record: dict[str, object], assembly_track_count: int) -> str:
    source_id = str(record["source_id"])
    source = record["source"]
    manifest = record["manifest"]
    status = str(record["release_status"])
    assembly = str(record["assembly"])
    browser = (
        f'<a class="button primary" href="{jbrowse_href(assembly, "../", source_id)}">{bi("Open source track", "打开来源 track")}</a>'
        if record["has_jbrowse"] else f'<span class="button disabled">{bi("No endpoint track", "无端点 track")}</span>'
    )
    pmid = str(source["pmid"])
    study_id = f"PMID_{pmid}"
    gff3 = (
        f'<a class="download-card featured" href="{study_download_url(pmid, "endpoints.gff3.gz", "../")}"><strong>{bi("Study GFF3", "研究 GFF3")}</strong><code>{study_id}/endpoints.gff3.gz</code></a>'
        if int(record["record_count"]) > 0 and status != "audit_only" else ""
    )
    metadata = (
        f'<a class="download-card" href="{study_download_url(pmid, "metadata.tsv", "../")}"><strong>{bi("Readable study metadata", "可读研究元数据")}</strong><code>metadata.tsv</code></a>'
        f'<a class="download-card" href="{study_download_url(pmid, "metadata.json", "../")}"><strong>{bi("Full study metadata", "完整研究元数据")}</strong><code>metadata.json</code></a>'
    )
    evidence = str(record["evidence_class"])
    raw_accessions = accession_links(source["raw_data_accessions"], str(manifest.get("raw_data_url", "")))
    browser_guide = browser_reading_guide([str(source["assay_family"])]) if record["has_jbrowse"] else ""
    content = f"""
<main class="page-shell record-shell">
  <nav class="breadcrumbs"><a href="../sources.html">{bi('Genomes', '基因组')}</a><span>/</span><a href="../assemblies/{esc(assembly)}.html">{esc(assembly)}</a><span>/</span><span>{source_id}</span></nav>
  <div class="record-heading"><div><p class="eyebrow">{source_id}</p><h1><em>{esc(source['species'])}</em></h1><p class="record-title">{esc(source['paper_title'])} · <a href="../studies/PMID_{esc(pmid)}.html">Study package PMID {esc(pmid)}</a></p></div>{status_badge(status)}</div>
  <section class="metric-grid"><div class="metric"><span>{bi('Records', '记录数')}</span><strong>{int(record['record_count']):,}</strong></div><div class="metric"><span>{bi('Evidence', '证据')}</span><strong>{esc(EVIDENCE_LABELS.get(evidence, evidence))}</strong></div><div class="metric"><span>{bi('Assembly accession', '参考组装')}</span><strong><a href="{assembly_accession_url(assembly)}" target="_blank" rel="noopener">{esc(assembly)}</a></strong></div><div class="metric"><span>{bi('Assay', '实验方法')}</span><strong>{esc(source['assay_family'])}</strong></div></section>
  <div class="record-layout"><div class="record-main">
    <section class="panel"><div class="panel-header"><h2>{bi('Source overview', '来源概况')}</h2>{browser}</div><dl class="data-list">
      <dt>{bi('Dataset', '数据集')}</dt><dd>{esc(manifest.get('dataset_id', 'NA'))}</dd><dt>{bi('Publication year', '发表年份')}</dt><dd>{esc(source['published_year'])}</dd>
      <dt>{bi('Evidence', '证据说明')}</dt><dd>{esc(EVIDENCE_LABELS.get(evidence, evidence))}</dd><dt>{bi('Tracks on this assembly', '该组装上的数据轨道')}</dt><dd>{assembly_track_count}</dd>
    </dl></section>{browser_guide}
    <section class="panel"><h2>{bi('Raw data accessions', '原始数据')}</h2><p class="section-note">Open the public repository record for each accession number.</p>{raw_accessions}</section>
    <section class="panel"><h2>{bi('Study download', '研究数据下载')}</h2><p class="section-note">{bi('Files are grouped by PMID. Studies with endpoint records include a combined GFF3 that retains each source_id.', '文件按 PMID 归类。有端点记录的研究提供合并 GFF3，并在每条 feature 中保留 source_id。')}</p><div class="download-grid compact-downloads">{gff3}{metadata}</div></section>
    <section class="panel"><h2>{bi('Data note', '数据说明')}</h2><p>{esc(manifest.get('known_limitations', source['blocker_or_note']))}</p><div class="evidence-note">{bi('A 3′ end record is not automatically a functionally proven terminator. Tracks from the same assembly remain separate evidence sources.', '3′ end 记录不自动等同于功能性终止子；同一组装上的不同 track 仍是独立证据来源。')}</div></section>
  </div><aside class="record-side">
    <section class="panel compact"><h2>{bi('Publication', '依据文献')}</h2><ul class="link-list"><li>{external_link(str(manifest.get('pubmed_url', '')), f"PubMed {source['pmid']}")}</li><li>{external_link(str(manifest.get('doi_url', '')), f"DOI {source['doi']}")}</li><li>{external_link(str(manifest.get('pmc_url', '')), str(source.get('pmc', 'PMC')))}</li></ul></section>
    <section class="panel compact"><h2>{bi('Identity', '标识')}</h2><dl class="mini-list"><dt>Source ID</dt><dd>{source_id}</dd><dt>Assembly</dt><dd><a href="{assembly_accession_url(assembly)}" target="_blank" rel="noopener">{esc(assembly)}</a></dd><dt>Version</dt><dd>v0.3.0</dd></dl></section>
  </aside></div>
</main>"""
    return page(f"{source_id} · {source['species']}", "sources", content, depth=1)


def study_page(pmid: str, records: list[dict[str, object]], study_dir: Path) -> str:
    """Render one page for the public package that groups all sources for a PMID."""
    if not records:
        raise ValueError(f"PMID_{pmid}: study page has no source records")
    first_source = records[0]["source"]
    title = str(first_source["paper_title"])
    total = sum(int(record["record_count"]) for record in records)
    species = sorted({str(record["source"]["species"]) for record in records})
    assemblies = sorted({str(record["assembly"]) for record in records})
    record_rows = "".join(
        f"<tr><td><a class=\"source-id\" href=\"../records/{esc(record['source_id'])}.html\">{esc(record['source_id'])}</a></td>"
        f"<td><em>{esc(record['source']['species'])}</em></td><td><code>{esc(record['assembly'])}</code></td>"
        f"<td>{esc(record['source']['assay_family'])}</td><td class=\"number\">{int(record['record_count']):,}</td></tr>"
        for record in records
    )
    download_files = [
        ("metadata.tsv", "Readable metadata table", "Tab-separated study summary with one row per source dataset."),
        ("metadata.json", "Full metadata", "Original source objects and provenance for every source dataset in this study."),
    ]
    if any(int(record["record_count"]) > 0 for record in records):
        download_files.insert(0, (
            "endpoints.gff3.gz",
            "Study endpoint GFF3",
            "Compressed 1-based endpoint features; source IDs remain in each feature.",
        ))
    extra_labels = {
        "gene_associations.tsv.gz": "Gene associations",
        "condition_observations.tsv.gz": "Condition observations",
    }
    for path in sorted(study_dir.glob("*.tsv.gz")):
        if path.name in extra_labels:
            download_files.append((path.name, extra_labels[path.name], "Study-specific supplementary records."))
    download_cards = "".join(
        f'<a class="download-card" href="{study_download_url(pmid, filename, "../")}" download>'
        f"<strong>{esc(label)}</strong><code>{esc(filename)}</code><span>{esc(description)}</span></a>"
        for filename, label, description in download_files
    )
    content = f"""
<main class="page-shell record-shell">
  <nav class="breadcrumbs"><a href="../catalog.html">{bi('Download', '下载')}</a><span>/</span><span>PMID_{esc(pmid)}</span></nav>
  <div class="record-heading"><div><p class="eyebrow">Study package · PMID {esc(pmid)}</p><h1>{esc(title)}</h1><p class="record-title"><a href="https://pubmed.ncbi.nlm.nih.gov/{esc(pmid)}/" target="_blank" rel="noopener">Open PubMed record ↗</a></p></div></div>
  <section class="metric-grid"><div class="metric"><span>Source datasets</span><strong>{len(records)}</strong></div><div class="metric"><span>3′-end records</span><strong>{total:,}</strong></div><div class="metric"><span>Organisms / strains</span><strong>{len(species)}</strong></div><div class="metric"><span>Reference assemblies</span><strong>{len(assemblies)}</strong></div></section>
  <section class="panel"><h2>Download this study</h2><p class="section-note">Files for all source datasets linked to this PMID are grouped together. The GFF3 keeps source IDs so records remain attributable within the combined study file.</p><div class="download-grid compact-downloads">{download_cards}</div></section>
  <section class="panel"><h2>Source datasets in this study</h2><div class="table-wrap"><table class="source-table"><thead><tr><th>Source ID</th><th>Organism / strain</th><th>Assembly</th><th>Assay</th><th>Records</th></tr></thead><tbody>{record_rows}</tbody></table></div></section>
</main>"""
    return page(f"PMID {pmid} · {title}", "catalog", content, depth=1)


def assembly_page(assembly: str, records: list[dict[str, object]]) -> str:
    total = sum(int(record["record_count"]) for record in records)
    published = [record for record in records if record["release_status"] != "audit_only"]
    browser_config = assembly_browser_config(assembly, records)
    browser = (
        f'<a class="button primary" href="{jbrowse_href(assembly, "../")}">{bi("Open genome browser", "打开基因组浏览器")}</a>'
        if browser_config else f'<span class="button disabled">{bi("Browser unavailable", "浏览器不可用")}</span>'
    )
    browser_actions = f'<div class="assembly-actions">{browser}</div>'
    track_rows = []
    for record in records:
        source = record["source"]
        manifest = record["manifest"]
        track_rows.append(f"""<tr><td><a class="source-id" href="../records/{record['source_id']}.html">{record['source_id']}</a></td><td>{esc(source['published_year'])}<small>{external_link(str(manifest.get('pubmed_url', '')), f"PMID {source['pmid']}")}</small></td><td>{accession_links(source['raw_data_accessions'], str(manifest.get('raw_data_url', '')), compact=True)}</td><td>{esc(source['assay_family'])}</td><td>{esc(EVIDENCE_LABELS.get(str(record['evidence_class']), str(record['evidence_class'])))}</td><td class="number">{int(record['record_count']):,}</td></tr>""")
    has_endpoints = total > 0
    gff3 = (
        f'<a class="download-card featured" href="{assembly_download_url(assembly, "endpoints.gff3", "../")}"><strong>{bi("GFF3 coordinates", "GFF3 坐标")}</strong><code>endpoints.gff3 · {total:,} records</code></a>'
        if published and has_endpoints else ""
    )
    organisms = sorted({str(record["source"]["species"]) for record in records})
    years = sorted(int(record["source"]["published_year"]) for record in records)
    browser_guide = browser_reading_guide(
        [str(record["source"]["assay_family"]) for record in records if record["has_jbrowse"]]
    )
    content = f"""
<main class="page-shell record-shell">
  <nav class="breadcrumbs"><a href="../sources.html">{bi('Genomes', '基因组')}</a><span>/</span><span>{esc(assembly)}</span></nav>
  <div class="record-heading"><div><p class="eyebrow">{bi('Reference assembly', '参考组装')}</p><h1>{esc(assembly)}</h1><p class="record-title"><em>{esc(' / '.join(organisms))}</em></p><p><a href="{assembly_accession_url(assembly)}" target="_blank" rel="noopener">View assembly in NCBI Datasets</a></p></div>{status_badge('published' if published else 'audit_only')}</div>
  <section class="metric-grid"><div class="metric"><span>{bi('Source tracks', '来源 track')}</span><strong>{len(records)}</strong></div><div class="metric"><span>{bi('Endpoint records', '端点记录')}</span><strong>{total:,}</strong></div><div class="metric"><span>{bi('Years', '年份')}</span><strong>{years[0] if len(years) == 1 else f'{years[0]}–{years[-1]}'}</strong></div><div class="metric"><span>{bi('Browser view', '浏览器视图')}</span><strong>{bi('Combined tracks' if len(records) > 1 else 'Single track', '多 track' if len(records) > 1 else '单 track')}</strong></div></section>
  <section class="panel assembly-summary"><div><h2>{bi('Datasets on this genome', '该基因组上的数据集')}</h2><p>{bi('Sources with the exact same assembly accession are shown together. Each study remains a separate track.', '参考组装 accession 完全相同的来源在此集中展示；每项研究保留为独立轨道。')}</p></div>{browser_actions}</section>{browser_guide}
  <section class="panel"><div class="table-wrap"><table class="source-table"><thead><tr><th>Track / Source</th><th>{bi('Year / paper', '年份 / 文献')}</th><th>Raw data accessions</th><th>{bi('Assay', '方法')}</th><th>{bi('Evidence', '证据')}</th><th>{bi('Records', '记录数')}</th></tr></thead><tbody>{''.join(track_rows)}</tbody></table></div></section>
  <section class="panel"><h2>{bi('Download this genome', '下载该基因组数据')}</h2><p class="section-note">{bi('Download GFF3 endpoint features and source metadata. Records from different studies keep separate source IDs and original score attributes.', '下载 GFF3 端点 feature 和来源元数据。不同研究的记录保留各自来源 ID 和原始分数属性。')}</p><div class="download-grid compact-downloads">{gff3}<a class="download-card" href="{assembly_download_url(assembly, 'metadata.json', '../')}"><strong>{bi('Metadata', '元数据')}</strong><code>metadata.json</code></a></div></section>
</main>"""
    return page(f"{assembly} · genome", "sources", content, depth=1)



# Static accession-page payload: lets the accession demo run on GitHub Pages
# without calling a local Python API.

JBROWSE_OVERLAYS = JBROWSE_CONFIG_ROOT

TRACK_STATUS_LABELS = {
    "signal_endpoints": ("Signal + endpoints", "信号 + 端点"),
    "endpoints_only": ("Endpoints only", "仅端点"),
    "metadata_only": ("Metadata only", "仅元数据"),
}

def source_has_signal_tracks(source_id: str) -> bool:
    """Return True if the source JBrowse overlay exposes BigWig signal tracks."""
    path = JBROWSE_OVERLAYS / f"{source_id}.config.json"
    if not path.is_file():
        return False
    config = json.loads(path.read_text(encoding="utf-8"))
    for track in config.get("tracks", []):
        adapter = track.get("adapter", {})
        if adapter.get("type") in ("BigWigAdapter", "MultiQuantitativeTrack"):
            return True
        if "bigWigLocation" in adapter:
            return True
        if adapter.get("type") == "MultiQuantitativeTrack":
            return True
        for sub in adapter.get("subadapters", []):
            if "bigWigLocation" in sub:
                return True
    return False


def reference_name_from_config(path: Path) -> str | None:
    """Extract the first reference sequence name from a JBrowse config file."""
    if not path.is_file():
        return None
    config = json.loads(path.read_text(encoding="utf-8"))
    for view in config.get("defaultSession", {}).get("views", []):
        regions = view.get("displayedRegions", [])
        if regions:
            return str(regions[0].get("refName", ""))
    return None


def track_status(record: dict[str, object]) -> str:
    """Classify the source track for the static accession page."""
    if record["release_status"] == "audit_only":
        return "metadata_only"
    if record["has_jbrowse"] and source_has_signal_tracks(str(record["source_id"])):
        return "signal_endpoints"
    return "endpoints_only"

def build_assemblies_json(grouped: dict[str, list[dict[str, object]]]) -> dict[str, object]:
    assembly_payloads: list[dict[str, object]] = []
    for assembly, group in grouped.items():
        published = [record for record in group if record["release_status"] != "audit_only"]
        browser_config = assembly_browser_config(assembly, group)
        assembly_config_path = JBROWSE_OVERLAYS / "assemblies" / f"{assembly}.config.json"
        track_records: list[dict[str, object]] = []
        for record in group:
            source = record["source"]
            manifest = record["manifest"]
            status = track_status(record)
            label_en, label_zh = TRACK_STATUS_LABELS[status]
            track_records.append({
                "source_id": record["source_id"],
                "name": f"{source['paper_title']} ({record['source_id']})",
                "paper_title": source["paper_title"],
                "publication_year": record["year"],
                "pmid": source["pmid"],
                "publication_url": str(manifest.get("pubmed_url", "")),
                "doi": source.get("doi", ""),
                "doi_url": str(manifest.get("doi_url", "")),
                "pmc": source.get("pmc", ""),
                "pmc_url": str(manifest.get("pmc_url", "")),
                "assay": source["assay_family"],
                "raw_data_accession": str(source["raw_data_accessions"]),
                "raw_data_url": str(manifest.get("raw_data_url", "")),
                "gff3_url": (
                    record_download_url(str(record["source_id"]), "endpoints.gff3")
                    if record["release_status"] != "audit_only" and int(record["record_count"]) > 0 else None
                ),
                "evidence_class": record["evidence_class"],
                "record_count": record["record_count"],
                "record_url": f"records/{record['source_id']}.html",
                "jbrowse_static_config_url": (
                    f"jbrowse/{quote(str(record['source_id']), safe='')}.config.json"
                    if record["has_jbrowse"] else None
                ),
                "track_status": status,
                "track_status_label_en": label_en,
                "track_status_label_zh": label_zh,
                "interpretation_note": str(manifest.get("known_limitations", source["blocker_or_note"])),
                "interpretation_note_zh": "",
            })
        reference_name = reference_name_from_config(assembly_config_path)
        if reference_name is None:
            for record in group:
                source_config = JBROWSE_OVERLAYS / f"{record['source_id']}.config.json"
                reference_name = reference_name_from_config(source_config)
                if reference_name:
                    break
        organism_names = sorted({str(record["source"]["species"]) for record in group})
        total_records = sum(int(record["record_count"]) for record in group)
        payload: dict[str, object] = {
            "schema_version": "1.0",
            "delivery_mode": "static_json_assembly_lookup",
            "assembly": {
                "accession": assembly,
                "display_name": f"BTED {assembly}",
                "scientific_name": organism_names[0] if organism_names else "",
                "strain": "",
                "reference_name": reference_name or "",
            },
            "record_count": total_records,
            "tracks": track_records,
            "jbrowse_config_url": browser_config,
            "jbrowse_static_config_url": (
                f"jbrowse/assemblies/{quote(assembly, safe='')}.config.json"
                if browser_config else None
            ),
            "assembly_page_url": f"assemblies/{assembly}.html",
            "gff3_url": assembly_download_url(assembly, "endpoints.gff3") if published and total_records else None,
            "metadata_url": assembly_download_url(assembly, "metadata.json"),
        }
        assembly_payloads.append(payload)
    assembly_payloads.sort(key=lambda item: str(item["assembly"]["accession"]))
    return {
        "release_version": RELEASE_VERSION,
        "assemblies": {str(payload["assembly"]["accession"]): payload for payload in assembly_payloads},
    }

def build_site(
    site_root: Path,
    downloads_root: Path,
    jbrowse_root: Path | None = None,
    studies_path: Path | None = None,
    hf_data_base_url: str | None = None,
) -> dict[str, object]:
    """Generate study, source, and assembly pages into a disposable site copy."""
    global SITE_ROOT, JBROWSE_CONFIG_ROOT, JBROWSE_OVERLAYS, HF_DATA_BASE_URL
    global SITE_COVERAGE_EN, SITE_COVERAGE_ZH
    SITE_ROOT = site_root.resolve()
    HF_DATA_BASE_URL = (
        validate_release_base_url(hf_data_base_url)
        if hf_data_base_url
        else f"downloads/{RELEASE_VERSION}"
    )
    if jbrowse_root is not None:
        JBROWSE_CONFIG_ROOT = jbrowse_root.resolve()
        JBROWSE_OVERLAYS = JBROWSE_CONFIG_ROOT
    studies_path = (studies_path or (downloads_root / "studies")).resolve()
    study_metadata = load_study_metadata(studies_path)
    source_metadata = load_sources(studies_path)
    source_ids = [str(source["source_id"]) for source in source_metadata]
    expected = [f"BATTER_S1_{number:03d}" for number in range(1, 23)]
    if source_ids != expected:
        raise RuntimeError("v0.3.0 study metadata does not contain the expected 22 ordered source IDs")

    for directory in (SITE_ROOT / "records", SITE_ROOT / "assemblies", SITE_ROOT / "studies", SITE_ROOT / "data", SITE_ROOT / "assets"):
        directory.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, object]] = []
    for item in source_metadata:
        source_id = str(item["source_id"])
        source = {
            "source_id": source_id,
            "species": item["species"],
            "published_year": str(item["year"]),
            "reference_genome": item["assembly"],
            "pmid": item["pmid"],
            "paper_title": item["title"],
            "doi": item["doi"],
            "pmc": item["pmc"],
            "raw_data_accessions": ";".join(item["raw_data_accessions"]),
            "assay_family": item["assay"],
            "blocker_or_note": item["known_limitations"],
        }
        manifest = {
            "dataset_id": item["dataset_id"],
            "raw_data_url": item["raw_data_url"],
            "pubmed_url": item["pubmed_url"],
            "doi_url": item["doi_url"],
            "pmc_url": item["pmc_url"],
            "known_limitations": item["known_limitations"],
        }
        source_gff3 = downloads_root / "records" / source_id / "endpoints.gff3"
        if source_gff3.is_file():
            with source_gff3.open(encoding="utf-8") as gff3_handle:
                observed_count = sum(1 for line in gff3_handle if line and not line.startswith("#"))
        else:
            observed_count = 0
        if observed_count != int(item["record_count"]):
            raise RuntimeError(f"{source_id}: generated source GFF3 has {observed_count} records, expected {item['record_count']}")
        status = str(item["release_status"])
        records.append({
            "source_id": source_id,
            "source": source,
            "manifest": manifest,
            "assembly": source["reference_genome"],
            "year": int(source["published_year"]),
            "evidence_class": "audit_only" if status == "audit_only" else item["evidence_class"],
            "release_status": status,
            "record_count": observed_count,
            "has_jbrowse": bool(item["has_jbrowse"]),
        })

    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for record in records:
        grouped[str(record["assembly"])].append(record)
    total_endpoint_records = sum(int(record["record_count"]) for record in records)
    SITE_COVERAGE_EN = (
        f"{len(grouped)} assemblies · {len(records)} source datasets · "
        f"{total_endpoint_records:,} endpoint records"
    )
    SITE_COVERAGE_ZH = (
        f"{len(grouped)} 个参考组装 · {len(records)} 个来源数据集 · "
        f"{total_endpoint_records:,} 条端点记录"
    )
    source_index = {str(record["source_id"]): record["source"] for record in records}
    record_index = {str(record["source_id"]): record for record in records}

    study_records: list[dict[str, object]] = []
    for metadata in study_metadata:
        pmid = str(metadata["pmid"])
        study_id = f"PMID_{pmid}"
        sources = metadata["sources"]
        study_source_ids = [str(source["source_id"]) for source in sources]
        if not study_source_ids or any(source_id not in record_index for source_id in study_source_ids):
            raise RuntimeError(f"{study_id}: metadata lists a missing or unknown source_id")
        group = [record_index[source_id] for source_id in study_source_ids]
        declared_count = int(metadata["record_count"])
        source_count = sum(int(record["record_count"]) for record in group)
        if declared_count != source_count:
            raise RuntimeError(f"{study_id}: metadata declares {declared_count} records, source metadata sums to {source_count}")
        study_dir = studies_path / study_id
        required_files = ["metadata.tsv", "metadata.json"]
        if declared_count > 0:
            required_files.append("endpoints.gff3.gz")
        for filename in required_files:
            if not (study_dir / filename).is_file():
                raise RuntimeError(f"{study_id}: canonical study package is missing {filename}")
        if declared_count > 0:
            with gzip.open(study_dir / "endpoints.gff3.gz", "rt", encoding="utf-8") as handle:
                observed_study_count = sum(1 for line in handle if line.strip() and not line.startswith("#"))
            if observed_study_count != declared_count:
                raise RuntimeError(f"{study_id}: GFF3 contains {observed_study_count} records, expected {declared_count}")
        study_records.append({
            "pmid": pmid,
            "study_id": study_id,
            "metadata": metadata,
            "sources": group,
            "source_ids": study_source_ids,
            "record_count": declared_count,
            "study_dir": study_dir,
        })

    for record in records:
        (SITE_ROOT / "records" / f"{record['source_id']}.html").write_text(
            record_page(record, len(grouped[str(record["assembly"])])), encoding="utf-8"
        )
    for study in study_records:
        (SITE_ROOT / "studies" / f"{study['study_id']}.html").write_text(
            study_page(str(study["pmid"]), study["sources"], study["study_dir"]), encoding="utf-8"
        )
    for assembly, group in grouped.items():
        (SITE_ROOT / "assemblies" / f"{assembly}.html").write_text(assembly_page(assembly, group), encoding="utf-8")

    catalog_sources = [{
        "source_id": record["source_id"], "species": record["source"]["species"],
        "year": record["year"], "assay": record["source"]["assay_family"], "assembly": record["assembly"],
        "pmid": record["source"]["pmid"], "evidence_class": record["evidence_class"],
        "release_status": record["release_status"], "record_count": record["record_count"],
        "raw_data_accessions": split_accessions(record["source"]["raw_data_accessions"]),
        "raw_data_url": record["manifest"].get("raw_data_url", ""),
        "has_jbrowse": record["has_jbrowse"], "record_url": f"records/{record['source_id']}.html",
        "study_id": f"PMID_{record['source']['pmid']}",
        "study_url": f"studies/PMID_{record['source']['pmid']}.html",
        "study_gff3_url": (
            study_download_url(str(record["source"]["pmid"]), "endpoints.gff3.gz")
            if int(record["record_count"]) > 0 and record["release_status"] != "audit_only" else None
        ),
    } for record in records]
    catalog_studies = []
    for study in study_records:
        source_group = study["sources"]
        pmid = str(study["pmid"])
        first_source = source_group[0]["source"]
        study_path = f"studies/{study['study_id']}"
        catalog_studies.append({
            "pmid": pmid,
            "study_id": study["study_id"],
            "title": first_source["paper_title"],
            "year": min(int(record["year"]) for record in source_group),
            "species": sorted({str(record["source"]["species"]) for record in source_group}),
            "assemblies": sorted({str(record["assembly"]) for record in source_group}),
            "source_ids": study["source_ids"],
            "source_count": len(source_group),
            "record_count": study["record_count"],
            "gff3_url": release_download_url(f"{study_path}/endpoints.gff3.gz") if int(study["record_count"]) > 0 else None,
            "metadata_tsv_url": release_download_url(f"{study_path}/metadata.tsv"),
            "metadata_json_url": release_download_url(f"{study_path}/metadata.json"),
            "gene_associations_url": release_download_url(f"{study_path}/gene_associations.tsv.gz") if (study["study_dir"] / "gene_associations.tsv.gz").is_file() else None,
            "condition_observations_url": release_download_url(f"{study_path}/condition_observations.tsv.gz") if (study["study_dir"] / "condition_observations.tsv.gz").is_file() else None,
            "study_url": f"studies/{study['study_id']}.html",
        })
    catalog_assemblies = []
    for assembly, group in grouped.items():
        source_ids_for_assembly = [str(record["source_id"]) for record in group]
        catalog_assemblies.append({
            "assembly": assembly,
            "assembly_url": assembly_accession_url(assembly),
            "species": sorted({str(record["source"]["species"]) for record in group}),
            "source_ids": source_ids_for_assembly,
            "track_count": len(group),
            "published_track_count": sum(record["release_status"] != "audit_only" for record in group),
            "record_count": sum(int(record["record_count"]) for record in group),
            "years": sorted({int(record["year"]) for record in group}),
            "assays": sorted({str(record["source"]["assay_family"]) for record in group}),
            "evidence_classes": sorted({str(record["evidence_class"]) for record in group}),
            "status": "published" if any(record["release_status"] != "audit_only" for record in group) else "audit_only",
            "browser_config": assembly_browser_config(assembly, group),
            "page_url": f"assemblies/{assembly}.html",
        })
    catalog = {
        "release_version": RELEASE_VERSION,
        "language": "en",
        "studies": catalog_studies,
        "sources": catalog_sources,
        "assemblies": catalog_assemblies,
        "downloads": {
            "release_manifest": release_download_url("release.json"),
            "checksums": release_download_url("SHA256SUMS.txt"),
        },
    }
    (SITE_ROOT / "data/catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    (SITE_ROOT / "data/assemblies.json").write_text(
        json.dumps(build_assemblies_json(grouped), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    (SITE_ROOT / "assets/data-release.json").write_text(
        json.dumps({
            "releaseVersion": RELEASE_VERSION,
            "baseUrl": HF_DATA_BASE_URL,
            "revision": release_revision(HF_DATA_BASE_URL),
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    endpoint_total = sum(int(record["record_count"]) for record in records)
    browser_track_total = sum(bool(record["has_jbrowse"]) for record in records)
    source_total = len(records)
    index_content = f"""
<main><section class="hero"><div class="page-shell hero-inner"><p class="eyebrow">BTED v0.3.0</p><h1>{bi('Explore bacterial transcript 3′ ends by genome.', '按基因组浏览细菌转录 3′ 端数据。')}</h1><p>{bi('Download each paper as one PMID folder with its GFF3 and metadata. Genome views still keep each source dataset as a separate track.', '按 PMID 下载每篇研究的 GFF3 和元数据；基因组浏览器中各来源数据仍分别显示。')}</p><div class="hero-actions"><a class="button primary" href="sources.html">{bi('Browse genomes', '浏览基因组')}</a><a class="button" href="catalog.html">{bi('Download by study', '按研究下载')}</a></div></div></section>
<section class="page-shell stat-strip"><div><strong>{len(grouped)}</strong><span>{bi('reference assemblies', '参考组装')}</span></div><div><strong>{source_total}</strong><span>{bi('source datasets', '来源数据集')}</span></div><div><strong>{endpoint_total:,}</strong><span>{bi('endpoint records', '端点记录')}</span></div><div><strong>{browser_track_total}</strong><span>{bi('browser-ready tracks', '可浏览轨道')}</span></div></section>
<section class="page-shell feature-grid"><article><h2>{bi('Genome browser', '基因组浏览器')}</h2><p>{bi('Open a reference assembly to compare its independent source tracks in JBrowse.', '打开参考组装，在 JBrowse 中比较各个独立来源轨道。')}</p></article><article><h2>{bi('Study files', '研究文件')}</h2><p>{bi('Each PMID package groups endpoint features and metadata for its source datasets.', '每个 PMID 文件包汇总该研究来源数据的端点和元数据。')}</p></article><article><h2>{bi('Readable metadata', '可读元数据')}</h2><p>{bi('Open metadata.tsv in a spreadsheet, or use metadata.json for full provenance.', 'metadata.tsv 可用表格软件打开；metadata.json 保存完整来源信息。')}</p></article></section></main>"""
    (SITE_ROOT / "index.html").write_text(page("Home", "index", index_content), encoding="utf-8")

    species_values = sorted({species for item in catalog_assemblies for species in item["species"]})
    assay_values = sorted({assay for item in catalog_assemblies for assay in item["assays"]})
    evidence_values = sorted({evidence for item in catalog_assemblies for evidence in item["evidence_classes"]})
    species_options = "".join(f'<option value="{esc(value.lower())}">{esc(value)}</option>' for value in species_values)
    assay_options = "".join(f'<option value="{esc(value.lower())}">{esc(value)}</option>' for value in assay_values)
    evidence_options = "".join(
        f'<option value="{esc(value)}">{esc(EVIDENCE_LABELS.get(value, value))}</option>'
        for value in evidence_values
    )
    genome_rows = []
    for item in catalog_assemblies:
        species_text = " / ".join(item["species"])
        assay_text = " / ".join(item["assays"])
        years = item["years"]
        year_text = str(years[0]) if len(years) == 1 else f"{years[0]}–{years[-1]}"
        study_label = "study" if item["track_count"] == 1 else "studies"
        evidence_text = " / ".join(
            EVIDENCE_LABELS.get(value, value) for value in item["evidence_classes"]
        )
        evidence_badge = status_badge(item["status"]) if item["status"] == "audit_only" else ""
        browser = (
            f'<a class="row-action secondary" href="{jbrowse_href(item["assembly"])}">JBrowse</a>'
            if item["browser_config"] else ""
        )
        sources = " ".join(item["source_ids"])
        accession_search = " ".join(
            accession
            for source_id in item["source_ids"]
            for accession in split_accessions(source_index[source_id]["raw_data_accessions"])
        )
        genome_rows.append(f"""<tr data-catalog-row data-species="{esc('|'.join(x.lower() for x in item['species']))}" data-assay="{esc('|'.join(x.lower() for x in item['assays']))}" data-evidence="{esc('|'.join(item['evidence_classes']))}" data-search="{esc((item['assembly']+' '+species_text+' '+assay_text+' '+sources+' '+accession_search).lower())}">
          <td class="select-cell"><input type="checkbox" data-download-choice value="{esc(item['assembly'])}" data-records="{item['record_count']}" aria-label="Select {esc(item['assembly'])}"></td>
          <td class="genome-identity"><a class="genome-name" href="{item['page_url']}"><em>{esc(species_text)}</em></a><small><code>{esc(item['assembly'])}</code> <a class="external-accession" href="{assembly_accession_url(item['assembly'])}" target="_blank" rel="noopener" aria-label="Open {esc(item['assembly'])} in NCBI Datasets">NCBI ↗</a></small></td>
          <td class="experiment-summary"><strong>{esc(assay_text)}</strong><small>{item['track_count']} {study_label} · {year_text}</small></td>
          <td class="evidence-summary">{esc(evidence_text)}{evidence_badge}</td>
          <td class="number endpoint-total"><strong>{int(item['record_count']):,}</strong></td>
          <td class="row-actions"><a class="row-action primary" href="{item['page_url']}">Details</a>{browser}</td>
        </tr>""")
    sources_content = f"""
<main class="page-shell genome-directory"><div class="page-heading directory-heading"><div><p class="eyebrow">BTED v0.3.0</p><h1>{bi('Genome assemblies', '基因组目录')}</h1><p>{bi('Find an exact reference genome, inspect its independent experimental studies, or open all available tracks in one coordinate view.', '查找精确参考基因组，查看独立实验研究，或在统一坐标下打开所有可用轨道。')}</p></div></div>
<section class="directory-stats" aria-label="Database coverage"><div><strong data-visible-count>{len(grouped)}</strong><span>reference assemblies shown</span></div><div><strong>{len(study_records)}</strong><span>study packages</span></div><div><strong>{source_total}</strong><span>source datasets</span></div><div><strong>{endpoint_total:,}</strong><span>endpoint records</span></div></section>
<section class="filters genome-filters" aria-label="Filter genome assemblies"><label><span>{bi('Search', '搜索')}</span><input type="search" data-filter-search placeholder="Organism, strain, assembly or data accession"></label><label><span>{bi('Organism', '物种')}</span><select data-filter="species"><option value="">All organisms</option>{species_options}</select></label><label><span>{bi('Assay', '方法')}</span><select data-filter="assay"><option value="">All assays</option>{assay_options}</select></label><label><span>{bi('Evidence', '证据')}</span><select data-filter="evidence"><option value="">All evidence types</option>{evidence_options}</select></label></section>
<section class="catalog-selection" aria-label="Selected genome downloads"><div><button type="button" class="text-button" data-select-visible>Select visible</button><button type="button" class="text-button" data-clear-all>Clear</button></div><p><strong data-selected-count>0</strong> genomes selected <span aria-hidden="true">·</span> <span data-selected-records>0</span> records</p><button type="button" class="button primary" data-download-selected disabled>{bi('Download selected ZIP', '下载所选 ZIP')}</button></section><p class="download-status catalog-download-status" data-download-status aria-live="polite"></p>
<div class="table-wrap genome-table-wrap"><table class="source-table genome-table"><thead><tr><th class="select-cell"><span class="visually-hidden">Select</span></th><th>{bi('Genome', '基因组')}</th><th>{bi('Experimental data', '实验数据')}</th><th>{bi('Evidence', '证据')}</th><th>{bi('3′ ends', '3′ 端点')}</th><th>{bi('Access', '访问')}</th></tr></thead><tbody>{''.join(genome_rows)}</tbody></table></div><p class="empty-state" data-empty-state hidden>{bi('No genomes match the filters.', '没有符合筛选条件的基因组。')}</p>
<p class="directory-footnote">One row represents one exact reference assembly. Studies sharing that assembly remain separate tracks in the genome view.</p></main>"""
    (SITE_ROOT / "sources.html").write_text(page("Genomes", "sources", sources_content), encoding="utf-8")

    study_download_rows = []
    for study in catalog_studies:
        pmid = str(study["pmid"])
        title = str(study["title"])
        organism_text = " / ".join(study["species"])
        assembly_text = ", ".join(study["assemblies"])
        links = [
            f'<a href="{study["metadata_tsv_url"]}">metadata.tsv</a>',
            f'<a href="{study["metadata_json_url"]}">metadata.json</a>',
        ]
        if study["gff3_url"]:
            links.insert(0, f'<a href="{study["gff3_url"]}">endpoints.gff3.gz</a>')
        if study["gene_associations_url"]:
            links.append(f'<a href="{study["gene_associations_url"]}">gene associations</a>')
        if study["condition_observations_url"]:
            links.append(f'<a href="{study["condition_observations_url"]}">condition observations</a>')
        study_download_rows.append(f"""<tr data-study-row data-search="{esc((pmid+' '+title+' '+organism_text+' '+assembly_text+' '+' '.join(study['source_ids'])).lower())}">
          <td><a class="source-id" href="{study['study_url']}">PMID_{esc(pmid)}</a><small>{study['source_count']} source dataset(s)</small></td>
          <td>{esc(title)}<small><em>{esc(organism_text)}</em></small></td>
          <td><code>{esc(assembly_text)}</code></td>
          <td class="number">{int(study['record_count']):,}</td>
          <td class="study-download-links">{' · '.join(links)}</td></tr>""")

    catalog_content = f"""
<main class="page-shell"><div class="page-heading"><div><p class="eyebrow">v0.3.0</p><h1>{bi('Download by study', '按研究下载')}</h1><p>{bi('The primary public package is one folder per PMID. Each folder contains a study GFF3, readable metadata.tsv and full metadata.json; study-specific supplementary tables stay with that study.', '规范数据按 PMID 分目录。每个目录包含研究 GFF3、便于阅读的 metadata.tsv 和完整 metadata.json；研究专属补充表也放在对应目录。')}</p></div></div>
<section class="panel download-help"><h2>{bi('Shared release files', '共享发布文件')}</h2><div class="file-pair"><div><code>release.json</code><span>{bi('Release version, study package inventory and record counts.', '版本号、研究文件清单和记录数。')}</span></div><div><code>SHA256SUMS.txt</code><span>{bi('Checksums for the published release files.', '发布文件的校验值。')}</span></div></div><p><a class="button" href="{release_download_url('release.json')}">release.json</a> <a class="button" href="{release_download_url('SHA256SUMS.txt')}">SHA256SUMS.txt</a></p><p>{bi('GFF3 coordinates are 1-based single-base features. Source-specific IDs and annotation fields are retained in each feature. metadata.tsv is a readable summary; metadata.json carries full provenance.', 'GFF3 使用 1-based 单碱基坐标，并保留来源编号和注释字段。metadata.tsv 便于阅读；metadata.json 保存完整来源信息。')}</p></section>
<section class="panel study-download-panel"><h2>{bi('Study packages', '研究文件包')}</h2><div class="table-wrap"><table class="source-table download-table"><thead><tr><th>PMID / source count</th><th>{bi('Publication / organisms', '论文 / 物种')}</th><th>{bi('Reference assembly', '参考组装')}</th><th>{bi('Records', '记录数')}</th><th>{bi('Files in study folder', '研究目录文件')}</th></tr></thead><tbody>{''.join(study_download_rows)}</tbody></table></div><p class="section-note">Each row links to one PMID package. A study with multiple source datasets keeps them together and preserves each <code>source_id</code>.</p></section>
</main>"""
    (SITE_ROOT / "catalog.html").write_text(page("Download", "catalog", catalog_content), encoding="utf-8")

    methodology_content = f"""<main class="page-shell prose"><div class="page-heading"><div><p class="eyebrow">Data notes</p><h1>{bi('About BTED and its data', 'BTED 与数据说明')}</h1></div></div><section><h2>{bi('About this database', '数据库简介')}</h2><p>{bi('BTED makes public bacterial transcript 3′-end datasets easier to find, compare, download, and inspect in a genome browser.', 'BTED 让公开的细菌转录 3′ 端数据更容易查找、比较、下载和在基因组浏览器中查看。')}</p><p>{bi(f'The v0.3.0 release includes {source_total} source datasets across {len(grouped)} assemblies, with {endpoint_total:,} endpoint records. See the project repository for release documentation and source material.', f'v0.3.0 发布版包含 {source_total} 个来源数据集、覆盖 {len(grouped)} 个组装和 {endpoint_total:,} 条端点记录。发布说明和来源材料见项目仓库。')} <a href="{REPOSITORY_URL}">GitHub</a></p></section><section><h2>{bi('Assembly grouping', '按组装聚合')}</h2><p>{bi('Datasets are grouped only when the complete reference assembly accession is identical. Grouping changes the presentation, not source identity.', '只有完整参考组装 accession 一致时才聚合；聚合只改变展示方式，不改变来源身份。')}</p></section><section><h2>{bi('Independent tracks', '独立轨道')}</h2><p>{bi('A track represents one processed source. Agreement between tracks is useful for comparison but is not automatically a consensus or functional proof.', '一个轨道对应一个处理来源。不同轨道的一致性可用于比较，但不自动构成共识或功能证明。')}</p></section><section><h2>{bi('Interpreting records', '理解端点记录')}</h2><p>{bi('Observed signals, author-called endpoints and literature-curated records have different meanings. A transcript 3′-end record is not automatically a functionally proven terminator.', '实验信号、作者标注的端点和文献整理记录含义不同。转录本 3′ 端记录不自动等同于已验证的功能性终止子。')}</p></section><section><h2>{bi('Files', '文件')}</h2><p>{bi('GFF3 is the interoperable coordinate file; every endpoint is a 1-based single-base feature. The score column contains a dot, and original study-specific scores remain in attributes. Metadata records provenance, publications, accessions and limitations.', 'GFF3 是通用坐标文件；每个端点为 1-based 单碱基 feature。score 列为“.”，原始研究分数保留在属性中。元数据记录来源、文献、登录号和限制。')}</p></section></main>"""
    (SITE_ROOT / "methodology.html").write_text(page("Data notes", "methodology", methodology_content), encoding="utf-8")

    (SITE_ROOT / "about.html").write_text(legacy_redirect_page("About", "methodology.html"), encoding="utf-8")
    (SITE_ROOT / "quick-search.html").write_text(
        legacy_redirect_page("Search genome data", "sources.html", "query"), encoding="utf-8"
    )
    (SITE_ROOT / "accession-range-demo.html").write_text(
        legacy_redirect_page("Search genome data", "sources.html", "accession"), encoding="utf-8"
    )
    browser_html = page(
        "Genome browser",
        "browser",
        browser_page_content(),
        extra_scripts=f'<script src="assets/browser-wrapper.js?v={SITE_ASSET_VERSION}"></script>',
    )
    (SITE_ROOT / "browser.html").write_text(browser_html, encoding="utf-8")

    print(f"PASS  Generated v0.3.0 site: {len(study_records)} study pages, {len(grouped)} assembly pages, {len(records)} source pages")
    return catalog


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-root", type=Path, required=True, help="Disposable site copy to receive generated HTML and JSON")
    parser.add_argument("--downloads-root", type=Path, required=True, help="Generated downloads/v0.3.0 directory")
    parser.add_argument("--jbrowse-root", type=Path, help="JBrowse package containing v0.3.0 configs")
    parser.add_argument("--studies-dir", type=Path, default=STUDIES_PATH)
    parser.add_argument("--hf-data-base-url", help="Pinned Hugging Face resolve URL ending in /v0.3.0")
    args = parser.parse_args()
    build_site(args.site_root, args.downloads_root, args.jbrowse_root, args.studies_dir, args.hf_data_base_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
