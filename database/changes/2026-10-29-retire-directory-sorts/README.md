# Retire optional directory sorts

Worker/browser changes deployed on 2026-10-29 as
`b624f306-bed3-4943-9cfd-4f8c454a95ad`. The user's later live-only policy
authorized deleting the indexes; all three DROP statements in migration `0011`
were subsequently applied and their absence checked in `sqlite_schema`.
Worker `4b46ea20-371a-4479-a76f-e3888906d547` also retires the aggregate directory.

The Worker rejects `sort=predictions&direction=asc` and every `sort=training`
request with HTTP 400 before D1 or edge-cache lookup. Collection default
predictions descending remains available. Browser links using the retired sorts
keep their filters and use predictions descending or the collection's default
order. Counts, augmented-region data and the augmentation dataset filter remain.

## Applied order

1. Deploy and check the Worker/browser change first. Check rejected API requests
   without issuing valid directory scans. The visible sorting controls are unchanged.
2. Review current UTC-day account usage and allocate a separate DDL budget.
   Do not infer a remaining daily allowance from rolling-24-hour statistics.
3. Apply only `database/migrations/0011_retire_directory_sorts.sql` to an existing
   database. Never replay the bootstrap schema or other migrations. Record D1's
   official read/write receipt; stop on a quota error without further readback.
4. Check just the three index names in `sqlite_schema` when budget permits.
   Do not run global integrity, foreign-key or FTS checks. Capacity reclaimed
   must be established from D1 statistics, not inferred from the local footprint.

Fresh directory builds use `0005_genome_directory.sql`, which no longer creates
these indexes. No table rows, collection pointers or scientific assets change.

## Current operation

Keep the new Worker if the index operation is interrupted. The removed sorts are
rejected even if only some indexes were dropped. `DROP INDEX IF EXISTS` supports
a later continuation after confirming the receipt and quota state.

There is no index-rebuild rollback: the features are retired. Do not restore a
Worker that accepts these sorts or serves deleted aggregate-directory versions.
Existing full-directory import bundles may contain old CREATE INDEX statements;
do not replay them. Prepared data-only GTDB imports do not require these indexes.

Official production DROP receipts total 564 rows read and 3 rows written. D1
size fell from 446,701,568 to 410,054,656 bytes before the additional taxonomy
cleanup. This observed 36,646,912-byte reduction replaces the earlier local estimate.
Receipts: workspace `BTED/_workspace/outputs/BTED-GTDB-update-2026-10-29/live-only-0001…0004`.

Local assessment: workspace `BTED/_workspace/outputs/BTED-GTDB-update-2026-10-29/index-review.md`.
The three indexes occupied 35.71 MB in the older directory staging copy; that
historical model is not added to the measured production savings.
