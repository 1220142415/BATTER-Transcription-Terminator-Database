"""Add the uploaded BATTER augmentation to the existing genome directory."""
import json
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote
from build_v0_4_site import esc, page


class GenomePhyla(HTMLParser):
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr" and "data-genome-row" in attrs:
            self.genomes[attrs["data-sort-accession"].upper()] = attrs.get("data-taxonomy-phylum", "")


def phylum_content(records, experimental):
    # Use the directory's experimental taxonomy for overlapping assemblies.
    genomes = {row[0].upper(): next((taxon[3:] for taxon in row[11].split(";") if taxon.startswith("p__")), "") for row in records}
    genomes.update(experimental)
    counts = Counter(phylum or "Unclassified" for phylum in genomes.values())
    classified = sorted(((name, count) for name, count in counts.items() if name != "Unclassified"), key=lambda item: (-item[1], item[0]))
    top = classified[:8]
    other = sum(count for _name, count in classified[8:])
    if other:
        top.append(("Other phyla", other))
    top.append(("Unclassified", counts["Unclassified"]))
    largest = max(1, *(count for _name, count in top))
    bars = []
    for name, count in top:
        label = esc(name) if name in {"Other phyla", "Unclassified"} else f'<a href="genomes.html?phylum={quote(name, safe="")}">{esc(name)}</a>'
        bars.append(f'<div class="home-phylum-row"><span>{label}</span><div class="home-phylum-bar" aria-hidden="true"><i style="width:{count / largest * 100:.2f}%"></i></div><strong>{count:,}</strong></div>')
    return f'''<section class="home-phyla" aria-labelledby="home-phyla-heading"><div><h2 id="home-phyla-heading">Genomes by phylum</h2><p>{len(genomes):,} catalog genomes. Top 8 phyla shown. Other phyla: remaining classified genomes. Unclassified: no recorded phylum.</p></div><div class="home-phyla-chart" aria-label="Genome count by phylum">{''.join(bars)}</div></section>'''


def build(site_root):
    catalogue = Path(__file__).resolve().parents[1] / "data/registry/batter-browser.json"
    data = json.loads(catalogue.read_text(encoding="utf-8"))
    overlays_path = catalogue.parent / "batter-overlays.json"
    overlays = json.loads(overlays_path.read_text(encoding="utf-8")) if overlays_path.exists() else {"genomes": {}}
    if overlays.get("revision") == data["revision"]:
        data["reference_sizes"] = {genome: [sum(contig["length"] for contig in item["batter_contigs"].values()), len(item["batter_contigs"])]
                                   for genome, item in overlays["genomes"].items()}
    (site_root / "assets/batter-browser.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    directory = site_root / "genomes.html"
    html = directory.read_text(encoding="utf-8")
    phyla = GenomePhyla()
    phyla.genomes = {}
    phyla.feed(html)
    home = site_root / "index.html"
    home.write_text(home.read_text(encoding="utf-8").replace('<section class="home-reference"', phylum_content(data["genomes"], phyla.genomes) + '\n<section class="home-reference"', 1), encoding="utf-8")
    selector = '''<label>Data type<select data-genome-dataset><option value="">All data</option><option value="experimental">Experimental</option><option value="prediction">Prediction</option><option value="augmentation">Augmentation / Rfam</option></select></label>'''
    html = html.replace('<label class="mobile-sort">', selector + '<label class="mobile-sort">', 1)
    html = html.replace('</select></label>\n    <button class="mobile-sort-direction"', '<option value="predictions">Predictions</option><option value="training">Training regions</option></select></label>\n    <button class="mobile-sort-direction"', 1)
    html = html.replace('data-genome-search-form>', 'data-genome-search-form inert>', 1)
    html = html.replace('<div class="genome-result-count" role="status">', '<p class="genome-load-status" data-genome-load-status role="status">Loading genomes…</p><div class="genome-result-count" role="status" hidden>', 1)
    html = html.replace('<tbody data-genome-results>', '<tbody data-genome-results hidden>', 1)
    controls = '''<div class="batter-pagination"><button class="button" type="button" data-genome-prev disabled>Previous</button><span data-genome-page-number></span><button class="button" type="button" data-genome-next disabled>Next</button><button class="button" type="button" data-genome-retry hidden>Retry</button></div><noscript><p>Enable JavaScript to search all genomes. Experimental genomes are listed above.</p><style>[data-genome-results][hidden] { display: table-row-group !important; } .genome-result-count[hidden] { display: block !important; } [data-genome-load-status] { display: none; }</style></noscript>'''
    html = html.replace('</section>\n</main>', controls + '\n</section>\n</main>', 1)
    directory.write_text(html, encoding="utf-8")
    content = '''<main class="page-shell genome-page" data-batter-genome data-genome-page data-preserve-default-view="true">
<p class="breadcrumbs"><a href="../genomes.html">Genomes</a><span>/</span><span>Genome data</span></p>
<section class="genome-title"><div><h1 data-batter-title>Loading genome…</h1><p class="assembly-id" data-batter-id></p></div></section>
<section class="genome-summary" aria-label="Genome data summary" data-batter-summary></section>
<section class="genome-provenance" aria-label="Reference and coordinate provenance" data-batter-provenance hidden></section>
<section class="genome-overview" aria-label="Genome taxonomy" data-batter-taxonomy hidden></section>
<section class="browser-panel" id="genome-browser" data-genome-browser style="--browser-frame-height:820px">
<div class="browser-panel-heading"><div><h2>Genome browser</h2><p>Orange: predictions. Blue: augmentation. Purple: Rfam. Pale: training windows.</p></div><div class="browser-actions"><button class="browser-open" type="button" data-share-view disabled>Share view</button><button class="browser-open" type="button" data-retry-browser>Reload</button><a class="browser-open" data-batter-full hidden>Open full browser ↗</a></div></div>
<p class="browser-share-status" data-browser-status role="status" aria-live="polite">Loading genome data…</p><p class="browser-share-status" data-share-status role="status"></p><input class="browser-share-manual" data-share-manual aria-label="Share link" readonly hidden>
<iframe data-browser-frame title="Genome browser" loading="lazy" referrerpolicy="no-referrer" hidden></iframe></section>
<section class="genome-downloads" id="genome-downloads"><div><h2>Downloads</h2><p>Prediction and training files. Upload in progress.</p></div><div class="genome-download-actions" data-batter-downloads></div></section></main>'''
    generic_page = page("Genome", content, current="genomes", scripts=("../assets/batter-browser.js",), depth=1)
    (site_root / "genomes/genome.html").write_text(generic_page, encoding="utf-8")
    (site_root / "genomes/batter.html").write_text(generic_page, encoding="utf-8")  # Existing shared links.
    ids = {row[0] for row in data["genomes"]}
    experimental = {}
    for path in (site_root / "genomes").glob("*.html"):
        if path.stem.startswith("GCF_"):
            experimental[path.stem] = f"/jbrowse/assemblies/{path.stem}.config.json"
        if path.stem in ids:
            text = path.read_text(encoding="utf-8")
            text = text.replace('data-genome-page data-assembly=', 'data-batter-genome data-preserve-default-view="true" data-genome-page data-assembly=', 1)
            section = '''<section class="genome-summary" aria-label="Computational data summary" data-batter-summary></section><section class="genome-provenance" aria-label="Reference and coordinate provenance" data-batter-provenance hidden></section><section class="genome-downloads"><div><h2>Prediction and training files</h2></div><div class="genome-download-actions" data-batter-downloads></div></section>'''
            text = text.replace('<section class="browser-panel"', section + '<section class="browser-panel"', 1)
            text = text.replace('src="../assets/genome-page.js"', 'src="../assets/batter-browser.js"')
            path.write_text(text, encoding="utf-8")
    registry = {"revision": data["revision"], "experimental": experimental,
                "overlays": overlays["genomes"] if overlays.get("revision") == data["revision"] else {}}
    (site_root / "assets/genome-browsers.json").write_text(json.dumps(registry, indent=2), encoding="utf-8")
