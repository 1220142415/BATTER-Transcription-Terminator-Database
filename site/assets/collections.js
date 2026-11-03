(function () {
  "use strict";
  const format = n => Number(n).toLocaleString("en-US");
  const retry = document.querySelector("[data-collections-retry]");
  const status = document.querySelector("[data-collections-status]");
  const phylumSelect = document.querySelector("[data-phylum-collection]");
  const phylumStatus = document.querySelector("[data-phylum-status]");
  const phylumChart = document.querySelector("[data-phylum-chart]");
  const phylumLink = document.querySelector("[data-phylum-link]");
  let collections = [];
  const renderPhyla = () => {
    if (!phylumSelect || !phylumChart) return;
    const selected = collections.find(item => item.collection === phylumSelect.value) || collections[0];
    if (!selected) return;
    const phyla = Object.entries(selected.phylum_counts || {}).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    const top = phyla.slice(0, 8), other = phyla.slice(8).reduce((sum, [, count]) => sum + count, 0);
    if (other) top.push(["Other phyla", other]);
    const largest = Math.max(1, ...top.map(([, count]) => count));
    phylumChart.replaceChildren();
    for (const [name, count] of top) {
      const item = document.createElement("div"), label = document.createElement("span"), bar = document.createElement("div"), fill = document.createElement("i"), number = document.createElement("strong");
      item.className = "home-phylum-row";
      if (name === "Other phyla") label.textContent = name;
      else { const link = document.createElement("a"); link.href = `${selected.collection}.html?phylum=${encodeURIComponent(name)}`; link.textContent = name; label.append(link); }
      bar.className = "home-phylum-bar"; bar.setAttribute("aria-hidden", "true"); fill.style.width = `${count / largest * 100}%`; bar.append(fill);
      number.textContent = format(count); item.append(label, bar, number); phylumChart.append(item);
    }
    phylumStatus.textContent = `${format(phyla.reduce((sum, [, count]) => sum + count, 0))} genomes with recorded phylum · ${selected.taxonomy_label}.`;
    phylumLink.href = `${selected.collection}.html`;
  };
  phylumSelect?.addEventListener("change", renderPhyla);
  async function load() {
    if (retry) retry.hidden = true;
    try {
      const response = await fetch("api/collections");
      if (!response.ok) throw new Error("unavailable");
      const data = await response.json();
      if (data.metadata_source !== "d1") throw new Error("unexpected source");
      collections = data.collections;
      if (phylumSelect) {
        phylumSelect.replaceChildren(...collections.map(row => { const option = document.createElement("option"); option.value = row.collection; option.textContent = row.label; return option; }));
        phylumSelect.value = collections.some(row => row.collection === "gtdb") ? "gtdb" : collections[0]?.collection || "";
        renderPhyla();
      }
      for (const row of collections) {
        const directory = document.querySelector(`[data-genome-search-form][data-genome-prefix="${row.collection}"]`);
        if (directory) directory.dispatchEvent(new CustomEvent("bted:collection-version", {detail:{version:row.version}}));
        const card = document.querySelector(`[data-collection-card="${row.collection}"]`);
        const progress = row.partial ? `${format(row.total)} of ${format(row.source_genome_count)} input genomes published · Partial release`
          : `${format(row.total)} genomes · ${row.collection === "experimental" ? format(row.feature_totals.endpoints) + " experimental 3′-end records · " + format(row.feature_totals.predictions) + " predicted regions" : format(row.feature_totals.predictions) + " predicted regions"}`;
        if (card) {
          card.querySelector("[data-collection-taxonomy]").textContent = `Taxonomy · ${row.taxonomy_label}`;
          card.querySelector("[data-collection-count]").textContent = format(row.total);
          card.querySelector("[data-collection-progress]").textContent = row.partial ? progress
            : row.collection === "experimental" ? `${format(row.feature_totals.endpoints)} 3′-end records` : "";
        }
        const summary = document.querySelector(`[data-live-collection="${row.collection}"]`);
        const taxonomy = document.querySelector(`[data-live-taxonomy="${row.collection}"]`);
        if (taxonomy) taxonomy.textContent = `Taxonomy · ${row.taxonomy_label}`;
        if (summary) summary.textContent = progress;
      }
      if (status) status.textContent = "";
    } catch {
      if (status) status.textContent = "Collection summary unavailable.";
      if (phylumStatus) phylumStatus.textContent = "Taxonomy counts unavailable. Reload to retry.";
      if (phylumChart) phylumChart.replaceChildren();
      document.querySelectorAll("[data-live-collection]").forEach(node => { node.textContent = "Summary unavailable. Reload to retry."; });
      document.querySelectorAll("[data-collection-count]").forEach(node => { node.textContent = "Unavailable"; });
      if (retry) retry.hidden = false;
    }
  }
  retry?.addEventListener("click", load);
  load();
})();
