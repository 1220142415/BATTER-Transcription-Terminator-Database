const PUBLIC_EVIDENCE = new Set([
  "observed_signal",
  "called_endpoint",
  "author_called_endpoint",
  "curated_record",
]);

const CURRENT_RELEASE_VERSION = "v0.4.0";
const RETIRED_RELEASE_ARCHIVE = "data/archive/BTED-v0.2.0.tar.gz";
const DATA_RELEASE_MANIFEST_PATH = "/assets/data-release.json";
const BTED_PLUGIN_PATH = "/jbrowse/plugins/bted-track-plugin.js?v=39";
const HF_DATA_ASSET_PATTERN = /^https:\/\/huggingface\.co\/datasets\/liurulong\/terminator\/resolve\/([0-9a-f]{40})\/(v0\.3\.0|v0\.4\.0|v0\.5\.0)\/(.+)$/;
const LOCAL_DATA_ASSET_PATTERN = /^downloads\/(v0\.3\.0|v0\.4\.0)\/(.+)$/;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const PLUS_STRAND_COLOR = "#0f766e";
const MINUS_STRAND_COLOR = "#be123c";
const CONDITION_SIGNAL_PATH = /^genomes\/experimental-only\/(GCF_\d+\.\d+)\/studies\/PMID_(\d+)\/sources\/(BATTER_[A-Za-z0-9_]+)\/conditions\/([A-Za-z0-9_-]+)\/mean3\/signal\.(plus|minus)\.bw$/;

function trackCitation(track) {
  try {
    const metadata = JSON.parse(track.metadata_json || "{}");
    return { citation: metadata.citation || {}, limitations: metadata.known_limitations || "" };
  } catch {
    return { citation: {}, limitations: "" };
  }
}

function publicSourceMetadata(source) {
  const { used_for_batter_augmentation: _unused, metadata_json, ...fields } = source;
  return { ...fields, metadata: JSON.parse(metadata_json || "null") };
}

const RESPONSE_HEADERS = [
  "accept-ranges",
  "cache-control",
  "content-length",
  "content-range",
  "content-type",
  "last-modified",
];

function json(payload, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(payload, null, 2), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", ...extraHeaders },
  });
}

function bad(code, message, field) {
  return json({ error: { code, message, ...(field ? { field } : {}) } }, 422);
}

function retiredReleaseResponse(releaseVersion) {
  return json({
    error: "release_version_retired",
    release_version: releaseVersion,
    current_release_version: CURRENT_RELEASE_VERSION,
    archive_path: RETIRED_RELEASE_ARCHIVE,
  }, 410);
}

function decodePath(value) {
  try {
    return decodeURIComponent(value);
  } catch {
    return null;
  }
}

function isLoopbackHost(hostname) {
  return hostname === "localhost" || hostname === "127.0.0.1";
}

function pageParams(url) {
  const page = Number(url.searchParams.get("page") || "1");
  const pageSize = Number(url.searchParams.get("page_size") || "50");
  if (!Number.isInteger(page) || page < 1) return { error: bad("invalid_pagination", "page must be an integer >= 1", "page") };
  if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > 100) {
    return { error: bad("invalid_pagination", "page_size must be between 1 and 100", "page_size") };
  }
  return { page, pageSize, offset: (page - 1) * pageSize };
}

function pageResult(data, page, pageSize, total) {
  return {
    data,
    pagination: {
      page,
      page_size: pageSize,
      returned: data.length,
      total,
      has_next: page * pageSize < total,
    },
  };
}

const d1Lookups = new WeakMap();

async function cachedD1Lookup(database, key, load) {
  let entries = d1Lookups.get(database);
  if (!entries) { entries = new Map(); d1Lookups.set(database, entries); }
  const now = Date.now();
  const existing = entries.get(key);
  if (existing?.expiresAt > now) return existing.task;
  const entry = { expiresAt: now + 60000, task: Promise.resolve().then(load) };
  entries.delete(key); entries.set(key, entry);
  while (entries.size > 512) entries.delete(entries.keys().next().value);
  try {
    const value = await entry.task;
    if (!value && entries.get(key) === entry) entries.delete(key);
    return value;
  } catch (error) {
    if (entries.get(key) === entry) entries.delete(key);
    throw error;
  }
}

async function currentRelease(env) {
  return cachedD1Lookup(env.BTED_DB, `release:${CURRENT_RELEASE_VERSION}`, () => env.BTED_DB.prepare(
    "SELECT * FROM release_versions WHERE release_version = ? AND is_current = 1 LIMIT 1",
  ).bind(CURRENT_RELEASE_VERSION).first());
}

function releasePayload(release) {
  return {
    release_version: release.release_version,
    status: release.status,
    canonical_manifest_path: release.canonical_manifest_path,
    canonical_manifest_sha256: release.canonical_manifest_sha256,
    asset_origin_status: release.asset_origin_status,
    materializer_version: release.materializer_version,
  };
}

function dataReleaseError(code) {
  const error = new Error(code);
  error.code = code;
  return error;
}

function dataReleaseErrorResponse(error) {
  const code = error?.code === "data_release_manifest_invalid"
    ? error.code
    : "data_release_manifest_missing";
  return json({ error: code }, 503, { "cache-control": "no-store" });
}

async function fixedDataReleaseManifest(env, request) {
  if (!env.ASSETS || typeof env.ASSETS.fetch !== "function") {
    throw dataReleaseError("data_release_manifest_missing");
  }
  let response;
  try {
    response = await env.ASSETS.fetch(new Request(
      new URL(DATA_RELEASE_MANIFEST_PATH, request.url),
      { method: "GET" },
    ));
  } catch {
    throw dataReleaseError("data_release_manifest_missing");
  }
  if (!response || !response.ok) throw dataReleaseError("data_release_manifest_missing");

  let manifest;
  try {
    manifest = await response.json();
  } catch {
    throw dataReleaseError("data_release_manifest_invalid");
  }
  if (!manifest || manifest.releaseVersion !== CURRENT_RELEASE_VERSION
      || !manifest.assets || typeof manifest.assets !== "object" || Array.isArray(manifest.assets)) {
    throw dataReleaseError("data_release_manifest_invalid");
  }
  for (const [logicalPath, asset] of Object.entries(manifest.assets)) {
    if (!safeLogicalPath(logicalPath) || !asset || typeof asset !== "object"
        || typeof asset.url !== "string" || !Number.isInteger(asset.byte_size) || asset.byte_size < 0
        || !SHA256_PATTERN.test(String(asset.sha256 || ""))) {
      throw dataReleaseError("data_release_manifest_invalid");
    }
    const match = HF_DATA_ASSET_PATTERN.exec(asset.url);
    const localMatch = LOCAL_DATA_ASSET_PATTERN.exec(asset.url);
    if (match) {
      let decodedPath;
      try { decodedPath = decodeURIComponent(match[3]); } catch { decodedPath = null; }
      if (match[1] !== asset.revision || decodedPath !== logicalPath) {
        throw dataReleaseError("data_release_manifest_invalid");
      }
      if (match[2] === "v0.5.0" && (!((asset.asset_kind === "bigwig" && /^genomes\/experimental-only\/[A-Za-z0-9_.-]+\/studies\/PMID_\d+\/sources\/BATTER_[A-Za-z0-9_]+\/samples\/GSM\d+\/signal\.(plus|minus)\.bw$/.test(logicalPath))
        || (["bed", "gff3", "tbi"].includes(asset.asset_kind) && /^genomes\/experimental-only\/GCF_\d+\.\d+\/predictions\/BATTER-TPE-\d{8}\/prediction\.(bed|gff3\.gz(?:\.tbi)?)$/.test(logicalPath))
        || (["fasta", "fai"].includes(asset.asset_kind) && /^genomes\/experimental-only\/GCF_000005845\.2\/reference\/reference\.fna(?:\.fai)?$/.test(logicalPath))))) {
        throw dataReleaseError("data_release_manifest_invalid");
      }
    } else if (localMatch) {
      let decodedPath;
      try { decodedPath = decodeURIComponent(localMatch[2]); } catch { decodedPath = null; }
      if (decodedPath !== logicalPath || asset.revision != null) {
        throw dataReleaseError("data_release_manifest_invalid");
      }
    } else {
      throw dataReleaseError("data_release_manifest_invalid");
    }
  }
  return manifest;
}

function safeLogicalPath(value) {
  if (typeof value !== "string" || !value || value.startsWith("/") || value.includes("\\")
      || value.includes("?") || value.includes("#") || value.split("/").some((part) => !part || part === "." || part === "..")) {
    return false;
  }
  return true;
}

function allowedAsset(manifest, logicalPath, expectedAsset = null) {
  if (!safeLogicalPath(logicalPath)) throw dataReleaseError("data_release_manifest_invalid");
  const asset = manifest.assets[logicalPath] || registeredConditionAsset(expectedAsset);
  const compatibleKind = !expectedAsset || !asset?.asset_kind
    || asset.asset_kind === expectedAsset.asset_kind
    || (asset.asset_kind === "tsv" && expectedAsset.asset_kind === "metadata");
  if (!asset || (expectedAsset && (
    Number(asset.byte_size) !== Number(expectedAsset.byte_size)
    || String(asset.sha256) !== String(expectedAsset.sha256)
    || !compatibleKind
  ))) {
    throw dataReleaseError("data_release_manifest_invalid");
  }
  return asset;
}

function registeredConditionAsset(asset) {
  if (!asset) return null;
  const path = CONDITION_SIGNAL_PATH.exec(asset.logical_path || "");
  const origin = HF_DATA_ASSET_PATTERN.exec(asset.origin_url || "");
  if (!path || !origin || origin[2] !== "v0.5.0" || origin[3] !== asset.logical_path
      || path[1] !== asset.assembly_accession || path[3] !== asset.source_id
      || asset.asset_kind !== "bigwig" || Number(asset.is_public) !== 1
      || !SHA256_PATTERN.test(asset.sha256) || !Number.isSafeInteger(asset.byte_size) || asset.byte_size <= 0) return null;
  return { url: asset.origin_url, revision: origin[1], byte_size: asset.byte_size, sha256: asset.sha256, asset_kind: "bigwig" };
}

function dataAssetUrl(manifest, logicalPath, request, expectedAsset = null) {
  const asset = allowedAsset(manifest, logicalPath, expectedAsset);
  if (HF_DATA_ASSET_PATTERN.test(asset.url)) return asset.url;
  if (!isLoopbackHost(new URL(request.url).hostname)) {
    throw dataReleaseError("data_release_manifest_invalid");
  }
  return new URL(`/${asset.url}`, request.url).href;
}

async function withRelease(env, url) {
  const release = await currentRelease(env);
  return release ? { release, summary: releasePayload(release) } : null;
}

function assetUrl(request, assetKey, route = "/api/assets/") {
  return new URL(`${route}${encodeURIComponent(assetKey)}`, request.url).href;
}

async function publicAsset(env, releaseVersion, assetKey) {
  return cachedD1Lookup(env.BTED_DB, `asset:${releaseVersion}:${assetKey}`, () => env.BTED_DB.prepare(
    "SELECT asset_key, release_version, assembly_accession, source_id, asset_kind, logical_path, origin_url, origin_host, content_type, byte_size, sha256, supports_range, redistribution_status, is_public FROM assets WHERE asset_key = ? AND release_version = ? AND active = 1 AND is_public = 1",
  ).bind(assetKey, releaseVersion).first());
}

async function allAssets(env, releaseVersion, accession, sourceId) {
  let sql = "SELECT asset_key, release_version, assembly_accession, source_id, asset_kind, logical_path, origin_url, origin_host, content_type, byte_size, sha256, supports_range, redistribution_status, is_public FROM assets WHERE release_version = ? AND active = 1 AND is_public = 1";
  const params = [releaseVersion];
  if (accession) {
    sql += " AND assembly_accession = ?";
    params.push(accession);
  }
  if (sourceId) {
    sql += " AND source_id = ?";
    params.push(sourceId);
  }
  sql += " ORDER BY asset_kind, logical_path";
  const result = await env.BTED_DB.prepare(sql).bind(...params).all();
  return result.results || [];
}

async function sourceAccessions(env, releaseVersion, sourceId) {
  const result = await env.BTED_DB.prepare(
    "SELECT accession_namespace, accession, raw_value, accession_type, ordinal, external_url FROM source_accessions WHERE release_version = ? AND source_id = ? ORDER BY ordinal, accession",
  ).bind(releaseVersion, sourceId).all();
  return result.results || [];
}

async function sourceRow(env, releaseVersion, sourceId) {
  return env.BTED_DB.prepare(
    "SELECT * FROM sources WHERE release_version = ? AND source_id = ?",
  ).bind(releaseVersion, sourceId).first();
}

async function publication(env, pmid) {
  return pmid ? env.BTED_DB.prepare("SELECT * FROM publications WHERE pmid = ?").bind(pmid).first() : null;
}

function publicBrowserAvailable(source, track, assemblyAssets) {
  const endpointTrack = source
    && source.release_status === "published_standardized"
    && Number(source.record_count) > 0
    && track
    && Number(track.is_public) === 1;
  const fasta = assemblyAssets.find((asset) => asset.asset_kind === "fasta" && Number(asset.is_public) === 1);
  const fai = assemblyAssets.find((asset) => asset.asset_kind === "fai" && Number(asset.is_public) === 1);
  return Boolean(endpointTrack && fasta && fai);
}

async function trackRows(env, releaseVersion, accession, sourceId) {
  let sql = "SELECT * FROM tracks WHERE release_version = ?";
  const params = [releaseVersion];
  if (accession) {
    sql += " AND assembly_accession = ?";
    params.push(accession);
  }
  if (sourceId) {
    sql += " AND source_id = ?";
    params.push(sourceId);
  }
  sql += " ORDER BY display_order";
  const result = await env.BTED_DB.prepare(sql).bind(...params).all();
  return result.results || [];
}

async function sourcePayload(request, env, release, sourceId) {
  const source = await sourceRow(env, release.release_version, sourceId);
  if (!source) return null;
  let dataManifest;
  try {
    dataManifest = await fixedDataReleaseManifest(env, request);
  } catch (error) {
    return dataReleaseErrorResponse(error);
  }
  const [paper, accessions, assets, tracks, assemblyAssets] = await Promise.all([
    publication(env, source.publication_pmid),
    sourceAccessions(env, release.release_version, sourceId),
    allAssets(env, release.release_version, null, sourceId),
    trackRows(env, release.release_version, null, sourceId),
    allAssets(env, release.release_version, source.assembly_accession, null),
  ]);
  const browserAvailable = tracks.some((track) => publicBrowserAvailable(source, track, assemblyAssets));
  const studyGff3 = source.record_root
    ? assemblyAssets.find((asset) => asset.logical_path === source.record_root && asset.asset_kind === "gff3")
    : null;
  let gff3Url = null;
  try {
    if (studyGff3 && Number(studyGff3.is_public) === 1) {
      gff3Url = dataAssetUrl(dataManifest, studyGff3.logical_path, request, studyGff3);
    }
  } catch (error) {
    return dataReleaseErrorResponse(error);
  }
  const visibleAssets = studyGff3 && !assets.some((asset) => asset.asset_key === studyGff3.asset_key)
    ? [...assets, studyGff3]
    : assets;
  const publicSource = publicSourceMetadata(source);
  const links = {
    bted_record: `/genomes/${encodeURIComponent(source.assembly_accession)}.html?source_id=${encodeURIComponent(sourceId)}`,
  };
  if (source.release_status === "published_standardized" && Number(source.record_count) > 0) {
    if (gff3Url) links.gff3_download = gff3Url;
    links.endpoint_records = `/api/endpoints?source_id=${encodeURIComponent(sourceId)}`;
    if (browserAvailable) {
      const config = new URL(`/api/assemblies/${encodeURIComponent(source.assembly_accession)}/jbrowse-config`, request.url);
      config.searchParams.set("source_id", sourceId);
      links.jbrowse_config = config.href;
    }
  }
  return {
    release: releasePayload(release),
    source: {
      ...publicSource,
      publication: paper,
      accessions,
      tracks,
      assets: visibleAssets,
      browser_available: browserAvailable,
      links,
      provenance: {
        release_version: release.release_version,
        source_manifest_sha256: source.manifest_sha256,
      },
    },
  };
}

async function sourcesList(request, env, release, url) {
  const paging = pageParams(url);
  if (paging.error) return paging.error;
  const { page, pageSize, offset } = paging;
  const filters = [];
  const params = [release.release_version];
  const exact = [["source_id", "source_id"], ["species", "species"], ["assay_family", "assay_family"], ["release_status", "release_status"], ["evidence_class", "evidence_class"], ["assembly_accession", "assembly_accession"]];
  for (const [queryName, column] of exact) {
    const value = url.searchParams.get(queryName);
    if (value) {
      filters.push(`s.${column} = ?`);
      params.push(value);
    }
  }
  const q = url.searchParams.get("q");
  if (q) {
    filters.push("(s.source_id LIKE ? OR s.species LIKE ? OR s.manifest_path LIKE ? OR p.pmid LIKE ? OR p.paper_title LIKE ?)");
    const pattern = `%${q}%`;
    params.push(pattern, pattern, pattern, pattern, pattern);
  }
  const where = filters.length ? ` AND ${filters.join(" AND ")}` : "";
  const count = await env.BTED_DB.prepare(`SELECT COUNT(*) AS total FROM sources s LEFT JOIN publications p ON p.pmid = s.publication_pmid WHERE s.release_version = ?${where}`).bind(...params).first();
  const rows = await env.BTED_DB.prepare(`SELECT s.*, p.paper_title, p.published_year, p.doi FROM sources s LEFT JOIN publications p ON p.pmid = s.publication_pmid WHERE s.release_version = ?${where} ORDER BY s.source_id LIMIT ? OFFSET ?`).bind(...params, pageSize, offset).all();
  const data = (rows.results || []).map((row) => {
    const publicRow = publicSourceMetadata(row);
    return {
      ...publicRow,
      links: { detail: `/api/sources/${encodeURIComponent(row.source_id)}` },
      provenance: { release_version: release.release_version, source_manifest_sha256: row.manifest_sha256 },
    };
  });
  return json({ release: releasePayload(release), ...pageResult(data, page, pageSize, Number(count?.total || 0)) });
}

async function assemblyPayload(request, env, release, accession) {
  const assembly = await env.BTED_DB.prepare(
    "SELECT * FROM assemblies WHERE release_version = ? AND accession = ?",
  ).bind(release.release_version, accession).first();
  if (!assembly) return null;
  let dataManifest;
  try {
    dataManifest = await fixedDataReleaseManifest(env, request);
  } catch (error) {
    return dataReleaseErrorResponse(error);
  }
  const [contigs, tracks, assets, registeredAssets, endpointCount] = await Promise.all([
    env.BTED_DB.prepare("SELECT contig_accession, contig_name, length_bp, sequence_sha256, provenance_json FROM contigs WHERE release_version = ? AND assembly_accession = ? ORDER BY contig_accession").bind(release.release_version, accession).all(),
    trackRows(env, release.release_version, accession, null),
    allAssets(env, release.release_version, accession, null),
    allAssets(env, release.release_version, null, null),
    env.BTED_DB.prepare("SELECT COUNT(*) AS total FROM endpoints WHERE release_version = ? AND reference_assembly = ?").bind(release.release_version, accession).first(),
  ]);
  const trackData = [];
  for (const track of tracks) {
    const source = await sourceRow(env, release.release_version, track.source_id);
    const sourceGff3 = registeredAssets.find((asset) => asset.asset_key === track.asset_key && asset.asset_kind === "gff3")
      || (source?.record_root
      ? registeredAssets.find((asset) => asset.logical_path === source.record_root && asset.asset_kind === "gff3")
      : null);
    let gff3Url = null;
    try {
      if (sourceGff3 && Number(sourceGff3.is_public) === 1) {
        gff3Url = dataAssetUrl(dataManifest, sourceGff3.logical_path, request, sourceGff3);
      }
    } catch (error) {
      return dataReleaseErrorResponse(error);
    }
    trackData.push({
      ...track,
      source_status: source?.release_status,
      browser_available: publicBrowserAvailable(source, track, assets),
      gff3_url: gff3Url,
      links: { source: `/api/sources/${encodeURIComponent(track.source_id)}` },
    });
  }
  const browserAvailable = trackData.some((track) => track.browser_available) || Number(assembly.prediction_count) > 0 && assets.some(a => a.asset_kind === "fasta") && assets.some(a => a.asset_kind === "fai");
  return {
    release: releasePayload(release),
    assembly: {
      ...assembly,
      contigs: contigs.results || [],
      tracks: trackData,
      assets,
      endpoint_count: Number(endpointCount?.total || 0),
      browser_available: browserAvailable,
      gff3_url: null,
      metadata_url: dataAssetUrl(dataManifest, `genomes/${accession}/metadata.tsv`, request),
      links: {
        catalogue: `/api/catalogue?assembly_accession=${encodeURIComponent(accession)}`,
        ...(browserAvailable ? { jbrowse_config: new URL(`/api/assemblies/${encodeURIComponent(accession)}/jbrowse-config`, request.url).href } : {}),
      },
      provenance: { release_version: release.release_version },
    },
  };
}

async function assembliesList(env, release, url) {
  const paging = pageParams(url);
  if (paging.error) return paging.error;
  const { page, pageSize, offset } = paging;
  const filters = [];
  const params = [release.release_version];
  const accession = url.searchParams.get("assembly_accession");
  const species = url.searchParams.get("species");
  const q = url.searchParams.get("q");
  if (accession) { filters.push("a.accession = ?"); params.push(accession); }
  if (species) { filters.push("a.organism_name = ?"); params.push(species); }
  if (q) { filters.push("(a.accession LIKE ? OR a.organism_name LIKE ? OR a.strain LIKE ?)"); const p = `%${q}%`; params.push(p, p, p); }
  const where = filters.length ? ` AND ${filters.join(" AND ")}` : "";
  const count = await env.BTED_DB.prepare(`SELECT COUNT(*) AS total FROM assemblies a WHERE a.release_version = ?${where}`).bind(...params).first();
  const rows = await env.BTED_DB.prepare(`SELECT a.*, (SELECT COUNT(*) FROM sources s WHERE s.release_version = a.release_version AND s.assembly_accession = a.accession) AS source_count, (SELECT COUNT(*) FROM endpoints e WHERE e.release_version = a.release_version AND e.reference_assembly = a.accession) AS endpoint_count, (SELECT COUNT(*) FROM assets x WHERE x.release_version = a.release_version AND x.assembly_accession = a.accession AND x.asset_kind = 'fasta' AND x.is_public = 1) AS public_fasta_count FROM assemblies a WHERE a.release_version = ?${where} ORDER BY a.accession LIMIT ? OFFSET ?`).bind(...params, pageSize, offset).all();
  const data = (rows.results || []).map((row) => ({ ...row, browser_candidate: Number(row.public_fasta_count) > 0, provenance: { release_version: release.release_version } }));
  return json({ release: releasePayload(release), ...pageResult(data, page, pageSize, Number(count?.total || 0)) });
}

function endpointFilters(url) {
  const filters = [];
  const params = [];
  const sources = url.searchParams.getAll("source_id");
  if (sources.length) { filters.push(`e.source_id IN (${sources.map(() => "?").join(",")})`); params.push(...sources); }
  for (const [name, column] of [["assembly_accession", "reference_assembly"], ["contig_accession", "reference_name"], ["sample_id", "sample_id"], ["strand", "strand"], ["evidence_class", "evidence_class"]]) {
    const value = url.searchParams.get(name);
    if (value) { if (name === "evidence_class" && !PUBLIC_EVIDENCE.has(value)) return { error: bad("invalid_filter", `${value} is not a public endpoint evidence class`, name) }; if (name === "strand" && !["+", "-"].includes(value)) return { error: bad("invalid_filter", "strand must be + or -", name) }; filters.push(`e.${column} = ?`); params.push(value); }
  }
  for (const [name, operator] of [["position_min", ">="], ["position_max", "<="]]) {
    const value = url.searchParams.get(name);
    if (value !== null) { const n = Number(value); if (!Number.isInteger(n) || n < 1) return { error: bad("invalid_filter", `${name} must be a positive integer`, name) }; filters.push(`e.biological_coordinate_1based ${operator} ?`); params.push(n); }
  }
  const locus = url.searchParams.get("gene_or_locus");
  if (locus) { filters.push("e.associated_gene_or_locus = ?"); params.push(locus); }
  const q = url.searchParams.get("q");
  if (q) { filters.push("(e.end_id LIKE ? OR e.author_endpoint_id LIKE ? OR e.original_row_reference LIKE ?)"); const p = `%${q}%`; params.push(p, p, p); }
  return { sql: filters.length ? ` AND ${filters.join(" AND ")}` : "", params };
}

async function endpointsList(env, release, url) {
  const paging = pageParams(url);
  if (paging.error) return paging.error;
  const filter = endpointFilters(url);
  if (filter.error) return filter.error;
  const { page, pageSize, offset } = paging;
  const count = await env.BTED_DB.prepare(`SELECT COUNT(*) AS total FROM endpoints e WHERE e.release_version = ?${filter.sql}`).bind(release.release_version, ...filter.params).first();
  const order = url.searchParams.get("sort") || "end_id";
  const orderMap = { end_id: "e.end_id", position: "e.biological_coordinate_1based", source_id: "e.source_id", contig_accession: "e.reference_name" };
  if (!Object.prototype.hasOwnProperty.call(orderMap, order)) return bad("invalid_sort", `unsupported endpoint sort: ${order}`, "sort");
  const direction = url.searchParams.get("order") === "desc" ? "DESC" : "ASC";
  const rows = await env.BTED_DB.prepare(`SELECT e.* FROM endpoints e WHERE e.release_version = ?${filter.sql} ORDER BY ${orderMap[order]} ${direction}, e.end_id ASC LIMIT ? OFFSET ?`).bind(release.release_version, ...filter.params, pageSize, offset).all();
  const data = rows.results || [];
  return json({ release: releasePayload(release), ...pageResult(data, page, pageSize, Number(count?.total || 0)) });
}

async function catalogue(env, release, url) {
  const [stats, assemblies] = await Promise.all([
    statsPayload(env, release),
    assembliesList(env, release, url),
  ]);
  const assemblyJson = await assemblies.json();
  return json({ release: releasePayload(release), stats, assemblies: assemblyJson });
}

async function statsPayload(env, release) {
  const [sources, endpoints, assemblies, evidence] = await Promise.all([
    env.BTED_DB.prepare("SELECT release_status, COUNT(*) AS total FROM sources WHERE release_version = ? GROUP BY release_status").bind(release.release_version).all(),
    env.BTED_DB.prepare("SELECT COUNT(*) AS total FROM endpoints WHERE release_version = ?").bind(release.release_version).first(),
    env.BTED_DB.prepare("SELECT COUNT(*) AS total FROM assemblies WHERE release_version = ?").bind(release.release_version).first(),
    env.BTED_DB.prepare("SELECT evidence_class, COUNT(*) AS total FROM endpoints WHERE release_version = ? GROUP BY evidence_class ORDER BY evidence_class").bind(release.release_version).all(),
  ]);
  const sourceCounts = Object.fromEntries((sources.results || []).map((row) => [row.release_status, Number(row.total)]));
  return {
    sources: { total: Object.values(sourceCounts).reduce((sum, value) => sum + value, 0), published_standardized: sourceCounts.published_standardized || 0, audit_only: sourceCounts.audit_only || 0 },
    endpoints: { total: Number(endpoints?.total || 0), by_evidence_class: Object.fromEntries((evidence.results || []).map((row) => [row.evidence_class, Number(row.total)])) },
    assemblies: { total: Number(assemblies?.total || 0) },
  };
}

async function stats(env, release) {
  return json({ release: releasePayload(release), ...(await statsPayload(env, release)) });
}

async function endpointDetail(env, release, endId) {
  const row = await env.BTED_DB.prepare("SELECT * FROM endpoints WHERE release_version = ? AND end_id = ?").bind(release.release_version, endId).first();
  return row ? json({ release: releasePayload(release), endpoint: { ...row, provenance: { release_version: release.release_version, source_id: row.source_id, contig_accession: row.reference_name } } }) : json({ error: "endpoint_not_found", end_id: endId }, 404);
}

function experimentalPredictionTrack(request, manifest, assembly, assets, assemblyName, fasta) {
  if (!Number(assembly.prediction_count)) return null;
  if (!/^BATTER-TPE-\d{8}$/.test(assembly.prediction_run || "") || !/^[0-9a-f]{40}$/.test(assembly.prediction_revision || "")
      || assembly.prediction_reference_sha256 !== fasta.sha256) throw dataReleaseError("prediction_reference_mismatch");
  const counts = JSON.parse(assembly.prediction_contig_counts_json || "{}");
  if (Object.values(counts).some(n => !Number.isSafeInteger(n) || n < 1) || Object.values(counts).reduce((a,b) => a+b, 0) !== Number(assembly.prediction_count)) throw dataReleaseError("prediction_count_mismatch");
  const root = `genomes/experimental-only/${assembly.accession}/predictions/${assembly.prediction_run}/`;
  const uri = name => {
    const asset = assets.find(a => a.logical_path === root + name && Number(a.is_public) === 1);
    const registered = manifest.assets[root + name];
    if (!asset || registered?.revision !== assembly.prediction_revision) throw dataReleaseError("prediction_asset_mismatch");
    return { uri: dataAssetUrl(manifest, root + name, request, asset), locationType: "UriLocation" };
  };
  const id = "bted_experimental_prediction";
  return { type: "FeatureTrack", trackId: id, name: "Predicted regions", category: ["Model prediction"], assemblyNames: [assemblyName],
    adapter: { type: "Gff3TabixAdapter", gffGzLocation: uri("prediction.gff3.gz"), index: { location: uri("prediction.gff3.gz.tbi"), indexType: "TBI" } },
    displays: [{ type: "LinearBasicDisplay", displayId: id + "_display", height: 160, showLabels: false,
      renderer: { type: "SvgFeatureRenderer", showLabels: false, height: 14, color1: "jexl:btedStrandColor(feature)", color2: "jexl:btedStrandColor(feature)", mouseover: "jexl:btedPredictionTooltip(feature)" } }],
    metadata: { evidence_class: "model_prediction", btedContigCounts: counts,
      btedAbout: { kind: "prediction", assembly: assembly.accession, evidence: "Model prediction", record_count: Number(assembly.prediction_count), assay: "BATTER-TPE",
        reference: assembly.organism_name, reference_url: `https://www.ncbi.nlm.nih.gov/datasets/genome/${assembly.accession}/` },
      btedDownloads: ["prediction.bed", "prediction.gff3.gz"].map(name => ({ kind: "prediction", label: name.endsWith(".bed") ? "Prediction BED" : "Prediction GFF3", url: uri(name).uri, filename: `${assembly.accession}.${name}` })) } };
}

async function applyConditionSignals(config, request, env, accession, rows = null) {
  rows ||= await trackRows(env, CURRENT_RELEASE_VERSION, accession, null);
  for (const row of rows) {
    const info = JSON.parse(row.metadata_json || "{}");
    const conditions = info.signal_conditions;
    if (!conditions?.length || Number(row.is_public) !== 1) continue;
    if (row.assembly_accession !== accession || !Array.isArray(conditions)) throw dataReleaseError("signal_condition_mismatch");
    const endpoint = config.tracks.find(t => t.metadata?.btedAbout?.kind === "endpoint"
      && [t.metadata?.source_id, ...(t.metadata?.source_ids || []), t.metadata?.btedAbout?.source_id].includes(row.source_id));
    if (!endpoint || String(endpoint.metadata.btedAbout.pmid) !== row.pmid) throw dataReleaseError("signal_condition_mismatch");
    const assets = await allAssets(env, CURRENT_RELEASE_VERSION, accession, row.source_id);
    const groups = [], ids = new Set(), aliasLines = new Set();
    for (const condition of conditions) {
      const id = condition.condition_id;
      const reference = condition.reference;
      if (!/^[A-Za-z0-9_-]+$/.test(id) || ids.has(id) || condition.aggregation !== "arithmetic_mean"
          || condition.biological_replicates !== 3 || condition.signals?.length !== 2
          || new Set(condition.signals.map(s => s.strand)).size !== 2
          || reference?.browser_status !== "sequence_verified_aliases" || !Object.keys(reference.aliases || {}).length) {
        throw dataReleaseError("signal_condition_mismatch");
      }
      ids.add(id);
      for (const [canonical, alias] of Object.entries(reference.aliases)) {
        if (!/^[A-Za-z0-9_.-]+$/.test(canonical) || !/^[A-Za-z0-9_.-]+$/.test(alias)
            || !reference.contigs[alias] || !SHA256_PATTERN.test(reference.sequence_sha256?.[canonical] || "")) throw dataReleaseError("signal_reference_mismatch");
        aliasLines.add(`${canonical}\t${alias}`);
      }
      const root = `genomes/experimental-only/${accession}/studies/PMID_${row.pmid}/sources/${row.source_id}/conditions/${id}/mean3/`;
      const signals = ["plus", "minus"].map(strand => {
        const declared = condition.signals.find(s => s.strand === strand);
        const asset = assets.find(a => a.logical_path === `${root}signal.${strand}.bw` && a.asset_key === declared?.asset_key);
        const fixed = registeredConditionAsset(asset);
        if (!fixed || declared.path !== `v0.5.0/${asset.logical_path}` || declared.url !== fixed.url
            || declared.sha256 !== fixed.sha256 || declared.byte_size !== fixed.byte_size) throw dataReleaseError("signal_pair_missing");
        return { strand, url: fixed.url, fallback: assetUrl(request, asset.asset_key) };
      });
      const trackId = `bted_${row.source_id.toLowerCase()}_${id.toLowerCase()}_mean3_signal`;
      const about = { ...endpoint.metadata.btedAbout, kind: "signal", record_count: "", evidence: "",
        assay: condition.assay, conditions: condition.conditions, strand: "+ / −", coverage: "22 reference sequences",
        reference_name: Object.keys(reference.aliases).join(", "),
        raw_data_accessions: condition.samples.map(s => s.accession).join(", "),
        raw_data_url: `https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=${condition.series_accession}`,
        explanation: "Mean of 3 biological replicates; + strand above zero, − strand below." };
      delete about.gff3_url;
      groups.push({ type: "MultiQuantitativeTrack", trackId,
        name: `PMID ${row.pmid} · 3′ RNA-seq · ${condition.label}`,
        category: ["Experimental signal", `PMID ${row.pmid}`], assemblyNames: endpoint.assemblyNames,
        adapter: { type: "MultiWiggleAdapter", subadapters: signals.map(s => ({ type: "BigWigAdapter", source: s.strand,
          name: s.strand === "plus" ? "+ strand" : "− strand", color: s.strand === "plus" ? PLUS_STRAND_COLOR : MINUS_STRAND_COLOR,
          bigWigLocation: { uri: s.url, locationType: "UriLocation" } })) },
        metadata: { btedMirroredSignal: true, btedConditionSignal: true, condition_id: id, source_id: row.source_id,
          signal_values: condition.units, btedAbout: about,
          btedDownloads: signals.map(s => ({ kind: "bigwig", label: s.strand === "plus" ? "+ strand BigWig" : "− strand BigWig",
            url: s.url, filename: `${row.source_id}.${id}.mean3.${s.strand}.bw` })) },
        displays: [{ type: "MultiLinearWiggleDisplay", displayId: `${trackId}_display`, defaultRendering: "xyplot", autoscale: "global", scaleType: "log", height: 180 }] });
    }
    const assembly = config.assemblies.find(a => endpoint.assemblyNames.includes(a.name));
    const previousAliases = assembly.refNameAliases?.adapter?.location?.uri;
    const existing = previousAliases?.startsWith("data:text/plain,") ? decodeURIComponent(previousAliases.slice(16)).trim() : "";
    const aliases = [...new Set([...existing.split("\n"), ...aliasLines].filter(Boolean))];
    assembly.refNameAliases = { adapter: { type: "RefNameAliasAdapter", location: { uri: "data:text/plain," + encodeURIComponent(aliases.join("\n") + "\n"), locationType: "UriLocation" } } };
    config.tracks = config.tracks.filter(t => !(t.metadata?.btedConditionSignal && t.metadata.source_id === row.source_id));
    config.tracks.splice(config.tracks.indexOf(endpoint) + 1, 0, ...groups);
    for (const view of config.defaultSession.views) {
      const groupIds = new Set(groups.map(t => t.trackId));
      view.tracks = view.tracks.filter(t => !groupIds.has(t.configuration));
      const index = view.tracks.findIndex(t => t.configuration === endpoint.trackId);
      if (index >= 0) view.tracks.splice(index + 1, 0, ...groups.map(t => ({ id: `${t.trackId}_view`, type: t.type, configuration: t.trackId,
        displays: [{ id: `${t.trackId}_display_view`, type: "MultiLinearWiggleDisplay", configuration: t.displays[0].displayId, showSidebar: false }] })));
    }
  }
  return config;
}

async function experimentalBrowserConfig(request, env, accession) {
  const response = await env.ASSETS.fetch(new Request(new URL(`/jbrowse/assemblies/${accession}.config.json`, request.url)));
  if (!response.ok) return response;
  try {
    return json(await applyConditionSignals(await response.json(), request, env, accession), 200, { "cache-control": "no-cache" });
  } catch (error) { return dataReleaseErrorResponse(error); }
}

async function jbrowseConfig(request, env, release, accession, sourceId) {
  let dataManifest;
  try {
    dataManifest = await fixedDataReleaseManifest(env, request);
  } catch (error) {
    return dataReleaseErrorResponse(error);
  }
  const assembly = await env.BTED_DB.prepare("SELECT * FROM assemblies WHERE release_version = ? AND accession = ?").bind(release.release_version, accession).first();
  if (!assembly) return json({ error: "assembly_not_found", accession }, 404);
  const [assemblyAssets, tracks] = await Promise.all([
    allAssets(env, release.release_version, accession, null),
    trackRows(env, release.release_version, accession, sourceId),
  ]);
  const fasta = assemblyAssets.find((asset) => asset.asset_kind === "fasta" && Number(asset.is_public) === 1);
  const fai = assemblyAssets.find((asset) => asset.asset_kind === "fai" && Number(asset.is_public) === 1);
  if (!fasta || !fai) return json({ error: "jbrowse_unavailable", reason: "public FASTA+FAI are not registered for this assembly" }, 404);
  const publicTracks = [];
  for (const track of tracks) {
    const source = await sourceRow(env, release.release_version, track.source_id);
    if (!source || source.release_status !== "published_standardized" || Number(track.is_public) !== 1) continue;
    const sourceAssets = await allAssets(env, release.release_version, null, source.source_id);
    const endpointGff3 = assemblyAssets.find((asset) => asset.asset_key === track.asset_key
      && asset.asset_kind === "gff3" && Number(asset.is_public) === 1)
      || assemblyAssets.find((asset) => asset.asset_kind === "gff3"
        && Number(asset.is_public) === 1 && asset.logical_path === source.record_root);
    publicTracks.push({ track, source, sourceAssets, endpointGff3 });
  }
  if (!publicTracks.length && !Number(assembly.prediction_count)) return json({ error: "jbrowse_unavailable", reason: "no public published endpoint track" }, 404);
  const assemblyName = `BTED_${accession.replaceAll(".", "_")}`;
  const gff = assemblyAssets.find((asset) => asset.asset_kind === "gff3"
    && asset.logical_path.startsWith(`assemblies/${accession}/reference/`)
    && Number(asset.is_public) === 1);
  const tbi = assemblyAssets.find((asset) => asset.asset_kind === "tbi" && asset.logical_path === gff?.logical_path + ".tbi" && Number(asset.is_public) === 1);
  const browserGff = assemblyAssets.find((asset) => asset.asset_kind === "gff3"
    && asset.logical_path === `browser/${accession}/annotation.gff3`
    && Number(asset.is_public) === 1);
  const contig = await env.BTED_DB.prepare("SELECT contig_accession, length_bp FROM contigs WHERE release_version = ? AND assembly_accession = ? ORDER BY length_bp DESC, contig_accession ASC LIMIT 1").bind(release.release_version, accession).first();
  if (!contig) return json({ error: "jbrowse_unavailable", reason: "reference sequences are not registered for this assembly" }, 404);
  const endpointCounts = await env.BTED_DB.prepare("SELECT source_id, reference_name, COUNT(*) AS record_count FROM endpoints WHERE release_version = ? AND reference_assembly = ? GROUP BY source_id, reference_name").bind(release.release_version, accession).all();
  const contigName = contig.contig_accession;
  const length = Number(contig.length_bp);
  const firstEndpoint = await env.BTED_DB.prepare("SELECT biological_coordinate_1based FROM endpoints WHERE release_version = ? AND reference_assembly = ? AND reference_name = ? ORDER BY biological_coordinate_1based, end_id LIMIT 1").bind(release.release_version, accession, contigName).first();
  const initialStart = firstEndpoint ? Math.max(0, Number(firstEndpoint.biological_coordinate_1based) - 501) : 0;
  const initialEnd = Math.min(length, initialStart + (firstEndpoint ? 1000 : 10000));
  const initialBpPerPx = Math.max(0.001, (initialEnd - initialStart) / 1000);
  const tracksConfig = [];
  const signalTracks = new Map();
  const endpointTracks = new Map();
  for (const { track, source, sourceAssets, endpointGff3 } of publicTracks) {
    const rawAccessions = JSON.parse(track.raw_accessions_json || "[]");
    const { citation, limitations } = trackCitation(track);
    let endpointGff3Url = null;
    try {
      if (endpointGff3) {
        endpointGff3Url = dataAssetUrl(dataManifest, endpointGff3.logical_path, request, endpointGff3);
        const grouped = endpointTracks.get(endpointGff3.logical_path) || [];
        grouped.push({ track, source, rawAccessions, endpointGff3, endpointGff3Url });
        endpointTracks.set(endpointGff3.logical_path, grouped);
      }
    } catch (error) {
      return dataReleaseErrorResponse(error);
    }
    const metadata = {
      source_id: source.source_id,
      evidence_class: source.evidence_class,
      record_count: source.record_count,
      publication_title: track.paper_title,
      PubMed: track.pmid ? `https://pubmed.ncbi.nlm.nih.gov/${track.pmid}/` : null,
      DOI: track.doi ? `https://doi.org/${track.doi}` : null,
      raw_data_accessions: rawAccessions.map((item) => item.accession).join(", "),
      raw_data_links: rawAccessions.map((item) => item.external_url).filter(Boolean).join(" ; "),
      BTED_record: new URL(`/genomes/${encodeURIComponent(accession)}.html?source_id=${encodeURIComponent(source.source_id)}`, request.url).href,
      GFF3_download: endpointGff3Url,
      release_version: release.release_version,
      btedAbout: {
        kind: "endpoint", source_id: source.source_id, assembly: accession,
        title: citation.paper_title || track.paper_title, authors: citation.authors || "",
        journal: citation.journal || track.journal || "", year: citation.published_year || track.publication_year || "",
        pmid: track.pmid || "", pubmed_url: citation.pubmed_url || (track.pmid ? `https://pubmed.ncbi.nlm.nih.gov/${track.pmid}/` : ""),
        doi_url: track.doi ? `https://doi.org/${track.doi}` : "",
        assay: track.assay || source.assay_family || "", record_count: source.record_count,
        evidence: source.evidence_class === "author_called_endpoint"
          ? "Author-reported 3′ end"
          : "Literature-curated 3′ end",
        limitations,
        raw_data_accessions: rawAccessions.map((item) => item.accession).join(", "),
        raw_data_url: rawAccessions.map((item) => item.external_url).find(Boolean) || "",
        gff3_url: source.record_root ? dataAssetUrl(dataManifest, source.record_root, request) : "",
        explanation: "Study records counted separately.",
      },
    };
    if (endpointGff3) {
      const grouped = endpointTracks.get(endpointGff3.logical_path);
      grouped[grouped.length - 1].about = metadata.btedAbout;
    }
    const sample = JSON.parse(track.metadata_json || "{}").signal_sample;
    if (sample && (sample.genome_id !== accession || sample.pmid !== track.pmid || !/^GSM\d+$/.test(sample.sample_id))) {
      return json({ error: "signal_sample_mismatch" }, 503);
    }
    const sampleRoot = sample ? `genomes/experimental-only/${accession}/studies/PMID_${track.pmid}/sources/${source.source_id}/samples/${sample.sample_id}/` : "";
    const signalPlus = sourceAssets.find((asset) => asset.asset_kind === "bigwig" && (sample ? asset.logical_path === `${sampleRoot}signal.plus.bw` : asset.logical_path.endsWith("signal.forward.bw")) && Number(asset.is_public) === 1);
    const signalMinus = sourceAssets.find((asset) => asset.asset_kind === "bigwig" && (sample ? asset.logical_path === `${sampleRoot}signal.minus.bw` : asset.logical_path.endsWith("signal.reverse.bw")) && Number(asset.is_public) === 1);
    if (sample && (!signalPlus || !signalMinus)) return json({ error: "signal_pair_missing" }, 503);
    if (signalPlus && signalMinus) {
      const signalId = sample ? `bted_${sample.sample_id.toLowerCase()}_mirrored_signal` : `${track.track_id}_mirrored_signal`;
      let plusUrl, minusUrl;
      try {
        plusUrl = sample ? dataAssetUrl(dataManifest, signalPlus.logical_path, request, signalPlus) : assetUrl(request, signalPlus.asset_key);
        minusUrl = sample ? dataAssetUrl(dataManifest, signalMinus.logical_path, request, signalMinus) : assetUrl(request, signalMinus.asset_key);
      } catch (error) { return dataReleaseErrorResponse(error); }
      signalTracks.set(source.source_id, {
        type: "MultiQuantitativeTrack",
        trackId: signalId,
        name: sample ? `PMID ${track.pmid} · ${sample.assay} · ${sample.conditions.split(';')[0].trim()} · ${sample.sample_id}` : `PMID ${track.pmid} · experimental signal`,
        adapter: { type: "MultiWiggleAdapter", subadapters: [
          { type: "BigWigAdapter", source: "plus", name: "+ strand", color: PLUS_STRAND_COLOR, bigWigLocation: { uri: plusUrl, locationType: "UriLocation" } },
          { type: "BigWigAdapter", source: "minus", name: "− strand", color: MINUS_STRAND_COLOR, bigWigLocation: { uri: minusUrl, locationType: "UriLocation" } },
        ] },
        category: ["Experimental signal", `PMID ${track.pmid}`],
        assemblyNames: [assemblyName],
        metadata: {
          ...metadata, signal_values: "Raw BigWig values; mirrored only for display", strand: "+ / −", btedMirroredSignal: true,
          btedDownloads: [
            { kind: "bigwig", label: "+ strand BigWig", url: plusUrl, filename: `${sample?.sample_id || source.source_id}.signal.plus.bw` },
            { kind: "bigwig", label: "− strand BigWig", url: minusUrl, filename: `${sample?.sample_id || source.source_id}.signal.minus.bw` },
          ],
          btedAbout: {
            ...metadata.btedAbout, kind: "signal", strand: "+ / −",
            record_count: "",
            ...(sample ? { sample_id: sample.sample_id, conditions: sample.conditions, coverage: sample.coverage,
              reference_name: Object.keys(sample.reference_contigs).join(", "), assay: sample.assay,
              raw_data_accessions: sample.sample_id, raw_data_url: `https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=${sample.sample_id}` } : {}),
            explanation: "+ strand above zero; − strand below.",
          },
        },
        displays: [{
          type: "MultiLinearWiggleDisplay", displayId: `${signalId}_display`, defaultRendering: "xyplot", autoscale: "global", scaleType: "log", height: 180,
        }],
      });
    }
  }
  for (const [logicalPath, studyTracks] of endpointTracks) {
    const first = studyTracks[0];
    const sourceIds = studyTracks.map(({ source: sourceItem }) => sourceItem.source_id);
    const publicationTitles = [...new Set(studyTracks.map(({ track: trackItem }) => trackItem.paper_title).filter(Boolean))];
    const pmids = [...new Set(studyTracks.map(({ track: trackItem }) => trackItem.pmid).filter(Boolean))];
    const rawAccessions = [...new Set(studyTracks.flatMap(({ rawAccessions: values }) => values.map((item) => item.accession).filter(Boolean)))];
    const endpointTrackId = `source_${sourceIds[0].replace(/[^A-Za-z0-9_]/g, "_")}_endpoints`;
    const evidenceClasses = [...new Set(studyTracks.map(({ source: sourceItem }) => sourceItem.evidence_class).filter(Boolean))];
    const contigCounts = {};
    for (const row of endpointCounts.results || []) {
      if (sourceIds.includes(row.source_id)) contigCounts[row.reference_name] = (contigCounts[row.reference_name] || 0) + Number(row.record_count);
    }
    const totalRecords = studyTracks.reduce((sum, { source: item }) => sum + Number(item.record_count || 0), 0);
    const metadata = {
      btedContigCounts: Object.values(contigCounts).reduce((sum, count) => sum + count, 0) === totalRecords ? contigCounts : null,
      source_ids: sourceIds,
      evidence_class: evidenceClasses.length === 1 ? evidenceClasses[0] : evidenceClasses.join(", "),
      record_count: studyTracks.reduce((sum, { source: sourceItem }) => sum + Number(sourceItem.record_count || 0), 0),
      publication_title: publicationTitles.join("; "),
      PubMed: pmids.map((pmid) => `https://pubmed.ncbi.nlm.nih.gov/${pmid}/`).join(" ; "),
      DOI: [...new Set(studyTracks.map(({ track: trackItem }) => trackItem.doi).filter(Boolean))].map((doi) => `https://doi.org/${doi}`).join(" ; "),
      raw_data_accessions: rawAccessions.join(", "),
      raw_data_links: [...new Set(studyTracks.flatMap(({ rawAccessions: values }) => values.map((item) => item.external_url).filter(Boolean)))].join(" ; "),
      GFF3_download: dataAssetUrl(dataManifest, first.source.record_root, request),
      release_version: release.release_version,
      logical_path: logicalPath,
      btedAbout: { ...first.about, record_count: studyTracks.reduce((sum, { source: item }) => sum + Number(item.record_count || 0), 0), gff3_url: dataAssetUrl(dataManifest, first.source.record_root, request) },
      btedDownloads: [{ kind: "endpoint", label: "3′ end GFF3", url: first.endpointGff3Url, filename: `${sourceIds[0]}.endpoints.gff3`, source_id: sourceIds[0] }],
    };
    tracksConfig.push({
      type: "FeatureTrack",
      trackId: endpointTrackId,
      name: `PMID ${pmids.join(", ")} · 3′ ends`,
      adapter: { type: "Gff3Adapter", gffLocation: { uri: first.endpointGff3Url, locationType: "UriLocation" } },
      category: ["Experimental 3′ ends", ...pmids.map(pmid => `PMID ${pmid}`)],
      assemblyNames: [assemblyName],
      metadata,
      displays: [{
        type: "LinearBasicDisplay", displayId: `${endpointTrackId}_display`, showLabels: false, height: 140,
        renderer: { type: "SvgFeatureRenderer", color1: "jexl:btedStrandColor(feature)", color2: "jexl:btedStrandColor(feature)", height: 14, showLabels: false },
      }],
    });
    for (const sourceId of sourceIds) {
      const signal = signalTracks.get(sourceId);
      if (signal) tracksConfig.push(signal);
    }
  }
  const configTracks = [];
  if (gff && tbi) {
    configTracks.push({
      type: "FeatureTrack",
      trackId: `${assemblyName}_genes`,
      name: "Reference gene annotation",
      adapter: { type: "Gff3TabixAdapter", gffGzLocation: { uri: assetUrl(request, gff.asset_key), locationType: "UriLocation" }, index: { location: { uri: assetUrl(request, tbi.asset_key), locationType: "UriLocation" }, indexType: "TBI" } },
      displays: [{ type: "LinearBasicDisplay", displayId: `${assemblyName}_genes-LinearBasicDisplay`, height: 130, jexlFilters: ["get(feature,'type')!='region'"], renderer: { type: "SvgFeatureRenderer", showDescriptions: false, color1: "jexl:btedStrandColor(feature)", color2: "jexl:btedStrandColor(feature)" } }],
      category: ["Reference annotation"],
      assemblyNames: [assemblyName],
      metadata: {
        release_version: release.release_version, gff3_sha256: gff.sha256, tbi_sha256: tbi.sha256,
        btedDownloads: [{ kind: "reference", label: "Reference annotation GFF3", url: assetUrl(request, gff.asset_key), filename: `${accession}.genes.gff3.gz` }],
        btedAbout: {
          kind: "reference", assembly: accession,
          reference: `${assembly.display_name || assembly.organism_name} · ${accession}`,
          reference_name: contigName,
          reference_url: `https://www.ncbi.nlm.nih.gov/datasets/genome/${encodeURIComponent(accession)}/`,
          explanation: "NCBI gene annotation.",
        },
      },
    });
  } else if (browserGff) {
    configTracks.push({
      type: "FeatureTrack",
      trackId: `${assemblyName}_genes`,
      name: "Reference gene annotation",
      adapter: { type: "Gff3Adapter", gffLocation: { uri: assetUrl(request, browserGff.asset_key), locationType: "UriLocation" } },
      displays: [{ type: "LinearBasicDisplay", displayId: `${assemblyName}_genes-LinearBasicDisplay`, height: 130, jexlFilters: ["get(feature,'type')!='region'"], renderer: { type: "SvgFeatureRenderer", showDescriptions: false, color1: "jexl:btedStrandColor(feature)", color2: "jexl:btedStrandColor(feature)" } }],
      category: ["Reference annotation"],
      assemblyNames: [assemblyName],
      metadata: {
        release_version: release.release_version, gff3_sha256: browserGff.sha256,
        btedDownloads: [{ kind: "reference", label: "Reference annotation GFF3", url: assetUrl(request, browserGff.asset_key), filename: `${accession}.genes.gff3` }],
        btedAbout: {
          kind: "reference", assembly: accession,
          reference: `${assembly.display_name || assembly.organism_name} · ${accession}`,
          reference_name: contigName,
          reference_url: `https://www.ncbi.nlm.nih.gov/datasets/genome/${encodeURIComponent(accession)}/`,
          explanation: "NCBI gene annotation.",
        },
      },
    });
  }
  configTracks.push(...tracksConfig);
  try {
    const prediction = experimentalPredictionTrack(request, dataManifest, assembly, assemblyAssets, assemblyName, fasta);
    if (prediction) configTracks.push(prediction);
  } catch (error) { return dataReleaseErrorResponse(error); }
  const sessionTracks = configTracks.map((track, index) => ({
    id: `bted_track_${index + 1}`,
    type: track.type,
    configuration: track.trackId,
    minimized: false,
    displays: [{
      id: `bted_display_${index + 1}`,
      type: track.type === "MultiQuantitativeTrack" ? "MultiLinearWiggleDisplay" : "LinearBasicDisplay",
      configuration: track.displays?.[0]?.displayId || `${track.trackId}-LinearBasicDisplay`,
      ...(track.type === "MultiQuantitativeTrack" ? { showSidebar: false } : {}),
    }],
  }));
  sessionTracks.unshift({
    id: "bted_reference_track", type: "ReferenceSequenceTrack", configuration: `${assemblyName}_refseq`, minimized: false,
    displays: [{ id: "bted_reference_display", type: "LinearReferenceSequenceDisplay", configuration: `${assemblyName}_refseq-LinearReferenceSequenceDisplay`, showTranslation: true, heightPreConfig: 120 }],
  });
  const config = {
    plugins: [{ name: "BTEDTrackPlugin", esmUrl: new URL(BTED_PLUGIN_PATH, request.url).href }],
    assemblies: [{ name: assemblyName, displayName: `${assembly.display_name || assembly.organism_name} (${accession})`, sequence: { type: "ReferenceSequenceTrack", name: "Reference sequence", trackId: `${assemblyName}_refseq`, adapter: { type: "IndexedFastaAdapter", fastaLocation: { uri: assetUrl(request, fasta.asset_key), locationType: "UriLocation" }, faiLocation: { uri: assetUrl(request, fai.asset_key), locationType: "UriLocation" } } } }],
    tracks: configTracks,
    defaultSession: { name: `BTED · ${accession}`, views: [{ id: "bted_linear_genome_view", type: "LinearGenomeView", name: assembly.organism_name || accession, offsetPx: initialStart / initialBpPerPx, bpPerPx: initialBpPerPx, displayedRegions: [{ refName: contigName, start: 0, end: length, reversed: false, assemblyName }], tracks: sessionTracks }] },
    metadata: { release_version: release.release_version, assembly_accession: accession, source_ids: publicTracks.map(({ source }) => source.source_id), browser_asset_origin: release.asset_origin_status },
  };
  try { return json(await applyConditionSignals(config, request, env, accession, publicTracks.map(p => p.track))); }
  catch (error) { return dataReleaseErrorResponse(error); }
}

async function proxyAsset(request, env, release, assetKey) {
  if (new URL(request.url).searchParams.has("url")) return json({ error: "arbitrary_origin_not_supported" }, 400);
  const asset = await publicAsset(env, release.release_version, assetKey);
  if (!asset) return json({ error: "unknown_or_private_asset", asset_key: assetKey }, 404);
  const range = request.headers.get("range");
  if (range && Number(asset.supports_range) !== 1) return json({ error: "range_not_supported" }, 416, { "content-range": `bytes */${asset.byte_size}` });
  const requestUrl = new URL(request.url);
  let dataManifest;
  let assetRef;
  try {
    dataManifest = await fixedDataReleaseManifest(env, request);
    assetRef = allowedAsset(dataManifest, asset.logical_path, asset);
  } catch (error) {
    return dataReleaseErrorResponse(error);
  }
  const localBase = String(env.LOCAL_ASSET_BASE || "").trim();
  let origin;
  let staticAssetRequest = false;
  if (isLoopbackHost(requestUrl.hostname) && localBase) {
    let localUrl;
    try {
      localUrl = new URL(localBase);
    } catch {
      return json({ error: "local_origin_not_allowed" }, 403);
    }
    if (
      localUrl.protocol !== "http:"
      || !isLoopbackHost(localUrl.hostname)
      || localUrl.username
      || localUrl.password
      || localUrl.search
      || localUrl.hash
    ) {
      return json({ error: "local_origin_not_allowed" }, 403);
    }
    const prefix = localUrl.pathname.replace(/\/$/, "");
    const localRelative = LOCAL_DATA_ASSET_PATTERN.exec(assetRef.url);
    const localPath = localRelative ? assetRef.url : asset.logical_path;
    origin = new URL(`${localUrl.origin}${prefix}/${localPath.split("/").map(encodeURIComponent).join("/")}`);
  } else {
    const localRelative = LOCAL_DATA_ASSET_PATTERN.exec(assetRef.url);
    if (localRelative) {
      if (!isLoopbackHost(requestUrl.hostname)) return dataReleaseErrorResponse(dataReleaseError("data_release_manifest_invalid"));
      origin = new URL(`/${assetRef.url}`, request.url);
      staticAssetRequest = true;
    } else {
      origin = new URL(assetRef.url);
    }
    if (!staticAssetRequest && (origin.protocol !== "https:" || origin.hostname !== "huggingface.co")) {
      return json({ error: "origin_not_allowed" }, 403);
    }
  }
  const headersIn = new Headers();
  for (const header of ["range", "if-range", "if-none-match", "if-modified-since"]) {
    const value = request.headers.get(header);
    if (value) headersIn.set(header, value);
  }
  let upstream;
  try {
    if (staticAssetRequest && env.ASSETS && typeof env.ASSETS.fetch === "function") {
      upstream = await env.ASSETS.fetch(new Request(origin, { method: request.method, headers: headersIn }));
    } else {
      upstream = await fetch(origin, { method: request.method, headers: headersIn, redirect: "follow" });
    }
  } catch {
    // Keep an unavailable upstream from surfacing as an opaque Worker 500. In
    // local Wrangler this commonly means the sandbox cannot reach HF; the
    // registered asset and its provenance remain valid, but the proxy cannot
    // deliver bytes until the origin is reachable again.
    return json(
      { error: "asset_origin_unavailable", asset_key: asset.asset_key },
      502,
      { "cache-control": "no-store" },
    );
  }
  const headers = new Headers();
  for (const header of RESPONSE_HEADERS) {
    const value = upstream.headers.get(header);
    if (value) headers.set(header, value);
  }
  if (!headers.has("content-type")) headers.set("content-type", asset.content_type);
  if (!headers.has("content-length") && upstream.status === 200) headers.set("content-length", String(asset.byte_size));
  if (range && upstream.status === 206) {
    const contentRange = headers.get("content-range") || "";
    const match = contentRange.match(/^bytes (\d+)-(\d+)\/(\d+)$/);
    const length = Number(headers.get("content-length"));
    if (!match || Number(match[3]) !== Number(asset.byte_size) || !Number.isInteger(length) || length !== Number(match[2]) - Number(match[1]) + 1) {
      return json({ error: "upstream_range_mismatch" }, 502);
    }
  } else if (upstream.status === 200 && headers.has("content-length") && Number(headers.get("content-length")) !== Number(asset.byte_size)) {
    return json({ error: "upstream_length_mismatch" }, 502);
  }
  headers.set("accept-ranges", "bytes");
  headers.set("cache-control", "public, max-age=31536000, immutable");
  headers.set("etag", `"sha256:${asset.sha256}"`);
  headers.set("x-bted-asset-key", asset.asset_key);
  headers.set("x-bted-release-version", release.release_version);
  headers.set("x-bted-sha256", asset.sha256);
  return new Response(request.method === "HEAD" ? null : upstream.body, { status: upstream.status, headers });
}

async function staticAsset(request, env) {
  if (!env.ASSETS || typeof env.ASSETS.fetch !== "function") return json({ error: "static_assets_not_configured" }, 404);
  const response = await env.ASSETS.fetch(request);
  const url = new URL(request.url);
  // JBrowse's large application chunks already carry content hashes.
  const immutable = /^\/jbrowse\/static\/(?:js|css)\/[^/]+\.[0-9a-f]{8}(?:\.chunk)?\.(?:js|css)$/.test(url.pathname)
    || url.pathname === "/jbrowse/plugins/bted-track-plugin.js" && url.searchParams.get("v") === new URL(BTED_PLUGIN_PATH, request.url).searchParams.get("v");
  if (!response.ok || !immutable) return response;
  const headers = new Headers(response.headers);
  headers.set("cache-control", "public, max-age=31536000, immutable");
  return new Response(response.body, { status: response.status, headers });
}

const BATTER_FILES = new Map([
  ...["reference.fa.gz", "reference.fa.gz.fai", "reference.fa.gz.gzi"].map(file => [file, "reference/" + file]),
  ...["augmentation.gff3.gz", "augmentation.gff3.gz.tbi"].map(file => [file, "training/" + file]),
  ...["prediction.gff3.gz", "prediction.gff3.gz.tbi"].map(file => [file, "predictions/" + file]),
  ...["genes.gff3.gz", "genes.gff3.gz.tbi"].map(file => [file, "annotations/batter/" + file]),
]);
const RUNTIME_FILE_NAMES = [...BATTER_FILES.keys()];
const RUNTIME_COUNTS = ["otu_augmentation_span", "otu_augmentation_window", "rfam_training_span", "rfam_training_window", "tes_prediction"];
const RUNTIME_ANNOTATION = ["accession", "features", "reason", "source_gff_sha256", "circular_overhang_features"];

export function runtimeCatalogueRow(row) {
  return [row.genome_id, row.batch, row.otu_id, row.organism, row.genome_type,
    ...RUNTIME_COUNTS.slice(0, 4).map(key => row[key]), row.annotation_status, row.tes_prediction, row.taxonomy, row.source_collection];
}

export function runtimeGenomeMetadata(row, files) {
  const annotation = { status: row.annotation_status };
  for (const key of RUNTIME_ANNOTATION) if (row["annotation_" + key] != null) annotation[key] = row["annotation_" + key];
  const validation = Object.fromEntries(["augmentation", "augmentation_features", "prediction", "prediction_features"].map(key => [key, row["validation_" + key]]));
  const metadata = Object.fromEntries(["genome_id", "batch", "batch_rank", "otu_id", "genome_type", "source_collection", "taxonomy", "augmentation_status"].map(key => [key, row[key]]));
  metadata.annotation = annotation;
  metadata.feature_counts = Object.fromEntries(RUNTIME_COUNTS.map(key => [key, row[key]]));
  metadata.reference = Object.fromEntries(["bases", "contigs", "source", "source_sha256"].map(key => [key, row["reference_" + key]]));
  metadata.reference.source_path = `genomes/${row.otu_id}.fna.gz`;
  metadata.files = {};
  for (const file of files) {
    if (!Number.isInteger(file.file_kind) || !RUNTIME_FILE_NAMES[file.file_kind] || metadata.files[RUNTIME_FILE_NAMES[file.file_kind]]) throw new Error("runtime_invalid_file_kind");
    metadata.files[RUNTIME_FILE_NAMES[file.file_kind]] = { bytes: file.byte_size, sha256: file.sha256 };
  }
  metadata.validation = validation;
  return metadata;
}

async function runtimeRelease(env) {
  const release = await cachedD1Lookup(env.BTED_DB, `runtime-release:${env.BTED_METADATA_REVISION}`, () =>
    env.BTED_DB.prepare("SELECT reference_revision,status,genome_count,file_count FROM hf_runtime_release WHERE singleton=1").bind().first());
  if (release?.reference_revision !== env.BTED_METADATA_REVISION || release.status !== "ready" || release.genome_count !== 42904) throw new Error("runtime_release_unavailable");
  return release;
}
const batterCatalogues = new WeakMap();
const directoryPins = new WeakMap();
const DIRECTORY_RANKS = ["phylum", "class", "order", "family", "genus", "species"];
const DIRECTORY_SORT = { accession: "accession_key", organism: "organism_key", size: "size", endpoints: "endpoints", predictions: "predictions", training: "training" };
const DIRECTORY_DATASETS = { experimental: "endpoints", prediction: "predictions", augmentation: "training" };

function directoryConditions(version, criteria) {
  const where = ["version = ?"], binds = [version];
  for (const field of ["source", "genome_type", "annotation", ...DIRECTORY_RANKS]) if (criteria[field]) {
    where.push(`"${field}" = ?`); binds.push(criteria[field]);
  }
  if (criteria.dataset) where.push(`${DIRECTORY_DATASETS[criteria.dataset]} > 0`);
  if (criteria.q) {
    const tokens = criteria.q.split(/[^\p{L}\p{N}_.-]+/u).filter(Boolean), trigrams = new Set();
    for (const token of tokens) {
      const chars = [...token];
      for (let index = 0; index < chars.length - 2; index++) trigrams.add(chars.slice(index, index + 3).join(""));
    }
    where.push("id IN (SELECT rowid FROM hf_directory_search WHERE hf_directory_search MATCH ?)");
    binds.push([...trigrams].map(token => `"${token.replaceAll('"', '""')}"`).join(" AND "));
    for (const token of tokens) { where.push("instr(search_text, ?) > 0"); binds.push(token); }
  }
  return { condition: where.join(" AND "), binds };
}

async function directoryFacets(request, env, ctx, version, storageVersion, summary, criteria) {
  const facets = {}, groups = new Map();
  for (const field of ["source", "genome_type", "annotation", "dataset", ...DIRECTORY_RANKS]) {
    const index = DIRECTORY_RANKS.indexOf(field);
    if (index > 0 && DIRECTORY_RANKS.slice(0, index).some(parent => !criteria[parent])) continue;
    // A menu offers alternatives to itself; a parent classification also ignores its descendants.
    const scope = Object.fromEntries(Object.entries(criteria).filter(([key]) => key !== field &&
      !(index >= 0 && DIRECTORY_RANKS.slice(index + 1).includes(key))));
    if (!Object.keys(scope).length) {
      facets[field] = field === "source" ? summary.sources : field === "phylum" ? summary.phyla.slice().sort((a, b) => summary.counts.phylum[b] - summary.counts.phylum[a])
        : Object.entries(summary.counts[field] || {}).filter(([, count]) => count > 0).map(([value]) => value).sort();
      continue;
    }
    if (field === "phylum") {
      facets.phylum = await directoryCachedValue(request, env, ctx, version, "phylum-by-count-v1", scope, async () => {
        const { condition, binds } = directoryConditions(storageVersion, scope);
        const rows = await env.BTED_DB.prepare(`SELECT phylum,COUNT(*) AS n FROM hf_directory_genomes WHERE ${condition} AND phylum != '' GROUP BY phylum ORDER BY n DESC,phylum ASC`).bind(...binds).all();
        return rows.results.map(row => row.phylum);
      });
      continue;
    }
    const key = JSON.stringify(scope);
    if (!groups.has(key)) groups.set(key, { scope, fields: [] });
    groups.get(key).fields.push(field);
  }
  await Promise.all([...groups.values()].map(async ({ scope, fields }) => {
    const values = await directoryCachedValue(request, env, ctx, version, "facets-v2", { ...scope, fields: fields.join(",") }, async () => {
      const { condition, binds } = directoryConditions(storageVersion, scope);
      const expressions = fields.flatMap(field => field === "dataset"
        ? Object.entries(DIRECTORY_DATASETS).map(([key, column]) => `MAX(${column} > 0) AS "${key}"`)
        : [`json_group_array(DISTINCT "${field}") FILTER (WHERE "${field}" != '') AS "${field}"`]);
      return env.BTED_DB.prepare(`SELECT ${expressions.join(",")} FROM hf_directory_genomes WHERE ${condition}`).bind(...binds).first();
    });
    for (const field of fields) facets[field] = field === "dataset"
      ? Object.keys(DIRECTORY_DATASETS).filter(key => values[key]) : JSON.parse(values[field]).sort();
  }));
  return facets;
}

function directoryQuery(url) {
  const params = url.searchParams;
  const page = Number(params.get("page") || 1);
  const sort = params.get("sort") || "endpoints", direction = params.get("direction") || "desc";
  if (!/^[0-9a-f]{24}$/.test(params.get("v") || "") || !Number.isInteger(page) || page < 1 || page > 2000
      || !Object.hasOwn(DIRECTORY_SORT, sort) || !["asc", "desc"].includes(direction)
      || params.has("page_size") && params.get("page_size") !== "25") throw new Error("invalid_directory_query");
  const q = (params.get("q") || "").normalize("NFKC").toLowerCase().trim();
  const tokens = q.split(/[^\p{L}\p{N}_.-]+/u).filter(Boolean);
  if (q.length > 160 || tokens.length > 12) throw new Error("invalid_directory_query");
  if (tokens.length && !tokens.some(token => [...token].length >= 3)) throw new Error("search_too_short");
  const query = { v: params.get("v"), page, sort, direction, q };
  for (const field of ["source", "genome_type", "annotation", "dataset", ...DIRECTORY_RANKS]) {
    query[field] = params.get(field) || "";
    if (query[field].length > 160) throw new Error("invalid_directory_query");
  }
  for (const [field, allowed] of [["genome_type", ["isolate", "MAG", "SAG", "unknown"]], ["annotation", ["Available", "Missing"]], ["dataset", ["experimental", "prediction", "augmentation"]]]) {
    if (query[field] && !allowed.includes(query[field])) throw new Error("invalid_directory_query");
  }
  return { query, tokens };
}

async function directoryCachedValue(request, env, ctx, version, kind, params, load) {
  const keyUrl = new URL("/__directory-cache", request.url);
  keyUrl.searchParams.set("version", version); keyUrl.searchParams.set("kind", kind);
  for (const [key, value] of Object.entries(params)) if (value) keyUrl.searchParams.set(key, value);
  keyUrl.searchParams.sort();
  const key = new Request(keyUrl), cache = globalThis.caches?.default;
  try { const hit = await cache?.match(key); if (hit) return hit.json(); } catch { /* Use D1 if the edge cache is unavailable. */ }
  const value = await cachedD1Lookup(env.BTED_DB, keyUrl.href, load);
  if (cache) {
    const task = cache.put(key, json(value, 200, { "cache-control": "public, max-age=60, s-maxage=604800" })).catch(() => {});
    if (ctx?.waitUntil) ctx.waitUntil(task); else await task;
  }
  return value;
}

async function genomeDirectory(request, env, ctx) {
  let parsed;
  try { parsed = directoryQuery(new URL(request.url)); }
  catch (error) { return json({ error: error.message }, 400, { "cache-control": "no-store" }); }
  const { query, tokens } = parsed;
  try {
    if (!directoryPins.has(env.ASSETS)) {
      const task = env.ASSETS.fetch(new Request(new URL("/assets/genome-directory.json", request.url))).then(async response => {
        if (!response.ok) throw new Error("directory_unavailable");
        return response.json();
      });
      directoryPins.set(env.ASSETS, task);
      task.catch(() => directoryPins.delete(env.ASSETS));
    }
    const pin = await directoryPins.get(env.ASSETS);
    if (query.v !== pin.version || pin.reference_revision !== env.BTED_METADATA_REVISION
        || pin.annotation_revision !== (env.BTED_ANNOTATION_REVISION || "original")) return json({ error: "directory_version_changed" }, 409, { "cache-control": "no-store" });
    const release = await cachedD1Lookup(env.BTED_DB, `directory-release:${query.v}`, () => env.BTED_DB.prepare(
      "SELECT summary_json FROM hf_directory_releases WHERE version = ? AND reference_revision = ? AND annotation_revision = ? AND status = 'ready'")
      .bind(query.v, pin.reference_revision, pin.annotation_revision).first());
    if (!release) throw new Error("directory_unavailable");
    const summary = JSON.parse(release.summary_json);
    if (query.source && !summary.sources.includes(query.source)) return json({ error: "invalid_directory_query" }, 400, { "cache-control": "no-store" });
    const storageVersion = summary.storage_version || query.v;
    const criteria = Object.fromEntries(["source", "genome_type", "annotation", "dataset", ...DIRECTORY_RANKS, "q"]
      .filter(field => field === "q" ? tokens.length : query[field]).map(field => [field, query[field]]));
    const { condition, binds } = directoryConditions(storageVersion, criteria);
    const fields = Object.keys(criteria), knownCount = fields.length === 0 ? summary.total
      : fields.length === 1 && summary.counts[fields[0]] ? summary.counts[fields[0]][criteria[fields[0]]] ?? 0 : null;
    const total = knownCount ?? (await directoryCachedValue(request, env, ctx, query.v, "count", criteria, () =>
      env.BTED_DB.prepare(`SELECT COUNT(*) AS total FROM hf_directory_genomes WHERE ${condition}`).bind(...binds).first())).total;
    const page = Math.max(1, Math.min(query.page, Math.ceil(total / 25)));
    const order = `${query.sort === "size" ? "(size IS NULL), " : ""}${DIRECTORY_SORT[query.sort]} ${query.direction.toUpperCase()}, accession_key ASC`;
    const { results } = await env.BTED_DB.prepare(`SELECT * FROM hf_directory_genomes WHERE ${condition} ORDER BY ${order} LIMIT 25 OFFSET ?`)
      .bind(...binds, (page - 1) * 25).all();
    const catalogueFields = "genome_id,batch,otu_id,organism,genome_type,otu_augmentation_span,otu_augmentation_window,rfam_training_span,rfam_training_window,annotation_status,tes_prediction,taxonomy,source_collection";
    if (env.BTED_RUNTIME_FIELDS === "on") await runtimeRelease(env);
    const metadataRows = results.length ? (await env.BTED_DB.prepare(env.BTED_RUNTIME_FIELDS === "on"
      ? `SELECT ${catalogueFields} FROM hf_runtime_genomes WHERE genome_id IN (${results.map(() => "?").join(",")})`
      : `SELECT genome_id, catalogue_row_json FROM hf_genome_metadata WHERE revision = ? AND genome_id IN (${results.map(() => "?").join(",")})`)
      .bind(...(env.BTED_RUNTIME_FIELDS === "on" ? [] : [pin.reference_revision]), ...results.map(row => row.genome_id)).all()).results : [];
    const records = new Map(metadataRows.map(row => [row.genome_id, env.BTED_RUNTIME_FIELDS === "on" ? runtimeCatalogueRow(row) : row.catalogue_row_json ? JSON.parse(row.catalogue_row_json) : null]));
    const rows = results.map(item => {
      if (!records.has(item.genome_id) && (env.BTED_RUNTIME_FIELDS !== "on" || item.training
          || item.predictions && summary.experimental_predictions?.[item.genome_id] !== item.predictions)) throw new Error("directory_metadata_mismatch");
      const batter = records.get(item.genome_id) || [item.genome_id, "", "", item.organism, "", 0, 0, 0, 0, item.annotation === "Available" ? "matched" : "unavailable", item.predictions, "", "NCBI-RefSeq"];
      batter[3] = item.organism;
      const row = { batter, dataset: { taxonomyPhylum: item.phylum, taxonomyGenus: item.genus, sortEndpoints: String(item.endpoints), sortPredictions: String(item.predictions), sortTraining: String(item.training) } };
      if (item.size) row.referenceSize = [item.size, item.contigs];
      if (item.recovered_coverage) row.recoveredAnnotation = { coverage: item.recovered_coverage, matched_reference_contigs: item.recovered_matched, total_reference_contigs: item.recovered_total };
      return row;
    });
    const facets = await directoryFacets(request, env, ctx, query.v, storageVersion, summary, criteria);
    return json({ rows, total, page, page_size: 25, facets, sources: summary.sources }, 200,
      { "cache-control": "public, max-age=60", "x-bted-metadata-source": "d1" });
  } catch (error) {
    console.error("Genome directory:", error.message);
    return json({ error: "directory_unavailable" }, 503, { "cache-control": "no-store" });
  }
}

async function hfMetadataRelease(env) {
  if (!/^[0-9a-f]{40}$/.test(env.BTED_METADATA_REVISION || "")) throw new Error("metadata_revision_invalid");
  const release = await cachedD1Lookup(env.BTED_DB, `hf-release:${env.BTED_METADATA_REVISION}`, () =>
    env.BTED_DB.prepare("SELECT revision, catalogue_header_json FROM hf_metadata_releases WHERE revision = ? AND status = 'ready'")
      .bind(env.BTED_METADATA_REVISION).first());
  if (!release) throw new Error("metadata_release_unavailable");
  return release;
}

async function hfGenomeMetadata(env, id) {
  if (env.BTED_RUNTIME_FIELDS === "on") {
    await runtimeRelease(env);
    return cachedD1Lookup(env.BTED_DB, `runtime-genome:${env.BTED_METADATA_REVISION}:${id}`, async () => {
      const row = await env.BTED_DB.prepare("SELECT * FROM hf_runtime_genomes WHERE genome_id = ?").bind(id).first();
      if (!row) return null;
      const files = await env.BTED_DB.prepare("SELECT file_kind,byte_size,sha256 FROM hf_runtime_files WHERE genome_key = ?").bind(row.id).all();
      return { catalogue_row: runtimeCatalogueRow(row), metadata: runtimeGenomeMetadata(row, files.results) };
    });
  }
  return cachedD1Lookup(env.BTED_DB, `hf-genome:${env.BTED_METADATA_REVISION}:${id}`, () =>
    env.BTED_DB.prepare("SELECT catalogue_row_json, metadata_json FROM hf_genome_metadata WHERE revision = ? AND genome_id = ?")
      .bind(env.BTED_METADATA_REVISION, id).first());
}

async function batterCatalogueResponse(request, env) {
  if (!env.BTED_METADATA_REVISION) {
    const response = await env.ASSETS.fetch(new Request(new URL("/assets/batter-browser.json", request.url)));
    if (!env.BTED_ANNOTATION_REVISION || !response.ok || request.method === "HEAD") return response;
    const data = await response.json();
    data.annotation_recovery = await registeredAnnotationRecovery(request, env, data.revision);
    return json(data);
  }
  try {
    const release = await hfMetadataRelease(env);
    const genomeRows = await cachedD1Lookup(env.BTED_DB, `hf-catalogue:${release.revision}`, async () => {
      const pages = [];
      for (let page = 0; ; page += 100) {
        const { results } = await env.BTED_DB.prepare("SELECT rows_json FROM hf_catalogue_pages WHERE revision = ? AND page >= ? AND page < ? ORDER BY page")
          .bind(release.revision, page, page + 100).all();
        pages.push(...results);
        if (results.length < 100) break;
      }
      if (!pages.length) throw new Error("catalogue_unavailable");
      return pages.map(row => row.rows_json.slice(1, -1)).join(',');
    });
    const fields = JSON.parse(release.catalogue_header_json);
    if (env.BTED_ANNOTATION_REVISION) fields.annotation_recovery = await registeredAnnotationRecovery(request, env, release.revision);
    const header = JSON.stringify(fields);
    const body = header.slice(0, -1) + ',"genomes":[' + genomeRows + ']}';
    return new Response(request.method === "HEAD" ? null : body, { headers: {
      "content-type": "application/json; charset=utf-8", "cache-control": "public, max-age=300",
      "x-bted-metadata-source": "d1", "x-bted-revision": release.revision,
    } });
  } catch (error) {
    console.error("BATTER catalogue:", error.message);
    return json({ error: "catalogue_unavailable" }, 503, { "cache-control": "no-store" });
  }
}

async function batterCatalogue(request, env) {
  if (!batterCatalogues.has(env.ASSETS)) {
    const task = env.ASSETS.fetch(new Request(new URL("/assets/batter-browser.json", request.url))).then(async response => {
      if (!response.ok) throw new Error("catalogue_unavailable");
      const data = await response.json();
      if (!/^[0-9a-f]{40}$/.test(data.revision) || data.layout !== "genome-first" || !Array.isArray(data.genomes)) throw new Error("catalogue_invalid");
      return { revision: data.revision, genomes: new Map(data.genomes.map(row => [row[0], row])) };
    });
    batterCatalogues.set(env.ASSETS, task);
    task.catch(() => batterCatalogues.delete(env.ASSETS));
  }
  return batterCatalogues.get(env.ASSETS);
}

async function genomeBrowserRegistry(request, env) {
  const response = await env.ASSETS.fetch(new Request(new URL("/assets/genome-browsers.json", request.url)));
  if (!response.ok) throw new Error("genome_browser_registry_unavailable");
  return response.json();
}

async function registeredAnnotationRecovery(request, env, referenceRevision) {
  if (!env.BTED_ANNOTATION_REVISION) return null;
  const recovery = (await genomeBrowserRegistry(request, env)).annotation_recovery;
  if (!recovery || recovery.annotation_revision !== env.BTED_ANNOTATION_REVISION
      || !/^[0-9a-f]{40}$/.test(recovery.annotation_revision) || recovery.reference_revision !== referenceRevision) {
    throw new Error("annotation_supplement_revision_mismatch");
  }
  return recovery;
}

export function applyRecoveredAnnotation(metadata, recovery) {
  if (!recovery) return;
  if (recovery.reference_revision !== metadata.revision) throw new Error("annotation_supplement_revision_mismatch");
  const entry = recovery.genomes?.[metadata.genome_id];
  if (!entry) return;
  const path = `${recovery.path_prefix}/batter-${metadata.batch}/${metadata.genome_id}/annotations/recovered/genes.gff3`;
  if (!/^[0-9a-f]{40}$/.test(recovery.annotation_revision)
      || entry.reference_sha256 !== metadata.files["reference.fa.gz"].sha256
      || recovery.path_prefix !== "v0.5.0/genomes" || !/^\d{3}$/.test(metadata.batch)
      || !/^[A-Za-z0-9_.-]{1,128}$/.test(metadata.genome_id)
      || entry.file?.path !== undefined || !SHA256_PATTERN.test(entry.file?.sha256)
      || !Number.isSafeInteger(entry.file.bytes) || entry.file.bytes < 1
      || !["full", "partial"].includes(entry.coverage)
      || !Number.isSafeInteger(entry.matched_reference_contigs) || entry.matched_reference_contigs < 1
      || entry.total_reference_contigs !== metadata.reference.contigs
      || entry.matched_reference_contigs > entry.total_reference_contigs
      || !Number.isSafeInteger(entry.features) || entry.features < 1
      || (entry.coverage === "full") !== (entry.matched_reference_contigs === entry.total_reference_contigs)) {
    throw new Error("annotation_supplement_reference_mismatch");
  }
  metadata.annotation = { ...metadata.annotation, original_status: metadata.annotation.status, status: "matched",
    recovered: true, coverage: entry.coverage, matched_reference_contigs: entry.matched_reference_contigs,
    total_reference_contigs: entry.total_reference_contigs, features: entry.features,
    source_url: entry.source_url, source_annotation_type: entry.source_annotation_type,
    annotation_revision: recovery.annotation_revision };
  metadata.browser_files["genes.gff3"] = { ...entry.file,
    url: `https://huggingface.co/datasets/liurulong/terminator/resolve/${recovery.annotation_revision}/${path}`,
    fallback_url: `/api/batter/${encodeURIComponent(metadata.genome_id)}/files/genes.gff3?revision=${metadata.revision}` };
}

export function combineGenomeTracks(config, experimental, verified, metadata) {
  const id = metadata.genome_id;
  const matching = verified?.compatible && verified.batter_reference_sha256 === metadata.files["reference.fa.gz"].sha256
    && verified.experimental_reference_url === experimental.assemblies[0].sequence.adapter.fastaLocation.uri;
  config.configuration = experimental.configuration;
  config.metadata.combined_reference_status = matching ? "matching_sequences" : "separate_views";
  if (!matching) {
    config.assemblies.push(...experimental.assemblies);
    config.tracks.push(...experimental.tracks);
    config.defaultSession.views.push(...experimental.defaultSession.views);
    return config;
  }
  const aliases = Object.entries(verified.aliases || {}).filter(([alias, ref]) => alias !== ref).map(([alias, ref]) => `${ref}\t${alias}`).join("\n");
  if (aliases) config.assemblies[0].refNameAliases = { adapter: { type: "RefNameAliasAdapter", location: { uri: "data:text/plain," + encodeURIComponent(aliases + "\n"), locationType: "UriLocation" } } };
  const tracks = experimental.tracks.filter(track => !config.tracks.some(existing => existing.metadata?.btedAbout?.kind === "reference") || track.metadata?.btedAbout?.kind !== "reference")
    .map(track => {
      const counts = track.metadata?.btedContigCounts;
      const mapped = {};
      if (counts) for (const [ref, count] of Object.entries(counts)) {
        const target = verified.aliases?.[ref] || ref;
        mapped[target] = (mapped[target] || 0) + count;
      }
      return { ...track, assemblyNames: [id], metadata: { ...track.metadata,
        ...(counts ? { btedContigCounts: mapped } : {}) } };
    });
  config.tracks.push(...tracks);
  const available = new Set(tracks.map(track => track.trackId));
  const sessionTracks = experimental.defaultSession.views.flatMap(view => view.tracks).filter(track => available.has(track.configuration));
  config.defaultSession.views[0].tracks.push(...sessionTracks);
  return config;
}

async function batterFileBytes(url, file) {
  const response = await fetch(url, { cf: { cacheTtl: 86400, cacheEverything: true } });
  if (!response.ok) throw new Error("file_not_uploaded");
  if (file.bytes > 16 * 1024 * 1024) throw new Error("file_too_large");
  const bytes = await response.arrayBuffer();
  const hash = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map(n => n.toString(16).padStart(2, "0")).join("");
  if (bytes.byteLength !== file.bytes || hash !== file.sha256) throw new Error("file_checksum_mismatch");
  return bytes;
}

// TBI's metadata bin stores whole-reference mapped record counts, not viewport hits.
export function tabixContigCounts(bytes, contigs, expected) {
  try {
    const data = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    let offset = 4;
    const uint = () => { const n = data.getUint32(offset, true); offset += 4; return n; };
    const skip = n => { offset += n; if (offset > data.byteLength) throw new Error("truncated_index"); };
    if (data.getUint32(0, true) !== 0x01494254) return null;
    const references = uint();
    skip(24);
    const nameBytes = uint();
    const names = new TextDecoder().decode(bytes.subarray(offset, offset + nameBytes)).split("\0");
    skip(nameBytes);
    if (names.pop() !== "" || names.length !== references) return null;
    const counts = new Map();
    for (const ref of names) {
      if (!contigs.has(ref) || counts.has(ref)) return null;
      const bins = uint();
      let mapped = null;
      for (let i = 0; i < bins; i++) {
        const bin = uint(), chunks = uint();
        if (bin === 37450) {
          if (chunks !== 2 || mapped !== null) return null;
          mapped = Number(data.getBigUint64(offset + 16, true));
          if (!Number.isSafeInteger(mapped) || data.getBigUint64(offset + 24, true) !== 0n) return null;
        }
        skip(chunks * 16);
      }
      skip(uint() * 8);
      if (mapped === null) return null;
      counts.set(ref, mapped);
    }
    if ([...counts.values()].reduce((sum, n) => sum + n, 0) !== expected) return null;
    return Object.fromEntries([...contigs.keys()].map(ref => [ref, counts.get(ref) || 0]));
  } catch { return null; } // Optional counts must not block an otherwise usable track.
}

export function augmentationContigCounts(text, contigs, expected) {
  const types = new Map([["augmented_terminator_span", "otu_augmentation_span"], ["rfam_training_span", "rfam_training_span"]]);
  const totals = { otu_augmentation_span: 0, rfam_training_span: 0, otu_augmentation_window: 0, rfam_training_window: 0 };
  const breakdown = Object.fromEntries([...contigs.keys()].map(ref => [ref, { otu: 0, rfam: 0 }]));
  for (const line of text.split(/\r?\n/)) {
    if (!line || line.startsWith("#")) continue;
    const fields = line.split("\t"), [ref, , type] = fields;
    const start = Number(fields[3]), end = Number(fields[4]);
    if (fields.length !== 9 || !contigs.has(ref) || !Number.isSafeInteger(start) || !Number.isSafeInteger(end)
        || start < 1 || end < start || end > contigs.get(ref)) return null;
    let key = types.get(type);
    if (type === "training_sequence_window" || type === "rfam_training_window") {
      const dataset = fields[8].split(";").find(attr => attr.startsWith("dataset_class="))?.slice(14);
      key = dataset === "otu_augmentation_window" || dataset === "rfam_training_window" ? dataset : null;
    }
    if (!key) return null;
    totals[key]++;
    if (type === "augmented_terminator_span") breakdown[ref].otu++;
    if (type === "rfam_training_span") breakdown[ref].rfam++;
  }
  if (Object.entries(totals).some(([key, n]) => n !== expected[key])) return null;
  return { counts: Object.fromEntries(Object.entries(breakdown).map(([ref, n]) => [ref, n.otu + n.rfam])), breakdown };
}

async function batterConfig(request, metadata) {
  const id = metadata.genome_id;
  const uri = file => ({ uri: metadata.browser_files[file].url, locationType: "UriLocation" });
  const reference = { type: "ReferenceSequenceTrack", trackId: "batter_refseq", name: "Reference sequence", adapter: { type: "BgzipFastaAdapter", fastaLocation: uri("reference.fa.gz"), faiLocation: uri("reference.fa.gz.fai"), gziLocation: uri("reference.fa.gz.gzi") } };
  const fai = new TextDecoder().decode(await batterFileBytes(uri("reference.fa.gz.fai").uri, metadata.files["reference.fa.gz.fai"]));
  const contigs = new Map(fai.trim().split(/\r?\n/).map(line => { const [ref, size] = line.split("\t"); return [ref, Number(size)]; }));
  if ([...contigs.values()].some(length => !Number.isSafeInteger(length) || length < 1)) throw new Error("reference_index_invalid");
  let ref = contigs.keys().next().value, start = 0;
  const counts = metadata.feature_counts;
  const augmented = counts.otu_augmentation_span + counts.rfam_training_span;
  let augmentationCounts = null;
  if (augmented || counts.otu_augmentation_window || counts.rfam_training_window) {
    const bytes = await batterFileBytes(uri("augmentation.gff3.gz").uri, metadata.files["augmentation.gff3.gz"]);
    // BGZF contains concatenated gzip members; Workers' DecompressionStream rejects the trailing members.
    const { gunzipSync } = await import("node:zlib");
    const text = gunzipSync(new Uint8Array(bytes)).toString("utf8");
    augmentationCounts = augmentationContigCounts(text, contigs, counts);
    const first = text.split(/\r?\n/).find(line => line && !line.startsWith("#"));
    if (!first) throw new Error("augmentation_records_missing");
    const fields = first.split("\t");
    if (fields.length !== 9 || !contigs.has(fields[0]) || Number(fields[3]) < 1 || Number(fields[4]) > contigs.get(fields[0])) throw new Error("augmentation_reference_mismatch");
    ref = fields[0]; start = Math.max(0, Number(fields[3]) - 201);
  }
  const tracks = [];
  function addTrack(trackId, name, file, renderer, height, explanation) {
    tracks.push({ type: "FeatureTrack", trackId, name, assemblyNames: [id], category: [trackId === "batter_prediction" ? "Model prediction" : trackId === "batter_genes" ? "Reference annotation" : "Augmentation / Rfam"],
      adapter: file.endsWith(".gff3") ? { type: "Gff3Adapter", gffLocation: uri(file) }
        : { type: "Gff3TabixAdapter", gffGzLocation: uri(file), index: { location: uri(file + ".tbi"), indexType: "TBI" } },
      displays: [{ type: "LinearBasicDisplay", displayId: trackId + "_display", height, showLabels: false, renderer: { type: "SvgFeatureRenderer", showLabels: false, ...renderer } }],
      metadata: { btedAbout: { kind: trackId === "batter_genes" ? "reference" : "augmentation", title: "BATTER", assembly: id, evidence: trackId === "batter_genes" ? "Reference annotation" : "OTU data augmentation and Rfam-derived training regions", ...(trackId === "batter_augmentation" ? { record_count: augmented } : {}), explanation, doi_url: "https://doi.org/10.1186/s40168-026-02454-1", gff3_url: uri(file).uri },
        btedDownloads: [{ kind: "reference", label: name + " GFF3", url: uri(file).uri, filename: id + "." + file }] } });
  }
  if (!metadata.annotation.recovered && metadata.annotation.status === "matched" && metadata.browser_files["genes.gff3.gz"] && metadata.browser_files["genes.gff3.gz.tbi"]) {
    addTrack("batter_genes", "Reference gene annotation", "genes.gff3.gz", { showDescriptions: false, color1: "jexl:btedStrandColor(feature)", color2: "jexl:btedStrandColor(feature)" }, 130, "Gene annotation matched to this reference.");
  }
  if (metadata.annotation.recovered && metadata.browser_files["genes.gff3"]) {
    const annotation = metadata.annotation;
    const explanation = `Annotation: ${annotation.matched_reference_contigs}/${annotation.total_reference_contigs} contigs${annotation.coverage === "partial" ? " (partial)" : ""}.`;
    addTrack("batter_genes", "Reference gene annotation", "genes.gff3", { showDescriptions: false, color1: "jexl:btedStrandColor(feature)", color2: "jexl:btedStrandColor(feature)" }, 130, explanation);
    tracks.at(-1).metadata.btedAbout = { kind: "reference", title: "Gene annotation", assembly: id,
      reference: `${id} · ${annotation.matched_reference_contigs}/${annotation.total_reference_contigs} contigs${annotation.coverage === "partial" ? " (partial)" : ""}`,
      evidence: annotation.source_annotation_type, explanation, record_count: annotation.features,
      gff3_url: uri("genes.gff3").uri, source_url: annotation.source_url };
  }
  if (augmented || counts.otu_augmentation_window || counts.rfam_training_window) {
    addTrack("batter_augmentation", "Augmentation / Rfam regions", "augmentation.gff3.gz", { color1: "jexl:btedAugmentationColor(feature)", color2: "jexl:btedAugmentationColor(feature)", mouseover: "jexl:get(feature,'type') == 'training_sequence_window' || get(feature,'type') == 'rfam_training_window' ? 'Sequence context window' : get(feature,'name')", height: 14 }, 96, "OTU augmentation and Rfam training regions. Counts exclude context windows.");
  }
  for (const track of tracks) {
    if (track.trackId === "batter_genes") track.displays[0].jexlFilters = ["get(feature,'type')!='region'"];
    if (track.trackId === "batter_augmentation") {
      track.displays[0].jexlFilters = ["get(feature,'type')!='training_sequence_window' && get(feature,'type')!='rfam_training_window'"];
      track.metadata.btedContigCounts = augmentationCounts?.counts || null;
      track.metadata.btedContigBreakdown = augmentationCounts?.breakdown || null;
    }
  }
  if (counts.tes_prediction > 0) {
    addTrack("batter_prediction", "Predicted regions", "prediction.gff3.gz", { color1: "jexl:btedStrandColor(feature)", color2: "jexl:btedStrandColor(feature)", height: 14, mouseover: "jexl:btedPredictionTooltip(feature)" }, 160, "BATTER predictions with interval coordinates.");
    const about = tracks.at(-1).metadata.btedAbout;
    about.kind = "prediction"; about.evidence = "Model prediction"; about.record_count = counts.tes_prediction;
    tracks.at(-1).metadata.btedContigCounts = null;
    try {
      const file = "prediction.gff3.gz.tbi";
      const bytes = await batterFileBytes(uri(file).uri, metadata.files[file]);
      const { gunzipSync } = await import("node:zlib");
      tracks.at(-1).metadata.btedContigCounts = tabixContigCounts(gunzipSync(new Uint8Array(bytes)), contigs, counts.tes_prediction);
    } catch { /* Missing optional index statistics leave the count unavailable, never zero. */ }
  }
  const sessionTracks = [{ id: "batter_sequence", type: "ReferenceSequenceTrack", configuration: reference.trackId, displays: [{ type: "LinearReferenceSequenceDisplay", configuration: reference.trackId + "-LinearReferenceSequenceDisplay", showTranslation: true, heightPreConfig: 120 }] },
    ...tracks.map(track => ({ id: track.trackId, type: "FeatureTrack", configuration: track.trackId, displays: [{ type: "LinearBasicDisplay", configuration: track.displays[0].displayId }] }))];
  return { plugins: [{ name: "BTEDTrackPlugin", esmUrl: new URL(BTED_PLUGIN_PATH, request.url).href }],
    assemblies: [{ name: id, sequence: reference }], tracks,
    defaultSession: { name: "BTED genome · " + id, views: [{ id: "batter_view", type: "LinearGenomeView", bpPerPx: 1, offsetPx: start, displayedRegions: [{ refName: ref, start: 0, end: contigs.get(ref), assemblyName: id, reversed: false }], tracks: sessionTracks }] },
    metadata: { revision: metadata.revision } };
}

async function batterApi(request, env, match) {
  const url = new URL(request.url), id = decodePath(match[1]);
  if (!id || !/^[A-Za-z0-9_.-]{1,128}$/.test(id) || url.searchParams.has("url")) return json({ error: "invalid_genome_request" }, 400);
  try {
    let catalogue, row, wrapper;
    if (env.BTED_METADATA_REVISION) {
      catalogue = await hfMetadataRelease(env);
      const stored = await hfGenomeMetadata(env, id);
      row = stored?.catalogue_row || (stored?.catalogue_row_json ? JSON.parse(stored.catalogue_row_json) : null);
      wrapper = stored?.metadata ? { genome_id: id, group: `batter-${stored.metadata.batch}`, has_prediction: true, records: { batter: structuredClone(stored.metadata) } }
        : stored ? JSON.parse(stored.metadata_json) : null;
    } else {
      catalogue = await batterCatalogue(request, env);
      row = catalogue.genomes.get(id);
    }
    if (!row) return json({ error: "genome_not_indexed" }, 404);
    if (url.searchParams.has("revision") && url.searchParams.get("revision") !== catalogue.revision) return json({ error: "revision_changed_reload_page" }, 409);
    if (!/^\d{3}$/.test(row[1])) throw new Error("catalogue_invalid_batch");
    const base = `https://huggingface.co/datasets/liurulong/terminator/resolve/${catalogue.revision}/v0.5.0/genomes/batter-${row[1]}/${encodeURIComponent(id)}/`;
    if (!wrapper) {
      const response = await fetch(base + "metadata.json", { cf: { cacheTtl: 86400, cacheEverything: true } });
      if (!response.ok) return json({ error: "genome_upload_unavailable" }, 503, { "cache-control": "no-store" });
      wrapper = await response.json();
    }
    const metadata = wrapper.records?.batter;
    if (wrapper.genome_id !== id || wrapper.group !== `batter-${row[1]}` || wrapper.has_prediction !== true
      || metadata?.genome_id !== id || metadata.batch !== row[1] || metadata.otu_id !== row[2]
      || !metadata.feature_counts || !metadata.reference || !metadata.annotation || !metadata.files) throw new Error("metadata_mismatch");
    for (const [field, column] of [["otu_augmentation_span", 5], ["otu_augmentation_window", 6], ["rfam_training_span", 7], ["rfam_training_window", 8], ["tes_prediction", 10]]) {
      const count = metadata.feature_counts[field];
      if (!Number.isSafeInteger(count) || count < 0 || count !== row[column]) throw new Error("metadata_count_mismatch");
    }
    metadata.revision = catalogue.revision;
    metadata.browser_files = {};
    for (const [file, entry] of Object.entries(metadata.files)) {
      if (!BATTER_FILES.has(file)) continue;
      if (!Number.isSafeInteger(entry.bytes) || entry.bytes < 0 || !SHA256_PATTERN.test(entry.sha256)) throw new Error("metadata_invalid_file");
      metadata.browser_files[file] = { ...entry, url: base + BATTER_FILES.get(file), fallback_url: `/api/batter/${encodeURIComponent(id)}/files/${file}?revision=${catalogue.revision}` };
    }
    for (const file of ["reference.fa.gz", "reference.fa.gz.fai", "reference.fa.gz.gzi"]) if (!metadata.browser_files[file]) throw new Error("reference_not_uploaded");
    if (env.BTED_ANNOTATION_REVISION) applyRecoveredAnnotation(metadata, await registeredAnnotationRecovery(request, env, catalogue.revision));
    if (match[2] === "config") {
      let config = await batterConfig(request, metadata);
      const registry = await genomeBrowserRegistry(request, env);
      const path = registry.experimental?.[id];
      if (path) {
        if (!/^\/jbrowse\/assemblies\/[A-Za-z0-9_.-]+\.config\.json$/.test(path)) throw new Error("invalid_experimental_config_path");
        const experimentalResponse = await env.ASSETS.fetch(new Request(new URL(path, request.url)));
        if (!experimentalResponse.ok) throw new Error("experimental_config_unavailable");
        const verified = registry.revision === catalogue.revision ? registry.overlays?.[id] : null;
        config = combineGenomeTracks(config, await experimentalResponse.json(), verified, metadata);
        await applyConditionSignals(config, request, env, id);
      }
      return json(config, 200, { "cache-control": "no-cache", "x-bted-metadata-source": env.BTED_METADATA_REVISION ? "d1" : "hf" });
    }
    if (match[2] !== "files") return json(metadata, 200, { "cache-control": "no-cache", "x-bted-metadata-source": env.BTED_METADATA_REVISION ? "d1" : "hf" });
    const file = decodePath(match[3]);
    const asset = metadata.browser_files[file];
    if (!asset) return json({ error: "file_not_registered" }, 404);
    const range = request.headers.get("range");
    if (range && !/^bytes=(?:\d+-\d*|-\d+)$/.test(range)) return json({ error: "invalid_range" }, 416);
    let upstream;
    if (asset.bytes <= 512 * 1024) {
      // Small registered files reuse the verified immutable cache used by config
      // generation. Large reference and annotation files still stream upstream.
      const bytes = new Uint8Array(await batterFileBytes(asset.url, asset));
      let start = 0, end = bytes.length - 1;
      if (range) {
        const [left, right] = range.slice(6).split("-");
        const first = left ? Number(left) : Number(right);
        const last = right ? Number(right) : end;
        if (!Number.isSafeInteger(first) || !Number.isSafeInteger(last) ||
            (!left && first === 0) || (left && (first >= bytes.length || last < first))) {
          return json({ error: "invalid_range" }, 416, { "content-range": `bytes */${bytes.length}` });
        }
        start = left ? first : Math.max(0, bytes.length - first);
        end = left ? Math.min(last, end) : end;
      }
      upstream = new Response(request.method === "HEAD" ? null : bytes.subarray(start, end + 1), {
        status: range ? 206 : 200,
        headers: { "content-type": "application/octet-stream", "content-length": String(end - start + 1),
          ...(range ? { "content-range": `bytes ${start}-${end}/${bytes.length}` } : {}) },
      });
    } else {
      upstream = await fetch(asset.url, { method: request.method, headers: range ? { range } : {} });
    }
    if (![200, 206].includes(upstream.status)) return json({ error: "file_upload_unavailable" }, upstream.status === 416 ? 416 : 503, { "cache-control": "no-store" });
    const headers = new Headers();
    for (const key of RESPONSE_HEADERS) if (upstream.headers.has(key)) headers.set(key, upstream.headers.get(key));
    if (upstream.status === 206) {
      const bounds = (headers.get("content-range") || "").match(/^bytes (\d+)-(\d+)\/(\d+)$/);
      if (!bounds || Number(bounds[3]) !== asset.bytes || Number(bounds[2]) < Number(bounds[1]) || Number(headers.get("content-length")) !== Number(bounds[2]) - Number(bounds[1]) + 1) return json({ error: "upstream_range_mismatch" }, 502);
    } else if (headers.has("content-length") && Number(headers.get("content-length")) !== asset.bytes) return json({ error: "upstream_length_mismatch" }, 502);
    headers.set("accept-ranges", "bytes");
    headers.set("cache-control", "public, max-age=86400");
    headers.set("x-bted-sha256", asset.sha256);
    headers.set("x-bted-revision", catalogue.revision);
    return new Response(request.method === "HEAD" ? null : upstream.body, { status: upstream.status, headers });
  } catch (error) {
    console.error("BATTER browser:", error.message);
    return json({ error: "batter_data_unavailable" }, 503, { "cache-control": "no-store" });
  }
}

// Views only, following RAPPTOR's document-load and bot filters. No IP, user
// agent, query string, visitor identifier, or individual event is persisted.
const USAGE_RETENTION_DAYS = 400;
const USAGE_RANGES = [7, 30, 90, 365, 0];
const USAGE_BOT = /bot|crawl|spider|slurp|scrape|curl|wget|python-requests|httpx|axios|okhttp|java\/|go-http|libwww|headless|phantomjs|puppeteer|playwright|lighthouse|monitor|uptime|pingdom|preview|facebookexternalhit|embedly|feedfetcher|semrush|ahrefs|archive\.org/i;

function usageDay(time = Date.now()) {
  return new Date(time).toISOString().slice(0, 10);
}

function shiftUsageDay(day, offset) {
  return usageDay(Date.parse(`${day}T00:00:00Z`) + offset * 86400000);
}

function usagePath(request) {
  const path = new URL(request.url).pathname.replace(/\/$/, "") || "/";
  if (path === "/" || path === "/index" || path === "/index.html") return "/";
  if (path === "/genomes" || path === "/genomes.html") return "/genomes";
  if (path === "/methodology" || path === "/methodology.html") return "/methodology";
  const genome = /^\/genomes\/([A-Za-z0-9_.-]+)$/.exec(path);
  const id = genome?.[1].replace(/\.html$/, "");
  return id && !["batter", "genome"].includes(id) ? `/genomes/${id}` : null;
}

function countableUsage(request, response) {
  if (request.method !== "GET" || !usagePath(request)) return false;
  if (response.status !== 200 || !response.headers.get("content-type")?.includes("text/html")) return false;
  const headers = request.headers;
  const agent = headers.get("user-agent");
  if (!agent || agent.length < 8 || USAGE_BOT.test(agent)) return false;
  if (headers.has("range") || headers.has("next-router-prefetch") || headers.has("x-nextjs-data")) return false;
  if (/prefetch|prerender/i.test(`${headers.get("purpose") || ""} ${headers.get("sec-purpose") || ""}`)) return false;
  const destination = headers.get("sec-fetch-dest");
  return destination ? destination === "document" : Boolean(headers.get("accept")?.includes("text/html"));
}

function usageGeo(request) {
  // Only Cloudflare's trusted edge metadata; client geolocation headers are ignored.
  const cf = request.cf || {};
  const raw = typeof cf.country === "string" ? cf.country.toUpperCase() : "";
  const country = /^[A-Z]{2}$/.test(raw) && raw !== "T1" ? raw : "XX";
  const text = (value) => typeof value === "string" ? value.trim().slice(0, 64) : "";
  return { country, region: country === "XX" ? "" : text(cf.region), city: country === "XX" ? "" : text(cf.city) };
}

async function recordUsage(request, env) {
  const geo = usageGeo(request);
  const day = usageDay();
  await env.BTED_DB.batch([
    env.BTED_DB.prepare(`INSERT INTO analytics_daily_geo (day, country_code, region, city, views)
      VALUES (?, ?, ?, ?, 1) ON CONFLICT(day, country_code, region, city)
      DO UPDATE SET views = views + 1`).bind(day, geo.country, geo.region, geo.city),
    env.BTED_DB.prepare(`INSERT INTO analytics_daily_path (day, path, views)
      VALUES (?, ?, 1) ON CONFLICT(day, path) DO UPDATE SET views = views + 1`).bind(day, usagePath(request)),
  ]);
}

function usageCountryName(code) {
  const names = { HK: "Hong Kong, China", MO: "Macao, China", TW: "Taiwan, China", XX: "Unknown" };
  if (names[code]) return names[code];
  try { return new Intl.DisplayNames(["en"], { type: "region" }).of(code) || code; } catch { return code; }
}

async function usageReport(env, url) {
  const value = url.searchParams.get("days") ?? "30";
  if (!USAGE_RANGES.map(String).includes(value)) return json({ error: "invalid_usage_range" }, 400, { "cache-control": "no-store" });
  const days = Number(value);
  const endDay = usageDay();
  const cutoff = shiftUsageDay(endDay, -(USAGE_RETENTION_DAYS - 1));
  const from = days ? shiftUsageDay(endDay, -(days - 1)) : cutoff;
  if (!env.BTED_DB) return json({ error: "usage_unavailable" }, 503, { "cache-control": "no-store" });
  try {
    const [countryRows, cityRows, pathRows, dayRows, boundary] = await env.BTED_DB.batch([
      env.BTED_DB.prepare(`SELECT country_code, SUM(views) AS views FROM analytics_daily_geo
        WHERE day BETWEEN ? AND ? GROUP BY country_code ORDER BY views DESC, country_code`).bind(from, endDay),
      env.BTED_DB.prepare(`SELECT country_code, region, city, SUM(views) AS views FROM analytics_daily_geo
        WHERE day BETWEEN ? AND ? AND city <> '' GROUP BY country_code, region, city
        ORDER BY views DESC, country_code, region, city LIMIT 50`).bind(from, endDay),
      env.BTED_DB.prepare(`SELECT path, SUM(views) AS views FROM analytics_daily_path
        WHERE day BETWEEN ? AND ? GROUP BY path ORDER BY views DESC, path LIMIT 30`).bind(from, endDay),
      env.BTED_DB.prepare(`SELECT day, SUM(views) AS views FROM analytics_daily_geo
        WHERE day BETWEEN ? AND ? GROUP BY day ORDER BY day`).bind(from, endDay),
      env.BTED_DB.prepare("SELECT MIN(day) AS first_day FROM analytics_daily_geo WHERE day BETWEEN ? AND ?").bind(cutoff, endDay),
    ]);
    const views = countryRows.results.reduce((sum, row) => sum + Number(row.views), 0);
    const countries = countryRows.results.map((row) => ({ code: row.country_code, name: usageCountryName(row.country_code), views: Number(row.views), share: views ? Number(row.views) / views : 0 }));
    const firstRecordedDay = boundary.results[0]?.first_day || null;
    const startDay = days ? from : firstRecordedDay || endDay;
    const byDay = new Map(dayRows.results.map((row) => [row.day, Number(row.views)]));
    const daily = [];
    for (let day = startDay; day <= endDay; day = shiftUsageDay(day, 1)) daily.push({ day, views: byDay.get(day) || 0 });
    return json({ rangeDays: days, startDay, endDay, firstRecordedDay, retentionDays: USAGE_RETENTION_DAYS,
      totals: { views, countries: countries.filter((row) => row.code !== "XX").length, activeDays: daily.filter((row) => row.views > 0).length },
      countries, cities: cityRows.results.map((row) => ({ countryCode: row.country_code, countryName: usageCountryName(row.country_code), region: row.region, city: row.city, views: Number(row.views) })),
      paths: pathRows.results.map((row) => ({ path: row.path, views: Number(row.views) })), daily,
    }, 200, { "cache-control": "public, max-age=60" });
  } catch {
    return json({ error: "usage_unavailable" }, 503, { "cache-control": "no-store" });
  }
}

async function purgeUsage(env, time) {
  if (!env.BTED_DB) return;
  const cutoff = shiftUsageDay(usageDay(time), -(USAGE_RETENTION_DAYS - 1));
  await env.BTED_DB.batch([
    env.BTED_DB.prepare("DELETE FROM analytics_daily_geo WHERE day < ?").bind(cutoff),
    env.BTED_DB.prepare("DELETE FROM analytics_daily_path WHERE day < ?").bind(cutoff),
  ]);
}

async function cachedPublicApi(request, ctx, load, env = {}) {
  const url = new URL(request.url);
  const experimentalConfig = /^\/jbrowse\/assemblies\/GCF_\d+\.\d+\.config\.json$/.test(url.pathname);
  const directory = url.pathname === "/api/genome-directory";
  let directoryParams;
  if (directory) { try { directoryParams = directoryQuery(url).query; } catch { return load(); } }
  const fixedMetadata = /^[0-9a-f]{40}$/.test(env.BTED_METADATA_REVISION || "") &&
    (url.pathname === "/api/batter-catalogue" || /^\/api\/batter\/[A-Za-z0-9_.-]{1,128}(?:\/config)?$/.test(url.pathname));
  // Validate before a normalized cache key can hide an invalid request.
  if (fixedMetadata && url.pathname !== "/api/batter-catalogue" &&
      (url.searchParams.has("url") || url.searchParams.has("revision") && url.searchParams.get("revision") !== env.BTED_METADATA_REVISION)) return load();
  const catalogue = url.pathname === "/api/batter-catalogue";
  const pinnedCatalogue = fixedMetadata && catalogue && url.searchParams.get("v") === "1"
    && url.searchParams.get("revision") === env.BTED_METADATA_REVISION
    && url.searchParams.get("annotation") === (env.BTED_ANNOTATION_REVISION || "original");
  const ttl = experimentalConfig ? 300 : directory ? 604800 : fixedMetadata ? (catalogue ? 604800 : 86400) : url.pathname === "/api/usage" ? 60
    : url.pathname === "/api/batter-catalogue" ? 300
    : /^\/api\/(stats|catalogue|sources|assemblies|endpoints)(\/[^/]+(\/jbrowse-config)?)?$/.test(url.pathname) ? 300 : 0;
  const cache = globalThis.caches?.default;
  if (!ttl || request.method !== "GET" || request.headers.has("range") || !cache) return load();
  const keyUrl = new URL(url);
  if (directory) {
    keyUrl.search = "";
    for (const [key, value] of Object.entries(directoryParams)) if (value) keyUrl.searchParams.set(key, String(value));
  }
  if (fixedMetadata) keyUrl.search = "";
  keyUrl.searchParams.set("__bted_cache", directory ? `directory-v3:${env.BTED_METADATA_REVISION}:${env.BTED_ANNOTATION_REVISION || "original"}` : catalogue
    ? `catalogue-v1:${CURRENT_RELEASE_VERSION}:${env.BTED_METADATA_REVISION || "hf"}:${env.BTED_ANNOTATION_REVISION || "original"}`
    : `public-api-20261015-v9:${CURRENT_RELEASE_VERSION}:${env.BTED_METADATA_REVISION || "hf"}:${env.BTED_ANNOTATION_REVISION || "original"}:${env.BTED_RUNTIME_FIELDS || "legacy"}:${BTED_PLUGIN_PATH}`);
  keyUrl.searchParams.sort();
  const key = new Request(keyUrl);
  const cacheControl = `public, max-age=${pinnedCatalogue ? 31536000 : Math.min(ttl, 60)}, s-maxage=${ttl}${pinnedCatalogue ? ", immutable" : ""}`;
  try {
    const hit = await cache.match(key);
    if (hit) {
      const headers = new Headers(hit.headers); headers.set("x-bted-cache", "HIT");
      headers.set("cache-control", cacheControl);
      return new Response(hit.body, { status: hit.status, headers });
    }
  } catch { /* Cache failures must not block the public API. */ }
  const response = await load();
  if (response.status !== 200 || !response.headers.get("content-type")?.startsWith("application/json")
      || /no-store|private/i.test(response.headers.get("cache-control") || "")) return response;
  const headers = new Headers(response.headers);
  headers.set("cache-control", cacheControl);
  headers.set("x-bted-cache", "MISS");
  const cached = new Response(response.body, { status: response.status, headers });
  const task = cache.put(key, cached.clone()).catch(() => {});
  if (ctx?.waitUntil) ctx.waitUntil(task); else await task;
  return cached;
}

export default {
  async scheduled(controller, env, ctx) {
    ctx.waitUntil(purgeUsage(env, controller.scheduledTime));
  },
  async fetch(request, env, ctx) {
    return cachedPublicApi(request, ctx, () => routeRequest(request, env, ctx), env);
  },
};

async function routeRequest(request, env, ctx) {
    const url = new URL(request.url);
    if (!["GET", "HEAD"].includes(request.method)) return json({ error: "method_not_allowed" }, 405, { allow: "GET, HEAD" });
    if (url.pathname.startsWith("/downloads/v0.2.0/")) return retiredReleaseResponse("v0.2.0");
    if (!url.pathname.startsWith("/api/")) {
      const experimentalConfig = /^\/jbrowse\/assemblies\/(GCF_\d+\.\d+)\.config\.json$/.exec(url.pathname);
      if (experimentalConfig) return experimentalBrowserConfig(request, env, experimentalConfig[1]);
      let assetRequest = request;
      const genomePage = /^\/genomes\/([A-Za-z0-9_.-]+)(?:\.html)?$/.exec(url.pathname);
      if (genomePage && !["batter", "genome"].includes(genomePage[1])) {
        const id = genomePage[1].replace(/\.html$/, "");
        try {
          const registry = await genomeBrowserRegistry(request, env);
          if (!registry.experimental?.[id]) {
            const available = env.BTED_METADATA_REVISION
              ? ((await hfGenomeMetadata(env, id))?.catalogue_row || (await hfGenomeMetadata(env, id))?.catalogue_row_json)
              : (await batterCatalogue(request, env)).genomes.has(id);
            if (available) assetRequest = new Request(new URL("/genomes/genome", request.url), request);
          }
        } catch { /* Existing static experimental pages remain available. */ }
      }
      const response = await staticAsset(assetRequest, env);
      if (env.BTED_ANALYTICS === "on" && env.BTED_DB && ctx && countableUsage(request, response)) {
        ctx.waitUntil(recordUsage(request, env).catch(() => console.error("BTED usage write failed")));
      }
      return response;
    }
    if (url.pathname === "/api/usage") return usageReport(env, url);
    if (url.pathname === "/api/genome-directory") return genomeDirectory(request, env, ctx);
    if (url.pathname === "/api/batter-catalogue") return batterCatalogueResponse(request, env);
    const batterMatch = url.pathname.match(/^\/api\/batter\/([^/]+)(?:\/(config|files)(?:\/([^/]+))?)?$/);
    if (batterMatch) return batterApi(request, env, batterMatch);
    const requestedRelease = url.searchParams.get("release_version");
    if (requestedRelease === "v0.2.0") {
      return retiredReleaseResponse(requestedRelease);
    }
    if (requestedRelease && requestedRelease !== CURRENT_RELEASE_VERSION) {
      return json({ error: "release_not_found", release_version: requestedRelease }, 404);
    }
    const selected = await withRelease(env, url);
    if (url.pathname === "/api/health") return selected ? json({ status: "ok", deployment: "cloudflare-worker-d1-preview", release: releasePayload(selected.release) }) : json({ status: "error", error: "release_not_loaded" }, 503);
    if (!selected) return json({ error: "release_not_found" }, 404);
    if (url.pathname === "/api/stats") return stats(env, selected.release);
    if (url.pathname === "/api/catalogue") return catalogue(env, selected.release, url);
    if (url.pathname === "/api/sources") return sourcesList(request, env, selected.release, url);
    if (url.pathname === "/api/assemblies") return assembliesList(env, selected.release, url);
    if (url.pathname === "/api/endpoints") return endpointsList(env, selected.release, url);
    const assetPrefix = url.pathname.startsWith("/api/assets/") ? "/api/assets/" : url.pathname.startsWith("/api/remote-data/") ? "/api/remote-data/" : null;
    if (assetPrefix) {
      const assetKey = decodePath(url.pathname.slice(assetPrefix.length));
      return assetKey ? proxyAsset(request, env, selected.release, assetKey) : json({ error: "invalid_asset_key" }, 400);
    }
    const assemblyMatch = url.pathname.match(/^\/api\/assemblies\/([^/]+)(?:\/jbrowse-config)?$/);
    if (assemblyMatch) {
      const accession = decodePath(assemblyMatch[1]);
      if (!accession) return json({ error: "invalid_assembly_accession" }, 400);
      if (url.pathname.endsWith("/jbrowse-config")) return jbrowseConfig(request, env, selected.release, accession, url.searchParams.get("source_id"));
      const payload = await assemblyPayload(request, env, selected.release, accession);
      if (payload instanceof Response) return payload;
      return payload ? json(payload) : json({ error: "assembly_not_found", accession }, 404);
    }
    const sourceMatch = url.pathname.match(/^\/api\/sources\/([^/]+)$/);
    if (sourceMatch) {
      const sourceId = decodePath(sourceMatch[1]);
      const payload = sourceId ? await sourcePayload(request, env, selected.release, sourceId) : null;
      if (payload instanceof Response) return payload;
      return payload ? json(payload) : json({ error: "source_not_found", source_id: sourceId }, 404);
    }
    const endpointMatch = url.pathname.match(/^\/api\/endpoints\/([^/]+)$/);
    if (endpointMatch) {
      const endId = decodePath(endpointMatch[1]);
      return endId ? endpointDetail(env, selected.release, endId) : json({ error: "invalid_endpoint_id" }, 400);
    }
    return json({ error: "not_found" }, 404);
}
