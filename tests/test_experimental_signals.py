"""Signal pairs must stay with their verified source, genome and publication."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from experimental_signals import apply_signal_tracks, load_signals, signal_assets


class SignalTests(unittest.TestCase):
    def test_source_mapping_order_and_coverage(self):
        samples, revision = load_signals()
        assets = signal_assets({})
        self.assertEqual(len(assets), 8)
        for sample in samples:
            sid = sample['source_id']
            endpoint = {'trackId': 'endpoint', 'assemblyNames': ['assembly'], 'metadata': {'source_id': sid,
                'btedAbout': {'kind': 'endpoint', 'source_id': sid, 'assembly': sample['genome_id'], 'pmid': sample['pmid']}}}
            other = {'trackId': 'other', 'metadata': {}}
            legacy = {'trackId': 'legacy', 'metadata': {'btedAbout': {'kind': 'signal', 'source_id': sid}}}
            config = {'tracks': [endpoint, other, legacy], 'defaultSession': {'views': [{'tracks': [
                {'configuration': 'endpoint'}, {'configuration': 'other'}, {'configuration': 'legacy'}]}]}}
            sources = {sid: {'assembly': sample['genome_id'], 'pmid': sample['pmid']}}
            apply_signal_tracks(config, sources)
            new = config['tracks'][1]
            self.assertEqual(new['metadata']['btedAbout']['sample_id'], sample['sample_id'])
            self.assertEqual(new['name'], f"PMID {sample['pmid']} · {sample['assay']} · {sample['conditions'].split(';')[0].strip()} · {sample['sample_id']}")
            self.assertEqual(new['displays'][0]['scaleType'], 'linear')
            self.assertEqual(new['displays'][0]['autoscale'], 'local')
            self.assertEqual(config['tracks'][0], endpoint)
            self.assertIn(legacy, config['tracks'])  # Preserve distinct existing coverage.
            visible = [t['configuration'] for t in config['defaultSession']['views'][0]['tracks']]
            self.assertEqual(visible, ['endpoint', new['trackId'], 'other'])
            for adapter in new['adapter']['subadapters']:
                self.assertIn(revision, adapter['bigWigLocation']['uri'])
            snapshot = copy.deepcopy(config)
            apply_signal_tracks(config, sources)
            self.assertEqual(config, snapshot)
            sources[sid]['pmid'] = 'wrong'
            with self.assertRaises(ValueError):
                apply_signal_tracks(config, sources)
        vibrio = samples[-1]
        self.assertEqual(vibrio['reference_contigs'], {'CP009977.1': 3248023})
        self.assertIn('Chromosome 1 only', vibrio['coverage'])


if __name__ == '__main__':
    unittest.main()
