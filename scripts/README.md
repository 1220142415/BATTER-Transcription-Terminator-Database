# Script entry points

Run scripts from the repository root. Data preparation produces local artifacts; applying SQL to remote D1 is a separate operation.

| Task | Entry points |
|---|---|
| Build the website | `stage_site.py`; fixed inputs in the deployment guide |
| Build pages | `build_v0_4_site.py`, `build_batter_browser.py`, `build_collections.py` |
| Prepare experimental files | `build_bted_v0_4_release.py`, `prepare_v04_reference.py`, `build_v04_asset_manifest.py` |
| Prepare experimental D1 import | `generate_bted_d1.py`, `bted_v04_d1.py` |
| Prepare scalar metadata and directory | `build_runtime_metadata.py`, `build_genome_directory.py` |
| Initial collection and taxonomy migrations | `prepare_collections_d1.py`, `prepare_taxonomy_d1.py` |
| Experimental membership | `prepare_experimental_membership.py` |
| Reviewed study/sample metadata | `prepare_live_metadata_d1.py` |
| Signal and prediction registrations | `experimental_signals.py`, `experimental_predictions.py` |
| Validate data and site | `validate_bted_v0_4.py`, `validate-site.py`, `validate_repo_layout.py`, `check_markdown_links.py` |
| Preview fixed assets | `serve_v04_preview.py` |

Use `dist/d1/<operation>/` for large import bundles, exports and local SQLite copies. Keep reviewed small corrections under `database/changes/`, with apply/rollback SQL and evidence.

The collection and taxonomy preparation scripts reproduce named migrations with fixed preconditions; they are not general production refresh commands. Later corrections require a new version.

Some v03 modules remain dependencies of the build or frozen-archive validation. `import_hf_metadata_d1.py` handles historical metadata formats; do not rerun the old JSON import against the current scalar-table production database.

[Build and deploy](../docs/deployment.md) · [Database](../database/README.md)
