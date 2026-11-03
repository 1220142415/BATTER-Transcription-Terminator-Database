# D1 database

The Worker uses the `BTED_DB` binding for `bted-catalog`. Configuration is in [`worker/wrangler.jsonc`](../worker/wrangler.jsonc). D1 holds metadata and file registrations; scientific-file bytes remain at fixed Hugging Face revisions.

## Files and lifecycle

| Path | Purpose |
|---|---|
| `schema.sql` | Base experimental-release schema |
| `migrations/0002…0013` | Ordered schema and historical upgrades; original numbering retained |
| `changes/<date>-<purpose>/apply.sql` | Reviewed correction with explicit prior-version conditions |
| `changes/<date>-<purpose>/rollback.sql` | Restore the corresponding prior state |
| `../tests/fixtures/d1-seed.sql` | Test-only input, not production initialization |
| `../dist/d1/<operation>/` | Ignored local import bundles, exports and SQLite copies |

Inspect the existing schema before applying missing upgrades. Migration `0007` retires old metadata tables and requires verified scalar tables and recoverable exports. Historical upgrades were applied through explicit SQL; Wrangler's migration ledger may not reflect them.

Migration `0011` drops three retired directory-sort indexes. The Worker rejects
these sorts and all three indexes were removed in production on 2026-10-29.
See the [retirement record](changes/2026-10-29-retire-directory-sorts/README.md).

## Table groups

| Tables | Contents |
|---|---|
| `release_versions`, `publications`, `assemblies`, `sources`, `contigs`, `endpoints`, `assets`, `tracks` | Experimental provenance, coordinates and assets |
| `hf_runtime_release`, `hf_runtime_genomes`, `hf_runtime_files` | Scalar GEM metadata and fixed scientific-file registrations |
| `hf_directory_releases`, `hf_directory_genomes`, `hf_directory_search` | Versioned directories, pagination and search |
| `bted_collections` | Active directory and default taxonomy per collection |
| `bted_taxonomy_records` | Classification, matching status and source evidence |
| `gtdb_genome_assets` | GTDB per-genome file revisions and groups |
| `bted_experimental_v05_assemblies`, `bted_experimental_v05_sources`, `bted_experimental_v05_files` | Approved v0.5.0 assemblies, unchanged evidence labels and pinned scientific files |

Usage counts have [separate aggregate tables](../docs/USAGE_ANALYTICS.md).

The current experimental directory has 29 assemblies and 39,896 records. Its
logical version is `202610310000000000000005`, with directory/taxonomy storage
`202610220000000000000006`. Preserve that storage and the reference registry
while they are online dependencies. New v0.5.0 evidence is registered separately;
legacy v0.4.0 coordinate tables and their evidence constraints remain unchanged.
Experimental pages use one shared template and the standard `/api/assemblies/`
metadata contract for both registrations. The Worker reads assembly membership,
source details and per-file HF revisions from D1. Adding approved data and
activating the D1 collection does not require a per-genome page or code change.

Migration `0013` documents the installed extension schema; do not replay the
release SQL or all migrations as a deployment step.

## Reviewed corrections

| Directory | Transition | Change |
|---|---|---|
| `changes/2026-10-22-taxonomy/` | Experimental v2 → v4 | Separate taxonomy systems; default to NCBI |
| `changes/2026-10-22-predictions/` | v4 → v5 | Restore registered predictions |
| `changes/2026-10-22-experimental-membership/` | v5 → v6 | Include only the 20 references with published experimental endpoints |
| `changes/2026-10-23-display-copy/` | Existing directories unchanged | GEM name and R98 display label; remove Cascino exclusion-status text from source cards |
| `changes/2026-10-23-gem-r89/` | Existing directories unchanged | Correct GEM taxonomy display to R89 after direct classification-table comparison |
| `changes/2026-10-25-page-copy/` | Existing directories unchanged | Shorten the three collection descriptions; preserve scientific metadata and counts |

The short version names refer to the full directory identifiers in SQL and `data/registry/collections.json`.
Production now retains only online releases and real online dependencies. Old
directory rows are being deleted, not kept for recovery; historical rollback SQL
is valid only while every referenced row and version still exists. Do not restore
the retired aggregate directory or optional sorts.

## Prepare a correction

1. Read the affected current D1 fields and active versions; do not create a production backup.
2. Generate a new version with the existing preparation script. Keep sources, verification, apply and rollback together.
3. Apply it to a local SQLite copy and check affected keys, counts, coordinate/file versions and foreign keys.
4. Execute the reviewed remote SQL and read back the changed state. Update page bindings and deploy only after the versions agree.
5. After acceptance, delete superseded, unreferenced registrations within the same
   account-wide daily budget. Keep receipts and source methods, not production
   backup snapshots. Preserve actual online scientific-file registrations.

[Collection rules](../docs/COLLECTIONS.md) · [Deployment](../docs/deployment.md) · [Query costs](../docs/D1_METADATA.md)
