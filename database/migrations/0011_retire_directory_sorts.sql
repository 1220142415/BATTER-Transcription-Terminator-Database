-- Deploy the Worker that rejects predictions ASC and all training sorts first.
-- Existing directories only: preserve rows, search, filters and default sorting.
DROP INDEX IF EXISTS directory_predictions_asc;
DROP INDEX IF EXISTS directory_training;
DROP INDEX IF EXISTS directory_training_asc;
