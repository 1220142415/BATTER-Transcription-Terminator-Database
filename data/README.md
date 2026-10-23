# Data directory

| Directory | Contents |
|---|---|
| `public/v0.4.0/` | Frozen experimental GFF3, supplementary tables, metadata and file inventory |
| `registry/` | Build bindings, registered assets, source extracts and reference mappings |
| `registry/internal/` | Provenance and inclusion/exclusion evidence |
| `archive/` | Original release archives required for reproducibility and validation |
| `audit/` | Candidate-data and redistribution review records |

Production metadata is served from D1. Frozen metadata files document their release; they are not an alternative production source. Database schema and corrections are under [`database/`](../database/README.md). Large exports and import candidates belong in the ignored `dist/d1/<operation>/` directory.

The v0.4.0 package registers 21 references. Twenty have published experimental endpoints; S002 / `GCF_000005845.2` is metadata-only. See [membership rules](../docs/COLLECTIONS.md#experimental-membership).

Retain source accessions, article and supplementary-file URLs, reference versions, field mappings and curation decisions. Original scientific files and evidence remain in their source language and format.
