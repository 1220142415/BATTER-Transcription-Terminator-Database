import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { gzipSync } from "node:zlib";
import test from "node:test";

const source = readFileSync(new URL("../prototype/accession-range/src/worker.js", import.meta.url), "utf8");
const { default: worker, combineGenomeTracks, tabixContigCounts, augmentationContigCounts, applyRecoveredAnnotation } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
const catalogue = JSON.parse(readFileSync(new URL("../data/registry/batter-browser.json", import.meta.url)));
const id = "GCF_000006605.1", revision = catalogue.revision;
const nativeFetch = globalThis.fetch;

function tabixIndex(counts) {
  const names = Buffer.from(Object.keys(counts).join("\0") + "\0");
  const header = Buffer.alloc(36);
  header.write("TBI\x01"); header.writeUInt32LE(Object.keys(counts).length, 4);
  header.writeUInt32LE(names.length, 32);
  return Buffer.concat([header, names, ...Object.values(counts).map(count => {
    const ref = Buffer.alloc(48);
    ref.writeUInt32LE(1, 0); ref.writeUInt32LE(37450, 4); ref.writeUInt32LE(2, 8);
    ref.writeBigUInt64LE(BigInt(count), 28);
    return ref;
  }), Buffer.alloc(8)]);
}

function environment({ empty = false, annotation = "matched", indexStats = true, d1 = true } = {}) {
  const files = {
    "reference.fa.gz": gzipSync(">chr1\nACGT\n"),
    "reference.fa.gz.fai": Buffer.from("chr1\t10000\t6\t60\t61\n"),
    "reference.fa.gz.gzi": Buffer.alloc(8),
    "augmentation.gff3.gz": Buffer.concat([gzipSync(empty ? "##gff-version 3\n" : "##gff-version 3\nchr1\tBATTER\ttraining_sequence_window\t8320\t8893\t.\t-\t.\tID=W;dataset_class=otu_augmentation_window\nchr1\tBATTER\taugmented_terminator_span\t8580\t8636\t.\t-\t.\tID=S\n"), gzipSync("")]),
    "augmentation.gff3.gz.tbi": Buffer.alloc(8),
    "genes.gff3.gz": gzipSync("##gff-version 3\n"), "genes.gff3.gz.tbi": Buffer.alloc(8),
    "prediction.gff3.gz": gzipSync("##gff-version 3\nchr1\tBATTER\tpredicted_terminator_region\t10\t30\t0.9\t+\t.\tID=P\n"), "prediction.gff3.gz.tbi": indexStats ? gzipSync(tabixIndex({ chr1: 1 })) : Buffer.alloc(8),
  };
  const metadata = { genome_id: id, batch: "000", otu_id: "OTU-44316", reference: { contigs: 1, bases: 10000 }, annotation: { status: annotation },
    feature_counts: { tes_prediction: 1, otu_augmentation_span: empty ? 0 : 1, otu_augmentation_window: empty ? 0 : 1, rfam_training_span: 0, rfam_training_window: 0 },
    files: Object.fromEntries(Object.entries(files).map(([name, bytes]) => [name, { bytes: bytes.length, sha256: createHash("sha256").update(bytes).digest("hex") }])) };
  const wrapper = { genome_id: id, group: "batter-000", has_prediction: true, records: { batter: metadata } };
  const fixtureCatalogue = { revision, layout: "genome-first", genomes: [[id, "000", "OTU-44316", id, "isolate", empty ? 0 : 1, empty ? 0 : 1, 0, 0, annotation, 1]] };
  const base = `https://huggingface.co/datasets/liurulong/terminator/resolve/${revision}/v0.5.0/genomes/batter-000/${id}/`;
  const paths = Object.fromEntries(Object.entries(files).map(([file, bytes]) => [base + (file.startsWith("reference") ? "reference/" : file.startsWith("augmentation") ? "training/" : file.startsWith("prediction") ? "predictions/" : "annotations/batter/") + file, bytes]));
  const calls = [], d1Queries = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    if (String(url) === base + "metadata.json") {
      assert.equal(d1, false, "D1 metadata must not read HF metadata");
      return Response.json(wrapper);
    }
    const bytes = paths[String(url)];
    if (!bytes) return new Response("missing", { status: 404 });
    const range = new Headers(options.headers).get("range");
    if (range) return new Response(bytes.subarray(0, 6), { status: 206, headers: { "content-length": "6", "content-range": `bytes 0-5/${bytes.length}` } });
    return new Response(bytes, { headers: { "content-length": String(bytes.length) } });
  };
  return { calls, d1Queries, metadata, wrapper, ...(d1 ? { BTED_METADATA_REVISION: revision, BTED_DB: {
    prepare(sql) { return { bind(...values) { return {
      async first() {
        d1Queries.push({ sql, values });
        if (sql.includes("hf_metadata_releases")) return values[0] === revision ? { revision, catalogue_header_json: JSON.stringify({ revision, layout: "genome-first" }) } : null;
        if (sql.includes("hf_genome_metadata")) return values[0] === revision && values[1] === id ? {
          catalogue_row_json: JSON.stringify(fixtureCatalogue.genomes[0]), metadata_json: JSON.stringify(wrapper), genome_id: id,
        } : null;
        throw new Error("Unexpected SQL: " + sql);
      },
      async all() {
        d1Queries.push({ sql, values });
        assert.ok(sql.includes("hf_catalogue_pages"));
        return { results: [{ rows_json: JSON.stringify(fixtureCatalogue.genomes) }] };
      },
    }; } }; },
  } } : {}), ASSETS: { fetch: async request => request.url.endsWith("genome-browsers.json") ? Response.json({ revision, experimental: {}, overlays: {} }) : Response.json(fixtureCatalogue) } };
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
    assert.equal(config.tracks[2].displays[0].renderer.mouseover, "jexl:btedPredictionTooltip(feature)");
    assert.equal(config.tracks[2].displays[0].renderer.height, 14);
    assert.equal(config.tracks[2].metadata.btedAbout.explanation, "BATTER predictions with interval coordinates.");
    assert.equal(config.tracks[1].adapter.type, "Gff3TabixAdapter");
    assert.equal(config.tracks[1].metadata.btedAbout.evidence, "OTU data augmentation and Rfam-derived training regions");
    assert.equal(config.tracks[1].name, "Augmentation / Rfam regions");
    assert.deepEqual(config.tracks[1].metadata.btedContigCounts, { chr1: 1 });
    assert.deepEqual(config.tracks[1].metadata.btedContigBreakdown, { chr1: { otu: 1, rfam: 0 } });
    assert.deepEqual(config.tracks[2].metadata.btedContigCounts, { chr1: 1 });
    assert.equal(config.tracks[0].metadata.btedAbout.record_count, undefined);
    assert.ok(!env.calls.some(call => call.url.endsWith("prediction.gff3.gz")));
    assert.deepEqual(config.tracks[1].displays[0].jexlFilters, ["get(feature,'type')!='training_sequence_window' && get(feature,'type')!='rfam_training_window'"]);
    assert.deepEqual(config.tracks[0].displays[0].jexlFilters, ["get(feature,'type')!='region'"]);
    assert.equal(config.tracks[0].displays[0].renderer.showDescriptions, false);
  } finally { globalThis.fetch = nativeFetch; }
});

test("computational counts distinguish contigs, exclude context windows, and reject unverified totals", () => {
  const contigs = new Map([["chr1", 10000], ["chr2", 10000], ["empty", 10000]]);
  const index = tabixIndex({ chr1: 7, chr2: 2 });
  assert.deepEqual(tabixContigCounts(index, contigs, 9), { chr1: 7, chr2: 2, empty: 0 });
  assert.equal(tabixContigCounts(index, contigs, 8), null);
  assert.equal(tabixContigCounts(index.subarray(0, 60), contigs, 9), null);
  assert.equal(tabixContigCounts(index, new Map([["chr1", 10000]]), 9), null);
  const noStats = Buffer.from(index); noStats.writeUInt32LE(1, 4 + 36 + Buffer.byteLength("chr1\0chr2\0"));
  assert.equal(tabixContigCounts(noStats, contigs, 9), null);
  const text = "##gff-version 3\n" + [
    "chr1\tBATTER\taugmented_terminator_span\t10\t30\t.\t+\t.\tID=A",
    "chr1\tBATTER\trfam_training_span\t15\t25\t.\t-\t.\tID=R",
    "chr2\tBATTER\taugmented_terminator_span\t20\t40\t.\t-\t.\tID=B",
    "chr1\tBATTER\ttraining_sequence_window\t1\t60\t.\t+\t.\tdataset_class=otu_augmentation_window",
    "chr1\tBATTER\trfam_training_window\t1\t60\t.\t-\t.\tdataset_class=rfam_training_window",
  ].join("\n");
  const expected = { otu_augmentation_span: 2, rfam_training_span: 1, otu_augmentation_window: 1, rfam_training_window: 1 };
  assert.deepEqual(augmentationContigCounts(text, contigs, expected), {
    counts: { chr1: 2, chr2: 1, empty: 0 }, breakdown: { chr1: { otu: 1, rfam: 1 }, chr2: { otu: 1, rfam: 0 }, empty: { otu: 0, rfam: 0 } },
  });
  assert.equal(augmentationContigCounts(text, contigs, { ...expected, otu_augmentation_span: 3 }), null);
  assert.equal(augmentationContigCounts(text.replace("\t10\t30", "\t0\t30"), contigs, expected), null);
});

test("missing prediction index statistics do not prevent loading tracks or masquerade as zero", async () => {
  const env = environment({ indexStats: false });
  try {
    const response = await worker.fetch(request(id + "/config"), env);
    assert.equal(response.status, 200);
    const config = await response.json();
    assert.equal(config.tracks.find(track => track.trackId === "batter_prediction").metadata.btedContigCounts, null);
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

test("published annotation supplement verifies reference identity, preserves provenance and creates one native track", async () => {
  const env = environment({ empty: true, annotation: "mismatch" });
  const annotationRevision = 'a'.repeat(40);
  const gff = Buffer.from('##gff-version 3\nchr1\tNCBI\tgene\t1\t4\t.\t+\t.\tID=G\n');
  const file = { bytes: gff.length,
    sha256: createHash('sha256').update(gff).digest('hex') };
  const entry = { reference_sha256: env.metadata.files['reference.fa.gz'].sha256, coverage: 'full',
    matched_reference_contigs: 1, total_reference_contigs: 1, features: 1,
    source_url: 'https://ftp.ncbi.nlm.nih.gov/example.gff.gz', source_annotation_type: 'published_NCBI_GFF3', file };
  const recovery = { path_prefix: 'v0.5.0/genomes', reference_revision: revision, annotation_revision: annotationRevision, genomes: { [id]: entry } };
  env.BTED_ANNOTATION_REVISION = annotationRevision;
  const originalAssetsFetch = env.ASSETS.fetch;
  env.ASSETS.fetch = async request => request.url.endsWith('genome-browsers.json')
    ? Response.json({ revision, experimental: {}, overlays: {}, annotation_recovery: recovery }) : originalAssetsFetch(request);
  const fixtureFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => String(url).includes(annotationRevision) && String(url).endsWith('/genes.gff3')
    ? new Response(gff) : fixtureFetch(url, options);
  try {
    const response = await worker.fetch(request(id + '/config'), env);
    assert.equal(response.status, 200);
    const config = await response.json();
    const tracks = config.tracks.filter(track => track.trackId === 'batter_genes');
    assert.equal(tracks.length, 1);
    assert.equal(tracks[0].adapter.type, 'Gff3Adapter');
    assert.ok(tracks[0].adapter.gffLocation.uri.includes(annotationRevision));
    assert.match(tracks[0].metadata.btedAbout.reference, /1\/1 contigs/);
    assert.equal(env.wrapper.records.batter.annotation.status, 'mismatch');
    const metadata = await (await worker.fetch(request(id), env)).json();
    assert.equal(metadata.annotation.status, 'matched');
    assert.equal(metadata.annotation.original_status, 'mismatch');
    assert.equal(metadata.annotation.annotation_revision, annotationRevision);
    assert.ok(metadata.browser_files['genes.gff3'].fallback_url.includes(revision));
    const annotationFile = await worker.fetch(request(id + '/files/genes.gff3'), env);
    assert.equal(annotationFile.status, 200);
    assert.equal(await annotationFile.text(), gff.toString());
    const catalogueResponse = await worker.fetch(new Request('https://bted.example/api/batter-catalogue'), env);
    assert.deepEqual((await catalogueResponse.json()).annotation_recovery, recovery);
    const callsBefore = env.d1Queries.length;
    const extraMetadata = structuredClone(metadata); extraMetadata.annotation.status = 'mismatch';
    const partial = structuredClone(recovery); partial.genomes[id].coverage = 'partial';
    extraMetadata.reference.contigs = 2; partial.genomes[id].total_reference_contigs = 2;
    applyRecoveredAnnotation(extraMetadata, partial);
    assert.equal(extraMetadata.annotation.coverage, 'partial');
    assert.equal(env.d1Queries.length, callsBefore);
    assert.throws(() => applyRecoveredAnnotation({ ...metadata, revision: 'b'.repeat(40) }, recovery), /revision_mismatch/);
    const invalid = structuredClone(recovery); invalid.genomes[id].reference_sha256 = 'f'.repeat(64);
    assert.throws(() => applyRecoveredAnnotation(metadata, invalid), /reference_mismatch/);
    invalid.genomes[id] = { ...entry, file: { ...file, path: '../unregistered.gff3' } };
    assert.throws(() => applyRecoveredAnnotation(metadata, invalid), /reference_mismatch/);
  } finally { globalThis.fetch = nativeFetch; }
});

test("genome-first metadata keeps the API contract and maps all four file directories", async () => {
  let env = environment();
  try {
    const response = await worker.fetch(request(id), env);
    assert.equal(response.status, 200);
    const data = await response.json();
    assert.equal(data.genome_id, id);
    assert.equal(data.feature_counts.tes_prediction, 1);
    assert.equal(data.records, undefined);
    for (const [file, folder] of [["reference.fa.gz", "reference"], ["prediction.gff3.gz", "predictions"], ["augmentation.gff3.gz", "training"], ["genes.gff3.gz", "annotations/batter"]]) {
      assert.equal(data.browser_files[file].url, `https://huggingface.co/datasets/liurulong/terminator/resolve/${revision}/v0.5.0/genomes/batter-000/${id}/${folder}/${file}`);
    }
    assert.equal(env.calls.length, 0); // D1 metadata requires no HF requests.
    assert.equal(response.headers.get("x-bted-metadata-source"), "d1");
    env = environment(); env.wrapper.group = "batter-042";
    assert.equal((await worker.fetch(request(id), env)).status, 503);
    env = environment();
    env.metadata.feature_counts.tes_prediction = 2;
    assert.equal((await worker.fetch(request(id), env)).status, 503);
  } finally { globalThis.fetch = nativeFetch; }
});

test("D1 catalogue serves the registered snapshot and refuses an unavailable revision", async () => {
  const env = environment();
  try {
    const response = await worker.fetch(new Request("https://bted.example/api/batter-catalogue"), env);
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("x-bted-metadata-source"), "d1");
    const data = await response.json();
    assert.equal(data.revision, revision);
    assert.equal(data.genomes[0][0], id);
    assert.equal((await worker.fetch(request(id + "?revision=" + "a".repeat(40)), env)).status, 409);
    env.BTED_METADATA_REVISION = "a".repeat(40);
    assert.equal((await worker.fetch(request(id), env)).status, 503);
    assert.equal(env.calls.length, 0);
  } finally { globalThis.fetch = nativeFetch; }
});

test("genome HTML, metadata, config and file fallback share indexed lookups without mutating stored JSON", async () => {
  const env = environment();
  try {
    await worker.fetch(new Request("https://bted.example/genomes/" + id), env);
    await Promise.all([worker.fetch(request(id), env), worker.fetch(request(id + "/config"), env)]);
    await worker.fetch(new Request(request(id + "/files/reference.fa.gz"), { headers: { Range: "bytes=0-5" } }), env);
    assert.equal(env.d1Queries.filter(query => query.sql.includes("hf_genome_metadata")).length, 1);
    assert.equal(env.d1Queries.filter(query => query.sql.includes("hf_metadata_releases")).length, 1);
    assert.equal(env.metadata.revision, undefined); assert.equal(env.metadata.browser_files, undefined);
    const assets = env.ASSETS;
    env.ASSETS = { fetch: async req => req.url.endsWith("genome-browsers.json")
      ? Response.json({ experimental: { EXPERIMENT: "/jbrowse/assemblies/EXPERIMENT.config.json" } }) : assets.fetch(req) };
    await worker.fetch(new Request("https://bted.example/genomes/EXPERIMENT"), env);
    assert.equal(env.d1Queries.length, 2); // Static experimental pages do not query HF metadata.
  } finally { globalThis.fetch = nativeFetch; }
});

test("same-genome tracks merge using verified sequence aliases; mismatched references remain separate views", () => {
  const metadata = { genome_id: id, files: { "reference.fa.gz": { sha256: "a".repeat(64) } } };
  const base = () => ({ assemblies: [{ name: id }], tracks: [{ trackId: "batter_augmentation", metadata: {} }], defaultSession: { views: [{ id: "batter_view", tracks: [] }] }, metadata: {} });
  const experimental = { assemblies: [{ name: "experimental_ref", sequence: { adapter: { fastaLocation: { uri: "https://example.org/reference.fa" } } } }],
    tracks: [{ trackId: "experimental_endpoints", assemblyNames: ["experimental_ref"], metadata: { btedAbout: { kind: "endpoint" }, btedContigCounts: { BA000030: 1159 } } }], defaultSession: { views: [{ id: "experimental_view", tracks: [{ configuration: "experimental_endpoints" }] }] } };
  const verified = { compatible: true, batter_reference_sha256: "a".repeat(64), experimental_reference_url: "https://example.org/reference.fa", aliases: { BA000030: "NC_003155" } };
  const merged = combineGenomeTracks(base(), experimental, verified, metadata);
  assert.equal(merged.assemblies.length, 1);
  assert.equal(merged.defaultSession.views.length, 1);
  assert.deepEqual(merged.tracks[1].assemblyNames, [id]);
  assert.deepEqual(merged.tracks[1].metadata.btedContigCounts, { NC_003155: 1159 });
  assert.deepEqual(experimental.tracks[0].metadata.btedContigCounts, { BA000030: 1159 });
  assert.equal(merged.defaultSession.views[0].tracks[0].configuration, "experimental_endpoints");
  assert.equal(decodeURIComponent(merged.assemblies[0].refNameAliases.adapter.location.uri), "data:text/plain,NC_003155\tBA000030\n");
  const separated = combineGenomeTracks(base(), experimental, { ...verified, batter_reference_sha256: "b".repeat(64) }, metadata);
  assert.equal(separated.assemblies.length, 2);
  assert.equal(separated.defaultSession.views.length, 2);
  assert.equal(separated.metadata.combined_reference_status, "separate_views");
  assert.deepEqual(separated.tracks[1].assemblyNames, ["experimental_ref"]);
  assert.deepEqual(separated.tracks[1].metadata.btedContigCounts, { BA000030: 1159 });
});

test("contig status separates cataloged zero, unavailable counts and absent experiments without using viewport features", async () => {
  const pluginSource = readFileSync(new URL("../jbrowse-plugin/src/plugin.js", import.meta.url), "utf8");
  const { experimentalContigCoverage, endpointTrackCount, scientificTrackCount } = await import(`data:text/javascript;base64,${Buffer.from(pluginSource + '\n// coverage-only test').toString("base64")}`);
  const track = counts => ({ assemblyNames: [id], metadata: { btedAbout: { kind: "endpoint" }, btedContigCounts: counts } });
  const tracks = [track({ chr1: 100 }), track({ chr1: 12, chr2: 3 })];
  assert.deepEqual(experimentalContigCoverage(tracks, id, "chr1"), { status: "covered", count: 112 });
  assert.deepEqual(experimentalContigCoverage(tracks, id, "chr2"), { status: "covered", count: 3 });
  assert.deepEqual(experimentalContigCoverage(tracks, id, "chr3"), { status: "empty", count: 0 });
  for (const counts of [null, { chr1: -1 }, { chr1: "100" }]) {
    assert.deepEqual(experimentalContigCoverage([...tracks, track(counts)], id, "chr3"), { status: "unknown", count: null });
  }
  assert.deepEqual(experimentalContigCoverage(tracks, "another_assembly", "chr1"), { status: "unavailable", count: null });
  assert.deepEqual(experimentalContigCoverage([], id, "chr1"), { status: "unavailable", count: null });
  assert.equal(endpointTrackCount(tracks[0], "chr1").text, "100 records");
  assert.equal(endpointTrackCount(tracks[1], "chr1").text, "12 records");
  assert.equal(endpointTrackCount(tracks[0], "chr2").status, "empty");
  assert.equal(endpointTrackCount(tracks[0], "chr2").text, "0 records");
  assert.equal(endpointTrackCount(track(null), "chr1").text, "Count unavailable");
  assert.ok(endpointTrackCount(tracks[1], "chr2").title.includes("chr2"));
  assert.ok(endpointTrackCount(tracks[1], "chr2").title.includes("Whole contig, both strands"));
  assert.equal(endpointTrackCount({metadata:{btedAbout:{kind:"signal"}}}, "chr1"), null);
  const computed = kind => ({ metadata: { btedAbout: { kind }, btedContigCounts: { chr1: 9, chr2: 0 }, btedContigBreakdown: { chr1: { otu: 7, rfam: 2 } } } });
  assert.equal(scientificTrackCount(tracks[0], "chr1").text, "100 records");
  assert.equal(scientificTrackCount(computed("prediction"), "chr1").text, "9 regions");
  assert.equal(scientificTrackCount(computed("augmentation"), "chr2").text, "0 regions");
  assert.equal(scientificTrackCount(computed("augmentation"), "missing").text, "Count unavailable");
  assert.ok(scientificTrackCount(computed("augmentation"), "chr1").title.includes("OTU: 7; Rfam: 2"));
  assert.ok(scientificTrackCount(computed("prediction"), "chr1").title.includes("Whole contig, both strands"));
  assert.equal(scientificTrackCount(computed("reference"), "chr1"), null);
});

test("scientific glyphs anchor one-base endpoints and preserve interval bounds and strand when reversed", async () => {
  const source = readFileSync(new URL("../jbrowse-plugin/src/plugin.js", import.meta.url), "utf8");
  const { drawBtedScientificFeature: draw, isBtedScientificFeature: matches, predictionTooltip } = await import(
    `data:text/javascript;base64,${Buffer.from(source + '\n// glyph-only test').toString("base64")}`);
  const feature = (type, strand, source = "BATTER") => ({ get: key => ({ type, strand, source }[key]) });
  const render = (type, strand, reversed = false, width = 1) => {
    const paths = [], rectangles = []; let path;
    const ctx = { beginPath() { path = []; }, moveTo(x,y) { path.push([x,y]); },
      lineTo(x,y) { path.push([x,y]); }, closePath() {}, stroke() { paths.push({ kind: "stroke", points: path }); },
      fill() { paths.push({ kind: "fill", points: path }); }, fillRect(...rect) { rectangles.push(rect); } };
    const box = { x: 20, y: 5, width, height: 14 };
    draw({ ctx, feature: feature(type, strand), featureLayout: box, reversed, canvasWidth: 100 });
    return { paths, rectangles, box, color: ctx.fillStyle };
  };
  for (const [strand, reversed, direction] of [[1,false,1],[-1,false,-1],[1,true,-1],[-1,true,1]]) {
    const endpoint = render("terminator_endpoint", strand, reversed);
    assert.equal(Math.sign(endpoint.paths[0].points[1][0] - 20.5), direction);
    assert.ok(endpoint.paths[0].points.every(([x]) => x >= endpoint.box.x && x <= endpoint.box.x + endpoint.box.totalLayoutWidth));
    assert.equal(endpoint.paths[0].kind, "fill");
    assert.equal(endpoint.color, strand === 1 ? "#0f766e" : "#be123c");
    assert.equal(endpoint.rectangles.length, 0);
    assert.deepEqual(endpoint.paths[1], { kind: 'stroke', points: [[20.5,6],[20.5,18]] });
    for (const type of ["augmented_terminator_span", "rfam_training_span", "predicted_terminator_region"]) {
      const interval = render(type, strand, reversed, 40);
      const anchor = direction > 0 ? 60 : 20;
      assert.deepEqual(interval.rectangles, [[20,15,40,3]]);
      assert.deepEqual(interval.paths[0].points.slice(0,2), [[anchor,6],[anchor + direction * 6,6]]);
      assert.equal(interval.paths[0].kind, "stroke");
      assert.equal(interval.color, strand === 1 ? "#0f766e" : "#be123c");
      assert.equal(interval.paths[0].points[3][0], anchor + direction * 6);
      assert.ok(interval.paths[0].points.every(([x,y]) => x >= interval.box.x && x <= interval.box.x + interval.box.totalLayoutWidth && y >= 6 && y <= 12));
      assert.deepEqual(interval.paths[1], { kind: 'stroke', points: [[anchor,6],[anchor,18]] });
      assert.ok(interval.box.x <= 20 && interval.box.x + interval.box.totalLayoutWidth >= 60);
      assert.equal(interval.box.totalLayoutWidth, 48);
    }
  }
  assert.equal(render("augmented_terminator_span", 0, false, 40).rectangles.length, 1);
  for (const [strand, boundary] of [[1, '44,113'],[-1, '44,060']]) {
    const tooltip = predictionTooltip({ get: key => ({ strand, start: 44059, end: 44113, refName: 'chr1', score: 0.7 }[key]) });
    assert.ok(tooltip.includes('chr1:44,060–44,113'));
    assert.ok(tooltip.includes('54 bp'));
    assert.ok(tooltip.includes(`3′ boundary: ${boundary}`));
    assert.ok(tooltip.includes('Score: 0.7'));
  }
  assert.ok(predictionTooltip({ get: key => ({ strand: 0, start: 0, end: 1, refName: 'chr1', score: 0 }[key]) }).includes('(?)'));
  assert.equal(render("predicted_terminator_region", 0, false, 40).rectangles.length, 1);
  assert.equal(render("terminator_endpoint", 0).paths.length, 1);
  assert.equal(render("training_sequence_window", 1, false, 40).rectangles[0][2], 40);
  assert.equal(render("rfam_training_window", -1, false, 40).rectangles[0][2], 40);
  assert.equal(matches(feature("terminator_endpoint", 1, "BATTER_S1_010")), true);
  assert.equal(matches(feature("predicted_terminator_region", 1, "BATTER-TPE")), true);
  assert.equal(matches(feature("rfam_training_window", -1, "BATTER-augmentation")), true);
  assert.equal(matches(feature("gene", 1)), false);
  assert.equal(matches(feature("terminator_endpoint", 1, "my_experiment")), false);
});

test("file proxy preserves ranges and rejects unknown IDs, arbitrary files and revision mixing", async () => {
  let env = environment();
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
    env = environment(); env.metadata.files["reference.fa.gz.fai"].sha256 = "b".repeat(64);
    assert.equal((await worker.fetch(request(id + "/config"), env)).status, 503);
  } finally { globalThis.fetch = nativeFetch; }
});

test("augmentation fallback requires matching pinned metadata, preserving Range and cancellation", async () => {
  globalThis.location = { origin: "https://bted.example", href: "blob:https://bted.example/adapter" };
  const url = `https://huggingface.co/datasets/liurulong/terminator/resolve/${revision}/v0.5.0/genomes/batter-000/${id}/reference/reference.fa.gz`;
  const backup = `/api/batter/${id}/files/reference.fa.gz?revision=${revision}`;
  const calls = []; let failure = false; const indexUrl = url + ".gzi";
  globalThis.fetch = async (input, options = {}) => {
    const req = new Request(input, options); calls.push(req); req.signal.throwIfAborted();
    if (req.url.startsWith("https://huggingface.co/")) {
      if (req.url === indexUrl) return new Response("origin denied", { status: 403 });
      if (failure) throw new TypeError("Failed to fetch");
      return new Response("direct");
    }
    if (!req.url.includes("/files/")) return Response.json({ revision, batch: "000", browser_files: { "reference.fa.gz": { url, fallback_url: backup, sha256: "b".repeat(64) }, "reference.fa.gz.gzi": { url: indexUrl, fallback_url: backup + ".gzi", sha256: "b".repeat(64) } } });
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
    assert.equal(await (await plugin.fetchBtedAsset(indexUrl)).text(), "backup"); // HTTP 403 also uses the registered backup.
    const controller = new AbortController(); controller.abort();
    await assert.rejects(plugin.fetchBtedAsset(url, { signal: controller.signal }), { name: "AbortError" });
    const feature = (type, dataset) => ({ get: key => key === "type" ? type : { dataset_class: [dataset] } });
    assert.equal(plugin.augmentationColor(feature("training_sequence_window", "otu_augmentation_window")), "#bfdbfe");
    assert.equal(plugin.augmentationColor({get: key => ({type: "augmented_terminator_span", strand: 1}[key])}), "#0f766e");
    assert.equal(plugin.augmentationColor({get: key => ({type: "rfam_training_span", strand: -1}[key])}), "#be123c");
  } finally { globalThis.fetch = nativeFetch; }
});

test("small immutable files use verified full reads when uncached forwarding fails, preserving ranges and HEAD", async () => {
  let env = environment();
  const fixtureFetch = globalThis.fetch;
  globalThis.fetch = (url, options = {}) => String(url).endsWith("/training/augmentation.gff3.gz") && !options.cf?.cacheEverything
    ? new Response("origin denied", { status: 403 }) : fixtureFetch(url, options);
  try {
    const path = id + "/files/augmentation.gff3.gz?revision=" + revision;
    const full = await worker.fetch(request(path), env);
    assert.equal(full.status, 200);
    const bytes = Buffer.from(await full.arrayBuffer());
    assert.equal(createHash("sha256").update(bytes).digest("hex"), env.metadata.files["augmentation.gff3.gz"].sha256);
    for (const [range, start, end] of [["bytes=0-15", 0, 15], ["bytes=16-", 16, bytes.length-1],
      ["bytes=-16", bytes.length-16, bytes.length-1], ["bytes=0-999999", 0, bytes.length-1]]) {
      const response = await worker.fetch(new Request(request(path), { headers: { Range: range } }), env);
      assert.equal(response.status, 206);
      assert.equal(response.headers.get("content-range"), `bytes ${start}-${end}/${bytes.length}`);
      assert.equal(response.headers.get("x-bted-sha256"), env.metadata.files["augmentation.gff3.gz"].sha256);
      assert.deepEqual(Buffer.from(await response.arrayBuffer()), bytes.subarray(start, end+1));
    }
    const head = await worker.fetch(new Request(request(path), { method: "HEAD", headers: { Range: "bytes=0-15" } }), env);
    assert.equal(head.status, 206); assert.equal(head.headers.get("content-length"), "16");
    assert.equal((await head.arrayBuffer()).byteLength, 0);
    for (const range of ["bytes=-0", "bytes=20-10", "bytes=999999-", "bytes=0-1,3-4", "bytes=9007199254740992-"]) {
      assert.equal((await worker.fetch(new Request(request(path), { headers: { Range: range } }), env)).status, 416);
    }
    env = environment(); env.metadata.files["augmentation.gff3.gz"].sha256 = "a".repeat(64);
    assert.equal((await worker.fetch(request(path), env)).status, 503);
  } finally { globalThis.fetch = nativeFetch; }
});

test("annotation supplement fallback pins annotation and reference versions independently", async () => {
  globalThis.location = { origin: 'https://bted.example', href: 'blob:https://bted.example/adapter' };
  const annotationRevision = 'a'.repeat(40);
  const url = `https://huggingface.co/datasets/liurulong/terminator/resolve/${annotationRevision}/v0.5.1/annotation-recovery/2026-10-14/genomes/${id}/genes.gff3`;
  const backup = `/api/batter/${id}/files/genes.gff3?revision=${revision}`;
  const calls = [];
  globalThis.fetch = async (input, options) => {
    const req = new Request(input, options); calls.push(req);
    if (req.url.startsWith('https://huggingface.co/')) throw new TypeError('origin unavailable');
    if (!req.url.includes('/files/')) return Response.json({ revision, annotation: { annotation_revision: annotationRevision },
      browser_files: { 'genes.gff3': { url, fallback_url: backup, sha256: 'b'.repeat(64) } } });
    return new Response('annotation', { headers: { 'x-bted-sha256': 'b'.repeat(64), 'x-bted-revision': revision } });
  };
  try {
    const pluginSource = readFileSync(new URL('../jbrowse-plugin/src/plugin.js', import.meta.url), 'utf8') + '\n// supplement-fallback-test';
    const plugin = await import(`data:text/javascript;base64,${Buffer.from(pluginSource).toString('base64')}`);
    assert.equal(await (await plugin.fetchBtedAsset(url, { headers: { Range: 'bytes=0-9' } })).text(), 'annotation');
    assert.equal(calls.at(-1).headers.get('range'), 'bytes=0-9');
    assert.equal(calls[1].url, `https://bted.example/api/batter/${id}`);
    assert.ok(calls.at(-1).url.endsWith(`?revision=${revision}`));
    await assert.rejects(plugin.fetchBtedAsset(url.replace(annotationRevision, 'c'.repeat(40))), { name: 'TypeError' });
  } finally { globalThis.fetch = nativeFetch; }
});
