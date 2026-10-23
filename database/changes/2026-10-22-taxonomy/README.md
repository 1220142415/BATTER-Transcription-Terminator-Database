# 2026-10-22-taxonomy

Separates NCBI, GTDB R207.0 and original GEM classification records. Initial wider registry: 21 references, with unmatched entries retained.

`apply.sql` appends a versioned directory and activates its pointer; `rollback.sql` restores the prior pointer. Check the exact prior version before execution. Do not replay against another current release.

Sources and execution evidence: workspace `outputs/BTED-taxonomy-2026-10-22/`. Schema and operating rules: [database guide](../../README.md).
