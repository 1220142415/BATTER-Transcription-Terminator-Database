# Recovering gene annotations

This document describes the **2026-10-14 annotation recovery** for the earlier computational catalogue. Current counts are returned separately by each D1 collection.

## Released files

The recovery covers **257 genomes**: 241 with all reference contigs matched and 16 with partial contig coverage. NCBI contributes 4 complete and 16 partial matches, GEM 1 complete match, and Almeida 236 complete matches. The package contains 515 files and 109,320,403 bytes.

Current files are under `v0.5.0/genomes/batter-<batch>/<genome>/annotations/recovered/`, with the catalogue at `v0.5.0/catalogues/annotation-recovery.json`, fixed to HF commit `2acf28d9cf0a276f05e6a1456d56c92ccc2292b7`. The reference remains fixed to `9f81698a3cee64f4eaf90b90cd36d640f38d9315`.

The earlier [v0.5.1 recovery package](https://huggingface.co/datasets/liurulong/terminator/tree/82180c1e12905470b9c3e3e56c80e5ea510e8460/v0.5.1/annotation-recovery/2026-10-14) remains available at its fixed historical commit. The current layout retains the recovered GFF3 and provenance bytes.

## Coordinate matching

Compare complete source and registered reference contig sequences. Reuse coordinates only on identical sequences. Sequence identifiers may be renamed using the verified mapping; there is no alignment-based coordinate transfer, shifting or clipping. Report matched and total reference contigs for partial coverage.

`Available` means a reference-compatible annotation file exists, including explicitly labeled partial coverage. `Missing` means no usable file is registered. It does not imply that genes are absent. Old URL states such as `Incompatible` map to `Missing`; detailed reasons remain in metadata.

## Source assessment

| Source | Result of the recorded review |
|---|---|
| NCBI | Of 55 exceptional entries, 4 complete and 16 partial matches were recovered; 35 could not reuse the annotation. The 4,124 unavailable exact-version directories had no GFF in that review. |
| [GEM](https://portal.nersc.gov/GEM/README.md) | Prodigal FFN archive available. One tested member, `3300009503_23`, matched all 483 contigs and 4,513 CDS sequences/coordinates. Other members were not covered by that verification. |
| [Almeida](https://ftp.ebi.ac.uk/pub/databases/metagenomics/umgs_analyses/) | Among 602 entries: 236 complete recoveries, 112 without original UMGS ID mappings and 254 with download failures. Network failures remain unresolved, not classified as absent annotations. |
| [Pasolli](https://segatalab.cibio.unitn.it/data/Pasolli_et_al.html) | FASTA and functional summaries found; no per-genome CDS coordinate files found in the reviewed listing. |
| [Nayfach](https://github.com/snayfach/IGGdb) | Genome, taxonomy and quality data described; no directly usable full CDS coordinate files identified in the reviewed README. |
| IMG | Requests failed; annotation availability remains unresolved. |

The four complete NCBI recoveries are `GCF_000472605.1`, `GCF_002942785.1`, `GCF_004004555.1` and `GCF_000972785.3`. The last includes seven valid circular-origin features whose original coordinates are retained. Extra source contigs not present in a registered reference are excluded.

## Reproduction and evidence

```sh
python scripts/audit_annotation_recovery.py --verify --partial --status mismatch download_failed invalid_gff
python scripts/audit_annotation_recovery.py --almeida --workers 4
python scripts/prepare_annotation_recovery.py
python scripts/verify_annotation_correspondence.py
```

The independent correspondence check compared recovered GFF3 with original GFF/FFN/FAA files and both source and registered reference sequences. It checked 257 genomes, 29,921 matched contigs and 544,906 annotation records. Twenty entries reuse published GFF3; 237 recover published CDS coordinates. FAA-derived records preserve coordinate and partial attributes and check protein/interval length; translation and function were not revalidated.

Complete coverage refers to matched reference contigs, not complete gene or functional annotation. No new gene prediction was performed.

Detailed reports and deployment evidence are retained outside the source tree at workspace `outputs/BTED-publication-2026-10-22/retained-evidence/annotation-recovery-2026-10-14/`, including `correspondence-report.json`, `partial-verified-report.json`, `almeida-verified-report.json` and `deployment-verified.json`. The historical shared directory had 14,593 Available and 28,330 Missing entries after recovery; these are not current per-collection totals.
