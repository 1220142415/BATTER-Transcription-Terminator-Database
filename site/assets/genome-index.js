(function () {
  "use strict";

  const form = document.querySelector("[data-genome-search-form]");
  const input = document.querySelector("[data-genome-search]");
  const cards = Array.from(document.querySelectorAll("[data-genome-card]"));
  const count = document.querySelector("[data-visible-count]");
  const empty = document.querySelector("[data-empty]");
  if (!input || !cards.length) return;

  const params = new URLSearchParams(window.location.search);
  const initialQuery = params.get("search") || params.get("query") || params.get("accession") || params.get("assembly") || "";
  if (initialQuery) input.value = initialQuery;

  function applyFilter() {
    const query = input.value.trim().toLocaleLowerCase();
    let visible = 0;
    cards.forEach((card) => {
      const matches = !query || card.dataset.search.includes(query);
      card.hidden = !matches;
      if (matches) visible += 1;
    });
    if (count) count.textContent = String(visible);
    if (empty) empty.hidden = visible > 0;
  }

  input.addEventListener("input", applyFilter);
  if (form) form.addEventListener("submit", (event) => {
    event.preventDefault();
    const query = input.value.trim();
    const url = new URL(window.location.href);
    if (query) url.searchParams.set("search", query);
    else url.searchParams.delete("search");
    ["query", "accession", "assembly"].forEach((key) => url.searchParams.delete(key));
    window.history.replaceState({}, "", url);
    applyFilter();
  });
  applyFilter();
})();
