-- Independent catalogue releases; existing links and scientific tables stay intact.
CREATE TABLE IF NOT EXISTS bted_collections (
  collection TEXT PRIMARY KEY CHECK(collection IN ('gtdb','experimental','gem')),
  version TEXT NOT NULL REFERENCES hf_directory_releases(version),
  label TEXT NOT NULL,
  taxonomy_label TEXT NOT NULL,
  description TEXT NOT NULL,
  source_genome_count INTEGER NOT NULL,
  partial INTEGER NOT NULL CHECK(partial IN (0,1))
);
CREATE TABLE IF NOT EXISTS gtdb_genome_assets (
  version TEXT NOT NULL,
  genome_id TEXT NOT NULL,
  asset_group TEXT NOT NULL,
  asset_revision TEXT NOT NULL CHECK(length(asset_revision)=40),
  PRIMARY KEY(version,genome_id),
  FOREIGN KEY(version,genome_id) REFERENCES hf_directory_genomes(version,genome_id)
) WITHOUT ROWID;
