(function () {
  "use strict";

  const root = document.querySelector("[data-browser-wrapper]");
  if (!root) return;

  const query = new URLSearchParams(window.location.search);
  const sourceValue = query.get("source_id");
  const frame = root.querySelector("[data-browser-frame]");
  const assemblySelect = root.querySelector("[data-browser-assembly-select]");
  const select = root.querySelector("[data-browser-source]");
  const status = root.querySelector("[data-browser-status]");
  const sourceNote = root.querySelector("[data-browser-source-note]");
  let catalogue = null;
  let assembly = null;
  let selectedSource = sourceValue || "";

  function text(selector, value) {
    const element = root.querySelector(selector);
    if (element) element.textContent = value || "—";
  }

  function showLink(selector, label, href) {
    const element = root.querySelector(selector);
    if (!element) return;
    element.hidden = !href;
    if (href) {
      element.href = href;
      element.textContent = label;
    }
  }

  function accessionParts(value) {
    return String(value || "").split(/[;,\s]+/).map((item) => item.trim()).filter(Boolean);
  }

  function accessionLink(accession, fallback) {
    if (/^GSE\d+$/.test(accession)) return `https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=${encodeURIComponent(accession)}`;
    if (/^SR[APRX]\d+$/.test(accession)) return `https://www.ncbi.nlm.nih.gov/sra/?term=${encodeURIComponent(accession)}`;
    if (/^PRJNA\d+$/.test(accession)) return `https://www.ncbi.nlm.nih.gov/bioproject/${encodeURIComponent(accession)}`;
    if (/^PRJEB\d+$/.test(accession)) return `https://www.ebi.ac.uk/ena/browser/view/${encodeURIComponent(accession)}`;
    if (/^E-MTAB-\d+$/.test(accession)) return `https://www.ebi.ac.uk/biostudies/arrayexpress/studies/${encodeURIComponent(accession)}`;
    return fallback || "";
  }

  function renderRawLinks(track) {
    const container = root.querySelector("[data-browser-raw]");
    container.replaceChildren();
    const tracks = Array.isArray(track) ? track : [track];
    const seen = new Set();
    tracks.flatMap((item) => accessionParts(item.raw_data_accession).map((accession) => ({
      accession,
      fallback: item.raw_data_url,
    }))).filter(({ accession }) => {
      if (seen.has(accession)) return false;
      seen.add(accession);
      return true;
    }).forEach(({ accession, fallback }, index) => {
      const link = document.createElement("a");
      link.target = "_blank";
      link.rel = "noopener";
      link.href = accessionLink(accession, index === 0 ? fallback : "");
      link.textContent = `Raw data · ${accession}`;
      if (link.href && link.href !== window.location.href) container.append(link);
    });
  }

  function renderStudyLinks(tracks) {
    const container = root.querySelector("[data-browser-studies]");
    container.replaceChildren();
    container.hidden = tracks.length < 2;
    if (container.hidden) return;
    tracks.forEach((track) => {
      const item = document.createElement("span");
      item.className = "browser-study-links-item";
      const label = document.createElement("strong");
      label.textContent = track.source_id;
      item.append(label);
      if (track.publication_url) {
        const pubmed = document.createElement("a");
        pubmed.href = track.publication_url;
        pubmed.target = "_blank";
        pubmed.rel = "noopener";
        pubmed.textContent = "PubMed";
        item.append(pubmed);
      }
      if (track.doi_url) {
        const doi = document.createElement("a");
        doi.href = track.doi_url;
        doi.target = "_blank";
        doi.rel = "noopener";
        doi.textContent = "DOI";
        item.append(doi);
      }
      if (track.record_url) {
        const record = document.createElement("a");
        record.href = track.record_url;
        record.textContent = "Dataset details";
        item.append(record);
      }
      container.append(item);
    });
  }

  function configFor(sourceId) {
    const track = sourceId && assembly.tracks.find((item) => item.source_id === sourceId);
    const path = track?.jbrowse_static_config_url || assembly.jbrowse_static_config_url;
    if (!path) throw new Error(`JBrowse config is not available for ${assembly.assembly.accession}`);
    return new URL(path, window.location.href);
  }

  function iframeUrl(config) {
    const params = new URLSearchParams();
    params.set("config", config.href);
    // Keep JBrowse deep-link state separate from the wrapper's accession parameter.
    ["loc", "session", "tracks", "highlight"].forEach((name) => {
      const value = query.get(name);
      if (value) params.set(name, value);
    });
    return `jbrowse/index.html?${params.toString()}`;
  }

  function updatePageUrl(sourceId) {
    const url = new URL(window.location.href);
    url.searchParams.set("assembly", assembly.assembly.accession);
    url.searchParams.delete("config");
    if (sourceId) url.searchParams.set("source_id", sourceId);
    else url.searchParams.delete("source_id");
    window.history.replaceState({}, "", url);
  }

  function renderTrack(track) {
    if (!track) return;
    selectedSource = track.source_id;
    select.value = selectedSource;
    const recordCount = Number(track.record_count || 0).toLocaleString("en-US");
    const statusLabel = track.track_status_label_en || "Endpoint records";
    text("[data-browser-study]", `${track.source_id} · ${track.publication_year} · ${track.assay} · ${recordCount} records · ${statusLabel}`);
    showLink("[data-browser-paper]", "Publication", track.publication_url);
    showLink("[data-browser-pubmed]", `PubMed ${track.pmid || ""}`.trim(), track.publication_url);
    showLink("[data-browser-doi]", track.doi ? `DOI ${track.doi}` : "DOI", track.doi_url);
    showLink("[data-browser-gff3]", "Download GFF3", track.gff3_url);
    showLink("[data-browser-record]", "Dataset details", track.record_url);
    renderStudyLinks([]);
    renderRawLinks(track);
    sourceNote.textContent = assembly.tracks.length > 1
      ? "Select a source to focus its track. Studies on the same assembly remain separate."
      : "This assembly has one source track.";
  }

  function renderAllTracks() {
    selectedSource = "";
    select.value = "";
    const tracks = assembly.tracks.filter((track) => track.track_status !== "metadata_only");
    const totalRecords = tracks.reduce((sum, track) => sum + Number(track.record_count || 0), 0);
    text("[data-browser-study]", `${tracks.length} source tracks · ${totalRecords.toLocaleString("en-US")} endpoint records`);
    showLink("[data-browser-paper]", "Publication", "");
    showLink("[data-browser-pubmed]", "PubMed", "");
    showLink("[data-browser-doi]", "DOI", "");
    showLink("[data-browser-gff3]", "Download GFF3", "");
    showLink("[data-browser-record]", "Dataset details", "");
    renderStudyLinks(tracks);
    const raw = tracks.map((track) => ({
      raw_data_accession: track.raw_data_accession,
      raw_data_url: track.raw_data_url,
    }));
    const container = root.querySelector("[data-browser-raw]");
    container.replaceChildren();
    renderRawLinks(raw);
    sourceNote.textContent = "Studies on the same assembly remain separate source tracks.";
  }

  function loadFrame(sourceId) {
    const config = configFor(sourceId);
    frame.src = iframeUrl(config);
    updatePageUrl(sourceId);
    status.textContent = sourceId ? `Showing ${sourceId} in the browser.` : "Showing all independent source tracks.";
  }

  function renderAssembly() {
    const data = catalogue.assemblies[assembly.accession];
    if (!data) throw new Error(`Assembly ${assembly.accession} is not in the catalogue`);
    assembly = data;
    assemblySelect.value = assembly.assembly.accession;
    assemblySelect.disabled = false;
    text("[data-browser-organism]", `${assembly.assembly.scientific_name}${assembly.assembly.strain ? ` · ${assembly.assembly.strain}` : ""}`);
    text("[data-browser-assembly]", assembly.assembly.accession);
    text("[data-browser-reference]", assembly.assembly.reference_name ? ` · ${assembly.assembly.reference_name}` : "");
    const ncbi = `https://www.ncbi.nlm.nih.gov/datasets/genome/${encodeURIComponent(assembly.assembly.accession)}/`;
    showLink("[data-browser-assembly-link]", assembly.assembly.accession, ncbi);
    showLink("[data-browser-genome]", "Genome details", assembly.assembly_page_url);
    select.replaceChildren();
    const all = document.createElement("option");
    all.value = "";
    all.textContent = "All source tracks";
    select.append(all);
    const available = assembly.tracks.filter((track) => track.track_status !== "metadata_only");
    select.disabled = available.length < 1;
    available.forEach((track) => {
      const option = document.createElement("option");
      option.value = track.source_id;
      const statusLabel = track.track_status_label_en || "Endpoint records";
      option.textContent = `${track.source_id} · ${track.publication_year} · ${Number(track.record_count || 0).toLocaleString("en-US")} records · ${statusLabel}`;
      select.append(option);
    });
    const initial = available.find((track) => track.source_id === selectedSource);
    if (initial) renderTrack(initial);
    else if (available.length > 1) renderAllTracks();
    else if (available[0]) renderTrack(available[0]);
    if (assembly.jbrowse_static_config_url) loadFrame(selectedSource);
    else status.textContent = "JBrowse configuration is not available for this assembly.";
  }

  function populateAssemblyChoices() {
    assemblySelect.replaceChildren();
    const prompt = document.createElement("option");
    prompt.value = "";
    prompt.textContent = "Choose a reference assembly";
    assemblySelect.append(prompt);
    Object.entries(catalogue.assemblies)
      .filter(([, item]) => Boolean(item.jbrowse_static_config_url))
      .sort(([left], [right]) => left.localeCompare(right))
      .forEach(([accession, item]) => {
        const option = document.createElement("option");
        option.value = accession;
        option.textContent = `${accession} · ${item.assembly.scientific_name}`;
        assemblySelect.append(option);
      });
    assemblySelect.disabled = false;
  }

  function updateCoverage() {
    const sources = new Map();
    Object.values(catalogue.assemblies).forEach((entry) => {
      entry.tracks.forEach((track) => sources.set(track.source_id, track));
    });
    const totalRecords = Object.values(catalogue.assemblies).reduce((sum, entry) => sum + Number(entry.record_count || 0), 0);
    const coverage = document.querySelector("[data-browser-coverage]");
    if (coverage) coverage.textContent = `${Object.keys(catalogue.assemblies).length} assemblies · ${sources.size} source datasets · ${totalRecords.toLocaleString("en-US")} endpoint records`;
  }

  async function start() {
    const response = await fetch("data/assemblies.json", { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`Catalogue request failed: ${response.status}`);
    catalogue = await response.json();
    populateAssemblyChoices();
    updateCoverage();

    const accession = query.get("assembly");
    if (!accession) {
      status.textContent = "Choose a reference assembly to see its source tracks.";
      return;
    }
    const item = catalogue.assemblies[accession];
    if (!item) throw new Error(`Assembly ${accession} is not in the catalogue`);
    assembly = { accession };
    renderAssembly();

  }

  assemblySelect.addEventListener("change", () => {
    if (!assemblySelect.value) return;
    const url = new URL("browser.html", window.location.href);
    url.searchParams.set("assembly", assemblySelect.value);
    window.location.assign(url.href);
  });

  select.addEventListener("change", () => {
    const track = assembly.tracks.find((item) => item.source_id === select.value);
    if (track) renderTrack(track);
    else renderAllTracks();
    loadFrame(select.value);
  });

  start().catch((error) => {
    status.textContent = "The browser view could not be prepared. Open the genome details page to check the source.";
    console.error(error);
  });
})();
