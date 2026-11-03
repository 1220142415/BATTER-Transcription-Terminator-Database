# Recovering gene annotations

Current counts are returned separately by each D1 collection. The 2026-10-27 run
below is separate from the earlier recovery retained later in this document.

Current maintenance continues from local `_workspace/outputs/BTED-GTDB-update-2026-10-29/STATUS.md`
and `live-only-state.json`, as described in [deployment.md](deployment.md).
The older run checkpoints below are historical records.

## GEM-origin recovery — 2026-10-27

Before recovery, GEM Legacy collection `202610220000000000000003` had 42,904 genomes:
14,575 Available (including 16 partial) and 28,329 Missing before this run. Missing
by original source: GEM 12,792; IMG 7,791; NCBI GenBank 3,962; NCBI RefSeq 197;
Pasolli 2,637; Almeida 366; Nayfach 584. GEM Legacy combines these seven origins;
`source_collection = GEM` identifies only the original GEM-study subset.

All **12,792 GEM-origin targets** have passed exact source/reference contig and
CDS nucleotide/coordinate/strand checks, including independent GFF3 parsing:
12,792 full, zero partial or failed, **32,549,067 CDS**, **5,766,973,527 GFF3 bytes**.
Coordinates come from the official original Prodigal FFN, not a new prediction.
The reference remains `9f81698a3cee64f4eaf90b90cd36d640f38d9315`.
Sixteen pilots passed JBrowse 4.3.0 loading and rendering before batch recovery.

HF publication completed at
[`765f663d12e49b06721ca03aecc7d1c64daa78cb`](https://huggingface.co/datasets/liurulong/terminator/tree/765f663d12e49b06721ca03aecc7d1c64daa78cb/v0.5.0/catalogues)
in the existing
`v0.5.0/genomes/batter-<batch>/<genome>/annotations/recovered/genes.gff3` layout.
New uploads contain only per-genome GFF3; compact source/checksum provenance is
merged into `v0.5.0/catalogues/annotation-recovery.json`, with full processing
records retained locally. Already published provenance files are preserved.
Plain GFF3 uses the existing `Gff3Adapter` and does not require an index.

All 12,792 remote GFF3 paths, byte sizes and LFS SHA256 values passed verification;
15 force-downloaded samples also matched their local SHA256. The merged manifest
has 13,049 entries, including all 257 historical records unchanged.
The audit, complete verification records, upload commits and remote evidence are
in workspace `BTED/_workspace/outputs/BTED-GEM-recovery-2026-10-27/`; `upload-state.json` records
the completed immutable checkpoint. `recovery-report.md` contains the source
breakdown and website handoff.
Production D1 staging completed on 2026-10-27 after authorization. The new ready
GEM directory `765f663d12e49b06721ca001` has 27,367 Available and 15,537 Missing;
legacy directory `765f663d12e49b06721ca002` is also ready. Remote checks passed for
all 12,792 target rows, reference contig counts, unchanged scientific/other fields,
42,904 cloned taxonomy records, search and foreign keys. Evidence is in the same
workspace output under `d1-update/verified.json`.

The user subsequently authorized synchronization, activation and deployment.
Active GEM is now `765f663d12e49b06721ca001`; legacy alias
`ce9c58ba2c3700dd9b610a6e` uses storage `765f663d12e49b06721ca002` without duplicated
directory rows. Worker `fc1b24d5-efe8-402b-8032-daa1d6df7ba2`, browser registry and
annotation binding all use the new HF annotation commit. Plugin version 43 handles
the existing v0.5.0 recovered GFF3 paths in the same-origin network fallback.
Live acceptance verified counts, directory interactions, three new genome
configurations, a real GFF3 download and rendered CDS with the fallback exercised.
Evidence is in `deployment/live-acceptance.json` and its screenshots.
No reference FASTA, prediction files or experimental records changed.

Later production audits exhausted the Free daily read quota; the final collection
API check returned 503. Both read and write quota errors are recorded. Old-data
cleanup did not delete any rows and the last measured D1 size was 457,453,568 bytes.
The user approved a one-time continuation on 2026-10-28 at 08:10 Asia/Shanghai.
The runner now uses small batches and measured maintenance stop thresholds, not
repeated full-database audits. Current and indirect reference/storage dependencies
remain protected. See the output's `deployment/quota-cause.md`,
`deployment/maintenance-state.json` and `RUN_STATE.md` for the active checkpoint.

Reproduction uses `index_gem_ffn.py`, `recover_gem_cds.py`, `upload_gem_cds.py`
and `prepare_gem_recovery_registration.py`. The uploader resumes from the remote
manifest, preserves prior entries and refuses conflicting/unregistered files.
Registration consumes the verified uploaded manifest snapshot and prepares local
SQL, rollback and matching asset/revision bindings without applying them remotely.

## Other-source recovery — 2026-10-27/28

The next run started from the active 42,904-genome GEM Legacy collection after
GEM-origin recovery: 27,367 Available (16 partial), 15,537 Missing. This baseline
uses the verified local snapshot matching the prior production readback, not a
new production scan while D1 quotas are exhausted.

| Original source | Missing before | Newly full | Newly partial | Remaining Missing |
|---|---:|---:|---:|---:|
| GEM | 0 | 0 | 0 | 0 |
| Almeida | 366 | 366 | 0 | 0 |
| NCBI GenBank | 3,962 | 3,114 | 2 | 846 |
| NCBI RefSeq | 197 | 44 | 23 | 130 |
| IMG | 7,791 | 0 | 0 | 7,791 |
| Pasolli | 2,637 | 2,177 | 0 | 460 |
| Nayfach | 584 | 583 | 0 | 1 |

All **6,309 additions** passed source/reference correspondence: **6,284 full,
25 partial**, **14,091,561 CDS**, **3,177,222,630 GFF3 bytes**. Original Almeida
FAA coordinates account for 254 genomes; 118 use official NCBI annotation and
11 use RefSeq annotation archived by BV-BRC. The other **5,926 genomes use
published third-party reannotation**: UHGG Prokka (2,872) or BV-BRC PATRIC (3,054).
These origins are explicitly distinct in the merged manifest. No new gene
prediction was run.

Complete contig sequences must be identical before coordinates are reused.
The independent base audit checked 14,903,656,560 reference bp and
14,847,739,994 matched bp; unmatched reference contigs occur only in the 25
partial genomes and contribute no restored CDS. CDS coordinates, strand, oriented
DNA and interval lengths passed; FAA/API conversion also checks published
proteins. CDS interval bases total 13,115,024,496 including overlaps, rather than
unique genome coverage. Four source-route JBrowse samples rendered successfully.

HF publication and remote acceptance completed at
[`b00d63a7d7105c77e331ff6a2a5f221db5d01942`](https://huggingface.co/datasets/liurulong/terminator/tree/b00d63a7d7105c77e331ff6a2a5f221db5d01942/v0.5.0/catalogues).
The existing recovered GFF3 layout is unchanged. All 13,049 prior manifest entries
are preserved; the manifest now has 19,358 entries. Two accepted immutable
checkpoints cover all 6,309 new paths, sizes and LFS SHA256 values; 22 actual
fixed-revision sample downloads also matched SHA256. Only per-genome GFF3 and
the existing shared manifest were added or updated. The upload/API HTTP-body
ledger records 3,591,826,489 bytes; this is not the proxy provider's billed total.

Detailed source/origin counts, failures, base audit, upload commits and verification
are in workspace `BTED/_workspace/outputs/BTED-legacy-sources-2026-10-27/`. Reproduction uses
`recover_legacy_sources.py`, `audit_legacy_cds_bases.py`, `upload_legacy_cds.py`,
`prepare_legacy_cds_registration.py` and `report_legacy_cds_recovery.py`.
The six recovery tests and 16 focused browser/API tests passed.

**Production has not enabled these additions.** Local D1 increment preparation
passed against the real snapshot, updating 12,618 existing directory rows without
directory/taxonomy cloning or FTS rebuilding. The GEM collection version remains
unchanged; the new legacy alias `fbd94c2f8757818dac80864a` points to existing
storage. Legacy directory rows with no registered contig count remain empty;
the GEM directory and scientific correspondence checks verify reference dimensions.
SQL, staged registries and revision settings are in
`website/b00d63a7d7105c77e331ff6a2a5f221db5d01942/` under that output directory.
Worker/API and reference-details/track source labels are implemented and checked
locally, including the inspected third-party partial example in
`qa/origin-copy.png`. Enabling the new revision, applying SQL and deploying need
separate authorization. Once enabled, GEM Legacy will have 33,676 Available
(41 partial) and 9,228 Missing. See `WEBSITE_HANDOFF.md` for activation steps.

The remaining 976 NCBI targets retain failure reasons, principally published
protein/phase checks, nonidentical contigs and complex joined CDS. UHGG did not
uniquely map 460 Pasolli and one Nayfach target. IMG access is unresolved, not a
sequence-validation failure: 16/16 pilot IDs mapped through the official current
JGI API, but downloads require login and most pilot files need tape restoration.
`IMG_DOWNLOAD_HELP.md` names one small GFF/FNA sample for manual download and
subsequent exact-sequence verification. No tape restoration was requested.

## Earlier recovery — 2026-10-14

The remaining sections describe the earlier computational catalogue and its fixed
published snapshot, rather than the current collection totals.

### Released files

The recovery covers **257 genomes**: 241 with all reference contigs matched and 16 with partial contig coverage. NCBI contributes 4 complete and 16 partial matches, GEM 1 complete match, and Almeida 236 complete matches. The package contains 515 files and 109,320,403 bytes.

Current files are under `v0.5.0/genomes/batter-<batch>/<genome>/annotations/recovered/`, with the catalogue at `v0.5.0/catalogues/annotation-recovery.json`, fixed to HF commit `2acf28d9cf0a276f05e6a1456d56c92ccc2292b7`. The reference remains fixed to `9f81698a3cee64f4eaf90b90cd36d640f38d9315`.

The earlier [v0.5.1 recovery package](https://huggingface.co/datasets/liurulong/terminator/tree/82180c1e12905470b9c3e3e56c80e5ea510e8460/v0.5.1/annotation-recovery/2026-10-14) remains available at its fixed historical commit. The current layout retains the recovered GFF3 and provenance bytes.

### Coordinate matching

Compare complete source and registered reference contig sequences. Reuse coordinates only on identical sequences. Sequence identifiers may be renamed using the verified mapping; there is no alignment-based coordinate transfer, shifting or clipping. Report matched and total reference contigs for partial coverage.

`Available` means a reference-compatible annotation file exists, including explicitly labeled partial coverage. `Missing` means no usable file is registered. It does not imply that genes are absent. Old URL states such as `Incompatible` map to `Missing`; detailed reasons remain in metadata.

### Source assessment

| Source | Result of the recorded review |
|---|---|
| NCBI | Of 55 exceptional entries, 4 complete and 16 partial matches were recovered; 35 could not reuse the annotation. The 4,124 unavailable exact-version directories had no GFF in that review. |
| [GEM](https://portal.nersc.gov/GEM/README.md) | Prodigal FFN archive available. One tested member, `3300009503_23`, matched all 483 contigs and 4,513 CDS sequences/coordinates. Other members were not covered by that verification. |
| [Almeida](https://ftp.ebi.ac.uk/pub/databases/metagenomics/umgs_analyses/) | Among 602 entries: 236 complete recoveries, 112 without original UMGS ID mappings and 254 with download failures. Network failures remain unresolved, not classified as absent annotations. |
| [Pasolli](https://segatalab.cibio.unitn.it/data/Pasolli_et_al.html) | FASTA and functional summaries found; no per-genome CDS coordinate files found in the reviewed listing. |
| [Nayfach](https://github.com/snayfach/IGGdb) | Genome, taxonomy and quality data described; no directly usable full CDS coordinate files identified in the reviewed README. |
| IMG | Requests failed; annotation availability remains unresolved. |

The four complete NCBI recoveries are `GCF_000472605.1`, `GCF_002942785.1`, `GCF_004004555.1` and `GCF_000972785.3`. The last includes seven valid circular-origin features whose original coordinates are retained. Extra source contigs not present in a registered reference are excluded.

### Reproduction and evidence

```sh
python scripts/audit_annotation_recovery.py --verify --partial --status mismatch download_failed invalid_gff
python scripts/audit_annotation_recovery.py --almeida --workers 4
python scripts/prepare_annotation_recovery.py
python scripts/verify_annotation_correspondence.py
```

The independent correspondence check compared recovered GFF3 with original GFF/FFN/FAA files and both source and registered reference sequences. It checked 257 genomes, 29,921 matched contigs and 544,906 annotation records. Twenty entries reuse published GFF3; 237 recover published CDS coordinates. FAA-derived records preserve coordinate and partial attributes and check protein/interval length; translation and function were not revalidated.

Complete coverage refers to matched reference contigs, not complete gene or functional annotation. No new gene prediction was performed.

Detailed reports and deployment evidence are retained in the Git-ignored local workspace at `BTED/_workspace/outputs/BTED-publication-2026-10-22/retained-evidence/annotation-recovery-2026-10-14/`, including `correspondence-report.json`, `partial-verified-report.json`, `almeida-verified-report.json` and `deployment-verified.json`. The historical shared directory had 14,593 Available and 28,330 Missing entries after recovery; these are not current per-collection totals.
