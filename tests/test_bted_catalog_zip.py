"""Exercise the browser's assembly ZIP code and inspect the resulting archive."""

from __future__ import annotations

import base64
import io
import json
import subprocess
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

NODE_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const releaseBase = 'https://huggingface.co/datasets/liurulong/terminator/resolve/0123456789abcdef0123456789abcdef01234567/v0.3.0';
const fixtures = {
  'assets/data-release.json': JSON.stringify({baseUrl: releaseBase}),
  [`${releaseBase}/assemblies/A/metadata.json`]: JSON.stringify({record_count: 1}),
  [`${releaseBase}/assemblies/A/endpoints.gff3`]: '##gff-version 3\ncontig\tBTED\tendpoint\t1\t1\t.\t+\t.\tID=E1;source_id=S1\n',
  [`${releaseBase}/assemblies/B/metadata.json`]: JSON.stringify({record_count: 0}),
};
const choices = ['A', 'B'].map(value => ({
  value, checked: true, dataset: {records: value === 'A' ? '1' : '0'},
  addEventListener() {},
}));
let clickHandler, zipBlob, downloadName;
const button = {disabled: false, addEventListener(event, fn) {
  if (event === 'click') clickHandler = fn;
}};
const fields = {
  '[data-selected-count]': {textContent: ''},
  '[data-selected-records]': {textContent: ''},
  '[data-download-status]': {textContent: ''},
  '[data-download-selected]': button,
};
global.document = {
  baseURI: 'https://bted.example/sources.html',
  querySelectorAll(selector) { return selector === '[data-download-choice]' ? choices : []; },
  querySelector(selector) { return fields[selector] || null; },
  createElement() { return {click() { downloadName = this.download; }, remove() {}}; },
  body: {appendChild() {}},
};
global.fetch = async url => {
  url = String(url);
  if (!(url in fixtures)) return {ok: false, status: 404};
  const body = fixtures[url];
  const data = Buffer.from(body, 'utf8');
  return {ok: true, json: async () => JSON.parse(body), arrayBuffer: async () => data.buffer.slice(
    data.byteOffset, data.byteOffset + data.byteLength,
  )};
};
URL.createObjectURL = blob => { zipBlob = blob; return 'blob:test'; };
URL.revokeObjectURL = () => {};
vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8'));
(async () => {
  await clickHandler();
  if (!zipBlob) throw new Error(fields['[data-download-status]'].textContent);
  process.stdout.write(JSON.stringify({
    archive: Buffer.from(await zipBlob.arrayBuffer()).toString('base64'),
    filename: downloadName,
    status: fields['[data-download-status]'].textContent,
  }));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""


class CatalogueZipTests(unittest.TestCase):
    def test_archive_contains_gff3_and_metadata_only_when_records_exist(self) -> None:
        result = subprocess.run(
            ["node", "-e", NODE_HARNESS, str(ROOT / "site/assets/site.js")],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        outcome = json.loads(result.stdout)
        self.assertEqual(outcome["filename"], "BTED-v0.3.0-2-assemblies.zip")
        self.assertEqual(outcome["status"], "Packaged 2 genome assemblies.")
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(outcome["archive"]))) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(sorted(archive.namelist()), [
                "A/endpoints.gff3", "A/metadata.json", "B/metadata.json",
            ])
            self.assertEqual(
                archive.read("A/endpoints.gff3"),
                b"##gff-version 3\ncontig\tBTED\tendpoint\t1\t1\t.\t+\t.\tID=E1;source_id=S1\n",
            )
            self.assertFalse(any(name.lower().endswith((".csv", ".tsv", ".bed")) for name in archive.namelist()))
            self.assertEqual(json.loads(archive.read("B/metadata.json"))["record_count"], 0)


if __name__ == "__main__":
    unittest.main()
