# D1 database

The Worker uses the `BTED_DB` binding for `bted-catalog`. Configuration is in [`worker/wrangler.jsonc`](../worker/wrangler.jsonc). D1 holds metadata and file registrations; scientific-file bytes remain at fixed Hugging Face revisions.

## Files and lifecycle

| Path | Purpose |
|---|---|
| `schema.sql` | Base experimental-release schema |
| `migrations/0002…0010` | Ordered schema and historical upgrades; original numbering retained |
| `changes/<date>-<purpose>/apply.sql` | Reviewed correction with explicit prior-version conditions |
| `changes/<date>-<purpose>/rollback.sql` | Restore the corresponding prior state |
| `../tests/fixtures/d1-seed.sql` | Test-only input, not production initialization |
| `../dist/d1/<operation>/` | Ignored local import bundles, exports and SQLite copies |

Inspect the existing schema before applying missing upgrades. Migration `0007` retires old metadata tables and requires verified scalar tables and recoverable exports. Historical upgrades were applied through explicit SQL; Wrangler's migration ledger may not reflect them.

## Table groups

| Tables | Contents |
|---|---|
| `release_versions`, `publications`, `assemblies`, `sources`, `contigs`, `endpoints`, `assets`, `tracks` | Experimental provenance, coordinates and assets |
| `hf_runtime_release`, `hf_runtime_genomes`, `hf_runtime_files` | Scalar GEM metadata and fixed scientific-file registrations |
| `hf_directory_releases`, `hf_directory_genomes`, `hf_directory_search` | Versioned directories, pagination and search |
| `bted_collections` | Active directory and default taxonomy per collection |
| `bted_taxonomy_records` | Classification, matching status and source evidence |
| `gtdb_genome_assets` | GTDB per-genome file revisions and groups |

Usage counts have [separate aggregate tables](../docs/USAGE_ANALYTICS.md).

## Reviewed corrections

| Directory | Transition | Change |
|---|---|---|
| `changes/2026-10-22-taxonomy/` | Experimental v2 → v4 | Separate taxonomy systems; default to NCBI |
| `changes/2026-10-22-predictions/` | v4 → v5 | Restore registered predictions |
| `changes/2026-10-22-experimental-membership/` | v5 → v6 | Include only the 20 references with published experimental endpoints |

The short version names refer to the full directory identifiers in SQL and `data/registry/collections.json`. Rollback also requires matching Worker/cache bindings. Old directory rows remain available for recovery.

## Prepare a correction

1. Export the affected current D1 fields; record the active version and recovery bookmark.
2. Generate a new version with the existing preparation script. Keep sources, verification, apply and rollback together.
3. Apply it to a local SQLite copy and check affected keys, counts, coordinate/file versions and foreign keys.
4. Execute the reviewed remote SQL and read back the changed state. Update page bindings and deploy only after the versions agree.
5. Keep large exports, temporary SQL and production backups outside Git.

[Collection rules](../docs/COLLECTIONS.md) · [Deployment](../docs/deployment.md) · [Query costs](../docs/D1_METADATA.md)
