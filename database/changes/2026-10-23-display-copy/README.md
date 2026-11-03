# Public display copy

Rename `GEM catalogue · Legacy` to `GEM`, identify the user-confirmed GEM taxonomy
as GTDB R98 and replace the archive-status description with its data contents.
The active GEM directory remains `202610220000000000000003`; taxonomy record keys,
ranks, counts, file registrations and scientific versions do not change.
Remove the exclusion-status sentence from the three published Cascino source cards.
Both SQL files guard the affected prior values.

Apply `apply.sql` after recording the current collection row and recovery bookmark.
Read back the affected fields and `/api/collections`, then deploy the matching pages.
To reverse these edits while their guards still hold, apply `rollback.sql` and
restore Worker `dec45f7c-b155-4257-b196-7f33cd822a38`.
