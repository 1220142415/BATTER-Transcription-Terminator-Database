-- Display descriptions only; preserve collection versions and scientific records.
UPDATE bted_collections SET description='BATTER-TPE predictions on GTDB R207.0 assemblies. Fixed, partially published catalogue.'
WHERE collection='gtdb' AND version='deffa4a7183f71a8b47b3c44'
  AND description='BATTER-TPE predictions for GTDB R207.0 genomes.';

UPDATE bted_collections SET description='Study-reported transcript 3′ ends, BATTER-TPE predictions, original publications and condition-specific coverage tracks.'
WHERE collection='experimental' AND version='202610220000000000000006'
  AND description='Study-reported transcript 3′ ends, predicted regions and signal tracks.';

UPDATE bted_collections SET description='BATTER predictions and augmentation/Rfam regions from GEM and other genome sources.'
WHERE collection='gem' AND version='202610220000000000000003'
  AND description='BATTER predictions and training regions from GEM and other genome sources.';

