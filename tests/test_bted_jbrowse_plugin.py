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
let replaceAbout, colorFunction, mirroredRenderer;
class FeatureRendererType {
  constructor(settings){Object.assign(this,settings);}
  async getFeatures(){return new Map();}
}
const pluginManager = {
  jexl: {addFunction(name, fn){if(name==='btedStrandColor')colorFunction=fn;}},
  jbrequire(name){
    if(name==='react')return {createElement(tag, props, ...children){return {tag:typeof tag==='string'?tag:'component',props,children};}};
    if(name==='@jbrowse/core/configuration')return {readConfObject(config){return config;},getConf(config,key){return config[key];},ConfigurationSchema(){return {};}};
    if(name==='@jbrowse/core/util')return {getContainingTrack(){return {};}};
    if(name==='@jbrowse/core/pluggableElementTypes/renderers/FeatureRendererType')return {default:FeatureRendererType};
    throw Error(name);
  },
  addToExtensionPoint(name, callback){if(name==='Core-replaceAbout')replaceAbout=callback;},
  addRendererType(factory){mirroredRenderer=factory(this);},
};
const plugin = new mod.default();
plugin.install(pluginManager);
plugin.configure(pluginManager);
const original=()=>null;
const about={kind:'endpoint',title:'Example paper',authors:'A; B',journal:'Test Journal',year:'2026',pmid:'12345678',source_id:'S1',assay:'Term-seq',record_count:17,evidence:'Paper-reported 3′ end',assembly:'GCF_TEST',license:'CC BY',gff3_url:'https://example.org/endpoints.gff3.gz',pubmed_url:'https://pubmed.ncbi.nlm.nih.gov/12345678/'};
const component=replaceAbout(original,{config:{metadata:{btedAbout:about}}});
const tree=component({config:{metadata:{btedAbout:about}}});
const text=JSON.stringify(tree);
const rectangles=[];
const ctx={fillStyle:'',clearRect(){},fillRect(x,y,w,h){rectangles.push({x,y,w,h,color:this.fillStyle});},beginPath(){},moveTo(){},lineTo(){},stroke(){},fillText(){}};
const signal=(source,score,start)=>({get(key){return {source,score,start,end:start+1}[key];}});
const maximum=mod.paintMirroredSignal(ctx,[signal('plus',10,20),signal('minus',5,20)],{start:0,end:100,reversed:false},1,100,180);
const scaledMaximum=mod.paintMirroredSignal(ctx,[signal('plus',10,20)],{start:0,end:100,reversed:false},1,100,180,20);
mod.paintMirroredSignal(ctx,[signal('minus',5,20)],{start:0,end:100,reversed:true},1,100,180,20);
process.stdout.write(JSON.stringify({colors:['+', '-', '?', 1, -1].map(x=>colorFunction({get(){return x;}})),hasConfigure:typeof plugin.configure==='function',renderer:mirroredRenderer?.name,maximum,scaledMaximum,bars:rectangles.filter(r=>r.color==='#0f766e'||r.color==='#be123c'),keepsOriginal:replaceAbout(original,{config:{metadata:{}}})===original,content:text}));
"""


class BtedJBrowsePluginTests(unittest.TestCase):
    def test_strand_colors_and_grouped_about(self) -> None:
        self.assertTrue(PLUGIN.is_file(), "Build the locked JBrowse plugin before tests")
        result = subprocess.run(
            ["node", "--input-type=module", "-e", HARNESS, str(PLUGIN)],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr[:1500])
        data = json.loads(result.stdout)
        self.assertEqual(data["colors"], ["#0f766e", "#be123c", "#64748b", "#0f766e", "#be123c"])
        self.assertTrue(data["hasConfigure"])
        self.assertEqual(data["renderer"], "BTEDMirroredSignalRenderer")
        self.assertEqual(data["maximum"], 10)
        self.assertEqual(data["scaledMaximum"], 20)
        self.assertEqual([(bar["color"], bar["x"], bar["y"]) for bar in data["bars"]], [
            ("#0f766e", 20, 14), ("#be123c", 20, 91), ("#0f766e", 20, 52), ("#be123c", 79, 91),
        ])
        self.assertTrue(data["keepsOriginal"])
        for required in ("Study", "Endpoint evidence", "Source and use", "Example paper", "Test Journal", "S1", "CC BY", "Download study GFF3"):
            self.assertIn(required, data["content"])
        self.assertNotIn("schema_version", data["content"])


if __name__ == "__main__":
    unittest.main()
