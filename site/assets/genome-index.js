(function () {
  "use strict";

  const form = document.querySelector("[data-genome-search-form]");
  const search = document.querySelector("[data-genome-search]");
  const tbody = document.querySelector("[data-genome-results]");
  const count = document.querySelector("[data-visible-count]");
  const empty = document.querySelector("[data-empty]");
  const clear = document.querySelector("[data-clear-filters]");
  const dataType = document.querySelector("[data-genome-dataset]");
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
  const sortFields = new Set(["accession", "organism", "studies", "endpoints", "signal"]);
  const numericFields = new Set(["studies", "endpoints", "signal"]);
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
    sortField = sortFields.has(params.get("sort")) ? params.get("sort") : "accession";
    direction = (params.get("direction") || params.get("order")) === "desc" ? "desc" : "asc";
    if (mobileSort) mobileSort.value = sortField;
  }

  function updateUrl() {
    const url = new URL(window.location.href);
    ["q", "search", "query", "accession", "assembly", "taxon", "rank", "phylum", "class", "order", "family", "genus", "study", "assay", "evidence", "signal", "sort", "dataset", "direction"]
      .forEach((key) => url.searchParams.delete(key));
    if (search.value.trim()) url.searchParams.set("q", search.value.trim());
    taxonomy.forEach(select => { if (select.value) url.searchParams.set(select.dataset.taxonomyRank, select.value); });
    if (dataType?.value) url.searchParams.set("dataset", dataType.value);
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
    if (dataType?.value) {
      const available = { experimental: Number(row.dataset.sortEndpoints) > 0,
        prediction: Number(row.batter?.[10]) > 0, augmentation: Number(row.batter?.[5] || 0) + Number(row.batter?.[7] || 0) > 0 };
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
    const left = a.dataset[`sort${sortField[0].toUpperCase()}${sortField.slice(1)}`];
    const right = b.dataset[`sort${sortField[0].toUpperCase()}${sortField.slice(1)}`];
    const primary = numericFields.has(sortField) ? Number(left) - Number(right) : collator.compare(left, right);
    const ordered = direction === "desc" ? -primary : primary;
    return ordered || collator.compare(a.dataset.sortAccession, b.dataset.sortAccession);
  }

  function render() {
    if (!catalogueReady) return;
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
  taxonomy.forEach((select, index) => select.addEventListener("change", () => {
    taxonomy.slice(index + 1).forEach(child => { child.value = ""; });
    updateTaxa(); changed();
  }));
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
    taxonomy.forEach(select => { select.value = ""; });
    updateTaxa();
    if (dataType) dataType.value = "";
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
    catalogueReady = false;
    form.inert = true;
    retry.hidden = true;
    loadStatus.textContent = "Loading genomes…";
    try {
      const response = await fetch("assets/batter-browser.json");
      if (!response.ok) throw new Error();
      const records = (await response.json()).genomes;
      const indexed = new Map(rows.map(row => [row.dataset.sortAccession.toUpperCase(), row]));
      for (const record of records) {
        let row = indexed.get(record[0].toUpperCase());
        if (!row) {
          row = { dataset: { genomeSearch: "", sortAccession: record[0].toLowerCase(), sortOrganism: record[3].toLowerCase(), sortStudies: "1", sortEndpoints: "0", sortSignal: "0" }, sources: [] };
          const ranks = { p: "Phylum", c: "Class", o: "Order", f: "Family", g: "Genus" };
          for (const taxon of (record[11] || "").split(";")) {
            const rank = ranks[taxon[0]], value = taxon.slice(3);
            if (rank && value) row.dataset[`taxonomy${rank}`] = value;
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
      loadStatus.textContent = "Upload in progress. Each genome is listed once; training windows are excluded from span counts.";
    } catch {
      loadStatus.textContent = "Uploaded genome list unavailable. Experimental genomes remain available."; retry.hidden = false;
    } finally {
      catalogueReady = true;
      readUrl(); render();
      tbody.hidden = false;
      if (resultCount) resultCount.hidden = false;
      form.inert = false;
    }
  }
  if (dataType) { retry.addEventListener("click", loadGenomes); loadGenomes(); }
})();
