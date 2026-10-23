// Preserve directory bookmarks from before the separate home page existed.
const homeQuery = new URLSearchParams(location.search);
if (location.hash === "#genome-directory" || ["q", "search", "query", "accession", "assembly", "taxon", "study", "assay", "evidence", "signal", "sort", "order"].some((key) => homeQuery.has(key))) {
  location.replace(`genomes.html${location.search}${location.hash}`);
}

// The deployed site's statistics come from D1, not build-time release tables.
if (document.querySelector("[data-live-summary]")) {
  const numbers = document.querySelectorAll(".home-summary strong");
  const chart = document.querySelector("[data-live-phyla]");
  const format = value => Number(value).toLocaleString("en-US");
  async function loadSummary() {
    try {
      const response = await fetch("api/site-summary");
      if (!response.ok) throw new Error("unavailable");
      const data = await response.json();
      if (data.metadata_source !== "d1") throw new Error("unexpected metadata");
      [data.total, data.predictions, data.training, data.experimental, data.records, data.publications].forEach((value, index) => { numbers[index].textContent = format(value); });
      const phyla = Object.entries(data.phyla).filter(([name]) => name).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
      const top = phyla.slice(0, 8), other = phyla.slice(8).reduce((sum, [, count]) => sum + count, 0);
      if (other) top.push(["Other phyla", other]);
      const largest = Math.max(1, ...top.map(([, count]) => count));
      const heading = document.createElement("div"), title = document.createElement("h2"), note = document.createElement("p"), bars = document.createElement("div");
      title.textContent = "Genomes by phylum"; note.textContent = `${format(phyla.reduce((sum, [, count]) => sum + count, 0))} genomes with recorded phylum.`;
      heading.append(title, note); bars.className = "home-phyla-chart";
      for (const [name, count] of top) {
        const row = document.createElement("div"), label = document.createElement("span"), bar = document.createElement("div"), fill = document.createElement("i"), number = document.createElement("strong");
        row.className = "home-phylum-row"; bar.className = "home-phylum-bar"; bar.setAttribute("aria-hidden", "true"); fill.style.width = `${count / largest * 100}%`;
        if (name === "Other phyla") label.textContent = name;
        else { const a = document.createElement("a"); a.textContent = name; a.href = `genomes.html?phylum=${encodeURIComponent(name)}`; label.append(a); }
        number.textContent = format(count); bar.append(fill); row.append(label, bar, number); bars.append(row);
      }
      chart.replaceChildren(heading, bars);
    } catch {
      numbers.forEach(node => { node.textContent = "Unavailable"; });
      const message = document.createElement("p"), retry = document.createElement("button");
      message.textContent = "Release statistics unavailable."; retry.textContent = "Retry"; retry.addEventListener("click", loadSummary);
      chart.replaceChildren(message, retry);
    }
  }
  loadSummary();
}
