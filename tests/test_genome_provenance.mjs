import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import test from "node:test";

const script = readFileSync(new URL("../site/assets/batter-browser.js", import.meta.url), "utf8");

test("genome provenance uses registered metadata and remains readable when the browser is unavailable", async () => {
  for (const [otu, annotation] of [["OTU-32567", { status: "unavailable" }], ["", { status: "unavailable" }],
    ["OTU-32567", { status: "matched", coverage: "partial", matched_reference_contigs: 45, total_reference_contigs: 46,
      annotation_origin_label: "Published third-party reannotation" }]]) {
    const element = () => ({ children: [], dataset: {}, hidden: true, textContent: "",
      append(...items) { this.children.push(...items); },
      replaceChildren(...items) { this.children = items; },
      setAttribute() {},
      addEventListener() {}, removeEventListener() {},
    });
    const nodes = new Map();
    const select = selector => {
      if (!nodes.has(selector)) nodes.set(selector, element());
      return nodes.get(selector);
    };
    const metadata = { otu_id: otu, genome_type: "SAG", taxonomy: otu ? "p__P; c__C;o__O;f__F;g__Example;s__Example species" : "p__P;s__", source_collection: "IMG",
      reference: { source: "GEM representative", source_path: "genomes/OTU-32567.fna.gz", source_sha256: "a".repeat(64), contigs: 46, bases: 1309253 },
      feature_counts: otu ? { tes_prediction: 0, otu_augmentation_span: 11, rfam_training_span: 5, otu_augmentation_window: 105, rfam_training_window: 5 } : {}, browser_files: {"augmentation.gff3.gz":{url:"https://example.org/augmentation.gff3.gz"}}, annotation, revision: "b".repeat(40),
    };
    select("[data-experimental-count]").textContent = "2,848";
    runInNewContext(script, {
      document: { baseURI: "https://bted.example/genomes/genome.html", querySelector: select, createElement: element },
      location: { href: "https://bted.example/genomes/genome.html?genome=2228664028", search: "?genome=2228664028" },
      history: { replaceState() {} }, URL, URLSearchParams,
      fetch: async url => ({ ok: !String(url).includes("/config"), json: async () => metadata }),
    });
    await new Promise(resolve => setImmediate(resolve));
    const panel = select("[data-batter-provenance]");
    const facts = Object.fromEntries(panel.children[1].children.map(item => item.children.map(node => node.textContent)));
    assert.equal(panel.hidden, false);
    assert.equal(facts["Genome ID"], "2228664028");
    assert.equal(facts["GEM OTU"], otu || undefined);
    assert.equal(facts["Genome source"], "IMG");
    assert.equal(facts["Reference sequence"], "GEM representative");
    assert.equal(facts["Input FASTA"], undefined);
    assert.equal(facts["Genome size"], "1,309,253 bp");
    assert.equal(facts["Contigs"], "46");
    assert.equal(facts["CDS annotation"], undefined);
    const taxonomy = select("[data-batter-taxonomy]");
    assert.equal(taxonomy.hidden, false);
    assert.deepEqual(taxonomy.children[1].children.map(item => item.children.map(node => node.textContent)), [
      ["Phylum", "P"], ["Class", otu ? "C" : "Not assigned"], ["Order", otu ? "O" : "Not assigned"],
      ["Family", otu ? "F" : "Not assigned"], ["Genus", otu ? "Example" : "Not assigned"],
      ["Species", otu ? "Example species" : "Not assigned"],
    ]);
    assert.equal(taxonomy.children[0].children[1].children[0].textContent, "GTDB R89 (GEM)");
    assert.equal(select("[data-experimental-count]").textContent, "2,848");
    assert.equal(select("[data-prediction-count]").textContent, otu ? "0" : "Not available");
    assert.equal(select("[data-training-count]").textContent, otu ? "16" : "Not available");
    assert.equal(select("[data-training-breakdown]").textContent, otu ? "OTU 11 · Rfam 5" : "");
    assert.equal(select("[data-batter-downloads]").children[0].textContent, "Augmented regions (GFF3)");
    assert.equal(panel.children.length, 2);
    assert.ok(!JSON.stringify(panel).includes('Gene annotation:'));
    assert.ok(!JSON.stringify(panel).includes('Published third-party reannotation'));
    assert.ok(!JSON.stringify(panel).includes(metadata.reference.source_sha256));
    assert.match(select("[data-browser-status]").textContent, /unavailable/);
  }
});
