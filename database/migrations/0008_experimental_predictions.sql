ALTER TABLE assemblies ADD COLUMN prediction_count INTEGER NOT NULL DEFAULT 0 CHECK (prediction_count >= 0);
ALTER TABLE assemblies ADD COLUMN prediction_run TEXT;
ALTER TABLE assemblies ADD COLUMN prediction_revision TEXT;
ALTER TABLE assemblies ADD COLUMN prediction_reference_sha256 TEXT;
ALTER TABLE assemblies ADD COLUMN prediction_contig_counts_json TEXT CHECK (prediction_contig_counts_json IS NULL OR json_valid(prediction_contig_counts_json));
