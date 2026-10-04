(function () {
  "use strict";

  const form = document.querySelector("[data-genome-search-form]");
  const search = document.querySelector("[data-genome-search]");
  const tbody = document.querySelector("[data-genome-results]");
  const count = document.querySelector("[data-visible-count]");
  const resultRange = document.querySelector("[data-result-range]");
  const empty = document.querySelector("[data-empty]");
  const clear = document.querySelector("[data-clear-filters]");
  const dataType = document.querySelector("[data-genome-dataset]");
  const filters = [
    ["source", document.querySelector("[data-genome-source-filter]"), "genomeSource"],
    ["genome_type", document.querySelector("[data-genome-type-filter]"), "genomeType"],
    ["annotation", document.querySelector("[data-genome-annotation-filter]"), "genomeAnnotation"],
  ].filter(([, select]) => select);
  const resultCount = document.querySelector(".genome-result-count");
  const previous = document.querySelector("[data-genome-prev]");
  const next = document.querySelector("[data-genome-next]");
  const pageNumber = document.querySelector("[data-genome-page-number]");
  const loadStatus = document.querySelector("[data-genome-load-status]");
  const retry = document.querySelector("[data-genome-retry]");
  const taxonomy = Array.from(document.querySelectorAll("[data-taxonomy-rank]"));
  if (!form || !search || !tbody) return;

  const rows = Array.from(tbody.querySelectorAll("[data-genome-row]"));
  if (dataType) rows.forEach(row => { row.node = row; });
  const sortButtons = Array.from(document.querySelectorAll("[data-sort]"));
  const mobileSort = document.querySelector("[data-sort-select]");
  const mobileDirection = document.querySelector("[data-sort-direction]");
  const sortFields = new Set(["accession", "organism", "size", "endpoints", ...(dataType ? ["predictions", "training"] : [])]);
  const numericFields = new Set(["size", "endpoints", "predictions", "training"]);
  const collator = new Intl.Collator("en", { numeric: true, sensitivity: "base" });
  let sortField = "accession";
  let direction = "asc";
  let page = 0;
  const pageSize = 25;
  let catalogueReady = !dataType;

  function validOption(select, value) {
    return Array.from(select.options).some((option) => option.value === value) ? value : "";
  }

  function readUrl() {
    const params = new URLSearchParams(window.location.search);
    search.value = params.get("q") || params.get("search") || params.get("query")
      || params.get("accession") || params.get("assembly") || "";
    const [legacyRank, ...legacyName] = (params.get("taxon") || "").split(":");
    updateTaxa(Object.fromEntries(taxonomy.map(select => {
      const rank = select.dataset.taxonomyRank;
      return [rank, params.get(rank) || (legacyRank === rank ? legacyName.join(":") : "")];
    })));
    if (dataType) dataType.value = validOption(dataType, params.get("dataset") || "");
    filters.forEach(([param, select]) => { select.value = validOption(select, params.get(param) || ""); });
    sortField = sortFields.has(params.get("sort")) ? params.get("sort") : "accession";
    direction = (params.get("direction") || params.get("order")) === "desc" ? "desc" : "asc";
    if (mobileSort) mobileSort.value = sortField;
  }

  function updateUrl() {
    const url = new URL(window.location.href);
    ["q", "search", "query", "accession", "assembly", "taxon", "rank", "phylum", "class", "order", "family", "genus", "study", "assay", "evidence", "signal", "sort", "dataset", "direction", ...filters.map(([param]) => param)]
      .forEach((key) => url.searchParams.delete(key));
    if (search.value.trim()) url.searchParams.set("q", search.value.trim());
    taxonomy.forEach(select => { if (select.value) url.searchParams.set(select.dataset.taxonomyRank, select.value); });
    if (dataType?.value) url.searchParams.set("dataset", dataType.value);
    filters.forEach(([param, select]) => { if (select.value) url.searchParams.set(param, select.value); });
    if (sortField !== "accession") url.searchParams.set("sort", sortField);
    if (direction !== "asc") url.searchParams.set("direction", direction);
    window.history.replaceState({}, "", url);
  }

  function updateTaxa(selection = {}) {
    let matching = rows;
    let missingParent = false;
    for (const select of taxonomy) {
      const rank = select.dataset.taxonomyRank;
      const key = `taxonomy${rank[0].toUpperCase()}${rank.slice(1)}`;
      const selected = selection[rank] ?? select.value;
      select.disabled = missingParent;
      const values = missingParent ? [] : [...new Set(matching.map(row => row.dataset[key]).filter(Boolean))].sort(collator.compare);
      const all = document.createElement("option"); all.value = ""; all.textContent = "All";
      select.replaceChildren(all);
      for (const value of values) {
        const option = document.createElement("option"); option.value = value; option.textContent = value; select.append(option);
      }
      select.value = values.includes(selected) ? selected : "";
      if (select.value) matching = matching.filter(row => row.dataset[key] === select.value);
      else missingParent = true;
    }
  }

  function sourceMatches(row, query) {
    if (filters.some(([, select, key]) => select.value && row.dataset[key] !== select.value)) return false;
    if (dataType?.value) {
      const available = { experimental: Number(row.dataset.sortEndpoints) > 0,
        prediction: Number(row.batter?.[10]) > 0, augmentation: Number(row.batter?.[5] || 0) + Number(row.batter?.[7] || 0) > 0 };
      available.experimental_prediction = available.experimental && available.prediction;
      if (!available[dataType.value]) return false;
    }
    for (const select of taxonomy) {
      const rank = select.dataset.taxonomyRank;
      const key = `taxonomy${rank[0].toUpperCase()}${rank.slice(1)}`;
      if (select.value && row.dataset[key] !== select.value) return false;
    }
    const tokens = query.normalize("NFKC").split(/[^\p{L}\p{N}_.-]+/u).filter(Boolean);
    const sources = row.sources || Array.from(row.querySelectorAll("[data-source-filter]"));
    const text = `${row.dataset.genomeSearch} ${sources.map(source => source.dataset.search).join(" ")}`.normalize("NFKC").toLocaleLowerCase();
    return tokens.every(token => text.includes(token));
  }

  function compareRows(a, b) {
    const left = a.dataset[`sort${sortField[0].toUpperCase()}${sortField.slice(1)}`] ?? 0;
    const right = b.dataset[`sort${sortField[0].toUpperCase()}${sortField.slice(1)}`] ?? 0;
    if (sortField === "size" && (!Number(left) || !Number(right))) {
      return Number(!Number(left)) - Number(!Number(right)) || collator.compare(a.dataset.sortAccession, b.dataset.sortAccession);
    }
    const primary = numericFields.has(sortField) ? Number(left) - Number(right) : collator.compare(left, right);
    const ordered = direction === "desc" ? -primary : primary;
    return ordered || collator.compare(a.dataset.sortAccession, b.dataset.sortAccession);
  }

  function render() {
    if (!catalogueReady) return;
    const query = search.value.trim().toLocaleLowerCase();
    const matched = [];
    rows.sort(compareRows).forEach((row) => {
      row.hidden = !sourceMatches(row, query);
      if (!row.hidden) matched.push(row);
      if (!dataType) tbody.append(row);
    });
    if (dataType) {
      tbody.replaceChildren();
      page = Math.max(0, Math.min(page, Math.ceil(matched.length / pageSize) - 1));
      for (const row of matched.slice(page * pageSize, (page + 1) * pageSize)) tbody.append(row.node || genomeRow(row));
      previous.disabled = page === 0; next.disabled = (page + 1) * pageSize >= matched.length;
      pageNumber.textContent = matched.length ? `${page + 1} / ${Math.ceil(matched.length / pageSize)}` : "";
    }
    if (count) count.textContent = matched.length.toLocaleString("en-US");
    if (resultRange) {
      const start = matched.length ? (dataType ? page * pageSize + 1 : 1) : 0;
      const end = dataType ? Math.min((page + 1) * pageSize, matched.length) : matched.length;
      resultRange.textContent = `Showing ${start.toLocaleString("en-US")}–${end.toLocaleString("en-US")}`;
    }
    if (empty) empty.hidden = matched.length !== 0;
    sortButtons.forEach((button) => {
      const th = button.closest("th");
      if (th) th.setAttribute("aria-sort", button.dataset.sort === sortField
        ? (direction === "asc" ? "ascending" : "descending") : "none");
    });
    if (mobileSort) mobileSort.value = sortField;
    if (mobileDirection) mobileDirection.textContent = direction === "asc" ? "Ascending" : "Descending";
  }

  function changed() {
    page = 0;
    updateUrl();
    render();
  }

  search.addEventListener("input", changed);
  form.addEventListener("submit", (event) => { event.preventDefault(); changed(); });
  taxonomy.forEach((select, index) => select.addEventListener("change", () => {
    taxonomy.slice(index + 1).forEach(child => { child.value = ""; });
    updateTaxa(); changed();
  }));
  dataType?.addEventListener("change", changed);
  filters.forEach(([, select]) => select.addEventListener("change", changed));
  previous?.addEventListener("click", () => { page--; render(); });
  next?.addEventListener("click", () => { page++; render(); });
  sortButtons.forEach((button) => button.addEventListener("click", () => {
    const next = button.dataset.sort;
    if (!sortFields.has(next)) return;
    if (sortField === next) direction = direction === "asc" ? "desc" : "asc";
    else { sortField = next; direction = "asc"; }
    changed();
  }));
  mobileSort?.addEventListener("change", () => {
    if (!sortFields.has(mobileSort.value)) return;
    sortField = mobileSort.value;
    direction = "asc";
    changed();
  });
  mobileDirection?.addEventListener("click", () => {
    direction = direction === "asc" ? "desc" : "asc";
    changed();
  });
  clear?.addEventListener("click", () => {
    search.value = "";
    taxonomy.forEach(select => { select.value = ""; });
    updateTaxa();
    if (dataType) dataType.value = "";
    filters.forEach(([, select]) => { select.value = ""; });
    sortField = "accession";
    direction = "asc";
    changed();
  });
  window.addEventListener("popstate", () => { page = 0; readUrl(); render(); });
  updateSourceOptions();
  readUrl();
  render();

  function genomeRow(row) {
    const record = row.batter;
    const tr = document.createElement("tr");
    const href = `genomes/${encodeURIComponent(record[0])}`;
    for (const label of ["Genome ID", "Genome source", "Organism", "Taxonomy", "Assembly size", "Terminator data", "Annotation"]) {
      const td = document.createElement("td"); td.dataset.label = label;
      if (label === "Genome ID") {
        const link = document.createElement("a"), code = document.createElement("code");
        link.className = "genome-table-name"; link.href = href; code.textContent = record[0]; link.append(code); td.append(link);
        showOtu(td, record[2]);
      } else if (label === "Genome source") {
        td.textContent = referenceSource(record[12]);
      } else if (label === "Organism") {
        const name = document.createElement("span"); name.className = "genome-organism"; name.textContent = record[3]; td.append(name);
        const type = document.createElement("small"); type.textContent = record[4] === "MAG" ? "Metagenome-assembled" : record[4]; td.append(type);
      } else if (label === "Taxonomy") {
        const phylum = document.createElement("span"), genus = document.createElement("small");
        phylum.textContent = row.dataset.taxonomyPhylum || "Unclassified"; genus.textContent = row.dataset.taxonomyGenus || "Genus not assigned"; td.append(phylum, genus);
      } else if (label === "Assembly size") {
        td.dataset.referenceSize = ""; referenceSize(td, row);
      } else if (label === "Terminator data") {
        const counts = document.createElement("div"); counts.className = "genome-data-counts";
        for (const [type, field, text, title] of [["experimental", "endpoints", "experimental endpoints", "Published transcript 3′ end records"], ["prediction", "predictions", "predictions", "Model predictions"], ["training", "training", "augmentation / Rfam", "OTU augmentation and Rfam training regions; context windows excluded"]]) {
          const badge = document.createElement("span"), number = document.createElement("b");
          badge.className = `genome-evidence ${type}${Number(row.dataset[`sort${field[0].toUpperCase()}${field.slice(1)}`]) ? "" : " unavailable"}`;
          badge.title = title; number.textContent = Number(row.dataset[`sort${field[0].toUpperCase()}${field.slice(1)}`] || 0).toLocaleString("en-US"); badge.append(number, ` ${text}`); counts.append(badge);
        }
        td.append(counts);
      } else {
        td.append(annotationBadge(record[9]));
      }
      tr.append(td);
    }
    return tr;
  }

  function showOtu(cell, otu) {
    let label = cell.querySelector("[data-gem-otu]");
    if (!otu) { label?.remove(); return; }
    if (!label) { label = document.createElement("small"); label.dataset.gemOtu = ""; cell.append(label); }
    label.textContent = `GEM OTU: ${otu}`;
    label.title = "Species-level cluster; coordinates refer to this representative genome, not all cluster members.";
  }

  function referenceSource(source) {
    return ({ "NCBI-RefSeq": "NCBI RefSeq", "NCBI-MAG": "NCBI GenBank", "NCBI-SAG": "NCBI GenBank" })[source] || source || "Not cataloged";
  }

  function updateSourceOptions() {
    const select = filters.find(([param]) => param === "source")?.[1];
    if (!select) return;
    const all = document.createElement("option"); all.value = ""; all.textContent = "All sources";
    select.replaceChildren(all);
    for (const source of [...new Set(rows.map(row => row.dataset.genomeSource).filter(Boolean))].sort(collator.compare)) {
      const option = document.createElement("option"); option.value = source; option.textContent = source; select.append(option);
    }
  }

  function referenceSize(cell, row) {
    cell.replaceChildren();
    cell.title = "Browser reference length; may cover a subset of assembly contigs";
    const bases = document.createElement("span");
    bases.textContent = row.referenceSize ? `${row.referenceSize[0].toLocaleString("en-US")} bp` : "Not cataloged";
    cell.append(bases);
    if (row.referenceSize) { const contigs = document.createElement("small"); contigs.textContent = `${row.referenceSize[1].toLocaleString("en-US")} ${row.referenceSize[1] === 1 ? "contig" : "contigs"}`; cell.append(contigs); }
    else bases.className = "muted";
  }

  function annotationLabel(status) {
    return ({ matched: "Available", mismatch: "Incompatible", contig_mismatch: "Incompatible", unavailable: "Missing", download_failed: "Unavailable", invalid_gff: "Unavailable" })[status] || "Not cataloged";
  }

  function annotationBadge(status) {
    const badge = document.createElement("span");
    badge.className = `genome-annotation${status === "matched" ? "" : " unavailable"}`;
    badge.textContent = annotationLabel(status);
    return badge;
  }

  async function loadGenomes() {
    catalogueReady = false;
    form.inert = true;
    retry.hidden = true;
    loadStatus.textContent = "Loading genomes…";
    try {
      const response = await fetch("assets/batter-browser.json");
      if (!response.ok) throw new Error();
      const catalogue = await response.json();
      const records = catalogue.genomes;
      const indexed = new Map(rows.map(row => [row.dataset.sortAccession.toUpperCase(), row]));
      for (const record of records) {
        let row = indexed.get(record[0].toUpperCase());
        if (!row) {
          row = { dataset: { genomeSearch: "", sortAccession: record[0].toLowerCase(), sortOrganism: record[3].toLowerCase(), sortEndpoints: "0" }, sources: [] };
          const ranks = { p: "Phylum", c: "Class", o: "Order", f: "Family", g: "Genus" };
          for (const taxon of (record[11] || "").split(";")) {
            const rank = ranks[taxon[0]], value = taxon.slice(3);
            if (rank && value) row.dataset[`taxonomy${rank}`] = value;
          }
          rows.push(row); indexed.set(record[0].toUpperCase(), row);
        }
        row.batter = record;
        row.dataset.genomeSource = referenceSource(record[12]);
        row.dataset.genomeType = record[4] || "unknown";
        row.dataset.genomeAnnotation = annotationLabel(record[9]);
        row.dataset.genomeSearch += ` ${record[0]} ${record[2]} ${record[3]} ${record[11] || ""} ${referenceSource(record[12])}`.toLowerCase();
        row.sources ||= Array.from(row.querySelectorAll("[data-source-filter]"));
        row.dataset.sortPredictions = String(record[10]);
        row.dataset.sortTraining = String(record[5] + record[7]);
        row.referenceSize = catalogue.reference_sizes?.[record[0]];
        row.dataset.sortSize = row.referenceSize ? String(row.referenceSize[0]) : "";
        if (record[10] > 0) row.dataset.genomeSearch += " batter predictions 42402588";
        if (record[5] + record[7] > 0) row.dataset.genomeSearch += " batter augmentation training 42402588";
        if (row.node) {
          row.node.querySelector('[data-label="Genome source"]').textContent = referenceSource(record[12]);
          showOtu(row.node.querySelector('[data-label="Genome ID"]'), record[2]);
          for (const [selector, value] of [["[data-prediction-count]", record[10]], ["[data-augmentation-count]", record[5] + record[7]]]) {
            const number = row.node.querySelector(selector); number.textContent = value.toLocaleString("en-US"); number.parentElement.classList.toggle("unavailable", !value);
          }
          referenceSize(row.node.querySelector("[data-reference-size]"), row);
          row.node.querySelector('[data-label="Annotation"]').replaceChildren(annotationBadge(record[9]));
        }
      }
      loadStatus.textContent = "Upload in progress. Training regions include OTU augmentation and Rfam; context windows are excluded.";
    } catch {
      loadStatus.textContent = "Uploaded genome list unavailable. Experimental genomes remain available."; retry.hidden = false;
    } finally {
      catalogueReady = true;
      updateSourceOptions();
      readUrl(); render();
      tbody.hidden = false;
      if (resultCount) resultCount.hidden = false;
      form.inert = false;
    }
  }
  if (dataType) { retry.addEventListener("click", loadGenomes); loadGenomes(); }
})();
