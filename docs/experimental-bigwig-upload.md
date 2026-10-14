# Experimental BigWig uploads

Upload experimental signal to the existing dataset `liurulong/terminator`.
The destination follows the current genome-first directory:

```text
v0.5.0/genomes/<group>/<genome_id>/studies/PMID_<pmid>/sources/<source_id>/samples/<sample_id>/
  signal.plus.bw
  signal.minus.bw
  metadata.json
  SHA256SUMS.txt
```

For GSM2500131 this is
`v0.5.0/genomes/experimental-only/GCF_000005845.1/studies/PMID_29606352/sources/BATTER_S1_001/samples/GSM2500131/`.
The explicit manifest matches the genome, paper, registered source, GEO series,
sample, and strand. New conditions or replicates use distinct sample IDs.
For non-GEO data, use a stable source-specific sample ID and omit the series
accession. Do not infer the reference or biological strand from an arbitrary filename.

## Prepare and upload

1. Copy `data/registry/templates/experimental_bigwig_intake.json` to a local
   manifest. Set the paths to your converted BigWigs and the registered IDs.
   The group must match the genome's existing HF `metadata.json`.
2. Authenticate using the existing `liurulong` account with `hf auth login`.
3. Prepare and inspect the upload plan (reads HF, does not upload):

```bash
python scripts/publish_experimental_bigwigs.py \
  --manifest /absolute/path/to/intake.json \
  --output /absolute/path/to/fresh-preparation-directory
```

4. Publish using a new output directory:

```bash
python scripts/publish_experimental_bigwigs.py \
  --manifest /absolute/path/to/intake.json \
  --output /absolute/path/to/fresh-upload-directory \
  --publish
```

Requires `huggingface_hub` (`python -m pip install huggingface_hub`). Proxy
configuration, when needed, belongs to the invoking command/session.
Only paths in the manifest and the additive signal catalogue are committed.
Existing sample files with differing bytes are rejected. Commit creation checks
the parent revision. An ambiguous timeout triggers an exact-path comparison
before any retry. The final receipt records a fixed HF revision, streamed SHA-256,
BigWig HTTP Range and CORS checks, and preservation of existing source files.
If post-upload verification fails, consult `upload-receipt.json`; a completed
upload must not be inferred solely from the commit request.

## One BigWig

`signals` may contain only one entry. Set `strand` to `plus` or `minus` only
when its biological strand is known; otherwise set it to `unstranded`.
An unstranded signal is stored as `signal.unstranded.bw`. An absent strand is
not fabricated. Keep separate strand signals nonnegative for BTED's mirror renderer.

## Reference and provenance

All chromosome names and lengths must match the exact reference FASTA index
in that genome's HF directory. `chrom_aliases` is an explicit name mapping,
not a coordinate conversion. The uploader permits aliases with the same byte
length and edits only the chromosome B+ tree keys, leaving signal and index
blocks intact. Regenerate the BigWig from WIG for other renames or reference
changes. For GSM2500131, `NC_000913_2` maps to `NC_000913.2` (4,639,675 bp).
The source file's name/hash, aliases, resulting hash and raw summary are retained.

The optional `expected_source_sha256` on a signal entry checks a recorded server
hash before publication; `source_url` retains its public data source.

## Additive catalogue and website integration

`v0.5.0/catalogues/experimental_signals.json` indexes uploaded samples and signal
paths with sizes and hashes. It supplements the original pinned release; it
does not rewrite `release.json`, `SHA256SUMS.txt`, or historical completion proofs.
Legacy source-level `signal.plus.bw`/`signal.minus.bw` remain intact.

The uploader first commits and verifies sample payloads, then enrolls them in
the catalogue with their fixed payload revision, reference contigs, and actual
SHA-256/Range/CORS verification results. Failed verification does not enroll a
sample for automatic loading.

The Worker reads the latest catalogue (60-second cache) when serving static or
API-generated experimental JBrowse configs. It matches the genome, registered
source, PMID and reference before adding sample signal tracks to the default
session. Strand-separated samples use BTED's mirror renderer, including a
single known strand. Unstranded samples use a regular quantitative display.
Legacy source signal definitions remain available in the track selector; the
sample tracks take their place in the default view for that source.
Explicit shared-view/session track choices still control the user's view.

BigWigs are served through an exact-path, fixed-revision signal proxy; arbitrary
upstream URLs are rejected. Future successful uploads using this script appear
without a new data release or website redeploy once this Worker code is running.
For an offline local preview, copy the uploader's final `experimental-signals.json`
to the staged site's `assets/experimental-signals.json`; only verified snapshots
are accepted. The original release proof and assets stay pinned.

When a local preview cannot reach HF directly, the existing `HF_PREVIEW_GATEWAY`
setting also applies to the live signal catalogue and sample files. Both the
request and gateway must use loopback hosts; the gateway must explicitly allow
the catalogue and its registered fixed-revision files. This option cannot route
public website requests through a local gateway. A frozen offline snapshot only
contains samples registered when the snapshot was copied.
