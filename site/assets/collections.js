(function () {
  "use strict";
  const format = n => Number(n).toLocaleString("en-US");
  const retry = document.querySelector("[data-collections-retry]");
  const status = document.querySelector("[data-collections-status]");
  async function load() {
    if (retry) retry.hidden = true;
    try {
      const response = await fetch("api/collections");
      if (!response.ok) throw new Error("unavailable");
      const data = await response.json();
      if (data.metadata_source !== "d1") throw new Error("unexpected source");
      for (const row of data.collections) {
        const card = document.querySelector(`[data-collection-card="${row.collection}"]`);
        const progress = row.partial ? `${format(row.total)} of ${format(row.source_genome_count)} input genomes published · Partial release`
          : `${format(row.total)} genomes · ${row.collection === "experimental" ? format(row.feature_totals.endpoints) + " experimental 3′-end records · " + format(row.feature_totals.predictions) + " predicted regions" : format(row.feature_totals.predictions) + " predicted regions"}`;
        if (card) {
          card.querySelector("[data-collection-taxonomy]").textContent = `Classification · ${row.taxonomy_label}`;
          card.querySelector("[data-collection-count]").textContent = format(row.total);
          card.querySelector("[data-collection-progress]").textContent = row.partial ? progress : "";
        }
        const summary = document.querySelector(`[data-live-collection="${row.collection}"]`);
        const taxonomy = document.querySelector(`[data-live-taxonomy="${row.collection}"]`);
        if (taxonomy) taxonomy.textContent = `Classification · ${row.taxonomy_label}`;
        if (summary) summary.textContent = progress;
      }
      if (status) status.textContent = "";
    } catch {
      if (status) status.textContent = "Collection summary unavailable.";
      document.querySelectorAll("[data-live-collection]").forEach(node => { node.textContent = "Release summary unavailable. Reload to retry."; });
      document.querySelectorAll("[data-collection-count]").forEach(node => { node.textContent = "Unavailable"; });
      if (retry) retry.hidden = false;
    }
  }
  retry?.addEventListener("click", load);
  load();
})();
