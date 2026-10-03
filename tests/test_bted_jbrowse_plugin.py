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
    if(name==='@jbrowse/core/ui')return {Dialog(){return null;}};
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
const region=mod.visibleGff3('##gff-version 3\nchr1\tS1\tterminator_endpoint\t10\t10\t.\t+\t.\tID=A%3B1\nchr1\tS1\tterminator_endpoint\t20\t20\t.\t-\t.\tID=B\nchr2\tS1\tterminator_endpoint\t10\t10\t.\t+\t.\tID=C\n',{ref:'chr1',start:9,end:10});
const shareView={width:100,bpPerPx:2,displayedRegions:[{refName:'chr1'}],pxToBp(px){return {refName:'chr1',coord:1000+Math.round(px*2),reversed:true,oob:false};},tracks:[{configuration:'track_A',displays:[{height:44}]}]};
const share=mod.sharedView(shareView,new Set(['track_A']));
const fitCalls=[];
const fitView={width:800,offsetPx:1795,bpPerPx:1,displayedRegions:[{refName:'chr1'}],
  async navToLocString(location,assembly){fitCalls.push(['navigate',location,assembly]);},
  zoomTo(scale,center){fitCalls.push(['zoom',scale,center]);}};
await mod.showDefaultLocalReference(fitView,{regions:[{refName:'chr1',start:0,end:3573470}]},'BTED_TEST');
let rejectsUnknown=false;
try{mod.validateSharedState({...share,tracks:[{id:'unknown',height:44}]},new Set(['track_A']));}catch{rejectsUnknown=true;}
const rectangles=[];
const ctx={fillStyle:'',clearRect(){},fillRect(x,y,w,h){rectangles.push({x,y,w,h,color:this.fillStyle});},beginPath(){},moveTo(){},lineTo(){},stroke(){},fillText(){}};
const signal=(source,score,start)=>({get(key){return {source,score,start,end:start+1}[key];}});
const maximum=mod.paintMirroredSignal(ctx,[signal('plus',10,20),signal('minus',5,20)],{start:0,end:100,reversed:false},1,100,180);
const scaledMaximum=mod.paintMirroredSignal(ctx,[signal('plus',10,20)],{start:0,end:100,reversed:false},1,100,180,20);
mod.paintMirroredSignal(ctx,[signal('minus',5,20)],{start:0,end:100,reversed:true},1,100,180,20);
process.stdout.write(JSON.stringify({colors:['+', '-', '?', 1, -1].map(x=>colorFunction({get(){return x;}})),hasConfigure:typeof plugin.configure==='function',renderer:mirroredRenderer?.name,maximum,scaledMaximum,bars:rectangles.filter(r=>r.color==='#0f766e'||r.color==='#be123c'),keepsOriginal:replaceAbout(original,{config:{metadata:{}}})===original,content:text,region,share,fitCalls,rejectsUnknown}));
"""


class BtedJBrowsePluginTests(unittest.TestCase):
    def test_direct_reads_only_fall_back_on_network_failure(self) -> None:
        script = r'''
import fs from 'node:fs';
import assert from 'node:assert/strict';
// JBrowse adapters also run inside blob workers, whose relative base is opaque.
globalThis.location = {href:'blob:https://bted.example/worker',origin:'https://bted.example',protocol:'blob:'};
const url = 'https://huggingface.co/datasets/liurulong/terminator/resolve/'+'a'.repeat(40)+'/v0.3.0/assemblies/GCF_000005845.1/reference/reference.fna.fai';
const backup = '/api/assets/v0.4.0--'+'b'.repeat(64);
const asset = {url, fallback_url:backup, sha256:'c'.repeat(64)};
const calls=[];
let mode='success';
globalThis.fetch=async (input,init={})=>{
  const request=new Request(input,init); calls.push(request);
  request.signal.throwIfAborted();
  if(request.url.startsWith('https://huggingface.co/')){
    if(mode==='failure')throw new TypeError('Failed to fetch');
    return new Response('direct',{status:mode==='missing'?404:200});
  }
  if(request.url.endsWith('/assets/data-release.json'))return Response.json({releaseVersion:'v0.4.0',assets:{'assemblies/GCF_000005845.1/reference/reference.fna.fai':asset}});
  return new Response('backup',{status:206,headers:{'x-bted-sha256':'c'.repeat(64),'Content-Range':'bytes 0-5/29'}});
};
const mod=await import('data:text/javascript,'+encodeURIComponent(fs.readFileSync(process.argv[1],'utf8')));
assert.equal(await (await fetch(url)).text(),'direct');
assert.equal(calls.length,1); assert.equal(calls[0].cache,'no-cache'); assert.equal(calls[0].credentials,'omit');
mode='missing'; assert.equal((await fetch(url)).status,404); assert.equal(calls.length,2);
const cancel=new AbortController();cancel.abort();
await assert.rejects(fetch(url,{signal:cancel.signal}),{name:'AbortError'});
assert.equal(calls.length,3);
mode='failure';
assert.equal(await (await fetch(new Request(url,{headers:{Range:'bytes=0-5'}}))).text(),'backup');
assert.equal(calls.at(-1).headers.get('Range'),'bytes=0-5');
assert.equal(calls.at(-1).url,'https://bted.example'+backup);
const directCount=calls.filter(request=>request.url===url).length;
await fetch(url,{headers:{Range:'bytes=6-9'}});
assert.equal(calls.filter(request=>request.url===url).length,directCount);
await assert.rejects(fetch(url.replace('a'.repeat(40),'d'.repeat(40))),/Failed to fetch/);
await fetch('https://example.org/file');assert.equal(calls.at(-1).cache,'default');
'''
        result = subprocess.run(["node", "--input-type=module", "-e", script, str(PLUGIN)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr[:1500])

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
        for required in ("Study", "Endpoint evidence", "Example paper", "Test Journal", "S1"):
            self.assertIn(required, data["content"])
        self.assertNotIn("CC BY", data["content"])
        self.assertNotIn("License", data["content"])
        self.assertIn("ID=A%3B1", data["region"])
        self.assertNotIn("ID=B", data["region"])
        self.assertNotIn("ID=C", data["region"])
        self.assertEqual(data["share"]["center"], 1100)
        self.assertTrue(data["share"]["reversed"])
        self.assertEqual(data["share"]["tracks"], [{"id": "track_A", "height": 44}])
        self.assertEqual(data["fitCalls"][0], ["navigate", "chr1:2295", "BTED_TEST"])
        self.assertEqual(data["fitCalls"][1][0], "zoom")
        self.assertAlmostEqual(data["fitCalls"][1][1], 1000 / 800)
        self.assertEqual(data["fitCalls"][1][2], 400)
        self.assertTrue(data["rejectsUnknown"])
        self.assertNotIn("schema_version", data["content"])


if __name__ == "__main__":
    unittest.main()
