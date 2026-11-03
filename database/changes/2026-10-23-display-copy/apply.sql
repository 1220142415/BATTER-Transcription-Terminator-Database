-- Display metadata only; keep the active directory, ranks and scientific files.
UPDATE bted_collections SET label='GEM', taxonomy_label='GTDB R98 (GEM)',
  description='BATTER predictions and augmentation/Rfam regions from GEM and other genome sources.'
WHERE collection='gem' AND version='202610220000000000000003'
  AND label='GEM catalogue · Legacy'
  AND taxonomy_label='GEM / GTDB (original; release not established)'
  AND description='Archived computational catalogue, including GEM, IMG, NCBI and published-study sources. Predictions are retained without further updates.';

UPDATE sources SET metadata_json=json_remove(metadata_json,'$.interpretation_note')
WHERE release_version='v0.4.0'
  AND source_id IN ('BTED_EXT_2026_102','BTED_EXT_2026_103','BTED_EXT_2026_104')
  AND json_extract(metadata_json,'$.interpretation_note')='Study-defined ends only; uncertain peaks excluded.';
