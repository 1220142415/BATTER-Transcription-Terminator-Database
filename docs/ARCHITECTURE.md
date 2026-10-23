# Architecture

## Request flow

```text
scripts/stage_site.py → dist/worker-site/ (HTML, JS, CSS, JBrowse)
                              ↓
Browser → worker/src/worker.js → D1 (collections, taxonomy, studies, samples, assets)
             ↓
         Fixed Hugging Face files (FASTA, GFF3, BigWig, indexes)
```

D1 is the production metadata source. JSON is the API response format. Registry TSVs provide curation and build inputs, not a fallback when D1 is unavailable. Scientific-file routes resolve registered revisions and support HTTP Range requests.

## Code locations

| Path | Responsibility |
|---|---|
| `worker/src/worker.js` | Routing, D1 queries, caches, browser configuration, file proxy and usage counts |
| `worker/wrangler.jsonc` | Deployment and D1 binding |
| `site/assets/`, `site/css/` | Directory controls, study cards, downloads and layout |
| `scripts/stage_site.py` | Build orchestration and pinned JBrowse patches |
| `scripts/build_v0_4_site.py` | Experimental pages and shared page components |
| `scripts/build_batter_browser.py`, `scripts/build_collections.py` | Computational pages and collection entry points |
| `jbrowse-plugin/src/plugin.js` | Track glyphs, signal scaling and embedded-browser controls |
| `bted_pipeline/` | Experimental-data normalization and validation |
| `database/` | Schema, ordered migrations and reviewed corrections |
| `data/` | Source evidence, fixed-file manifests and experimental releases |
| `tests/` | Regression tests; fixtures are not production seed data |
| `dist/` | Generated files and local build inputs; ignored by Git |

## Queries and interaction

GTDB and GEM use 25-row server pages. The experimental collection fits in one page, whose D1 response is reused for 60 seconds for local filtering and sorting. Larger collections retain server pagination. Collection versions isolate caches; release pointers have a 60-second edge cache.

Genome source filtering is offered only for GEM. All collections sort through table-header buttons, including on narrow screens where the table scrolls horizontally. Sorting retains the same D1 fields and cached-result behavior.

See [D1 query costs](D1_METADATA.md), [metadata contracts](GENOME_METADATA.md) and [browser behavior](browser-controls.md).
