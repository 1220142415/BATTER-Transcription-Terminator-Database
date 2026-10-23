# Three independent collections

The default browsing entry is `/gtdb.html`. `/experimental.html` and `/gem.html`
have their own filters, records, details, browser configurations and downloads.
An accession appearing in two collections has two independent URLs; it is not merged.
Existing `/genomes/*` shared links retain their original contract.

| Collection | Scientific input | Classification |
|---|---|---|
| GTDB predictions | BATTER-TPE intervals; pinned, partial HF snapshot | GTDB R207.0 (2022) |
| Experimental 3′ ends | Study-reported endpoints, registered signals and existing model predictions | NCBI Taxonomy verified by exact assembly version and TaxID; GTDB R207.0 supplementary |
| GEM catalogue · Legacy | Existing multi-source computational catalogue; no prediction updates | Original GEM / GTDB classification; exact release not established |

The initial GTDB snapshot is `deffa4a7183f71a8b47b3c44`, commit
`7ed77270f02862da5722dad1d7836e3444e67dfd`: 27,275 published genomes from
62,291 input genomes. Scientific
files use each catalogue row's own immutable revision, not the moving HF branch.

## Runtime and build

- `/api/collections`: D1 release descriptions, per-collection counts and publication coverage.
- `/api/collections/{collection}/directory?v={version}`: existing indexed, linked-facet D1 pagination, 25 rows per page.
- `/api/collections/gtdb/{id}` and `/config`: D1 metadata and JBrowse config.
- `/api/collections/gtdb/{id}/files/{file}?revision={snapshot_commit}`:
  allowlisted, fixed-revision scientific files with Range support. Reference FAI
  contig count and total length must agree with D1 before returning a config.
- `/api/collections/gem/{id}` and `/config`: original D1 metadata and computational
  tracks only, without experimental overlays.
- `/api/collections/experimental/{id}/config`: registered reference, endpoint,
  signal and prediction tracks. Study cards and ZIP continue using the existing
  live D1 APIs; predictions have separate download links.

## Experimental membership

The current directory `202610220000000000000006` contains **20** references with
published experimental endpoints. It has 29,460 experimental records and 124,740
existing predicted regions: 111,782 on 18 BATTER-TPE references plus 11,090 and
1,868 BATTER regions on two sequence-verified computational references.

`GCF_000005845.2` (S002, [PMID 38030608](https://pubmed.ncbi.nlm.nih.gov/38030608/))
is metadata-only (`audit_only`, zero published endpoints). The directory summary
pins its retained reference metadata to `reference_registry_version` v5, keeping
legacy URLs usable from D1 without adding this reference to the experimental count. It remains registered
with its 4,447 predictions and its legacy reference URL, but is not counted as an
experimental member. The previous signal review found FASTQ in
[E-MTAB-12429](https://www.ebi.ac.uk/biostudies/arrayexpress/studies/E-MTAB-12429),
not a verified author BigWig. Admission requires a checked Term-seq-only endpoint
mapping to NC_000913.3; RNAtag-seq call sets and NC_000913.2 coordinates must not be
substituted. Verified BigWig is useful additional evidence, not a substitute for
published endpoint records.

GCF_000009765.2 predictions cover the computational chromosome plus an additional
plasmid; experimental endpoints cover the matched chromosome. Counts and download
scope remain explicit. Augmentation/Rfam remains in GEM Legacy. No inference or
coordinate conversion was performed by this directory correction.

Query caching and D1 costs are described in [D1 metadata](D1_METADATA.md).

`bted_collections` binds each collection to a ready `hf_directory_releases` entry.
The existing directory table and indexes hold independent version-scoped rows.
`gtdb_genome_assets` registers each published genome's group and scientific revision.
No runtime metadata lookup falls back to a TSV or remote HF metadata JSON.

## Classification records and defaults

`bted_taxonomy_records` separates classification from organism identity, gene annotation
and coordinate files. Its key is `(version, genome_id, system, taxonomy_version)`;
`version` refers to the collection's immutable directory release. Collections never
share or merge a genome row. `bted_collections.taxonomy_system` and
`taxonomy_version` select the default classification. The indexed directory's six
rank columns are a projection of that default, not an independently edited lineage.
Changing defaults requires a new directory release and refreshed summaries/search.

Systems are `ncbi`, `gtdb` and `gem_original`. NCBI records have TaxID, retrieval
timestamp, exact matched assembly, official assembly/Taxonomy links and evidence.
Their taxonomy version is empty: a retrieval date is not a release number.
GTDB records name `R207.0`; original GEM records keep an empty version because its
exact GTDB release is not established. `verified` identifies a checked exact match;
`retained` preserves a published mapping without asserting fresh classification;
`unmatched` means no exact accession-version match; `pending` means the assembly
identity could not be resolved. Unmatched/pending records have empty ranks.
Missing ranks are never filled from another system or a newer/paired assembly.

`/api/collections/{collection}/{genome}/taxonomy` returns the selected default,
all classifications and their evidence from D1. Experimental page metadata uses
the explicit experimental collection release, not the latest unrelated directory.
The detail page shows NCBI by default, with GTDB and historical GEM in separate
expandable blocks. Study organism names, strains, coordinate files and signals
remain unchanged. ZIP metadata adds named default-taxonomy and GTDB fields without
overwriting study species. GTDB/GEM detail metadata exposes its classification
records while retaining the existing browser configuration contracts.

Historical classification preparation (before the membership correction): `202610220000000000000004`, 21 references.
NCBI resolves 20 exact assembly versions; `GCF_000005845.1` returns an empty official
assembly report and stays pending (not borrowed from `.2`). GTDB R207.0 matches
19 exact accessions, with two unmatched; original GEM retains 16 matches and five
unmatched. Evidence and guarded release migration are prepared with
`scripts/prepare_taxonomy_d1.py` and stored in the workspace
`outputs/BTED-taxonomy-2026-10-22/`. Historical directory releases remain available
in D1 for recovery; no scientific data tables are rewritten.

Prepare with `scripts/prepare_collections_d1.py` using the pinned current pointer,
snapshot, compressed catalogue and an exported current D1 directory. The script
checks local SQLite integrity, foreign keys, counts, FTS and the pagination index
before emitting additive SQL. Existing directory and scientific rows are unchanged.

`scripts/build_collections.py` reads `data/registry/collections.json` for page release
bindings and labels. Runtime counts come from D1. `scripts/stage_site.py` invokes
this builder after the existing Worker page generators. Keep `BTED_COLLECTION_REVISION`
in the Worker configuration aligned with the release so edge caches cannot mix releases.

## Acceptance and recovery

Check all three entry points, linked filters, header sorting, pagination, configurations and affected downloads. Browser checks must inspect actual feature or signal rendering. See [Deployment](deployment.md) for checks and [the current release](releases/current.md) for active versions and recovery.
