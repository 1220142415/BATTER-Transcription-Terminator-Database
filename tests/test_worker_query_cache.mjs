import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../worker/src/worker.js", import.meta.url), "utf8");
const { default: worker, currentRelease, publicAsset, cachedPublicApi, hfMetadataRelease, hfGenomeMetadata, batterCatalogueResponse } = await import(`data:text/javascript;base64,${Buffer.from(source + "\nexport { currentRelease, publicAsset, cachedPublicApi, hfMetadataRelease, hfGenomeMetadata, batterCatalogueResponse };").toString("base64")}`);

function edgeCache() {
  const entries = new Map();
  return {
    async match(request) {
      const entry = entries.get(request.url);
      return entry?.expiresAt > Date.now() ? entry.response.clone() : undefined;
    },
    async put(request, response) {
      const ttl = Number(/s-maxage=(\d+)/.exec(response.headers.get("cache-control"))[1]);
      entries.set(request.url, { response, expiresAt: Date.now() + ttl * 1000 });
    },
  };
}

test("fixed HF release and genome reads share concurrent requests and isolate revisions", async () => {
  const revision = "a".repeat(40);
  let reads = 0;
  const env = { BTED_METADATA_REVISION: revision, BTED_DB: { prepare: () => ({ bind: (...values) => ({
    first: async () => { reads++; return { revision: values[0], metadata_json: "{}" }; },
  }) }) } };
  await Promise.all([hfMetadataRelease(env), hfMetadataRelease(env), hfGenomeMetadata(env, "A"), hfGenomeMetadata(env, "A")]);
  assert.equal(reads, 2);
  await hfGenomeMetadata(env, "B"); assert.equal(reads, 3);
  await hfGenomeMetadata({ ...env, BTED_METADATA_REVISION: "b".repeat(40) }, "A"); assert.equal(reads, 4);
});

test("annotation supplement revisions isolate edge responses without additional database queries", async () => {
  const originalCaches = globalThis.caches;
  globalThis.caches = { default: edgeCache() };
  let loads = 0;
  const request = new Request('https://bted.example/api/batter/A/config');
  const env = { BTED_METADATA_REVISION: 'a'.repeat(40) };
  const load = async () => Response.json({ load: ++loads });
  try {
    await cachedPublicApi(request, null, load, env);
    const withAnnotation = { ...env, BTED_ANNOTATION_REVISION: 'b'.repeat(40) };
    assert.equal((await cachedPublicApi(request, null, load, withAnnotation)).headers.get('x-bted-cache'), 'MISS');
    assert.equal((await cachedPublicApi(request, null, load, withAnnotation)).headers.get('x-bted-cache'), 'HIT');
    assert.equal(loads, 2);
  } finally { globalThis.caches = originalCaches; }
});

test("catalogue cold load scans 430 indexed page rows once without OFFSET", async () => {
  let queries = 0, rowsRead = 0;
  const revision = "a".repeat(40);
  const env = { BTED_METADATA_REVISION: revision, BTED_DB: { prepare: sql => ({ bind: (...values) => ({
    first: async () => ({ revision, catalogue_header_json: JSON.stringify({ revision }) }),
    all: async () => {
      assert.ok(!sql.includes("OFFSET")); assert.match(sql, /page >= \? AND page < \?/);
      queries++;
      const results = Array.from({ length: Math.max(0, Math.min(values[2], 430) - values[1]) }, (_, i) => ({ rows_json: JSON.stringify([[values[1] + i]]) }));
      rowsRead += results.length; return { results };
    },
  }) }) } };
  const request = new Request("https://bted.example/api/batter-catalogue");
  const [response, concurrent] = await Promise.all([batterCatalogueResponse(request, env), batterCatalogueResponse(request, env)]);
  assert.equal(response.status, 200);
  const data = await response.json(); assert.equal(data.genomes.length, 430);
  assert.deepEqual(data.genomes.at(-1), [429]); assert.equal(queries, 5); assert.equal(rowsRead, 430);
  assert.deepEqual(await concurrent.json(), data);
  assert.deepEqual(await (await batterCatalogueResponse(request, env)).json(), data);
  assert.equal(queries, 5); assert.equal(rowsRead, 430);
  const originalNow = Date.now, expired = originalNow() + 60001;
  try {
    Date.now = () => expired;
    assert.deepEqual(await (await batterCatalogueResponse(request, env)).json(), data);
    assert.equal(queries, 10); assert.equal(rowsRead, 860);
  } finally { Date.now = originalNow; }
});

test("failed catalogue page reads do not poison a retry", async () => {
  const revision = "a".repeat(40);
  let queries = 0;
  const env = { BTED_METADATA_REVISION: revision, BTED_DB: { prepare: () => ({ bind: () => ({
    first: async () => ({ revision, catalogue_header_json: JSON.stringify({ revision }) }),
    all: async () => { if (++queries === 1) throw new Error("unavailable"); return { results: [{ rows_json: '[["A"]]' }] }; },
  }) }) } };
  const request = new Request("https://bted.example/api/batter-catalogue");
  assert.equal((await batterCatalogueResponse(request, env)).status, 503);
  assert.deepEqual((await (await batterCatalogueResponse(request, env)).json()).genomes, [["A"]]);
  assert.equal(queries, 2);
});

test("pinned directory browser cache and unversioned requests share the edge entry safely", async () => {
  const originalCaches = globalThis.caches;
  globalThis.caches = { default: edgeCache() };
  const revision = "a".repeat(40), annotation = "b".repeat(40);
  const env = { BTED_METADATA_REVISION: revision, BTED_ANNOTATION_REVISION: annotation };
  let reads = 0;
  const load = async () => Response.json({ reads: ++reads });
  const request = query => new Request(`https://bted.example/api/batter-catalogue${query}`);
  try {
    const pinned = await cachedPublicApi(request(`?revision=${revision}&annotation=${annotation}&v=1`), null, load, env);
    assert.match(pinned.headers.get("cache-control"), /max-age=31536000, s-maxage=604800, immutable/);
    for (const query of ["", `?revision=${revision}&annotation=wrong&v=1`, `?revision=wrong&annotation=${annotation}&v=1`, `?revision=${revision}&annotation=${annotation}&v=2`]) {
      const hit = await cachedPublicApi(request(query), null, load, env);
      assert.equal(hit.headers.get("x-bted-cache"), "HIT");
      assert.equal(hit.headers.get("cache-control"), "public, max-age=60, s-maxage=604800");
    }
    assert.equal(reads, 1);
    const hit = await cachedPublicApi(request(`?revision=${revision}&annotation=${annotation}&v=1`), null, load, env);
    assert.match(hit.headers.get("cache-control"), /immutable/);
    assert.equal(reads, 1);
  } finally { globalThis.caches = originalCaches; }
});

test("fixed metadata edge hits normalize unused queries, isolate snapshots and validate before hits", async () => {
  const originalCaches = globalThis.caches, originalNow = Date.now;
  let now = originalNow(), reads = 0;
  Date.now = () => now; globalThis.caches = { default: edgeCache() };
  const revision = "a".repeat(40), env = { BTED_METADATA_REVISION: revision };
  const request = (path, options) => new Request(`https://bted.example${path}`, options);
  const load = async () => { reads++; return Response.json({ reads }); };
  try {
    for (const path of ["/api/batter-catalogue", "/api/batter/GCF_A", "/api/batter/GCF_A/config"]) {
      assert.equal((await cachedPublicApi(request(path), null, load, env)).headers.get("x-bted-cache"), "MISS");
      const hit = await cachedPublicApi(request(path + "?revision=" + revision + "&v=29&unused=1"), null, load, env);
      assert.equal(hit.headers.get("x-bted-cache"), "HIT"); assert.match(hit.headers.get("cache-control"), path === "/api/batter-catalogue" ? /s-maxage=604800/ : /s-maxage=86400/);
    }
    assert.equal(reads, 3);
    now += 301000;
    await cachedPublicApi(request("/api/batter-catalogue"), null, load, env); assert.equal(reads, 3);
    for (const [query, status] of [["?url=x", 400], ["?revision=wrong", 409]]) {
      const response = await cachedPublicApi(request("/api/batter/GCF_A" + query), null, async () => Response.json({}, { status }), env);
      assert.equal(response.status, status);
    }
    await cachedPublicApi(request("/api/batter/GCF_A"), null, load, { BTED_METADATA_REVISION: "b".repeat(40) }); assert.equal(reads, 4);
    for (const options of [{ method: "HEAD" }, { headers: { Range: "bytes=0-5" } }]) await cachedPublicApi(request("/api/batter/GCF_A", options), null, load, env);
    assert.equal(reads, 6);
    now += 86400000;
    await cachedPublicApi(request("/api/batter/GCF_A"), null, load, env); assert.equal(reads, 7);
    await cachedPublicApi(request("/api/batter/GCF_A/files/reference.fa.gz"), null, load, env);
    await cachedPublicApi(request("/api/batter/GCF_A/files/reference.fa.gz"), null, load, env); assert.equal(reads, 9);
  } finally { globalThis.caches = originalCaches; Date.now = originalNow; }
});

test("D1 release and asset lookups share concurrent reads, expire, and remain database-scoped", async () => {
  const originalNow = Date.now;
  let now = originalNow(), reads = 0;
  Date.now = () => now;
  const database = { prepare: sql => ({ bind: (...values) => ({ first: async () => { reads++; return { sql, values }; } }) }) };
  const env = { BTED_DB: database };
  try {
    await Promise.all([currentRelease(env), currentRelease(env)]);
    assert.equal(reads, 1);
    await Promise.all([publicAsset(env, "v0.4.0", "A"), publicAsset(env, "v0.4.0", "A")]);
    assert.equal(reads, 2);
    await publicAsset(env, "v0.4.0", "B");
    await publicAsset(env, "v0.3.0", "A");
    assert.equal(reads, 4);
    await currentRelease({ BTED_DB: { ...database } });
    assert.equal(reads, 5);
    now += 60001;
    await currentRelease(env); await publicAsset(env, "v0.4.0", "A");
    assert.equal(reads, 7);
  } finally { Date.now = originalNow; }
});

test("missing or failed lookups can recover immediately instead of caching a failure", async () => {
  let reads = 0, mode = "missing";
  const env = { BTED_DB: { prepare: () => ({ bind: () => ({ first: async () => {
    reads++; if (mode === "error") throw new Error("D1 unavailable");
    return mode === "missing" ? null : { is_public: 1 };
  } }) }) } };
  assert.equal(await publicAsset(env, "v0.4.0", "A"), null);
  mode = "error"; await assert.rejects(publicAsset(env, "v0.4.0", "A"));
  mode = "ok"; assert.equal((await publicAsset(env, "v0.4.0", "A")).is_public, 1);
  await publicAsset(env, "v0.4.0", "A"); assert.equal(reads, 3);
});

test("edge usage hits avoid all five D1 reads; ranges and expiry have independent reports", async () => {
  const originalCaches = globalThis.caches, originalNow = Date.now;
  let now = originalNow(), reads = 0, writes = 0;
  Date.now = () => now; globalThis.caches = { default: edgeCache() };
  const env = { BTED_ANALYTICS: "on", ASSETS: { fetch: async () => new Response("<html>", { headers: { "content-type": "text/html" } }) },
    BTED_DB: { prepare: sql => ({ bind: () => ({ sql }) }), async batch(statements) {
      if (statements[0].sql.startsWith("INSERT")) writes++;
      else reads += statements.length;
      return statements.map(() => ({ results: [] }));
    } } };
  async function run(path, options = {}) {
    const pending = [];
    const response = await worker.fetch(new Request(`https://bted.example${path}`, options), env, { waitUntil: task => pending.push(task) });
    await Promise.all(pending); return response;
  }
  try {
    const first = await run("/api/usage?days=7&test=1");
    assert.equal(first.status, 200); assert.equal(reads, 5);
    assert.match(first.headers.get("cache-control"), /s-maxage=60/);
    const second = await run("/api/usage?test=1&days=7");
    assert.equal(first.headers.get("x-bted-cache"), "MISS");
    assert.equal(second.headers.get("x-bted-cache"), "HIT");
    assert.deepEqual(await second.json(), await first.json()); assert.equal(reads, 5);
    await run("/api/usage?days=30"); assert.equal(reads, 10);
    now += 60001; await run("/api/usage?days=7&test=1"); assert.equal(reads, 15);
    await run("/api/usage?days=7&test=1", { headers: { Range: "bytes=0-5" } }); assert.equal(reads, 20);
    const browserHeaders = { "user-agent": "Mozilla/5.0 Chrome/130", "sec-fetch-dest": "document", accept: "text/html" };
    await run("/index.html", { headers: browserHeaders }); await run("/index.html", { headers: browserHeaders });
    assert.equal(writes, 2); // Page views still count even while API reports are cached.
  } finally { globalThis.caches = originalCaches; Date.now = originalNow; }
});

test("metadata cache skips failed responses, health, file ranges and HEAD; cache outages fall back", async () => {
  const originalCaches = globalThis.caches;
  globalThis.caches = { default: edgeCache() };
  let queries = 0;
  const request = (path, options) => new Request(`https://bted.example${path}`, options);
  const load = async () => { queries++; return Response.json({ result: queries }); };
  try {
    assert.match((await cachedPublicApi(request("/api/stats"), null, load)).headers.get("cache-control"), /s-maxage=300/);
    await cachedPublicApi(request("/api/stats"), null, load); assert.equal(queries, 1);
    for (const path of ["/api/health", "/api/assets/A", "/api/batter/GCF_A/config"]) {
      await cachedPublicApi(request(path), null, load); await cachedPublicApi(request(path), null, load);
    }
    await cachedPublicApi(request("/api/stats", { method: "HEAD" }), null, load);
    assert.equal(queries, 8);
    let failures = 0;
    const fail = async () => { failures++; return Response.json({ error: "unavailable" }, { status: 503 }); };
    await cachedPublicApi(request("/api/catalogue"), null, fail); await cachedPublicApi(request("/api/catalogue"), null, fail);
    assert.equal(failures, 2);
    const privateLoad = async () => { failures++; return Response.json({}, { headers: { "cache-control": "no-store" } }); };
    await cachedPublicApi(request("/api/catalogue"), null, privateLoad); await cachedPublicApi(request("/api/catalogue"), null, privateLoad);
    assert.equal(failures, 4);
    globalThis.caches = { default: { match: async () => { throw new Error("offline"); }, put: async () => { throw new Error("offline"); } } };
    assert.equal((await cachedPublicApi(request("/api/stats"), null, load)).status, 200);
  } finally { globalThis.caches = originalCaches; }
});
