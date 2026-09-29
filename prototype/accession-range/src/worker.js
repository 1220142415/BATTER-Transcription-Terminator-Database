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
  const { used_for_batter_augmentation: _unusedAugmentationFlag, ...publicSource } = source;
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
    const { used_for_batter_augmentation: _unusedAugmentationFlag, ...publicRow } = row;
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
  const firstEndpoint = await env.BTED_DB.prepare("SELECT biological_coordinate_1based FROM endpoints WHERE release_version = ? AND reference_assembly = ? AND reference_name = ? ORDER BY biological_coordinate_1based, end_id LIMIT 1").bind(release.release_version, accession, contigName).first();
  const length = Number(contig.length_bp);
  const regionStart = firstEndpoint ? Math.max(0, Number(firstEndpoint.biological_coordinate_1based) - 501) : 0;
  const regionEnd = Math.min(length, regionStart + (firstEndpoint ? 1000 : 10000));
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
        type: "LinearBasicDisplay", displayId: `${endpointTrackId}_display`, showLabels: false, height: 44,
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
      displays: [{ type: "LinearBasicDisplay", displayId: `${assemblyName}_genes-LinearBasicDisplay`, renderer: { type: "SvgFeatureRenderer", color1: "jexl:btedStrandColor(feature)", color2: "jexl:btedStrandColor(feature)" } }],
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
      displays: [{ type: "LinearBasicDisplay", displayId: `${assemblyName}_genes-LinearBasicDisplay`, renderer: { type: "SvgFeatureRenderer", color1: "jexl:btedStrandColor(feature)", color2: "jexl:btedStrandColor(feature)" } }],
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
  return json({
    plugins: [{ name: "BTEDTrackPlugin", esmUrl: new URL("/jbrowse/plugins/bted-track-plugin.js", request.url).href }],
    assemblies: [{ name: assemblyName, displayName: `${assembly.display_name || assembly.organism_name} (${accession})`, sequence: { type: "ReferenceSequenceTrack", trackId: `${assemblyName}_refseq`, adapter: { type: "IndexedFastaAdapter", fastaLocation: { uri: assetUrl(request, fasta.asset_key), locationType: "UriLocation" }, faiLocation: { uri: assetUrl(request, fai.asset_key), locationType: "UriLocation" } } } }],
    tracks: configTracks,
    defaultSession: { name: `BTED · ${accession}`, views: [{ id: "bted_linear_genome_view", type: "LinearGenomeView", name: assembly.organism_name || accession, offsetPx: 0, bpPerPx: Math.max(0.001, (regionEnd - regionStart) / 1000), displayedRegions: [{ refName: contigName, start: regionStart, end: regionEnd, reversed: false, assemblyName }], tracks: sessionTracks }] },
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

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!["GET", "HEAD"].includes(request.method)) return json({ error: "method_not_allowed" }, 405, { allow: "GET, HEAD" });
    if (url.pathname.startsWith("/downloads/v0.2.0/")) return retiredReleaseResponse("v0.2.0");
    if (!url.pathname.startsWith("/api/")) return staticAsset(request, env);
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
