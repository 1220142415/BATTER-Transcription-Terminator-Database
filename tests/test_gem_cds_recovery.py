import gzip
import hashlib
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from index_gem_ffn import header
from recover_gem_cds import recover
import upload_gem_cds as uploader


class GemCdsTests(unittest.TestCase):
    def test_gff_only_upload_and_legacy_provenance_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); row, member=self.fixture(root)
            archive={'url':'https://example.org/ffn.tar','bytes':4096,'etag':'original','last_modified':'original'}
            result=recover(row,member,archive,'a'*40,root,root/'metadata',True)
            old={'reference_revision':'a'*40,'path_prefix':'v0.5.0/genomes','genomes':{'HISTORICAL':{'keep':'exact'}}}
            entry={k:result[k] for k in ['reference_sha256','matched_reference_contigs',
                'total_reference_contigs','features','source_url','source_annotation_type','file']}
            entry['coverage']='full'
            local=deepcopy(old);local['genomes'][row[0]]=entry
            for name,data in [('pilot-validation.json',{'accepted':True}),('hf-manifest.json',old),
                              ('ffn-index/archive.json',archive),(str(Path('publish')/uploader.MANIFEST_PATH),local)]:
                uploader.save_json(root/name,data)
            state={'manifest':deepcopy(old),'head':'b'*40,'files':{}}
            commits=[]
            def commit(repo,operations,parent_commit,**kwargs):
                self.assertEqual(parent_commit,state['head'])
                commits.append([op.path_in_repo for op in operations])
                for op in operations:
                    self.assertNotIn('provenance.json',op.path_in_repo)
                    if op.path_in_repo==uploader.MANIFEST_PATH:
                        state['manifest']=json.loads(op.path_or_fileobj)
                    else:
                        state['files'][op.path_in_repo]=Path(op.path_or_fileobj).read_bytes()
                state['head']=str(len(commits))*40
                return SimpleNamespace(oid=state['head'])
            def download(repo,path,revision,**kwargs):
                self.assertEqual(revision,state['head'])
                target=root/'remote'/path;target.parent.mkdir(parents=True,exist_ok=True)
                if path==uploader.MANIFEST_PATH:
                    target.write_text(json.dumps(state['manifest']))
                else:
                    target.write_bytes(state['files'][path])
                return str(target)
            def inventory(repo,paths,revision,**kwargs):
                self.assertEqual(revision,state['head'])
                return [SimpleNamespace(path=p,size=len(state['files'][p]),
                    lfs=SimpleNamespace(sha256=uploader.sha(state['files'][p]))) for p in paths if p in state['files']]
            api=Mock();api.repo_info.side_effect=lambda *a,**k:SimpleNamespace(sha=state['head'])
            api.create_commit.side_effect=commit;api.get_paths_info.side_effect=inventory
            with patch.object(uploader,'HfApi',return_value=api),patch.object(uploader,'hf_hub_download',side_effect=download),patch.object(uploader,'set_client_factory'):
                report=uploader.upload(root,available=True)
                self.assertTrue(report['complete'])
                self.assertEqual(commits[0],[uploader.annotation_path(row[0],row[1]),uploader.MANIFEST_PATH])
                self.assertEqual(state['manifest']['genomes']['HISTORICAL'],old['genomes']['HISTORICAL'])
                self.assertEqual(state['manifest']['genomes'][row[0]]['provenance']['source_ffn_sha256'],result['source_ffn_sha256'])
                self.assertEqual(json.loads(Path(report['manifest_snapshot']).read_text()),state['manifest'])
                # Resume a commit made by the old uploader: enrich the manifest,
                # preserve existing GFF3 and never require remote provenance.
                del state['manifest']['genomes'][row[0]]['provenance']
                uploader.upload(root,available=True)
                self.assertEqual(commits[1],[uploader.MANIFEST_PATH])
                state['manifest']['genomes'][row[0]]['features']+=1
                with self.assertRaisesRegex(ValueError,'remote_annotation_conflict'):
                    uploader.upload(root,available=True)

    def test_tar_directory_and_checksum(self):
        directory = tarfile.TarInfo('ffn'); directory.type = tarfile.DIRTYPE
        self.assertEqual(header(directory.tobuf()).name, 'ffn')
        self.assertIsNone(header(b'not a header'.ljust(512, b' ')))

    def fixture(self, root, extra=False, bad=False):
        genome, batch = 'GEM_TEST', '001'
        work = root/'inputs'/genome; work.mkdir(parents=True)
        ffn = gzip.compress(b'>old_1 # 2 # 4 # 1 # ID=1;partial=00\nACG\n'
                            b'>old_2 # 2 # 4 # -1 # ID=2;partial=00\nCGT\n'
                            b'>excluded_1 # 1 # 3 # 1 # ID=3\nTTT\n')
        (work/'original.ffn.gz').write_bytes(ffn)
        (work/'original.fna.gz').write_bytes(gzip.compress(b'>old\nAACGTT\n>excluded\nTTT\n'))
        reference = gzip.compress(b'>display\nAACGTT\n'+(b'>unmatched\nCCCC\n' if extra else b''))
        (work/'reference.fa.gz').write_bytes(reference)
        metadata = root/'metadata'/'genomes'/f'batter-{batch}'/genome/'metadata.json'
        metadata.parent.mkdir(parents=True)
        metadata.write_text(json.dumps({'genome_id':genome,'records':{'batter':{
            'genome_id':genome,'source_collection':'GEM','reference':{'contigs':2 if extra else 1,'bases':10 if extra else 6},
            'files':{'reference.fa.gz':{'bytes':len(reference),'sha256':'0'*64 if bad else hashlib.sha256(reference).hexdigest()}}}}}))
        return [genome,batch,*([None]*7),'no_ncbi_accession'], {'offset':512,'bytes':len(ffn),'member':f'ffn/{genome}.ffn.gz'}

    def test_full_partial_checksum_and_resume(self):
        for partial in [False, True]:
            with self.subTest(partial=partial), tempfile.TemporaryDirectory() as directory:
                root=Path(directory); row, member=self.fixture(root,extra=partial)
                result=recover(row,member,{'url':'https://example.org/ffn.tar'},'a'*40,root,root/'metadata',True)
                self.assertEqual(result['result'],'partial' if partial else 'full')
                self.assertEqual(result['features'],2)
                self.assertEqual(result['omitted_source_cds'],1)
                self.assertEqual(recover(row,member,{'url':'https://example.org/ffn.tar'},'a'*40,root,root/'metadata',True),result)
                (root/'results'/'GEM_TEST.json').unlink()
                self.assertEqual(recover(row,member,{'url':'https://example.org/ffn.tar'},'a'*40,root,root/'metadata',True),result)
                with self.assertRaisesRegex(ValueError,'checkpoint_inputs_changed'):
                    recover(row,member,{'url':'https://example.org/ffn.tar'},'b'*40,root,root/'metadata',True)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); row, member=self.fixture(root,bad=True)
            result=recover(row,member,{},'a'*40,root,root/'metadata',True)
            self.assertEqual(result['result'],'failed')
            self.assertIn('checksum_mismatch',result['reason'])
            self.assertFalse((root/'publish').exists())


if __name__=='__main__':
    unittest.main()
