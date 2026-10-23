# 2026-10-22-experimental-membership

Selects references with published endpoints. Excludes only GCF_000005845.2 from the experimental directory; original scientific registrations remain. 20 references, 29,460 experimental records and 124,740 predicted regions.

`apply.sql` appends a versioned directory and activates its pointer; `rollback.sql` restores the prior pointer. Check the exact prior version before execution. Do not replay against another current release.

Sources and execution evidence: workspace `outputs/BTED-publication-2026-10-22/`. Schema and operating rules: [database guide](../../README.md).

## Eligibility evidence

- [PMID 38030608](https://pubmed.ncbi.nlm.nih.gov/38030608/), [article](https://doi.org/10.1038/s41467-023-43534-2), [data](https://www.ebi.ac.uk/biostudies/arrayexpress/studies/E-MTAB-12429).
- Reviewed D1 record: `BATTER_S1_002`, `audit_only`, `record_count=0`, `signals=[]`; source scope is Term-seq only, excluding RNAtag-seq.
- Existing author signal review: no BigWig found within E-MTAB-12429, SDRF and ERP142802; only FASTQ found. This migration does not claim a new exhaustive search.
- Supplementary Data 3 exists, but per-record experimental origin and the retained Term-seq sheet mapping still need review before admission. NC_000913.2 endpoints cannot be reused as NC_000913.3 coordinates.
- Prepared using `scripts/prepare_experimental_membership.py`; `verification.json` contains expected totals and exclusions. Rollback retains scientific tables and old directory versions.

The new summary pins `reference_registry_version` to v5. Audit-only legacy URLs read their registered metadata and classification from that explicit D1 version; they do not re-enter the experimental directory or use a TSV fallback.
