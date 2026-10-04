"""Add the uploaded BATTER augmentation to the existing genome directory."""
import json
import shutil
from pathlib import Path
from build_v0_4_site import page


def build(site_root):
    catalogue = Path(__file__).resolve().parents[1] / "data/registry/batter-browser.json"
    data = json.loads(catalogue.read_text(encoding="utf-8"))
    shutil.copyfile(catalogue, site_root / "assets/batter-browser.json")
    directory = site_root / "genomes.html"
    html = directory.read_text(encoding="utf-8")
    selector = '''<label class="dataset-picker">Dataset <select data-genome-dataset><option value="experimental">Experimental genomes</option><option value="augmentation">Training augmentation</option></select></label>'''
    html = html.replace('<div class="genome-directory-panel">', selector + '<div class="genome-directory-panel" data-experimental-directory>', 1)
    panel = '''<div class="genome-directory-panel" data-batter-directory hidden>
<form class="genome-filter-bar" data-batter-search-form role="search"><label class="genome-filter-search">Search genomes<input type="search" data-batter-search placeholder="Species, genome or OTU" autocomplete="off"></label><label>Type<select data-batter-type><option value="">All types</option><option>isolate</option><option>MAG</option><option>SAG</option></select></label><label>Records<select data-batter-records><option value="">All genomes</option><option value="yes">With augmentation</option><option value="no">No augmentation</option></select></label></form>
<p class="genome-result-count" data-batter-count role="status">Loading uploaded genomes…</p>
<div class="genome-table-scroll"><table class="genome-directory-table"><thead><tr><th>Organism</th><th>Genome / OTU</th><th>Type</th><th>Augmented spans</th><th>Rfam spans</th><th>Open</th></tr></thead><tbody data-batter-results></tbody></table></div>
<div class="batter-pagination"><button class="button" type="button" data-batter-prev disabled>Previous</button><span data-batter-page></span><button class="button" type="button" data-batter-next disabled>Next</button><button class="button" type="button" data-batter-reload hidden>Retry</button></div>
<p class="muted">Upload in progress. Only indexed genomes are listed. Training windows provide sequence context; counts refer to spans.</p></div>'''
    html = html.replace('</section>\n</main>', panel + '\n</section>\n</main>', 1)
    html = html.replace('</body>', '<script src="assets/batter-browser.js" defer></script></body>')
    directory.write_text(html, encoding="utf-8")
    content = '''<main class="page-shell genome-page" data-batter-genome data-genome-page data-preserve-default-view="true">
<p class="breadcrumbs"><a href="../genomes.html?dataset=augmentation">Genomes</a><span>/</span><span>Training augmentation</span></p>
<section class="genome-title"><div><p class="eyebrow">BATTER · training augmentation</p><h1 data-batter-title>Loading genome…</h1><p class="assembly-id" data-batter-id></p><p data-batter-reference class="muted"></p></div></section>
<section class="genome-summary" aria-label="Training data summary" data-batter-summary></section>
<section class="browser-panel" data-genome-browser style="--browser-frame-height:820px">
<div class="browser-panel-heading"><div><p class="eyebrow">Genome browser</p><h2>Training augmentation</h2><p>Dark blue: augmented spans. Purple: Rfam spans. Pale: training windows.</p></div><div class="browser-actions"><button class="browser-open" type="button" data-share-view disabled>Share view</button><button class="browser-open" type="button" data-retry-browser>Reload</button><a class="browser-open" data-batter-full hidden>Open full browser ↗</a></div></div>
<p class="browser-share-status" data-browser-status role="status" aria-live="polite">Loading genome data…</p><p class="browser-share-status" data-share-status role="status"></p><input class="browser-share-manual" data-share-manual aria-label="Share link" readonly hidden>
<iframe data-browser-frame title="Training augmentation genome browser" loading="lazy" referrerpolicy="no-referrer" hidden></iframe></section>
<section class="genome-downloads"><div><p class="eyebrow">Genome files</p><h2>Downloads</h2><p>Computational training data. Upload in progress.</p></div><div class="genome-download-actions" data-batter-downloads></div></section></main>'''
    (site_root / "genomes/batter.html").write_text(page("Training augmentation", content, current="genomes", scripts=("../assets/batter-browser.js",), depth=1), encoding="utf-8")
    ids = {row[0] for row in data["genomes"]}
    for path in (site_root / "genomes").glob("*.html"):
        if path.stem in ids:
            text = path.read_text(encoding="utf-8")
            link = f'<p><a class="button" href="batter.html?genome={path.stem}">Training augmentation ↗</a></p>'
            text = text.replace('</p></div></section>', '</p>' + link + '</div></section>', 1)
            path.write_text(text, encoding="utf-8")
