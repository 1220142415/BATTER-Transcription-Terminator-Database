import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../prototype/accession-range/src/worker.js", import.meta.url), "utf8");
const { default: worker, experimentalSampleTracks, addExperimentalSamples, verifiedExperimentalSample } = await import(
  `data:text/javascript;base64,${Buffer.from(source + "\nexport { experimentalSampleTracks, addExperimentalSamples, verifiedExperimentalSample }; ").toString("base64")}`);
const request = new Request("https://bted.example/jbrowse/assemblies/GCF_000005845.1.config.json");
const root = "v0.5.0/genomes/experimental-only/GCF_000005845.1/studies/PMID_29606352/sources/BATTER_S1_001/samples/GSM2500131";
function sample(strands = ["plus", "minus"]) {
  return { path: root, metadata_path: `${root}/metadata.json`, metadata_sha256: "c".repeat(64),
    genome_id: "GCF_000005845.1", group: "experimental-only", pmid: "29606352", source_id: "BATTER_S1_001",
    sample_id: "GSM2500131", revision: "a".repeat(40), reference_contigs: { "NC_000913.2": 4639675 },
    verification: { status: "complete", sha256: true, http_range: true, cors: true, reference_names_and_lengths: true },
    signals: strands.map(strand => ({ strand, path: `${root}/signal.${strand}.bw`, byte_size: 4096, sha256: "b".repeat(64) })) };
}
function config() {
  return { assemblies: [{ name: "ecoli" }], tracks: [
    { type: "FeatureTrack", trackId: "ends", metadata: { source_id: "BATTER_S1_001", btedAbout: { kind: "endpoint", pmid: "29606352" } } },
    { type: "MultiQuantitativeTrack", trackId: "legacy", metadata: { source_id: "BATTER_S1_001", btedAbout: { kind: "signal" } } },
  ], defaultSession: { views: [{ type: "LinearGenomeView", displayedRegions: [{ refName: "NC_000913.2", start: 0, end: 4639675, assemblyName: "ecoli" }],
    tracks: [{ configuration: "ends" }, { configuration: "legacy" }] }] } };
}
const catalogue = samples => ({ schema: "bted-experimental-signals-v1", release_version: "v0.5.0", samples });

test("verified samples become default mirror tracks while legacy definitions remain available", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => Response.json(catalogue([sample()]));
  try {
    const result = await addExperimentalSamples(config(), "GCF_000005845.1", request, { ASSETS: {} });
    const track = result.tracks.find(track => track.metadata?.sample_id);
    assert.equal(track.type, "MultiQuantitativeTrack");
    assert.deepEqual(track.adapter.subadapters.map(a => a.source), ["plus", "minus"]);
    assert.equal(track.metadata.btedMirroredSignal, true);
    assert.deepEqual(track.assemblyNames, ["ecoli"]);
    assert.ok(track.adapter.subadapters[0].bigWigLocation.uri.includes(`/api/experimental-signals/files?revision=${"a".repeat(40)}`));
    const defaults = result.defaultSession.views[0].tracks.map(t => t.configuration);
    assert.deepEqual(defaults, ["ends", track.trackId]);
    assert.ok(result.tracks.some(t => t.trackId === "legacy"));
    await addExperimentalSamples(result, "GCF_000005845.1", request, { ASSETS: {} });
    assert.equal(result.tracks.filter(t => t.metadata?.sample_id).length, 1);
  } finally { globalThis.fetch = originalFetch; }
});

test("single strand and unstranded samples load without inventing a second signal", () => {
  for (const strand of ["plus", "minus", "unstranded"]) {
    const [track] = experimentalSampleTracks(config(), "GCF_000005845.1", catalogue([sample([strand])]), request);
    assert.ok(track);
    if (strand === "unstranded") {
      assert.equal(track.type, "QuantitativeTrack");
      assert.equal(track.displays[0].type, "LinearWiggleDisplay");
      assert.equal(track.metadata.btedMirroredSignal, false);
    } else assert.deepEqual(track.adapter.subadapters.map(a => a.source), [strand]);
  }
});

test("unverified, wrong study, wrong reference, and other genome files never become default tracks", () => {
  for (const alter of [s => { delete s.verification; }, s => { s.verification.cors = false; },
    s => { s.verification.sha256 = "true"; },
    s => { s.reference_contigs = { "NC_000913.2": 4641652 }; }, s => { s.reference_contigs = { "NC_000913.3": 4639675 }; },
    s => { s.source_id = "OTHER"; }, s => { s.genome_id = "OTHER"; }, s => { s.pmid = "99999"; }]) {
    const row = sample(); alter(row);
    assert.deepEqual(experimentalSampleTracks(config(), "GCF_000005845.1", catalogue([row]), request), []);
  }
  const row = sample(); row.signals[0].path = "../../other.bw";
  assert.equal(verifiedExperimentalSample(row), false);
});

test("static genome configs receive defaults automatically, without user JSON imports", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => Response.json(catalogue([sample()]));
  try {
    const env = { ASSETS: { fetch: async () => Response.json(config()) } };
    const response = await worker.fetch(request, env, {});
    assert.equal(response.status, 200);
    assert.equal((await response.json()).metadata.experimental_signal_samples[0], "GSM2500131");
  } finally { globalThis.fetch = originalFetch; }
});

test("HF failures preserve the genome browser and can use a verified local catalogue snapshot", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => { throw new Error("offline"); };
  try {
    const baseline = config();
    const missing = { ASSETS: { fetch: async () => new Response("missing", { status: 404 }) } };
    assert.deepEqual(await addExperimentalSamples(baseline, "GCF_000005845.1", request, missing), baseline);
    const snapshot = { ASSETS: { fetch: async () => Response.json(catalogue([sample()])) } };
    const result = await addExperimentalSamples(config(), "GCF_000005845.1", request, snapshot);
    assert.equal(result.metadata.experimental_signal_samples[0], "GSM2500131");
  } finally { globalThis.fetch = originalFetch; }
});

test("the signal proxy rejects arbitrary paths and URLs", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => Response.json(catalogue([sample()]));
  try {
    const env = { ASSETS: {} };
    assert.equal((await worker.fetch(new Request("https://bted.example/api/experimental-signals/files?url=https://example.org/file"), env, {})).status, 400);
    assert.equal((await worker.fetch(new Request("https://bted.example/api/experimental-signals/files?revision=" + "a".repeat(40) + "&path=other.bw"), env, {})).status, 404);
  } finally { globalThis.fetch = originalFetch; }
});

test("loopback preview reads the live catalogue and validated byte ranges through its gateway", async () => {
  const originalFetch = globalThis.fetch;
  const upstreams = [];
  globalThis.fetch = async (url, options) => {
    upstreams.push(String(url));
    if (String(url).endsWith("experimental_signals.json")) return Response.json(catalogue([sample()]));
    assert.equal(options.headers.get("range"), "bytes=0-63");
    return new Response(new Uint8Array(64), { status: 206, headers: { "content-length": "64", "content-range": "bytes 0-63/4096" } });
  };
  try {
    const env = { ASSETS: {}, HF_PREVIEW_GATEWAY: "http://127.0.0.1:8789/" };
    const url = `http://127.0.0.1:8787/api/experimental-signals/files?revision=${"a".repeat(40)}&path=${encodeURIComponent(root + "/signal.plus.bw")}`;
    const response = await worker.fetch(new Request(url, { headers: { range: "bytes=0-63" } }), env, {});
    assert.equal(response.status, 206);
    assert.equal(response.headers.get("content-range"), "bytes 0-63/4096");
    assert.equal(response.headers.get("x-bted-hf-revision"), "a".repeat(40));
    assert.equal((await response.arrayBuffer()).byteLength, 64);
    assert.equal(upstreams.length, 2);
    assert.ok(upstreams.every(url => url.startsWith("http://127.0.0.1:8789/datasets/liurulong/terminator/resolve/")));
    upstreams.length = 0;
    const publicEnv = { ASSETS: { fetch: async () => new Response("missing", { status: 404 }) }, HF_PREVIEW_GATEWAY: env.HF_PREVIEW_GATEWAY };
    const publicResponse = await worker.fetch(new Request(url.replace("http://127.0.0.1:8787", "https://bted.example")), publicEnv, {});
    assert.equal(publicResponse.status, 503);
    assert.equal(upstreams.length, 0);
  } finally { globalThis.fetch = originalFetch; }
});
