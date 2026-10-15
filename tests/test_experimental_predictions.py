import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from experimental_predictions import load_predictions, prediction_assets, apply_prediction_track, prediction_only_config


class ExperimentalPredictionTests(unittest.TestCase):
    def test_reference_identity_counts_and_track_semantics(self):
        data = load_predictions()
        self.assertEqual(len(data['genomes']), 19)
        self.assertEqual(sum(r['prediction_count'] for r in data['genomes'].values()), 116229)
        self.assertEqual(len(prediction_assets({})), 59)
        for genome, row in data['genomes'].items():
            config = {'assemblies': [{'name': genome, 'sequence': {'adapter': {'fastaLocation': {'uri': row['reference']['source_url']}}}}],
                      'tracks': [{'trackId': 'endpoint'}], 'defaultSession': {'views': [{'tracks': [{'configuration': 'endpoint'}]}]}}
            apply_prediction_track(config, genome)
            track = config['tracks'][-1]
            self.assertEqual(track['metadata']['btedAbout']['kind'], 'prediction')
            self.assertEqual(sum(track['metadata']['btedContigCounts'].values()), row['prediction_count'])
            self.assertNotIn('pmid', track['metadata']['btedAbout'])
            before = copy.deepcopy(config)
            apply_prediction_track(config, genome)
            self.assertEqual(before, config)
            config['assemblies'][0]['sequence']['adapter']['fastaLocation']['uri'] += 'wrong'
            with self.assertRaises(ValueError):
                apply_prediction_track(config, genome)
        standalone = prediction_only_config('GCF_000005845.2')
        self.assertEqual(standalone['defaultSession']['views'][0]['displayedRegions'][0]['refName'], 'NC_000913.3')
        self.assertEqual(len(standalone['tracks']), 1)


if __name__ == '__main__':
    unittest.main()
