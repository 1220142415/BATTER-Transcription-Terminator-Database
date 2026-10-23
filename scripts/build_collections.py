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
        for key, label in [('gtdb', 'GTDB predictions'), ('experimental', 'Experimental 3′ ends'), ('gem', 'GEM · Legacy')]) + '</nav>'


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
        f'<a href="#{target}">{label}</a>' for target, label in [('genome-overview', 'Reference & classification'), ('genome-browser', 'Genome browser'), (final_id, final_label)]) + '</nav>'
    return content.replace('<section class="browser-panel"', navigation + reference + '<section class="browser-panel"', 1)


def build(site, release_root=ROOT / 'data/public/v0.4.0'):
    registry_path = ROOT / 'data/registry/collections.json'
    if not registry_path.exists():
        return
    registry = json.loads(registry_path.read_bytes())
    cards = ''.join(f'''<article class="collection-card{' collection-card-primary' if key == 'gtdb' else ''}" data-collection-card="{key}">
<p class="eyebrow">{'Model predictions' if key == 'gtdb' else 'Experimental evidence' if key == 'experimental' else 'Archived predictions'}</p>
<h2><a href="{key}.html">{esc(r['label'])} <span aria-hidden="true">↗</span></a></h2>
<p class="collection-number"><strong data-collection-count>Loading…</strong> <span>genomes</span></p>
<p>{esc(r['description'])}</p><p class="collection-version" data-collection-taxonomy>Classification · {esc(r['taxonomy_label'])}</p>
<p class="collection-progress" data-collection-progress></p></article>''' for key, r in registry.items())
    home = f'''<main class="page-shell collection-home"><section class="collection-intro"><p class="eyebrow">BTED · Bacterial Transcript 3′ End Database</p>
<h1>Bacterial RNA 3′ ends</h1><p>Browse experimental records and model predictions by collection.</p>
<a class="button collection-primary" href="gtdb.html">Browse GTDB predictions <span aria-hidden="true">→</span></a></section>
<section class="collection-cards" aria-label="Data collections">{cards}</section>
<p class="collection-help">Collections are counted separately and may contain overlapping genomes.</p>
<p data-collections-status role="status"></p><button class="button" data-collections-retry hidden>Retry collection summary</button>
<section class="collection-guide"><h2>BATTER</h2><p>Jin, Y., Cui, J., Liu, R. et al. <a href="https://doi.org/10.1186/s40168-026-02454-1">Conserved 3′ stem-loop structures enable comprehensive analysis of bacterial transcription termination in metagenomes.</a> <em>Microbiome</em> 14, 222 (2026).</p></section></main>'''
    (site / 'index.html').write_text(page('Home', home, current='home', scripts=('assets/collections.js',)), encoding='utf-8')
    for key, r in registry.items():
        default_sort = 'endpoints' if key == 'experimental' else 'predictions'
        content = index_content([], {}, {}, data_sorts=("endpoints", "predictions") if key == "experimental" else ("predictions", "training") if key == "gem" else ("predictions",), source_filter=key == "gem")
        heading = f'''<div class="page-heading"><div><p class="eyebrow">{'Archived predictions' if key == 'gem' else 'Experimental evidence' if key == 'experimental' else 'Model predictions'}</p><h1>{esc(r['label'])}</h1><p>{esc(r['description'])}</p></div><a class="text-link" href="methodology.html#organization">Data notes ↗</a></div>
<div class="collection-meta"><p class="collection-version" data-live-taxonomy="{key}">Classification · {esc(r['taxonomy_label'])}</p><p data-live-collection="{key}" class="collection-progress" role="status">Loading release summary…</p></div>'''
        content = re.sub(r'<div class="page-heading">.*?</a></div>', lambda _: heading, content, count=1, flags=re.S)
        content = content.replace('<main>', f'<main class="collection-directory" data-directory-collection="{key}">' + collection_nav(key), 1)
        content = content.replace('data-genome-search-form>', f'data-genome-search-form data-genome-prefix="{key}" data-default-sort="{default_sort}" data-genome-pages="api/collections/{key}/directory?v={r["version"]}" inert>')
        dataset = '<label hidden>Data type<select data-genome-dataset><option value="">All data</option><option value="experimental">Experimental</option><option value="prediction">Prediction</option><option value="augmentation">Augmentation / Rfam</option></select></label>'
        if key in ('gem', 'experimental'):
            dataset = dataset.replace('<label hidden>', '<label>')
        if key == 'gem':
            dataset = dataset.replace('<label hidden>', '<label>').replace('<option value="experimental">Experimental</option>', '')
        if key == 'experimental':
            dataset = dataset.replace('<option value="augmentation">Augmentation / Rfam</option>', '')
        content = content.replace('<div class="genome-refine-filters">', '<div class="genome-refine-filters">' + dataset, 1)
        if key != 'experimental':
            content = content.replace('title="Also searches study titles and PMID"', '')
        content = content.replace('<option value="unknown">', '<option value="environmental">Environmental</option><option value="unknown">')
        content = content.replace('<div class="genome-result-count" role="status">', '<p data-genome-load-status role="status">Loading genomes…</p><div class="genome-result-count" role="status" hidden>')
        content = content.replace('<tbody data-genome-results>', '<tbody data-genome-results hidden>')
        pagination = '<div class="batter-pagination"><button class="button" data-genome-prev disabled>Previous</button><span data-genome-page-number></span><button class="button" data-genome-next disabled>Next</button><button class="button" data-genome-retry hidden>Retry</button></div><noscript><p>Enable JavaScript to query this catalogue.</p></noscript>'
        content = content.replace('</section>\n</main>', pagination + '</section>\n</main>')
        (site / f'{key}.html').write_text(page(r['label'], content, current='genomes', scripts=('assets/genome-index.js', 'assets/collections.js')), encoding='utf-8')
        (site / key).mkdir(exist_ok=True)
        if key == 'experimental':
            experiments = json.loads((site / 'assets/genome-browsers.json').read_bytes())['experimental']
            release = json.loads((release_root / 'release.json').read_bytes())
            published = {f['path'].split('/')[1] for f in release['files'] if f['path'].endswith('/endpoints.gff3.gz')}
            for id in experiments:
                if id not in published:
                    # The Worker redirects registered audit-only references to their retained URL.
                    (site / key / f'{id}.html').unlink(missing_ok=True)
                    continue
                content = genome_content({'assembly': id}, {}, {}, f'../api/collections/experimental/{id}/config', d1_metadata=True)
                content = content.replace('data-live-experimental>', 'data-live-experimental data-collection="experimental">')
                content = content.replace('<p class="breadcrumbs">', collection_nav(key, 1) + '<p class="breadcrumbs">', 1)
                content = content.replace('href="../genomes.html">Genomes', 'href="../experimental.html">Experimental 3′ ends')
                content = content.replace('<p class="eyebrow">Reference genome</p>', '<p class="eyebrow">Experimental 3′ ends</p>')
                content = detail_layout(content, key)
                content = content.replace('</main>', '<section class="genome-downloads" data-experimental-predictions hidden></section></main>')
                (site / key / f'{id}.html').write_text(page(id, content, current='genomes', depth=1,
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
<li><a href="experimental.html">Experimental 3′ ends</a>: 20 reference assemblies with published endpoints, model predictions and available signal tracks. NCBI Taxonomy is the default; GTDB R207.0 mappings are shown separately.</li>
<li><a href="gem.html">GEM · Legacy</a>: earlier predictions and augmentation/Rfam data from GEM, IMG, NCBI and published studies. Original classification is retained; its exact GTDB release is unresolved. Predictions are not updated.</li></ul>
<p>Counts are separate for each collection; genomes may overlap. Study organism names are retained independently of classification.</p>
<p>Experimental prediction downloads may cover additional contigs in a sequence-matched computational reference. The genome page reports that scope.</p></section>'''
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


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', type=Path, default=ROOT / 'dist/worker-site')
    build(parser.parse_args().site)
