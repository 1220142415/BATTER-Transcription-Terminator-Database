-- Correct the display label only; preserve GEM annotations and directory keys.
UPDATE bted_collections SET taxonomy_label='GTDB R89 (GEM)'
WHERE collection='gem' AND version='202610220000000000000003'
  AND label='GEM' AND taxonomy_label='GTDB R98 (GEM)';
