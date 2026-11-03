# Current deployment

Production: [BTED](https://bted.1052596411.workers.dev/).
Updated: **2026-11-01**. Worker: `d0046baa-c3e6-4aea-8ebc-318501c97267`.

## Online collections

| Collection | Active directory | Coverage |
|---|---|---|
| Experimental | `202610310000000000000005` | 29 references; 39,896 experimental records; 124,740 predicted regions |
| GTDB | `deffa4a7183f71a8b47b3c44` | 27,275 / 62,291 genomes; partial |
| GEM | `765f663d12e49b06721ca001` | 42,904 genomes; 12,792 recovered annotations activated |

Experimental v0.5.0 adds 9 assemblies, 11 sources and 10,436 records at HF revision
`277f829ad3b408f60925122ff2a498c8a158e7c3`. The 20 existing assemblies remain in the
current collection. New evidence labels are preserved in dedicated registrations.
The 9 new assemblies have pending NCBI classification; no lineage was inferred.
Directory/taxonomy storage `202610220000000000000006` and reference registry v5
remain actual online dependencies, not backup copies. The health API reports the
new experimental release separately from the retained v0.4.0 scientific release.

All three collections use generic D1-driven detail shells. Experimental pages
now use the established reference summary, study cards, study ZIP and JBrowse
controls; the separate v0.5.0 HTML/style implementation was removed. Assembly
membership and scientific-file revisions are read from D1 rather than a code
allowlist or fixed commit. Directory versions follow `/api/collections`, so
approved data registration and activation do not require rebuilding the pages.

GEM annotation revision: `765f663d12e49b06721ca03aecc7d1c64daa78cb`.

## In progress

- **GTDB update:** 1,570 of the fixed 57,271 candidate genomes are in D1 loading,
  including 120 added on November 1. All additions have official receipts, and
  the latest imported genome's directory, taxonomy and scientific-file revision
  match the prepared per-genome registration. No pointer switch. Snapshot
  `19d287cdc5dab25026d996be`, metadata revision
  `a24ecb1b5192479036d328afcbd3a6ae8421cbea`; source coverage is 57,271 / 62,291.
  Another 55,701 candidate genomes remain.
- **Old-version cleanup:** on November 1, deleted 24,004 retired directory rows
  and one empty retired release header. Remaining retired rows: 83,246, derived
  from the saved inventory minus acknowledged deletions. No retired taxonomy rows.
  Last official size: 357,400,576 bytes (357.40 MB), a net 28.57 MB reduction from
  this run's starting size after the additional GTDB import. No production backup created.
- **Non-GEM annotation recovery:** 6,309 additions published to HF and prepared
  locally, not activated; separate production scope remains required.
- **Experimental intake:** BW25113 has 1,095 locally verified endpoints, not published.

## Resume and recovery

The active checkpoint is `_workspace/outputs/BTED-GTDB-update-2026-10-29/live-only-state.json`,
with `STATUS.md` and `RUNBOOK.md` beside it. State: `safe_budget_stop`, no pending
operation or import inflight. November 1 maintenance: 242,364 reads / 49,929 writes,
within 500,000 / 50,000. The preceding day's 15-write maintenance remainder was
not the account's hard-quota balance. The new UTC day was admitted normally after
account-level management checks; rolling statistics may lag. Do not grant a
second same-day budget. Next GTDB position: `016-genomes.sql`, offset 70
(batch_index 15).

Continue within the shared daily ceiling of 500,000 reads / 50,000 writes and
reserve at least 1,000,000 reads / 30,000 writes for the website. Keep the serving
GTDB until the full candidate and its browser/download paths pass acceptance;
then switch the D1 pointer/summary, accept the dynamic directory and delete superseded records.
Production retains current data and real dependencies, not rollback snapshots.
The existing `bted-gtdb` continuation stops after cleanup and GTDB acceptance.
Recovery uses forward fixes, not historical Workers requiring deleted data.

## Acceptance evidence

The new experimental collection passed local SQLite import, foreign-key and search
checks, 29-row pagination (25 + 4), source-method filtering, all nine new pages and
configurations, and new evidence-label checks. Nineteen directory/compatibility/API
tests passed; the final four extension tests and the legacy-health regression passed.
The staged site validator and Worker dry-run passed.

Production health, collection summaries, directories and configurations returned HTTP 200.
Browser checks passed pagination and search without JavaScript errors; a new reference
sequence and gene track rendered. GFF3, BED and reference Range downloads returned
HTTP 206 at the pinned revision. An existing experimental page returned HTTP 200;
GEM sample `3300028569_36` retained full recovered CDS coverage (110 / 110 contigs,
2,865 features). No GTDB activation was claimed.

Receipts and screenshots: `_workspace/outputs/BTED-experimental-v05-d1-release-2026-10-31/`
(`d1-driven-production-deploy.log`, `shared-production.json`, `d1-driven-production.json`).
Bounded D1 receipts and the maintenance ledger remain in the active GTDB directory.

The shared-page correction passed the 11 site-builder tests, the 30 relevant
API/directory/compatibility tests, and seven final extension tests. A fixture
assembly added only to D1 became available through the generic shell without
changing HTML or a code allowlist. Pinned scientific revision changes were also
read from D1. Production checks confirmed the shared study cards, native browser
bridge/strand styles, location links, ZIP download and the original experiment
page. The Worker asset lookup uses the extensionless shell URL to preserve the
user-facing accession during Cloudflare canonical URL handling.

GTDB and GEM production detail/config/download smoke checks also passed, using
`GCA_000007325.1` and recovered-CDS genome `3300028569_36` respectively. Each
collection has one generic detail shell; the deployed static site contains no
backup/history/archive package. Retired D1 rows are still pending budgeted cleanup;
this presentation correction did not delete them or change their scientific data.

November 1 cleanup acceptance confirmed unchanged collection pointers, all six
protected release dependencies, the 29-assembly/39,896-record experiment projection,
new-experiment FTS lookup and a newly imported GTDB registration. Health and
collection APIs returned HTTP 200. Receipts:
`_workspace/outputs/BTED-GTDB-update-2026-10-29/cleanup-2026-11-01-acceptance.json`
and `cleanup-2026-11-01-live-http.json`.
