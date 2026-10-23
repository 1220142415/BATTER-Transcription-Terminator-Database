-- Small, immutable directory projection. Scientific metadata stays in its original tables.
CREATE TABLE IF NOT EXISTS hf_directory_releases (
  version TEXT PRIMARY KEY,
  reference_revision TEXT NOT NULL,
  annotation_revision TEXT NOT NULL,
  summary_json TEXT NOT NULL CHECK (json_valid(summary_json)),
  status TEXT NOT NULL CHECK (status IN ('loading', 'ready'))
);
CREATE TABLE IF NOT EXISTS hf_directory_genomes (
  id INTEGER PRIMARY KEY,
  version TEXT NOT NULL REFERENCES hf_directory_releases(version),
  genome_id TEXT NOT NULL,
  accession_key TEXT NOT NULL,
  organism_key TEXT NOT NULL,
  organism TEXT NOT NULL,
  source TEXT NOT NULL,
  genome_type TEXT NOT NULL,
  annotation TEXT NOT NULL,
  endpoints INTEGER NOT NULL,
  predictions INTEGER NOT NULL,
  training INTEGER NOT NULL,
  size INTEGER,
  contigs INTEGER,
  phylum TEXT NOT NULL, class TEXT NOT NULL, "order" TEXT NOT NULL,
  family TEXT NOT NULL, genus TEXT NOT NULL, species TEXT NOT NULL,
  search_text TEXT NOT NULL,
  recovered_matched INTEGER,
  recovered_total INTEGER,
  recovered_coverage TEXT,
  UNIQUE (version, genome_id)
);
CREATE INDEX IF NOT EXISTS directory_accession ON hf_directory_genomes(version, accession_key);
CREATE INDEX IF NOT EXISTS directory_organism ON hf_directory_genomes(version, organism_key, accession_key);
CREATE INDEX IF NOT EXISTS directory_endpoints ON hf_directory_genomes(version, endpoints DESC, accession_key);
CREATE INDEX IF NOT EXISTS directory_endpoints_asc ON hf_directory_genomes(version, endpoints, accession_key);
CREATE INDEX IF NOT EXISTS directory_predictions ON hf_directory_genomes(version, predictions DESC, accession_key);
CREATE INDEX IF NOT EXISTS directory_predictions_asc ON hf_directory_genomes(version, predictions, accession_key);
CREATE INDEX IF NOT EXISTS directory_training ON hf_directory_genomes(version, training DESC, accession_key);
CREATE INDEX IF NOT EXISTS directory_training_asc ON hf_directory_genomes(version, training, accession_key);
CREATE INDEX IF NOT EXISTS directory_size ON hf_directory_genomes(version, (size IS NULL), size, accession_key);
CREATE INDEX IF NOT EXISTS directory_size_desc ON hf_directory_genomes(version, (size IS NULL), size DESC, accession_key);
CREATE INDEX IF NOT EXISTS directory_source ON hf_directory_genomes(version, source);
CREATE INDEX IF NOT EXISTS directory_type ON hf_directory_genomes(version, genome_type);
CREATE INDEX IF NOT EXISTS directory_annotation ON hf_directory_genomes(version, annotation);
CREATE INDEX IF NOT EXISTS directory_taxonomy ON hf_directory_genomes(version, phylum, class, "order", family, genus, species);
CREATE VIRTUAL TABLE IF NOT EXISTS hf_directory_search USING fts5(
  search_text, content='hf_directory_genomes', content_rowid='id', tokenize='trigram', detail=none, columnsize=0
);
