import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";

const source = readFileSync(new URL("../prototype/accession-range/src/worker.js", import.meta.url), "utf8");
const { default: worker, usageDay, shiftUsageDay } = await import(`data:text/javascript;base64,${Buffer.from(source + "\nexport { usageDay, shiftUsageDay };").toString("base64")}`);

function environment() {
  const sqlite = new DatabaseSync(":memory:");
  const schema = readFileSync(new URL("../prototype/accession-range/migrations/0003_usage_analytics.sql", import.meta.url), "utf8");
  sqlite.exec(schema);
  sqlite.exec(schema); // Idempotent for an already deployed D1.
  return {
    sqlite, BTED_ANALYTICS: "on",
    ASSETS: { fetch: async () => new Response("<!doctype html><title>BTED</title>", { headers: { "content-type": "text/html; charset=utf-8" } }) },
    BTED_DB: {
      prepare(sql) { return { bind(...values) { return { sql, values }; } }; },
      async batch(statements) {
        sqlite.exec("BEGIN");
        try {
          const result = statements.map(({ sql, values }) => ({ results: sqlite.prepare(sql).all(...values) }));
          sqlite.exec("COMMIT");
          return result;
        } catch (error) { sqlite.exec("ROLLBACK"); throw error; }
      },
    },
  };
}

const browserHeaders = { "user-agent": "Mozilla/5.0 Chrome/130.0.0.0 Safari/537.36", "sec-fetch-dest": "document", accept: "text/html" };
function request(path = "/", { method = "GET", headers = {}, cf = { country: "US", region: "California", city: "Los Angeles" } } = {}) {
  const req = new Request(`https://bted.example${path}`, { method, headers: { ...browserHeaders, ...headers } });
  Object.defineProperty(req, "cf", { value: cf });
  return req;
}
async function run(req, env) {
  const pending = [];
  const response = await worker.fetch(req, env, { waitUntil: (task) => pending.push(task) });
  await Promise.all(pending);
  return response;
}

test("repeat document views aggregate geography and normalized paths, without identifiers", async () => {
  const env = environment();
  try {
    await run(request("/index.html?secret=ignored"), env);
    await run(request("/"), env);
    await run(request("/genomes.html"), env);
    await run(request("/genomes/"), env);
    await run(request("/genomes/GCF_000005845.2.html?loc=123"), env);
    await run(request("/genomes/GCF_000005845.2/"), env);
    await run(request("/methodology.html", { cf: { country: "hk", region: "Hong Kong", city: "Hong Kong" } }), env);
    const response = await run(request("/api/usage?days=7"), env);
    assert.equal(response.status, 200);
    const report = await response.json();
    assert.deepEqual(report.totals, { views: 7, countries: 2, activeDays: 1 });
    assert.equal(report.countries[0].code, "US");
    assert.equal(report.countries[0].share, 6 / 7);
    assert.equal(report.countries[1].name, "Hong Kong, China");
    assert.equal(report.daily.length, 7);
    assert.equal(report.daily.at(-1).views, 7);
    assert.equal(report.daily[0].views, 0);
    assert.equal(report.paths.find((row) => row.path === "/").views, 2);
    assert.equal(report.paths.find((row) => row.path === "/genomes").views, 2);
    assert.equal(report.paths.find((row) => row.path === "/genomes/GCF_000005845.2").views, 2);
    assert.equal(report.cities[0].city, "Los Angeles");
    const columns = env.sqlite.prepare("PRAGMA table_info(analytics_daily_geo)").all().map((row) => row.name);
    assert.deepEqual(columns, ["day", "country_code", "region", "city", "views"]);
    assert.ok(!JSON.stringify(report).includes("secret"));
  } finally { env.sqlite.close(); }
});

test("API, assets, iframe, downloads, dashboards, bots, prefetch, HEAD and failed HTML do not count", async () => {
  const env = environment();
  try {
    for (const path of ["/usage", "/usage.html", "/jbrowse/index.html", "/assets/genome-page.js", "/downloads/v0.4.0/release.json", "/sources.html", "/unknown"]) await run(request(path), env);
    for (const headers of [{ "sec-fetch-dest": "iframe" }, { "sec-fetch-dest": "empty" }, { purpose: "prefetch" }, { "sec-purpose": "prefetch;prerender" }, { range: "bytes=0-10" }, { "user-agent": "curl/8.0" }, { "user-agent": "Googlebot" }, { "user-agent": "" }, { "next-router-prefetch": "1" }]) await run(request("/", { headers }), env);
    await run(request("/", { method: "HEAD" }), env);
    for (const status of [301, 404, 500]) {
      env.ASSETS.fetch = async () => new Response("<html>", { status, headers: { "content-type": "text/html" } });
      await run(request(), env);
    }
    env.ASSETS.fetch = async () => new Response("bytes", { headers: { "content-type": "application/octet-stream" } });
    await run(request(), env);
    assert.equal((await (await run(request("/api/usage"), env)).json()).totals.views, 0);
    env.ASSETS.fetch = async () => new Response("<html>", { headers: { "content-type": "text/html" } });
    await run(request("/", { headers: { "sec-fetch-dest": "" } }), env); // Older browser fallback.
    assert.equal((await (await run(request("/api/usage"), env)).json()).totals.views, 1);
  } finally { env.sqlite.close(); }
});

test("only request.cf supplies locations; missing/invalid country is Unknown and text is bounded", async () => {
  const env = environment();
  try {
    await run(request("/", { headers: { "cf-ipcountry": "CN", "x-vercel-ip-city": "Beijing", "cf-connecting-ip": "1.2.3.4", "x-forwarded-for": "5.6.7.8" } }), env);
    await run(request("/", { cf: null, headers: { "cf-ipcountry": "CN", "x-vercel-ip-city": "Beijing" } }), env);
    await run(request("/", { cf: { country: "T1", city: "Discard this" } }), env);
    await run(request("/", { cf: { country: "TW", city: "x".repeat(100), region: "y".repeat(100) } }), env);
    const report = await (await run(request("/api/usage"), env)).json();
    assert.equal(report.countries.find((row) => row.code === "XX").views, 2);
    assert.ok(!report.countries.some((row) => row.code === "CN"));
    assert.equal(report.cities.find((row) => row.countryCode === "TW").city.length, 64);
    assert.equal(report.cities.find((row) => row.countryCode === "TW").region.length, 64);
    assert.ok(!JSON.stringify(report).includes("1.2.3.4"));
  } finally { env.sqlite.close(); }
});

test("ranges are validated, history is bounded, cron purges both aggregates at UTC boundary", async () => {
  const env = environment();
  try {
    const today = usageDay();
    const old = shiftUsageDay(today, -400);
    const retained = shiftUsageDay(today, -399);
    for (const day of [old, retained, today]) {
      env.sqlite.prepare("INSERT INTO analytics_daily_geo VALUES (?, 'US', '', '', 1)").run(day);
      env.sqlite.prepare("INSERT INTO analytics_daily_path VALUES (?, '/', 1)").run(day);
    }
    for (const days of ["-1", "401", "no", "", "7;DROP", "7.0"]) assert.equal((await run(request(`/api/usage?days=${encodeURIComponent(days)}`), env)).status, 400);
    const history = await (await run(request("/api/usage?days=0"), env)).json();
    assert.equal(history.totals.views, 2);
    assert.equal(history.daily.length, 400);
    assert.equal(history.firstRecordedDay, retained);
    const pending = [];
    await worker.scheduled({ scheduledTime: Date.parse(`${today}T03:20:00Z`) }, env, { waitUntil: (task) => pending.push(task) });
    await Promise.all(pending);
    for (const table of ["analytics_daily_geo", "analytics_daily_path"]) assert.equal(env.sqlite.prepare(`SELECT COUNT(*) AS n FROM ${table}`).get().n, 2);
    assert.equal(shiftUsageDay("2024-03-01", -1), "2024-02-29");
  } finally { env.sqlite.close(); }
});

test("counting can be disabled; reporting and failures never depend on a scientific release", async () => {
  const env = environment();
  try {
    env.BTED_ANALYTICS = "off";
    await run(request(), env);
    assert.equal((await (await run(request("/api/usage"), env)).json()).totals.views, 0);
    env.BTED_ANALYTICS = "on";
    env.BTED_DB.batch = async () => { throw new Error("No usage table"); };
    assert.equal((await run(request(), env)).status, 200);
    const failure = await run(request("/api/usage"), env);
    assert.equal(failure.status, 503);
    assert.equal(failure.headers.get("cache-control"), "no-store");
    assert.deepEqual(await failure.json(), { error: "usage_unavailable" });
  } finally { env.sqlite.close(); }
});
