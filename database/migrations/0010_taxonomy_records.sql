-- Classification is separate from organism identity and scientific coordinates.
ALTER TABLE bted_collections ADD COLUMN taxonomy_system TEXT NOT NULL DEFAULT '';
ALTER TABLE bted_collections ADD COLUMN taxonomy_version TEXT NOT NULL DEFAULT '';
CREATE TABLE bted_taxonomy_records (
  version TEXT NOT NULL,
  genome_id TEXT NOT NULL,
  system TEXT NOT NULL CHECK(system IN ('ncbi','gtdb','gem_original')),
  taxonomy_version TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('verified','retained','unmatched','pending')),
  tax_id INTEGER,
  scientific_name TEXT NOT NULL DEFAULT '',
  matched_accession TEXT NOT NULL DEFAULT '',
  match_method TEXT NOT NULL,
  domain TEXT NOT NULL DEFAULT '',
  phylum TEXT NOT NULL DEFAULT '', class TEXT NOT NULL DEFAULT '', "order" TEXT NOT NULL DEFAULT '',
  family TEXT NOT NULL DEFAULT '', genus TEXT NOT NULL DEFAULT '', species TEXT NOT NULL DEFAULT '',
  source_url TEXT NOT NULL,
  retrieved_at TEXT NOT NULL,
  evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
  PRIMARY KEY(version,genome_id,system,taxonomy_version),
  FOREIGN KEY(version,genome_id) REFERENCES hf_directory_genomes(version,genome_id),
  CHECK(status NOT IN ('pending','unmatched') OR
    (domain='' AND phylum='' AND class='' AND "order"='' AND family='' AND genus='' AND species=''))
) WITHOUT ROWID;
