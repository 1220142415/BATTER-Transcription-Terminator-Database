# Unified experimental and BATTER genome directory

The local `batter-genomes.html` page searches BTED experimental assemblies and BATTER genomes together. The Worker joins records only when their **complete genome ID** matches; it does not merge by organism name. The current D1 snapshot contains 21 experimental assemblies and 42,905 BATTER genomes, including two shared IDs: 42,924 unique genomes (19 experimental-only, 42,903 BATTER-only). The page fetches 25, 50, or 100 rows at a time. A detail view has a shareable URL such as `batter-genomes.html?genome=2228664028`.

All 42,905 bacterial OTUs in this catalogue have a matching GEM representative FASTA entry: the OTU and representative genome ID both match the BATTER record. The UI's **Original source** filter is the `study` field copied unchanged from BATTER's `combined-statistics.txt`, not GEM membership. Its eight values include GEM (12,793), IMG (7,792), NCBI-RefSeq (10,707), NCBI-MAG (7,573), and four other sources. The value `GEM` therefore identifies one original-source group within a catalogue whose entries all have GEM representative sequences. The importer now checks both OTU and genome ID against the GEM reference manifest.

The local source snapshot is `gff3/{batch_manifest.tsv,taxonomy_by_genome.tsv,audit.json}` and `gem_references/manifest.tsv` under `/home/liurulong/terminator` on `labx-cu010`. `audit.json` is checked during import so counts from an older pre-clipping manifest cannot silently replace the current totals. For the snapshot checked on 2026-09-29, the import reports 42,905 genomes, 122,044,160 predicted features, 2,389,081 OTU augmentation spans, 149,160 Rfam training spans, and 243 genomes with `no_records_in_source` status. Reference metadata is matched by OTU; it does not certify coordinate validation.

## Prepare the current local inputs

Copy the four small metadata files from the server into an ignored workspace directory. GFF3 files are not copied or imported into D1.

```powershell
$dataDir = 'data/derived/batter_gff3/full_run_cu10-current-20260929'
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
$ssh = 'C:\Windows\System32\OpenSSH\scp.exe'
& $ssh -o BatchMode=yes labx-cu010:/home/liurulong/terminator/gff3/batch_manifest.tsv "$dataDir/"
& $ssh -o BatchMode=yes labx-cu010:/home/liurulong/terminator/gff3/taxonomy_by_genome.tsv "$dataDir/"
& $ssh -o BatchMode=yes labx-cu010:/home/liurulong/terminator/gff3/audit.json "$dataDir/"
& $ssh -o BatchMode=yes labx-cu010:/home/liurulong/terminator/gem_references/manifest.tsv "$dataDir/gem_references_manifest.tsv"
```

Import the validated snapshot into the Wrangler **local** D1 database. Stop `wrangler dev` before importing so its SQLite file is idle.

```powershell
$d1Root = 'prototype/accession-range/.wrangler/state/v3/d1/miniflare-D1DatabaseObject'
$d1Files = @(Get-ChildItem -LiteralPath $d1Root -Filter '*.sqlite' | Where-Object Name -ne 'metadata.sqlite')
if ($d1Files.Count -ne 1) { throw "Expected one local D1 database file under $d1Root; inspect the database binding before importing." }
python scripts/import_batter_catalog.py `
  --data-dir data/derived/batter_gff3/full_run_cu10-current-20260929 `
  --apply `
  --local-db $d1Files[0].FullName
```

The importer creates SQL export files in `dist/batter-genomes-import-chunks/`, applies migration `0003_add_batter_genome_catalog.sql` to the selected local D1 SQLite file, then replaces rows only in `batter_genomes` inside one SQLite transaction. Parameterized `executemany` avoids a single oversized SQL statement. The importer verifies D1 totals before committing. It also checks unique genome and OTU joins, taxonomy and genome-type totals, numeric feature counts, file checksums, the current `audit.json`, and coverage against the GEM reference manifest. GFF3 files are neither copied into D1 nor served as downloads.

To keep the experimental catalogue functional in the same local preview, initialize that D1 file with the verified v0.4.0 bundle and generated SQL described in [the Worker and D1 deployment instructions](deployment.md#worker-与-d1) before importing BATTER rows. The existing `/api/batter-genomes` routes remain available. The new `/api/genomes` routes read both D1 collections without copying GFF3 into the database. This is local D1 state, not a new public release.

## Build and open the local preview

The shell builder writes the unified page, CSS/JS, and an exact 100-genome pilot browser manifest into the ignored Worker preview directory. The pilot data service serves the already validated FASTA and browser tracks with HTTP Range support on port 8783. Start both services from separate terminals:

```powershell
python scripts/build_batter_catalog_preview.py --output-dir dist/worker-site
python scripts/validate_batter_tes_pilot.py
python scripts/validate_batter_augmentation_pilot.py
python scripts/serve_batter_tes_preview.py
```

```powershell
Set-Location prototype/accession-range
& 'D:\科研\promoter\datasetweb\RAPPTOR\node_modules\.bin\wrangler.cmd' dev --local --config .\wrangler.jsonc
```

Open `http://127.0.0.1:8787/batter-genomes.html`. The two shared genomes, `GCF_000009765.2` and `GCF_000012525.1`, link to pilot JBrowse configurations that show experimental 3′ ends, BATTER predictions, and training augmentation as separate tracks. The remaining pilot genomes show their ready BATTER tracks; experimental-only genomes use the existing BTED browser when its reference and track are public. `GCF_000005845.2` has no browser reference and is shown without a browser link. Other BATTER genomes show a pending-track state. The pilot link points to local port 8783, so it requires the pilot service.

The two shared references passed sequence identity checks before track merging: experimental `BA000030.4` equals GEM `NC_003155.5` for `GCF_000009765.2`; the two GEM contigs of `GCF_000012525.1` match the experimental browser reference hashes. Only browser copies map the sequence names where needed; source GFF3 files remain unchanged.

Useful API checks are:

```text
GET /api/genomes/stats
GET /api/genomes?membership=both&page_size=25
GET /api/genomes?membership=experimental&page_size=25
GET /api/genomes?source=IMG&type=MAG&phylum=Firmicutes_A
GET /api/genomes/2228664028
GET /api/genomes/GCF_000009765.2
GET /api/batter-genomes/stats
```

Experimental 3′ ends, predictions, OTU augmentation, and Rfam training counts are shown separately. Experimental BTED pages and links remain available. The 243 BATTER genomes without augmentation records are marked explicitly. BATTER GFF3 files have pending-public-release status and no public download links; existing published experimental GFF3 links remain available.

Genome details also show the experimental browser's contig IDs and lengths, and the BATTER GEM representative FASTA metadata (genome ID, collection, contig count, total bases, and source-relative path). The source-relative FASTA path is descriptive metadata, not a download link. Experimental-only entries with no registered contigs show that the contig information is unavailable.

## Current directory interactions

The v5 interface uses English throughout. Phylum → Species options depend only on selected parent ranks, following RAPPTOR's taxonomy interaction. Text, evidence, BigWig, original-source, and genome-type filters combine on the result list. Changing a parent clears its children; fresh options show a loading state. Search waits 300 ms and cancels obsolete requests.

Genome ID, BATTER predictions, OTU augmentation, and Rfam training table headings toggle sorting. Filter, sort, and page-size changes return to page 1; URLs retain the current query and page. Clear filters resets in place to Genome ID ascending, 50 rows, and page 1. Failed requests offer Retry without clearing the query.

Run `node --test --test-isolation=none tests/bted_unified_filters.test.mjs` and `python -m unittest discover -s tests -p test_bted_catalog_presentation.py` for focused regressions. `scripts/verify_bted_catalog_interactions.mjs` runs browser acceptance against `BTED_CATALOG_CANDIDATE` and `BTED_PREVIEW_ORIGIN`. Its explicit `--ui-only` mode checks the interface and link navigation without certifying remote file transport; the saved report marks that distinction.
