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
let replaceAbout, extendElement, colorFunction, mirroredRenderer;
class FeatureRendererType {
  constructor(settings){Object.assign(this,settings);}
  async getFeatures(){return new Map();}
}
const pluginManager = {
  jexl: {addFunction(name, fn){if(name==='btedStrandColor')colorFunction=fn;}},
  jbrequire(name){
    if(name==='react')return {createElement(tag, props, ...children){return {tag:typeof tag==='string'?tag:'component',props,children};}};
    if(name==='@jbrowse/core/pluggableElementTypes')return {GlyphType:class {constructor(settings){Object.assign(this,settings);}}};
    if(name==='@jbrowse/core/configuration')return {readConfObject(config){return config;},getConf(config,key){return config[key];},ConfigurationSchema(){return {};}};
    if(name==='@jbrowse/core/util')return {getContainingTrack(display){return display.track || {};}};
    if(name==='@jbrowse/core/ui')return {Dialog(){return null;}};
    if(name==='@jbrowse/core/pluggableElementTypes/renderers/FeatureRendererType')return {default:FeatureRendererType};
    throw Error(name);
  },
  addToExtensionPoint(name, callback){if(name==='Core-replaceAbout')replaceAbout=callback;if(name==='Core-extendPluggableElement')extendElement=callback;},
  addRendererType(factory){mirroredRenderer=factory(this);},
  addGlyphType(factory){factory(this);},
};
const plugin = new mod.default();
plugin.install(pluginManager);
plugin.configure(pluginManager);
let displayViews;
const signalDisplay={track:{metadata:{btedMirroredSignal:true}},autoscale:'global',trackMenuItems(){return [{label:'Score',subMenu:[{label:'Autoscale type',subMenu:[{label:'Global'},{label:'Local'}]}]}];}};
extendElement({name:'MultiLinearWiggleDisplay',stateModel:{extend(fn){displayViews=fn(signalDisplay).views;return this;}}});
if(displayViews.autoscaleType!=='local')throw Error('Saved global setting overrode current-window scaling');
const scaleMenu=displayViews.trackMenuItems()[0].subMenu[0];
if(scaleMenu.subMenu.length!==1 || scaleMenu.subMenu[0].label!=='Visible window')throw Error('Global scale menu remains exposed');
signalDisplay.track.metadata.btedMirroredSignal=false;
if(displayViews.autoscaleType!=='global')throw Error('Unrelated user track scale was changed');
const original=()=>null;
const about={kind:'endpoint',title:'Example paper',authors:'A; B',journal:'Test Journal',year:'2026',pmid:'12345678',source_id:'S1',assay:'Term-seq',record_count:17,evidence:'Paper-reported 3′ end',assembly:'GCF_TEST',license:'CC BY',gff3_url:'https://example.org/endpoints.gff3.gz',pubmed_url:'https://pubmed.ncbi.nlm.nih.gov/12345678/'};
const component=replaceAbout(original,{config:{metadata:{btedAbout:about}}});
const tree=component({config:{metadata:{btedAbout:about}}});
const dialogTitle={textContent:'BATTER_S1_007 · PMID 31555254 · endpoint records'};
tree.props.ref({closest(){return {querySelector(){return dialogTitle;}};}});
if(dialogTitle.textContent!=='PMID 31555254 · endpoint records')throw Error('About title exposes internal source ID');
tree.props.ref(null);
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
const maximum=mod.paintMirroredSignal(ctx,[signal('plus',10,20),signal('minus',5,20)],{start:0,end:100,reversed:false},1,100,180,10);
// Viewport statistics share one scale across both strands and all render blocks.
const stable=[];
const stableCtx={...ctx,fillRect(x,y,w,h){if(this.fillStyle==='#0f766e')stable.push(h);}};
mod.paintMirroredSignal(stableCtx,[signal('plus',5,20),signal('minus',100,80)],{start:0,end:100},1,100,180,100);
mod.paintMirroredSignal(stableCtx,[signal('plus',5,20)],{start:0,end:100},1,100,180,5);
if(Math.abs(stable[0]-3.8)>1e-9 || stable[1]!==76)throw Error('Signal did not rescale with the visible window');
mod.paintMirroredSignal(stableCtx,[signal('plus',0,20)],{start:0,end:100},1,100,180,100);
if(stable.length!==2)throw Error('Zero signal was painted');
// A tenfold score difference must produce a tenfold height on the same linear scale.
const linearBars=[];
const linearCtx={...ctx,fillRect(x,y,w,h){if(this.fillStyle==='#0f766e'||this.fillStyle==='#be123c')linearBars.push(h);}};
mod.paintMirroredSignal(linearCtx,[signal('plus',100,20),signal('minus',1000,30)],{start:0,end:100},1,100,180,1000,'linear');
if(Math.abs(linearBars[1]/linearBars[0]-10)>1e-9)throw Error('Linear coverage heights lost their 1000:100 ratio');
// Excluding a strong peak raises the weak-window bars; original scores remain intact.
const logBars=[];
const logCtx={...ctx,fillRect(x,y,w,h){if(this.fillStyle==='#0f766e'||this.fillStyle==='#be123c')logBars.push(h);}};
const weak=signal('plus',572,20), minusWeak=signal('minus',12,20);
mod.paintMirroredSignal(logCtx,[weak,minusWeak,signal('minus',367957,80)],{start:0,end:100},1,100,180,367957,'log');
mod.paintMirroredSignal(logCtx,[weak,minusWeak],{start:0,end:100},1,100,180,572,'log');
if(logBars[0]<30 || logBars[1]<10 || logBars[2]!==76 || logBars[3]!==76 || logBars[4]<=logBars[1])throw Error('Visible-window log scaling or shared strand scale failed');
mod.paintMirroredSignal(logCtx,[signal('plus',0,20)],{start:0,end:100},1,100,180,367957,'log');
if(logBars.length!==5 || weak.get('score')!==572)throw Error('Zero or original score changed');
globalThis.OffscreenCanvas=class { getContext(){return {...ctx,getImageData(){return {data:[]};}};} };
const rendered=await mirroredRenderer.render({regions:[{start:0,end:100}],bpPerPx:1,height:180,scaleOpts:{domain:[0,200],stats:{scoreMax:100}}});
if(rendered.visibleMax!==100)throw Error('Renderer ignored shared viewport statistics');
const logRendered=await mirroredRenderer.render({regions:[{start:0,end:100}],bpPerPx:1,height:180,scaleOpts:{scaleType:'log',stats:{scoreMax:367957}}});
if(logRendered.signalScale!=='log' || logRendered.visibleMax!==367957)throw Error('Renderer lost the shared window log scale');
const fractionalRendered=await mirroredRenderer.render({regions:[{start:0,end:100}],bpPerPx:1,height:180,scaleOpts:{stats:{scoreMax:0.5}}});
if(fractionalRendered.visibleMax!==0.5)throw Error('Fractional window maximum was clamped to one');
const localRendered=await mirroredRenderer.render({regions:[{start:0,end:100}],bpPerPx:1,height:180,scaleOpts:{scaleType:'log',stats:{scoreMax:572}}});
if(localRendered.visibleMax!==572)throw Error('Renderer retained the previous window maximum');
const emptyRendered=await mirroredRenderer.render({regions:[{start:0,end:100}],bpPerPx:1,height:180,scaleOpts:{stats:{scoreMax:0}}});
if(emptyRendered.visibleMax!==1)throw Error('Empty window must retain a valid blank baseline');
const scaledMaximum=mod.paintMirroredSignal(ctx,[signal('plus',10,20)],{start:0,end:100,reversed:false},1,100,180,20);
mod.paintMirroredSignal(ctx,[signal('minus',5,20)],{start:0,end:100,reversed:true},1,100,180,20);
process.stdout.write(JSON.stringify({colors:['+', '-', '?', 1, -1].map(x=>colorFunction({get(){return x;}})),hasConfigure:typeof plugin.configure==='function',renderer:mirroredRenderer?.name,maximum,scaledMaximum,bars:rectangles.filter(r=>r.color==='#0f766e'||r.color==='#be123c'),keepsOriginal:replaceAbout(original,{config:{metadata:{}}})===original,content:text,region,share,fitCalls,rejectsUnknown}));
"""


class BtedJBrowsePluginTests(unittest.TestCase):
    def test_track_buttons_use_native_actions_and_check_bridge_sender(self) -> None:
        script = r'''
import fs from 'node:fs';
import assert from 'node:assert/strict';
const actions = [], replies = [];
let listener, ready;
const current = { type: 'LinearGenomeView', id: 'view1', width: 100, assemblyNames: ['A'],
  setTrackLabels() {}, activateTrackSelector() { actions.push('select'); } };
const session = { views: [current], assemblies: [{ name: 'A', sequence: { trackId: 'reference' } }],
  addWidget(type, id, options) { actions.push({ type, id, options }); return { type }; },
  showWidget(widget) { actions.push(widget.type); },
  getTracksById() { return { reference: { trackId: 'reference' }, ...Object.fromEntries(Array.from({ length: 6 }, (_, i) => [i, { assemblyNames: ['A'] }])) }; } };
globalThis.window = { location: { search: '?bted_bridge=unit', origin: 'https://bted.example' },
  parent: { postMessage(message) { replies.push(message); } },
  addEventListener(type, fn) { if (type === 'message') listener = fn; },
  setInterval(fn) { ready = fn; return 1; }, clearInterval() {} };
globalThis.document = { createElement: () => ({}), head: { append() {} } };
const mod = await import('data:text/javascript,' + encodeURIComponent(fs.readFileSync(process.argv[1], 'utf8')));
const pm = { rootModel: { session, jbrowse: { tracks: [], assemblies: [] } },
  jexl: { addFunction() {} }, addToExtensionPoint() {}, addRendererType() {}, addGlyphType() {},
  jbrequire(name) {
    if (name === 'react') return { createElement() {} };
    if (name === '@jbrowse/core/configuration') return { readConfObject: x => x, getConf: (x, k) => x[k] };
    if (name.endsWith('/FeatureRendererType')) return { default: class {} };
    return {};
  } };
new mod.default().install(pm);
current.tracks = [{ displays: [{height:120}] }, { displays: [{height:180}] }, { displays: [{height:180}] }];
ready(); assert.equal(replies.at(-1).trackCount, 7);
assert.equal(replies.at(-1).frameHeight, 758);
const message = type => ({ origin: 'https://bted.example', source: window.parent,
  data: { channel: 'bted-browser-v1', nonce: 'unit', id: '1', type } });
await listener({ ...message('add-user-track'), origin: 'https://other.example' });
await listener({ ...message('add-user-track'), source: {} });
await listener({ ...message('add-user-track'), data: { ...message('add-user-track').data, nonce: 'wrong' } });
assert.equal(actions.length, 0);
await listener(message('select-tracks')); assert.deepEqual(actions, ['select']);
await listener(message('add-user-track'));
assert.deepEqual(actions[1], { type: 'AddTrackWidget', id: 'addTrackWidget', options: { view: 'view1' } });
assert.equal(actions[2], 'AddTrackWidget'); assert.equal(replies.at(-1).type, 'panel-opened');
'''
        result = subprocess.run(["node", "--input-type=module", "-e", script, str(PLUGIN)], cwd=ROOT,
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr[:1500])

    def test_embedded_menus_keep_exports_and_preserve_other_filters(self) -> None:
        script = r'''
import fs from 'node:fs';
import assert from 'node:assert/strict';
const mod=await import('data:text/javascript,'+encodeURIComponent(fs.readFileSync(process.argv[1],'utf8')));
global.window={location:{href:'https://bted.example/jbrowse/',origin:'https://bted.example'}};
const pinned='https://huggingface.co/datasets/liurulong/terminator/resolve/'+'a'.repeat(40)+'/';
assert.equal(mod.downloadUrl(pinned+'v0.5.0/genomes/batter-000/GCF_TEST/predictions/tes.gff3.gz'),pinned+'v0.5.0/genomes/batter-000/GCF_TEST/predictions/tes.gff3.gz');
assert.equal(mod.downloadUrl(pinned+'v0.4.0/tracks/S1/endpoints.gff3'),pinned+'v0.4.0/tracks/S1/endpoints.gff3');
assert.equal(mod.downloadUrl(pinned.replace('a'.repeat(40),'main')+'v0.5.0/genomes/batter-000/GCF_TEST/predictions/tes.gff3.gz'),'');
assert.equal(mod.downloadUrl('https://example.org/file'),'');
let filters=["jexl:get(feature,'type')=='gene'"];
const display={activeFilters:()=>filters,setJexlFilters(next){filters=next;}};
const items=[{label:'Show...',subMenu:[{label:'Show labels'},{label:'Gene glyph'}]},
 {label:'Display mode',subMenu:['normal','compact','collapse'].map(label=>({label}))},
 {label:'Filter by...',subMenu:[{label:'Edit filters...'},{label:'Show only genes'}]}];
const menu=mod.compactFeatureMenu(items,display,'endpoint');
assert.deepEqual(menu[0].subMenu.map(x=>x.label),['Show labels']);
assert.deepEqual(menu[1].subMenu.map(x=>x.label),['Expanded','Compact']);
const strand=menu[2].subMenu.find(x=>x.label==='Strand');
assert.equal(menu[2].subMenu.some(x=>x.label==='Show only genes'),false);
const genes=mod.compactFeatureMenu(items,display,'reference');
assert.ok(genes[0].subMenu.some(x=>x.label==='Gene glyph'));
assert.ok(genes[2].subMenu.some(x=>x.label==='Show only genes'));
strand.subMenu[1].onClick();assert.equal(filters.length,2);assert.ok(filters[1].includes("=='+'"));
strand.subMenu[2].onClick();assert.equal(filters.length,2);assert.ok(filters[1].includes("=='-'"));
strand.subMenu[0].onClick();assert.deepEqual(filters,["jexl:get(feature,'type')=='gene'"]);
filters=["jexl:get(feature,'type')!='training_sequence_window' && get(feature,'type')!='rfam_training_window'", "jexl:get(feature,'strand')==1 || get(feature,'strand')=='+'"];
let context=mod.compactFeatureMenu(items,display,'augmentation')[2].subMenu.find(x=>x.label==='Show sequence context windows');
assert.equal(context.checked,false);context.onClick();assert.equal(filters.length,1);assert.ok(filters[0].includes("=='+'"));
context=mod.compactFeatureMenu(items,display,'augmentation')[2].subMenu.find(x=>x.label==='Show sequence context windows');
assert.equal(context.checked,true);context.onClick();assert.equal(filters.length,2);
const contextStrand=mod.compactFeatureMenu(items,display,'augmentation')[2].subMenu.find(x=>x.label==='Strand');
contextStrand.subMenu[2].onClick();assert.ok(filters.includes("jexl:get(feature,'type')!='training_sequence_window' && get(feature,'type')!='rfam_training_window'"));
filters=["jexl:get(feature,'type')!='region'"];
const regionControl=mod.compactFeatureMenu(items,display,'reference')[2].subMenu.find(x=>x.label==='Show reference-region annotations');
assert.equal(regionControl.checked,false);regionControl.onClick();assert.deepEqual(filters,[]);
const actions=[{label:'About track'},{label:'Track actions',subMenu:[{label:'Save track data',onClick:()=>42},{label:'Copy track'}]}];
assert.deepEqual(mod.compactTrackActions(actions,true).map(x=>x.label),['About track']);
const exportItem=mod.compactTrackActions(actions,false)[1];
assert.equal(exportItem.label,'Export visible track data');assert.equal(exportItem.onClick(),42);
assert.equal(actions[1].subMenu.length,2);
'''
        result = subprocess.run(["node", "--input-type=module", "-e", script, str(PLUGIN)], cwd=ROOT,
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr[:1500])

    def test_external_details_keep_native_widget_and_standalone_fallback(self) -> None:
        script = r'''
import fs from 'node:fs';
import assert from 'node:assert/strict';
global.window = { location: { search: '' } };
const mod = await import('data:text/javascript,' + encodeURIComponent(fs.readFileSync(process.argv[1], 'utf8')));
let replaceWidget;
const react = { createElement: (component, props, ...children) => ({ component, props, children }), useEffect() {}, useMemo: fn => fn(), useState: value => [value, () => {}] };
const ThemeProvider = () => null;
const pm = {
  jexl: { addFunction() {} }, addRendererType() {}, addGlyphType() {},
  addToExtensionPoint(name, callback) { if (name === 'Core-replaceWidget') replaceWidget = callback; },
  jbrequire(name) {
    if (name === 'react') return react;
    if (name === 'react-dom') return { createPortal: (content, target) => ({ content, target }) };
    if (name === '@mui/material/styles') return { ThemeProvider, useTheme: () => ({ components: {} }) };
    if (name === '@jbrowse/core/util/tracks') return { storeBlobLocation: ({ blob }) => ({ name: blob.name, blob, locationType: 'BlobLocation' }) };
    if (name.endsWith('/FeatureRendererType')) return { default: class {} };
    return {};
  },
};
new mod.default().install(pm);
const Original = () => null;
const model = { type: 'BaseFeatureWidget' }, props = { model, session: {}, toolbarHeight: 36 };
assert.equal(replaceWidget(Original, props), Original); // Full browser remains native.
window.location.search = '?bted_bridge=test';
window.parent = { document: { querySelector: () => null } };
assert.equal(replaceWidget(Original, props), Original); // Missing outer host remains usable.
global.document = { documentElement: { dataset: {} } };
const target = {};
const shadowRoot = { querySelector: () => target };
window.parent.document.querySelector = () => ({ querySelector: () => ({ shadowRoot }) });
assert.equal(replaceWidget(Original, { model: { type: 'UnknownWidget' } }), Original);
const Wrapper = replaceWidget(Original, props), portal = Wrapper(props);
assert.equal(portal.target, target);
assert.equal(portal.content.component, ThemeProvider);
assert.equal(portal.content.props.theme.components.MuiPopover.defaultProps.container, target);
const native = portal.content.children[0];
assert.equal(native.component, Original);
assert.equal(native.props.model, model);
assert.equal(native.props.session, props.session);
assert.equal(native.props.toolbarHeight, 0);
assert.equal(native.props.modal, true);
assert.equal(replaceWidget(Original, props), Wrapper); // Reusing a widget does not remount its controls.
for (const type of ['HierarchicalTrackSelectorWidget', 'AddTrackWidget']) {
  const panelModel = { type, setTrackData(value) { this.trackData = value; }, setIndexTrackData(value) { this.indexData = value; } };
  const panelProps = { ...props, model: panelModel };
  const Panel = replaceWidget(Original, panelProps);
  const panelTree = Panel(panelProps).content;
  const nativePanel = type === 'AddTrackWidget' ? panelTree.children.at(-1).children[0] : panelTree.children.at(-1);
  assert.equal(nativePanel.component, Original);
  assert.equal(nativePanel.props.model, panelProps.model);
  assert.equal(nativePanel.props.toolbarHeight, 0);
  if (type === 'HierarchicalTrackSelectorWidget') assert.ok(nativePanel.props.overrideDimensions.height.includes('480px'));
  if (type === 'AddTrackWidget') {
    const file = new File(['chr1\t0\t10'], 'sample.bed');
    const input = panelTree.children[1].children[0].children[1];
    assert.equal(input.props.multiple, true);
    input.props.onChange({ target: { files: [file] } });
    assert.notEqual(panelModel.trackData.blob, file);
    assert.equal(await panelModel.trackData.blob.text(), await file.text());
    assert.equal(panelModel.trackData.name, file.name);
    assert.equal(panelModel.indexData, undefined);
    const bam = new File(['synthetic'], 'sample.bam'), index = new File(['index'], 'sample.bam.bai');
    input.props.onChange({ target: { files: [index, bam] } });
    assert.equal(panelModel.trackData.name, bam.name);
    assert.equal(panelModel.indexData.name, index.name);
    input.props.onChange({ target: { files: [bam] } });
    assert.equal(panelModel.trackData, undefined); // No stale data after invalid selection.
    assert.equal(panelModel.indexData, undefined);
    for (const name of ['sample.bed', 'sample.gff3', 'sample.bw']) {
      assert.equal(mod.selectLocalTrackFiles([{ name }]).track.name, name);
    }
    for (const [main, indexName] of [['sample.bam', 'sample.bai'], ['sample.bam', 'sample.bam.csi'],
      ['sample.cram', 'sample.cram.crai'], ['sample.gff3.gz', 'sample.gff3.gz.tbi'], ['sample.vcf.gz', 'sample.vcf.gz.csi']]) {
      assert.equal(mod.selectLocalTrackFiles([{ name: indexName }, { name: main }]).index.name, indexName);
    }
    assert.throws(() => mod.selectLocalTrackFiles([{ name: 'sample.bam' }]), /requires/);
    assert.throws(() => mod.selectLocalTrackFiles([{ name: 'sample.bam' }, { name: 'other.bam.bai' }]), /does not match/);
    assert.throws(() => mod.selectLocalTrackFiles([{ name: 'sample.bam.bai' }]), /one track/);
    assert.throws(() => mod.selectLocalTrackFiles([{ name: 'a.bed' }, { name: 'b.bed' }]), /one track/);
  }
}
window.parent.document.querySelector = () => { throw Error('Cross-origin'); };
assert.equal(replaceWidget(Original, props), Original);
'''
        result = subprocess.run(["node", "--input-type=module", "-e", script, str(PLUGIN)], cwd=ROOT,
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr[:1500])

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
assert.equal(calls.length,1); assert.equal(calls[0].cache,'force-cache'); assert.equal(calls[0].credentials,'omit');
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

    def test_persistent_cache_preserves_ranges_versions_and_network_fallback(self) -> None:
        script = r'''
import fs from 'node:fs';
import assert from 'node:assert/strict';
const source = fs.readFileSync(process.argv[1], 'utf8');
globalThis.location = { origin: 'https://bted.example', href: 'blob:https://bted.example/adapter' };
const entries = new Map(), calls = [];
const cache = {
  async match(key) { return entries.get(String(key))?.clone(); },
  async put(key, response) { assert.equal(response.status, 200); entries.set(String(key), response.clone()); },
  async keys() { return [...entries.keys()]; },
  async delete(key) { return entries.delete(String(key)); },
};
globalThis.caches = { async open() { return cache; } };
const pinned = 'https://huggingface.co/datasets/liurulong/terminator/resolve/' + 'a'.repeat(40) + '/v0.3.0/';
const url = pinned + 'assemblies/GCF_TEST/reference/reference.fna';
const fallback = '/api/assets/v0.4.0--' + 'b'.repeat(64);
let mode = 'range';
const network = async (input, init = {}) => {
  const request = new Request(input, init); calls.push(request);
  request.signal.throwIfAborted();
  if (request.url.endsWith('/assets/data-release.json')) return Response.json({ releaseVersion: 'v0.4.0',
    assets: { 'assemblies/GCF_TEST/reference/reference.fna': { url, fallback_url: fallback, sha256: 'c'.repeat(64) } } });
  if (mode === 'fallback' && request.url.startsWith('https://huggingface.co')) throw new TypeError('Failed to fetch');
  if (mode === 'missing') return new Response('missing', { status: 404, headers: { 'content-length': '7' } });
  const range = request.headers.get('range');
  const body = range === 'bytes=4-7' ? 'efgh' : 'abcd';
  return new Response(body, { status: range ? 206 : 200, headers: {
    'content-length': mode === 'large' ? '600000' : '4',
    ...(range ? { 'content-range': range === 'bytes=4-7' ? 'bytes 4-7/8' : 'bytes 0-3/8' } : {}),
    'x-bted-sha256': 'c'.repeat(64), 'etag': 'fixed-version',
  } });
};
async function frame(id) {
  globalThis.fetch = network;
  return import('data:text/javascript,' + encodeURIComponent(source + '\n// fresh-frame-' + id));
}
let mod = await frame(1);
let response = await mod.fetchBtedAsset(url, { headers: { Range: 'bytes=0-3' } });
assert.equal(response.status, 206); assert.equal(await response.text(), 'abcd');
assert.equal(calls[0].cache, 'force-cache'); assert.equal(entries.size, 1);
mod = await frame(2); // The same Cache Storage survives a new iframe/worker context.
response = await mod.fetchBtedAsset(new Request(url, { headers: { Range: 'bytes=0-3' } }));
assert.equal(calls.length, 1); assert.equal(response.status, 206);
assert.equal(response.headers.get('content-range'), 'bytes 0-3/8');
assert.equal(response.headers.get('etag'), 'fixed-version'); assert.equal(await response.text(), 'abcd');
assert.equal(response.headers.has('x-bted-cached-status'), false);
response = await mod.fetchBtedAsset(url, { headers: { Range: 'bytes=4-7' } });
assert.equal(await response.text(), 'efgh'); assert.equal(calls.length, 2);
await mod.fetchBtedAsset(url.replace('a'.repeat(40), 'd'.repeat(40)), { headers: { Range: 'bytes=0-3' } });
assert.equal(calls.length, 3); // Different fixed revisions cannot share cached bytes.
const abort = new AbortController(); abort.abort();
await assert.rejects(mod.fetchBtedAsset(url, { signal: abort.signal, headers: { Range: 'bytes=0-3' } }), { name: 'AbortError' });
assert.equal(calls.length, 3);
await mod.fetchBtedAsset(url, { cache: 'no-store', headers: { Range: 'bytes=0-3' } });
assert.equal(calls.length, 4); assert.equal(calls.at(-1).cache, 'no-store');
await mod.fetchBtedAsset(url, { headers: { Range: 'bytes=0-3', 'If-Range': 'fixed-version' } });
assert.equal(calls.length, 5);
mode = 'missing';
for (let i = 0; i < 2; i++) assert.equal((await mod.fetchBtedAsset(url + '.missing')).status, 404);
assert.equal(calls.length, 7);
mode = 'large';
for (let i = 0; i < 2; i++) await mod.fetchBtedAsset(url + '.large');
assert.equal(calls.length, 9);
entries.clear(); mode = 'fallback';
response = await mod.fetchBtedAsset(url, { headers: { Range: 'bytes=0-3' } });
assert.equal(await response.text(), 'abcd'); assert.equal(response.headers.get('x-bted-sha256'), 'c'.repeat(64));
const before = calls.length;
mod = await frame(3);
response = await mod.fetchBtedAsset(url, { headers: { Range: 'bytes=0-3' } });
assert.equal(calls.length, before); assert.equal(response.status, 206); assert.equal(await response.text(), 'abcd');
mode = 'range'; entries.clear();
for (let i = 0; i < 130; i++) await mod.fetchBtedAsset(url + '.' + i);
assert.equal(entries.size, 128);
entries.clear(); calls.length = 0;
const originAsset = 'https://bted.example/api/assets/v0.4.0--' + 'f'.repeat(64);
await mod.fetchBtedAsset(originAsset, { headers: { Range: 'bytes=0-3' } });
await mod.fetchBtedAsset(originAsset, { headers: { Range: 'bytes=0-3' } });
assert.equal(calls.length, 1);
const versionedFile = 'https://bted.example/api/batter/GCF_TEST/files/reference.fa.gz?revision=' + 'e'.repeat(40);
await mod.fetchBtedAsset(versionedFile); await mod.fetchBtedAsset(versionedFile);
assert.equal(calls.length, 2);
const unversioned = versionedFile.split('?')[0];
await mod.fetchBtedAsset(unversioned); await mod.fetchBtedAsset(unversioned);
assert.equal(calls.length, 4); // Mutable routes do not use the persistent data cache.
globalThis.caches.open = async () => { throw Error('Storage disabled'); };
assert.equal((await mod.fetchBtedAsset(url)).status, 200); // Storage failures remain nonfatal.
'''
        result = subprocess.run(["node", "--input-type=module", "-e", script, str(PLUGIN)], cwd=ROOT,
                                capture_output=True, text=True, encoding="utf-8")
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
        for required in ("Study", "Endpoint evidence", "Example paper", "Test Journal"):
            self.assertIn(required, data["content"])
        self.assertNotIn('"Source"', data["content"])
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
