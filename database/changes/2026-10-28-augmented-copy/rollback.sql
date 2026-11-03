-- Restore display copy only, while the same collection version remains active.
UPDATE bted_collections
SET description='BATTER predictions and training regions from GEM and other genome sources.'
WHERE collection='gem' AND version='765f663d12e49b06721ca001'
  AND description='Predicted and augmented regions from GEM and other genome sources.';
