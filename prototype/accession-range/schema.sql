PRAGMA foreign_keys = ON;

-- Cloudflare D1 preview projection of the verified canonical release.
-- Source annotations and gene rows remain outside D1: they are served as
-- registered HF/metadata assets and the current catalogue UI does not query
-- gene records. This is not a PostgreSQL promotion or a new data release.

CREATE TABLE IF NOT EXISTS release_versions (
  release_version TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK (status IN ('preview', 'published', 'retired')),
  is_current INTEGER NOT NULL DEFAULT 0 CHECK (is_current IN (0, 1)),
  release_date TEXT,
  canonical_manifest_path TEXT NOT NULL,
  canonical_manifest_sha256 TEXT NOT NULL CHECK (length(canonical_manifest_sha256) = 64),
  asset_origin_status TEXT NOT NULL CHECK (asset_origin_status IN ('verified', 'planned_not_verified', 'local_verified')),
  materializer_version TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS one_current_release
  ON release_versions (is_current) WHERE is_current = 1;

CREATE TABLE IF NOT EXISTS publications (
  pmid TEXT PRIMARY KEY,
  doi TEXT,
  pmc TEXT,
  published_year INTEGER,
  journal TEXT,
  paper_title TEXT NOT NULL,
  citation_json TEXT
);

CREATE TABLE IF NOT EXISTS assemblies (
  assembly_pk INTEGER PRIMARY KEY AUTOINCREMENT,
  release_version TEXT NOT NULL REFERENCES release_versions(release_version),
  accession TEXT NOT NULL,
  assembly_name TEXT,
  organism_name TEXT NOT NULL,
  strain TEXT,
  taxon_id TEXT,
  reference_url TEXT,
  UNIQUE (release_version, accession)
);

CREATE TABLE IF NOT EXISTS contigs (
  contig_pk INTEGER PRIMARY KEY AUTOINCREMENT,
  release_version TEXT NOT NULL,
  assembly_accession TEXT NOT NULL,
  contig_accession TEXT NOT NULL,
  contig_name TEXT NOT NULL,
  length_bp INTEGER NOT NULL CHECK (length_bp > 0),
  sequence_sha256 TEXT,
  provenance_json TEXT,
  UNIQUE (release_version, assembly_accession, contig_accession),
  FOREIGN KEY (release_version, assembly_accession)
    REFERENCES assemblies (release_version, accession)
);

CREATE TABLE IF NOT EXISTS sources (
  source_pk INTEGER PRIMARY KEY AUTOINCREMENT,
  release_version TEXT NOT NULL,
  source_id TEXT NOT NULL,
  assembly_accession TEXT NOT NULL,
  publication_pmid TEXT,
  species TEXT NOT NULL,
  phylum TEXT,
  assay_family TEXT NOT NULL,
  evidence_class TEXT NOT NULL,
  release_status TEXT NOT NULL CHECK (release_status IN ('published_standardized', 'audit_only', 'to_review', 'blocked')),
  record_count INTEGER NOT NULL CHECK (record_count >= 0),
  used_for_batter_augmentation INTEGER NOT NULL CHECK (used_for_batter_augmentation IN (0, 1)),
  has_jbrowse INTEGER NOT NULL CHECK (has_jbrowse IN (0, 1)),
  accessibility_status TEXT,
  coordinate_status TEXT,
  processing_status TEXT,
  redistribution_status TEXT,
  manifest_path TEXT NOT NULL,
  manifest_sha256 TEXT NOT NULL CHECK (length(manifest_sha256) = 64),
  record_root TEXT,
  source_note TEXT,
  decision_note TEXT,
  known_limitations TEXT,
  UNIQUE (release_version, source_id),
  FOREIGN KEY (release_version, assembly_accession)
    REFERENCES assemblies (release_version, accession),
  FOREIGN KEY (publication_pmid) REFERENCES publications (pmid),
  CHECK (
    (release_status = 'audit_only' AND record_count = 0 AND has_jbrowse = 0 AND evidence_class = 'NA')
    OR release_status <> 'audit_only'
  ),
  CHECK (
    release_status <> 'published_standardized'
    OR (record_count > 0 AND evidence_class IN ('observed_signal', 'called_endpoint', 'author_called_endpoint', 'curated_record'))
  )
);

CREATE TABLE IF NOT EXISTS source_accessions (
  source_accession_pk INTEGER PRIMARY KEY AUTOINCREMENT,
  release_version TEXT NOT NULL,
  source_id TEXT NOT NULL,
  accession_namespace TEXT NOT NULL,
  accession TEXT NOT NULL,
  raw_value TEXT NOT NULL,
  accession_type TEXT,
  ordinal INTEGER NOT NULL,
  external_url TEXT,
  UNIQUE (release_version, source_id, accession_namespace, accession),
  FOREIGN KEY (release_version, source_id) REFERENCES sources (release_version, source_id)
);

CREATE TABLE IF NOT EXISTS assets (
  asset_key TEXT PRIMARY KEY,
  release_version TEXT NOT NULL REFERENCES release_versions(release_version),
  assembly_accession TEXT,
  source_id TEXT,
  asset_kind TEXT NOT NULL CHECK (asset_kind IN ('fasta', 'fai', 'gff3', 'tbi', 'bigwig', 'bed', 'config', 'metadata', 'checksum', 'archive')),
  logical_path TEXT NOT NULL,
  origin_url TEXT NOT NULL,
  origin_host TEXT NOT NULL,
  content_type TEXT NOT NULL,
  byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
  sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
  supports_range INTEGER NOT NULL CHECK (supports_range IN (0, 1)),
  redistribution_status TEXT NOT NULL,
  is_public INTEGER NOT NULL CHECK (is_public IN (0, 1)),
  active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
  UNIQUE (release_version, logical_path),
  FOREIGN KEY (release_version, assembly_accession) REFERENCES assemblies (release_version, accession),
  FOREIGN KEY (release_version, source_id) REFERENCES sources (release_version, source_id)
);

CREATE TABLE IF NOT EXISTS tracks (
  track_id TEXT PRIMARY KEY,
  release_version TEXT NOT NULL,
  source_id TEXT NOT NULL,
  assembly_accession TEXT NOT NULL,
  publication_year INTEGER,
  pmid TEXT,
  doi TEXT,
  paper_title TEXT,
  journal TEXT,
  raw_accessions_json TEXT,
  assay TEXT NOT NULL,
  evidence_class TEXT NOT NULL,
  record_count INTEGER NOT NULL CHECK (record_count >= 0),
  asset_key TEXT,
  is_public INTEGER NOT NULL CHECK (is_public IN (0, 1)),
  display_order INTEGER NOT NULL,
  metadata_json TEXT,
  UNIQUE (release_version, source_id),
  FOREIGN KEY (release_version, source_id) REFERENCES sources (release_version, source_id),
  FOREIGN KEY (release_version, assembly_accession) REFERENCES assemblies (release_version, accession),
  FOREIGN KEY (asset_key) REFERENCES assets (asset_key)
);

CREATE TABLE IF NOT EXISTS endpoints (
  end_id TEXT PRIMARY KEY,
  release_version TEXT NOT NULL,
  source_id TEXT NOT NULL,
  sample_id TEXT NOT NULL,
  assay TEXT NOT NULL,
  evidence_class TEXT NOT NULL CHECK (evidence_class IN ('observed_signal', 'called_endpoint', 'author_called_endpoint', 'curated_record')),
  author_endpoint_id TEXT,
  published_reference_accession TEXT NOT NULL,
  reference_assembly TEXT NOT NULL,
  reference_name TEXT NOT NULL,
  replicon_label TEXT NOT NULL,
  biological_coordinate_1based INTEGER NOT NULL CHECK (biological_coordinate_1based >= 1),
  gff_start_1based INTEGER NOT NULL CHECK (gff_start_1based >= 1),
  gff_end_1based INTEGER NOT NULL CHECK (gff_end_1based >= gff_start_1based),
  strand TEXT NOT NULL CHECK (strand IN ('+', '-')),
  signal_or_score TEXT NOT NULL,
  author_category TEXT,
  associated_gene_or_locus TEXT,
  pmid TEXT,
  doi TEXT,
  source_table_or_file TEXT NOT NULL,
  coordinate_interpretation TEXT NOT NULL,
  original_row_reference TEXT NOT NULL,
  qc_status TEXT NOT NULL,
  note TEXT NOT NULL,
  UNIQUE (release_version, end_id),
  FOREIGN KEY (release_version, source_id) REFERENCES sources (release_version, source_id),
  CHECK (gff_start_1based = biological_coordinate_1based),
  CHECK (gff_end_1based = biological_coordinate_1based)
);

CREATE INDEX IF NOT EXISTS contigs_by_assembly
  ON contigs (release_version, assembly_accession, contig_accession);
CREATE INDEX IF NOT EXISTS sources_by_catalogue
  ON sources (release_version, source_id, assembly_accession);
CREATE INDEX IF NOT EXISTS tracks_by_assembly
  ON tracks (release_version, assembly_accession, display_order);
CREATE INDEX IF NOT EXISTS assets_by_assembly
  ON assets (release_version, assembly_accession, asset_kind, is_public);
CREATE INDEX IF NOT EXISTS assets_by_source
  ON assets (release_version, source_id, asset_kind, is_public);
CREATE INDEX IF NOT EXISTS endpoints_by_source
  ON endpoints (release_version, source_id, end_id);
CREATE INDEX IF NOT EXISTS endpoints_by_assembly_position
  ON endpoints (release_version, reference_assembly, reference_name, biological_coordinate_1based);
CREATE INDEX IF NOT EXISTS endpoints_by_locus
  ON endpoints (release_version, associated_gene_or_locus);

-- BATTER's genome-level predictions and training records are a separate
-- catalogue from BTED's study-derived experimental endpoints.
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
