(function () {
  "use strict";

  const form = document.querySelector("[data-genome-search-form]");
  const search = document.querySelector("[data-genome-search]");
  const tbody = document.querySelector("[data-genome-results]");
  const count = document.querySelector("[data-visible-count]");
  const empty = document.querySelector("[data-empty]");
  const clear = document.querySelector("[data-clear-filters]");
  const dataType = document.querySelector("[data-genome-dataset]");
  const previous = document.querySelector("[data-genome-prev]");
  const next = document.querySelector("[data-genome-next]");
  const pageNumber = document.querySelector("[data-genome-page-number]");
  const loadStatus = document.querySelector("[data-genome-load-status]");
  const retry = document.querySelector("[data-genome-retry]");
  const taxonomy = document.querySelector("[data-filter-taxonomy]");
  const filters = {
    study: document.querySelector("[data-filter-study]"),
    assay: document.querySelector("[data-filter-assay]"),
    evidence: document.querySelector("[data-filter-evidence]"),
    signal: document.querySelector("[data-filter-signal]"),
  };
  if (!form || !search || !tbody) return;

  const rows = Array.from(tbody.querySelectorAll("[data-genome-row]"));
  if (dataType) rows.forEach(row => { row.node = row; });
  const sortButtons = Array.from(document.querySelectorAll("[data-sort]"));
  const mobileSort = document.querySelector("[data-sort-select]");
  const mobileDirection = document.querySelector("[data-sort-direction]");
  const sortFields = new Set(["accession", "organism", "studies", "endpoints", "signal"]);
  const numericFields = new Set(["studies", "endpoints", "signal"]);
  const collator = new Intl.Collator("en", { numeric: true, sensitivity: "base" });
  let sortField = "accession";
  let direction = "asc";
  let page = 0;
  const pageSize = 25;

  function validOption(select, value) {
    return Array.from(select.options).some((option) => option.value === value) ? value : "";
  }

  function readUrl() {
    const params = new URLSearchParams(window.location.search);
    search.value = params.get("q") || params.get("search") || params.get("query")
      || params.get("accession") || params.get("assembly") || "";
    Object.entries(filters).forEach(([key, select]) => {
      if (select) select.value = validOption(select, params.get(key) || "");
    });
    if (taxonomy) taxonomy.value = validOption(taxonomy, params.get("taxon") || "");
    if (dataType) dataType.value = validOption(dataType, params.get("dataset") || "");
    sortField = sortFields.has(params.get("sort")) ? params.get("sort") : "accession";
    direction = params.get("order") === "desc" ? "desc" : "asc";
    if (mobileSort) mobileSort.value = sortField;
  }

  function updateUrl() {
    const url = new URL(window.location.href);
    ["q", "search", "query", "accession", "assembly", "taxon", "study", "assay", "evidence", "signal", "sort", "order", "dataset"]
      .forEach((key) => url.searchParams.delete(key));
    if (search.value.trim()) url.searchParams.set("q", search.value.trim());
    if (taxonomy?.value) url.searchParams.set("taxon", taxonomy.value);
    if (dataType?.value) url.searchParams.set("dataset", dataType.value);
    Object.entries(filters).forEach(([key, select]) => {
      if (select && select.value) url.searchParams.set(key, select.value);
    });
    if (sortField !== "accession") url.searchParams.set("sort", sortField);
    if (direction !== "asc") url.searchParams.set("order", direction);
    window.history.replaceState({}, "", url);
  }

  function sourceMatches(row, query) {
    if (dataType?.value) {
      const available = { experimental: Number(row.dataset.sortEndpoints) > 0,
        prediction: Number(row.batter?.[10]) > 0, augmentation: Number(row.batter?.[5] || 0) + Number(row.batter?.[7] || 0) > 0 };
      if (!available[dataType.value]) return false;
    }
    if (taxonomy?.value) {
      const separator = taxonomy.value.indexOf(":");
      const rank = taxonomy.value.slice(0, separator);
      const value = taxonomy.value.slice(separator + 1);
      const key = `taxonomy${rank[0].toUpperCase()}${rank.slice(1)}`;
      if (row.dataset[key] !== value) return false;
    }
    const tokens = query.normalize("NFKC").split(/[^\p{L}\p{N}_.-]+/u).filter(Boolean);
    const sources = row.sources || Array.from(row.querySelectorAll("[data-source-filter]"));
    return sources.some((source) => {
      const text = `${row.dataset.genomeSearch} ${source.dataset.search}`.normalize("NFKC");
      if (!tokens.every((token) => text.includes(token))) return false;
      return Object.entries(filters).every(([key, select]) => !select || !select.value || source.dataset[key] === select.value);
    });
  }

  function compareRows(a, b) {
    const left = a.dataset[`sort${sortField[0].toUpperCase()}${sortField.slice(1)}`];
    const right = b.dataset[`sort${sortField[0].toUpperCase()}${sortField.slice(1)}`];
    const primary = numericFields.has(sortField) ? Number(left) - Number(right) : collator.compare(left, right);
    const ordered = direction === "desc" ? -primary : primary;
    return ordered || collator.compare(a.dataset.sortAccession, b.dataset.sortAccession);
  }

  function render() {
    const query = search.value.trim().toLocaleLowerCase();
    let visible = 0;
    const matched = [];
    rows.sort(compareRows).forEach((row) => {
      row.hidden = !sourceMatches(row, query);
      if (!row.hidden) { visible += 1; matched.push(row); }
      if (!dataType) tbody.append(row);
    });
    if (dataType) {
      tbody.replaceChildren();
      page = Math.max(0, Math.min(page, Math.ceil(matched.length / pageSize) - 1));
      for (const row of matched.slice(page * pageSize, (page + 1) * pageSize)) tbody.append(row.node || genomeRow(row));
      previous.disabled = page === 0; next.disabled = (page + 1) * pageSize >= matched.length;
      pageNumber.textContent = matched.length ? `${page + 1} / ${Math.ceil(matched.length / pageSize)}` : "";
      document.querySelector("[data-total-count]").textContent = rows.length.toLocaleString("en-US");
    }
    if (count) count.textContent = String(visible);
    if (empty) empty.hidden = visible !== 0;
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
  Object.values(filters).forEach((select) => select?.addEventListener("change", changed));
  taxonomy?.addEventListener("change", changed);
  dataType?.addEventListener("change", changed);
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
    if (taxonomy) taxonomy.value = "";
    if (dataType) dataType.value = "";
    Object.values(filters).forEach((select) => { if (select) select.value = ""; });
    sortField = "accession";
    direction = "asc";
    changed();
  });
  window.addEventListener("popstate", () => { readUrl(); render(); });
  readUrl();
  render();

  function genomeRow(row) {
    const record = row.batter;
    const tr = document.createElement("tr");
    const href = `genomes/${encodeURIComponent(record[0])}`;
    const labels = ["Organism", "Assembly", "Phylum", "Studies", "Methods", "Endpoints", "Predicted", "Training spans", "Signal", "Open"];
    const values = [record[3], `${record[0]} · ${record[2]}`, row.dataset.taxonomyPhylum || "Not assigned", row.dataset.sortStudies, row.methods, "0", Number(record[10]).toLocaleString("en-US"), (record[5] + record[7]).toLocaleString("en-US"), "No signal", "Open genome"];
    values.forEach((value, i) => {
      const td = document.createElement("td"); td.dataset.label = labels[i];
      if (i === 0 || i === 9) { const link = document.createElement("a"); link.textContent = value; link.href = href; td.append(link); }
      else td.textContent = value;
      tr.append(td);
    });
    return tr;
  }

  async function loadGenomes() {
    retry.hidden = true;
    loadStatus.textContent = "Loading uploaded genomes…";
    try {
      const response = await fetch("assets/batter-browser.json");
      if (!response.ok) throw new Error();
      const records = (await response.json()).genomes;
      const indexed = new Map(rows.map(row => [row.dataset.sortAccession.toUpperCase(), row]));
      const taxa = new Set();
      for (const record of records) {
        let row = indexed.get(record[0].toUpperCase());
        if (!row) {
          row = { dataset: { genomeSearch: "", sortAccession: record[0].toLowerCase(), sortOrganism: record[3].toLowerCase(), sortStudies: "1", sortEndpoints: "0", sortSignal: "0" }, sources: [] };
          const ranks = { p: "Phylum", c: "Class", o: "Order", f: "Family", g: "Genus" };
          for (const taxon of (record[11] || "").split(";")) {
            const rank = ranks[taxon[0]], value = taxon.slice(3);
            if (rank && value) { row.dataset[`taxonomy${rank}`] = value; taxa.add(`${rank.toLowerCase()}:${value}`); }
          }
          rows.push(row); indexed.set(record[0].toUpperCase(), row);
        }
        row.batter = record;
        row.dataset.genomeSearch += ` ${record[0]} ${record[2]} ${record[3]} ${record[11] || ""}`.toLowerCase();
        row.sources ||= Array.from(row.querySelectorAll("[data-source-filter]"));
        if (record[10] > 0 && !row.sources.some(source => source.dataset.evidence === "model_prediction")) row.sources.push({ dataset: { search: "batter predictions 42402588", study: "42402588", assay: "BATTER-TPE", published: "yes", evidence: "model_prediction", signal: "no" } });
        if (record[5] + record[7] > 0 && !row.sources.some(source => source.dataset.evidence === "training_augmentation")) row.sources.push({ dataset: { search: "batter augmentation training 42402588", study: "42402588", assay: "Training augmentation", published: "yes", evidence: "training_augmentation", signal: "no" } });
        const published = row.sources.filter(source => source.dataset.published === "yes");
        row.dataset.sortStudies = String(new Set(published.map(source => source.dataset.study)).size);
        row.methods = [...new Set(published.map(source => source.dataset.assay).filter(Boolean))].sort().join(" · ") || "—";
        if (row.node) {
          row.node.querySelector('[data-label="Studies"]').textContent = row.dataset.sortStudies;
          row.node.querySelector('[data-label="Methods"]').textContent = row.methods;
          row.node.querySelector("[data-prediction-count]").textContent = Number(record[10]).toLocaleString("en-US");
          row.node.querySelector("[data-augmentation-count]").textContent = (record[5] + record[7]).toLocaleString("en-US");
        }
      }
      function addOption(select, value, label) {
        if (!select || Array.from(select.options).some(option => option.value === value)) return;
        const option = document.createElement("option"); option.value = value; option.textContent = label; select.append(option);
      }
      const knownTaxa = new Set(Array.from(taxonomy.options).map(option => option.value));
      for (const taxon of [...taxa].sort()) {
        if (knownTaxa.has(taxon)) continue;
        const option = document.createElement("option"); option.value = taxon; option.textContent = taxon.replace(":", ": "); taxonomy.append(option);
      }
      addOption(filters.study, "42402588", "BATTER · PMID 42402588");
      for (const method of ["BATTER-TPE", "Training augmentation"]) addOption(filters.assay, method, method);
      addOption(filters.evidence, "model_prediction", "Model prediction"); addOption(filters.evidence, "training_augmentation", "Training augmentation");
      loadStatus.textContent = "Upload in progress. Each genome is listed once; training windows are excluded from span counts.";
      readUrl(); render();
    } catch {
      loadStatus.textContent = "Uploaded genome list unavailable. Experimental genomes remain available."; retry.hidden = false;
    }
  }
  if (dataType) { retry.addEventListener("click", loadGenomes); loadGenomes(); }
})();
