import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { gzipSync } from "node:zlib";
import test from "node:test";

const source = readFileSync(new URL("../prototype/accession-range/src/worker.js", import.meta.url), "utf8");
const { default: worker, combineGenomeTracks } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
const catalogue = JSON.parse(readFileSync(new URL("../data/registry/batter-browser.json", import.meta.url)));
const id = "GCF_000006605.1", revision = catalogue.revision;
const nativeFetch = globalThis.fetch;

function environment({ empty = false, annotation = "matched" } = {}) {
  const files = {
    "reference.fa.gz": gzipSync(">chr1\nACGT\n"),
    "reference.fa.gz.fai": Buffer.from("chr1\t10000\t6\t60\t61\n"),
    "reference.fa.gz.gzi": Buffer.alloc(8),
    "augmentation.gff3.gz": Buffer.concat([gzipSync(empty ? "##gff-version 3\n" : "##gff-version 3\nchr1\tBATTER\ttraining_sequence_window\t8320\t8893\t.\t-\t.\tID=W\nchr1\tBATTER\taugmented_terminator_span\t8580\t8636\t.\t-\t.\tID=S\n"), gzipSync("")]),
    "augmentation.gff3.gz.tbi": Buffer.alloc(8),
    "genes.gff3.gz": gzipSync("##gff-version 3\n"), "genes.gff3.gz.tbi": Buffer.alloc(8),
    "prediction.gff3.gz": gzipSync("##gff-version 3\nchr1\tBATTER\tpredicted_terminator_region\t10\t30\t0.9\t+\t.\tID=P\n"), "prediction.gff3.gz.tbi": Buffer.alloc(8),
  };
  const metadata = { genome_id: id, batch: "000", otu_id: "OTU-44316", reference: { contigs: 1, bases: 10000 }, annotation: { status: annotation },
    feature_counts: { tes_prediction: 1, otu_augmentation_span: empty ? 0 : 1, otu_augmentation_window: empty ? 0 : 1, rfam_training_span: 0, rfam_training_window: 0 },
    files: Object.fromEntries(Object.entries(files).map(([name, bytes]) => [name, { bytes: bytes.length, sha256: createHash("sha256").update(bytes).digest("hex") }])) };
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    const file = String(url).split("/").at(-1);
    if (file === "metadata.json") return Response.json(metadata);
    const bytes = files[file];
    if (!bytes) return new Response("missing", { status: 404 });
    const range = new Headers(options.headers).get("range");
    if (range) return new Response(bytes.subarray(0, 6), { status: 206, headers: { "content-length": "6", "content-range": `bytes 0-5/${bytes.length}` } });
    return new Response(bytes, { headers: { "content-length": String(bytes.length) } });
  };
  return { calls, metadata, ASSETS: { fetch: async request => request.url.endsWith("genome-browsers.json") ? Response.json({ revision, experimental: {}, overlays: {} }) : Response.json(catalogue) } };
}
const request = path => new Request("https://bted.example/api/batter/" + path);

test("indexed augmentation uses its own bgzip reference, opens the first window, and retains native tracks", async () => {
  const env = environment();
  try {
    const response = await worker.fetch(request(id + "/config"), env);
    assert.equal(response.status, 200);
    const config = await response.json();
    assert.equal(config.assemblies[0].sequence.adapter.type, "BgzipFastaAdapter");
    assert.ok(config.assemblies[0].sequence.adapter.gziLocation.uri.includes(revision));
    assert.equal(config.defaultSession.views[0].offsetPx, 8119);
    assert.equal(config.defaultSession.views[0].tracks[0].type, "ReferenceSequenceTrack");
    assert.equal(config.defaultSession.views[0].tracks[0].displays[0].showTranslation, true);
    assert.deepEqual(config.tracks.map(track => track.trackId), ["batter_genes", "batter_augmentation", "batter_prediction"]);
    assert.equal(config.tracks[2].metadata.btedAbout.evidence, "Model prediction");
    assert.equal(config.tracks[1].adapter.type, "Gff3TabixAdapter");
    assert.equal(config.tracks[1].metadata.btedAbout.evidence, "Computational training augmentation");
  } finally { globalThis.fetch = nativeFetch; }
});

test("empty augmentation and unmatched annotation do not create misleading tracks", async () => {
  const env = environment({ empty: true, annotation: "contig_mismatch" });
  try {
    const response = await worker.fetch(request(id + "/config"), env);
    assert.equal(response.status, 200);
    const config = await response.json();
    assert.deepEqual(config.tracks.map(track => track.trackId), ["batter_prediction"]);
    assert.equal(config.defaultSession.views[0].offsetPx, 0);
    assert.ok(!env.calls.some(call => call.url.endsWith("augmentation.gff3.gz")));
  } finally { globalThis.fetch = nativeFetch; }
});

test("same-genome tracks merge using verified sequence aliases; mismatched references remain separate views", () => {
  const metadata = { genome_id: id, files: { "reference.fa.gz": { sha256: "a".repeat(64) } } };
  const base = () => ({ assemblies: [{ name: id }], tracks: [{ trackId: "batter_augmentation", metadata: {} }], defaultSession: { views: [{ id: "batter_view", tracks: [] }] }, metadata: {} });
  const experimental = { assemblies: [{ name: "experimental_ref", sequence: { adapter: { fastaLocation: { uri: "https://example.org/reference.fa" } } } }],
    tracks: [{ trackId: "experimental_endpoints", assemblyNames: ["experimental_ref"], metadata: {} }], defaultSession: { views: [{ id: "experimental_view", tracks: [{ configuration: "experimental_endpoints" }] }] } };
  const verified = { compatible: true, batter_reference_sha256: "a".repeat(64), experimental_reference_url: "https://example.org/reference.fa", aliases: { BA000030: "NC_003155" } };
  const merged = combineGenomeTracks(base(), experimental, verified, metadata);
  assert.equal(merged.assemblies.length, 1);
  assert.equal(merged.defaultSession.views.length, 1);
  assert.deepEqual(merged.tracks[1].assemblyNames, [id]);
  assert.equal(merged.defaultSession.views[0].tracks[0].configuration, "experimental_endpoints");
  assert.equal(decodeURIComponent(merged.assemblies[0].refNameAliases.adapter.location.uri), "data:text/plain,NC_003155\tBA000030\n");
  const separated = combineGenomeTracks(base(), experimental, { ...verified, batter_reference_sha256: "b".repeat(64) }, metadata);
  assert.equal(separated.assemblies.length, 2);
  assert.equal(separated.defaultSession.views.length, 2);
  assert.equal(separated.metadata.combined_reference_status, "separate_views");
  assert.deepEqual(separated.tracks[1].assemblyNames, ["experimental_ref"]);
});

test("file proxy preserves ranges and rejects unknown IDs, arbitrary files and revision mixing", async () => {
  const env = environment();
  try {
    assert.equal((await worker.fetch(request("unknown/config"), env)).status, 404);
    assert.equal(env.calls.length, 0);
    assert.equal((await worker.fetch(request(id + "/files/secret.txt"), env)).status, 404);
    assert.equal((await worker.fetch(request(id + "/config?revision=" + "a".repeat(40)), env)).status, 409);
    assert.equal((await worker.fetch(request(id + "?url=https://example.org"), env)).status, 400);
    const response = await worker.fetch(new Request(request(id + "/files/reference.fa.gz?revision=" + revision), { headers: { Range: "bytes=0-5" } }), env);
    assert.equal(response.status, 206);
    assert.equal(response.headers.get("x-bted-sha256"), env.metadata.files["reference.fa.gz"].sha256);
    assert.equal(response.headers.get("x-bted-revision"), revision);
    assert.equal((await response.arrayBuffer()).byteLength, 6);
    env.metadata.files["reference.fa.gz.fai"].sha256 = "b".repeat(64);
    assert.equal((await worker.fetch(request(id + "/config"), env)).status, 503);
  } finally { globalThis.fetch = nativeFetch; }
});

test("augmentation fallback requires matching pinned metadata, preserving Range and cancellation", async () => {
  globalThis.location = { origin: "https://bted.example", href: "blob:https://bted.example/adapter" };
  const url = `https://huggingface.co/datasets/liurulong/terminator/resolve/${revision}/v0.5.0/batter/batches/000/genomes/${id}/reference.fa.gz`;
  const backup = `/api/batter/${id}/files/reference.fa.gz?revision=${revision}`;
  const calls = []; let failure = false;
  globalThis.fetch = async (input, options = {}) => {
    const req = new Request(input, options); calls.push(req); req.signal.throwIfAborted();
    if (req.url.startsWith("https://huggingface.co/")) {
      if (failure) throw new TypeError("Failed to fetch");
      return new Response("direct");
    }
    if (!req.url.includes("/files/")) return Response.json({ revision, batch: "000", browser_files: { "reference.fa.gz": { url, fallback_url: backup, sha256: "b".repeat(64) } } });
    return new Response("backup", { headers: { "x-bted-sha256": "b".repeat(64), "x-bted-revision": revision } });
  };
  try {
    const pluginSource = readFileSync(new URL("../jbrowse-plugin/src/plugin.js", import.meta.url), "utf8");
    const plugin = await import(`data:text/javascript;base64,${Buffer.from(pluginSource).toString("base64")}`);
    assert.equal(await (await plugin.fetchBtedAsset(url)).text(), "direct");
    assert.equal(calls.length, 1);
    failure = true;
    assert.equal(await (await plugin.fetchBtedAsset(url, { headers: { Range: "bytes=0-5" } })).text(), "backup");
    assert.equal(calls.at(-1).headers.get("range"), "bytes=0-5");
    const controller = new AbortController(); controller.abort();
    await assert.rejects(plugin.fetchBtedAsset(url, { signal: controller.signal }), { name: "AbortError" });
    const feature = (type, dataset) => ({ get: key => key === "type" ? type : { dataset_class: [dataset] } });
    assert.equal(plugin.augmentationColor(feature("training_sequence_window", "otu_augmentation_window")), "#bfdbfe");
    assert.equal(plugin.augmentationColor(feature("augmented_terminator_span", "otu_augmentation_span")), "#1d4ed8");
    assert.equal(plugin.augmentationColor(feature("rfam_training_span", "rfam_training_span")), "#7c3aed");
  } finally { globalThis.fetch = nativeFetch; }
});
