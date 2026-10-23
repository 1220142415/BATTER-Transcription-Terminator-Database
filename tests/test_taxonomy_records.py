"""Exact-assembly classification does not borrow lineage from another record."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from prepare_taxonomy_d1 import ncbi_record


class TaxonomyRecordsTests(unittest.TestCase):
    def test_newer_accession_does_not_resolve_old_assembly(self):
        row = ncbi_record('GCF_000005845.1', {'reports': [{'accession':'GCF_000005845.2'}]}, None, '2026-10-22')
        self.assertEqual(row['status'], 'pending')
        self.assertIsNone(row['tax_id'])
        self.assertEqual(row['species'], '')

    def test_rank_names_come_only_from_the_matched_taxid(self):
        assembly = {'reports':[{'accession':'GCF_123.1','organism':{'tax_id':123,'organism_name':'Study identity'}}]}
        taxonomy = {'reports':[{'taxonomy':{'tax_id':123,'rank':'SPECIES','current_scientific_name':{'name':'NCBI species'},
            'classification':{'domain':{'name':'Bacteria'},'phylum':{'name':'NCBI phylum'}}}}]}
        row = ncbi_record('GCF_123.1',assembly,taxonomy,'2026-10-22')
        self.assertEqual(row['species'],'NCBI species')
        self.assertEqual(row['phylum'],'NCBI phylum')
        self.assertEqual(row['genus'],'')
        self.assertEqual(row['taxonomy_version'],'')
        self.assertEqual(row['matched_accession'],'GCF_123.1')
        taxonomy['reports'][0]['taxonomy']['tax_id']=456
        with self.assertRaises(AssertionError):
            ncbi_record('GCF_123.1',assembly,taxonomy,'2026-10-22')


if __name__ == '__main__':
    unittest.main()
