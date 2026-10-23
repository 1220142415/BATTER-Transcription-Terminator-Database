# Sources and evidence

The original BATTER Table S1 contains 22 source datasets from 13 publications. Twenty-one sources contribute 28,399 records; S002 is metadata-only. The v0.4.0 release adds three Cascino sources with 1,061 records. Current totals and inclusion rules are described in [Collections](COLLECTIONS.md#experimental-membership).

A source ID identifies a dataset, not necessarily an independent sequencing experiment. Study cards link reused sequencing data where known. Records from separate sources remain distinguishable even when their coordinates overlap.

## Interpreting RNA 3′ ends

RNA 3′ ends can reflect transcription termination or RNA processing. The [S. lividans study](https://doi.org/10.3389/fmicb.2019.02074) reports TEPs; the [BATTER paper](https://doi.org/10.1186/s40168-026-02454-1) discusses steady-state ends and post-termination processing. BTED preserves the source evidence class rather than assigning a new functional classification to each endpoint.

**Nanopore native RNA-seq** is the method name used in the [D. dadantii paper](https://doi.org/10.1128/mbio.00524-22). Its Methods describe direct RNA sequencing; Table S2D supplies putative TTS positions. It is not a Term-seq assay.

## Published source records

Counts below are source rows, not unique positions across the database. Full assembly versions and sequence identifiers specify the coordinate reference.

| PMID | Source / organism or strain | Assembly and sequence | v0.4.0 records / evidence | Interpretation |
|---|---|---|---|---|
| [29606352](https://pubmed.ncbi.nlm.nih.gov/29606352/) | `S1_001` · *E. coli* K-12 MG1655 | `GCF_000005845.1` · `NC_000913.2` | 607;`curated_record` | Curated from Lalanne Table S3. No new endpoint calling was performed by BTED. |
| [38030608](https://pubmed.ncbi.nlm.nih.gov/38030608/) | `S1_002` · *E. coli* K-12 MG1655 | `GCF_000005845.2` · `NC_000913.3` | 0;`audit_only` | Supplementary Data 3 still needs a record-level Term-seq-only mapping. RNAtag-seq records are outside the intended scope; no endpoints are published. |
| [29606352](https://pubmed.ncbi.nlm.nih.gov/29606352/) | `S1_003` · *B. subtilis* 168 | `GCF_000009045.1` · `NC_000964.3` | 1,414;`curated_record` | Curated from Table S3. A signal comparison did not change the evidence class. |
| [29606352](https://pubmed.ncbi.nlm.nih.gov/29606352/) | `S1_004` · *Caulobacter vibrioides* NA1000 | `GCF_000022005.1` · `CP001340.1` | 337;`curated_record` | WIG, supplementary tables and samples identify CP001340.1. The conflicting GEO reference NC_000913.2 is recorded in the audit. |
| [29606352](https://pubmed.ncbi.nlm.nih.gov/29606352/) | `S1_005` · *V. natriegens* NBRC 15636 | `GCF_001456255.1` · `CP009977.1`, `CP009978.1` | 1,154;`curated_record` | Two reference sequences are handled separately. |
| [30517198](https://pubmed.ncbi.nlm.nih.gov/30517198/) | `S1_006` · *Streptococcus pneumoniae* TIGR4 | `GCF_000006885.1` · `NC_003028.3` | 1,864;`author_called_endpoint` | Supplementary Table S2 contains 1,864 gene-associated rows at 1,811 strand-specific positions. Preserve the author rows. |
| [31555254](https://pubmed.ncbi.nlm.nih.gov/31555254/) | `S1_007` · *Streptomyces lividans* TK24 | `GCF_000739105.1` · `CP009124.1` | 1,640;`author_called_endpoint` | Supplementary Dataset 3 reports transcript end positions (TEPs), which may include termination and processing products. |
| [31594819](https://pubmed.ncbi.nlm.nih.gov/31594819/) | `S1_008` · *Pseudomonas aeruginosa* PAO1 | `GCF_000006765.1` · `NC_002516.2` | 1,965;`author_called_endpoint` | Table S1B supplies reproducible Term-seq endpoints. Table S1A has 805 gene associations, versus 804 in the text; the supplementary rows are retained separately. |
| [32694125](https://pubmed.ncbi.nlm.nih.gov/32694125/) | `S1_009` · *Zymomonas mobilis* ZM4 | `GCF_003054575.1` · `CP023715.1`–`CP023719.1` (5 sequences) | 2,091;`author_called_endpoint` | Author TTSs after excluding processing sites. Excludes 1,746 prediction-only TransTermHP sites. Retains 616 prediction matches marked in the list; the text reports 617. |
| [33319794](https://pubmed.ncbi.nlm.nih.gov/33319794/) | `S1_010` · *S. avermitilis* MA-4680 | `GCF_000009765.2` · `BA000030.4` | 1,159;`author_called_endpoint` | BA000030.4 and NC_003155.5 are sequence-identical; the browser uses a verified sequence alias. |
| [33319794](https://pubmed.ncbi.nlm.nih.gov/33319794/) | `S1_011` · *S. griseus* NBRC 13350 | `GCF_000010605.1` · `NC_010572.1` | 2,024;`author_called_endpoint` | Term-seq endpoints reported by Lee et al. (2020). |
| [33319794](https://pubmed.ncbi.nlm.nih.gov/33319794/) | `S1_012` · *S. coelicolor* A3(2) | `GCF_000203835.1` · `NC_003888.3` | 1,308;`author_called_endpoint` | Term-seq endpoints reported by Lee et al. (2020). |
| [33319794](https://pubmed.ncbi.nlm.nih.gov/33319794/) | `S1_013` · *S. lividans* TK24 | `GCF_000739105.1` · `CP009124.1` | 1,208;`author_called_endpoint` | Same reference as S007, but a separate publication/source record. See the study metadata for sequencing-data reuse. |
| [33319794](https://pubmed.ncbi.nlm.nih.gov/33319794/) | `S1_014` · *S. tsukubensis* | `GCF_003932715.1` · `CP020700.1` | 1,283;`author_called_endpoint` | Term-seq endpoints reported by Lee et al. (2020). |
| [33319794](https://pubmed.ncbi.nlm.nih.gov/33319794/) | `S1_015` · *S. clavuligerus* | `GCF_005519465.1` · `CP027858.1`, `CP027859.1` | 1,140;`author_called_endpoint` | Chromosome and plasmid records share one reference assembly. Kept separate from the S017 source records. |
| [33319794](https://pubmed.ncbi.nlm.nih.gov/33319794/) | `S1_016` · *S. venezuelae* ATCC 15439 | `GCF_015710995.1` · `CP059991.1` | 870;`author_called_endpoint` | The paper, ATCC and ENA use S. venezuelae; current NCBI assembly metadata uses S. gardneri. Sequence identity supports the coordinates; the study name is retained. |
| [33947798](https://pubmed.ncbi.nlm.nih.gov/33947798/) | `S1_017` · *S. clavuligerus* ATCC 27064 | `GCF_005519465.1` · `CP027858.1`, `CP027859.1` | 1,427;`author_called_endpoint` | Author table from Hwang et al. (2021), kept separate from S015. Horizontal table layout requires counting entries rather than worksheet rows. |
| [34054774](https://pubmed.ncbi.nlm.nih.gov/34054774/) | `S1_018` · *Synechocystis* PCC 7338 | `GCF_018282115.1` · `CP054306.1`–`CP054309.1` (4 sequences) | 487;`author_called_endpoint` | Supplementary Data S2; chromosome and three plasmids have separate coordinates. |
| [34874777](https://pubmed.ncbi.nlm.nih.gov/34874777/) | `S1_019` · *Synechocystis* PCC 6803 | `GCF_000009725.1` · `NC_000911.1` | 784;`author_called_endpoint` | TEPs from Table S5. PubMed records publication in 2021; the frozen source registration contains published_year=2022. |
| [35491820](https://pubmed.ncbi.nlm.nih.gov/35491820/) | `S1_020` · *Dickeya dadantii* 3937 | `GCF_000147055.1` · `NC_014500.1` | 1,165;`author_called_endpoint` | Only Table S2D native RNA-seq positions are published. S2B/S2C are predictions; S1C combines experimental and predicted evidence. |
| [37402717](https://pubmed.ncbi.nlm.nih.gov/37402717/) | `S1_021` · *Borreliella burgdorferi* B31 | `GCF_000008685.2` · 20 of 22 reference sequences contain endpoints | 1,905;`author_called_endpoint` | 2,277 observations across two conditions yield 1,905 endpoint records. Conflicting condition annotations at 14 positions are retained in the observation table. |
| [37096044](https://pubmed.ncbi.nlm.nih.gov/37096044/) | `S1_022` · *Mycobacterium tuberculosis* H37Rv | `GCF_000195955.2` · `NC_000962.3` | 2,567;`author_called_endpoint` | AL123456.3 and NC_000962.3 are sequence-identical. Excludes 29,096 RhoTermPredict-only sites. |

## Coordinate and inclusion rules

- Experimental GFF3 records use 1-based inclusive coordinates with equal start and end. Match coordinates within a sequence and strand; do not combine different contigs.
- `curated_record` identifies literature-curated records. `author_called_endpoint` retains author-reported experimental calls. Pure predictions are kept out of the experimental endpoint files.
- The original augmentation summary files under [`data/registry/internal/augmentation/`](../data/registry/internal/augmentation/) lack per-record genomic coordinates. They are separate from the coordinate-resolved augmentation/Rfam tracks in GEM Legacy.
- Frozen metadata can retain earlier registration values. For S002, `published_year=2018` is not the paper's 2023 publication year. Current cards use corrected D1 publication fields; the original value remains in the audit trail.

S002 Supplementary Data 3 is covered by the publisher's [CC BY 4.0 statement](https://www.nature.com/articles/s41467-023-43534-2#rightslink). Reuse requires attribution, a license link and a description of changes. Its `release_status=audit_only` is a curation decision, separate from redistribution permission. Admission requires the reviewed Term-seq-only record mapping to NC_000913.3.

## Additional studies

| Study | Treatment | Basis |
|---|---|---|
| [Cascino 2026, PMID 42148773](https://pubmed.ncbi.nlm.nih.gov/42148773/) | Sources `BTED_EXT_2026_102`–`104`, GCF_000012525.1; 388 + 331 + 342 = 1,061 records | Table S1 `defined end` entries. Another 196 dispersed/uncertain entries remain under review. CP000100.1 and NC_007604.1 are identical sequences. |
| [Fuchs 2021, PMID 34131082](https://pubmed.ncbi.nlm.nih.gov/34131082/) | Not published | 1,967 draft records require review, including 75 with unresolved strand. |
| [TERMITe, PMID 40586304](https://pubmed.ncbi.nlm.nih.gov/40586304/) | Not published | 7,229 software-derived positions from eight sources are held as candidate records. |
| Cascino Eco/Bsu reanalysis, `BTED_EXT_2026_105` | Audit only | Reuses sequencing data underlying S001/S003; not added as an independent endpoint dataset. |

Files and supplemental-table relationships are described in the [release guide](releases/v0.4.0.md). Source identifiers, reference versions and original attributes remain available in the registered data.
