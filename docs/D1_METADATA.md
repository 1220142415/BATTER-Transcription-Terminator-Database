# D1 queries and usage

D1 stores studies, samples, taxonomy, directories, counts and scientific-file registrations. Production uses `BTED_D1_ONLY=on` and `BTED_RUNTIME_FIELDS=on`. A failed D1 request shows an error rather than restoring older TSV or HF metadata. See the [database guide](../database/README.md).

## Query and cache behavior

- GTDB and GEM return 25-row pages. Totals, phylum counts and filter options share aggregation where their filter scope is the same.
- The complete experimental directory is reused in the browser for 60 seconds. Search, header sorting and linked filters use that response; the next interaction after expiry revalidates it. Larger collections use server pagination.
- Directory responses use a seven-day versioned edge cache. Active release pointers use a deployment-keyed 60-second cache.
- The browser retains up to 12 server query results. Errors are not cached and incompatible versions are rejected.
- Study metadata uses short response caches. Scientific files use fixed data and representation versions; production JBrowse configuration and the public scientific-file allowlist come from D1 registrations. The allowlist query reads the 230 current public assets once per Worker isolate per 60 seconds, not once per track. Browser configurations cache for five minutes.
- Search and sorting do not write to D1. Usage counting is separate.

### Retired optional sorts

The deployed Worker rejects predictions ascending and training sorting in either
direction with HTTP 400 before D1 and edge-cache access. Predictions descending
remains the GTDB/GEM default. Old browser links retain their filters and use a
supported order. Augmented-region counts, files and dataset filtering are unchanged.
The three production indexes were deleted on 2026-10-29. Official D1 receipts
reported 564 rows read and 3 rows written for the three DROP operations;
database size fell by 36,646,912 bytes. See the
[retirement record](../database/changes/2026-10-29-retire-directory-sorts/README.md).

### Keep only online releases

Production retains active collections and actual online reference/file dependencies,
not backup or rollback directories. The aggregate `/genomes.html` entry now redirects
to GEM with query parameters intact. `/api/genome-directory` and `/api/site-summary`
return 410/no-store before D1 or old edge-cache access; use `/api/collections` and
the collection directory endpoints instead. `/genomes/<id>` details remain usable.
The experimental reference registry still serves the audit-only assembly and must
not be deleted as a backup. Remove unreferenced releases in measured batches.

## Measured cost

For the same GTDB `streptomyces` core query and data state:

| Metric | Before | After |
|---|---:|---:|
| SQL queries | 4 | 2 |
| Rows read | 14,677 | 7,392 |
| Rows written | 0 | 0 |

Core read rows decreased by 49.6%, excluding unchanged metadata/release overhead. A later directory-version addition changed the measured result to 7,434 read rows. Costs vary by query. The tested experimental filtering interaction took about 44 ms and made no extra directory request within the cache window. Measurements are recorded in workspace `BTED/_workspace/outputs/BTED-query-2026-10-22/`.

## Free-plan limits

[Cloudflare D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/) checked on 2026-10-22 lists **5,000,000 rows read and 100,000 rows written per day**, resetting at 00:00 UTC. Total storage is 5 GB; the [per-database limit](https://developers.cloudflare.com/d1/platform/limits/) is 500 MB on Free.

Imports, index maintenance, deletions and verification queries count toward usage. Cache misses, expiry and release changes still read D1. Check account-wide usage under Dashboard → D1 → Metrics → Row Metrics.

Each counted page updates two aggregate rows; inserts with indexes can consume four written rows. Thus 10,000 counted page loads use roughly 20,000–40,000 written rows, plus retention cleanup. See [usage counting](USAGE_ANALYTICS.md).

Keep small directory corrections additive rather than rebuilding the search index. Current database size and migration costs are in the [deployment record](releases/current.md).
