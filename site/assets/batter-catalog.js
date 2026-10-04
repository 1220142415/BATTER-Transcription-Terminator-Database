(() => {
  "use strict";

  const number = new Intl.NumberFormat("en-US");
  const ranks = ["phylum", "class", "order", "family", "genus", "species"];
  const rankPlural = { phylum: "phyla", class: "classes", order: "orders", family: "families", genus: "genera", species: "species" };
  const state = new URLSearchParams(window.location.search);
  const genomeId = state.get("genome") || state.get("assembly_accession") || state.get("genome_id") || "";
  state.delete("genome");
  const directory = document.getElementById("batter-directory");
  const detail = document.getElementById("batter-detail");
  const list = document.getElementById("batter-results");
  const status = document.getElementById("batter-result-summary");
  const sourceSelect = document.getElementById("batter-source");
  const typeSelect = document.getElementById("batter-type");
  const membershipSelect = document.getElementById("batter-membership");
  const evidenceSelect = document.getElementById("batter-evidence");
  const bigwigSelect = document.getElementById("batter-bigwig");
  const searchInput = document.getElementById("batter-search");
  const pilotOrigin = "http://127.0.0.1:8783";
  const pilotGenomes = new Map();
  let releaseManifest = null;
  let requestVersion = 0;
  let requestController = null;
  let facetsDirty = true;
  let searchTimer = null;
  const sortButtons = [...document.querySelectorAll("[data-batter-sort]")];
  const errorPanel = document.getElementById("batter-request-error");
  const errorMessage = document.getElementById("batter-error-message");

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[character]);
  }

  function formatted(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? number.format(parsed) : "—";
  }

  function releaseText(value) {
    return String(value || "").replace(/\bv0\.5\.0\b/g, releaseManifest?.releaseLabel || "v5");
  }

  const downloadLabels = {
    "reference.fa.gz": "Reference FASTA",
    "reference.fa.gz.fai": "FASTA index (.fai)",
    "reference.fa.gz.gzi": "FASTA compression index (.gzi)",
    "prediction.gff3.gz": "Predictions GFF3",
    "prediction.gff3.gz.tbi": "Predictions index",
    "augmentation.gff3.gz": "Training records GFF3",
    "augmentation.gff3.gz.tbi": "Training records index",
    "genes.gff3.gz": "Gene annotation GFF3",
    "genes.gff3.gz.tbi": "Gene annotation index",
  };

  function paramsForApi(extra = {}) {
    const params = new URLSearchParams(state);
    params.delete("genome");
    for (const [key, value] of Object.entries(extra)) params.set(key, value);
    return params;
  }

  function writeUrl() {
    const url = new URL(window.location.href);
    url.search = state.toString();
    if (genomeId) url.searchParams.set("genome", genomeId);
    window.history.replaceState(null, "", url);
  }

  async function getJson(url, signal) {
    const response = await fetch(url, { signal, headers: { accept: "application/json" } });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.message || payload.error || `Request failed (${response.status})`);
    return payload;
  }

  function replaceOptions(select, entries, emptyLabel, selected) {
    select.replaceChildren(new Option(emptyLabel, ""));
    for (const entry of entries) select.add(new Option(`${entry.value} · ${formatted(entry.count)}`, entry.value));
    if (selected && !entries.some((entry) => entry.value === selected)) select.add(new Option(selected, selected));
    select.value = selected || "";
  }

  async function loadPilotManifest() {
    try {
      releaseManifest = await getJson("/assets/data-release.json");
      if (releaseManifest.releaseVersion === "v0.5.0") {
        for (const id of releaseManifest.batterBrowser?.preparedGenomeIds || []) pilotGenomes.set(String(id), { genome_id: id });
        if (releaseManifest.publicationStatus === "hf_preview") {
          const notice = document.createElement("p");
          notice.className = "batter-reference-note";
          notice.id = "hf-availability";
          notice.textContent = `Latest · v5 · ${formatted(releaseManifest.availableGenomeCount)} / ${formatted(releaseManifest.totalGenomeCount)} genomes available · Other data preparing`;
          (directory || detail).before(notice);
        }
        return;
      }
    } catch { /* Legacy previews may have no release manifest. */ }
    try {
      const payload = await getJson("/assets/batter-preview-catalog.json");
      const rows = Array.isArray(payload) ? payload : (payload.genomes || []);
      for (const row of rows) {
        if (row.genome_id) pilotGenomes.set(String(row.genome_id), row);
      }
    } catch {
      // The full BATTER browser configs are a local preview asset. The experimental
      // browser remains available from the Worker when the pilot manifest is absent.
    }
  }

  function showRankLoading(rank, loading) {
    document.getElementById(`batter-${rank}`).setAttribute("aria-busy", String(loading));
    document.getElementById(`batter-${rank}-loading`).hidden = !loading;
  }

  function lockTaxonomy() {
    ranks.forEach((rank, index) => {
      const hasParents = ranks.slice(0, index).every((parent) => state.get(parent));
      document.getElementById(`batter-${rank}`).disabled = true;
      showRankLoading(rank, hasParents);
    });
  }

  function clearChildRanks(index) {
    for (const rank of ranks.slice(index)) {
      state.delete(rank);
      const select = document.getElementById(`batter-${rank}`);
      select.disabled = true;
      replaceOptions(select, [], `All ${rankPlural[rank]}`, "");
      showRankLoading(rank, false);
    }
  }

  async function loadTaxonomyOptions(criteria, signal, version) {
    for (let index = 0; index < ranks.length; index += 1) {
      const rank = ranks[index];
      const select = document.getElementById(`batter-${rank}`);
      const selected = criteria.get(rank) || "";
      if (index > 0 && !criteria.get(ranks[index - 1])) {
        clearChildRanks(index);
        break;
      }
      const params = new URLSearchParams({ rank });
      for (const parent of ranks.slice(0, index)) params.set(parent, criteria.get(parent));
      const payload = await getJson(`/api/genomes/facets?${params}`, signal);
      if (version !== requestVersion || signal.aborted) return;
      replaceOptions(select, payload.options || [], `All ${rankPlural[rank]}`, selected);
      select.disabled = false;
      showRankLoading(rank, false);
    }
    if (version === requestVersion && !signal.aborted) facetsDirty = false;
  }

  function detailHref(id) {
    const params = new URLSearchParams(state);
    params.set("genome", id);
    return `batter-genomes.html?${params.toString()}`;
  }

  function pilotBrowserHref(id) {
    if (!pilotGenomes.has(String(id))) return "";
    if (releaseManifest?.releaseVersion === "v0.5.0") {
      const config = new URL(releaseManifest.batterBrowser.route.replace("{genome_id}", encodeURIComponent(id)), window.location.origin);
      const browser = new URL("/jbrowse/index.html", window.location.origin);
      browser.searchParams.set("config", config.href);
      return browser.href;
    }
    const config = `assemblies/BATTER_TES_${id}.config.json`;
    return `${pilotOrigin}/jbrowse/index.html?config=${encodeURIComponent(config)}`;
  }

  function experimentalBrowserHref(id) {
    const config = new URL(`/api/${releaseManifest?.releaseVersion === "v0.5.0" ? "genomes" : "assemblies"}/${encodeURIComponent(id)}/jbrowse-config`, window.location.origin);
    const browser = new URL("/jbrowse/index.html", window.location.origin);
    browser.searchParams.set("config", config.href);
    return browser.href;
  }

  function browserForRow(row) {
    const pilot = pilotBrowserHref(row.genome_id);
    if (pilot) return { href: pilot, label: row.has_experimental ? "Unified tracks" : releaseManifest?.releaseVersion === "v0.5.0" ? "BATTER tracks" : "BATTER pilot" };
    if (Number(row.experimental_browser_available) === 1 && (releaseManifest?.publicationStatus !== "hf_preview" || releaseManifest.experimentalAvailable)) {
      return { href: experimentalBrowserHref(row.genome_id), label: "Experimental tracks" };
    }
    return null;
  }

  function renderRows(rows) {
    if (!rows.length) {
      list.innerHTML = '<tr><td colspan="7">No genomes match these filters.</td></tr>';
      return;
    }
    list.innerHTML = rows.map((row) => {
      const classification = [row.phylum, row.class, row.genus].filter(Boolean).join(" · ");
      const membership = row.membership === "both" ? "Both" : row.membership === "experimental" ? "Experimental" : "BATTER";
      const noRecords = row.augmentation_status === "no_records_in_source"
        ? '<span class="batter-empty-badge">No augmentation records</span>' : "";
      const browser = browserForRow(row);
      const browserCell = browser
        ? `<a class="batter-browser-link" href="${esc(browser.href)}" target="_blank" rel="noopener">${esc(browser.label)} ↗</a>`
        : '<span class="batter-browser-state">Tracks preparing</span>';
      const experimentalCount = row.has_experimental
        ? `${formatted(row.experimental_endpoint_count)}<span class="taxon-secondary">${formatted(row.experimental_track_count)} studies</span>`
        : "0";
      const batterCount = row.has_batter ? formatted(row.tes_prediction) : "0";
      const otuCount = row.has_batter ? formatted(row.otu_augmentation_span) : "0";
      const rfamCount = row.has_batter ? formatted(row.rfam_training_span) : "0";
      return `<tr>
        <td data-label="Genome ID"><a class="genome-link" href="${esc(detailHref(row.genome_id))}">${esc(row.genome_id)}</a><span class="batter-type-badge">${membership}</span>${row.otu_id ? `<span class="otu-id">${esc(row.otu_id)}</span>` : ""}${row.species ? `<span class="taxon-secondary">${esc(row.species)}</span>` : ""}</td>
        <td data-label="Classification"><span class="taxon-primary">${esc(row.species || row.genus || "Not provided")}</span><span class="taxon-secondary">${esc(classification || "Not provided")}</span>${row.genome_type ? `<span class="taxon-secondary">${esc(row.genome_type)} · ${esc(row.source_collection || "Not provided")}</span>` : ""}</td>
        <td data-label="Experimental 3′ ends">${experimentalCount}</td>
        <td class="numeric" data-label="BATTER predictions">${batterCount}</td>
        <td class="numeric" data-label="OTU augmentation">${otuCount}${noRecords}</td>
        <td class="numeric" data-label="Rfam training">${rfamCount}</td>
        <td data-label="Local browser">${browserCell}</td>
      </tr>`;
    }).join("");
  }

  async function loadList(criteria, signal, version) {
    let payload = await getJson(`/api/genomes?${criteria}`, signal);
    if (version !== requestVersion || signal.aborted) return;
    const lastPage = Math.max(1, Math.ceil(payload.pagination.total / payload.pagination.page_size));
    if (payload.pagination.page > lastPage) {
      criteria.set("page", String(lastPage));
      payload = await getJson(`/api/genomes?${criteria}`, signal);
      if (version !== requestVersion || signal.aborted) return;
    }
    renderRows(payload.data || []);
    const page = payload.pagination.page;
    const pageCount = Math.max(1, Math.ceil(payload.pagination.total / payload.pagination.page_size));
    status.textContent = `${formatted(payload.pagination.total)} genomes · ${formatted(payload.pagination.returned)} on this page`;
    document.getElementById("batter-page-summary").textContent = `Page ${formatted(page)} of ${formatted(pageCount)}`;
    document.getElementById("batter-previous").disabled = page <= 1;
    document.getElementById("batter-next").disabled = page >= pageCount;
    document.getElementById("batter-page-jump").max = String(pageCount);
    document.getElementById("batter-page-jump").value = String(page);
    state.set("page", String(page));
    writeUrl();
  }

  function invalidateRequests() {
    requestVersion += 1;
    requestController?.abort();
    window.clearTimeout(searchTimer);
  }

  function updateSortHeaders() {
    const sort = state.get("sort") || "genome_id_asc";
    for (const button of sortButtons) {
      const field = button.dataset.batterSort;
      const ascending = sort === `${field}_asc`;
      const active = ascending || sort === `${field}_desc`;
      const next = active ? (ascending ? "descending" : "ascending") : (field === "genome_id" ? "ascending" : "descending");
      button.closest("th").setAttribute("aria-sort", active ? (ascending ? "ascending" : "descending") : "none");
      button.setAttribute("aria-label", `Sort ${button.dataset.sortLabel} ${next}`);
      button.querySelector("[data-sort-icon]").textContent = active ? (ascending ? "↑" : "↓") : "↕";
      button.classList.toggle("is-active", active);
    }
  }

  function setLoading() {
    directory.setAttribute("aria-busy", "true");
    status.textContent = "Updating results…";
    for (const id of ["batter-previous", "batter-next", "batter-page-jump"]) document.getElementById(id).disabled = true;
  }

  async function refresh({ facets = false, resetPage = true } = {}) {
    invalidateRequests();
    const version = requestVersion;
    const controller = new AbortController();
    requestController = controller;
    facetsDirty ||= facets;
    if (resetPage) state.set("page", "1");
    state.set("page_size", ["25", "50", "100"].includes(state.get("page_size")) ? state.get("page_size") : "50");
    const page = Number(state.get("page") || 1);
    state.set("page", String(Number.isSafeInteger(page) && page > 0 ? page : 1));
    // URLs with orphaned child filters cannot represent the taxonomy controls.
    const missingParent = ranks.findIndex((rank) => !state.get(rank));
    if (missingParent >= 0) clearChildRanks(missingParent + 1);
    writeUrl();
    updateSortHeaders();
    setLoading();
    errorPanel.hidden = true;
    const criteria = paramsForApi();
    if (facetsDirty) lockTaxonomy();
    try {
      await Promise.all([
        facetsDirty ? loadTaxonomyOptions(criteria, controller.signal, version) : Promise.resolve(),
        loadList(criteria, controller.signal, version),
      ]);
    } catch (error) {
      if (version !== requestVersion || error.name === "AbortError") return;
      // Cancel sibling requests too, so a failed refresh cannot later appear successful.
      controller.abort();
      status.textContent = "Could not update the genome catalogue.";
      errorMessage.textContent = error.message;
      errorPanel.hidden = false;
      for (const id of ["batter-previous", "batter-next", "batter-page-jump"]) document.getElementById(id).disabled = true;
      for (const rank of ranks) showRankLoading(rank, false);
    } finally {
      if (version === requestVersion) {
        requestController = null;
        directory.setAttribute("aria-busy", "false");
        document.getElementById("batter-page-jump").disabled = !errorPanel.hidden;
      }
    }
  }

  async function loadStats() {
    const payload = await getJson("/api/genomes/stats");
    for (const key of ["genome_count", "experimental_genome_count", "batter_genome_count", "both_genome_count", "no_augmentation_genome_count"]) {
      const target = document.querySelector(`[data-batter-stat="${key}"]`);
      if (target) target.textContent = formatted(payload[key]);
    }
    replaceOptions(sourceSelect, payload.source_collections || [], "All original sources", state.get("source") || "");
    replaceOptions(typeSelect, payload.genome_types || [], "All types", state.get("type") || "");
  }

  function fact(label, value) {
    return `<dt>${esc(label)}</dt><dd>${esc(value || "Not provided")}</dd>`;
  }

  function fileStatusLabel(fileStatus) {
    if (fileStatus === "public_download") return "Public download";
    if (fileStatus === "hf_preview") return "Download available";
    if (fileStatus === "data_preparing") return "Data preparing";
    if (fileStatus === "local_prepared") return "Prepared locally · not published";
    if (fileStatus === "no_source_records") return "No records in source";
    if (fileStatus === "pending_public_release") return "Data preparing";
    return "No public files";
  }

  function renderExperimentalReference(record) {
    const contigs = Array.isArray(record.reference_contigs) ? record.reference_contigs : [];
    const rows = contigs.length
      ? contigs.map((contig) => `<li><code>${esc(contig.seqid || "Not provided")}</code> · ${formatted(contig.length_bp)} bp</li>`).join("")
      : '<li>Contig information not provided</li>';
    return `<div class="batter-reference-block"><h3>Experimental browser reference</h3><p>Assembly ${esc(record.assembly_accession || "Not provided")}${record.strain ? ` · strain ${esc(record.strain)}` : ""}</p><ul>${rows}</ul></div>`;
  }

  function renderBatterReference(record) {
    const reference = record.reference || {};
    return `<div class="batter-reference-block"><h3>BATTER GEM representative reference</h3><dl class="batter-facts">${fact("Representative genome ID", reference.genome_id)}${fact("Contigs", reference.contigs == null ? "" : formatted(reference.contigs))}${fact("Total bases", reference.bases == null ? "" : `${formatted(reference.bases)} bp`)}</dl></div>`;
  }

  function renderExperimentalSection(genome) {
    const record = genome.experimental;
    if (!genome.has_experimental) {
      return '<section class="batter-detail-section"><h2>Experimental 3′ end records</h2><p class="batter-reference-note">This genome has no experimental assembly record in the BTED catalogue.</p></section>';
    }
    const tracks = record.tracks.length ? `<div class="batter-study-list">${record.tracks.map((track) => {
      const citation = track.pmid
        ? `<a href="https://pubmed.ncbi.nlm.nih.gov/${encodeURIComponent(track.pmid)}/" target="_blank" rel="noopener">PMID ${esc(track.pmid)}</a>`
        : "Source record";
      const file = track.download_url
        ? `<a href="${esc(track.download_url)}">${track.file_status === "local_prepared" ? "Download local study GFF3" : "Download public GFF3"}</a>`
        : `<span class="batter-browser-state">${esc(fileStatusLabel(track.file_status))}</span>`;
      const signals = (track.signal_downloads || []).map(signal => `<a href="${esc(signal.url)}">${esc(signal.label)}</a>`).join(" · ");
      return `<article class="batter-study-card"><div><h3>${esc(track.source_id)}</h3><p>${esc(track.paper_title || track.assay || "Study-derived experimental 3′ end track")}</p></div><dl><dt>Records</dt><dd>${formatted(track.record_count)}</dd><dt>Evidence</dt><dd>${esc(track.evidence_class || "Not provided")}</dd><dt>Source</dt><dd>${citation}</dd><dt>File</dt><dd>${file}</dd><dt>BigWig</dt><dd>${signals || (track.has_bigwig ? "Data preparing" : "Not provided")}</dd></dl></article>`;
    }).join("")}</div>` : '<p class="batter-reference-note">The assembly is listed, but no experiment track has been prepared.</p>';
    const browserLink = "";
    return `<section class="batter-detail-section"><h2>Experimental 3′ end records</h2><p class="batter-reference-note">${formatted(record.endpoint_count)} records across ${formatted(record.track_count)} study tracks · ${esc(releaseText(record.source))}</p>${renderExperimentalReference(record)}${browserLink}${tracks}</section>`;
  }

  function renderBatterSection(genome) {
    if (!genome.has_batter) {
      return '<section class="batter-detail-section"><h2>BATTER records</h2><p class="batter-reference-note">No BATTER record has this complete genome ID.</p></section>';
    }
    const record = genome.batter;
    const noRecords = record.no_augmentation_records
      ? '<p class="batter-no-records"><strong>This genome has no augmentation records.</strong> The BATTER source contains no OTU augmentation or Rfam training records for this genome.</p>' : "";
    const card = (title, item) => `<article class="batter-file-card"><h3>${esc(title)}</h3><span class="batter-pending-badge">${esc(fileStatusLabel(item.file_status))}</span><p>Records: ${formatted(item.count)}</p><p>Source: ${esc(item.source || "Not provided")}</p>${item.source_windows !== undefined ? `<p>Source windows: ${formatted(item.source_windows)}</p>` : ""}</article>`;
    const pilotLink = pilotBrowserHref(genome.genome_id);
    const browserLink = "";
    const downloads = (record.downloads || []).map(file => `<a href="${esc(file.url)}">${esc(downloadLabels[file.filename] || file.filename)}</a>`).join(" · ");
    const releaseState = record.publication_status === "local_prepared" ? "Local prepared files · not publicly released" : ["public_download", "hf_preview"].includes(record.publication_status) ? "Files available" : record.publication_status === "held" ? "Held for reference validation" : "Data preparing";
    return `<section class="batter-detail-section"><h2>BATTER predictions and training records</h2><p class="batter-reference-note">${esc(record.otu_id)} · ${esc(record.genome_type)} · ${esc(record.source_collection)}. BATTER classification is shown when supplied; experimental-only genomes have no inferred classification.</p>${renderBatterReference(record)}${noRecords}${browserLink}<div class="batter-file-grid">${card("Predicted candidates", record.predictions)}${card("OTU augmentation", record.otu_augmentation)}${card("Rfam training", record.rfam_training)}</div><p class="batter-record-state">${esc(releaseState)}</p>${downloads ? `<p class="batter-downloads">${downloads}</p>` : ""}</section>`;
  }

  function renderDetail(genome) {
    const title = genome.organism_name || genome.genome_id;
    const membership = genome.membership === "both" ? "Experimental + BATTER" : genome.membership === "experimental" ? "Experimental only" : "BATTER only";
    const taxonomy = genome.taxonomy || {};
    const browser = pilotBrowserHref(genome.genome_id) || (genome.experimental.browser_available ? experimentalBrowserHref(genome.genome_id) : "");
    const browserSummary = browser
      ? `<p><a class="button batter-open-browser" href="${esc(browser)}" target="_blank" rel="noopener">Open genome browser ↗</a></p>`
      : '<p class="batter-browser-state">Data preparing</p>';
    document.getElementById("batter-detail-content").innerHTML = `
      <header class="batter-detail-heading"><p class="eyebrow">UNIFIED GENOME RECORD · ${esc(membership)}</p><h1>${esc(genome.genome_id)}</h1><p>${esc(title)}${genome.batter.otu_id ? ` · ${esc(genome.batter.otu_id)}` : ""}</p>${browserSummary}</header>
      <div class="batter-detail-metrics" aria-label="Record counts">
        <div><span>Experimental 3′ end records</span><strong>${formatted(genome.experimental.endpoint_count)}</strong></div>
        <div><span>BATTER predictions</span><strong>${formatted(genome.batter.predictions.count)}</strong></div>
        <div><span>OTU augmentation</span><strong>${formatted(genome.batter.otu_augmentation.count)}</strong></div>
        <div><span>Rfam training</span><strong>${formatted(genome.batter.rfam_training.count)}</strong></div>
      </div>
      <section class="batter-detail-section"><h2>Genome classification</h2><dl class="batter-facts">${fact("Complete genome ID", genome.genome_id)}${fact("Collection", membership)}${fact("Organism", title)}${fact("Domain", taxonomy.domain)}${fact("Phylum", taxonomy.phylum)}${fact("Class", taxonomy.class)}${fact("Order", taxonomy.order)}${fact("Family", taxonomy.family)}${fact("Genus", taxonomy.genus)}${fact("Species", taxonomy.species)}${fact("BATTER original source", genome.batter.source_collection)}${fact("Genome type", genome.batter.genome_type)}${fact("OTU", genome.batter.otu_id)}</dl></section>
      ${renderExperimentalSection(genome)}
      ${renderBatterSection(genome)}
      <section class="batter-detail-section batter-evidence-boundary"><h2>Record types</h2><p>Study-derived experimental records, model predictions, OTU augmentation, and Rfam training records are listed separately. A shared genome ID joins the records; no species-name matching is used.</p></section>`;
  }

  async function openGenome() {
    document.querySelectorAll('.batter-hero, .batter-stat-grid, .batter-provenance-note, .batter-evidence-grid').forEach(element => { element.hidden = true; });
    directory.hidden = true;
    detail.hidden = false;
    document.getElementById("batter-back").href = `batter-genomes.html${state.toString() ? `?${state}` : ""}`;
    try {
      const payload = await getJson(`/api/genomes/${encodeURIComponent(genomeId)}`);
      renderDetail(payload.data);
    } catch (error) {
      document.getElementById("batter-detail-content").innerHTML = `<p class="batter-error">Could not load genome ${esc(genomeId)}: ${esc(error.message)}</p>`;
    }
  }

  function setupControls() {
    searchInput.value = state.get("q") || "";
    if (evidenceSelect) {
      evidenceSelect.value = state.get("evidence") || "all";
      evidenceSelect.addEventListener("change", () => {
        state.delete("membership");
        if (evidenceSelect.value === "all") state.delete("evidence"); else state.set("evidence", evidenceSelect.value);
        refresh();
      });
      bigwigSelect.value = ["true", "1"].includes(state.get("has_bigwig")) ? "true" : ["false", "0"].includes(state.get("has_bigwig")) ? "false" : "";
      bigwigSelect.addEventListener("change", () => {
        if (bigwigSelect.value) state.set("has_bigwig", bigwigSelect.value); else state.delete("has_bigwig");
        refresh();
      });
    }
    if (membershipSelect) {
      membershipSelect.value = state.get("membership") || "all";
      membershipSelect.addEventListener("change", () => {
        if (membershipSelect.value === "all") state.delete("membership"); else state.set("membership", membershipSelect.value);
        refresh();
      });
    }
    sourceSelect.addEventListener("change", () => {
      if (sourceSelect.value) state.set("source", sourceSelect.value); else state.delete("source");
      refresh();
    });
    typeSelect.addEventListener("change", () => {
      if (typeSelect.value) state.set("type", typeSelect.value); else state.delete("type");
      refresh();
    });
    searchInput.addEventListener("input", () => {
      if (searchInput.value.trim()) state.set("q", searchInput.value.trim()); else state.delete("q");
      invalidateRequests();
      setLoading();
      errorPanel.hidden = true;
      searchTimer = window.setTimeout(() => refresh(), 300);
    });
    sortButtons.forEach((button) => {
      button.addEventListener("click", () => {
        const field = button.dataset.batterSort;
        const current = state.get("sort") || "genome_id_asc";
        const direction = current === `${field}_asc` ? "desc" : current === `${field}_desc` ? "asc" : field === "genome_id" ? "asc" : "desc";
        state.set("sort", `${field}_${direction}`);
        refresh();
      });
    });
    const pageSize = document.getElementById("batter-page-size");
    pageSize.value = ["25", "50", "100"].includes(state.get("page_size")) ? state.get("page_size") : "50";
    pageSize.addEventListener("change", () => {
      state.set("page_size", pageSize.value);
      refresh();
    });
    ranks.forEach((rank, index) => {
      const select = document.getElementById(`batter-${rank}`);
      select.addEventListener("change", () => {
        if (select.value) state.set(rank, select.value); else state.delete(rank);
        clearChildRanks(index + 1);
        facetsDirty = true;
        refresh({ facets: true });
      });
    });
    document.getElementById("batter-clear").addEventListener("click", () => {
      for (const key of [...state.keys()]) state.delete(key);
      state.set("sort", "genome_id_asc");
      state.set("page_size", "50");
      searchInput.value = "";
      sourceSelect.value = "";
      typeSelect.value = "";
      if (membershipSelect) membershipSelect.value = "all";
      if (evidenceSelect) evidenceSelect.value = "all";
      if (bigwigSelect) bigwigSelect.value = "";
      pageSize.value = "50";
      clearChildRanks(0);
      refresh({ facets: true });
    });
    document.getElementById("batter-retry").addEventListener("click", () => refresh({ resetPage: false }));
    document.getElementById("batter-previous").addEventListener("click", () => {
      const page = Math.max(1, Number(state.get("page") || 1) - 1);
      state.set("page", String(page));
      refresh({ resetPage: false });
    });
    document.getElementById("batter-next").addEventListener("click", () => {
      state.set("page", String(Number(state.get("page") || 1) + 1));
      refresh({ resetPage: false });
    });
    document.getElementById("batter-page-jump").addEventListener("change", (event) => {
      const maximum = Number(event.target.max || 1);
      const requested = Number(event.target.value || 1);
      const page = Number.isSafeInteger(requested) ? Math.max(1, Math.min(maximum, requested)) : 1;
      state.set("page", String(page));
      refresh({ resetPage: false });
    });
  }

  async function init() {
    await Promise.all([loadPilotManifest(), loadStats().catch(() => {})]);
    if (genomeId) {
      await openGenome();
      return;
    }
    setupControls();
    await refresh({ facets: true, resetPage: false });
  }

  init();
})();
