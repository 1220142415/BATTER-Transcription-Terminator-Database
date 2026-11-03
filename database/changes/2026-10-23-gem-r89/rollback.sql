-- Restore the preceding display label only while this correction is active.
UPDATE bted_collections SET taxonomy_label='GTDB R98 (GEM)'
WHERE collection='gem' AND version='202610220000000000000003'
  AND label='GEM' AND taxonomy_label='GTDB R89 (GEM)';
