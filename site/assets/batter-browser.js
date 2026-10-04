(function () {
  "use strict";
  const $ = selector => document.querySelector(selector);
  const format = value => Number(value || 0).toLocaleString("en-US");
  function link(text, href) {
    const node = document.createElement("a");
    node.textContent = text; node.href = href;
    return node;
  }

  const directory = $("[data-batter-directory]");
  if (directory) {
    const select = $("[data-genome-dataset]");
    const search = $("[data-batter-search]");
    const type = $("[data-batter-type]");
    const records = $("[data-batter-records]");
    const count = $("[data-batter-count]");
    const retry = $("[data-batter-reload]");
    const previous = $("[data-batter-prev]"), next = $("[data-batter-next]");
    let rows, matches = [], page = 0, loading = false;
    const pageSize = 25;
    function render() {
      const body = $("[data-batter-results]");
      body.replaceChildren();
      for (const row of matches.slice(page * pageSize, (page + 1) * pageSize)) {
        const tr = document.createElement("tr");
        const labels = ["Organism", "Genome / OTU", "Type", "Augmented spans", "Rfam spans", "Open"];
        const href = `genomes/batter.html?genome=${encodeURIComponent(row[0])}`;
        const cells = [link(row[3], href), `${row[0]} · ${row[2]}`, row[4], format(row[5]), format(row[7]), link("Open genome", href)];
        cells.forEach((value, i) => {
          const td = document.createElement("td"); td.dataset.label = labels[i];
          if (value instanceof Node) td.append(value); else td.textContent = value;
          tr.append(td);
        });
        body.append(tr);
      }
      count.textContent = `${format(matches.length)} of ${format(rows.length)} uploaded genomes`;
      $("[data-batter-page]").textContent = matches.length ? `${page + 1} / ${Math.ceil(matches.length / pageSize)}` : "No matching genomes";
      previous.disabled = page === 0; next.disabled = (page + 1) * pageSize >= matches.length;
    }
    function filter() {
      if (!rows) return;
      const words = search.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
      matches = rows.filter(row => (!type.value || row[4] === type.value) &&
        (!records.value || (row[5] + row[7] > 0) === (records.value === "yes")) &&
        words.every(word => `${row[0]} ${row[2]} ${row[3]}`.toLowerCase().includes(word)));
      page = 0; render();
    }
    async function load() {
      if (rows || loading) return;
      loading = true; retry.hidden = true; count.textContent = "Loading uploaded genomes…";
      try {
        const response = await fetch("assets/batter-browser.json");
        if (!response.ok) throw new Error();
        rows = (await response.json()).genomes;
        filter();
      } catch {
        count.textContent = "Genome list unavailable. Select Retry."; retry.hidden = false;
      } finally { loading = false; }
    }
    function switchDataset() {
      const augmentation = select.value === "augmentation";
      $("[data-experimental-directory]").hidden = augmentation;
      directory.hidden = !augmentation;
      const url = new URL(location.href);
      if (augmentation) url.searchParams.set("dataset", "augmentation"); else url.searchParams.delete("dataset");
      history.replaceState(null, "", url);
      if (augmentation) load();
    }
    select.value = new URLSearchParams(location.search).get("dataset") === "augmentation" ? "augmentation" : "experimental";
    search.value = new URLSearchParams(location.search).get("search") || "";
    select.addEventListener("change", switchDataset);
    search.addEventListener("input", filter); type.addEventListener("change", filter); records.addEventListener("change", filter);
    $("[data-batter-search-form]").addEventListener("submit", event => { event.preventDefault(); filter(); });
    previous.addEventListener("click", () => { page--; render(); });
    next.addEventListener("click", () => { page++; render(); });
    retry.addEventListener("click", load);
    switchDataset();
  }

  const root = $("[data-batter-genome]");
  if (!root) return;
  const id = new URLSearchParams(location.search).get("genome");
  const status = $("[data-browser-status]");
  const reload = $("[data-retry-browser]");
  async function loadGenome() {
    status.textContent = "Loading genome data…"; reload.disabled = true;
    try {
      if (!id || !/^[A-Za-z0-9_.-]{1,128}$/.test(id)) throw new Error("Choose a genome from the genome directory.");
      const api = new URL(`../api/batter/${encodeURIComponent(id)}`, document.baseURI);
      const requestedRevision = new URLSearchParams(location.search).get("revision");
      if (requestedRevision) api.searchParams.set("revision", requestedRevision);
      const response = await fetch(api);
      if (response.status === 409) throw new Error("This data version has changed. Open the genome again from the directory.");
      if (!response.ok) throw new Error(response.status === 404 ? "This genome is not in the uploaded catalogue." : "Genome files are not available yet. Select Reload to retry.");
      const data = await response.json();
      const pageUrl = new URL(location.href); pageUrl.searchParams.set("revision", data.revision); history.replaceState(null, "", pageUrl);
      const name = data.taxonomy.split(";").find(taxon => taxon.startsWith("s__"))?.slice(3) || id;
      document.title = `${name} · Training augmentation · BTED`;
      $("[data-batter-title]").textContent = name;
      $("[data-batter-id]").textContent = `${id} · ${data.otu_id} · ${data.genome_type}`;
      $("[data-batter-reference]").textContent = `Reference: ${data.reference.source}. ${format(data.reference.contigs)} contigs · ${format(data.reference.bases)} bp.`;
      const counts = data.feature_counts;
      const summary = $("[data-batter-summary]"); summary.replaceChildren();
      for (const [key, label] of [["otu_augmentation_span", "augmented spans"], ["otu_augmentation_window", "augmentation windows"], ["rfam_training_span", "Rfam spans"], ["rfam_training_window", "Rfam windows"]]) {
        const item = document.createElement("div"), number = document.createElement("strong"), text = document.createElement("span");
        number.textContent = format(counts[key]); text.textContent = label; item.append(number, text); summary.append(item);
      }
      const downloads = $("[data-batter-downloads]"); downloads.replaceChildren();
      for (const [file, label] of [["augmentation.gff3.gz", "Training GFF3"], ["reference.fa.gz", "Reference FASTA"], ["genes.gff3.gz", "Gene annotation"]]) {
        if (!data.browser_files[file] || (file.startsWith("genes") && data.annotation.status !== "matched")) continue;
        const node = link(label, data.browser_files[file].url); node.className = "button"; downloads.append(node);
      }
      const metadataLink = link("Metadata", api.href); metadataLink.className = "button"; downloads.append(metadataLink);
      if (data.annotation.status !== "matched" || !counts.otu_augmentation_span && !counts.rfam_training_span) {
        const note = document.createElement("p"); note.className = "muted";
        note.textContent = [data.annotation.status !== "matched" ? "No matching gene annotation." : "", !counts.otu_augmentation_span && !counts.rfam_training_span ? "No augmented spans for this genome." : ""].filter(Boolean).join(" ");
        downloads.append(note);
      }
      const config = new URL(api); config.pathname += "/config"; config.searchParams.set("revision", data.revision);
      const configResponse = await fetch(config);
      if (!configResponse.ok) throw new Error("Browser files are not ready yet. Select Reload to retry.");
      await configResponse.json(); // Confirm the reference and training files are readable before opening JBrowse.
      const frame = $("[data-browser-frame]");
      $("[data-genome-browser]").style.setProperty("--browser-frame-height", `${350 + (data.annotation.status === "matched" ? 130 : 0) + (counts.otu_augmentation_window + counts.rfam_training_window > 0 ? 140 : 0)}px`);
      root.dataset.assembly = id; frame.dataset.config = config.href; frame.title = `${id} training augmentation`; frame.hidden = false;
      const full = $("[data-batter-full]"); full.href = new URL(`../jbrowse/index.html?config=${encodeURIComponent(config.href)}`, document.baseURI).href; full.hidden = false;
      reload.removeEventListener("click", loadGenome);
      const script = document.createElement("script"); script.src = "../assets/genome-page.js"; document.body.append(script);
    } catch (error) { status.textContent = error.message; }
    finally { reload.disabled = false; }
  }
  reload.addEventListener("click", loadGenome);
  loadGenome();
})();
