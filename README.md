# BTED — Bacterial Transcript 3′ End Database

BTED provides bacterial RNA 3′-end records from published studies, BATTER model predictions, and available sequencing-signal tracks. Each dataset is linked to its publication, experimental method, conditions, and reference assembly.

**[Browse BTED](https://bted.1052596411.workers.dev/)** · [Data and sources](docs/SOURCES.md) · [Build the website](docs/deployment.md) · [Report an issue](https://github.com/1220142415/BATTER-Transcription-Terminator-Database/issues)

## Data collections

| Collection | Available data | Classification |
|---|---|---|
| [Experimental 3′ ends](https://bted.1052596411.workers.dev/experimental.html) | 29 reference assemblies; 39,896 experimental records and 124,740 predicted regions | NCBI Taxonomy (9 new assemblies pending classification); GTDB R207.0 available separately |
| [GTDB predictions](https://bted.1052596411.workers.dev/gtdb.html) | BATTER-TPE predictions for 27,275 of 62,291 input genomes; partial release | GTDB R207.0 (2022) |
| [GEM](https://bted.1052596411.workers.dev/gem.html) | BATTER predictions and augmentation/Rfam regions for 42,904 genomes from GEM and other sources | GTDB R89 (GEM) |

Counts are reported separately for each collection. Genomes may occur in more than one collection. The experimental total counts source records, including records from different studies at the same position.

RNA 3′ ends can result from transcription termination or RNA processing. Experimental records and model predictions are therefore presented as separate evidence types. See [source-specific interpretation](docs/SOURCES.md) and the [BATTER study](https://doi.org/10.1186/s40168-026-02454-1).

## Browse and download

1. Select a collection and search by genome identifier or organism name.
2. Filter by classification or data availability. Click a table heading to sort; click it again to reverse the order.
3. Open a genome to inspect its reference, tracks, publications, and downloads.

All experimental genome pages use the same D1-driven presentation and offer study-data ZIPs, including registered GFF3/BED files and their indexes. Prediction and reference files have separate links where available. BigWig tracks show the registered samples or conditions; each track scales to its visible window. Peak heights across separately scaled tracks are not directly comparable.

Scientific files are hosted in the [Hugging Face dataset](https://huggingface.co/datasets/liurulong/terminator). The website uses fixed file revisions and D1 for current metadata. The [v0.4.0 file guide](docs/releases/v0.4.0.md) describes experimental GFF3, metadata and supplementary tables. The retained v0.4.0 package contributes 20 endpoint-bearing references. The v0.5.0 extension adds 9 assemblies and 10,436 records, including new endpoint data for the formerly metadata-only GCF_000005845.2 reference. See the [current release](docs/releases/current.md) for active revisions and pending GTDB ingestion.

## Run and reproduce

Requirements: Python 3.12+, Node.js 24, and the pinned inputs in the [build and deployment guide](docs/deployment.md). Run from the repository root:

```sh
python scripts/validate_repo_layout.py
python scripts/check_markdown_links.py
python -m unittest discover -s tests -p 'test*.py' -q
node --test tests/*.mjs
```

The build guide covers the JBrowse application, scientific-file snapshots, plugin build, Cloudflare configuration, and recovery. A static preview alone does not provide the production D1 APIs.

## Repository guide

| Directory | Contents |
|---|---|
| `worker/` | Cloudflare Worker, D1 queries and file routes |
| `site/` | Browser interactions and styles |
| `jbrowse-plugin/` | Track glyphs, signal display and browser controls |
| `scripts/` | Site builders, data preparation and validation |
| `bted_pipeline/` | Experimental-data normalization and checks |
| `database/` | Schema, ordered migrations and reviewed data changes |
| `data/` | Frozen releases, source records and reference mappings |
| `tests/` | Regression tests and small fixtures |
| `docs/` | Data methods, architecture and operations |

[Architecture](docs/ARCHITECTURE.md) · [Database](database/README.md) · [Script index](scripts/README.md) · [Contributing](CONTRIBUTING.md) · [Current deployment](docs/releases/current.md)

Local project progress is in `_workspace/PROGRESS.md` (Git-ignored). Active maintenance resumes from `_workspace/outputs/BTED-GTDB-update-2026-10-29/STATUS.md`, its `RUNBOOK.md` and `live-only-state.json`.

## Citation and reuse

For BATTER predictions, cite:

Jin, Y., Cui, J., Liu, R. et al. **Conserved 3′ stem-loop structures enable comprehensive analysis of bacterial transcription termination in metagenomes.** *Microbiome* 14, 222 (2026). [doi:10.1186/s40168-026-02454-1](https://doi.org/10.1186/s40168-026-02454-1).

For experimental data, also cite the original studies linked on each genome page and in the [source catalogue](docs/SOURCES.md). Record the collection, genome accession and downloaded file revision in your analysis. Third-party data retain their source-specific reuse terms. This repository does not yet declare a software license.
