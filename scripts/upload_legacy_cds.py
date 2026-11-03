"""Incrementally publish verified non-GEM CDS in the existing recovered layout."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

import upload_gem_cds as existing
from huggingface_hub import HfApi, CommitOperationAdd, set_client_factory
from recover_legacy_sources import ROOT, PRIOR, REFERENCE
from prepare_annotation_recovery import annotation_path, MANIFEST_PATH
from annotation_transfer_budget import Budget
from recover_gem_cds import sha, save_json

def snapshot(api):
    parent=api.repo_info(existing.REPO,repo_type='dataset',expand=['sha'],timeout=60).sha
    local=PRIOR/'uploaded'/parent/MANIFEST_PATH
    remote=json.loads(local.read_text()) if local.exists() else existing.manifest_at(parent,ROOT)
    assert remote['reference_revision']==REFERENCE,'HF_reference_changed'
    save_json(ROOT/'hf-head.json',dict(sha=parent))
    target=ROOT/'hf-manifest-before.json'
    if not target.exists():save_json(target,remote)
    print('HF_CURRENT',parent,'manifest_genomes',len(remote['genomes']),flush=True)
    return parent,remote

def publish(snapshot_only=False,verify_only=False):
    budget=Budget(ROOT/'proxy-upload-transfer.jsonl',cap=5_000_000_000)
    set_client_factory(budget.client)
    api=HfApi()
    print('CHECK_WRITE_ACCESS',flush=True)
    api.auth_check(existing.REPO,repo_type='dataset',write=True)
    print('READ_CURRENT_SNAPSHOT',flush=True)
    parent,remote=snapshot(api)
    if snapshot_only:return
    before=json.loads((ROOT/'hf-manifest-before.json').read_text()) if verify_only else deepcopy(remote)
    new={};files={}
    for path in sorted((ROOT/'results').glob('*.json')):
        result=json.loads(path.read_text())
        if result['result'] not in {'full','partial'}:continue
        genome=result['genome_id']
        gate=json.loads((ROOT/(result['route']+'-pilot.json')).read_text())
        assert gate['accepted'] and result['independent_correspondence']=='passed','unverified_source_or_output'
        assert result['reference_revision']==REFERENCE,'reference_changed'
        location=annotation_path(genome,result['batch']);file=ROOT/'publish'/location
        data=file.read_bytes()
        assert len(data)==result['file']['bytes'] and sha(data)==result['file']['sha256'],'verified_output_changed'
        entry={k:result[k] for k in ['reference_sha256','matched_reference_contigs','total_reference_contigs','features','source_url','source_annotation_type','file']}
        entry['coverage']=result['result']
        entry['provenance']={k:result[k] for k in ['source_collection','source_accession','annotation_origin',
            'source_reference_url','processed_at','independent_correspondence'] if k in result}
        for key in ['source_faa_sha256','source_reference_sha256','source_gff_sha256','source_features_sha256','source_gbff_sha256','source_release','protein_translation','bvbrc_genome_id']:
            if key in result:entry['provenance'][key]=result[key]
        if genome in remote['genomes']:
            assert remote['genomes'][genome]==entry,'published_annotation_conflict:'+genome
            if verify_only and genome not in before['genomes']:
                new[genome]=entry;files[genome]=(location,file)
            continue
        if verify_only:continue
        new[genome]=entry;files[genome]=(location,file)
    if not new:
        print('NO_NEW_VERIFIED_FILES',flush=True);return
    # A file without a manifest entry is not safe to overwrite either.
    names=sorted(new)
    for i in ([] if verify_only else range(0,len(names),400)):
        assert not api.get_paths_info(existing.REPO,[files[g][0] for g in names[i:i+400]],repo_type='dataset',revision=parent),'unregistered_remote_file_exists'
    expected=sum(e['file']['bytes'] for e in new.values())
    if not verify_only:assert budget.used+expected*4/3+100_000_000<budget.cap,'proxy_upload_budget_insufficient'
    print('VERIFY_READY' if verify_only else 'UPLOAD_READY',len(new),'genomes','GFF_bytes',expected,flush=True)
    for i in ([] if verify_only else range(0,len(names),400)):
        group=names[i:i+400]
        operations=[CommitOperationAdd(path_in_repo=files[g][0],path_or_fileobj=str(files[g][1])) for g in group]
        for g in group:remote['genomes'][g]=new[g]
        operations.append(CommitOperationAdd(path_in_repo=MANIFEST_PATH,path_or_fileobj=(json.dumps(remote,indent=2)+'\n').encode()))
        commit=api.create_commit(existing.REPO,repo_type='dataset',parent_commit=parent,operations=operations,
            commit_message=f'Add sequence-verified legacy CDS: {len(group)} genomes',
            commit_description='Published exact-reference CDS only. Provenance distinguishes original Almeida, NCBI/archived RefSeq annotation and third-party UHGG Prokka/BV-BRC PATRIC. No new predictions, deletions or reference changes.',num_threads=8)
        record=dict(commit=commit.oid,parent=parent,genomes=group)
        with (ROOT/'upload-commits.jsonl').open('a') as out:out.write(json.dumps(record)+'\n')
        parent=commit.oid
        save_json(ROOT/'upload-state.json',dict(commit=parent,complete=False,uploaded=i+len(group),selected=len(names)))
        print('COMMIT',parent,i+len(group),'/',len(names),flush=True)
    downloaded=existing.manifest_at(parent,ROOT)
    assert downloaded==remote,'uploaded_manifest_differs'
    assert all(downloaded['genomes'][g]==e for g,e in before['genomes'].items()),'historical_recovery_changed'
    verified=0
    for i in range(0,len(names),400):
        batch=names[i:i+400];paths={files[g][0]:g for g in batch}
        found=api.get_paths_info(existing.REPO,list(paths),repo_type='dataset',revision=parent)
        assert len(found)==len(batch),'uploaded_inventory_incomplete'
        for item in found:
            entry=new[paths[item.path]]['file'];assert item.size==entry['bytes'],'remote_size_mismatch'
            if item.lfs:assert item.lfs.sha256==entry['sha256'],'remote_LFS_checksum_mismatch'
            verified+=1
    # Force a real final-SHA readback for each origin, plus full/partial and sizes.
    results={g:json.loads((ROOT/'results'/(g+'.json')).read_text()) for g in names}
    samples=set(names[:1]+sorted(names,key=lambda g:new[g]['file']['bytes'])[-1:])
    for origin in {r['annotation_origin'] for r in results.values()}:
        group=[g for g,r in results.items() if r['annotation_origin']==origin]
        samples.update(group[:2])
    for source in {r['source_collection'] for r in results.values()}:
        samples.add(next(g for g,r in results.items() if r['source_collection']==source))
    samples.update([g for g in names if new[g]['coverage']=='partial'][:3])
    checks=[]
    for g in sorted(samples):
        path=existing.hf_hub_download(existing.REPO,files[g][0],repo_type='dataset',revision=parent,cache_dir=str(ROOT/'hf-verify-cache'),force_download=True)
        data=Path(path).read_bytes();assert len(data)==new[g]['file']['bytes'] and sha(data)==new[g]['file']['sha256'],'remote_sample_mismatch'
        checks.append(dict(genome_id=g,path=files[g][0],bytes=len(data),sha256=sha(data)))
    save_json(ROOT/'uploaded'/parent/MANIFEST_PATH,downloaded)
    report=dict(commit=parent,complete=True,newly_uploaded=len(names),new_genomes=names,
        preserved_existing_entries=len(before['genomes']),manifest_genomes=len(remote['genomes']),remote_inventory_verified=verified,
        downloaded_sha256_samples=checks,gff_bytes=expected,proxy_http_body_bytes=budget.used,per_genome_uploads=['genes.gff3'])
    save_json(ROOT/'upload-state.json',report)
    save_json(ROOT/('upload-verification-'+parent+'.json'),report)
    print('REMOTE_VERIFIED',parent,len(names),'new_genomes',len(checks),'downloaded_samples',flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--snapshot-only',action='store_true')
    parser.add_argument('--verify-only',action='store_true',help='Read back current published additions without uploading.')
    args=parser.parse_args();publish(args.snapshot_only,args.verify_only)
