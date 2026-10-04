const PUBLIC_EVIDENCE = new Set([
  "observed_signal",
  "called_endpoint",
  "author_called_endpoint",
  "curated_record",
]);

const CURRENT_RELEASE_VERSION = "v0.4.0";
function activeReleaseVersion(env) {
  return env.BTED_RELEASE_VERSION === "v0.5.0" ? "v0.5.0" : CURRENT_RELEASE_VERSION;
}
const RETIRED_RELEASE_ARCHIVE = "data/archive/BTED-v0.2.0.tar.gz";
const DATA_RELEASE_MANIFEST_PATH = "/assets/data-release.json";
const HF_DATA_ASSET_PATTERN = /^https:\/\/huggingface\.co\/datasets\/liurulong\/terminator\/resolve\/([0-9a-f]{40})\/(v0\.3\.0|v0\.4\.0|v0\.5\.0)\/(.+)$/;
const LOCAL_DATA_ASSET_PATTERN = /^downloads\/(v0\.3\.0|v0\.4\.0|v0\.5\.0)\/(.+)$/;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const PLUS_STRAND_COLOR = "#0f766e";
const MINUS_STRAND_COLOR = "#be123c";
const BATTER_TAXONOMY_RANKS = ["phylum", "class", "order", "family", "genus", "species"];
const BATTER_PAGE_SIZES = new Set([25, 50, 100]);
const BATTER_RELEASE_FILES = new Set(["reference.fa.gz", "reference.fa.gz.fai", "reference.fa.gz.gzi", "prediction.gff3.gz", "prediction.gff3.gz.tbi", "augmentation.gff3.gz", "augmentation.gff3.gz.tbi", "genes.gff3.gz", "genes.gff3.gz.tbi"]);

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

function batterFilters(url, { facetRank = null } = {}) {
  const clauses = [];
  const params = [];
  const q = (url.searchParams.get("q") || "").trim();
  if (q) {
    if (q.length > 160) return { error: bad("invalid_search", "q must be 160 characters or fewer", "q") };
    clauses.push("search_text LIKE ?");
    params.push(`%${q}%`);
  }
  for (const [parameter, column] of [["source", "source_collection"], ["type", "genome_type"]]) {
    const value = (url.searchParams.get(parameter) || "").trim();
    if (value) {
      clauses.push(`${column} = ?`);
      params.push(value);
    }
  }
  const rankLimit = facetRank ? BATTER_TAXONOMY_RANKS.indexOf(facetRank) : BATTER_TAXONOMY_RANKS.length;
  for (const [index, rank] of BATTER_TAXONOMY_RANKS.entries()) {
    if (index >= rankLimit) break;
    const value = (url.searchParams.get(rank) || "").trim();
    if (value) {
      clauses.push(`${rank === "order" ? '"order"' : rank} = ?`);
      params.push(value);
    }
  }
  return { clauses, params };
}

async function batterStats(env) {
  const [summary, types, sources] = await Promise.all([
    env.BTED_DB.prepare(`SELECT COUNT(*) AS genome_count,
      COALESCE(SUM(tes_prediction), 0) AS prediction_count,
      COALESCE(SUM(CASE WHEN augmentation_status = 'has_features' THEN 1 ELSE 0 END), 0) AS augmented_genome_count,
      COALESCE(SUM(otu_augmentation_span), 0) AS otu_augmentation_count,
      COALESCE(SUM(rfam_training_span), 0) AS rfam_training_count,
      COALESCE(SUM(CASE WHEN augmentation_status = 'no_records_in_source' THEN 1 ELSE 0 END), 0) AS no_augmentation_genome_count
      FROM batter_genomes`).first(),
    env.BTED_DB.prepare(`SELECT genome_type AS value, COUNT(*) AS count FROM batter_genomes
      GROUP BY genome_type ORDER BY genome_type`).all(),
    env.BTED_DB.prepare(`SELECT source_collection AS value, COUNT(*) AS count FROM batter_genomes
      GROUP BY source_collection ORDER BY source_collection`).all(),
  ]);
  return json({ ...summary, genome_types: types.results || [], source_collections: sources.results || [] });
}

async function batterFacets(env, url) {
  const rank = url.searchParams.get("rank") || "";
  if (!BATTER_TAXONOMY_RANKS.includes(rank)) return bad("invalid_taxonomy_rank", "rank must be a supported taxonomy rank", "rank");
  const filters = batterFilters(url, { facetRank: rank });
  if (filters.error) return filters.error;
  const column = rank === "order" ? '"order"' : rank;
  const where = [...filters.clauses, `${column} <> ''`].join(" AND ");
  const rows = await env.BTED_DB.prepare(`SELECT ${column} AS value, COUNT(*) AS count
    FROM batter_genomes
    WHERE ${where}
    GROUP BY ${column} ORDER BY ${column} COLLATE NOCASE LIMIT 5000`)
    .bind(...filters.params)
    .all();
  return json({ rank, options: rows.results || [] });
}

async function batterGenomeList(env, url) {
  const pagination = pageParams(url);
  if (pagination.error) return pagination.error;
  if (!BATTER_PAGE_SIZES.has(pagination.pageSize)) return bad("invalid_pagination", "page_size must be 25, 50, or 100", "page_size");
  const filters = batterFilters(url);
  if (filters.error) return filters.error;
  const orderBy = {
    genome_id_asc: "genome_id COLLATE NOCASE ASC",
    genome_id_desc: "genome_id COLLATE NOCASE DESC",
    predictions_desc: "tes_prediction DESC",
    predictions_asc: "tes_prediction ASC",
    otu_augmentation_desc: "otu_augmentation_span DESC",
    otu_augmentation_asc: "otu_augmentation_span ASC",
    rfam_training_desc: "rfam_training_span DESC",
    rfam_training_asc: "rfam_training_span ASC",
  }[url.searchParams.get("sort") || "genome_id_asc"];
  if (!orderBy) return bad("invalid_sort", "sort is not supported", "sort");
  const where = filters.clauses.length ? `WHERE ${filters.clauses.join(" AND ")}` : "";
  const [count, result] = await Promise.all([
    env.BTED_DB.prepare(`SELECT COUNT(*) AS total FROM batter_genomes ${where}`).bind(...filters.params).first(),
    env.BTED_DB.prepare(`SELECT genome_id, otu_id, genome_type, source_collection, phylum, class, genus, species,
      tes_prediction, otu_augmentation_span, rfam_training_span, augmentation_status
      FROM batter_genomes ${where} ORDER BY ${orderBy}, genome_id COLLATE NOCASE ASC LIMIT ? OFFSET ?`)
      .bind(...filters.params, pagination.pageSize, pagination.offset).all(),
  ]);
  return json({
    ...pageResult(result.results || [], pagination.page, pagination.pageSize, Number(count?.total || 0)),
    sort: url.searchParams.get("sort") || "genome_id_asc",
  });
}

async function batterGenomeDetail(env, genomeId) {
  if (!/^[A-Za-z0-9._-]{1,96}$/.test(genomeId)) return bad("invalid_genome_id", "genome_id is invalid", "genome_id");
  const row = await env.BTED_DB.prepare("SELECT * FROM batter_genomes WHERE genome_id = ? LIMIT 1").bind(genomeId).first();
  return row ? json({ data: row }) : json({ error: "genome_not_found", genome_id: genomeId }, 404);
}

function unifiedGenomeFilters(url, releaseVersion, { facetRank = null } = {}) {
  const clauses = [];
  const params = [];
  // Like RAPPTOR, taxonomy choices depend only on the selected parent ranks.
  // List queries continue to apply every catalogue filter.
  const filterParams = facetRank ? new URLSearchParams() : url.searchParams;
  const q = (filterParams.get("q") || "").trim();
  if (q) {
    if (q.length > 160) return { error: bad("invalid_search", "q must be 160 characters or fewer", "q") };
    clauses.push(`(COALESCE(b.search_text, '') LIKE ? OR COALESCE(a.accession, '') LIKE ?
      OR COALESCE(a.organism_name, '') LIKE ? OR COALESCE(a.strain, '') LIKE ?
      OR EXISTS (SELECT 1 FROM tracks t LEFT JOIN publications p ON p.pmid = t.pmid
        WHERE t.release_version = ? AND t.assembly_accession = a.accession
        AND (t.source_id LIKE ? OR t.assay LIKE ? OR COALESCE(p.pmid, '') LIKE ? OR COALESCE(p.paper_title, '') LIKE ?)))`);
    const pattern = `%${q}%`;
    params.push(pattern, pattern, pattern, pattern, releaseVersion, pattern, pattern, pattern, pattern);
  }
  const membership = (filterParams.get("membership") || "").trim();
  if (membership === "experimental") clauses.push("a.accession IS NOT NULL AND b.genome_id IS NULL");
  else if (membership === "batter") clauses.push("b.genome_id IS NOT NULL AND a.accession IS NULL");
  else if (membership === "both") clauses.push("a.accession IS NOT NULL AND b.genome_id IS NOT NULL");
  else if (membership && membership !== "all") return { error: bad("invalid_membership", "membership must be experimental, batter, or both", "membership") };

  // Evidence filters are inclusive; legacy membership remains exclusive.
  const evidence = filterParams.get("evidence") || "all";
  if (evidence === "experimental") clauses.push("a.accession IS NOT NULL");
  else if (evidence === "prediction") clauses.push("b.genome_id IS NOT NULL");
  else if (evidence === "both") clauses.push("a.accession IS NOT NULL AND b.genome_id IS NOT NULL");
  else if (evidence !== "all") return { error: bad("invalid_evidence", "evidence must be all, experimental, prediction, or both", "evidence") };
  const bigwig = filterParams.get("has_bigwig");
  if (bigwig !== null && !["true", "false", "1", "0"].includes(bigwig)) return { error: bad("invalid_bigwig", "has_bigwig must be true or false", "has_bigwig") };
  if (bigwig !== null) {
    clauses.push(`${["false", "0"].includes(bigwig) ? "NOT " : ""}EXISTS (SELECT 1 FROM assets signal
      WHERE signal.release_version = ? AND signal.assembly_accession = g.genome_id AND signal.asset_kind = 'bigwig' AND signal.active = 1)`);
    params.push(releaseVersion);
  }

  for (const [parameter, column] of [["source", "b.source_collection"], ["type", "b.genome_type"]]) {
    const value = (filterParams.get(parameter) || "").trim();
    if (value) {
      clauses.push(`${column} = ?`);
      params.push(value);
    }
  }
  const rankLimit = facetRank ? BATTER_TAXONOMY_RANKS.indexOf(facetRank) : BATTER_TAXONOMY_RANKS.length;
  for (const [index, rank] of BATTER_TAXONOMY_RANKS.entries()) {
    if (index >= rankLimit) break;
    const value = (url.searchParams.get(rank) || "").trim();
    if (value) {
      clauses.push(`b.${rank === "order" ? '"order"' : rank} = ?`);
      params.push(value);
    }
  }
  return { clauses, params };
}

const UNIFIED_GENOME_IDS = `WITH genome_ids(genome_id) AS (
  SELECT accession FROM assemblies WHERE release_version = ?
  UNION
  SELECT genome_id FROM batter_genomes
)`;

const UNIFIED_GENOME_JOINS = `
  FROM genome_ids g
  LEFT JOIN assemblies a ON a.release_version = ? AND a.accession = g.genome_id
  LEFT JOIN batter_genomes b ON b.genome_id = g.genome_id`;

async function unifiedGenomeStats(env, releaseVersion) {
  const [summary, types, sources] = await Promise.all([
    env.BTED_DB.prepare(`SELECT
      (SELECT COUNT(*) FROM assemblies WHERE release_version = ?) AS experimental_genome_count,
      (SELECT COUNT(*) FROM batter_genomes) AS batter_genome_count,
      (SELECT COUNT(*) FROM batter_genomes b INNER JOIN assemblies a ON a.release_version = ? AND a.accession = b.genome_id) AS both_genome_count,
      (SELECT COUNT(*) FROM batter_genomes WHERE augmentation_status = 'no_records_in_source') AS no_augmentation_genome_count,
      (SELECT COUNT(*) FROM tracks WHERE release_version = ?) AS experimental_track_count,
      (SELECT COUNT(*) FROM endpoints WHERE release_version = ?) AS experimental_endpoint_count`)
      .bind(releaseVersion, releaseVersion, releaseVersion, releaseVersion).first(),
    env.BTED_DB.prepare(`SELECT genome_type AS value, COUNT(*) AS count FROM batter_genomes
      GROUP BY genome_type ORDER BY genome_type`).all(),
    env.BTED_DB.prepare(`SELECT source_collection AS value, COUNT(*) AS count FROM batter_genomes
      GROUP BY source_collection ORDER BY source_collection`).all(),
  ]);
  const experimental = Number(summary?.experimental_genome_count || 0);
  const batter = Number(summary?.batter_genome_count || 0);
  const both = Number(summary?.both_genome_count || 0);
  return json({
    genome_count: experimental + batter - both,
    experimental_genome_count: experimental,
    batter_genome_count: batter,
    both_genome_count: both,
    experimental_only_genome_count: experimental - both,
    batter_only_genome_count: batter - both,
    no_augmentation_genome_count: Number(summary?.no_augmentation_genome_count || 0),
    experimental_track_count: Number(summary?.experimental_track_count || 0),
    experimental_endpoint_count: Number(summary?.experimental_endpoint_count || 0),
    genome_types: types.results || [],
    source_collections: sources.results || [],
  });
}

async function unifiedGenomeFacets(env, url, releaseVersion) {
  const rank = url.searchParams.get("rank") || "";
  if (!BATTER_TAXONOMY_RANKS.includes(rank)) return bad("invalid_taxonomy_rank", "rank must be a supported taxonomy rank", "rank");
  const filters = unifiedGenomeFilters(url, releaseVersion, { facetRank: rank });
  if (filters.error) return filters.error;
  const column = rank === "order" ? 'b."order"' : `b.${rank}`;
  const where = [...filters.clauses, `${column} <> ''`].join(" AND ");
  const rows = await env.BTED_DB.prepare(`${UNIFIED_GENOME_IDS}
    SELECT ${column} AS value, COUNT(*) AS count ${UNIFIED_GENOME_JOINS}
    WHERE ${where} GROUP BY ${column} ORDER BY ${column} COLLATE NOCASE LIMIT 5000`)
    .bind(releaseVersion, releaseVersion, ...filters.params)
    .all();
  return json({ rank, options: rows.results || [] });
}

async function unifiedGenomeList(env, release, url) {
  const pagination = pageParams(url);
  if (pagination.error) return pagination.error;
  if (!BATTER_PAGE_SIZES.has(pagination.pageSize)) return bad("invalid_pagination", "page_size must be 25, 50, or 100", "page_size");
  const filters = unifiedGenomeFilters(url, release.release_version);
  if (filters.error) return filters.error;
  const orderBy = {
    genome_id_asc: "g.genome_id COLLATE NOCASE ASC",
    genome_id_desc: "g.genome_id COLLATE NOCASE DESC",
    predictions_desc: "COALESCE(b.tes_prediction, -1) DESC",
    predictions_asc: "COALESCE(b.tes_prediction, 2147483647) ASC",
    otu_augmentation_desc: "COALESCE(b.otu_augmentation_span, -1) DESC",
    otu_augmentation_asc: "COALESCE(b.otu_augmentation_span, 2147483647) ASC",
    rfam_training_desc: "COALESCE(b.rfam_training_span, -1) DESC",
    rfam_training_asc: "COALESCE(b.rfam_training_span, 2147483647) ASC",
  }[url.searchParams.get("sort") || "genome_id_asc"];
  if (!orderBy) return bad("invalid_sort", "sort is not supported", "sort");
  const where = filters.clauses.length ? `WHERE ${filters.clauses.join(" AND ")}` : "";
  const bindArgs = [release.release_version, release.release_version, ...filters.params];
  const [count, result] = await Promise.all([
    env.BTED_DB.prepare(`${UNIFIED_GENOME_IDS}
      SELECT COUNT(*) AS total ${UNIFIED_GENOME_JOINS} ${where}`)
      .bind(...bindArgs).first(),
    env.BTED_DB.prepare(`${UNIFIED_GENOME_IDS}
      SELECT g.genome_id, COALESCE(NULLIF(a.organism_name, ''), NULLIF(b.species, '')) AS species, a.strain,
        CASE WHEN a.accession IS NOT NULL AND b.genome_id IS NOT NULL THEN 'both'
          WHEN a.accession IS NOT NULL THEN 'experimental' ELSE 'batter' END AS membership,
        CASE WHEN a.accession IS NOT NULL THEN 1 ELSE 0 END AS has_experimental,
        CASE WHEN b.genome_id IS NOT NULL THEN 1 ELSE 0 END AS has_batter,
        EXISTS (SELECT 1 FROM assets signal WHERE signal.release_version = a.release_version
          AND signal.assembly_accession = g.genome_id AND signal.asset_kind = 'bigwig' AND signal.active = 1) AS has_bigwig,
        b.otu_id, b.genome_type, b.source_collection, b.domain, b.phylum, b.class, b."order", b.family, b.genus,
        b.tes_prediction, b.otu_augmentation_window, b.otu_augmentation_span,
        b.rfam_training_window, b.rfam_training_span, b.augmentation_status,
        (SELECT COUNT(*) FROM tracks t WHERE t.release_version = ? AND t.assembly_accession = g.genome_id) AS experimental_track_count,
        (SELECT COUNT(*) FROM endpoints e WHERE e.release_version = ? AND e.reference_assembly = g.genome_id) AS experimental_endpoint_count,
        (SELECT CASE WHEN EXISTS (SELECT 1 FROM tracks t JOIN sources s
            ON s.release_version = t.release_version AND s.source_id = t.source_id
          WHERE t.release_version = a.release_version AND t.assembly_accession = g.genome_id
            AND t.is_public = 1 AND s.release_status = 'published_standardized' AND s.record_count > 0
            AND EXISTS (SELECT 1 FROM assets f WHERE f.release_version = t.release_version
              AND f.assembly_accession = g.genome_id AND f.asset_kind = 'fasta' AND f.is_public = 1 AND f.active = 1)
            AND EXISTS (SELECT 1 FROM assets i WHERE i.release_version = t.release_version
              AND i.assembly_accession = g.genome_id AND i.asset_kind = 'fai' AND i.is_public = 1 AND i.active = 1))
          THEN 1 ELSE 0 END) AS experimental_browser_available
      ${UNIFIED_GENOME_JOINS} ${where}
      ORDER BY ${orderBy}, g.genome_id COLLATE NOCASE ASC LIMIT ? OFFSET ?`)
      .bind(release.release_version, release.release_version, release.release_version, release.release_version,
        ...filters.params, pagination.pageSize, pagination.offset).all(),
  ]);
  return json({
    ...pageResult(result.results || [], pagination.page, pagination.pageSize, Number(count?.total || 0)),
    sort: url.searchParams.get("sort") || "genome_id_asc",
  });
}

async function unifiedGenomeDetail(request, env, release, genomeId) {
  if (!/^[A-Za-z0-9._-]{1,96}$/.test(genomeId)) return bad("invalid_genome_id", "genome_id is invalid", "genome_id");
  const [batter, experimental] = await Promise.all([
    env.BTED_DB.prepare("SELECT * FROM batter_genomes WHERE genome_id = ? LIMIT 1").bind(genomeId).first(),
    assemblyPayload(request, env, release, genomeId),
  ]);
  if (experimental instanceof Response) return experimental;
  if (!batter && !experimental) return json({ error: "genome_not_found", genome_id: genomeId }, 404);
  const assembly = experimental?.assembly || null;
  const tracks = (assembly?.tracks || []).map((track) => ({
    source_id: track.source_id,
    pmid: track.pmid,
    publication_year: track.publication_year,
    paper_title: track.paper_title,
    assay: track.assay,
    evidence_class: track.evidence_class,
    record_count: Number(track.record_count || 0),
    source_status: track.source_status || "not_recorded",
    browser_available: Boolean(track.browser_available),
    file_status: track.gff3_url ? (track.publication_status || "public_download") : "data_preparing",
    download_url: track.gff3_url || null,
    has_bigwig: Boolean(track.has_bigwig),
    signal_downloads: track.signal_downloads || [],
  }));
  const noAugmentation = batter?.augmentation_status === "no_records_in_source";
  const data = {
    genome_id: genomeId,
    membership: batter && assembly ? "both" : batter ? "batter" : "experimental",
    has_experimental: Boolean(assembly),
    has_batter: Boolean(batter),
    organism_name: assembly?.organism_name || batter?.species || batter?.genus || genomeId,
    taxonomy: batter ? {
      domain: batter.domain || "",
      phylum: batter.phylum || "",
      class: batter.class || "",
      order: batter.order || "",
      family: batter.family || "",
      genus: batter.genus || "",
      species: batter.species || "",
    } : null,
    experimental: assembly ? {
      status: "available",
      assembly_accession: assembly.accession,
      organism_name: assembly.organism_name,
      strain: assembly.strain,
      reference_contigs: (assembly.contigs || []).map((contig) => ({
        seqid: contig.contig_accession,
        length_bp: Number(contig.length_bp || 0),
        sequence_sha256: contig.sequence_sha256 || null,
      })),
      track_count: tracks.length,
      endpoint_count: Number(assembly.endpoint_count || 0),
      source: `BTED ${release.release_version} study tracks`,
      tracks,
      browser_available: Boolean(assembly.browser_available),
      jbrowse_config: assembly.links?.jbrowse_config || null,
    } : { status: "not_present", track_count: 0, endpoint_count: 0, tracks: [] },
    batter: batter ? {
      status: "available",
      otu_id: batter.otu_id,
      genome_type: batter.genome_type,
      source_collection: batter.source_collection,
      reference: {
        genome_id: batter.reference_genome_id,
        cohort: batter.reference_cohort,
        fasta_path: batter.reference_fasta_path,
        contigs: batter.reference_contigs,
        bases: batter.reference_bases,
        sha256: batter.reference_sha256,
      },
      predictions: { count: Number(batter.tes_prediction || 0), source: "BATTER-TPE model predictions", file_status: "pending_public_release" },
      otu_augmentation: {
        count: Number(batter.otu_augmentation_span || 0),
        source_windows: Number(batter.otu_augmentation_window || 0),
        source: "BATTER OTU augmentation training records",
        file_status: noAugmentation ? "no_source_records" : "pending_public_release",
      },
      rfam_training: {
        count: Number(batter.rfam_training_span || 0),
        source_windows: Number(batter.rfam_training_window || 0),
        source: "BATTER Rfam-family training records",
        file_status: noAugmentation ? "no_source_records" : "pending_public_release",
      },
      augmentation_status: batter.augmentation_status,
      no_augmentation_records: noAugmentation,
      public_downloads: [],
    } : { status: "not_present", predictions: { count: 0 }, otu_augmentation: { count: 0 }, rfam_training: { count: 0 } },
    provenance: { release_version: release.release_version, match_key: "exact_genome_id" },
  };
  if (batter && activeReleaseVersion(env) === "v0.5.0") {
    const publication = await batterPublication(request, env, genomeId);
    data.batter.publication_status = publication?.publication_status || "data_preparing";
    data.batter.downloads = publication?.downloads || [];
    data.batter.annotation = publication?.metadata?.annotation || null;
    data.batter.validation = publication?.metadata?.validation || null;
    data.batter.public_downloads = ["public_download", "hf_preview"].includes(publication?.publication_status) ? publication.downloads : [];
    data.batter.browser_available = Boolean(publication?.metadata?.files?.["reference.fa.gz"]);
    data.batter.jbrowse_config = data.batter.browser_available ? new URL(`/api/genomes/${encodeURIComponent(genomeId)}/jbrowse-config`, request.url).href : null;
    for (const [key, name] of [["predictions", "prediction.gff3.gz"], ["otu_augmentation", "augmentation.gff3.gz"], ["rfam_training", "augmentation.gff3.gz"]]) {
      if (publication?.metadata?.files?.[name] && (key === "predictions" || !noAugmentation)) data.batter[key].file_status = publication.publication_status;
    }
  }
  return json({ data });
}

async function batterPublication(request, env, genomeId) {
  const row = await env.BTED_DB.prepare("SELECT * FROM batter_release_assets WHERE genome_id = ? AND release_version = ? LIMIT 1").bind(genomeId, "v0.5.0").first();
  if (!row) return null;
  const metadata = JSON.parse(row.metadata_json);
  const manifest = await fixedDataReleaseManifest(env, request);
  const downloads = Object.entries(metadata.files || {}).map(([name, file]) => {
    if (!BATTER_RELEASE_FILES.has(name) || !SHA256_PATTERN.test(file.sha256) || !Number.isInteger(file.byte_size) || file.byte_size < 0) throw dataReleaseError("data_release_manifest_invalid");
    const remote = HF_DATA_ASSET_PATTERN.exec(file.url);
    const local = LOCAL_DATA_ASSET_PATTERN.exec(file.url);
    const folder = name.startsWith("reference.") ? "reference" : name.startsWith("prediction.") ? "predictions" : name.startsWith("augmentation.") ? "training" : "annotations/batter";
    const migratedPath = `genomes/batter-${metadata.batch}/${genomeId}/${folder}/${name}`;
    const expectedTail = manifest.layout === "genome-first-v1" ? migratedPath : `/genomes/${genomeId}/${name}`;
    if (row.publication_status === "local_prepared") {
      if (!isLoopbackHost(new URL(request.url).hostname) || !local || local[1] !== "v0.5.0" || !safeLogicalPath(local[2]) || !local[2].endsWith(expectedTail)) throw dataReleaseError("local_origin_not_allowed");
    } else if (!["public_download", "hf_preview"].includes(row.publication_status) || !remote || remote[1] !== (manifest.publicationStatus === "hf_preview" ? manifest.batchRevisions?.[metadata.batch] : manifest.releaseRevision) || remote[2] !== "v0.5.0" || !safeLogicalPath(remote[3]) || (manifest.layout === "genome-first-v1" ? remote[3] !== expectedTail : !remote[3].endsWith(expectedTail))
        || (manifest.publicationStatus === "hf_preview" && (row.publication_status !== "hf_preview" || remote[3] !== `batter/batches/${metadata.batch}/genomes/${genomeId}/${name}`))) {
      throw dataReleaseError("data_release_manifest_invalid");
    }
    const url = local ? new URL("/" + file.url, request.url) : new URL(`/api/genomes/${encodeURIComponent(genomeId)}/files/${encodeURIComponent(name)}`, request.url);
    if (remote) url.searchParams.set("revision", remote[1]);
    return { filename: name, ...file, origin_url: file.url, url: url.href };
  });
  return { ...row, metadata, downloads };
}

async function genomeJbrowseConfig(request, env, release, genomeId) {
  if (activeReleaseVersion(env) !== "v0.5.0") return jbrowseConfig(request, env, release, genomeId, null);
  const publication = await batterPublication(request, env, genomeId);
  const dataManifest = await fixedDataReleaseManifest(env, request);
  if (!publication?.metadata?.files?.["reference.fa.gz"]) {
    if (dataManifest.publicationStatus === "hf_preview" && !dataManifest.experimentalAvailable) return json({ error: "data_preparing" }, 503, { "cache-control": "no-store" });
    return jbrowseConfig(request, env, release, genomeId, null);
  }
  const files = Object.fromEntries(publication.downloads.map(file => [file.filename, file]));
  const contigs = publication.metadata.reference_contigs;
  const experimental = dataManifest.publicationStatus === "hf_preview" && !dataManifest.experimentalAvailable ? null : await assemblyPayload(request, env, release, genomeId);
  if (experimental instanceof Response) return experimental;
  let config;
  if (experimental?.assembly?.browser_available) {
    if (!publication.metadata.shared_reference_verified) return json({ error: "shared_reference_not_verified" }, 409);
    const response = await jbrowseConfig(request, env, release, genomeId, null);
    if (!response.ok) return response;
    config = await response.json();
  } else {
    const assemblyName = `BTED_${genomeId}`;
    const first = [...contigs].sort((a, b) => b.length_bp - a.length_bp || a.seqid.localeCompare(b.seqid))[0];
    if (!first || !files["reference.fa.gz.fai"] || !files["reference.fa.gz.gzi"]) return json({ error: "incomplete_reference" }, 409);
    config = {
      assemblies: [{ name: assemblyName, sequence: { type: "ReferenceSequenceTrack", trackId: `${assemblyName}_refseq`, adapter: {
        type: "BgzipFastaAdapter", fastaLocation: { uri: files["reference.fa.gz"].url, locationType: "UriLocation" },
        faiLocation: { uri: files["reference.fa.gz.fai"].url, locationType: "UriLocation" },
        gziLocation: { uri: files["reference.fa.gz.gzi"].url, locationType: "UriLocation" },
      } } }], tracks: [],
      defaultSession: { name: `BTED · ${genomeId}`, views: [{ id: "bted_linear_genome_view", type: "LinearGenomeView", offsetPx: 0, bpPerPx: 1,
        displayedRegions: [{ refName: first.seqid, start: 0, end: first.length_bp, reversed: false, assemblyName }], tracks: [] }] },
      metadata: { release_version: "v0.5.0", assembly_accession: genomeId },
    };
  }
  const assemblyName = config.assemblies[0].name;
  for (const [name, label, category] of [["genes", "NCBI reference gene annotation", "Reference annotation"], ["prediction", "BATTER model predictions", "Model predictions"], ["augmentation", "BATTER training augmentation", "Training records"]]) {
    const file = files[`${name}.gff3.gz`], index = files[`${name}.gff3.gz.tbi`];
    if (!file || !index) continue;
    const trackId = `${assemblyName}_batter_${name}`;
    config.tracks.push({ type: "FeatureTrack", trackId, name: label, assemblyNames: [assemblyName], category: [category],
      adapter: { type: "Gff3TabixAdapter", gffGzLocation: { uri: file.url, locationType: "UriLocation" }, index: { location: { uri: index.url, locationType: "UriLocation" }, indexType: "TBI" } },
      displays: [{ type: "LinearBasicDisplay", displayId: `${trackId}_display` }], metadata: { release_version: "v0.5.0", sha256: file.sha256, publication_status: publication.publication_status },
    });
    config.defaultSession.views[0].tracks.push({ id: trackId, type: "FeatureTrack", configuration: trackId, minimized: false,
      displays: [{ id: `${trackId}_session`, type: "LinearBasicDisplay", configuration: `${trackId}_display` }] });
  }
  config.metadata.publication_status = publication.publication_status;
  config.metadata.reference_contigs = contigs;
  config.metadata.empty_augmentation = !files["augmentation.gff3.gz.tbi"];
  return json(config);
}

async function batterApi(request, env, url) {
  const path = url.pathname;
  try {
    if (path === "/api/batter-genomes/stats") return await batterStats(env);
    if (path === "/api/batter-genomes/facets") return await batterFacets(env, url);
    if (path === "/api/batter-genomes") return await batterGenomeList(env, url);
    const match = path.match(/^\/api\/batter-genomes\/([^/]+)$/);
    if (match) {
      const genomeId = decodePath(match[1]);
      return genomeId ? await batterGenomeDetail(env, genomeId) : bad("invalid_genome_id", "genome_id is invalid", "genome_id");
    }
    return json({ error: "not_found" }, 404);
  } catch {
    return json({ error: "batter_catalog_unavailable", message: "Import the BATTER catalogue into local D1 before starting the preview." }, 503, { "cache-control": "no-store" });
  }
}

async function currentRelease(env) {
  return env.BTED_DB.prepare(
    "SELECT * FROM release_versions WHERE release_version = ? AND is_current = 1 LIMIT 1",
  ).bind(activeReleaseVersion(env)).first();
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
  if (!manifest || manifest.releaseVersion !== activeReleaseVersion(env)
      || !manifest.assets || typeof manifest.assets !== "object" || Array.isArray(manifest.assets)) {
    throw dataReleaseError("data_release_manifest_invalid");
  }
  if (manifest.publicationStatus === "hf_preview") {
    if (!isLoopbackHost(new URL(request.url).hostname) || manifest.releaseRevision !== null
        || !SHA256_PATTERN.test(manifest.releaseManifestSha256 || "") || !manifest.batchRevisions
        || Object.entries(manifest.batchRevisions).some(([batch, revision]) => !/^\d{3}$/.test(batch) || Number(batch) > 42 || !/^[0-9a-f]{40}$/.test(revision))) {
      throw dataReleaseError("data_release_manifest_invalid");
    }
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
      if (match[1] !== asset.revision || decodedPath !== logicalPath || (manifest.releaseVersion === "v0.5.0" && match[2] !== "v0.5.0")
          || (manifest.publicationStatus === "hf_preview" && (!manifest.experimentalAvailable || asset.revision !== manifest.experimentalRevision))
          || (manifest.releaseVersion === "v0.5.0" && manifest.publicationStatus === "public_download" && asset.revision !== manifest.releaseRevision)) {
        throw dataReleaseError("data_release_manifest_invalid");
      }
    } else if (localMatch) {
      let decodedPath;
      try { decodedPath = decodeURIComponent(localMatch[2]); } catch { decodedPath = null; }
      if (decodedPath !== logicalPath || asset.revision != null || ["hf_preview", "public_download"].includes(manifest.publicationStatus)) {
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
    || (["tsv", "gzi"].includes(asset.asset_kind) && expectedAsset.asset_kind === "metadata");
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
  if (HF_DATA_ASSET_PATTERN.test(asset.url)) {
    if (manifest.releaseVersion !== "v0.5.0") return asset.url;
    const key = expectedAsset?.asset_key || asset.asset_key;
    if (!key && manifest.releaseVersion !== "v0.5.0") return asset.url;
    if (!key) throw dataReleaseError("data_release_manifest_invalid");
    const url = new URL(`/api/assets/${encodeURIComponent(key)}`, request.url);
    url.searchParams.set("revision", asset.revision);
    return url.href;
  }
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
  const [contigs, tracks, assets, registeredAssets, endpointCount, signalSources] = await Promise.all([
    env.BTED_DB.prepare("SELECT contig_accession, contig_name, length_bp, sequence_sha256, provenance_json FROM contigs WHERE release_version = ? AND assembly_accession = ? ORDER BY contig_accession").bind(release.release_version, accession).all(),
    trackRows(env, release.release_version, accession, null),
    allAssets(env, release.release_version, accession, null),
    allAssets(env, release.release_version, null, null),
    env.BTED_DB.prepare("SELECT COUNT(*) AS total FROM endpoints WHERE release_version = ? AND reference_assembly = ?").bind(release.release_version, accession).first(),
    env.BTED_DB.prepare("SELECT DISTINCT source_id FROM assets WHERE release_version = ? AND assembly_accession = ? AND asset_kind = 'bigwig' AND active = 1").bind(release.release_version, accession).all(),
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
      gff3_url: source?.record_root && dataManifest.assets[source.record_root] ? dataAssetUrl(dataManifest, source.record_root, request) : gff3Url,
      browser_gff3_url: gff3Url,
      publication_status: dataManifest.publicationStatus || "public_download",
      has_bigwig: (signalSources.results || []).some(asset => asset.source_id === track.source_id),
      signal_downloads: assets.filter(asset => asset.source_id === track.source_id && asset.asset_kind === "bigwig")
        .map(asset => ({ label: /(?:plus|forward)/.test(asset.logical_path) ? "+ strand BigWig" : "− strand BigWig", url: dataAssetUrl(dataManifest, asset.logical_path, request, asset) })),
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
      metadata_url: dataManifest.publicationStatus === "hf_preview" && !dataManifest.experimentalAvailable ? null : dataAssetUrl(dataManifest, dataManifest.genomeMetadataPaths?.[accession] || `${release.release_version === "v0.5.0" ? "experimental/" : ""}genomes/${accession}/metadata.tsv`, request),
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
    && (asset.logical_path.startsWith(`assemblies/${accession}/reference/`)
      || asset.logical_path === `experimental/genomes/${accession}/genes.gff3.gz`
      || (dataManifest.layout === "genome-first-v1" && asset.logical_path.includes(`/${accession}/annotations/experimental/`)))
    && Number(asset.is_public) === 1);
  const tbi = assemblyAssets.find((asset) => asset.asset_kind === "tbi" && Number(asset.is_public) === 1
    && (!gff || asset.logical_path === `${gff.logical_path}.tbi`));
  const gzi = assemblyAssets.find((asset) => asset.logical_path === `${fasta.logical_path}.gzi`);
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
    const signalPlus = sourceAssets.find((asset) => asset.asset_kind === "bigwig" && /signal\.(forward|plus)\.bw$/.test(asset.logical_path) && Number(asset.is_public) === 1);
    const signalMinus = sourceAssets.find((asset) => asset.asset_kind === "bigwig" && /signal\.(reverse|minus)\.bw$/.test(asset.logical_path) && Number(asset.is_public) === 1);
    if (signalPlus && signalMinus) {
      const signalId = `${track.track_id}_mirrored_signal`;
      tracksConfig.push({
        type: "MultiQuantitativeTrack",
        trackId: signalId,
        name: `${source.source_id} · experimental signal (+ / −)`,
        adapter: { type: "MultiWiggleAdapter", subadapters: [
          { type: "BigWigAdapter", source: "plus", name: "+ strand", color: PLUS_STRAND_COLOR, bigWigLocation: { uri: dataAssetUrl(dataManifest, signalPlus.logical_path, request, signalPlus), locationType: "UriLocation" } },
          { type: "BigWigAdapter", source: "minus", name: "− strand", color: MINUS_STRAND_COLOR, bigWigLocation: { uri: dataAssetUrl(dataManifest, signalMinus.logical_path, request, signalMinus), locationType: "UriLocation" } },
        ] },
        category: ["BTED experimental signal", source.source_id],
        assemblyNames: [assemblyName],
        metadata: {
          ...metadata, signal_values: "Raw BigWig values; mirrored only for display", strand: "+ / −", btedMirroredSignal: true,
          btedDownloads: [
            { kind: "bigwig", label: "+ strand BigWig", url: dataAssetUrl(dataManifest, signalPlus.logical_path, request, signalPlus), filename: `${source.source_id}.signal.forward.bw` },
            { kind: "bigwig", label: "− strand BigWig", url: dataAssetUrl(dataManifest, signalMinus.logical_path, request, signalMinus), filename: `${source.source_id}.signal.reverse.bw` },
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
    } else if (signalPlus || signalMinus) {
      const signal = signalPlus || signalMinus;
      const signalId = `${track.track_id}_single_signal`;
      const signalUrl = dataAssetUrl(dataManifest, signal.logical_path, request, signal);
      jbrowseTracks.push({ type: "QuantitativeTrack", trackId: signalId,
        name: `${source.source_id} · experimental signal (${signalPlus ? "+" : "−"})`,
        assemblyNames: [assemblyName], category: ["BTED experimental signal", `PMID ${track.pmid}`, source.source_id],
        adapter: { type: "BigWigAdapter", bigWigLocation: { uri: signalUrl, locationType: "UriLocation" } },
        displays: [{ type: "LinearWiggleDisplay", displayId: `${signalId}_display` }],
        metadata: { ...metadata, btedDownloads: [{ kind: "bigwig", label: "Study BigWig signal", url: signalUrl }] },
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
      adapter: first.endpointGff3.logical_path.endsWith(".gz") && dataManifest.assets[`${first.endpointGff3.logical_path}.tbi`] ? {
        type: "Gff3TabixAdapter", gffGzLocation: { uri: first.endpointGff3Url, locationType: "UriLocation" },
        index: { location: { uri: dataAssetUrl(dataManifest, `${first.endpointGff3.logical_path}.tbi`, request), locationType: "UriLocation" }, indexType: "TBI" },
      } : { type: "Gff3Adapter", gffLocation: { uri: first.endpointGff3Url, locationType: "UriLocation" } },
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
  return json({
    plugins: [{ name: "BTEDTrackPlugin", esmUrl: new URL("/jbrowse/plugins/bted-track-plugin.js", request.url).href }],
    assemblies: [{ name: assemblyName, displayName: `${assembly.display_name || assembly.organism_name} (${accession})`, sequence: { type: "ReferenceSequenceTrack", trackId: `${assemblyName}_refseq`, adapter: {
      type: gzi ? "BgzipFastaAdapter" : "IndexedFastaAdapter",
      fastaLocation: { uri: assetUrl(request, fasta.asset_key), locationType: "UriLocation" },
      faiLocation: { uri: assetUrl(request, fai.asset_key), locationType: "UriLocation" },
      ...(gzi ? { gziLocation: { uri: assetUrl(request, gzi.asset_key), locationType: "UriLocation" } } : {}),
    } } }],
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
  if (release.release_version === "v0.5.0" && HF_DATA_ASSET_PATTERN.test(assetRef.url)) {
    return streamHfAsset(request, { ...assetRef, filename: asset.logical_path.split("/").at(-1) }, env);
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
      upstream = await staticAsset(new Request(origin, { method: request.method, headers: headersIn }), env);
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

function byteRange(value, size) {
  if (!value) return null;
  const match = /^bytes=(\d*)-(\d*)$/.exec(value);
  if (!match || (!match[1] && !match[2]) || size === 0) return false;
  const first = match[1] ? Number(match[1]) : null;
  const last = match[2] ? Number(match[2]) : null;
  if ((first !== null && !Number.isSafeInteger(first)) || (last !== null && !Number.isSafeInteger(last))) return false;
  const start = first === null ? Math.max(0, size - last) : first;
  const end = first === null || last === null ? size - 1 : Math.min(last, size - 1);
  return start < size && start >= 0 && end >= start ? { start, end } : false;
}

async function streamHfAsset(request, asset, env = {}) {
  const match = HF_DATA_ASSET_PATTERN.exec(asset.origin_url || asset.url);
  const fail = (code, status = 502) => json({ error: code }, status, { "cache-control": "no-store" });
  if (!match || !SHA256_PATTERN.test(asset.sha256) || !Number.isSafeInteger(asset.byte_size) || asset.byte_size < 0) return fail("data_release_manifest_invalid", 503);
  const requested = new URL(request.url);
  if (requested.searchParams.has("url")) return fail("arbitrary_origin_not_supported", 400);
  const revision = requested.searchParams.get("revision");
  if (revision && revision !== match[1]) return fail("revision_mismatch", 409);
  const tag = `"sha256:${asset.sha256}"`;
  const range = byteRange(request.headers.get("range"), asset.byte_size);
  if (range === false) return json({ error: "invalid_range" }, 416, { "content-range": `bytes */${asset.byte_size}`, "cache-control": "no-store" });
  const headersIn = new Headers({ accept: "*/*", "accept-encoding": "identity" });
  const effectiveRange = range && (!request.headers.has("if-range") || request.headers.get("if-range") === tag) ? range : null;
  if (effectiveRange) headersIn.set("range", `bytes=${effectiveRange.start}-${effectiveRange.end}`);
  let upstream;
  let upstreamUrl = asset.origin_url || asset.url;
  if (env.HF_PREVIEW_GATEWAY) {
    let gateway;
    try { gateway = new URL(env.HF_PREVIEW_GATEWAY); } catch { return fail("local_origin_not_allowed", 403); }
    if (!isLoopbackHost(requested.hostname) || gateway.protocol !== "http:" || !isLoopbackHost(gateway.hostname)
        || gateway.username || gateway.password || gateway.search || gateway.hash || gateway.pathname !== "/") return fail("local_origin_not_allowed", 403);
    // The private loopback bridge streams HF responses; the same checks apply.
    upstreamUrl = new URL(new URL(upstreamUrl).pathname, gateway).href;
  }
  try {
    upstream = await fetch(upstreamUrl, { method: request.method, headers: headersIn, redirect: "follow" });
  } catch { return fail("asset_origin_unavailable"); }
  const abandon = async (code, status) => {
    try { await upstream.body?.cancel(); } catch { /* no body on HEAD */ }
    return fail(code, status);
  };
  if (![200, 206].includes(upstream.status)) return abandon("asset_origin_unavailable", upstream.status === 429 || upstream.status === 503 ? 503 : 502);
  const headers = new Headers();
  for (const key of RESPONSE_HEADERS) if (upstream.headers.has(key)) headers.set(key, upstream.headers.get(key));
  if (effectiveRange) {
    const expected = `bytes ${effectiveRange.start}-${effectiveRange.end}/${asset.byte_size}`;
    if (upstream.status !== 206 || headers.get("content-range") !== expected
        || Number(headers.get("content-length")) !== effectiveRange.end - effectiveRange.start + 1) return abandon("upstream_range_mismatch", 502);
  } else if (upstream.status !== 200 || (headers.has("content-length") && Number(headers.get("content-length")) !== asset.byte_size)) {
    return abandon("upstream_length_mismatch", 502);
  }
  headers.set("content-length", String(effectiveRange ? effectiveRange.end - effectiveRange.start + 1 : asset.byte_size));
  headers.set("content-type", headers.get("content-type") || "application/octet-stream");
  headers.set("accept-ranges", "bytes");
  headers.set("etag", tag);
  headers.set("x-bted-hf-revision", match[1]);
  headers.set("x-bted-sha256", asset.sha256);
  // Stable API paths without a commit query must never cache an old snapshot.
  headers.set("cache-control", revision ? "public, max-age=31536000, immutable" : "no-store");
  return new Response(request.method === "HEAD" ? null : upstream.body, { status: upstream.status, headers });
}

async function genomeFile(request, env, genomeId, filename) {
  if (!/^[A-Za-z0-9._-]{1,96}$/.test(genomeId) || !/^[A-Za-z0-9._-]+$/.test(filename)) return json({ error: "unknown_asset" }, 404, { "cache-control": "no-store" });
  const publication = await batterPublication(request, env, genomeId);
  if (!publication?.metadata?.files) return json({ error: "data_preparing" }, 503, { "cache-control": "no-store" });
  const file = publication.downloads.find(item => item.filename === filename);
  if (!file) return json({ error: "unknown_asset" }, 404, { "cache-control": "no-store" });
  return streamHfAsset(request, file, env);
}

async function staticAsset(request, env) {
  if (env.ASSETS && typeof env.ASSETS.fetch === "function") {
    const response = await env.ASSETS.fetch(request);
    // Wrangler's local asset binding can ignore Range. Emulate byte ranges for
    // local preparation only; published data uses fixed-revision HF origins.
    const url = new URL(request.url), range = request.headers.get("range");
    if (activeReleaseVersion(env) !== "v0.5.0" || !isLoopbackHost(url.hostname)
        || !url.pathname.startsWith("/downloads/v0.5.0/") || !range || request.method !== "GET" || response.status !== 200) return response;
    const bytes = await response.arrayBuffer(), length = bytes.byteLength;
    const match = /^bytes=(\d*)-(\d*)$/.exec(range);
    let start = match?.[1] ? Number(match[1]) : Math.max(0, length - Number(match?.[2]));
    let end = match?.[1] ? (match[2] ? Math.min(Number(match[2]), length - 1) : length - 1) : length - 1;
    if (!match || (!match[1] && !match[2]) || start > end || start >= length || !Number.isSafeInteger(start) || !Number.isSafeInteger(end)) return new Response(null, { status: 416, headers: { "content-range": `bytes */${length}` } });
    const headers = new Headers(response.headers);
    headers.set("accept-ranges", "bytes");
    headers.set("content-range", `bytes ${start}-${end}/${length}`);
    headers.set("content-length", String(end - start + 1));
    return new Response(request.method === "HEAD" ? null : bytes.slice(start, end + 1), { status: 206, headers });
  }
  return json({ error: "static_assets_not_configured" }, 404);
}

const routes = {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!["GET", "HEAD"].includes(request.method)) return json({ error: "method_not_allowed" }, 405, { allow: "GET, HEAD" });
    if (url.pathname.startsWith("/downloads/v0.2.0/")) return retiredReleaseResponse("v0.2.0");
    if (!url.pathname.startsWith("/api/")) return staticAsset(request, env);
    if (url.pathname === "/api/batter-genomes" || url.pathname.startsWith("/api/batter-genomes/")) {
      return batterApi(request, env, url);
    }
    const requestedRelease = url.searchParams.get("release_version");
    if (requestedRelease === "v0.2.0") {
      return retiredReleaseResponse(requestedRelease);
    }
    if (requestedRelease && requestedRelease !== activeReleaseVersion(env)) {
      return json({ error: "release_not_found", release_version: requestedRelease }, 404);
    }
    const selected = await withRelease(env, url);
    if (url.pathname === "/api/health") return selected ? json({ status: "ok", deployment: "cloudflare-worker-d1-preview", release: releasePayload(selected.release) }) : json({ status: "error", error: "release_not_loaded" }, 503);
    if (!selected) return json({ error: "release_not_found" }, 404);
    if (url.pathname === "/api/genomes/stats") return await unifiedGenomeStats(env, selected.release.release_version);
    if (url.pathname === "/api/genomes/facets") return await unifiedGenomeFacets(env, url, selected.release.release_version);
    if (url.pathname === "/api/genomes") return await unifiedGenomeList(env, selected.release, url);
    const fileMatch = url.pathname.match(/^\/api\/genomes\/([^/]+)\/files\/([^/]+)$/);
    if (fileMatch) return genomeFile(request, env, decodePath(fileMatch[1]) || "", decodePath(fileMatch[2]) || "");
    const genomeMatch = url.pathname.match(/^\/api\/genomes\/([^/]+)(?:\/jbrowse-config)?$/);
    if (genomeMatch) {
      const genomeId = decodePath(genomeMatch[1]);
      if (genomeId && url.pathname.endsWith("/jbrowse-config")) return genomeJbrowseConfig(request, env, selected.release, genomeId);
      return genomeId ? await unifiedGenomeDetail(request, env, selected.release, genomeId) : bad("invalid_genome_id", "genome_id is invalid", "genome_id");
    }
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

export default {
  async fetch(request, env) {
    try { return await routes.fetch(request, env); }
    catch (error) {
      if (error?.code?.startsWith("data_release_manifest")) return dataReleaseErrorResponse(error);
      return json({ error: "catalog_unavailable" }, 503, { "cache-control": "no-store" });
    }
  },
};
