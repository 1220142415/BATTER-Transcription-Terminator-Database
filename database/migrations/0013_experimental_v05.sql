-- Approved v0.5.0 scientific registrations. Run only the reviewed release operation,
-- never replay all migrations against production. Existing coordinate tables stay intact.
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS bted_experimental_v05_assemblies(
 accession TEXT PRIMARY KEY,organism TEXT NOT NULL,endpoint_count INTEGER NOT NULL,
 source_count INTEGER NOT NULL,contigs_json TEXT NOT NULL CHECK(json_valid(contigs_json)),
 hf_revision TEXT NOT NULL CHECK(length(hf_revision)=40));
CREATE TABLE IF NOT EXISTS bted_experimental_v05_sources(
 source_id TEXT PRIMARY KEY,assembly_accession TEXT NOT NULL REFERENCES bted_experimental_v05_assemblies(accession),
 pmid TEXT NOT NULL,doi TEXT NOT NULL,evidence_class TEXT NOT NULL,assay TEXT NOT NULL,
 record_count INTEGER NOT NULL,metadata_json TEXT NOT NULL CHECK(json_valid(metadata_json)));
CREATE TABLE IF NOT EXISTS bted_experimental_v05_files(
 logical_path TEXT PRIMARY KEY,assembly_accession TEXT NOT NULL REFERENCES bted_experimental_v05_assemblies(accession),
 source_id TEXT REFERENCES bted_experimental_v05_sources(source_id),
 file_kind TEXT NOT NULL,byte_size INTEGER NOT NULL,sha256 TEXT NOT NULL CHECK(length(sha256)=64),
 hf_revision TEXT NOT NULL CHECK(length(hf_revision)=40));
CREATE INDEX IF NOT EXISTS bted_v05_file_assembly ON bted_experimental_v05_files(assembly_accession);
CREATE INDEX IF NOT EXISTS bted_v05_file_source ON bted_experimental_v05_files(source_id);

