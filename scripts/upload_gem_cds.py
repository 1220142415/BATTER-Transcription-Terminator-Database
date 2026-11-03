"""Publish only verified GEM additions, merging every existing recovery record.

Commits add GFF3 files and compact provenance in the existing merged manifest.
Full per-genome provenance stays local. Commits are guarded by parent SHA and
resumable from the remote manifest; no reference or prediction files are changed.
"""
import argparse
import json
import os
from pathlib import Path

# Keep uploads/downloads on the official Python HTTP path so the quota meter
# also includes file bodies (the optional native Xet transport bypasses hooks).
os.environ['HF_HUB_DISABLE_XET'] = '1'
from huggingface_hub import HfApi, CommitOperationAdd, hf_hub_download, set_client_factory

from annotation_transfer_budget import Budget
from prepare_annotation_recovery import annotation_path, MANIFEST_PATH
from recover_gem_cds import sha, save_json

REPO = 'liurulong/terminator'
PROVENANCE_KEYS = ['source_ffn_sha256', 'source_reference_sha256',
                   'source_reference_url', 'archive_member', 'processed_at',
                   'independent_correspondence']


def manifest_at(revision, root):
    file = hf_hub_download(REPO, MANIFEST_PATH, repo_type='dataset', revision=revision,
                           cache_dir=str(root/'hf-cache'))
    return json.loads(Path(file).read_text())


def upload(root, per_commit=200, pilot=False, available=False):
    # Recovery remains active. Keep its append stream separate; two processes
    # writing the previous shared JSONL produced fragmented records. Reserve
    # 2 GB of the original 20 GB allowance for recovery, cleanup and prior probes.
    budget = Budget(root/'proxy-upload-transfer.jsonl', cap=18_000_000_000)
    set_client_factory(budget.client)
    api = HfApi()
    api.auth_check(REPO,repo_type='dataset',write=True)
    gate = json.loads((root/'pilot-validation.json').read_text())
    if not gate['accepted']:
        raise ValueError('pilot_not_accepted')
    if not pilot and not available:
        batch = json.loads((root/'batch-report.json').read_text())
        if not batch['complete'] or batch['attempted'] != batch['target_genomes']:
            raise ValueError('batch_not_finished')
    old = json.loads((root/'hf-manifest.json').read_text())
    local = json.loads((root/'publish'/MANIFEST_PATH).read_text())
    if available:
        # Consume only atomically completed verification records; recovery may
        # keep processing other genomes while this fixed subset is published.
        local=json.loads(json.dumps(old))
        for path in (root/'results').glob('*.json'):
            result=json.loads(path.read_text())
            if result['result'] not in {'full','partial'}:
                continue
            entry={k:result[k] for k in ['reference_sha256','matched_reference_contigs',
                'total_reference_contigs','features','source_url','source_annotation_type','file']}
            entry['coverage']=result['result']
            local['genomes'][result['genome_id']]=entry
    for genome, entry in old['genomes'].items():
        if local['genomes'].get(genome) != entry:
            raise ValueError('historical_entry_would_change:'+genome)
    new = {g:e for g,e in local['genomes'].items() if g not in old['genomes']}
    if pilot:
        selected = set(json.loads((root/'pilot-genomes.json').read_text()))
        new = {g:e for g,e in new.items() if g in selected}
    rows = {}
    archive = json.loads((root/'ffn-index/archive.json').read_text())
    archive = {k: archive[k] for k in ['url','bytes','etag','last_modified']}
    for genome, entry in new.items():
        result = json.loads((root/'results'/f'{genome}.json').read_text())
        if result['result'] not in {'full','partial'} or result['independent_correspondence'] != 'passed':
            raise ValueError('unverified_result:'+genome)
        if result['reference_revision'] != local['reference_revision'] or any(result['archive'][k] != v for k,v in archive.items()):
            raise ValueError('verified_input_revision_mismatch:'+genome)
        path = annotation_path(genome,result['batch'])
        gff = root/'publish'/path
        raw = gff.read_bytes()
        if len(raw) != entry['file']['bytes'] or sha(raw) != entry['file']['sha256']:
            raise ValueError('output_checksum_mismatch:'+genome)
        if json.loads(gff.with_name('provenance.json').read_text()) != result:
            raise ValueError('provenance_mismatch:'+genome)
        entry['provenance'] = {k: result[k] for k in PROVENANCE_KEYS}
        rows[genome] = (path,gff)
    parent = api.repo_info(REPO,repo_type='dataset').sha
    remote = manifest_at(parent,root)
    if remote['reference_revision'] != local['reference_revision'] or remote['path_prefix'] != local['path_prefix']:
        raise ValueError('remote_reference_or_layout_changed')
    for genome, entry in old['genomes'].items():
        if remote['genomes'].get(genome) != entry:
            raise ValueError('historical_remote_entry_changed:'+genome)
    if remote.get('gem_prodigal_archive',archive) != archive:
        raise ValueError('remote_source_archive_changed')
    manifest_changed = remote.get('gem_prodigal_archive') != archive
    remote['gem_prodigal_archive'] = archive
    pending=[]
    for genome, entry in new.items():
        if genome in remote['genomes']:
            published = remote['genomes'][genome]
            # Older commits have identical GFF3/core fields but no consolidated
            # provenance. Enrich those entries without re-uploading their files.
            if ({k:v for k,v in published.items() if k != 'provenance'} !=
                    {k:v for k,v in entry.items() if k != 'provenance'} or
                    published.get('provenance',entry['provenance']) != entry['provenance']):
                raise ValueError('remote_annotation_conflict:'+genome)
            manifest_changed |= published != entry
            remote['genomes'][genome] = entry
        else:
            pending.append(genome)
    pending.sort()
    # No unnoticed files may be overwritten, even if absent from the manifest.
    for start in range(0,len(pending),500):
        paths=[rows[g][0] for g in pending[start:start+500]]
        if api.get_paths_info(REPO,paths,repo_type='dataset',revision=parent):
            raise ValueError('unregistered_remote_annotation_exists')
    total_bytes = sum(new[g]['file']['bytes'] for g in pending)
    estimate = round(total_bytes*4/3) + len(pending)*1500 + 100_000_000
    if budget.used+estimate > budget.cap:
        raise ValueError(f'upload_exceeds_proxy_budget:used={budget.used},estimate={estimate},cap={budget.cap}')
    print('UPLOAD_READY',len(pending),'genomes','input_bytes',total_bytes,'proxy_body_bytes_before',budget.used,flush=True)
    log = root/'upload-commits.jsonl'
    for start in (range(0,len(pending),per_commit) if pending else ([0] if manifest_changed else [])):
        group=pending[start:start+per_commit]
        operations=[]
        for genome in group:
            path,file=rows[genome]
            operations.append(CommitOperationAdd(path_in_repo=path,path_or_fileobj=str(file)))
            remote['genomes'][genome]=new[genome]
        manifest_bytes=(json.dumps(remote,indent=2)+'\n').encode()
        operations.append(CommitOperationAdd(path_in_repo=MANIFEST_PATH,path_or_fileobj=manifest_bytes))
        before=budget.used
        commit=api.create_commit(REPO,operations=operations,repo_type='dataset',parent_commit=parent,
                                 commit_message=f'Restore verified GEM CDS: {len(group)} genomes ({start+len(group)}/{len(pending)})',
                                 commit_description='Original GEM Prodigal FFN coordinates; exact source/reference contig and CDS nucleotide checks. Additions and merged recovery manifest only.',
                                 num_threads=4)
        record={'commit':commit.oid,'parent':parent,'genomes':group,'proxy_body_bytes':budget.used-before}
        with log.open('a') as stream:
            stream.write(json.dumps(record)+'\n')
        parent=commit.oid
        save_json(root/'upload-state.json',{'commit':parent,'new_genomes':len(new),
                  'manifest_genomes':len(remote['genomes']),'proxy_body_bytes':budget.used,'complete':False})
        print('COMMIT',parent,'uploaded',start+len(group),'/',len(pending),'proxy_body_bytes',budget.used,flush=True)
    # Read back from the actual final commit, not main or a local upload cache.
    downloaded=manifest_at(parent,root)
    if downloaded != remote:
        raise ValueError('remote_manifest_content_mismatch')
    # Registration must consume the actual uploaded checkpoint, not a publish
    # manifest concurrently written by the still-running recovery process.
    verified_manifest = root/'uploaded'/parent/MANIFEST_PATH
    save_json(verified_manifest,downloaded)
    samples=sorted(new,key=lambda g:new[g]['file']['bytes'])
    sample_ids=sorted(set(samples[:2]+samples[-2:]+samples[::max(1,len(samples)//12)]+[g for g in new if new[g]['coverage']=='partial'][:10]))
    verified=[]
    for genome in sample_ids:
        path=rows[genome][0]
        file=hf_hub_download(REPO,path,repo_type='dataset',revision=parent,cache_dir=str(root/'hf-verify-cache'),force_download=True)
        data=Path(file).read_bytes(); entry=new[genome]['file']
        if len(data)!=entry['bytes'] or sha(data)!=entry['sha256']:
            raise ValueError('remote_sample_checksum_mismatch:'+genome)
        if downloaded['genomes'][genome]['provenance'] != new[genome]['provenance']:
            raise ValueError('remote_provenance_summary_mismatch:'+genome)
        verified.append({'genome_id':genome,'path':path,'bytes':len(data),'sha256':sha(data),'provenance_summary_identical':True})
    expected_sizes={rows[g][0]:new[g]['file']['bytes'] for g in new}
    genomes_by_path={rows[g][0]:g for g in new}
    found={}
    lfs_verified=0
    for start in range(0,len(expected_sizes),500):
        paths=list(expected_sizes)[start:start+500]
        for item in api.get_paths_info(REPO,paths,repo_type='dataset',revision=parent):
            found[item.path]=item.size
            if item.lfs:
                genome=genomes_by_path[item.path]
                if item.lfs.sha256!=new[genome]['file']['sha256']:
                    raise ValueError('remote_lfs_checksum_mismatch:'+genome)
                lfs_verified+=1
    if found!=expected_sizes:
        raise ValueError('remote_inventory_incomplete_or_wrong_size')
    report={'commit':parent,'reference_revision':local['reference_revision'],'new_genomes':len(new),
            'preserved_historical_entries':len(old['genomes']),'manifest_genomes':len(remote['genomes']),
            'remote_inventory_verified':len(found),'remote_lfs_sha256_verified':lfs_verified,
            'sha256_samples':verified,'proxy_body_bytes':budget.used,'complete':True,
            'manifest_snapshot':str(verified_manifest),'per_genome_uploads':['genes.gff3'],
            'scope':'verified_checkpoint' if available or pilot else 'finished_batch'}
    save_json(root/'upload-state.json',report)
    print('UPLOAD_VERIFIED',parent,len(found),'genomes',len(verified),'samples',flush=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--per-commit',type=int,default=200)
    parser.add_argument('--pilot',action='store_true')
    parser.add_argument('--available',action='store_true',help='Publish the fixed subset of completed verified records while recovery continues')
    args=parser.parse_args()
    upload(args.output,args.per_commit,args.pilot,args.available)
