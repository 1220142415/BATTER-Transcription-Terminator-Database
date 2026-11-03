-- Display copy only. Do not change collection pointers or scientific records.
UPDATE bted_collections
SET description='Predicted and augmented regions from GEM and other genome sources.'
WHERE collection='gem' AND version='765f663d12e49b06721ca001'
  AND description='BATTER predictions and training regions from GEM and other genome sources.';
