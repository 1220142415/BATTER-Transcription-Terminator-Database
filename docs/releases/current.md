# Current deployment

Production: [BTED](https://bted.1052596411.workers.dev/).

The last accepted deployment is **2026-10-23**, Worker `dec45f7c-b155-4257-b196-7f33cd822a38`.

| Item | Active state |
|---|---|
| Experimental directory | `202610220000000000000006` |
| Experimental references | 20 |
| Experimental records | 29,460 |
| Predicted regions in the experimental collection | 124,740 |
| GTDB directory | `deffa4a7183f71a8b47b3c44` |
| GEM directory | `202610220000000000000003` |

## Accepted changes

Project documentation, comments and diagnostics are English. Genome source filtering is limited to GEM; sorting uses table headers on desktop and mobile. Pinned JBrowse sequence fixes retain genomic modes for CDS-only annotations and stop repeated sequence requests in the dialog.

Validation passed 93 Python tests, the Node regression checks, Markdown links and fresh 608-file staging. Browser checks covered all three collection filters and header sorting, cached experimental search, mobile layout, genomic sequence modes and the sequence dialog. Dialog sequence requests stabilized at three calls. Live checks confirmed the versioned patches, healthy APIs and unchanged collection metadata and counts. Evidence: workspace `outputs/BTED-copy-browser-2026-10-23/`.

This deployment required no D1 import or scientific-file changes.

## Code-only recovery

Restore the previous accepted Worker without changing D1:

```sh
npx wrangler rollback 39b349d7-421f-4652-96e0-99953acb19c1 --config worker/wrangler.jsonc
```

## Membership recovery

The previous membership correction and its evidence are recorded in workspace `outputs/BTED-publication-2026-10-22/`. Use the following only to reverse that data correction, while v6 remains active and no later correction has superseded it:

```sh
npx wrangler d1 execute bted-catalog --remote --config worker/wrangler.jsonc --file database/changes/2026-10-22-experimental-membership/rollback.sql --yes
npx wrangler rollback 22be45cd-f97b-429b-8ede-0aed1659403b --config worker/wrangler.jsonc
```

Read `/api/collections` to confirm v5. Restore local collection/cache bindings before redeployment. Rollback retains new directory rows and does not reimport scientific files.
