(function () {
  "use strict";
  const $ = selector => document.querySelector(selector);
  const format = value => Number(value || 0).toLocaleString("en-US");
  function link(text, href) {
    const node = document.createElement("a");
    node.textContent = text; node.href = href;
    return node;
  }

  const root = $("[data-batter-genome]");
  if (!root) return;
  const id = new URLSearchParams(location.search).get("genome") || root.dataset.assembly || decodeURIComponent(location.pathname.split("/").at(-1)).replace(/\.html$/, "");
  const status = $("[data-browser-status]");
  const reload = $("[data-retry-browser]");
  async function loadGenome() {
    status.textContent = "Loading genome data…"; reload.disabled = true;
    try {
      if (!id || !/^[A-Za-z0-9_.-]{1,128}$/.test(id)) throw new Error("Genome ID required.");
      const api = new URL(`../api/batter/${encodeURIComponent(id)}`, document.baseURI);
      const requestedRevision = new URLSearchParams(location.search).get("revision");
      if (requestedRevision) api.searchParams.set("revision", requestedRevision);
      const response = await fetch(api);
      if (response.status === 409) throw new Error("Data version changed. Reopen the genome from the catalog.");
      if (!response.ok) throw new Error(response.status === 404 ? "Genome not found." : "Genome files unavailable.");
      const data = await response.json();
      const pageUrl = new URL(location.href); pageUrl.searchParams.set("revision", data.revision); history.replaceState(null, "", pageUrl);
      const name = data.taxonomy.split(";").find(taxon => taxon.startsWith("s__"))?.slice(3) || id;
      document.title = `${name} · BTED`;
      if ($("[data-batter-title]")) $("[data-batter-title]").textContent = name;
      if ($("[data-batter-id]")) $("[data-batter-id]").textContent = name === id ? "" : id;
      if ($("[data-batter-reference]")) $("[data-batter-reference]").textContent = `Sequence source: ${data.reference.source}. ${format(data.reference.contigs)} contigs · ${format(data.reference.bases)} bp.`;
      const provenance = $("[data-batter-provenance]");
      if (provenance) {
        const heading = document.createElement("h2"), facts = document.createElement("dl");
        heading.textContent = "Reference details";
        const source = ({ "NCBI-RefSeq": "NCBI RefSeq", "NCBI-MAG": "NCBI GenBank", "NCBI-SAG": "NCBI GenBank" })[data.source_collection] || data.source_collection || "Not cataloged";
        for (const [label, value] of [["Genome ID", id], ["GEM OTU", data.otu_id], ["Genome source", source], ["Sequence source", data.reference.source], ["Genome type", data.genome_type], ["Reference length", `${format(data.reference.bases)} bp`], ["Contigs", format(data.reference.contigs)]]) {
          if (!value) continue;
          const item = document.createElement("div"), term = document.createElement("dt"), description = document.createElement("dd");
          term.textContent = label; description.textContent = value; item.append(term, description); facts.append(item);
        }
        provenance.replaceChildren(heading, facts);
        provenance.hidden = false;
      }
      const taxonomy = $("[data-batter-taxonomy]");
      if (taxonomy) {
        const header = document.createElement("div"), heading = document.createElement("h2"), source = document.createElement("span"), lineage = document.createElement("dl");
        header.className = "taxonomy-heading"; heading.textContent = "Taxonomy";
        source.append(link("GEM / GTDB", "https://portal.nersc.gov/GEM/otus/otu_taxonomy.tsv"));
        header.append(heading, source); lineage.className = "taxonomy-lineage";
        const ranks = Object.fromEntries((data.taxonomy || "").split(";").map(value => value.trim()).map(value => [value.slice(0, 1), value.slice(3)]));
        for (const [key, label] of [["p", "Phylum"], ["c", "Class"], ["o", "Order"], ["f", "Family"], ["g", "Genus"], ["s", "Species"]]) {
          const item = document.createElement("div"), term = document.createElement("dt"), value = document.createElement("dd");
          term.textContent = label; value.textContent = ranks[key] || "Not assigned"; item.append(term, value); lineage.append(item);
        }
        taxonomy.replaceChildren(header, lineage); taxonomy.hidden = false;
      }
      const counts = data.feature_counts || {};
      if (counts.otu_augmentation_span || counts.rfam_training_span || counts.tes_prediction) {
        const legend = document.createElement("div");
        legend.className = "browser-track-legend";
        legend.setAttribute("aria-label", "Track symbols");
        legend.title = "Bar: region. Hollow flag: 3′ boundary. Solid flag: experimental 3′ end.";
        for (const [kind, label] of [["plus", "+ strand"], ["minus", "− strand"], ["flag", "Hollow: region · Solid: experimental"]]) {
          const item = document.createElement("span"), swatch = document.createElement("i");
          swatch.className = `track-swatch track-swatch-${kind}`;
          swatch.setAttribute("aria-hidden", "true");
          item.append(swatch, label); legend.append(item);
        }
        $(".browser-panel-heading").append(legend);
      }
      const validCount = value => Number.isSafeInteger(value) && value >= 0;
      const hasTrainingCounts = validCount(counts.otu_augmentation_span) && validCount(counts.rfam_training_span);
      const training = hasTrainingCounts ? counts.otu_augmentation_span + counts.rfam_training_span : null;
      for (const [selector, count] of [["[data-prediction-count]", counts.tes_prediction], ["[data-training-count]", training]]) {
        const node = $(selector);
        node.textContent = validCount(count) ? format(count) : "Not cataloged";
        node.className = validCount(count) ? "" : "count-missing";
      }
      $("[data-training-breakdown]").textContent = hasTrainingCounts ? `OTU ${format(counts.otu_augmentation_span)} · Rfam ${format(counts.rfam_training_span)}` : "";
      const downloads = $("[data-batter-downloads]"); downloads.replaceChildren();
      for (const [file, label] of [["prediction.gff3.gz", "Predicted regions (GFF3)"], ["augmentation.gff3.gz", "Augmentation / Rfam regions (GFF3)"], ["reference.fa.gz", "Reference FASTA"], [data.annotation.recovered ? "genes.gff3" : "genes.gff3.gz", "Gene annotation"]]) {
        if (!data.browser_files[file] || (file.startsWith("genes") && data.annotation.status !== "matched")) continue;
        const node = link(label, data.browser_files[file].url); node.className = "button"; downloads.append(node);
      }
      if (data.annotation.coverage === "partial") {
        const note = document.createElement("p"); note.className = "muted";
        note.textContent = `Gene annotation: ${data.annotation.matched_reference_contigs} of ${data.annotation.total_reference_contigs} contigs.`;
        downloads.append(note);
      }
      const metadataLink = link("Genome metadata (JSON)", api.href); metadataLink.className = "button"; downloads.append(metadataLink);
      if (data.annotation.status !== "matched") {
        const note = document.createElement("p"); note.className = "muted";
        note.textContent = "Gene annotation: Missing.";
        downloads.append(note);
      }
      const config = new URL(api); config.pathname += "/config"; config.searchParams.set("revision", data.revision);
      const configResponse = await fetch(config);
      if (!configResponse.ok) throw new Error("Browser files unavailable.");
      const browserConfig = await configResponse.json();
      if (browserConfig.metadata?.combined_reference_status === "separate_views") {
        const note = document.createElement("p"); note.className = "muted";
        note.textContent = "Different references; separate coordinate views.";
        downloads.append(note);
      }
      const frame = $("[data-browser-frame]");
      const trackHeight = browserConfig.defaultSession.views.reduce((height, view) => height + 230 + view.tracks.reduce((sum, track) => sum + (track.type === "ReferenceSequenceTrack" ? 120 : browserConfig.tracks.find(item => item.trackId === track.configuration)?.displays?.[0]?.height || 140), 0), 0);
      $("[data-genome-browser]").style.setProperty("--browser-frame-height", `${Math.min(1500, trackHeight)}px`);
      root.dataset.assembly = id; frame.dataset.config = config.href; frame.title = `${id} genome browser`; frame.hidden = false;
      const full = $("[data-batter-full]") || $(".browser-actions a"); full.href = new URL(`../jbrowse/index.html?config=${encodeURIComponent(config.href)}`, document.baseURI).href; full.hidden = false;
      reload.removeEventListener("click", loadGenome);
      const script = document.createElement("script"); script.src = "../assets/genome-page.js"; document.body.append(script);
    } catch (error) {
      status.textContent = error.message;
      for (const selector of ["[data-prediction-count]", "[data-training-count]"]) {
        const node = $(selector);
        if (node?.textContent === "Loading…") node.textContent = "Unavailable";
      }
    }
    finally { reload.disabled = false; }
  }
  reload.addEventListener("click", loadGenome);
  loadGenome();
})();
