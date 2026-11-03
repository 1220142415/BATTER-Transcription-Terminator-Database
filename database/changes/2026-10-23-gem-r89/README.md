# GEM R89 display correction

Supersedes the R98 label introduced by `../2026-10-23-display-copy/`.
All 45,599 GEM OTU classification paths match the official GTDB R89 framework;
7,137 match R89 but neither adjacent release R86 nor R95.
Methods and complete comparisons: workspace `BTED/_workspace/outputs/BTED-GEM-version-check-2026-10-23/`.

`apply.sql` changes only the active GEM collection's taxonomy label, guarded by
its directory version and previous labels. GEM rank values, the `gem_original`
system and its empty version key remain unchanged. No scientific files change.
`rollback.sql` restores the preceding label with the same guards; use with the
previous Worker identified in `docs/releases/current.md`.
