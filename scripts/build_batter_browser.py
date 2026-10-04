"""Add the uploaded BATTER augmentation to the existing genome directory."""
import json
import shutil
import re
from pathlib import Path
from build_v0_4_site import page


def build(site_root):
    catalogue = Path(__file__).resolve().parents[1] / "data/registry/batter-browser.json"
    data = json.loads(catalogue.read_text(encoding="utf-8"))
    shutil.copyfile(catalogue, site_root / "assets/batter-browser.json")
    directory = site_root / "genomes.html"
    html = directory.read_text(encoding="utf-8")
    selector = '''<label>Data type<select data-genome-dataset><option value="">All data</option><option value="experimental">Experimental</option><option value="prediction">Prediction</option><option value="augmentation">Augmentation</option></select></label>'''
    html = html.replace('<label class="mobile-sort">', selector + '<label class="mobile-sort">', 1)
    html = html.replace('</select></label>\n    <button class="mobile-sort-direction"', '<option value="predictions">Predictions</option><option value="training">Training regions</option></select></label>\n    <button class="mobile-sort-direction"', 1)
    html = html.replace('</tr></thead>', '<th class="number" aria-sort="none"><button type="button" data-sort="predictions">Predictions</button></th><th class="number" aria-sort="none"><button type="button" data-sort="training">Training regions</button></th></tr></thead>', 1)
    html = html.replace('</td>\n</tr>', '</td><td data-label="Predictions" class="number" data-prediction-count>0</td><td data-label="Training regions" class="number" data-augmentation-count>0</td>\n</tr>')
    html = re.sub(r'of (\d+) genomes', r'of <span data-total-count>\1</span> genomes', html, count=1)
    html = html.replace('data-genome-search-form>', 'data-genome-search-form inert>', 1)
    html = html.replace('<div class="genome-result-count" role="status">', '<p class="genome-load-status" data-genome-load-status role="status">Loading genomes…</p><div class="genome-result-count" role="status" hidden>', 1)
    html = html.replace('<tbody data-genome-results>', '<tbody data-genome-results hidden>', 1)
    controls = '''<div class="batter-pagination"><button class="button" type="button" data-genome-prev disabled>Previous</button><span data-genome-page-number></span><button class="button" type="button" data-genome-next disabled>Next</button><button class="button" type="button" data-genome-retry hidden>Retry</button></div><noscript><p>Enable JavaScript to search all genomes. Experimental genomes are listed above.</p><style>[data-genome-results][hidden] { display: table-row-group !important; } .genome-result-count[hidden] { display: block !important; } [data-genome-load-status] { display: none; }</style></noscript>'''
    html = html.replace('</section>\n</main>', controls + '\n</section>\n</main>', 1)
    directory.write_text(html, encoding="utf-8")
    content = '''<main class="page-shell genome-page" data-batter-genome data-genome-page data-preserve-default-view="true">
<p class="breadcrumbs"><a href="../genomes.html">Genomes</a><span>/</span><span>Genome data</span></p>
<section class="genome-title"><div><p class="eyebrow">Genome data</p><h1 data-batter-title>Loading genome…</h1><p class="assembly-id" data-batter-id></p><p data-batter-reference class="muted"></p></div></section>
<section class="genome-summary" aria-label="Genome data summary" data-batter-summary></section>
<section class="browser-panel" data-genome-browser style="--browser-frame-height:820px">
<div class="browser-panel-heading"><div><p class="eyebrow">Genome browser</p><h2>Explore this genome</h2><p>Orange: predictions. Blue: augmentation. Purple: Rfam. Pale: training windows.</p></div><div class="browser-actions"><button class="browser-open" type="button" data-share-view disabled>Share view</button><button class="browser-open" type="button" data-retry-browser>Reload</button><a class="browser-open" data-batter-full hidden>Open full browser ↗</a></div></div>
<p class="browser-share-status" data-browser-status role="status" aria-live="polite">Loading genome data…</p><p class="browser-share-status" data-share-status role="status"></p><input class="browser-share-manual" data-share-manual aria-label="Share link" readonly hidden>
<iframe data-browser-frame title="Genome browser" loading="lazy" referrerpolicy="no-referrer" hidden></iframe></section>
<section class="genome-downloads"><div><p class="eyebrow">Genome files</p><h2>Downloads</h2><p>Published predictions and training data. Upload in progress.</p></div><div class="genome-download-actions" data-batter-downloads></div></section></main>'''
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
            section = '''<section class="genome-summary" aria-label="Computational data summary" data-batter-summary></section><section class="genome-downloads"><div><h2>Prediction and augmentation</h2><p>Orange: predictions. Blue: augmented spans. Pale: training windows.</p></div><div class="genome-download-actions" data-batter-downloads></div></section>'''
            text = text.replace('<section class="browser-panel"', section + '<section class="browser-panel"', 1)
            text = text.replace('src="../assets/genome-page.js"', 'src="../assets/batter-browser.js"')
            path.write_text(text, encoding="utf-8")
    overlays_path = catalogue.parent / "batter-overlays.json"
    overlays = json.loads(overlays_path.read_text(encoding="utf-8")) if overlays_path.exists() else {"genomes": {}}
    registry = {"revision": data["revision"], "experimental": experimental,
                "overlays": overlays["genomes"] if overlays.get("revision") == data["revision"] else {}}
    (site_root / "assets/genome-browsers.json").write_text(json.dumps(registry, indent=2), encoding="utf-8")
