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
  const sortFields = new Set(["accession", "organism", "size", "endpoints", ...(dataType ? ["predictions", "training"] : [])]);
  const numericFields = new Set(["size", "endpoints", "predictions", "training"]);
  const collator = new Intl.Collator("en", { numeric: true, sensitivity: "base" });
  const defaultSort = form.dataset.defaultSort || "endpoints";
  let sortField = defaultSort;
  let direction = "desc";
  let page = 0;
  const pageSize = 25;
  let catalogueReady = !dataType;
  let sortedBy = "";
  if (form.dataset.genomePages) { initPaged(); return; }

  function updateSortHeaders() {
    sortButtons.forEach(button => {
      button.dataset.sortDirection = button.dataset.sort === sortField ? direction : "";
      button.closest("th")?.setAttribute("aria-sort", "none");
    });
    sortButtons.find(button => button.dataset.sort === sortField)?.closest("th")?.setAttribute("aria-sort", direction === "asc" ? "ascending" : "descending");
  }

  function initPaged() {
    const pages = new Map();
    const menus = [...filters.map(([field, select]) => [field, select]), ...(dataType ? [["dataset", dataType]] : [])];
    const labels = new Map(menus.map(([, select]) => [select, new Map(Array.from(select.options).map(option => [option.value, option.textContent]))]));
    let sequence = 0, controller, searchTimer, localCatalogue, localLoadedAt = 0, useLocal = true;

    // The complete experimental collection fits on one D1 page. Reuse that
    // response for interactive filters; never substitute a bundled snapshot.
    function filterExperimental(data, url) {
      const ranks = taxonomy.map(s => s.dataset.taxonomyRank);
      const fields = ["source", "genome_type", "annotation", "dataset", ...ranks];
      const selected = Object.fromEntries(fields.map(k => [k, url.searchParams.get(k) || ""]));
      const q = (url.searchParams.get("q") || "").normalize("NFKC").toLowerCase().trim();
      const tokens = q.split(/[^\p{L}\p{N}_.-]+/u).filter(Boolean);
      const datasets = {experimental:"endpoints", prediction:"predictions", augmentation:"training"};
      const matches = (row, omitted = []) => {
        const r = row.filterData;
        if (!tokens.every(t => r.search_text.includes(t))) return false;
        return fields.every(k => omitted.includes(k) || !selected[k] || (k === "dataset" ? r[datasets[selected[k]]] > 0 : r[k] === selected[k]));
      };
      const facets = {};
      for (const field of fields) {
        const rank = ranks.indexOf(field);
        if (rank > 0 && ranks.slice(0, rank).some(k => !selected[k])) continue;
        const scope = data.rows.filter(r => matches(r, [field, ...(rank >= 0 ? ranks.slice(rank + 1) : [])]));
        if (field === "dataset") {
          facets[field] = Object.keys(datasets).filter(k => scope.some(r => r.filterData[datasets[k]] > 0));
          if (!tokens.length && fields.every(k => k === field || !selected[k])) facets[field].sort();
        }
        else {
          facets[field] = [...new Set(scope.map(r => r.filterData[field]).filter(Boolean))].sort();
          if (field === "phylum") {
            const counts = new Map();scope.forEach(r => counts.set(r.filterData.phylum, (counts.get(r.filterData.phylum) || 0) + 1));
            facets[field].sort((a,b) => counts.get(b) - counts.get(a) || (a < b ? -1 : a > b ? 1 : 0));
          }
        }
      }
      const key = {accession:"accession_key",organism:"organism_key"}[sortField] || sortField;
      const rows = data.rows.filter(r => matches(r)).sort((a,b) => {
        const x=a.filterData[key], y=b.filterData[key];
        if (key === "size" && (x == null) !== (y == null)) return Number(x == null)-Number(y == null);
        const order=x < y ? -1 : x > y ? 1 : 0;
        return (direction === "desc" ? -order : order) || (a.filterData.accession_key < b.filterData.accession_key ? -1 : 1);
      });
      return {...data, rows, total:rows.length, page:1, facets};
    }

    function restoreMenu(select, value) {
      if (value && !labels.get(select).has(value)) labels.get(select).set(value, value);
      if (value && !Array.from(select.options).some(option => option.value === value)) {
        const option = document.createElement("option"); option.value = value; option.textContent = labels.get(select).get(value); select.append(option);
      }
      select.value = value;
    }

    function menuOptions(select, values, allLabel) {
      const selected = select.value, names = labels.get(select);
      const all = document.createElement("option"); all.value = ""; all.textContent = allLabel;
      select.replaceChildren(all);
      // Keep an explicit selection when a search has no matches, so its scope and URL stay intact.
      const available = values;
      for (const value of new Set([...available, ...(selected ? [selected] : [])])) {
        const option = document.createElement("option"); option.value = value; option.textContent = names?.get(value) || value; select.append(option);
      }
      select.value = selected;
    }

    function readPagedUrl() {
      const params = new URLSearchParams(window.location.search);
      search.value = params.get("q") || params.get("search") || params.get("query") || params.get("accession") || params.get("assembly") || "";
      const [legacyRank, ...legacyName] = (params.get("taxon") || "").split(":");
      for (const select of taxonomy) {
        const rank = select.dataset.taxonomyRank, value = params.get(rank) || (legacyRank === rank ? legacyName.join(":") : "");
        if (value && !Array.from(select.options).some(option => option.value === value)) {
          const option = document.createElement("option"); option.value = value; option.textContent = value; select.append(option);
        }
        select.value = value;
      }
      if (dataType) restoreMenu(dataType, params.get("dataset") || "");
      filters.forEach(([param, select]) => {
        let value = params.get(param) || "";
        if (param === "annotation" && ["Incompatible", "Unavailable", "Not cataloged"].includes(value)) value = "Missing";
        restoreMenu(select, value);
      });
      sortField = sortFields.has(params.get("sort")) ? params.get("sort") : defaultSort;
      const order = params.get("direction") || params.get("order");
      direction = ["asc", "desc"].includes(order) ? order : params.has("sort") ? "asc" : "desc";
      page = Math.max(0, Math.min(1999, (Number(params.get("page")) || 1) - 1));
    }

    function showPage(data) {
      page = data.page - 1;
      tbody.replaceChildren(...data.rows.map(genomeRow));
      tbody.hidden = false;
      if (resultCount) resultCount.hidden = false;
      count.textContent = data.total.toLocaleString("en-US");
      const start = data.total ? page * pageSize + 1 : 0;
      resultRange.textContent = `Showing ${start.toLocaleString("en-US")}–${Math.min((page + 1) * pageSize, data.total).toLocaleString("en-US")}`;
      pageNumber.textContent = data.total ? `${page + 1} / ${Math.ceil(data.total / pageSize)}` : "";
      previous.disabled = page === 0;
      next.disabled = (page + 1) * pageSize >= data.total;
      empty.hidden = data.total !== 0;
      for (const [field, select] of menus) {
        if (Array.isArray(data.facets[field])) menuOptions(select, data.facets[field], labels.get(select).get(""));
      }
      for (const select of taxonomy) {
        const values = data.facets[select.dataset.taxonomyRank];
        menuOptions(select, values || [], "All");
        select.disabled = !values && !select.value;
      }
      updateSortHeaders();


      loadStatus.textContent = ""; retry.hidden = true;
    }

    async function loadPage() {
      const ticket = ++sequence;
      controller?.abort(); controller = new AbortController();
      const query = search.value.trim().normalize("NFKC");
      const tokens = query.split(/[^\p{L}\p{N}_.-]+/u).filter(Boolean);
      if (tokens.length && !tokens.some(token => [...token].length >= 3)) {
        loadStatus.textContent = "Enter at least 3 characters.";
        tbody.hidden = true; resultCount.hidden = true; previous.disabled = true; next.disabled = true;
        form.inert = false; return;
      }
      const url = new URL(form.dataset.genomePages, window.location.href);
      url.searchParams.set("page", String(page + 1)); url.searchParams.set("sort", sortField); url.searchParams.set("direction", direction);
      if (query) url.searchParams.set("q", query);
      if (dataType?.value) url.searchParams.set("dataset", dataType.value);
      filters.forEach(([param, select]) => { if (select.value) url.searchParams.set(param, select.value); });
      taxonomy.forEach(select => { if (select.value) url.searchParams.set(select.dataset.taxonomyRank, select.value); });
      const key = url.href;
      previous.disabled = true; next.disabled = true;
      loadStatus.textContent = "Loading genomes…"; retry.hidden = true;
      try {
        if (form.dataset.genomePrefix === "experimental" && useLocal) {
          if (!localCatalogue || Date.now() - localLoadedAt >= 60000) {
            const all = new URL(form.dataset.genomePages, window.location.href);
            const response = await fetch(all, {signal:controller.signal});
            if (!response.ok) throw new Error(response.status === 409 ? "version" : "unavailable");
            const data = await response.json();
            if (!Array.isArray(data.rows) || !Number.isInteger(data.total)) throw new Error("unavailable");
            useLocal = data.total === data.rows.length && data.total <= pageSize;
            if (useLocal) {
              if (data.rows.some(r => !r.filterData)) throw new Error("unavailable");
              localCatalogue=data; localLoadedAt=Date.now();
            }
          }
          if (ticket !== sequence) return;
          if (useLocal) { showPage(filterExperimental(localCatalogue, url)); return; }
        }
        let data = pages.get(key);
        if (!data) {
          const response = await fetch(key, { signal: controller.signal });
          if (!response.ok) throw new Error(response.status === 409 ? "version" : "unavailable");
          data = await response.json();
          if (!Array.isArray(data.rows) || data.rows.length > pageSize || !Number.isInteger(data.total) || !Number.isInteger(data.page)) throw new Error("unavailable");
          pages.set(key, data);
          while (pages.size > 12) pages.delete(pages.keys().next().value);
        }
        if (ticket !== sequence) return;
        showPage(data);
      } catch (error) {
        if (ticket !== sequence || error.name === "AbortError") return;
        loadStatus.textContent = error.message === "version" ? "Catalog updated. Reload this page." : "Catalog unavailable.";
        retry.hidden = false;
        // Never label the previous page as the newly requested result.
        tbody.hidden = true; resultCount.hidden = true;
      } finally { if (ticket === sequence) form.inert = false; }
    }

    function changePage(reset = true, debounce = false) {
      clearTimeout(searchTimer); sequence++; controller?.abort();
      if (reset) page = 0;
      updateUrl();
      if (debounce && !localCatalogue) searchTimer = setTimeout(loadPage, 300); else loadPage();
    }
    search.addEventListener("input", () => changePage(true, true));
    form.addEventListener("submit", event => { event.preventDefault(); changePage(); });
    taxonomy.forEach((select, index) => select.addEventListener("change", () => { taxonomy.slice(index + 1).forEach(child => { child.value = ""; }); changePage(); }));
    dataType?.addEventListener("change", () => changePage());
    filters.forEach(([, select]) => select.addEventListener("change", () => changePage()));
    previous?.addEventListener("click", () => { page--; changePage(false); });
    next?.addEventListener("click", () => { page++; changePage(false); });
    sortButtons.forEach(button => button.addEventListener("click", () => {
      const nextSort = button.dataset.sort;
      if (!sortFields.has(nextSort)) return;
      direction = sortField === nextSort ? direction === "asc" ? "desc" : "asc" : "asc";
      sortField = nextSort; changePage();
    }));
    clear?.addEventListener("click", () => {
      search.value = ""; taxonomy.forEach(select => { select.value = ""; });
      if (dataType) dataType.value = "";
      filters.forEach(([, select]) => { select.value = ""; });
      sortField = defaultSort; direction = "desc"; changePage();
    });
    retry.addEventListener("click", () => changePage(false));
    window.addEventListener("popstate", () => { clearTimeout(searchTimer); readPagedUrl(); loadPage(); });
    readPagedUrl(); loadPage();
  }

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
    filters.forEach(([param, select]) => {
      let value = params.get(param) || "";
      if (param === "annotation" && ["Incompatible", "Unavailable", "Not cataloged"].includes(value)) value = "Missing";
      select.value = validOption(select, value);
    });
    const explicitSort = sortFields.has(params.get("sort"));
    sortField = explicitSort ? params.get("sort") : defaultSort;
    const order = params.get("direction") || params.get("order");
    direction = ["asc", "desc"].includes(order) ? order : explicitSort ? "asc" : "desc";

  }

  function updateUrl() {
    const url = new URL(window.location.href);
    ["q", "search", "query", "accession", "assembly", "taxon", "rank", "phylum", "class", "order", "family", "genus", "species", "study", "assay", "evidence", "signal", "sort", "dataset", "direction", "page", "source", ...filters.map(([param]) => param)]
      .forEach((key) => url.searchParams.delete(key));
    if (search.value.trim()) url.searchParams.set("q", search.value.trim());
    taxonomy.forEach(select => { if (select.value) url.searchParams.set(select.dataset.taxonomyRank, select.value); });
    if (dataType?.value) url.searchParams.set("dataset", dataType.value);
    filters.forEach(([param, select]) => { if (select.value) url.searchParams.set(param, select.value); });
    if (sortField !== defaultSort || direction !== "desc") {
      url.searchParams.set("sort", sortField);
      url.searchParams.set("direction", direction);
    }
    if (form.dataset.genomePages && page > 0) url.searchParams.set("page", String(page + 1));
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

  function sourceMatches(row, tokens) {
    if (filters.some(([, select, key]) => select.value && row.dataset[key] !== select.value)) return false;
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
    if (!tokens.length) return true;
    row.searchText ??= `${row.dataset.genomeSearch} ${(row.sources || Array.from(row.querySelectorAll("[data-source-filter]"))).map(source => source.dataset.search).join(" ")}`.normalize("NFKC").toLocaleLowerCase();
    return tokens.every(token => row.searchText.includes(token));
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
    const tokens = search.value.trim().normalize("NFKC").toLocaleLowerCase().split(/[^\p{L}\p{N}_.-]+/u).filter(Boolean);
    const matched = [];
    const order = `${sortField}:${direction}`;
    if (sortedBy !== order) { rows.sort(compareRows); sortedBy = order; }
    rows.forEach((row) => {
      row.hidden = !sourceMatches(row, tokens);
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
    updateSortHeaders();
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
  clear?.addEventListener("click", () => {
    search.value = "";
    taxonomy.forEach(select => { select.value = ""; });
    updateTaxa();
    if (dataType) dataType.value = "";
    filters.forEach(([, select]) => { select.value = ""; });
    sortField = "endpoints";
    direction = "desc";
    changed();
  });
  window.addEventListener("popstate", () => { page = 0; readUrl(); render(); });
  updateSourceOptions();
  readUrl();
  render();

  function genomeRow(row) {
    const record = row.batter;
    const tr = document.createElement("tr");
    const href = `${form.dataset.genomePrefix || "genomes"}/${encodeURIComponent(record[0])}`;
    for (const label of ["Genome ID", "Genome source", "Organism", "Taxonomy", "Assembly size", "Transcript 3′-end data", "Annotation"]) {
      const td = document.createElement("td"); td.dataset.label = label;
      if (label === "Genome ID") {
        const link = document.createElement("a"), code = document.createElement("code");
        link.className = "genome-table-name"; link.href = href; code.textContent = record[0]; link.append(code); td.append(link);
        showOtu(td, record[2]);
      } else if (label === "Genome source") {
        td.textContent = referenceSource(record[12]);
      } else if (label === "Organism") {
        const name = document.createElement("span"); name.className = "genome-organism"; name.textContent = record[3]; td.append(name);
        const type = document.createElement("small"); type.textContent = ({ MAG: "Metagenome-assembled", SAG: "Single-cell amplified", isolate: "Isolate", environmental: "Environmental", unknown: "Type not recorded" })[record[4]] || record[4]; td.append(type);
      } else if (label === "Taxonomy") {
        const phylum = document.createElement("span"), genus = document.createElement("small");
        phylum.textContent = row.dataset.taxonomyPhylum || (row.dataset.taxonomyStatus === "pending" ? "Pending verification" : "Unclassified"); genus.textContent = row.dataset.taxonomyGenus || (row.dataset.taxonomyStatus === "pending" ? "Assembly version unresolved" : "Genus not assigned"); td.append(phylum, genus);
      } else if (label === "Assembly size") {
        td.dataset.referenceSize = ""; referenceSize(td, row);
      } else if (label === "Transcript 3′-end data") {
        const counts = document.createElement("div"); counts.className = "genome-data-counts";
        for (const [type, field, text, title] of [["experimental", "endpoints", "experimental 3′-end records", "Study-reported 3′ ends"], ["prediction", "predictions", "predicted regions", "BATTER predictions"], ["training", "training", "augmentation / Rfam regions", "OTU and Rfam regions; excludes context windows"]]) {
          if (!Number(row.dataset[`sort${field[0].toUpperCase()}${field.slice(1)}`])) continue;
          const badge = document.createElement("span"), number = document.createElement("b");
          badge.className = `genome-evidence ${type}${Number(row.dataset[`sort${field[0].toUpperCase()}${field.slice(1)}`]) ? "" : " unavailable"}`;
          badge.title = title; number.textContent = Number(row.dataset[`sort${field[0].toUpperCase()}${field.slice(1)}`] || 0).toLocaleString("en-US"); badge.append(number, ` ${text}`); counts.append(badge);
        }
        if (!counts.children.length) counts.textContent = form.dataset.genomePrefix === "experimental" ? "No published 3′-end records" : "—";
        td.append(counts);
      } else {
        td.append(annotationBadge(record[9], row.recoveredAnnotation));
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
    label.title = "Species-level cluster";
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
    cell.title = "Browser reference length";
    const bases = document.createElement("span");
    bases.textContent = row.referenceSize ? `${row.referenceSize[0].toLocaleString("en-US")} bp` : "Not cataloged";
    cell.append(bases);
    if (row.referenceSize) { const contigs = document.createElement("small"); contigs.textContent = `${row.referenceSize[1].toLocaleString("en-US")} ${row.referenceSize[1] === 1 ? "contig" : "contigs"}`; cell.append(contigs); }
    else bases.className = "muted";
  }

  function annotationLabel(status, recovered) {
    return status === "matched" || recovered ? "Available" : "Missing";
  }

  function annotationBadge(status, recovered) {
    const badge = document.createElement("span");
    badge.className = `genome-annotation${status === "matched" || recovered ? "" : " unavailable"}`;
    badge.textContent = annotationLabel(status, recovered);
    badge.title = ({ matched: "Reference annotation", mismatch: "Reference mismatch", contig_mismatch: "Reference mismatch", unavailable: "Annotation unavailable", download_failed: "Download failed", invalid_gff: "Invalid annotation coordinates", no_ncbi_accession: "No registered annotation source" })[status] || "Annotation missing";
    if (recovered) badge.title = `Annotation: ${recovered.matched_reference_contigs}/${recovered.total_reference_contigs} contigs${recovered.coverage === "partial" ? " (partial)" : ""}`;
    return badge;
  }

  async function loadGenomes() {
    catalogueReady = false;
    form.inert = true;
    retry.hidden = true;
    loadStatus.textContent = "Loading genomes…";
    try {
      const response = await fetch(form.dataset.genomeCatalogue || "api/batter-catalogue");
      if (!response.ok) throw new Error();
      const catalogue = await response.json();
      const records = catalogue.genomes;
      const indexed = new Map(rows.map(row => [row.dataset.sortAccession.toUpperCase(), row]));
      for (const record of records) {
        let row = indexed.get(record[0].toUpperCase());
        if (!row) {
          row = { dataset: { genomeSearch: "", sortAccession: record[0].toLowerCase(), sortOrganism: record[3].toLowerCase(), sortEndpoints: "0" }, sources: [] };
          const ranks = { p: "Phylum", c: "Class", o: "Order", f: "Family", g: "Genus", s: "Species" };
          for (const taxon of (record[11] || "").split(";")) {
            const rank = ranks[taxon[0]], value = taxon.slice(3);
            if (rank && value) row.dataset[`taxonomy${rank}`] = value;
          }
          rows.push(row); indexed.set(record[0].toUpperCase(), row);
        }
        row.batter = record;
        row.recoveredAnnotation = catalogue.annotation_recovery && catalogue.annotation_recovery.reference_revision === catalogue.revision
          ? catalogue.annotation_recovery.genomes?.[record[0]] : null;
        row.dataset.genomeSource = referenceSource(record[12]);
        row.dataset.genomeType = record[4] || "unknown";
        row.dataset.genomeAnnotation = annotationLabel(record[9], row.recoveredAnnotation);
        row.dataset.genomeSearch += ` ${record[0]} ${record[2]} ${record[3]} ${record[11] || ""} ${referenceSource(record[12])}`.toLowerCase();
        row.sources ||= Array.from(row.querySelectorAll("[data-source-filter]"));
        row.dataset.sortPredictions = String(record[10]);
        row.dataset.sortTraining = String(record[5] + record[7]);
        row.referenceSize = catalogue.reference_sizes?.[record[0]];
        row.dataset.sortSize = row.referenceSize ? String(row.referenceSize[0]) : "";
        if (record[10] > 0) row.dataset.genomeSearch += " batter predictions 42402588";
        if (record[5] + record[7] > 0) row.dataset.genomeSearch += " batter augmentation training 42402588";
        delete row.searchText;
        if (row.node) {
          row.node.querySelector('[data-label="Genome source"]').textContent = referenceSource(record[12]);
          showOtu(row.node.querySelector('[data-label="Genome ID"]'), record[2]);
          for (const [selector, value] of [["[data-prediction-count]", record[10]], ["[data-augmentation-count]", record[5] + record[7]]]) {
            const number = row.node.querySelector(selector); number.textContent = value.toLocaleString("en-US"); number.parentElement.hidden = !value; number.parentElement.classList.toggle("unavailable", !value);
          }
          referenceSize(row.node.querySelector("[data-reference-size]"), row);
          row.node.querySelector('[data-label="Annotation"]').replaceChildren(annotationBadge(record[9], row.recoveredAnnotation));
        }
      }
      loadStatus.textContent = "";
    } catch {
      loadStatus.textContent = "Catalog unavailable. Experimental genomes shown."; retry.hidden = false;
    } finally {
      catalogueReady = true;
      sortedBy = "";
      updateSourceOptions();
      readUrl(); render();
      tbody.hidden = false;
      if (resultCount) resultCount.hidden = false;
      form.inert = false;
    }
  }
  if (dataType) { retry.addEventListener("click", loadGenomes); loadGenomes(); }
})();
