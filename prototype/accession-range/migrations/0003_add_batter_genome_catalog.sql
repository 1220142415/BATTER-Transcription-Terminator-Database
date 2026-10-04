CREATE TABLE IF NOT EXISTS batter_genomes (
  genome_id TEXT PRIMARY KEY,
  otu_id TEXT NOT NULL,
  batch_rank INTEGER NOT NULL,
  genome_type TEXT NOT NULL CHECK (genome_type IN ('MAG', 'isolate', 'SAG')),
  source_collection TEXT NOT NULL,
  taxonomy TEXT NOT NULL,
  domain TEXT NOT NULL,
  phylum TEXT NOT NULL,
  class TEXT NOT NULL,
  "order" TEXT NOT NULL,
  family TEXT NOT NULL,
  genus TEXT NOT NULL,
  species TEXT NOT NULL,
  tes_prediction INTEGER NOT NULL CHECK (tes_prediction >= 0),
  otu_augmentation_window INTEGER NOT NULL CHECK (otu_augmentation_window >= 0),
  otu_augmentation_span INTEGER NOT NULL CHECK (otu_augmentation_span >= 0),
  rfam_training_window INTEGER NOT NULL CHECK (rfam_training_window >= 0),
  rfam_training_span INTEGER NOT NULL CHECK (rfam_training_span >= 0),
  augmentation_status TEXT NOT NULL CHECK (augmentation_status IN ('has_features', 'no_records_in_source')),
  prediction_gff3_path TEXT NOT NULL,
  prediction_gff3_sha256 TEXT NOT NULL CHECK (length(prediction_gff3_sha256) = 64),
  augmentation_gff3_path TEXT NOT NULL,
  augmentation_gff3_sha256 TEXT NOT NULL CHECK (length(augmentation_gff3_sha256) = 64),
  reference_cohort TEXT,
  reference_genome_id TEXT,
  reference_fasta_path TEXT,
  reference_compressed_bytes INTEGER,
  reference_sha256 TEXT,
  reference_contigs INTEGER,
  reference_bases INTEGER,
  search_text TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS batter_genomes_by_otu ON batter_genomes (otu_id);
CREATE INDEX IF NOT EXISTS batter_genomes_by_source_type ON batter_genomes (source_collection, genome_type);
CREATE INDEX IF NOT EXISTS batter_genomes_by_phylum_class_order ON batter_genomes (phylum, class, "order");
CREATE INDEX IF NOT EXISTS batter_genomes_by_family_genus_species ON batter_genomes (family, genus, species);
CREATE INDEX IF NOT EXISTS batter_genomes_by_prediction_count ON batter_genomes (tes_prediction DESC);
CREATE INDEX IF NOT EXISTS batter_genomes_by_otu_count ON batter_genomes (otu_augmentation_span DESC);
CREATE INDEX IF NOT EXISTS batter_genomes_by_rfam_count ON batter_genomes (rfam_training_span DESC);
