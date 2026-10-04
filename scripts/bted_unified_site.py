"""Render the v5 unified directory and preserve legacy URL state."""
import re
import json
from urllib.parse import quote


def navigation(depth=0):
    prefix = '../' * depth
    return f'''<header class="site-header"><div class="header-inner">
<a class="brand" href="{prefix}index.html"><span class="brand-mark">BTED</span><span class="brand-name">Bacterial Transcript 3′ End Database</span></a>
<nav class="site-nav" aria-label="Primary navigation"><a href="{prefix}batter-genomes.html">Genome directory</a><a href="{prefix}methodology.html">Data notes</a></nav></div></header>'''


def directory_page():
    from build_v0_4_site import batter_catalog_content, page
    content = batter_catalog_content()
    content = re.sub(r'<p class="batter-experimental-link">.*?</p>', '', content, flags=re.S)
    content = content.replace('collection membership', 'evidence type')
    content = content.replace('<label>Collection<select id="batter-membership"><option value="all">All genomes</option><option value="experimental">Experimental only</option><option value="batter">BATTER only</option><option value="both">Present in both</option></select></label>',
        '<label>Evidence<select id="batter-evidence"><option value="all">All genomes</option><option value="experimental">Experimental data available</option><option value="prediction">Predictions available</option><option value="both">Both available</option></select></label>'
        '<label>Signal files<select id="batter-bigwig"><option value="">Any status</option><option value="true">BigWig available</option><option value="false">No BigWig</option></select></label>')
    content = content.replace('Local preview', 'Latest · v5').replace('Local browser', 'Genome browser')
    html = page('Genome directory', content, current='batter', scripts=('assets/batter-catalog.js',), styles=('css/batter-catalog.css',))
    return re.sub(r'<header class="site-header">.*?</header>', navigation(), html, flags=re.S)


def redirect_page(relative):
    target = '../batter-genomes.html' if relative.parent.name in ('genomes', 'assemblies') else 'batter-genomes.html'
    genome = relative.stem if relative.parent.name in ('genomes', 'assemblies') else None
    # Keep every legacy parameter and only add the exact genome ID for a detail URL.
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Latest · v5</title></head><body>
<a id="unified-link" href="%s">Genome directory</a><script>
const target=new URL(%s,location.href);target.search=location.search;
const genome=%s;
if(genome)target.searchParams.set('genome',genome);
else if(target.searchParams.has('assembly_accession'))target.searchParams.set('genome',target.searchParams.get('assembly_accession'));
target.hash=location.hash;document.getElementById('unified-link').href=target.href;location.replace(target.href);
</script></body></html>''' % (target, json.dumps(target), json.dumps(genome))
