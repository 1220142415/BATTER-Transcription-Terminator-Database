"""Exercise the current genome-page ZIP builder with readable release files."""

from __future__ import annotations

import base64
import io
import json
import subprocess
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const files = {
  'https://bted.example/v0.4.0/genomes/GCF_TEST/metadata.tsv': 'source_id\tpmid\nS1\t123\n',
  'https://bted.example/v0.4.0/genomes/GCF_TEST/studies/PMID_123/endpoints.gff3.gz': 'GFF3-bytes',
};
const worker = process.argv[2] === 'worker';
const assets = Object.keys(files).map((url, index) => ({url, ...(worker ? {fallback_url: `/api/assets/test-${index}`} : {})}));
let clickHandler, archiveBlob, downloadName;
const links = Object.keys(files).map((href, index) => ({
  href,
  dataset: {zipPath: index ? 'GCF_TEST/studies/PMID_123/endpoints.gff3.gz' : 'GCF_TEST/metadata.tsv'},
}));
const button = {disabled: false, addEventListener(event, fn) {if (event === 'click') clickHandler = fn;}};
const status = {textContent: ''};
const frame = {dataset: {config: 'assemblies/GCF_TEST.config.json'}, src: '', closest() {return {closest() {return {append() {}};}};}};
const select = {value: '', addEventListener() {}};
const root = {dataset: {assembly: 'GCF_TEST'}, querySelectorAll(selector) {
  return selector === '[data-package-file][data-zip-path]' ? links : [];
}};
global.window = {location: {search: '', href: 'https://bted.example/genomes/GCF_TEST.html'},
  addEventListener() {}, history: {replaceState() {}}, setTimeout(fn) {fn();}};
global.document = {baseURI: 'https://bted.example/genomes/GCF_TEST.html', body: {append() {}},
  querySelector(selector) {
    return {'[data-genome-page]': root, '[data-browser-frame]': frame,
      '[data-source-select]': select, '[data-download-genome-package]': button,
      '[data-package-status]': status}[selector] || null;
  },
  querySelectorAll() {return [];},
  createElement() {return {dataset: {}, setAttribute() {}, querySelector() {return {attachShadow() {return {append() {}};}};}, click() {downloadName = this.download;}, remove() {}};},
};
global.fetch = async href => {
  href = String(href);
  if (href === 'https://bted.example/assets/data-release.json') return {ok: true, json: async () => ({assets})};
  if (worker) {
    const index = assets.findIndex(asset => `https://bted.example${asset.fallback_url}` === href);
    if (index < 0) throw new Error(`Worker download bypassed same-origin proxy: ${href}`);
    href = assets[index].url;
  }
  if (!(href in files)) return {ok: false, status: 404};
  const value = Buffer.from(files[href]);
  return {ok: true, arrayBuffer: async () => value.buffer.slice(value.byteOffset, value.byteOffset + value.byteLength)};
};
URL.createObjectURL = blob => {archiveBlob = blob; return 'blob:test';};
URL.revokeObjectURL = () => {};
vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8'));
(async () => {
  await clickHandler();
  if (!archiveBlob) throw new Error(status.textContent);
  process.stdout.write(JSON.stringify({archive: Buffer.from(await archiveBlob.arrayBuffer()).toString('base64'), filename: downloadName, status: status.textContent}));
})().catch(error => {console.error(error); process.exitCode = 1;});
"""


class GenomeZipTests(unittest.TestCase):
    def test_genome_zip_contains_only_gff3_and_readable_metadata(self) -> None:
        for mode in ('worker', 'pages'):
            with self.subTest(mode=mode):
                self.check_zip(mode)

    def check_zip(self, mode: str) -> None:
        result = subprocess.run(
            ["node", "-e", HARNESS, str(ROOT / "site/assets/study-download.js"), mode],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        outcome = json.loads(result.stdout)
        self.assertEqual(outcome["filename"], "BTED-v0.4.0-GCF_TEST.zip")
        self.assertIn("2 GFF3 and TSV files", outcome["status"])
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(outcome["archive"]))) as archive:
            self.assertEqual(archive.namelist(), [
                "GCF_TEST/metadata.tsv",
                "GCF_TEST/studies/PMID_123/endpoints.gff3.gz",
            ])
            self.assertEqual(archive.read("GCF_TEST/metadata.tsv"), b"source_id\tpmid\nS1\t123\n")
            self.assertFalse(any(name.endswith((".json", ".bed", ".csv")) for name in archive.namelist()))


if __name__ == "__main__":
    unittest.main()
