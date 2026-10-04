import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../prototype/accession-range/src/worker.js", import.meta.url), "utf8");
const { default: worker, currentRelease, publicAsset, cachedPublicApi } = await import(`data:text/javascript;base64,${Buffer.from(source + "\nexport { currentRelease, publicAsset, cachedPublicApi };").toString("base64")}`);

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
