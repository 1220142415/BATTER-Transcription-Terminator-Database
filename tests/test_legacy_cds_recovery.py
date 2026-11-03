"""Exact-reference recovery rejects coordinate/translation mismatches."""
import gzip
import json
import hashlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from copy import deepcopy

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import recover_legacy_sources as recovery
sys.path.insert(0,str(recovery.ROOT/'python-deps'))

@unittest.skipUnless(importlib.util.find_spec('Bio'),'Biopython needed for legacy annotation parsing')
class LegacyCdsTests(unittest.TestCase):
    def test_registration_updates_existing_storage_without_cloning(self):
        import sqlite3
        import prepare_legacy_cds_registration as registration
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);repo=root/'repo';commit='c'*40;oldsha='765f663d12e49b06721ca03aecc7d1c64daa78cb'
            summary=dict(total=1,available=0,counts={'annotation':{'Available':0,'Missing':1}})
            old=dict(version='oldalias',annotation_revision=oldsha,reference_revision=registration.REFERENCE,
                summary=dict(summary,storage_version=registration.STORAGE))
            recovery.gem.save_json(repo/'data/registry/genome-directory.json',old)
            recovery.gem.save_json(repo/'dist/worker-site/assets/genome-browsers.json',{'annotation_recovery':{}})
            entry=dict(coverage='full',matched_reference_contigs=1,total_reference_contigs=1)
            recovery.gem.save_json(root/'upload-state.json',dict(complete=True,commit=commit))
            recovery.gem.save_json(root/'hf-manifest-before.json',dict(annotation_revision=oldsha,genomes={}))
            recovery.gem.save_json(root/'uploaded'/commit/registration.MANIFEST_PATH,
                dict(reference_revision=registration.REFERENCE,genomes={'TEST':entry}))
            recovery.gem.save_json(root/'results/TEST.json',dict(independent_correspondence='passed',source_collection='NCBI-SAG'))
            snapshot=root/'source.sqlite';db=sqlite3.connect(snapshot)
            db.executescript('CREATE TABLE hf_directory_releases(version TEXT PRIMARY KEY,reference_revision TEXT,annotation_revision TEXT,summary_json TEXT,status TEXT);'
                'CREATE TABLE bted_collections(collection TEXT,version TEXT);'
                'CREATE TABLE hf_directory_genomes(version TEXT,genome_id TEXT,source TEXT,annotation TEXT,contigs INT,recovered_matched INT,recovered_total INT,recovered_coverage TEXT,search_text TEXT,UNIQUE(version,genome_id));')
            db.execute('INSERT INTO bted_collections VALUES(?,?)',('gem',registration.GEM))
            for version in [registration.GEM,registration.STORAGE]:
                db.execute('INSERT INTO hf_directory_releases VALUES(?,?,?,?,?)',(version,registration.REFERENCE,oldsha,json.dumps(summary),'ready'))
                db.execute('INSERT INTO hf_directory_genomes VALUES(?,?,?,?,?,?,?,?,?)',(version,'TEST','NCBI GenBank','Missing',1 if version==registration.GEM else None,None,None,None,'preserve search'))
            db.commit();db.close()
            with patch.object(registration,'ROOT',root),patch.object(registration,'REPO',repo),patch.object(registration,'legacy_binding_version',return_value='newalias'):
                registration.prepare(snapshot)
            db=sqlite3.connect(root/'website'/commit/'verified.sqlite')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM hf_directory_genomes').fetchone()[0],2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM hf_directory_genomes WHERE annotation=\'Available\' AND search_text=\'preserve search\'').fetchone()[0],2)
            self.assertEqual(db.execute('SELECT version FROM bted_collections').fetchone()[0],registration.GEM)
            db.close()

    def test_bvbrc_original_coordinates_require_published_sequence_checksums(self):
        item=dict(genome_id='1.1',assembly_accession='GCA_TEST.1',contigs=1,genome_length=9,refseq_cds=1)
        sequences=[dict(accession='old',sequence='TTATTTCAC')]
        feature=dict(accession='old',start=1,end=9,strand='-',segments=['complement(1..9)'],
            na_length=9,na_sequence_md5=hashlib.md5(b'GTGAAATAA').hexdigest(),
            aa_sequence_md5=hashlib.md5(b'MK').hexdigest(),feature_id='RefSeq.original')
        with tempfile.TemporaryDirectory() as tmp,patch.object(recovery,'json_body',side_effect=[json.dumps(sequences).encode(),json.dumps([feature]).encode()]),patch.object(recovery,'reference',return_value=({'new':b'TTATTTCAC'},'verified')):
            raw,_,_,info=recovery.bvbrc(['TEST','001'],Path(tmp),{'TEST':[item]})
            self.assertIn(b'new\tBV-BRC_RefSeq\tCDS\t1\t9\t.\t-\t0',raw)
            self.assertEqual(info['annotation_origin'],'archived_primary_database_annotation')
        bad_protein=dict(feature,aa_sequence_md5='wrong')
        both=dict(item,patric_cds=1)
        bodies=[json.dumps(x).encode() for x in [sequences,[bad_protein],sequences,[feature]]]
        with tempfile.TemporaryDirectory() as tmp,patch.object(recovery,'json_body',side_effect=bodies),patch.object(recovery,'reference',return_value=({'new':b'TTATTTCAC'},'verified')):
            raw,_,_,info=recovery.bvbrc(['TEST','001'],Path(tmp),{'TEST':[both]})
            self.assertEqual(info['annotation_origin'],'third_party_reannotation')
            self.assertEqual(info['source_annotation_type'],'published_BVBRC_PATRIC_CDS')
        # RAST explicitly masks an ambiguous codon to X, although GGN always
        # translates to G. Only a published matching protein checksum passes.
        ambiguous=[dict(accession='old',sequence='ATGGGNTAA')]
        masked=dict(feature,start=1,end=9,strand='+',segments=['1..9'],
            na_sequence_md5=hashlib.md5(b'ATGGGNTAA').hexdigest(),
            aa_sequence_md5=hashlib.md5(b'MX').hexdigest())
        with tempfile.TemporaryDirectory() as tmp,patch.object(recovery,'json_body',side_effect=[json.dumps(ambiguous).encode(),json.dumps([masked]).encode()]),patch.object(recovery,'reference',return_value=({'new':b'ATGGGNTAA'},'verified')):
            raw,_,_,_=recovery.bvbrc(['TEST','001'],Path(tmp),{'TEST':[item]})
            self.assertIn(b'\t+\t0\t',raw)
        feature['na_sequence_md5']='wrong'
        with tempfile.TemporaryDirectory() as tmp,patch.object(recovery,'json_body',side_effect=[json.dumps(sequences).encode(),json.dumps([feature]).encode()]),patch.object(recovery,'reference',return_value=({'new':b'TTATTTCAC'},'verified')):
            with self.assertRaisesRegex(ValueError,'published_CDS_md5_mismatch'):
                recovery.bvbrc(['TEST','001'],Path(tmp),{'TEST':[item]})

    def test_upload_adds_gff_only_and_preserves_history(self):
        import upload_legacy_cds as uploader
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);raw=b'##gff-version 3\nref\tNCBI\tCDS\t1\t9\t.\t+\t0\tID=gene1\n'
            result=dict(genome_id='TEST',batch='001',result='full',route='ncbi',
                reference_revision=uploader.REFERENCE,independent_correspondence='passed',
                reference_sha256='reference',matched_reference_contigs=1,total_reference_contigs=1,
                features=1,source_url='https://example.org/original.gff',source_annotation_type='published_NCBI_GFF3',
                source_collection='NCBI GenBank',source_accession='TEST',annotation_origin='primary_database_annotation',
                processed_at='test',file=dict(bytes=len(raw),sha256=uploader.sha(raw)))
            uploader.save_json(root/'results/TEST.json',result)
            uploader.save_json(root/'ncbi-pilot.json',dict(accepted=True))
            path=uploader.annotation_path('TEST','001');file=root/'publish'/path
            file.parent.mkdir(parents=True);file.write_bytes(raw)
            original=dict(reference_revision=uploader.REFERENCE,path_prefix='v0.5.0/genomes',genomes={'HISTORICAL':{'unchanged':True}})
            state=dict(manifest=deepcopy(original),sha='a'*40,files={});commits=[]
            from unittest.mock import Mock
            api=Mock();api.repo_info.side_effect=lambda *a,**kw:SimpleNamespace(sha=state['sha'])
            def commit(repo,operations,parent_commit,**kw):
                self.assertEqual(parent_commit,state['sha']);commits.append([op.path_in_repo for op in operations])
                for op in operations:
                    self.assertNotIn('provenance.json',op.path_in_repo)
                    if op.path_in_repo==uploader.MANIFEST_PATH:state['manifest']=json.loads(op.path_or_fileobj)
                    else:state['files'][op.path_in_repo]=Path(op.path_or_fileobj).read_bytes()
                state['sha']='b'*40;return SimpleNamespace(oid=state['sha'])
            def inventory(repo,paths,**kw):
                return [SimpleNamespace(path=p,size=len(state['files'][p]),lfs=SimpleNamespace(sha256=uploader.sha(state['files'][p]))) for p in paths if p in state['files']]
            api.create_commit.side_effect=commit;api.get_paths_info.side_effect=inventory
            with patch.object(uploader,'ROOT',root),patch.object(uploader,'PRIOR',root/'prior'),patch.object(uploader,'HfApi',return_value=api),patch.object(uploader,'set_client_factory'),patch.object(uploader.existing,'manifest_at',side_effect=lambda *a:deepcopy(state['manifest'])),patch.object(uploader.existing,'hf_hub_download',return_value=str(file)):
                uploader.publish()
                self.assertEqual(commits,[[path,uploader.MANIFEST_PATH]])
                self.assertEqual(state['manifest']['genomes']['HISTORICAL'],original['genomes']['HISTORICAL'])
                uploader.publish() # A verified repeat must not upload anything.
                self.assertEqual(len(commits),1)
                uploader.publish(verify_only=True)
                self.assertEqual(len(commits),1)
                self.assertTrue(json.loads((root/'upload-state.json').read_text())['complete'])

    def test_reverse_partial_start_and_translation_rejection(self):
        # Reverse CDS: original GTG start is translated as initiating M. The left
        # partial bit must not be mistaken for an incomplete protein N terminus.
        dna=gzip.compress(b'>old\nTTATTTCAC\n')
        faa=gzip.compress(b'>old_1 # 1 # 9 # -1 # ID=1_1;partial=10;start_type=GTG\nMK*\n')
        row=['TEST','001']
        with tempfile.TemporaryDirectory() as tmp, patch.object(recovery,'get',side_effect=[dna,faa]), patch.object(recovery,'reference',return_value=({'new':b'TTATTTCAC'},'verified')):
            raw,ref,mapping,info=recovery.almeida(row,Path(tmp),{'TEST':'UMGS1'})
            self.assertIn(b'new\tProdigal\tCDS\t1\t9\t.\t-\t0',raw)
            self.assertEqual(mapping,{'old':'new'})
            self.assertEqual(info['protein_translation'],'all_retained_CDS_passed_table_11')
        bad=gzip.compress(b'>old_1 # 1 # 9 # -1 # ID=1_1;partial=10;start_type=GTG\nMR*\n')
        with tempfile.TemporaryDirectory() as tmp, patch.object(recovery,'get',side_effect=[dna,bad]), patch.object(recovery,'reference',return_value=({'new':b'TTATTTCAC'},'verified')):
            with self.assertRaisesRegex(AssertionError,'protein_translation_mismatch'):
                recovery.almeida(row,Path(tmp),{'TEST':'UMGS1'})

    def test_partial_gff_retains_only_identical_contigs(self):
        gff=b'##gff-version 3\nold\tNCBI\tCDS\t1\t9\t.\t+\t0\tID=cds1\nother\tNCBI\tCDS\t1\t9\t.\t-\t0\tID=cds2\n'
        raw,mapping,count,omitted=recovery.gff_verified(gff,{'new':b'ATGAAATAA','missing':b'GGGGGGGGG'},
            {'old':b'ATGAAATAA','other':b'CCCCCCCCC'})
        self.assertEqual((mapping,count,omitted),({'old':'new'},1,1))
        self.assertNotIn(b'ID=cds2',raw)
        with self.assertRaisesRegex(ValueError,'outside_reference'):
            recovery.gff_verified(gff.replace(b'\t1\t9\t',b'\t1\t99\t'),{'new':b'ATGAAATAA'},{'old':b'ATGAAATAA'})

    def test_gbff_cds_sequence_and_strand(self):
        from Bio.Seq import Seq
        from Bio.SeqRecord import SeqRecord
        from Bio.SeqFeature import SeqFeature,SimpleLocation
        from Bio import SeqIO
        import io
        record=SeqRecord(Seq('TTATTTCAT'),id='old',name='old',description='published')
        record.annotations['molecule_type']='DNA'
        record.features=[SeqFeature(SimpleLocation(0,9,strand=-1),type='CDS',qualifiers={'locus_tag':['gene1'],'codon_start':['1']})]
        out=io.StringIO();SeqIO.write(record,out,'genbank');data=gzip.compress(out.getvalue().encode())
        with tempfile.TemporaryDirectory() as tmp, patch.object(recovery,'reference',return_value=({'new':b'TTATTTCAT'},'verified')):
            raw,_,_,info=recovery.gbff(['TEST','001'],Path(tmp),data,'https://example.org/original.gbff.gz','TEST','official pair')
            self.assertIn(b'new\tNCBI_GBFF\tCDS\t1\t9\t.\t-\t0',raw)
            self.assertEqual(info['features'],1)

if __name__=='__main__':unittest.main()
