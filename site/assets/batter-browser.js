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
      if (!id || !/^[A-Za-z0-9_.-]{1,128}$/.test(id)) throw new Error("Select a genome from the catalog.");
      const api = new URL(`../api/batter/${encodeURIComponent(id)}`, document.baseURI);
      const requestedRevision = new URLSearchParams(location.search).get("revision");
      if (requestedRevision) api.searchParams.set("revision", requestedRevision);
      const response = await fetch(api);
      if (response.status === 409) throw new Error("Data version changed. Reopen the genome from the catalog.");
      if (!response.ok) throw new Error(response.status === 404 ? "Genome not found in the catalog." : "Genome files unavailable. Select Reload to retry.");
      const data = await response.json();
      const pageUrl = new URL(location.href); pageUrl.searchParams.set("revision", data.revision); history.replaceState(null, "", pageUrl);
      const name = data.taxonomy.split(";").find(taxon => taxon.startsWith("s__"))?.slice(3) || id;
      document.title = `${name} · BTED`;
      if ($("[data-batter-title]")) $("[data-batter-title]").textContent = name;
      if ($("[data-batter-id]")) $("[data-batter-id]").textContent = `Genome ID: ${id}${data.otu_id ? ` · GEM OTU: ${data.otu_id}` : ""} · ${data.genome_type}`;
      if ($("[data-batter-reference]")) $("[data-batter-reference]").textContent = `Sequence source: ${data.reference.source}. ${format(data.reference.contigs)} contigs · ${format(data.reference.bases)} bp.`;
      const provenance = $("[data-batter-provenance]");
      if (provenance) {
        const heading = document.createElement("h2"), facts = document.createElement("dl"), note = document.createElement("p");
        heading.textContent = "Reference details";
        const source = ({ "NCBI-RefSeq": "NCBI RefSeq", "NCBI-MAG": "NCBI GenBank", "NCBI-SAG": "NCBI GenBank" })[data.source_collection] || data.source_collection || "Not cataloged";
        for (const [label, value] of [["Genome ID", id], ["GEM OTU", data.otu_id], ["Genome source", source], ["Sequence source", data.reference.source], ["Input FASTA", data.reference.source_path]]) {
          if (!value) continue;
          const item = document.createElement("div"), term = document.createElement("dt"), description = document.createElement("dd");
          term.textContent = label; description.textContent = value; item.append(term, description); facts.append(item);
        }
        note.textContent = "Prediction coordinates use this FASTA, not all members of its GEM OTU. An NCBI accession alone does not confirm sequence identity.";
        provenance.replaceChildren(heading, facts, note);
        if (data.reference.source_sha256) {
          const details = document.createElement("details"), summary = document.createElement("summary"), checksum = document.createElement("code");
          summary.textContent = "Original FASTA SHA-256"; checksum.textContent = data.reference.source_sha256;
          details.append(summary, checksum); provenance.append(details);
        }
        provenance.hidden = false;
      }
      const counts = data.feature_counts;
      const summary = $("[data-batter-summary]"); summary.replaceChildren();
      for (const [key, label] of [["tes_prediction", "predicted regions"], ["otu_augmentation_span", "augmented spans"], ["rfam_training_span", "Rfam spans"], ["otu_augmentation_window", "training windows"]]) {
        const item = document.createElement("div"), number = document.createElement("strong"), text = document.createElement("span");
        number.textContent = format(counts[key]); text.textContent = label; item.append(number, text); summary.append(item);
      }
      const downloads = $("[data-batter-downloads]"); downloads.replaceChildren();
      for (const [file, label] of [["prediction.gff3.gz", "Prediction GFF3"], ["augmentation.gff3.gz", "Training GFF3"], ["reference.fa.gz", "Reference FASTA"], ["genes.gff3.gz", "Gene annotation"]]) {
        if (!data.browser_files[file] || (file.startsWith("genes") && data.annotation.status !== "matched")) continue;
        const node = link(label, data.browser_files[file].url); node.className = "button"; downloads.append(node);
      }
      const metadataLink = link("Metadata", api.href); metadataLink.className = "button"; downloads.append(metadataLink);
      if (data.annotation.status !== "matched" || !counts.otu_augmentation_span && !counts.rfam_training_span) {
        const note = document.createElement("p"); note.className = "muted";
        note.textContent = [data.annotation.status !== "matched" ? "No matching gene annotation." : "", !counts.otu_augmentation_span && !counts.rfam_training_span ? "No augmentation / Rfam regions." : ""].filter(Boolean).join(" ");
        downloads.append(note);
      }
      const config = new URL(api); config.pathname += "/config"; config.searchParams.set("revision", data.revision);
      const configResponse = await fetch(config);
      if (!configResponse.ok) throw new Error("Browser files unavailable. Select Reload to retry.");
      const browserConfig = await configResponse.json();
      if (browserConfig.metadata?.combined_reference_status === "separate_views") {
        const note = document.createElement("p"); note.className = "muted";
        note.textContent = "Experimental and computational references differ and use separate coordinate views.";
        downloads.append(note);
      }
      const frame = $("[data-browser-frame]");
      const trackHeight = browserConfig.defaultSession.views.reduce((height, view) => height + 230 + view.tracks.reduce((sum, track) => sum + (track.type === "ReferenceSequenceTrack" ? 120 : browserConfig.tracks.find(item => item.trackId === track.configuration)?.displays?.[0]?.height || 140), 0), 0);
      $("[data-genome-browser]").style.setProperty("--browser-frame-height", `${Math.min(1500, trackHeight)}px`);
      root.dataset.assembly = id; frame.dataset.config = config.href; frame.title = `${id} genome browser`; frame.hidden = false;
      const full = $("[data-batter-full]") || $(".browser-actions a"); full.href = new URL(`../jbrowse/index.html?config=${encodeURIComponent(config.href)}`, document.baseURI).href; full.hidden = false;
      reload.removeEventListener("click", loadGenome);
      const script = document.createElement("script"); script.src = "../assets/genome-page.js"; document.body.append(script);
    } catch (error) { status.textContent = error.message; }
    finally { reload.disabled = false; }
  }
  reload.addEventListener("click", loadGenome);
  loadGenome();
})();
