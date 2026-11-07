# Build and deploy

Production runs on [Cloudflare Workers](https://bted.1052596411.workers.dev/). Run commands from the repository root. The configuration is `worker/wrangler.jsonc`; generated assets are under `dist/worker-site/`. GitHub CI runs validation. The Pages workflow is an optional manual mirror, not the production deployment.

## Fixed inputs

| Input | Version |
|---|---|
| Retained experimental files | `data/public/v0.4.0/` at Git commit `8132334474a70cc609261fb0dc05011fbfd9e8ef` |
| Experimental v0.5.0 extension | HF `277f829ad3b408f60925122ff2a498c8a158e7c3`; nine new assemblies and 11 sources; D1 `bted_experimental_v05_*` |
| Experimental stride-1 predictions and SAP1 annotation | HF `1276a8436cebd8e4a646e7d437a04ae6f944e63d`; 29 prediction packages; per-file D1 bindings |
| v0.4 scientific assets | HF `eea5b7225975b224a1c837f60c4fa10497fef022` |
| Earlier references and signals | HF `90651318aedf5a5ca26b8308070927d36fd3d6c9`, bound per file |
| GEM computational references | HF `9f81698a3cee64f4eaf90b90cd36d640f38d9315` |
| Recovered gene annotations | HF `765f663d12e49b06721ca03aecc7d1c64daa78cb` |
| GTDB directory | D1 `19d287cdc5dab25026d996be`, snapshot metadata HF `a24ecb1b5192479036d328afcbd3a6ae8421cbea`; scientific files use their registered per-genome revisions |
| Collection bindings | `data/registry/collections.json` and D1 `bted_collections` |
| JBrowse application | Verified `preview-v0.2.0` release archive, application version 4.3.0 |

Local metadata includes corrections not republished in the frozen HF package. Build scientific-file checksums from the public snapshot above. Current study cards, samples and taxonomy come from D1 at runtime.

## Build

Use Python 3.12+, Node.js 24 and the plugin lockfile. Deployment requires an authorized Cloudflare login. Keep credentials out of source and command logs.

```sh
mkdir -p dist/published-snapshot dist/jbrowse-release
# Skip fetching if this commit is already available locally.
git fetch --depth=1 origin 8132334474a70cc609261fb0dc05011fbfd9e8ef
git archive 8132334474a70cc609261fb0dc05011fbfd9e8ef data/public/v0.4.0 | tar -x -C dist/published-snapshot

gh release download preview-v0.2.0 --repo seu-yolo/BATTER-Transcription-Terminator-Database --pattern 'BTED-v0.2.0-jbrowse-assets.tar.gz*' --dir dist/jbrowse-release
npm ci --prefix jbrowse-plugin
npm --prefix jbrowse-plugin run check
npm --prefix jbrowse-plugin run build

python scripts/stage_site.py --data-version v0.4.0 --mode worker \
  --release-root dist/published-snapshot/data/public/v0.4.0 \
  --release-archive dist/jbrowse-release/BTED-v0.2.0-jbrowse-assets.tar.gz \
  --release-sha256-file dist/jbrowse-release/BTED-v0.2.0-jbrowse-assets.tar.gz.sha256 \
  --hf-v04-data-base-url https://huggingface.co/datasets/liurulong/terminator/resolve/eea5b7225975b224a1c837f60c4fa10497fef022/v0.4.0 \
  --output-dir dist/worker-site
```

These examples use Bash; in PowerShell, place multiline arguments on one line. `--jbrowse-dir <package>` can replace the archive arguments for an already verified, unpacked original application package. Use the original package, not a previously patched site output.

## Test and preview

```sh
python scripts/validate_bted_v0_4.py
python scripts/validate_repo_layout.py
python scripts/check_markdown_links.py
python -m unittest discover -s tests -p 'test*.py' -q
node --test tests/*.mjs
python scripts/validate-site.py dist/worker-site
npx wrangler deploy --dry-run --config worker/wrangler.jsonc --outdir dist/worker-dry-run
```

Use `npx wrangler dev --config worker/wrangler.jsonc` for a Worker preview with a reviewed local D1 import. `serve_v04_preview.py` checks static assets and layout; it does not substitute for D1 API acceptance.

## Apply data changes and deploy

Code-only changes do not require a D1 import. For data changes, follow the [database guide](../database/README.md) and execute only the reviewed operation. Never replay all migrations as a deployment step.

GTDB and GEM each use their existing generic detail shell; all three collection
directories obtain the active version from D1. Production experimental detail
URLs resolve internally to one data-free
`experimental/genome.html` shell. The existing study cards, download package,
reference summary and browser controls query the standard D1 APIs using the URL's
assembly accession. Do not add per-assembly HTML, a code allowlist, independent
styles or hardcoded HF commits when registering an experimental assembly.
The directory reads the active version from `/api/collections`; registration,
summary updates and collection activation in D1 do not require a site rebuild.

Production experimental browser configurations, including legacy `.config.json` URLs and combined views, are generated from D1 at request time. With `BTED_D1_ONLY=on`, D1 asset registrations also provide the scientific-file allowlist. Updating consistent metadata or pinned-file registrations does not require rebuilding or redeploying the site. Standalone Pages builds retain generated configurations and a fixed manifest.

```sh
# Only for an approved data change:
npx wrangler d1 execute bted-catalog --remote --config worker/wrangler.jsonc --file database/changes/<operation>/apply.sql --yes
# Only when Worker code or static assets changed:
npx wrangler deploy --config worker/wrangler.jsonc
```

Record the previous Worker version and active D1 collection pointers first.
Production retains only online releases and real online dependencies, not backup
or rollback directory copies. Accept a replacement before switching, then delete
its superseded registrations within budget. D1 collection pointers and summaries
are authoritative; `collections.json` provides build defaults, not a runtime
assembly list. Refresh local registry documentation after a release. Bump
`BTED_COLLECTION_REVISION` for code/cache changes, not for every data registration.
Keep `BTED_D1_ONLY=on`
and `BTED_RUNTIME_FIELDS=on` in production. Scientific-file updates require a
separately verified HF commit, not a moving `main` URL.

After deployment, check `/api/health`, `/api/collections`, affected directories and configurations. Exercise filtering, header sorting, downloads, and rendered tracks or sequence controls affected by the change.

### Keep maintenance within the Free row allowance

D1 Free allows 5,000,000 rows read and 100,000 rows written per UTC day, not that
many queries. Reuse valid saved full-validation evidence and check changed rows
with indexed predicates. Record official `meta.rows_read/rows_written` for remote
maintenance. Do not repeat global foreign-key, integrity or FTS checks after an
unchanged or rejected operation. Stop on a quota error without more readback.

The active continuation is `_workspace/outputs/BTED-GTDB-update-2026-10-29/live-only-state.json`;
read its `STATUS.md` and `RUNBOOK.md` before remote maintenance. October 31 is at
`safe_budget_stop` after 1,450 fixed GTDB candidate genomes were imported, with
no pending/inflight operation. The active experimental directory is now
`202610310000000000000005`; its `storage_version` remains
`202610220000000000000006`, an actual online dependency. GEM remains on its
accepted CDS-recovery revision. Historical counters and older pointer assertions
are not current admission or recovery instructions.

The existing `bted-gtdb` continuation runs daily at 08:20 Asia/Shanghai and stops
after cleanup and GTDB acceptance. `next-day` grants one account-checked UTC-day
budget and cleans retired rows; `admit-import-day` performs the same admission
without cleanup, so the existing `import_gtdb_batches.py run` can use that budget.
Both reject a second same-day grant. Cleanup, import and validation share at most
500,000 reads / 50,000 writes, reduced for account-wide activity and website
headroom. Rolling statistics may lag; use the checkpoint and actual receipts.

Current collections and experimental `reference_registry_version` dependencies
remain protected. The old aggregate alias and API are retired, so its former
storage is no longer protected and is queued for deletion. Do not use an import
or another endpoint to circumvent quota denial. Partial progress is not completion.

## Recovery

For a data correction, historical `rollback.sql` requires every referenced row
and version to remain available. Live-only cleanup deliberately removes those
copies. Fix forward with current collection/cache bindings; do not restore a
Worker serving purged directories or retired sorts. Preserve online scientific
registrations and usage counts.

Keep schema, ordered migrations and small reviewed corrections in Git. Store run
receipts and source evidence in the Git-ignored `_workspace/` directory; do not create production
backup exports. The [current deployment record](releases/current.md) identifies
the active version and applicable recovery conditions.

Experimental prediction refreshes use the per-assembly prediction bindings and registered BED/GFF3/TBI revisions in D1. The generic extension reader includes this capability after migration 0014. Ordinary file/version and count updates do not require rebuilding the site or redeploying the Worker.
