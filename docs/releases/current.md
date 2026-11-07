# Current deployment

Production: [BTED](https://bted.1052596411.workers.dev/).
Updated: **2026-11-07**. Worker: `882014ca-4cd1-4cf3-b601-0d7c4823f572`.

The November 7 browser update presents concise feature details across gene annotations, experimental 3′ ends, predicted terminator regions and augmented regions. Gene annotations retain the gene product, locus tag, protein accession and native sequence operations; internal identifiers, processing fields, duplicate values and missing attributes are omitted. Prediction scores and estimated false positives per kb remain visible. Rfam accessions and family names are retained without relabeling every Rfam-derived region as a terminator. Tooltips and optional feature labels use biological names or coordinates. The mixed experimental `signal_or_score` field is omitted from the panel because its definition differs among studies. Original scientific files and D1 records are unchanged. Plugin version: `v46`.

The November 6 release replaces the experimental predictions with **29 stride-1 scan sets / 400,068 predicted regions**, at HF `1276a8436cebd8e4a646e7d437a04ae6f944e63d`. The 39,896 experimental endpoint records and their evidence labels are unchanged. The former HF head is retained on `backup/bed-before-stride1-2026-11-06`; the 19 existing prediction paths are preserved, with 10 new packages following the same layout.

`GCF_000009765.2` now uses its existing complete reference, including SAP1 (`NC_004719.1`, 94,287 bp). The source-specific endpoint copy maps sequence-identical `BA000030.4` to `NC_003155.5` without changing any of its 1,159 coordinates, strands, IDs or original-accession attributes. The gene GFF3 retains all 7,676 chromosome features and adds 93 SAP1 genes, 4 pseudogenes, 97 CDS and one region record. Gene annotation and model predictions remain separate tracks.

The extension Worker now reads prediction bindings from D1 and reuses the established prediction-track builder. Migration 0014 supplies those bindings; future ordinary prediction-file/version refreshes use D1 without another Worker code change. GTDB and GEM bindings and data were not changed by this release.

The November 4 evening UI-only update removes the experimental Gene annotation dropdown (all 29 experimental references currently have annotation), while retaining the Annotation table column and Sequencing technology selector. GTDB and GEM annotation filters are unchanged. Full site validation, Wrangler dry-run, and online HTML/health/collection checks passed. Signal-availability filtering (5/29) remains a future candidate; absence of a track does not imply lack of experimental endpoint evidence.

November 4 frontend deployment hides the uncurated genome-type badge in the experimental directory only; GTDB and GEM retain their type labels and filters. The legacy aggregate directory binding is skipped during Worker staging because `build_collections` retires that page. The genome-browser registry is encoded as compact JSON without altering its content. Site validation, Wrangler dry-run, and online JS/collection/health acceptance passed. No D1 mutation or scientific-file re-registration was part of this frontend deployment.

## Online collections

| Collection | Active directory | Coverage |
|---|---|---|
| Experimental | `202610310000000000000005` | 29 references; 39,896 experimental records; 400,068 predicted regions |
| GTDB | `19d287cdc5dab25026d996be` | 57,271 / 62,291 genomes; partial; unchanged by this release |
| GEM | `765f663d12e49b06721ca001` | 42,904 genomes; 12,792 recovered annotations activated |

Experimental v0.5.0 adds 9 assemblies, 11 sources and 10,436 records at HF revision
`277f829ad3b408f60925122ff2a498c8a158e7c3`. The 20 existing assemblies remain in the
current collection. New evidence labels are preserved in dedicated registrations.
On 2026-11-04, production D1 taxonomy completed verification for all 29 experimental assemblies. The legacy MG1655 assembly `GCF_000005845.1` now uses NCBI strain TaxID 511145, explicitly documenting that its older assembly version was not resolved through the current NCBI assembly API. Only taxonomy, the directory row/search index and phylum summary were updated; the 607 endpoints and the then-current 4,415 predictions were unchanged. The generic experimental browser and API read this correction live without a Worker redeploy. The experimental genome-type label was subsequently removed from production by the November 4 Worker deployment described above.
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

- **GTDB:** the live API already reports 57,271 / 62,291 genomes at `19d287cdc5dab25026d996be`; this BED refresh leaves that binding unchanged. The earlier 1,570-genome loading description is superseded. Reconcile current pointers and receipts before any further maintenance.
- **Old-version cleanup:** on November 1, deleted 24,004 retired directory rows
  and one empty retired release header. Remaining retired rows: 83,246, derived
  from the saved inventory minus acknowledged deletions. No retired taxonomy rows.
  Last official size: 357,400,576 bytes (357.40 MB), a net 28.57 MB reduction from
  this run's starting size after the additional GTDB import. No production backup created.
- **Non-GEM annotation recovery:** 6,309 additions published to HF and prepared
  locally, not activated; separate production scope remains required.
- **Experimental intake:** BW25113 has 1,095 locally verified endpoints, not published.

## Resume and recovery

The experimental BED refresh checkpoint is `_workspace/outputs/BTED-prediction-bed-2026-11-06/STATUS.md`, with its execution constraints, official write/readback receipts and shared-cost ledger beside it. HF publication and D1 activation are complete; do not replay those operations.

GTDB maintenance records remain under `_workspace/outputs/BTED-GTDB-update-2026-10-29/`. Historical loading positions and the November 1 budget stop are not current restart instructions: compare the live D1 pointers with the machine state before any authorized continuation. Maintenance still shares the daily ceiling of 500,000 reads / 50,000 writes and reserves at least 1,000,000 reads / 30,000 writes for the website. Recovery uses forward fixes, not retired Workers or production rollback snapshots.

## Acceptance evidence

November 7 acceptance covers 108 Python tests, 83 JavaScript tests, the fixed-input site build, pinned asset-registry comparison and Worker dry-run. Production health and experimental/GEM/GTDB configurations passed; browser checks cover gene annotations and protein sequence, standalone CDS and genomic sequence, both reported experimental endpoints, prediction scores, OTU/Rfam regions and signal hover values. The GEM panel title contrast was corrected in plugin v46. Receipts and screenshots are retained in `_workspace/outputs/BTED-feature-details-2026-11-07/`.

November 6 acceptance covers all 29 live metadata/configuration pairs, 400,068 predictions and unchanged 39,896 experimental records; three representative BED Range downloads and all three S. avermitilis Tabix indexes passed. Gene-annotation download coverage includes both chromosome and SAP1. Focused Python/Node tests, the fixed-input site build, Worker dry-run and bounded production D1 readback passed. Operation receipts and rendered-browser evidence are retained in `_workspace/outputs/BTED-prediction-bed-2026-11-06/`.

### Retained October 31–November 1 evidence

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
