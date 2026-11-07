"""Build the three independent catalogue entry points, reusing the existing UI."""
import argparse
import json
import re
from pathlib import Path

from build_v0_4_site import browser_actions, esc, genome_content, genome_summary, index_content, page

ROOT = Path(__file__).resolve().parents[1]


def collection_nav(current, depth=0):
    prefix = '../' * depth
    return '<nav class="collection-nav" aria-label="Data collections">' + ''.join(
        f'<a href="{prefix}{key}.html"' + (' aria-current="page"' if key == current else '') + f'>{label}</a>'
        for key, label in [('experimental', 'Experimental 3′ ends'), ('gtdb', 'GTDB predictions'), ('gem', 'GEM')]) + '</nav>'


def retire_aggregate_directory(site):
    # Keep bookmarks, not a second directory or its obsolete D1 binding.
    (site / 'genomes.html').write_text('''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>GEM · BTED</title><meta http-equiv="refresh" content="0;url=gem.html"></head><body><a href="gem.html">Browse GEM</a><script>location.replace("gem.html"+location.search+location.hash)</script></body></html>''', encoding='utf-8')
    for name in ('genome-directory.json', 'home.js'):
        (site / 'assets' / name).unlink(missing_ok=True)


def detail_layout(content, collection):
    """Keep reference context visible before the browser, with direct section links."""
    content, count = re.subn(r'(<section class="genome-title">.*?</section>)\s*(<section class="genome-summary genome-counts".*?</section>)',
        r'<div class="genome-heading">\1\2</div>', content, count=1, flags=re.S)
    assert count == 1
    if collection == 'experimental':
        pattern = r'<section class="genome-overview" data-experimental-overview.*?</section>'
        reference = re.search(pattern, content, re.S).group(0).replace('data-experimental-overview', 'id="genome-overview" data-experimental-overview')
        final_id, final_label = 'genome-studies', 'Studies & downloads'
    else:
        pattern = r'<section class="genome-provenance".*?</section><section class="genome-overview".*?</section>'
        reference = '<div class="genome-reference" id="genome-overview">' + re.search(pattern, content, re.S).group(0) + '</div>'
        final_id, final_label = 'genome-downloads', 'Data files'
    content = re.sub(pattern, '', content, count=1, flags=re.S)
    navigation = '<nav class="genome-section-nav" aria-label="On this genome page">' + ''.join(
        f'<a href="#{target}">{label}</a>' for target, label in [('genome-overview', 'Reference & taxonomy'), ('genome-browser', 'Genome browser'), (final_id, final_label)]) + '</nav>'
    return content.replace('<section class="browser-panel"', navigation + reference + '<section class="browser-panel"', 1)


def build(site, release_root=ROOT / 'data/public/v0.4.0'):
    registry_path = ROOT / 'data/registry/collections.json'
    if not registry_path.exists():
        return
    registry = json.loads(registry_path.read_bytes())
    cards = ''.join(f'''<article class="collection-card{' collection-card-primary' if key == 'experimental' else ''}" data-collection-card="{key}">
<h2><a href="{key}.html">{esc(r['label'])} <span aria-hidden="true">↗</span></a></h2>
<p class="collection-number"><strong data-collection-count>Loading…</strong> <span>genomes</span></p>
<p>{esc(r['description'])}</p><p class="collection-version" data-collection-taxonomy>Taxonomy · {esc(r['taxonomy_label'])}</p>
<p class="collection-progress" data-collection-progress></p></article>''' for key in ('experimental', 'gtdb', 'gem') for r in (registry[key],))
    home = f'''<main class="page-shell collection-home"><section class="collection-hero" aria-label="About BTED"><div class="collection-intro"><p class="eyebrow">BTED · Bacterial Transcript 3′ End Database</p>
<h1>Bacterial transcript 3′ ends</h1><p>BTED brings together published bacterial transcript 3′ ends, predicted termination regions and augmented regions. Browse genomic regions, view available signal tracks, and download data.</p>
</div><figure class="hero-diagram"><div class="diagram-heading"><span class="eyebrow">Transcription termination</span></div><img src="assets/termination-motif.svg" width="520" height="310" alt="RNA stem-loop, U-rich tail and transcript 3′ end aligned with a schematic signal peak."><figcaption>Intrinsic termination (schematic).</figcaption></figure></section>
<section class="collection-cards" aria-label="Data collections">{cards}</section>
<section class="collection-phyla" data-phylum-explorer aria-labelledby="collection-phyla-heading">
<div class="collection-phyla-heading"><div><p class="eyebrow">Taxonomy</p><h2 id="collection-phyla-heading">Browse by phylum</h2>
<p>Ranked by genomes in the selected collection. Counts use that collection's taxonomy and do not combine overlapping releases.</p></div>
<label>Collection<select data-phylum-collection aria-label="Collection for phylum counts"></select></label></div>
<p class="collection-phyla-status" data-phylum-status role="status">Loading taxonomy counts…</p>
<div class="home-phyla-chart" data-phylum-chart aria-label="Genome count by phylum"></div>
<a class="text-link" data-phylum-link href="gtdb.html">Open selected collection →</a></section>
<p class="collection-help">Collections are counted separately and may contain overlapping genomes.</p>
<p data-collections-status role="status"></p><button class="button" data-collections-retry hidden>Retry</button>
<section class="collection-guide" id="batter-reference"><h2>Sources and methods</h2><p>Jin, Y., Cui, J., Liu, R. et al. <a href="https://doi.org/10.1186/s40168-026-02454-1">Conserved 3′ stem-loop structures enable comprehensive analysis of bacterial transcription termination in metagenomes.</a> <em>Microbiome</em> 14, 222 (2026).</p><div class="home-reference-links"><a class="button" href="https://github.com/xu-research-lab/BATTER">BATTER code ↗</a></div></section></main>'''
    (site / 'index.html').write_text(page('Home', home, current='home', scripts=('assets/collections.js',)), encoding='utf-8')
    for key, r in registry.items():
        default_sort = 'endpoints' if key == 'experimental' else 'predictions'
        content = index_content([], {}, {}, data_sorts=("endpoints", "predictions") if key == "experimental" else ("predictions", "training") if key == "gem" else ("predictions",), source_filter=key == "gem", sequencing_filter=key == "experimental")
        heading = f'''<div class="page-heading"><div><h1>{esc(r['label'])}</h1><p>{esc(r['description'])}</p></div><a class="text-link" href="methodology.html#organization">Data notes ↗</a></div>
<div class="collection-meta"><p class="collection-version" data-live-taxonomy="{key}">Taxonomy · {esc(r['taxonomy_label'])}</p><p data-live-collection="{key}" class="collection-progress" role="status">Loading summary…</p></div>'''
        content = re.sub(r'<div class="page-heading">.*?</a></div>', lambda _: heading, content, count=1, flags=re.S)
        content = content.replace('<main>', f'<main class="collection-directory" data-directory-collection="{key}">' + collection_nav(key), 1)
        content = content.replace('data-genome-search-form>', f'data-genome-search-form data-genome-prefix="{key}" data-default-sort="{default_sort}" data-genome-pages="api/collections/{key}/directory?v={r["version"]}" inert>')
        # Data type is redundant in collection-specific catalogues.
        # Experimental references all have gene annotations, and genome type
        # is not consistently curated. Neither is a useful experimental filter.
        if key == 'experimental':
            for filter_name, attribute in [('Genome type', 'data-genome-type-filter'), ('Gene annotation', 'data-genome-annotation-filter')]:
                content, removed = re.subn(r'\s*<label>' + re.escape(filter_name) + r'<select ' + attribute + r'>.*?</select></label>', '', content, count=1, flags=re.S)
                assert removed == 1, f'Missing expected experimental filter: {filter_name}'
        if key != 'experimental':
            content = content.replace('title="Also searches study titles and PMID"', '')
        content = content.replace('<option value="unknown">', '<option value="environmental">Environmental</option><option value="unknown">')
        content = content.replace('<div class="genome-result-count" role="status">', '<p data-genome-load-status role="status">Loading genomes…</p><div class="genome-result-count" role="status" hidden>')
        content = content.replace('<tbody data-genome-results>', '<tbody data-genome-results hidden>')
        pagination = '<div class="batter-pagination"><button class="button" data-genome-prev disabled>Previous</button><span data-genome-page-number></span><button class="button" data-genome-next disabled>Next</button><button class="button" data-genome-retry hidden>Retry</button></div><noscript><p>JavaScript is required to load the catalog.</p></noscript>'
        content = content.replace('</section>\n</main>', pagination + '</section>\n</main>')
        (site / f'{key}.html').write_text(page(r['label'], content, current='genomes', scripts=('assets/genome-index.js', 'assets/collections.js')), encoding='utf-8')
        (site / key).mkdir(exist_ok=True)
        if key == 'experimental':
            # One data-free shell serves every active D1 experimental assembly.
            content = genome_content({'assembly': ''}, {}, {}, '../api/collections/experimental/config', d1_metadata=True)
            content = re.sub(r'data-config="[^"]*"', 'data-config=""', content)
            content = content.replace('data-live-experimental>', 'data-live-experimental data-collection="experimental">')
            content = content.replace('<p class="breadcrumbs">', collection_nav(key, 1) + '<p class="breadcrumbs">', 1)
            content = content.replace('href="../genomes.html">Genomes', 'href="../experimental.html">Experimental 3′ ends')
            content = content.replace('<p class="eyebrow">Reference genome</p>', '<p class="eyebrow">Experimental 3′ ends</p>')
            content = detail_layout(content, key)
            content = content.replace('</main>', '<section class="genome-downloads" data-experimental-predictions hidden></section></main>')
            # URLs are checked against D1 and internally resolve to this shell.
            for legacy in (site / key).glob('GCF_*.html'):
                legacy.unlink()
            (site / key / 'genome.html').write_text(page(r['label'], content, current='genomes', depth=1,
                scripts=('../assets/study-metadata.js', '../assets/study-download.js', '../assets/genome-page.js')), encoding='utf-8')
        else:
            content = f'''<main class="page-shell genome-page" data-batter-genome data-genome-page data-collection="{key}" data-preserve-default-view="true">
{collection_nav(key, 1)}<p class="breadcrumbs"><a href="../{key}.html">{esc(r['label'])}</a><span>/</span><span>Genome data</span></p>
<section class="genome-title"><div><p class="eyebrow">{esc(r['label'])}</p><h1 data-batter-title>Loading genome…</h1><p class="assembly-id" data-batter-id></p></div></section>
{genome_summary(loading=True)}
<section class="browser-panel" data-genome-browser id="genome-browser"><div class="browser-panel-heading"><div class="browser-panel-title"><h2>Genome browser</h2>{browser_actions()}</div></div>
<p class="browser-share-status" data-browser-status role="status">Loading genome data…</p><p class="browser-share-status" data-share-status role="status"></p><input class="browser-share-manual" data-share-manual readonly hidden aria-label="Share link">
<iframe data-browser-frame title="Genome browser" loading="lazy" referrerpolicy="no-referrer" hidden></iframe></section>
<section class="genome-provenance" data-batter-provenance hidden></section><section class="genome-overview" data-batter-taxonomy hidden></section>
<section class="genome-downloads" id="genome-downloads"><div><h2>Data files</h2></div><div class="genome-download-actions" data-batter-downloads></div></section></main>'''
            (site / key / 'genome.html').write_text(page(r['label'], detail_layout(content, key), current='genomes', depth=1, scripts=('../assets/batter-browser.js',)), encoding='utf-8')
    # Make the new default explicit across generated and existing navigation; old shared URLs still work.
    notes = site / 'methodology.html'
    if notes.exists():
        text = notes.read_text(encoding='utf-8')
        data_notes = '''<section id="organization"><h2>Collections</h2>
<ul><li><a href="gtdb.html">GTDB predictions</a>: BATTER-TPE results for GTDB R207.0 (2022) assemblies. The directory reports published genomes against the full input set.</li>
<li><a href="experimental.html">Experimental 3′ ends</a>: 20 reference assemblies with published endpoints, predicted regions and signal tracks. NCBI Taxonomy is the default; GTDB R207.0 mappings are shown separately.</li>
<li><a href="gem.html">GEM</a>: Predicted and augmented regions from GEM, IMG, NCBI and published studies. GEM OTU taxonomy uses GTDB R89.</li></ul>
<p>Collections are counted separately; genomes may overlap. Study organism names are reported as published.</p>
<p>Prediction files may include extra contigs from a matched reference; the genome page shows the scope.</p></section>'''
        text = re.sub(r'<section id="organization">.*?</section>', lambda _: data_notes, text, count=1, flags=re.S)
        text = text.replace('href="genomes.html">Browse genomes', 'href="gtdb.html">Browse GTDB predictions')
        notes.write_text(text, encoding='utf-8')
    for path in site.rglob('*.html'):
        if 'jbrowse' in path.relative_to(site).parts:
            continue
        text = path.read_text(encoding='utf-8')
        text = re.sub(r'href="((?:\.\./)*)genomes.html">Genomes', r'href="\1gtdb.html">Collections', text)
        text = re.sub(r'href="((?:\.\./)*)genomes.html" aria-current="page">Genomes', r'href="\1gtdb.html" aria-current="page">Collections', text)
        path.write_text(text, encoding='utf-8')
    retire_aggregate_directory(site)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', type=Path, default=ROOT / 'dist/worker-site')
    build(parser.parse_args().site)
