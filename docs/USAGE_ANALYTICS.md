# Website usage counts

`usage.html` reports page views, not unique visitors.

## Counting rules

- Count successful GET page loads, including reloads, for the home page, directories, data notes and genome details.
- Normalize `.html` and extensionless paths and omit query parameters.
- Exclude API calls, downloads, static assets, redirects, the usage page, prefetches, Range requests, JBrowse frames and recognized crawlers. Unrecognized automated traffic may still be counted.
- Use Cloudflare `request.cf` for approximate country, region and city; ignore client-supplied location headers. Proxy/VPN locations may reflect their exit point.
- Store daily aggregates, not raw IP addresses, user agents, visitor identifiers or individual-event logs.
- Write asynchronously with `ctx.waitUntil`; counting failure does not block the page.
- Retain 400 days, removing expired rows daily at 03:20 UTC.

## Storage and API

| Table | Key | Value |
|---|---|---|
| `analytics_daily_geo` | UTC day, country code, region, city | Views |
| `analytics_daily_path` | UTC day, normalized path | Views |

D1 batch updates both tables atomically. Unknown countries use `XX`, and missing cities use an empty string. Totals include unknown locations; the country count excludes `XX`. Reports show the top 50 cities and 30 pages.

`GET /api/usage?days=7|30|90|365|0` returns aggregates; the default is 30 days and `0` selects retained history. `BTED_ANALYTICS=on` enables new counts. Other values stop counting while retaining existing reports. `assets.run_worker_first=true` routes HTML through the Worker.

For a new database, create the tables with `database/migrations/0003_usage_analytics.sql` before enabling counting. Do not replay schema changes on an existing database without checking its state.

```sh
node --test tests/test_usage_analytics.mjs
```

The map uses public-domain Natural Earth 1:110m data, with world-atlas 1:50m data for small countries and regions, reused from RAPPTOR. Its color scale is logarithmic; tables show exact counts. Local previews do not have production visitor geolocation.
