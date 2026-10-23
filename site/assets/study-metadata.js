(function () {
  "use strict";
  const root = document.querySelector("[data-live-experimental]");
  if (!root) return;
  const assembly = root.dataset.assembly;
  const status = root.querySelector("[data-study-load-status]");
  const retry = root.querySelector("[data-retry-studies]");
  const button = root.querySelector("[data-download-genome-package]");
  const cards = root.querySelector("[data-study-cards]");
  const packageFiles = root.querySelector("[data-study-package-files]");
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const format = value => Number(value).toLocaleString("en-US");
  const link = (label, href) => /^https:\/\//.test(String(href)) ? `<a href="${esc(href)}" target="_blank" rel="noopener">${esc(label)}</a>` : esc(label);
  function accessions(value) {
    return String(value || "").split(/[;,\s]+/).filter(Boolean).map(id => {
      const url = /^G[SME][EMSR]\d+$/.test(id) || /^G(?:SE|SM)\d+$/.test(id) ? `https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=${id}`
        : /^[SED]R[APRSX]\d+$/.test(id) || /^PRJ[A-Z]+\d+$/.test(id) || /^ERS\d+$/.test(id) ? `https://www.ebi.ac.uk/ena/browser/view/${id}`
          : /^E-MTAB-\d+$/.test(id) ? `https://www.ebi.ac.uk/biostudies/arrayexpress/studies/${id}` : null;
      return url ? link(id, url) : esc(id);
    }).join(" · ");
  }
  const facts = pairs => pairs.filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([label, value]) => `<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`).join("");
  const evidence = value => ({ author_called_endpoint: "Author-called 3′ end", called_endpoint: "Called 3′ end", curated_record: "Curated 3′-end record", observed_signal: "Observed 3′-end signal" })[value] || value;
  function taxonomyMarkup(classifications) {
    const ranks = ["phylum", "class", "order", "family", "genus", "species"];
    const primary = classifications?.records.find(r => r.system === classifications.default_system && r.taxonomy_version === classifications.default_version);
    if (!primary) throw new Error("Default classification unavailable.");
    const block = record => {
      const note = record.status === "pending" ? "Exact NCBI assembly version unresolved."
        : record.status === "unmatched" ? (record.system === "gtdb" ? "No exact assembly-version match in GTDB R207.0." : "No exact assembly match in the original GEM catalogue.") : "";
      const sourceLabel = record.tax_id ? `TaxID ${record.tax_id} ↗` : record.system === "ncbi" ? "NCBI assembly ↗" : record.label + " source ↗";
      const provenance = `<div class="taxonomy-meta">${link(sourceLabel, record.source_url)}${record.retrieved_at ? `<span>Retrieved ${esc(record.retrieved_at.slice(0,10))}</span>` : ""}</div>`;
      const lineage = note ? "" : `<dl class="taxonomy-lineage">${facts(ranks.map(rank => [rank[0].toUpperCase() + rank.slice(1), record[rank] || "Not assigned"]))}</dl>`;
      return `<div data-taxonomy-system="${esc(record.system)}">${provenance}${note ? `<p class="source-caveat">${esc(note)}</p>` : ""}${lineage}</div>`;
    };
    const supplementary = classifications.records.filter(r => r !== primary).sort((a,b) => (a.system === "gtdb" ? -1 : 1));
    return `<div class="genome-taxonomy"><div class="taxonomy-heading"><h3>${esc(primary.label)}</h3><span class="taxonomy-default">Default classification</span></div>${block(primary)}${supplementary.map(record => `<details class="taxonomy-supplement"><summary>${esc(record.system === "gtdb" ? record.label + " · supplementary classification" : "Original GEM mapping · historical")}</summary>${block(record)}</details>`).join("")}</div>`;
  }
  function sourceFacts(source) {
    const m = source.metadata || {};
    return [["3′-end assay", source.assay_family], ["Sample strain", m.sample_strain], ["Genotype", m.genotype],
      ["Conditions", m.conditions], ["Replicates", m.replicate_label ? m.replicate_label + (m.replicate_type ? ` (${m.replicate_type})` : "") : ""],
      ["Evidence", evidence(source.evidence_class)]];
  }
  function signalMarkup(source) {
    return source.signals.map(info => {
      if (info.signal_conditions?.length) return `<div class="source-signal"><p>BigWig · ${esc(info.signal_conditions[0].assay)}</p>`
        + info.signal_conditions.map(condition => `<div><p><strong>${esc(condition.label)}</strong> · ${accessions(condition.samples.map(sample => sample.accession).join(";"))}</p><p class="muted">${esc(condition.conditions)}</p></div>`).join("") + "</div>";
      const sample = info.signal_sample;
      return sample ? `<div class="source-signal"><p>BigWig sample: ${accessions(sample.sample_id)} · ${esc(sample.assay)}</p><p class="muted">${esc(sample.conditions)}</p></div>` : "";
    }).join("");
  }
  function studyMarkup(pmid, sources, allSources) {
    const first = sources[0], paper = first.publication || {}, citation = paper.citation || {};
    const title = paper.paper_title || first.metadata?.title || `PMID ${pmid}`;
    const paperUrl = /^10\./.test(paper.doi || "") ? `https://doi.org/${paper.doi}` : `https://pubmed.ncbi.nlm.nih.gov/${pmid}/`;
    const authors = (citation.authors || "").split(/;\s*/).filter(Boolean);
    const byline = [authors.length ? authors[0] + (authors.length > 1 ? " et al." : "") : "", paper.journal, paper.published_year].filter(Boolean).map(esc).join(" · ");
    const published = sources.filter(source => source.release_status === "published_standardized" && Number(source.record_count) > 0);
    const header = `<header><div><h3>${link(title + " ↗", paperUrl)}</h3><p class="study-citation">${byline ? byline + " · " : ""}${link(`PMID ${pmid} ↗`, `https://pubmed.ncbi.nlm.nih.gov/${pmid}/`)}</p></div>`;
    if (!published.length) return `<article class="study-card audit-card">${header}<span class="badge badge-review">Metadata only</span></header></article>`;
    const common = sourceFacts(first).filter(([label, value]) => value && published.every(source => sourceFacts(source).some(([key, v]) => key === label && v === value)));
    const commonLabels = new Set(common.map(([label]) => label));
    const details = published.map((source, index) => {
      const m = source.metadata || {};
      const paired = allSources.find(other => other.source_id === m.reused_data_with);
      const sampleDetails = m.sample_details ? `<p class="muted">${esc(m.sample_details)}</p>` : "";
      const uniqueFacts = facts(sourceFacts(source).filter(([label]) => !commonLabels.has(label)));
      return `<div class="source-evidence" id="source-${esc(source.source_id)}" data-source-card="${esc(source.source_id)}">
        ${published.length > 1 ? `<div class="source-heading"><h4>Dataset ${index + 1}</h4><strong>${format(source.record_count)} 3′-end records</strong></div>` : ""}
        ${uniqueFacts ? `<dl class="source-context">${uniqueFacts}</dl>` : ""}${sampleDetails}
        ${m.sample_id ? `<p>Samples: ${accessions(m.sample_id)}</p>` : ""}
        ${m.raw_data_accessions ? `<p class="source-links"><span class="source-raw">Raw data: ${accessions(m.raw_data_accessions)}</span></p>` : ""}
        ${paired ? `<p class="source-reuse">Shares raw sequencing data with ${link(`PMID ${paired.publication_pmid}`, `https://pubmed.ncbi.nlm.nih.gov/${paired.publication_pmid}/`)}.</p>` : ""}
        ${m.interpretation_note ? `<p class="source-caveat">${esc(m.interpretation_note)}</p>` : ""}${signalMarkup(source)}
      </div>`;
    }).join("");
    return `<article class="study-card" id="study-${esc(pmid)}">${header}<div class="study-count" title="Source records for this genome; overlapping coordinates are not deduplicated."><strong>${format(published.reduce((sum, source) => sum + Number(source.record_count), 0))}</strong><span>experimental 3′-end records</span></div></header><dl class="source-context">${facts(common)}</dl><div class="study-source-list">${details}</div></article>`;
  }
  function render(data) {
    if (data.metadata_source !== "d1" || data.assembly.accession !== assembly) throw new Error("Unexpected genome metadata.");
    const a = data.assembly, directory = a.directory || {};
    const title = a.organism_name || assembly;
    root.querySelector("[data-experimental-title]").textContent = title;
    document.title = `${title} · ${assembly} · BTED`;
    const count = root.querySelector("[data-experimental-count]");
    count.textContent = format(data.record_count); count.className = "";
    count.parentElement.querySelector("small").textContent = `${data.study_count} ${data.study_count === 1 ? "publication" : "publications"}`;
    if (!root.hasAttribute("data-batter-genome")) {
      const prediction = root.querySelector("[data-prediction-count]");
      prediction.textContent = format(data.predictions?.count || a.prediction_count || 0); prediction.className = "";
      const training = root.querySelector("[data-training-count]");
      training.textContent = format(directory.training || 0); training.className = "";
      root.querySelector("[data-training-breakdown]").textContent = "";
    }
    const size = a.contigs.reduce((sum, contig) => sum + Number(contig.length_bp), 0);
    root.querySelector("[data-experimental-overview]").innerHTML = `<div class="overview-heading"><h2>Reference & classification</h2>${link("NCBI assembly ↗", a.reference_url)}</div><dl class="genome-facts">${facts([["Genome source", directory.source], ["Reference strain", a.strain || "Not recorded"], ["Experimental reference length", `${format(size)} bp`], ["Contigs", format(a.contigs.length)]])}</dl>${taxonomyMarkup(a.classifications)}`;
    const predictionPanel = root.querySelector('[data-experimental-predictions]');
    if (predictionPanel) {
      const p=data.predictions;
      predictionPanel.hidden=!p;
      predictionPanel.innerHTML=p ? `<div class="section-heading"><h2>Model predictions</h2><div class="genome-download-actions">${p.downloads.map(f=>`<a class="button" href="${esc(f.url)}">${esc(f.label)}</a>`).join('')}</div></div><p><strong>${format(p.count)}</strong> predicted regions · ${esc(p.method)}</p><p class="muted">${p.reference_scope==='experimental'?'Predictions use the experimental reference assembly.':`Predictions use a sequence-verified computational reference (${format(p.reference_bases)} bp; ${p.reference_contigs} contigs). Counts and downloads cover that full reference; experimental tracks cover the matched contigs.`}</p>` : '';
    }
    const groups = new Map();
    for (const source of data.sources) {
      const group = groups.get(source.publication_pmid) || []; group.push(source); groups.set(source.publication_pmid, group);
    }
    cards.innerHTML = [...groups].map(([pmid, sources]) => studyMarkup(pmid, sources, data.sources)).join("");
    packageFiles.replaceChildren(...data.downloads.map(file => {
      const a = document.createElement("a"); a.href = file.url; a.dataset.packageFile = ""; a.dataset.zipPath = file.path; return a;
    }));
    const selected = new URLSearchParams(location.search).get("source_id");
    cards.querySelectorAll("[data-source-card]").forEach(card => card.classList.toggle("source-highlight", card.dataset.sourceCard === selected));
    button.hidden = data.record_count === 0; button.disabled = false; root.dataset.metadataSource = "d1";
  }
  async function load() {
    button.disabled = true; retry.hidden = true; status.textContent = "Loading study metadata…";
    try {
      const response = await fetch(new URL(`../api/assemblies/${encodeURIComponent(assembly)}/page-metadata`, document.baseURI));
      if (!response.ok) throw new Error("Study metadata unavailable.");
      render(await response.json()); status.textContent = "";
    } catch (error) {
      cards.replaceChildren(); packageFiles.replaceChildren();
      status.textContent = "Study metadata unavailable."; retry.hidden = false;
      root.querySelector("[data-experimental-count]").textContent = "Unavailable";
    }
  }
  retry.addEventListener("click", load);
  load();
})();
