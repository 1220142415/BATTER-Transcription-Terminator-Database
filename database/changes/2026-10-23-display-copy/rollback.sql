UPDATE bted_collections SET label='GEM catalogue · Legacy',
  taxonomy_label='GEM / GTDB (original; release not established)',
  description='Archived computational catalogue, including GEM, IMG, NCBI and published-study sources. Predictions are retained without further updates.'
WHERE collection='gem' AND version='202610220000000000000003'
  AND label='GEM' AND taxonomy_label='GTDB R98 (GEM)'
  AND description='BATTER predictions and augmentation/Rfam regions from GEM and other genome sources.';

UPDATE sources SET metadata_json=json_set(metadata_json,'$.interpretation_note','Study-defined ends only; uncertain peaks excluded.')
WHERE release_version='v0.4.0'
  AND source_id IN ('BTED_EXT_2026_102','BTED_EXT_2026_103','BTED_EXT_2026_104')
  AND json_type(metadata_json,'$.interpretation_note') IS NULL;
