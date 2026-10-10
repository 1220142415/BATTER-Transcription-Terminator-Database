"""Exercise the genome page share bridge without a real JBrowse network request."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const listeners = {};
const posted = [];
const root = {dataset:{assembly:'GCF_TEST'}};
const frameWindow = {postMessage(message, target){posted.push({message,target});}};
const frame = {dataset:{config:'assemblies/GCF_TEST.config.json'},contentWindow:frameWindow,src:''};
const button = {disabled:true,addEventListener(type,fn){this[type]=fn;}};
const status = {textContent:''};
const manual = {hidden:true,value:'',focus(){},select(){}};
const browserStatus = {textContent:''};
const retry = {addEventListener(type,fn){this[type]=fn;}};
const timers = new Map();let timerNumber=0;
const elements = {'[data-genome-page]':root,'[data-browser-frame]':frame,'[data-share-view]':button,'[data-share-status]':status,'[data-share-manual]':manual,'[data-browser-status]':browserStatus,'[data-retry-browser]':retry};
global.document = {baseURI:'https://bted.example/genomes/GCF_TEST.html',querySelector(key){return elements[key]||null;},querySelectorAll(){return [];}};
let url = process.argv[2];
global.window = {location:{get href(){return url;},get search(){return new URL(url).search;},get origin(){return new URL(url).origin;}},addEventListener(type,fn){listeners[type]=fn;},history:{replaceState(_a,_b,next){url=String(next);}},setTimeout(fn){timers.set(++timerNumber,fn);return timerNumber;},clearTimeout(id){timers.delete(id);}};
let copied = '';
let clipboardFails = false;
Object.defineProperty(global,'navigator',{value:{clipboard:{async writeText(text){if(clipboardFails)throw Error('denied');copied=text;}}},configurable:true});
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
const nonce = new URL(frame.src).searchParams.get('bted_bridge');
async function receive(type, id='', details={}){
  await listeners.message({origin:'https://bted.example',source:frameWindow,data:{channel:'bted-browser-v1',nonce,type,id,...details}});
}
(async()=>{
  await receive('ready');
  const restore = posted.find(row=>row.message.type==='restore')?.message;
  if(restore)await receive('restored',restore.id);
  button.click();
  const first=posted.findLast(row=>row.message.type==='capture').message;
  const state={version:1,ref:'CP009124.1',center:70000,zoom:2,reversed:true,tracks:[{id:'source_A',height:44}]};
  await receive('captured',first.id,{state});
  const successful={copied,restore,status:status.textContent,frame:frame.src};
  clipboardFails=true;
  button.click();
  const second=posted.findLast(row=>row.message.type==='capture').message;
  await receive('captured',second.id,{state});
  const fallback={status:status.textContent,manual:manual.value,visible:!manual.hidden};
  const readyStatus=browserStatus.textContent;
  retry.click();
  const retryNonce=new URL(frame.src).searchParams.get('bted_bridge');
  await receive('ready'); // A reply from the old frame must not enable sharing.
  const staleReplyIgnored=button.disabled;
  [...timers.values()][0]();
  const timeoutStatus=browserStatus.textContent;
  await listeners.message({origin:'https://bted.example',source:frameWindow,data:{channel:'bted-browser-v1',nonce:retryNonce,type:'error',message:'Reference unavailable'}});
  process.stdout.write(JSON.stringify({successful,fallback,readyStatus,retry:{newNonce:retryNonce!==nonce,staleReplyIgnored,timeoutStatus,errorStatus:browserStatus.textContent}}));
})().catch(error=>{console.error(error);process.exitCode=1;});
"""


class BtedShareTests(unittest.TestCase):
    def test_share_restore_and_clipboard_fallback(self) -> None:
        url = (
            "https://bted.example/genomes/GCF_TEST.html?view=1&ref=CP009124.1"
            "&center=70000&zoom=2&rev=1&tracks=source_A%3A44&session=local-old"
        )
        result = subprocess.run(
            ["node", "-e", HARNESS, str(ROOT / "site/assets/genome-page.js"), url],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr[:1000])
        data = json.loads(result.stdout)
        restored = data["successful"]["restore"]
        self.assertEqual(restored["state"]["center"], 70000)
        self.assertEqual(restored["state"]["tracks"], [{"id": "source_A", "height": 44}])
        self.assertNotIn("tracks=source_A", data["successful"]["frame"])
        self.assertNotIn("session=local", data["successful"]["frame"])
        self.assertIn("center=70000", data["successful"]["copied"])
        self.assertIn("tracks=source_A%3A44", data["successful"]["copied"])
        self.assertNotIn("session=local", data["successful"]["copied"])
        self.assertTrue(data["fallback"]["visible"])
        self.assertEqual(data["fallback"]["manual"], data["successful"]["copied"])
        self.assertEqual(data["readyStatus"], "")
        self.assertTrue(data["retry"]["newNonce"])
        self.assertTrue(data["retry"]["staleReplyIgnored"])
        self.assertIn("Reload", data["retry"]["timeoutStatus"])
        self.assertIn("Reference unavailable", data["retry"]["errorStatus"])


if __name__ == "__main__":
    unittest.main()
