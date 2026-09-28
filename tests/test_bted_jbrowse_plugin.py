"""Check the BTED plugin contract against the pinned JBrowse extension API."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "jbrowse-plugin/dist/bted-track-plugin.js"

HARNESS = r"""
import fs from 'node:fs';
global.window = {location:{href:'https://bted.example/jbrowse/index.html'}};
const source = fs.readFileSync(process.argv[1], 'utf8');
const mod = await import(`data:text/javascript,${encodeURIComponent(source)}`);
let replaceAbout, colorFunction;
const pluginManager = {
  jexl: {addFunction(name, fn){if(name==='btedStrandColor')colorFunction=fn;}},
  jbrequire(name){
    if(name==='react')return {createElement(tag, props, ...children){return {tag:typeof tag==='string'?tag:'component',props,children};}};
    if(name==='@jbrowse/core/configuration')return {readConfObject(config){return config;},getConf(config,key){return config[key];}};
    throw Error(name);
  },
  addToExtensionPoint(name, callback){if(name==='Core-replaceAbout')replaceAbout=callback;},
};
new mod.default().install(pluginManager);
const original=()=>null;
const about={kind:'endpoint',title:'Example paper',authors:'A; B',journal:'Test Journal',year:'2026',pmid:'12345678',source_id:'S1',assay:'Term-seq',record_count:17,evidence:'Paper-reported 3′ end',assembly:'GCF_TEST',license:'CC BY',gff3_url:'https://example.org/endpoints.gff3.gz',pubmed_url:'https://pubmed.ncbi.nlm.nih.gov/12345678/'};
const component=replaceAbout(original,{config:{metadata:{btedAbout:about}}});
const tree=component({config:{metadata:{btedAbout:about}}});
const text=JSON.stringify(tree);
process.stdout.write(JSON.stringify({colors:['+', '-', '?', 1, -1].map(x=>colorFunction({get(){return x;}})),keepsOriginal:replaceAbout(original,{config:{metadata:{}}})===original,content:text}));
"""


class BtedJBrowsePluginTests(unittest.TestCase):
    def test_strand_colors_and_grouped_about(self) -> None:
        self.assertTrue(PLUGIN.is_file(), "Build the locked JBrowse plugin before tests")
        result = subprocess.run(
            ["node", "--input-type=module", "-e", HARNESS, str(PLUGIN)],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["colors"], ["#0f766e", "#be123c", "#64748b", "#0f766e", "#be123c"])
        self.assertTrue(data["keepsOriginal"])
        for required in ("Study", "Endpoint evidence", "Source and use", "Example paper", "Test Journal", "S1", "CC BY", "Download study GFF3"):
            self.assertIn(required, data["content"])
        self.assertNotIn("schema_version", data["content"])


if __name__ == "__main__":
    unittest.main()
