-- Immutable public HF metadata; existing experimental and analytics tables remain separate.
CREATE TABLE IF NOT EXISTS hf_metadata_releases (
  revision TEXT PRIMARY KEY CHECK (length(revision) = 40),
  release_version TEXT NOT NULL,
  manifest_sha256 TEXT NOT NULL CHECK (length(manifest_sha256) = 64),
  manifest_header_json TEXT NOT NULL CHECK (json_valid(manifest_header_json)),
  catalogue_header_json TEXT NOT NULL CHECK (json_valid(catalogue_header_json)),
  genome_count INTEGER NOT NULL,
  computational_count INTEGER NOT NULL,
  asset_count INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('loading', 'ready'))
);

CREATE TABLE IF NOT EXISTS hf_genome_metadata (
  revision TEXT NOT NULL REFERENCES hf_metadata_releases(revision),
  genome_id TEXT NOT NULL,
  group_name TEXT NOT NULL,
  catalogue_row_json TEXT CHECK (catalogue_row_json IS NULL OR json_valid(catalogue_row_json)),
  catalogue_entry_json TEXT NOT NULL CHECK (json_valid(catalogue_entry_json)),
  metadata_json TEXT NOT NULL CHECK (json_valid(metadata_json)),
  metadata_sha256 TEXT NOT NULL CHECK (length(metadata_sha256) = 64),
  PRIMARY KEY (revision, genome_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS hf_registered_files (
  revision TEXT NOT NULL REFERENCES hf_metadata_releases(revision),
  path TEXT NOT NULL,
  byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
  sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
  source_path TEXT,
  generated INTEGER CHECK (generated IS NULL OR generated IN (0, 1)),
  PRIMARY KEY (revision, path)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS hf_catalogue_pages (
  revision TEXT NOT NULL REFERENCES hf_metadata_releases(revision),
  page INTEGER NOT NULL,
  rows_json TEXT NOT NULL CHECK (json_valid(rows_json)),
  PRIMARY KEY (revision, page)
) WITHOUT ROWID;
