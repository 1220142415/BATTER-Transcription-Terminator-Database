import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from align_experimental_gem_taxonomy import RANKS, align


class GemTaxonomyTests(unittest.TestCase):
    def test_requires_exact_assembly_and_preserves_reference_identity(self):
        rows = [dict(assembly=accession, reference_strain='MG1655', taxid='511145',
                     **{rank: 'NCBI value' for rank in RANKS})
                for accession in ('GCF_000005845.2', 'GCF_000005845.1', 'GCF_999999999.1')]
        members = [dict(genome_id='GCF_000005845.2', otu_id='OTU-1')]
        taxonomy = [dict(otu_id='OTU-1', t_phylum='Proteobacteria', t_genus='Escherichia', t_species='NULL')]
        result = align(rows, members, taxonomy)
        self.assertEqual(result[0]['phylum'], 'Proteobacteria')
        self.assertEqual(result[0]['species'], '')
        self.assertEqual(result[0]['taxonomy_status'], 'exact_accession')
        for row in result[1:]:
            self.assertEqual(row['taxonomy_status'], 'not_in_gem')
            self.assertTrue(all(row[rank] == '' for rank in RANKS))
        for original, row in zip(rows, result):
            for key in ('assembly', 'reference_strain', 'taxid'):
                self.assertEqual(row[key], original[key])


if __name__ == '__main__':
    unittest.main()
