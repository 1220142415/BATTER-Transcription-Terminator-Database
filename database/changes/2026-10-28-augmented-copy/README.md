# Augmented-region display copy

Applied to production on 2026-10-28. The website uses the updated static collection
description; this delta aligns the D1 collections API description. The precondition
and readback matched; official apply cost was 1 row read and 1 row written.
Evidence: workspace `BTED/_workspace/outputs/BTED-augmented-copy-2026-10-28/d1-{before-retry,apply,after}.json`.

`apply.sql` changes one GEM description, guarded by its current collection version
and prior text. It does not activate pending recovered annotations or change any
directory, file revision, counts or scientific records. Do not replay a full import.

Before an authorized production update, inspect only the indexed GEM collection
row and confirm its version and description match the guard. Apply the delta and
read back that row; expect one changed row. A zero-row update requires inspection,
not an unguarded retry. `rollback.sql` restores the prior description on the same
version. Local SQLite checks cover apply, no-op repeat, rollback and version guards.
