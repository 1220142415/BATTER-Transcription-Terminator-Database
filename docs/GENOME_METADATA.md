# Genome detail metadata

Genome pages show the registered reference, six taxonomic ranks (phylum through species), available data, browser, studies and downloads. The page title retains the organism name from the study metadata. The taxonomy block uses the name in the named classification source, which can differ from the study name.

## Experimental references

`data/registry/genome_taxonomy.tsv` contains NCBI Taxonomy lineages for 21 reference accessions, retrieved on 2026-10-05. Each row records the TaxID, source URL and retrieval date. The 20 TaxIDs come from NCBI assembly metadata. The `GCF_000005845.1` report was empty; that row uses TaxID 511145 for the explicitly named *E. coli* K-12 MG1655 organism. This taxonomic association does not establish sequence equivalence between assembly versions.

The downloaded response and request are preserved in the companion evidence directory `BTED-metadata-evidence-2026-10-05`:

- `ncbi-taxonomy-2026-10-05.xml`: SHA-256 `f139183ae008e8fc748e8827e0367ea5e0cb17eb08868b2c397a62c89c66c6d5`.
- `ncbi-taxonomy-request.json`: exact NCBI efetch URL, TaxIDs, date and response checksum.
- `assembly/<accession>.json`: reference strain and TaxID from NCBI assembly metadata.

Reference lengths and contig counts come from the existing browser metadata registries (`reference_contigs.v0.2.0.json` and `browser_refs/contigs.tsv`). They are not replaced by the lengths of newer NCBI assemblies. This update did not inspect FASTA or GFF files.

## Computational references

Computational pages retain the GEM catalogue's GTDB lineage and link to the [original taxonomy table](https://portal.nersc.gov/GEM/otus/otu_taxonomy.tsv). These names are not updated to current NCBI ranks. Missing ranks display `Not assigned`.

An overlapping experimental/computational page shows the NCBI classification for its experimental reference and a separate computational reference panel. GEM OTU, input FASTA and source checksum identify the computational input. Sharing an accession does not establish that the sequence or coordinate system is identical.

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
