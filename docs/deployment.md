# Build and deploy

Production runs on [Cloudflare Workers](https://bted.1052596411.workers.dev/). Run commands from the repository root. The configuration is `worker/wrangler.jsonc`; generated assets are under `dist/worker-site/`. GitHub CI runs validation. The Pages workflow is an optional manual mirror, not the production deployment.

## Fixed inputs

| Input | Version |
|---|---|
| Public experimental files | `data/public/v0.4.0/` at Git commit `8132334474a70cc609261fb0dc05011fbfd9e8ef` |
| v0.4 scientific assets | HF `eea5b7225975b224a1c837f60c4fa10497fef022` |
| Earlier references and signals | HF `90651318aedf5a5ca26b8308070927d36fd3d6c9`, bound per file |
| GEM computational references | HF `9f81698a3cee64f4eaf90b90cd36d640f38d9315` |
| Recovered gene annotations | HF `2acf28d9cf0a276f05e6a1456d56c92ccc2292b7` |
| GTDB directory | Snapshot `deffa4a7183f71a8b47b3c44`, commit `7ed77270f02862da5722dad1d7836e3444e67dfd`; scientific files use their registered per-genome revisions |
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
npx wrangler deploy --dry-run --config worker/wrangler.jsonc --outdir ../dist/worker-dry-run
```

Use `npx wrangler dev --config worker/wrangler.jsonc` for a Worker preview with a reviewed local D1 import. `serve_v04_preview.py` checks static assets and layout; it does not substitute for D1 API acceptance.

## Apply data changes and deploy

Code-only changes do not require a D1 import. For data changes, follow the [database guide](../database/README.md) and execute only the reviewed operation. Never replay all migrations as a deployment step.

```sh
# Only for an approved data change:
npx wrangler d1 execute bted-catalog --remote --config worker/wrangler.jsonc --file database/changes/<operation>/apply.sql --yes
# After checking the active D1 version:
npx wrangler deploy --config worker/wrangler.jsonc
```

Record the previous Worker version, D1 collection pointers and recovery bookmark first. Directory changes require matching `collections.json` and `BTED_COLLECTION_REVISION` values. Keep `BTED_D1_ONLY=on` and `BTED_RUNTIME_FIELDS=on` in production. Scientific-file updates require a separately verified HF commit, not a moving `main` URL.

After deployment, check `/api/health`, `/api/collections`, affected directories and configurations. Exercise filtering, header sorting, downloads, and rendered tracks or sequence controls affected by the change.

## Recovery

For a data correction, apply its `rollback.sql` while its preconditions still hold, then restore the corresponding Worker. Restore local collection/cache bindings before the next deployment. For code-only changes, roll back the Worker. Preserve scientific tables and usage counts.

Keep schema, ordered migrations and small reviewed corrections in Git. Store production exports, raw evidence and run logs outside the repository. The [current deployment record](releases/current.md) identifies the active version and recovery commands.
