# 2026-10-22-predictions

Restores existing predictions in directory v5; does not run inference or change scientific assets. Wider registry: 129,187 regions on 21 references.

`apply.sql` appends a versioned directory and activates its pointer; `rollback.sql` restores the prior pointer. Check the exact prior version before execution. Do not replay against another current release.

Sources and execution evidence: workspace `outputs/BTED-query-2026-10-22/`. Schema and operating rules: [database guide](../../README.md).
