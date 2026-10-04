"""Check generated user-facing catalogue copy and controls."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import bted_unified_site as unified
import bted_v05_web as web
import bted_hf_preview as preview

HAN = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')


class CataloguePresentationTests(unittest.TestCase):
    def test_directory_and_redirects_emit_english_controls(self):
        html = unified.directory_page()
        self.assertNotRegex(html, HAN)
        self.assertNotIn('id="batter-sort"', html)
        self.assertEqual(html.count('data-batter-sort='), 4)
        self.assertEqual(html.count('data-taxonomy-rank='), 6)
        for control in ('batter-evidence', 'batter-bigwig', 'batter-retry', 'batter-request-error'):
            self.assertIn('id="' + control + '"', html)
        self.assertIn('No BigWig', html)
        self.assertIn('Not provided', html)
        for path in ('catalog.html', 'genomes/GCF_test.html'):
            self.assertNotRegex(unified.redirect_page(Path(path)), HAN)

    def test_release_and_pending_pages_emit_english(self):
        self.assertEqual(web.RELEASE_DISPLAY_NAME, 'Latest · v5')
        html = '<main><a href="downloads/v0.5.0/missing.gff3">Study GFF3</a></main>'
        manifest = dict(assets={}, experimentalAvailable=False, availableGenomeCount=1, totalGenomeCount=2)
        rendered = preview.present_hf_page(html, manifest, Path('methodology.html'))
        self.assertNotRegex(rendered, HAN)
        self.assertIn('Latest · v5 · 1 / 2 genomes available', rendered)
        self.assertIn('Experimental data preparing', rendered)
        self.assertIn('Study GFF3 · Data preparing', rendered)

    def test_runtime_copy_contains_no_chinese(self):
        self.assertNotRegex((ROOT / 'site/assets/batter-catalog.js').read_text(encoding='utf-8'), HAN)


if __name__ == '__main__':
    unittest.main()
