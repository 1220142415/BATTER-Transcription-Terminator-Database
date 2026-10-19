# Genome detail metadata

Genome pages show the registered reference, six taxonomic ranks (phylum through species), available data, browser, studies and downloads. The page title retains the organism name from the study metadata. The taxonomy block uses the name in the named classification source, which can differ from the study name.

## Genome origin and taxonomy source

`Genome source` records the original database or study, as preserved by GEM's combined catalogue. The 42,904 computational genomes comprise GEM (12,793), IMG (7,791), NCBI GenBank (7,790), NCBI RefSeq (10,707), Pasolli et al. (2,637), Almeida et al. (602), and Nayfach et al. (584). These seven origins remain distinct. All 42,904 original source labels, OTU assignments and taxonomy strings were checked against GEM's original membership and taxonomy tables with no mismatches.

Using taxonomy supplied by the GEM catalogue does not mean that a genome originated in the GEM study. The catalogue also clustered and classified genomes from the other sources. In the UI, NCBI-MAG and NCBI-SAG are grouped as NCBI GenBank; the original labels remain in the underlying records.

## Experimental references

`data/registry/genome_taxonomy.tsv` uses the original GEM catalogue's GTDB-based taxonomy for experimental references, aligned on 2026-10-15. Sixteen of the 21 complete assembly accessions occur in GEM's `genome_to_otu.tsv`; their six ranks are copied from the corresponding `otu_taxonomy.tsv` row. `gem_otu_id` and `taxonomy_status` record the mapping. GEM membership here supplies taxonomy only; it does not add a computational dataset or change reference sequences.

Five references have no exact assembly match: `GCF_000005845.1`, `GCF_003932715.1`, `GCF_005519465.1`, `GCF_015710995.1` and `GCF_018282115.1`. Their six ranks are unassigned and the page states that no exact match was found. A different assembly version or similar organism name is not accepted as a match. Filling these entries requires a verified historical mapping or sequence classification against a confirmed matching GTDB release; the GEM release number has not been established.

Reference strain and NCBI TaxID remain identity metadata, separate from the displayed GEM classification. The original 2026-10-05 NCBI lineages are preserved in `dist/gem-taxonomy-2026-10-15/genome_taxonomy.before.tsv`. The `GCF_000005845.1` NCBI assembly report was empty; its TaxID 511145 records the explicitly named *E. coli* K-12 MG1655 organism and does not establish equivalence with another assembly version.

GEM assigns `GCF_000739105.1` (reference *Streptomyces lividans* TK24) to an OTU classified as *Streptomyces coelicolor*. The source classification is retained without renaming the study organism or strain. The GEM classification for `GCF_000005845.2` has no species assignment; that rank stays empty.

The downloaded response and request are preserved in the companion evidence directory `BTED-metadata-evidence-2026-10-05`:

- `ncbi-taxonomy-2026-10-05.xml`: SHA-256 `f139183ae008e8fc748e8827e0367ea5e0cb17eb08868b2c397a62c89c66c6d5`.
- `ncbi-taxonomy-request.json`: exact NCBI efetch URL, TaxIDs, date and response checksum.
- `assembly/<accession>.json`: reference strain and TaxID from NCBI assembly metadata.

Reference lengths and contig counts come from the existing browser metadata registries (`reference_contigs.v0.2.0.json` and `browser_refs/contigs.tsv`). They are not replaced by the lengths of newer NCBI assemblies. This update did not inspect FASTA or GFF files.

## Computational references

Computational pages retain the GEM catalogue's GTDB lineage and link to the [original taxonomy table](https://portal.nersc.gov/GEM/otus/otu_taxonomy.tsv). Both experimental and computational pages label the source `GEM / GTDB (original)`. The official table was downloaded again on 2026-10-15 and matched the archived copy; its HTTP last-modified date is 2020-09-24. The exact GTDB release number is not asserted. Missing ranks display `Not assigned`.

An overlapping experimental/computational page uses the same original GEM classification and a separate computational reference panel. GEM OTU, input FASTA and source checksum identify the computational input. Sharing an accession does not establish that the sequence or coordinate system is identical.

## Study context

The top summary separates experimental 3′-end records, predicted regions and augmentation / Rfam regions. Missing catalogue entries display `Not cataloged`; a registered count of zero remains `0`. Augmentation counts include OTU and Rfam spans, exclude their context windows, and retain the component counts. Experimental counts sum source records and can include overlapping sites.

Each study card shows the sum for that paper and this genome, with per-dataset counts when the paper has multiple source records. Method, sample strain, conditions, replicates and raw-data links remain visible. Internal source IDs, evidence details, licences and longer caveats are in `Source details`.

`data/registry/publications.tsv` contains the 14 paper titles and DOIs from the audited `corrected-metadata/experimental-metadata.corrected.tsv`. Repeated PMID entries were checked for agreement before extraction. `Read paper` links to the DOI; PubMed is also available. These display references do not replace the published metadata downloads.

`data/registry/source_context.tsv` adds sample strain, genotype, conditions, replicate description and shared-data relationships to source cards. Blank fields mean no verified value has been supplied here. Reference strain and sample strain remain separate fields.

The registry is a selected extract of `corrected-metadata/experimental-metadata.corrected.tsv` in the companion evidence directory. That file and `metadata-changes.tsv` record the field-level evidence. Before changing a value, check its cited paper or accession and retain the supporting response in the evidence directory.

Notable distinctions include:

- Lalanne 2018 (PMID 29606352): sample ML76, reference NA1000.
- Lee 2020 (PMID 33319794): sample M145, reference A3(2); sample NBRC 108819, reference NRRL 18488. These are not assumed to be identical strains.
- S007/S013 share PRJEB31507; S015/S017 share SRX6937123/4 (GEO GSM4105470/1). Source call sets remain separate; record totals are not counts of unique biological sites.
- Cascino 2026 (PMID 42148773): WT technical replicates GSM9264033/4 are combined in EXT102; Δmfd biological replicates GSM9264035/6 remain EXT103/104.

This presentation update does not replace the published metadata downloads, D1 records, endpoint counts or coordinate files. Pending scientific corrections remain listed in the audit's `corrected-metadata/pending-review.tsv`.
