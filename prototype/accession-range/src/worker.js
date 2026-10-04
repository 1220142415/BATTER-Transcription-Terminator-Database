const PUBLIC_EVIDENCE = new Set([
  "observed_signal",
  "called_endpoint",
  "author_called_endpoint",
  "curated_record",
]);

const CURRENT_RELEASE_VERSION = "v0.4.0";
const RETIRED_RELEASE_ARCHIVE = "data/archive/BTED-v0.2.0.tar.gz";
const DATA_RELEASE_MANIFEST_PATH = "/assets/data-release.json";
const HF_DATA_ASSET_PATTERN = /^https:\/\/huggingface\.co\/datasets\/liurulong\/terminator\/resolve\/([0-9a-f]{40})\/(v0\.3\.0|v0\.4\.0)\/(.+)$/;
const LOCAL_DATA_ASSET_PATTERN = /^downloads\/(v0\.3\.0|v0\.4\.0)\/(.+)$/;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const PLUS_STRAND_COLOR = "#0f766e";
const MINUS_STRAND_COLOR = "#be123c";

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

async function currentRelease(env) {
  return env.BTED_DB.prepare(
    "SELECT * FROM release_versions WHERE release_version = ? AND is_current = 1 LIMIT 1",
  ).bind(CURRENT_RELEASE_VERSION).first();
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
  const asset = manifest.assets[logicalPath];
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
  return env.BTED_DB.prepare(
    "SELECT asset_key, release_version, assembly_accession, source_id, asset_kind, logical_path, origin_host, content_type, byte_size, sha256, supports_range, redistribution_status, is_public FROM assets WHERE asset_key = ? AND release_version = ? AND active = 1 AND is_public = 1",
  ).bind(assetKey, releaseVersion).first();
}

async function allAssets(env, releaseVersion, accession, sourceId) {
  let sql = "SELECT asset_key, release_version, assembly_accession, source_id, asset_kind, logical_path, origin_host, content_type, byte_size, sha256, supports_range, redistribution_status, is_public FROM assets WHERE release_version = ? AND active = 1 AND is_public = 1";
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
  const browserAvailable = trackData.some((track) => track.browser_available);
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
  if (!publicTracks.length) return json({ error: "jbrowse_unavailable", reason: "no public published endpoint track" }, 404);
  const assemblyName = `BTED_${accession.replaceAll(".", "_")}`;
  const gff = assemblyAssets.find((asset) => asset.asset_kind === "gff3"
    && asset.logical_path.startsWith(`assemblies/${accession}/reference/`)
    && Number(asset.is_public) === 1);
  const tbi = assemblyAssets.find((asset) => asset.asset_kind === "tbi" && Number(asset.is_public) === 1);
  const browserGff = assemblyAssets.find((asset) => asset.asset_kind === "gff3"
    && asset.logical_path === `browser/${accession}/annotation.gff3`
    && Number(asset.is_public) === 1);
  const contig = await env.BTED_DB.prepare("SELECT contig_accession, length_bp FROM contigs WHERE release_version = ? AND assembly_accession = ? ORDER BY length_bp DESC, contig_accession ASC LIMIT 1").bind(release.release_version, accession).first();
  if (!contig) return json({ error: "jbrowse_unavailable", reason: "reference sequences are not registered for this assembly" }, 404);
  const contigName = contig.contig_accession;
  const length = Number(contig.length_bp);
  const firstEndpoint = await env.BTED_DB.prepare("SELECT biological_coordinate_1based FROM endpoints WHERE release_version = ? AND reference_assembly = ? AND reference_name = ? ORDER BY biological_coordinate_1based, end_id LIMIT 1").bind(release.release_version, accession, contigName).first();
  const initialStart = firstEndpoint ? Math.max(0, Number(firstEndpoint.biological_coordinate_1based) - 501) : 0;
  const initialEnd = Math.min(length, initialStart + (firstEndpoint ? 1000 : 10000));
  const initialBpPerPx = Math.max(0.001, (initialEnd - initialStart) / 1000);
  const tracksConfig = [];
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
          ? "Paper-reported transcript 3′ end; not proof of terminator function."
          : "Literature-curated 3′ end; BTED did not re-call this position from reads.",
        limitations,
        raw_data_accessions: rawAccessions.map((item) => item.accession).join(", "),
        raw_data_url: rawAccessions.map((item) => item.external_url).find(Boolean) || "",
        gff3_url: source.record_root ? dataAssetUrl(dataManifest, source.record_root, request) : "",
        explanation: "Records from different studies remain separate even at the same coordinate.",
      },
    };
    if (endpointGff3) {
      const grouped = endpointTracks.get(endpointGff3.logical_path);
      grouped[grouped.length - 1].about = metadata.btedAbout;
    }
    const signalPlus = sourceAssets.find((asset) => asset.asset_kind === "bigwig" && asset.logical_path.endsWith("signal.forward.bw") && Number(asset.is_public) === 1);
    const signalMinus = sourceAssets.find((asset) => asset.asset_kind === "bigwig" && asset.logical_path.endsWith("signal.reverse.bw") && Number(asset.is_public) === 1);
    if (signalPlus && signalMinus) {
      const signalId = `${track.track_id}_mirrored_signal`;
      tracksConfig.push({
        type: "MultiQuantitativeTrack",
        trackId: signalId,
        name: `${source.source_id} · experimental signal (+ / −)`,
        adapter: { type: "MultiWiggleAdapter", subadapters: [
          { type: "BigWigAdapter", source: "plus", name: "+ strand", color: PLUS_STRAND_COLOR, bigWigLocation: { uri: assetUrl(request, signalPlus.asset_key), locationType: "UriLocation" } },
          { type: "BigWigAdapter", source: "minus", name: "− strand", color: MINUS_STRAND_COLOR, bigWigLocation: { uri: assetUrl(request, signalMinus.asset_key), locationType: "UriLocation" } },
        ] },
        category: ["BTED experimental signal", source.source_id],
        assemblyNames: [assemblyName],
        metadata: {
          ...metadata, signal_values: "Raw BigWig values; mirrored only for display", strand: "+ / −", btedMirroredSignal: true,
          btedDownloads: [
            { kind: "bigwig", label: "+ strand BigWig", url: assetUrl(request, signalPlus.asset_key), filename: `${source.source_id}.signal.forward.bw` },
            { kind: "bigwig", label: "− strand BigWig", url: assetUrl(request, signalMinus.asset_key), filename: `${source.source_id}.signal.reverse.bw` },
          ],
          btedAbout: {
            ...metadata.btedAbout, kind: "signal", strand: "+ / −",
            record_count: "",
            explanation: "Measured signal from the study. The graph mirrors + and − around zero; the original BigWig values are unchanged. This track does not mark called 3′ ends.",
          },
        },
        displays: [{
          type: "MultiLinearWiggleDisplay", displayId: `${signalId}_display`, defaultRendering: "xyplot", height: 180,
        }],
      });
    }
  }
  for (const [logicalPath, studyTracks] of endpointTracks) {
    const first = studyTracks[0];
    const sourceIds = studyTracks.map(({ source: sourceItem }) => sourceItem.source_id);
    const assays = [...new Set(studyTracks.map(({ track: trackItem }) => trackItem.assay).filter(Boolean))];
    const publicationTitles = [...new Set(studyTracks.map(({ track: trackItem }) => trackItem.paper_title).filter(Boolean))];
    const pmids = [...new Set(studyTracks.map(({ track: trackItem }) => trackItem.pmid).filter(Boolean))];
    const rawAccessions = [...new Set(studyTracks.flatMap(({ rawAccessions: values }) => values.map((item) => item.accession).filter(Boolean)))];
    const endpointTrackId = `source_${sourceIds[0].replace(/[^A-Za-z0-9_]/g, "_")}_endpoints`;
    const evidenceClasses = [...new Set(studyTracks.map(({ source: sourceItem }) => sourceItem.evidence_class).filter(Boolean))];
    const metadata = {
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
      name: `${sourceIds.join(", ")} · PMID ${pmids.join(", ")} · ${assays.join(" / ")} endpoints`,
      adapter: { type: "Gff3Adapter", gffLocation: { uri: first.endpointGff3Url, locationType: "UriLocation" } },
      category: ["BTED endpoint tracks", ...sourceIds],
      assemblyNames: [assemblyName],
      metadata,
      displays: [{
        type: "LinearBasicDisplay", displayId: `${endpointTrackId}_display`, showLabels: false, height: 64,
        renderer: { type: "SvgFeatureRenderer", color1: "jexl:btedStrandColor(feature)", color2: "jexl:btedStrandColor(feature)", height: 14 },
      }],
    });
  }
  const configTracks = [];
  if (gff && tbi) {
    configTracks.push({
      type: "FeatureTrack",
      trackId: `${assemblyName}_genes`,
      name: "Reference gene annotation",
      adapter: { type: "Gff3TabixAdapter", gffGzLocation: { uri: assetUrl(request, gff.asset_key), locationType: "UriLocation" }, index: { location: { uri: assetUrl(request, tbi.asset_key), locationType: "UriLocation" }, indexType: "TBI" } },
      displays: [{ type: "LinearBasicDisplay", displayId: `${assemblyName}_genes-LinearBasicDisplay`, height: 130, renderer: { type: "SvgFeatureRenderer", color1: "jexl:btedStrandColor(feature)", color2: "jexl:btedStrandColor(feature)" } }],
      category: ["Reference annotation"],
      assemblyNames: [assemblyName],
      metadata: {
        release_version: release.release_version, gff3_sha256: gff.sha256, tbi_sha256: tbi.sha256,
        btedDownloads: [{ kind: "reference", label: "Reference annotation GFF3", url: assetUrl(request, gff.asset_key), filename: `${accession}.genes.gff3.gz` }],
        btedAbout: {
          kind: "reference", assembly: accession,
          reference: `${assembly.display_name || assembly.organism_name} · ${accession}`,
          reference_name: contigName,
          annotation_version: `GFF3 SHA-256 ${gff.sha256.slice(0, 16)}`,
          reference_url: `https://www.ncbi.nlm.nih.gov/datasets/genome/${encodeURIComponent(accession)}/`,
          explanation: "NCBI-derived gene annotation for the displayed reference assembly.",
        },
      },
    });
  } else if (browserGff) {
    configTracks.push({
      type: "FeatureTrack",
      trackId: `${assemblyName}_genes`,
      name: "Reference gene annotation",
      adapter: { type: "Gff3Adapter", gffLocation: { uri: assetUrl(request, browserGff.asset_key), locationType: "UriLocation" } },
      displays: [{ type: "LinearBasicDisplay", displayId: `${assemblyName}_genes-LinearBasicDisplay`, height: 130, renderer: { type: "SvgFeatureRenderer", color1: "jexl:btedStrandColor(feature)", color2: "jexl:btedStrandColor(feature)" } }],
      category: ["Reference annotation"],
      assemblyNames: [assemblyName],
      metadata: {
        release_version: release.release_version, gff3_sha256: browserGff.sha256,
        btedDownloads: [{ kind: "reference", label: "Reference annotation GFF3", url: assetUrl(request, browserGff.asset_key), filename: `${accession}.genes.gff3` }],
        btedAbout: {
          kind: "reference", assembly: accession,
          reference: `${assembly.display_name || assembly.organism_name} · ${accession}`,
          reference_name: contigName,
          annotation_version: `GFF3 SHA-256 ${browserGff.sha256.slice(0, 16)}`,
          reference_url: `https://www.ncbi.nlm.nih.gov/datasets/genome/${encodeURIComponent(accession)}/`,
          explanation: "NCBI-derived gene annotation for the displayed reference assembly.",
        },
      },
    });
  }
  configTracks.push(...tracksConfig);
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
  return json({
    plugins: [{ name: "BTEDTrackPlugin", esmUrl: new URL("/jbrowse/plugins/bted-track-plugin.js", request.url).href }],
    assemblies: [{ name: assemblyName, displayName: `${assembly.display_name || assembly.organism_name} (${accession})`, sequence: { type: "ReferenceSequenceTrack", name: "Reference sequence", trackId: `${assemblyName}_refseq`, adapter: { type: "IndexedFastaAdapter", fastaLocation: { uri: assetUrl(request, fasta.asset_key), locationType: "UriLocation" }, faiLocation: { uri: assetUrl(request, fai.asset_key), locationType: "UriLocation" } } } }],
    tracks: configTracks,
    defaultSession: { name: `BTED · ${accession}`, views: [{ id: "bted_linear_genome_view", type: "LinearGenomeView", name: assembly.organism_name || accession, offsetPx: initialStart / initialBpPerPx, bpPerPx: initialBpPerPx, displayedRegions: [{ refName: contigName, start: 0, end: length, reversed: false, assemblyName }], tracks: sessionTracks }] },
    metadata: { release_version: release.release_version, assembly_accession: accession, source_ids: publicTracks.map(({ source }) => source.source_id), browser_asset_origin: release.asset_origin_status },
  });
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
  if (env.ASSETS && typeof env.ASSETS.fetch === "function") return env.ASSETS.fetch(request);
  return json({ error: "static_assets_not_configured" }, 404);
}

const BATTER_FILES = new Set(["reference.fa.gz", "reference.fa.gz.fai", "reference.fa.gz.gzi", "augmentation.gff3.gz", "augmentation.gff3.gz.tbi", "prediction.gff3.gz", "prediction.gff3.gz.tbi", "genes.gff3.gz", "genes.gff3.gz.tbi"]);
const batterCatalogues = new WeakMap();

async function batterCatalogue(request, env) {
  if (!batterCatalogues.has(env.ASSETS)) {
    const task = env.ASSETS.fetch(new Request(new URL("/assets/batter-browser.json", request.url))).then(async response => {
      if (!response.ok) throw new Error("catalogue_unavailable");
      const data = await response.json();
      if (!/^[0-9a-f]{40}$/.test(data.revision) || !Array.isArray(data.genomes)) throw new Error("catalogue_invalid");
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
    .map(track => ({ ...track, assemblyNames: [id] }));
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
  if (augmented || counts.otu_augmentation_window || counts.rfam_training_window) {
    const bytes = await batterFileBytes(uri("augmentation.gff3.gz").uri, metadata.files["augmentation.gff3.gz"]);
    // BGZF contains concatenated gzip members; Workers' DecompressionStream rejects the trailing members.
    const { gunzipSync } = await import("node:zlib");
    const text = gunzipSync(new Uint8Array(bytes)).toString("utf8");
    const first = text.split(/\r?\n/).find(line => line && !line.startsWith("#"));
    if (!first) throw new Error("augmentation_records_missing");
    const fields = first.split("\t");
    if (fields.length !== 9 || !contigs.has(fields[0]) || Number(fields[3]) < 1 || Number(fields[4]) > contigs.get(fields[0])) throw new Error("augmentation_reference_mismatch");
    ref = fields[0]; start = Math.max(0, Number(fields[3]) - 201);
  }
  const tracks = [];
  function addTrack(trackId, name, file, renderer, height, explanation) {
    tracks.push({ type: "FeatureTrack", trackId, name, assemblyNames: [id], category: [trackId === "batter_prediction" ? "Model prediction" : trackId === "batter_genes" ? "Reference annotation" : "Training augmentation"],
      adapter: { type: "Gff3TabixAdapter", gffGzLocation: uri(file), index: { location: uri(file + ".tbi"), indexType: "TBI" } },
      displays: [{ type: "LinearBasicDisplay", displayId: trackId + "_display", height, showLabels: false, renderer: { type: "SvgFeatureRenderer", ...renderer } }],
      metadata: { btedAbout: { kind: trackId === "batter_genes" ? "reference" : "augmentation", title: "BATTER", assembly: id, evidence: "Computational training augmentation", record_count: augmented, explanation, doi_url: "https://doi.org/10.1186/s40168-026-02454-1", gff3_url: uri(file).uri },
        btedDownloads: [{ kind: "reference", label: name + " GFF3", url: uri(file).uri, filename: id + "." + file }] } });
  }
  if (metadata.annotation.status === "matched" && metadata.browser_files["genes.gff3.gz"] && metadata.browser_files["genes.gff3.gz.tbi"]) {
    addTrack("batter_genes", "Reference gene annotation", "genes.gff3.gz", { color1: "jexl:btedStrandColor(feature)", color2: "jexl:btedStrandColor(feature)" }, 130, "Gene annotation matched to this reference.");
  }
  if (augmented || counts.otu_augmentation_window || counts.rfam_training_window) {
    addTrack("batter_augmentation", "Training windows and terminator spans", "augmentation.gff3.gz", { color1: "jexl:btedAugmentationColor(feature)", color2: "jexl:btedAugmentationColor(feature)", height: 14 }, 140, "Dark blue: OTU augmented spans. Purple: Rfam training spans. Pale: sequence windows. Windows are context, not additional terminators.");
  }
  if (counts.tes_prediction > 0) {
    addTrack("batter_prediction", "BATTER · predicted terminator regions", "prediction.gff3.gz", { color1: "#d97706", color2: "#d97706", height: 14 }, 100, "Published BATTER-TPE genome-wide predictions. Scores are model outputs.");
    const about = tracks.at(-1).metadata.btedAbout;
    about.kind = "prediction"; about.evidence = "Model prediction"; about.record_count = counts.tes_prediction;
  }
  const sessionTracks = [{ id: "batter_sequence", type: "ReferenceSequenceTrack", configuration: reference.trackId, displays: [{ type: "LinearReferenceSequenceDisplay", configuration: reference.trackId + "-LinearReferenceSequenceDisplay", showTranslation: true, heightPreConfig: 120 }] },
    ...tracks.map(track => ({ id: track.trackId, type: "FeatureTrack", configuration: track.trackId, displays: [{ type: "LinearBasicDisplay", configuration: track.displays[0].displayId }] }))];
  return { plugins: [{ name: "BTEDTrackPlugin", esmUrl: new URL("/jbrowse/plugins/bted-track-plugin.js", request.url).href }],
    assemblies: [{ name: id, sequence: reference }], tracks,
    defaultSession: { name: "BTED genome · " + id, views: [{ id: "batter_view", type: "LinearGenomeView", bpPerPx: 1, offsetPx: start, displayedRegions: [{ refName: ref, start: 0, end: contigs.get(ref), assemblyName: id, reversed: false }], tracks: sessionTracks }] },
    metadata: { revision: metadata.revision } };
}

async function batterApi(request, env, match) {
  const url = new URL(request.url), id = decodePath(match[1]);
  if (!id || !/^[A-Za-z0-9_.-]{1,128}$/.test(id) || url.searchParams.has("url")) return json({ error: "invalid_genome_request" }, 400);
  try {
    const catalogue = await batterCatalogue(request, env);
    const row = catalogue.genomes.get(id);
    if (!row) return json({ error: "genome_not_indexed" }, 404);
    if (url.searchParams.has("revision") && url.searchParams.get("revision") !== catalogue.revision) return json({ error: "revision_changed_reload_page" }, 409);
    const base = `https://huggingface.co/datasets/liurulong/terminator/resolve/${catalogue.revision}/v0.5.0/batter/batches/${row[1]}/genomes/${encodeURIComponent(id)}/`;
    const response = await fetch(base + "metadata.json", { cf: { cacheTtl: 86400, cacheEverything: true } });
    if (!response.ok) return json({ error: "genome_upload_unavailable" }, 503, { "cache-control": "no-store" });
    const metadata = await response.json();
    if (metadata.genome_id !== id || metadata.batch !== row[1] || metadata.otu_id !== row[2] || !metadata.feature_counts || !metadata.reference || !metadata.annotation || !metadata.files) throw new Error("metadata_mismatch");
    metadata.revision = catalogue.revision;
    metadata.browser_files = {};
    for (const [file, entry] of Object.entries(metadata.files)) {
      if (!BATTER_FILES.has(file)) continue;
      if (!Number.isSafeInteger(entry.bytes) || entry.bytes < 0 || !SHA256_PATTERN.test(entry.sha256)) throw new Error("metadata_invalid_file");
      metadata.browser_files[file] = { ...entry, url: base + file, fallback_url: `/api/batter/${encodeURIComponent(id)}/files/${file}?revision=${catalogue.revision}` };
    }
    for (const file of ["reference.fa.gz", "reference.fa.gz.fai", "reference.fa.gz.gzi"]) if (!metadata.browser_files[file]) throw new Error("reference_not_uploaded");
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
      }
      return json(config, 200, { "cache-control": "no-cache" });
    }
    if (match[2] !== "files") return json(metadata, 200, { "cache-control": "no-cache" });
    const file = decodePath(match[3]);
    const asset = metadata.browser_files[file];
    if (!asset) return json({ error: "file_not_registered" }, 404);
    const range = request.headers.get("range");
    if (range && !/^bytes=(?:\d+-\d*|-\d+)$/.test(range)) return json({ error: "invalid_range" }, 416);
    const upstream = await fetch(asset.url, { method: request.method, headers: range ? { range } : {} });
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

export default {
  async scheduled(controller, env, ctx) {
    ctx.waitUntil(purgeUsage(env, controller.scheduledTime));
  },
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (!["GET", "HEAD"].includes(request.method)) return json({ error: "method_not_allowed" }, 405, { allow: "GET, HEAD" });
    if (url.pathname.startsWith("/downloads/v0.2.0/")) return retiredReleaseResponse("v0.2.0");
    if (!url.pathname.startsWith("/api/")) {
      let assetRequest = request;
      const genomePage = /^\/genomes\/([A-Za-z0-9_.-]+)(?:\.html)?$/.exec(url.pathname);
      if (genomePage && !["batter", "genome"].includes(genomePage[1])) {
        const id = genomePage[1].replace(/\.html$/, "");
        try {
          const catalogue = await batterCatalogue(request, env);
          if (catalogue.genomes.has(id)) {
            const registry = await genomeBrowserRegistry(request, env);
            if (!registry.experimental?.[id]) assetRequest = new Request(new URL("/genomes/genome", request.url), request);
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
  },
};
