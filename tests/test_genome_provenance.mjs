import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import test from "node:test";

const script = readFileSync(new URL("../site/assets/batter-browser.js", import.meta.url), "utf8");

test("genome provenance uses registered metadata and remains readable when the browser is unavailable", async () => {
  for (const otu of ["OTU-32567", ""]) {
    const element = () => ({ children: [], dataset: {}, hidden: true, textContent: "",
      append(...items) { this.children.push(...items); },
      replaceChildren(...items) { this.children = items; },
      addEventListener() {}, removeEventListener() {},
    });
    const nodes = new Map();
    const select = selector => {
      if (!nodes.has(selector)) nodes.set(selector, element());
      return nodes.get(selector);
    };
    const metadata = { otu_id: otu, genome_type: "SAG", taxonomy: "s__Example", source_collection: "IMG",
      reference: { source: "GEM representative", source_path: "genomes/OTU-32567.fna.gz", source_sha256: "a".repeat(64), contigs: 46, bases: 1309253 },
      feature_counts: {}, browser_files: {}, annotation: { status: "unavailable" }, revision: "b".repeat(40),
    };
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
    assert.equal(facts["Sequence source"], "GEM representative");
    assert.equal(facts["Input FASTA"], metadata.reference.source_path);
    assert.match(panel.children[2].textContent, /not all members/);
    assert.equal(panel.children[3].children[1].textContent, metadata.reference.source_sha256);
    assert.match(select("[data-browser-status]").textContent, /not ready/);
  }
});
