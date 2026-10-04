import copy
import hashlib
import sys
import unittest
import json
import tempfile
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import bted_hf_preview as preview
import bted_hf_relay as relay
import bted_v05_web as web
import serve_bted_hf_preview as server


def fixture():
    payload, genomes = [], []
    for n in range(1000):
        genome = str(2228664000 + n)
        files = {}
        for name in preview.FILES[:5]:
            relative = 'genomes/' + genome + '/' + name
            payload.append(dict(name=relative, bytes=128, sha256='d' * 64))
            files[name] = dict(logical_path='batter/batches/000/' + relative, byte_size=128, sha256='d' * 64)
        genomes.append(dict(genome_id=genome, batch='000', reference_contigs=[dict(seqid='contig', length_bp=100)], files=files))
    e = dict(group='batter-000', batch='000', upload_id='a' * 32, manifest_sha256=hashlib.sha256(relay.manifest_text(payload).encode()).hexdigest(),
             archive_sha256='b' * 64, release_manifest_sha256=relay.RELEASE_SHA, hf_repo=relay.REPO,
             hf_destination_prefix='v0.5.0/batter/batches/000/', genome_count=1000, payload_file_count=len(payload))
    proof = dict(e, status='complete', hf_branch=relay.BRANCH, hf_revision='c' * 40, hf_sha256_verified=True, hf_file_count=len(payload))
    return dict(schema='bted-hf-preview-v1', release_version=preview.VERSION, hf_repo=relay.REPO,
                release_manifest_sha256=relay.RELEASE_SHA, groups=[dict(envelope=e, receipt=proof, payload=payload)],
                genomes=genomes, available_genomes=1000, total_genomes=42904)


class PreviewProofTests(unittest.TestCase):
    def test_verified_batch_and_numeric_ids(self):
        self.assertEqual(preview.validate_snapshot(fixture())['batter-000']['revision'], 'c' * 40)

    def test_wrong_receipt_identity_and_unverified_commit_rejected(self):
        for key, value in [('upload_id', 'e' * 32), ('hf_revision', 'main'), ('hf_sha256_verified', False),
                           ('hf_file_count', 1), ('release_manifest_sha256', 'f' * 64), ('hf_branch', 'main'), ('status', 'publishing')]:
            with self.subTest(key=key):
                data = fixture()
                data['groups'][0]['receipt'][key] = value
                with self.assertRaises(ValueError): preview.validate_snapshot(data)

    def test_changed_inventory_and_forged_asset_rejected(self):
        data = fixture()
        data['groups'][0]['payload'][0]['sha256'] = 'e' * 64
        with self.assertRaises(ValueError): preview.validate_snapshot(data)
        data = fixture()
        data['genomes'][0]['files']['reference.fa.gz']['logical_path'] = 'batter/batches/001/genomes/secret/reference.fa.gz'
        with self.assertRaises(ValueError): preview.validate_snapshot(data)

    def test_incomplete_or_duplicate_batch_rejected(self):
        data = fixture()
        data['genomes'].pop()
        data['available_genomes'] -= 1
        with self.assertRaises(ValueError): preview.validate_snapshot(data)
        data = fixture()
        data['groups'].append(copy.deepcopy(data['groups'][0]))
        with self.assertRaises(ValueError): preview.validate_snapshot(data)

    def test_unreceipted_genome_rejected(self):
        data = fixture()
        data['genomes'][0]['batch'] = '001'
        with self.assertRaises(ValueError): preview.validate_snapshot(data)

    def test_v5_local_addresses_can_be_rebuilt_at_a_fixed_commit(self):
        path = 'experimental/genomes/GCF_000009765.2/reference.fa.gz'
        self.assertEqual(web.map_url('/downloads/v0.5.0/' + path, {}, 'c' * 40), web.data_url(path, 'c' * 40))
        with self.assertRaises(ValueError): web.map_url('downloads/v0.5.0/' + path, {}, 'main')

    def test_partial_receipts_cannot_become_full_release_proof(self):
        for proof in (None, {}, dict(status='complete', hf_repo=relay.REPO, hf_revision='c' * 40,
                                    hf_sha256_verified=True, hf_file_count=371963, genome_count=42904)):
            with self.subTest(proof=proof):
                data = fixture()
                data['complete_release_proof'] = proof
                with self.assertRaises(ValueError): preview.validate_snapshot(data)

    def test_failed_activation_preserves_previous_snapshot(self):
        temporary_root = Path(__file__).resolve().parents[1] / 'tmp'
        temporary_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as folder:
            root = Path(folder)
            candidate = root / 'candidate'
            (candidate / 'site/assets').mkdir(parents=True)
            manifest = dict(releaseManifestSha256=relay.RELEASE_SHA, batterBrowser=dict(preparedGenomeIds=['genome']))
            (candidate / 'site/assets/data-release.json').write_text(json.dumps(manifest))
            pointer = root / 'current.json'
            previous = b'{"backend":"http://127.0.0.1:8796","available_genomes":1000}'
            pointer.write_bytes(previous)
            detail = {'data': {'batter': {'downloads': [{'filename': 'reference.fa.gz.fai', 'url': 'http://127.0.0.1:8888/api/test', 'byte_size': 128, 'sha256': 'd'*64}]}}}
            with patch.object(server, 'get_json', side_effect=[manifest, {'release': {'canonical_manifest_sha256': relay.RELEASE_SHA}}, detail]), patch.object(server.urllib.request, 'urlopen', side_effect=OSError('HF unavailable')):
                with self.assertRaises(OSError): server.activate(candidate, 'http://127.0.0.1:8888', pointer)
            self.assertEqual(pointer.read_bytes(), previous)
            self.assertFalse((candidate / 'activation.acceptance.json').exists())

    def test_legacy_pages_do_not_offer_unverified_zip_or_static_browser_config(self):
        html = '<main><iframe data-browser-frame data-config="assemblies/GCF_test.config.json"></iframe><a href="../jbrowse/index.html?config=assemblies%2FGCF_test.config.json">Open browser</a><a data-package-file href="../downloads/v0.5.0/experimental/file.gff3.gz">Study GFF3</a><button data-download-genome-package>ZIP</button></main>'
        manifest = dict(assets={}, batterBrowser=dict(preparedGenomeIds=['GCF_test']), experimentalAvailable=False, availableGenomeCount=1000, totalGenomeCount=42904)
        prepared = preview.present_hf_page(html, manifest, Path('genomes/GCF_test.html'))
        self.assertIn('data-config="/api/genomes/GCF_test/jbrowse-config"', prepared)
        self.assertNotIn('data-download-genome-package', prepared)
        self.assertNotIn('data-package-file', prepared)
        self.assertNotIn('assemblies/', prepared)
        self.assertIn('Experimental data preparing', prepared)
        manifest['batterBrowser']['preparedGenomeIds'] = []
        unavailable = preview.present_hf_page(html, manifest, Path('genomes/GCF_test.html'))
        self.assertNotIn('data-browser-frame', unavailable)
        self.assertNotIn('jbrowse/index.html?', unavailable)


if __name__ == '__main__': unittest.main()
