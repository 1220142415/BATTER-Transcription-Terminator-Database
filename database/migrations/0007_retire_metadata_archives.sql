-- Apply only after 0006 is ready, BTED_RUNTIME_FIELDS=on is deployed,
-- live checks pass, and both legacy tables have a verified restorable export.
-- Fixed HF scientific files and the experimental catalog are unaffected.
DROP TABLE IF EXISTS hf_registered_files;
DROP TABLE IF EXISTS hf_genome_metadata;
PRAGMA optimize;
