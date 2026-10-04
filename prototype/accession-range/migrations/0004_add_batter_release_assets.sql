-- Release-specific asset projection; raw scientific catalogue remains separate.
CREATE TABLE IF NOT EXISTS batter_release_assets (
  genome_id TEXT NOT NULL,
  release_version TEXT NOT NULL,
  publication_status TEXT NOT NULL CHECK (publication_status IN ('local_prepared', 'public_download', 'held')),
  metadata_json TEXT NOT NULL,
  PRIMARY KEY (genome_id, release_version)
);
