# HF metadata in D1

## Current scalar storage: 2026-10-14

Worker `22194ff8-595c-4cc2-bcdf-3a63d93aae5e` uses `BTED_RUNTIME_FIELDS=on`. Production D1 occupies **164,818,944 bytes**, down from 431,210,496 bytes (61.78%). Genome pages, metadata, configurations, file fallback and the paged directory read indexed scalar fields; they do not read per-genome JSON from D1 or HF.

`hf_runtime_genomes` stores one current record for each of 42,904 computational genomes: identity, taxonomy, feature counts, reference information, annotation status and current validation fields. `hf_runtime_files` stores 328,721 current file sizes and checksums using an integer genome key and a file-kind number. URLs and source paths are generated from the pinned root, batch, genome and known filename. `hf_runtime_release` activates this single verified reference snapshot. No coordinate correction table, old coordinate fields, correction rules or correction lists are retained in D1 or returned by the active metadata API. The 1,019 upstream logs describe preprocessing already reflected in the published GFF3; they are not applied at query time.

After cutover and verification, migration `0007_retire_metadata_archives.sql` removed `hf_genome_metadata` and `hf_registered_files`. The experimental tables, directory projection, small release header and 430 catalogue pages remain. The pages preserve the complete-catalogue compatibility API with 431 cold rows read; the website uses the separate 25-row paged endpoint. The 19 experimental-only genomes use their existing experimental records and directory fields.

Cold first-page SQL measured **1 + 1 + 25 + 32 = 59 rows read**, previously 76. A sampled cold computational metadata request measured **1 + 1 + 1 + 8 = 11 rows read**, including the release header, runtime marker, scalar genome and seven file records. Other genomes have different file counts. Metadata/config retain 24-hour edge caching, directory pages retain seven-day edge caching, and in-memory lookups remain shared. Cache hits make no D1 reads; eviction, deeper pages and combined filters can increase daily reads. Normal metadata/directory browsing writes no rows; existing analytics writes remain separate.

The one-time runtime import reported 414,538 written rows and 743,255 read rows, including index work and count-checked activation. These are migration costs, not daily browsing costs. Free quotas still need account-wide monitoring as described below.

Preparation uses the verified original metadata SQLite backup, without downloading scientific files:

```powershell
py -3.13 scripts/build_runtime_metadata.py --source dist/d1-storage-audit-2026-10-14/hf-baseline.sqlite --output <fresh-runtime-bundle>
node --test --test-isolation=none tests/test_runtime_metadata.mjs tests/test_batter_browser.mjs tests/test_worker_query_cache.mjs tests/test_genome_directory.mjs
```

Import only the bundle's `sql_files` in order. Its final activation statement requires both runtime table counts to match. Verify remote readiness, fields/checksums and query plans before enabling `BTED_RUNTIME_FIELDS`. Keep the legacy tables until the deployed Worker passes live checks and their export has been restored and verified. Apply migration `0007` only then. Do not rerun the historical raw archive importer or disable `BTED_RUNTIME_FIELDS` after retirement without restoring the legacy tables first. A future reference update replaces the active scalar snapshot after review; do not retain a second full metadata archive in D1.

All 42,904 current metadata records and catalogue rows were reconstructed and compared with the verified original, omitting only the requested historical correction keys. Remote checks matched eight complete scalar rows and 58 file entries. The 275,329,824-byte production export was restored with SQLite integrity `ok`; all 42,923 legacy metadata rows and 457,805 file rows matched the original in every field. This backup remains a local migration recovery file, not an active D1 dataset. Current GFF3/index checks confirmed the example feature ends at 8,132, matching the contig length, rather than its historical 8,133 value. No scientific files or coordinates were changed by this migration.

Post-retirement checks used fresh uncached genome requests, a fresh configuration and a fresh directory page. Experimental counts remain 21 assemblies, 25 sources and 29,460 endpoints; directory counts remain 42,923 / 14,593 Available / 28,330 Missing. Evidence, SQL and backup receipts are in `dist/d1-runtime-current-2026-10-14/`; the restored export originates from `dist/d1-runtime-fields-2026-10-14/before-normalization.sql`. Fixed experimental, reference and annotation snapshots remain those in [deployment.md](deployment.md).

## Historical JSON import and paging

The following records describe the prior implementation and its initial import. The scalar storage above supersedes its raw per-genome tables and storage/read figures.

The current directory pagination implementation returns only 25 rows per request. The initial page does not fetch or prefetch the complete catalogue. Next/Previous and filters query `/api/genome-directory`; visited results are bounded to 12 entries in browser memory. Each page/filter has a seven-day edge cache and 60-second browser freshness. A cold unfiltered first page uses one release lookup plus two bounded 25-row queries against the derived directory and existing catalogue rows. Exact combined-filter counts and cascading taxonomy facets have separate shared caches. Search uses a trigram index and requires at least one three-character token. Deep pages use indexed OFFSET and may read preceding index entries; arbitrary combined filters can also scan more than 25 rows. The 25-row response size is not a guarantee of 25 D1 rows read.

The verified local projection contains 42,923 rows (14,593 Available / 28,330 Missing) and occupies about 68.5 MB including indexes. It reuses the existing scientific catalogue records and adds no per-file paths. Migration `0005_genome_directory.sql` and `scripts/build_genome_directory.py` generate resumable isolated tables and a count-checked activation step. Production version `b6d6dcaa5e9de931d43a25c3` is ready and active in Worker `24fa89c6-8823-411e-9fae-5648cd3c7771`; the earlier 108 MB import was rejected before execution, and this reduced plan passed review. The complete database now occupies 431,210,496 bytes. Actual first-page checks read 1 + 25 + 50 = 76 D1 rows. This one-time import wrote about 686,800 rows including index maintenance, distinct from normal read-only directory traffic. Its SQL and metrics are recorded in `dist/d1-directory-merged-2026-10-14/`. Only copy a new verified manifest to `data/registry/genome-directory.json` after remote readiness is confirmed; the standard browser builder then binds the page to that exact snapshot and refuses changed inputs.

Scientific download paths are derived from the fixed HF version, the genome root and known relative filenames. Recovered annotations now use the same `v0.5.0/genomes/` root and do not repeat complete paths in their manifest. Existing archived file registration and original source provenance remain available for release verification; the Worker does not query the redundant `hf_registered_files` path list.

The immutable HF snapshot `9f81698a3cee64f4eaf90b90cd36d640f38d9315` supplies genome metadata and file registration. Scientific files remain at their existing HF URLs. Existing experimental release and analytics tables are not replaced by this import.

The import stores complete metadata for 42,923 genomes, including 42,904 computational genomes; the browser catalogue, reference provenance, taxonomy, feature counts, annotation status and file checksums are retained. The 457,805 entries in `release.json` retain their published paths, original source paths, sizes and SHA-256 values. Genome-level provenance records are already included in each metadata wrapper. Large provenance archives and scientific files remain on HF.

## Prepare

Export the current database before importing. Use the current deployment configuration and the published v0.4.0 snapshot described in [deployment.md](deployment.md).

```powershell
wrangler d1 export bted-catalog --remote --config prototype/accession-range/wrangler.jsonc --output <backup.sql>
py -3.13 scripts/import_hf_metadata_d1.py --workers 24 --sql-output dist/d1-hf-metadata
```

The downloader uses `requests` and standard Git LFS batch downloads. An optional `--proxy http://127.0.0.1:<port>` sets the download proxy. It validates every file against the fixed manifest before caching it in `dist/hf-metadata/<revision>/`. Rerunning resumes from verified files. `--limit` is for download checks and cannot produce an import. `--offline --sql-output dist/d1-hf-metadata` generates SQL from a complete cache.

## Import and activate

Migration `0004_hf_metadata.sql` creates four isolated tables: `hf_metadata_releases`, `hf_genome_metadata`, `hf_registered_files` and `hf_catalogue_pages`. Import the generated SQL files in numeric order with `wrangler d1 execute bted-catalog --remote --config prototype/accession-range/wrangler.jsonc --file <file.sql>`. Inserts are resumable and do not replace existing records. Catalogue pages keep individual SQL statements below D1's size limit.

Before activation, verify row counts, prediction and training totals, registered file sizes, and sampled original metadata hashes against `import-manifest.json` and the HF manifest. Mark the release `ready` only after validation. Set `BTED_METADATA_REVISION` to the verified fixed commit in `wrangler.jsonc`, then deploy the Worker and regenerated pages.

The catalogue uses `/api/batter-catalogue`. Genome metadata and generated configurations continue to use `/api/batter/<genome>` and `/api/batter/<genome>/config`. With `BTED_METADATA_REVISION` set, these read D1 and reject an unavailable release; they do not fall back to HF metadata. Reference sequence, GFF3, BigWig and index downloads preserve their existing fixed URLs and checksums. The static catalogue remains a build input and a pre-activation fallback.

## Checks

```powershell
py -3.13 -m unittest discover -s tests -p test_import_hf_metadata_d1.py
node --test --test-isolation=none tests/test_batter_browser.mjs
```

The import test checks exact JSON bytes, checksums, counts and rejection of changed metadata. Worker tests verify D1 catalogue and metadata reads, revision rejection, and absence of HF metadata requests.

## Published import: 2026-10-13

The import is active in Worker version `14cfc356-a37d-4d65-8085-dea5971c163d` (plugin/config v=29). D1 contains 42,923 genome wrappers, 42,904 computational catalogue rows in 430 pages, and 457,805 registered files. The database occupies 363,708,416 bytes. Registered scientific and metadata files total 46,697,008,045 bytes; their contents remain on HF. The manifest's summary declares 457,807 files, while its actual `files` array contains 457,805; the import retains every actual entry.

The catalogue header includes reference lengths from the existing verified overlay records. Its complete API payload matches the staged catalogue, including these lengths. Both the site builder and importer use `read_browser_catalogue()` to preserve this contract.

All imported JSON SHA-256 values were checked in the complete local SQL roundtrip. Remote checks verified row counts, registered bytes, 122,039,507 predictions, 2,389,014 OTU augmentation regions, 149,158 Rfam regions, the complete catalogue header and 62 original metadata hashes covering all batches and experimental-only wrappers. Existing experimental table counts remained unchanged, including 25 sources and 29,460 endpoints. The release was marked `ready` before enabling `BTED_METADATA_REVISION`.

The final public checks matched 15 static assets, the full D1 catalogue and five metadata API samples, and verified configuration, health, cache headers, registered file hashes and `206` ranges. Actual browser checks covered catalogue search, reference lengths, track symbols/counts, About track and sharing. Evidence is in workspace `outputs/bted-finish-2026-10-13/`; the pre-import backup is `d1-before-metadata-2026-10-13.sql` and the remote report is `metadata-import-remote-verified.json`. The deployment report is `outputs/bted-copy-2026-10-12/cf-deployment-verified.json`.

## Daily limits and caching

[D1 Free](https://developers.cloudflare.com/d1/platform/pricing/) includes 5,000,000 rows read and 100,000 rows written per account per day, resetting at 00:00 UTC (08:00 Asia/Shanghai). These measure scanned/written rows, not HTTP requests or JSON records. Imports, verification queries, deletes and index maintenance also count. The account's current billing plan has not been confirmed; use Free limits for capacity planning. [Workers Free](https://developers.cloudflare.com/workers/platform/limits/#daily-requests) separately limits Worker requests to 100,000 per day.

With the fixed D1 revision enabled, successful GET catalogue responses use a seven-day edge cache; genome metadata and config retain their 24-hour edge cache. The directory requests a catalogue URL pinned by `revision`, `annotation` and representation `v=1`, allowing a one-year immutable browser cache. Unversioned or mismatched catalogue URLs retain 60-second browser freshness. All catalogue URLs share one edge entry; each response applies the appropriate browser policy, including on a hit. Catalogue cache keys include the release, HF revision, annotation revision and catalogue namespace, independent of visual plugin versions. Metadata/config keys retain the plugin version. Invalid genome revision and arbitrary URL parameters are checked before cache lookup. Failed responses, HEAD and Range requests are not stored. When changing catalogue content or representation without changing the data revisions, increment both the catalogue namespace and URL representation version; rebuild the directory. When changing generated metadata/config behavior without changing the snapshot or plugin version, increment their namespace in `cachedPublicApi`.

An edge hit makes no D1 reads. Cache entries are local to each Cloudflare location and may be evicted before their TTL; they are not a daily quota guarantee. The existing 60-second, 512-entry in-memory lookup cache also shares concurrent release/genome reads within a Worker isolate, including HTML and scientific file fallback requests. Missing/failed lookups are not retained. Static experimental pages require no HF metadata lookup.

The complete catalogue scans 430 indexed page rows plus one release row on a fully cold load, using five non-overlapping page ranges. Each page contains up to 100 genomes, so this is 431 database rows, not 42,904. Catalogue page reads now share the existing 60-second in-memory promise cache within one Worker isolate; concurrent cold requests or retries reuse the five page queries. Failed reads are removed and can recover immediately. A fully cold genome metadata or config request reads one release row and one genome row. Production D1 `meta.rows_read` measurements confirmed 1, 1 and 30 rows for release, genome and the final 400–499 page range, respectively; all measured queries wrote zero rows. Cached lookup reuse can reduce these counts further. Scientific file content continues to come from HF.

Metadata browsing adds no database writes. Existing page-view analytics updates two aggregate rows per counted document view. Inserting new aggregate keys also writes primary-key index entries, so allow up to four written rows per view before retention cleanup; updates to existing counters normally write two. For example, 10,000 counted page views use about 20,000–40,000 written rows plus cleanup. Keep this independent write budget in capacity planning; the analytics setting and counting policy are unchanged.

The post-import 24-hour snapshot showed 3,662,084 read rows and 501,330 written rows. This included the 501,169 imported rows and full-table verification, and is not a normal browsing baseline or a UTC-day report. Use D1 Metrics > Row Metrics to assess daily account consumption, including other databases. Avoid repeating full-table checks during routine deployment.

The initial JSON import occupied approximately 364 MB; current scalar storage is approximately 165 MB. Free has a [500 MB per-database limit](https://developers.cloudflare.com/d1/platform/limits/), distinct from the 5 GB account total. Check temporary migration capacity before importing another snapshot and retire replaced runtime data after verification. If Free daily query limits are exhausted, uncached D1-backed requests fail until reset, while existing edge entries and static assets can remain available.

The cache optimization was deployed on 2026-10-14 as Worker `766d8680-60c8-475b-a3cb-14d6fb1b00cb`, retaining plugin/config v=29. All three public API types passed MISS→HIT checks, including requests with unused query parameters; the complete catalogue still matches the published build. Wrong revisions and arbitrary URLs returned 409 and 400, respectively, even with a warm cache. HEAD was uncached and a registered file Range returned 206 with the original checksum. Checks passed 25 Node tests and 11 Worker Python tests. Production evidence is in `outputs/bted-finish-2026-10-13/verify_d1_cache_2026_10_14.json` and `d1-query-cost-2026-10-14.json`.
