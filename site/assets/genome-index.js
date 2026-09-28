(function () {
  "use strict";

  const form = document.querySelector("[data-genome-search-form]");
  const search = document.querySelector("[data-genome-search]");
  const tbody = document.querySelector("[data-genome-results]");
  const count = document.querySelector("[data-visible-count]");
  const empty = document.querySelector("[data-empty]");
  const clear = document.querySelector("[data-clear-filters]");
  const filters = {
    study: document.querySelector("[data-filter-study]"),
    assay: document.querySelector("[data-filter-assay]"),
    evidence: document.querySelector("[data-filter-evidence]"),
    signal: document.querySelector("[data-filter-signal]"),
  };
  if (!form || !search || !tbody) return;

  const rows = Array.from(tbody.querySelectorAll("[data-genome-row]"));
  const sortButtons = Array.from(document.querySelectorAll("[data-sort]"));
  const mobileSort = document.querySelector("[data-sort-select]");
  const mobileDirection = document.querySelector("[data-sort-direction]");
  const sortFields = new Set(["accession", "organism", "studies", "endpoints", "signal"]);
  const numericFields = new Set(["studies", "endpoints", "signal"]);
  const collator = new Intl.Collator("en", { numeric: true, sensitivity: "base" });
  let sortField = "accession";
  let direction = "asc";

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
    sortField = sortFields.has(params.get("sort")) ? params.get("sort") : "accession";
    direction = params.get("order") === "desc" ? "desc" : "asc";
    if (mobileSort) mobileSort.value = sortField;
  }

  function updateUrl() {
    const url = new URL(window.location.href);
    ["q", "search", "query", "accession", "assembly", "study", "assay", "evidence", "signal", "sort", "order"]
      .forEach((key) => url.searchParams.delete(key));
    if (search.value.trim()) url.searchParams.set("q", search.value.trim());
    Object.entries(filters).forEach(([key, select]) => {
      if (select && select.value) url.searchParams.set(key, select.value);
    });
    if (sortField !== "accession") url.searchParams.set("sort", sortField);
    if (direction !== "asc") url.searchParams.set("order", direction);
    window.history.replaceState({}, "", url);
  }

  function sourceMatches(row, query) {
    const genomeMatch = row.dataset.genomeSearch.includes(query);
    return Array.from(row.querySelectorAll("[data-source-filter]")).some((source) => {
      if (query && !genomeMatch && !source.dataset.search.includes(query)) return false;
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
    rows.sort(compareRows).forEach((row) => {
      row.hidden = !sourceMatches(row, query);
      if (!row.hidden) visible += 1;
      tbody.append(row);
    });
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
    updateUrl();
    render();
  }

  search.addEventListener("input", changed);
  form.addEventListener("submit", (event) => { event.preventDefault(); changed(); });
  Object.values(filters).forEach((select) => select?.addEventListener("change", changed));
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
    Object.values(filters).forEach((select) => { if (select) select.value = ""; });
    sortField = "accession";
    direction = "asc";
    changed();
  });
  window.addEventListener("popstate", () => { readUrl(); render(); });
  readUrl();
  render();
})();
