-- One verified active reference snapshot. Raw archives remain at their fixed HF revision.
CREATE TABLE IF NOT EXISTS hf_runtime_release (
  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  reference_revision TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('loading','ready')),
  genome_count INTEGER NOT NULL,
  file_count INTEGER NOT NULL,
  projection_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hf_runtime_genomes (
  id INTEGER PRIMARY KEY,
  genome_id TEXT NOT NULL UNIQUE,
  batch TEXT NOT NULL,
  batch_rank INTEGER NOT NULL,
  otu_id TEXT NOT NULL,
  organism TEXT NOT NULL,
  genome_type TEXT NOT NULL,
  source_collection TEXT NOT NULL,
  taxonomy TEXT NOT NULL,
  augmentation_status TEXT NOT NULL,
  otu_augmentation_span INTEGER NOT NULL,
  otu_augmentation_window INTEGER NOT NULL,
  rfam_training_span INTEGER NOT NULL,
  rfam_training_window INTEGER NOT NULL,
  tes_prediction INTEGER NOT NULL,
  reference_bases INTEGER NOT NULL,
  reference_contigs INTEGER NOT NULL,
  reference_source TEXT NOT NULL,
  reference_source_sha256 TEXT NOT NULL,
  annotation_status TEXT NOT NULL,
  annotation_accession TEXT,
  annotation_features INTEGER,
  annotation_reason TEXT,
  annotation_source_gff_sha256 TEXT,
  annotation_circular_overhang_features INTEGER,
  validation_augmentation TEXT NOT NULL,
  validation_augmentation_features INTEGER NOT NULL,
  validation_prediction TEXT NOT NULL,
  validation_prediction_features INTEGER NOT NULL,
  metadata_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hf_runtime_files (
  genome_key INTEGER NOT NULL REFERENCES hf_runtime_genomes(id),
  file_kind INTEGER NOT NULL CHECK(file_kind BETWEEN 0 AND 8),
  byte_size INTEGER NOT NULL CHECK(byte_size>=0),
  sha256 TEXT NOT NULL CHECK(length(sha256)=64),
  PRIMARY KEY(genome_key,file_kind)
) WITHOUT ROWID;
