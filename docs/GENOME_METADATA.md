# Genome detail metadata

Genome pages show the registered reference, six taxonomic ranks (phylum through species), available data, browser, studies and downloads. The page title retains the organism name from the study metadata. The taxonomy block uses the name in the named classification source, which can differ from the study name.

## Production metadata comes from D1

The Cloudflare Worker uses D1 for live descriptions. Experimental HTML contains loading containers, not a copy of the release TSV. D1 failure shows an unavailable state with retry; it never restores older card values.

| Display or download | D1-backed entry point |
| --- | --- |
| Experimental title, reference identity, taxonomy, paper, assay, samples, conditions and counts | `/api/assemblies/<accession>/page-metadata` |
| Study ZIP file list | `downloads` in the same response, using registered asset keys |
| Metadata inside the ZIP; existing metadata asset-key requests | `/api/assemblies/<accession>/metadata.tsv`; metadata requests under `/api/assets/<key>` also generate current D1 values |
| Experimental and signal track descriptions | Existing `/jbrowse/assemblies/<accession>.config.json` and mixed `/api/batter/<genome>/config`, with D1 descriptions and conditions applied |
| Collection cards and summaries | `/api/collections` |
| Legacy home summary | `/api/site-summary` |
| Collection directories and metadata | `/api/collections/<collection>/directory`, `/api/collections/<collection>/<genome>` |
| Legacy directory and computational metadata | `/api/genome-directory`, `/api/batter-catalogue`, `/api/batter/<genome>` |

Page descriptions and home summaries have a 60-second edge cache; experimental browser configurations have a five-minute edge cache. Metadata TSV downloads use `no-store`. These are response caches of D1 queries, not a second editable data source.

FASTA, GFF3, BigWig and scientific index files remain at pinned HF revisions. Static browser configuration retains validated coordinate systems, adapters and sequence-compatibility evidence; D1 supplies current study descriptions. The fixed asset manifest remains an integrity allowlist. Registry TSVs and the published snapshot are retained for evidence, migration and standalone Pages builds, not as production fallbacks. With `BTED_D1_ONLY=on`, missing D1 revision configuration fails rather than selecting the legacy HF catalogue path.

## Genome origin and taxonomy source

`Genome source` records the original database or study, as preserved by GEM's combined catalogue. The 42,904 computational genomes comprise GEM (12,793), IMG (7,791), NCBI GenBank (7,790), NCBI RefSeq (10,707), Pasolli et al. (2,637), Almeida et al. (602), and Nayfach et al. (584). These seven origins remain distinct. All 42,904 original source labels, OTU assignments and taxonomy strings were checked against GEM's original membership and taxonomy tables with no mismatches.

Using taxonomy supplied by the GEM catalogue does not mean that a genome originated in the GEM study. The catalogue also clustered and classified genomes from the other sources. In the UI, NCBI-MAG and NCBI-SAG are grouped as NCBI GenBank; the original labels remain in the underlying records.

## Experimental references

Experimental production pages and filters use separately verified NCBI Taxonomy
records in D1, joined by the explicit experimental collection release. GTDB
R207.0 exact-assembly classifications and the historical GEM mapping are retained
as independent records, not rank-level fallbacks. NCBI retrieval dates are not
release numbers. The lineage does not rename the study organism or strain.
See [classification records and defaults](COLLECTIONS.md#classification-records-and-defaults)
for keys, statuses, evidence, API and migration rules.

Nineteen of the 20 experimental members have verified NCBI assembly-version/TaxID matches. The wider 21-reference registry also retains the audit-only GCF_000005845.2.
`GCF_000005845.1` remains pending because its official assembly report is empty;
classification is not borrowed from `.2`. GTDB R207.0 supplies 18 exact matches among the 20 experimental members.
ZIP metadata includes the default classification source/status/TaxID/lineage and
the separate supplementary GTDB classification without replacing study species.

The following describes the retained historical mapping, not the current default:

`data/registry/genome_taxonomy.tsv` uses the original GEM catalogue's GTDB-based taxonomy for experimental references, aligned on 2026-10-15. Sixteen of the 21 complete assembly accessions occur in GEM's `genome_to_otu.tsv`; their six ranks are copied from the corresponding `otu_taxonomy.tsv` row. `gem_otu_id` and `taxonomy_status` record the mapping. GEM membership here supplies taxonomy only; it does not add a computational dataset or change reference sequences.

Five references have no exact assembly match: `GCF_000005845.1`, `GCF_003932715.1`, `GCF_005519465.1`, `GCF_015710995.1` and `GCF_018282115.1`. Their historical GEM ranks are unassigned; the current NCBI default is recorded separately. A different assembly version or similar organism name is not accepted as a match. Filling these entries requires a verified historical mapping or sequence classification against a confirmed matching GTDB release; the GEM release number has not been established.

Reference strain and NCBI TaxID remain identity metadata, separate from the historical GEM mapping. The original 2026-10-05 NCBI lineages are preserved in `outputs/BTED-publication-2026-10-22/retained-evidence/gem-taxonomy-2026-10-15/genome_taxonomy.before.tsv`. The `GCF_000005845.1` NCBI assembly report was empty; its TaxID 511145 records the explicitly named *E. coli* K-12 MG1655 organism and does not establish equivalence with another assembly version.

GEM assigns `GCF_000739105.1` (reference *Streptomyces lividans* TK24) to an OTU classified as *Streptomyces coelicolor*. The source classification is retained without renaming the study organism or strain. The GEM classification for `GCF_000005845.2` has no species assignment; that rank stays empty.

Reference lengths and contig counts in production come from D1 `contigs`, preserving the website's registered browser reference. The historical import used `reference_contigs.v0.2.0.json` and `browser_refs/contigs.tsv`, not newer NCBI assembly lengths.

## Computational references

GEM computational pages retain the GEM catalogue's GTDB lineage and link to the [original taxonomy table](https://portal.nersc.gov/GEM/otus/otu_taxonomy.tsv), with the exact release explicitly unknown. The official table was downloaded again on 2026-10-15 and matched the archived copy; its HTTP last-modified date is 2020-09-24. Missing ranks display `Not assigned`. The independent GTDB prediction collection uses R207.0; experimental defaults use NCBI, as described above.

Legacy overlapping experimental/computational pages retain a separate computational reference panel. GEM OTU, input FASTA and source checksum identify the computational input; the study overview uses the explicit experimental classification. Sharing an accession does not establish that the sequence or coordinate system is identical.

## Study context

The top summary separates experimental 3′-end records, predicted regions and augmentation / Rfam regions. Missing catalogue entries display `Not cataloged`; a registered count of zero remains `0`. Augmentation counts include OTU and Rfam spans, exclude their context windows, and retain the component counts. Experimental counts sum source records and can include overlapping sites.

Each study card shows the paper title, first author, journal, year and PubMed link, followed by the 3′-end assay, sample strain, genotype, verified conditions, replicates, evidence type and raw-data accession links. `3′-end assay` identifies the sequencing method behind the collected RNA 3′ ends, not all methods in the paper. Counts sum records for that paper and genome, with per-dataset counts when the paper has multiple source records; overlapping coordinates are not deduplicated. Interpretation notes, including RNA processing, shared sequencing data and known sample/reference strain differences, remain visible. Internal source IDs and licences are not displayed as card fields.

D1 `publications` supplies production titles, DOIs, authors, journal and year. The offline registry `data/registry/publications.tsv` contains 14 paper titles and DOIs from the audited `corrected-metadata/experimental-metadata.corrected.tsv`; repeated PMID entries were checked for agreement. The historical citation import also used `study_citations.v0.4.0.tsv`. Titles link to the paper DOI.

Experimental and combined pages use one study-download action, `Download study ZIP`, rather than individual study-file or source-metadata buttons. The ZIP retains its experimental GFF3 and related scientific TSV files, but generates `metadata.tsv` from current D1 records. It does not add reference, prediction or BigWig files. Pure computational pages retain their data-file downloads. Scientific file registration is unchanged.

The independent experimental collection additionally displays its existing model
predictions with separate counts and download links under `Model predictions`.
The study ZIP remains experimental-only. Eighteen experimental members use D1-registered
BATTER-TPE assets; two reuse sequence-verified computational overlays. Their
prediction count and download cover the computational reference, whose contig
scope is shown explicitly when it differs from the experimental reference.

Where a verified browser signal is registered, a separate BigWig block identifies its GEO sample or condition-specific sample group and protocol. These conditions describe the displayed signal, not necessarily every endpoint in the paper. Production reads `signal_sample` and `signal_conditions` from D1 `tracks.metadata_json`. Their reviewed import inputs are `experimental-signals.json` and `s021-derived-signals.json`. Unverified sample links and conditions are not inferred.

D1 `sources.metadata_json` supplies sample strain, genotype, conditions, replicate description and shared-data relationships to source cards. Previously reviewed missing fields were added from `data/registry/source_context.tsv` on 2026-10-19, with guarded update and rollback SQL. Blank fields mean no verified value has been supplied. Reference strain and sample strain remain separate fields.

Production assay labels use D1 `sources.assay_family`. The offline registry's `endpoint_assay` and `endpoint_assay_url` were reviewed against retained article text on 2026-10-19. Term-seq-only collections no longer display companion dRNA-seq, TSS-seq, ordinary RNA-seq or ribosome profiling. S020 uses Nanopore native RNA-seq; S021 uses 3′ RNA-seq (modified from Term-seq). S002 is restricted to Term-seq by the user-confirmed collection scope and remains metadata-only. S022's Term-seq label is supported by the abstract; its detailed supplementary-data review remains separate. Field-level excerpts are retained in the workspace `outputs/BTED-study-ui-2026-10-19/endpoint-assay-evidence.json`. The D1 connection reuses the already-corrected assay values without another assay migration.

The registry is a selected extract of `corrected-metadata/experimental-metadata.corrected.tsv` in the companion evidence directory. That file and `metadata-changes.tsv` record the field-level evidence. Before changing a value, check its cited paper or accession and retain the supporting response in the evidence directory.

Notable distinctions include:

- Lalanne 2018 (PMID 29606352): sample ML76, reference NA1000.
- Lee 2020 (PMID 33319794): sample M145, reference A3(2); sample NBRC 108819, reference NRRL 18488. These are not assumed to be identical strains.
- S007/S013 share PRJEB31507; S015/S017 share SRX6937123/4 (GEO GSM4105470/1). Source call sets remain separate; record totals are not counts of unique biological sites.
- Cascino 2026 (PMID 42148773): WT technical replicates GSM9264033/4 are combined in EXT102; Δmfd biological replicates GSM9264035/6 remain EXT103/104.

Current downloads use corrected D1 metadata. Scientific coordinate files and frozen-release metadata retain their own versions. Field-level corrections and pending reviews are recorded in the companion evidence directory; follow the [database correction process](../database/README.md) before changing them.
