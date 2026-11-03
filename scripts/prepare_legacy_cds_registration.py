"""Prepare and locally exercise indexed CDS metadata deltas; never query D1."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sqlite3

from recover_legacy_sources import ROOT, PRIOR, REFERENCE
from recover_gem_cds import save_json
from prepare_annotation_recovery import MANIFEST_PATH
from prepare_collections_d1 import literal
from prepare_gem_recovery_registration import legacy_binding_version

REPO=Path(__file__).resolve().parents[1]
GEM='765f663d12e49b06721ca001'
STORAGE='765f663d12e49b06721ca002'
SOURCE_LABELS={'NCBI-RefSeq':'NCBI RefSeq','NCBI-MAG':'NCBI GenBank','NCBI-SAG':'NCBI GenBank'}


def prepare(snapshot):
    uploaded=json.loads((ROOT/'upload-state.json').read_text());assert uploaded['complete'],'remote_verification_required'
    commit=uploaded['commit'];manifest=json.loads((ROOT/'uploaded'/commit/MANIFEST_PATH).read_text())
    before=json.loads((ROOT/'hf-manifest-before.json').read_text())
    assert all(manifest['genomes'].get(g)==e for g,e in before['genomes'].items()),'historical_manifest_changed'
    additions={g:e for g,e in manifest['genomes'].items() if g not in before['genomes']}
    assert additions,'no_new_annotations'
    out=ROOT/'website'/commit;out.mkdir(parents=True,exist_ok=True)
    database=out/'verified.sqlite';assert not database.exists(),'already_prepared_use_saved_evidence'
    db=sqlite3.connect(database);src=sqlite3.connect(snapshot);src.backup(db);src.close()
    db.row_factory=sqlite3.Row
    old_legacy=json.loads((REPO/'data/registry/genome-directory.json').read_text())
    assert old_legacy['summary']['storage_version']==STORAGE
    gem=dict(db.execute('SELECT * FROM hf_directory_releases WHERE version=?',(GEM,)).fetchone())
    assert gem['reference_revision']==REFERENCE and gem['annotation_revision']==before.get('annotation_revision', '765f663d12e49b06721ca03aecc7d1c64daa78cb')
    db.execute('INSERT OR IGNORE INTO hf_directory_releases VALUES(?,?,?,?,?)',
        (old_legacy['version'],REFERENCE,old_legacy['annotation_revision'],json.dumps(old_legacy['summary'],separators=(',',':')),'ready'))
    db.commit()
    recovery=deepcopy(manifest);recovery.pop('gem_prodigal_archive',None);recovery['annotation_revision']=commit
    browser=json.loads((REPO/'dist/worker-site/assets/genome-browsers.json').read_text())
    browser['annotation_recovery']=recovery
    legacy=legacy_binding_version(REPO/'dist/worker-site',browser)
    guard='_legacy_cds_'+commit[:12]
    def check(condition):
        return f'INSERT OR REPLACE INTO {guard} VALUES(1,CASE WHEN {condition} THEN 1 ELSE 0 END);\n'
    preamble=f'CREATE TABLE IF NOT EXISTS {guard}(id INTEGER PRIMARY KEY,ok INTEGER NOT NULL CHECK(ok=1));\n'
    preamble+=check(f"EXISTS(SELECT 1 FROM bted_collections WHERE collection='gem' AND version={literal(GEM)}) AND EXISTS(SELECT 1 FROM hf_directory_releases WHERE version={literal(GEM)} AND annotation_revision={literal(gem['annotation_revision'])} AND summary_json={literal(gem['summary_json'])} AND status='ready') AND EXISTS(SELECT 1 FROM hf_directory_releases WHERE version={literal(old_legacy['version'])} AND annotation_revision={literal(old_legacy['annotation_revision'])} AND status='ready')")
    (out/'00-preconditions.sql').write_text(preamble)
    db.executescript(preamble)
    oldrows={};names=sorted(additions);scripts=[]
    versions=[GEM,STORAGE];version_sql=','.join(map(literal,versions))
    for i in range(0,len(names),50):
        selected=names[i:i+50];updates=[];expected=[]
        for g in selected:
            e=additions[g];result=json.loads((ROOT/'results'/(g+'.json')).read_text())
            assert result['independent_correspondence']=='passed'
            oldrows[g]={}
            for v in versions:
                row=dict(db.execute('SELECT * FROM hf_directory_genomes WHERE version=? AND genome_id=?',(v,g)).fetchone())
                assert row['annotation']=='Missing' and row['source']==SOURCE_LABELS.get(result['source_collection'],result['source_collection']),g+':baseline_changed'
                # The legacy display directory omits reference dimensions; GEM
                # retains the registered count. Do not invent legacy metadata.
                assert row['contigs']==e['total_reference_contigs'] or (v==STORAGE and row['contigs'] is None),g+':reference_contigs_changed'
                oldrows[g][v]=row
            source=SOURCE_LABELS.get(result['source_collection'],result['source_collection'])
            expected.append('('+','.join(map(literal,[g,source,e['matched_reference_contigs'],e['total_reference_contigs'],e['coverage']]))+')')
            updates.append(f"UPDATE hf_directory_genomes SET annotation='Available',recovered_matched={e['matched_reference_contigs']},recovered_total={e['total_reference_contigs']},recovered_coverage={literal(e['coverage'])} WHERE version IN({version_sql}) AND genome_id={literal(g)} AND source={literal(source)} AND annotation='Missing';\n")
        # CROSS JOIN keeps the small VALUES set outermost; both directory rows
        # are point lookups on UNIQUE(version,genome_id), never a full scan.
        validation=f"(WITH expected(genome_id,source,matched,total,coverage) AS (VALUES {','.join(expected)}) SELECT COUNT(*) FROM expected e CROSS JOIN hf_directory_genomes d WHERE d.version IN({version_sql}) AND d.genome_id=e.genome_id AND d.source=e.source AND d.annotation='Available' AND d.recovered_matched=e.matched AND d.recovered_total=e.total AND d.recovered_coverage=e.coverage AND (d.contigs=e.total OR (d.version={literal(STORAGE)} AND d.contigs IS NULL)))={len(selected)*2}"
        sql=''.join(updates)+check(validation)
        path=out/f'delta-{i//50:03}.sql';path.write_text(sql);scripts.append(path.name)
        db.executescript('BEGIN;\n'+sql+'COMMIT;')
    summary=deepcopy(old_legacy['summary'])
    gem_summary=json.loads(gem['summary_json'])
    for s in [summary,gem_summary]:
        s['available']+=len(additions);s['counts']['annotation']['Available']+=len(additions);s['counts']['annotation']['Missing']-=len(additions)
    headers=f"UPDATE hf_directory_releases SET annotation_revision={literal(commit)},summary_json={literal(json.dumps(gem_summary,separators=(',',':')))} WHERE version={literal(GEM)} AND annotation_revision={literal(gem['annotation_revision'])};\n"
    headers+=f"INSERT INTO hf_directory_releases VALUES({literal(legacy)},{literal(REFERENCE)},{literal(commit)},{literal(json.dumps(summary,separators=(',',':')))},'ready') ON CONFLICT(version) DO NOTHING;\n"
    headers+=check(f"EXISTS(SELECT 1 FROM hf_directory_releases WHERE version={literal(GEM)} AND annotation_revision={literal(commit)}) AND EXISTS(SELECT 1 FROM hf_directory_releases WHERE version={literal(legacy)} AND annotation_revision={literal(commit)})")
    (out/'99-release-headers.sql').write_text(headers);db.executescript(headers)
    changed={'annotation','recovered_matched','recovered_total','recovered_coverage'}
    for g,e in additions.items():
        for v in versions:
            row=dict(db.execute('SELECT * FROM hf_directory_genomes WHERE version=? AND genome_id=?',(v,g)).fetchone())
            assert all(row[k]==value for k,value in oldrows[g][v].items() if k not in changed),g+':unrelated_field_changed'
    plan=[tuple(x) for x in db.execute("EXPLAIN QUERY PLAN SELECT * FROM hf_directory_genomes WHERE version IN(?,?) AND genome_id=?",(*versions,names[0]))]
    assert any('SEARCH' in str(x) and 'version=? AND genome_id=?' in str(x) for x in plan),'point_lookup_index_missing'
    db.close()
    save_json(out/'registry/annotation-recovery.json',recovery)
    save_json(out/'registry/genome-directory.json',dict(version=legacy,reference_revision=REFERENCE,annotation_revision=commit,summary=summary))
    save_json(out/'staged-assets/genome-browsers.json',browser)
    save_json(out/'worker-vars.json',dict(BTED_ANNOTATION_REVISION=commit,BTED_METADATA_REVISION=REFERENCE,BTED_COLLECTION_REVISION='legacy-cds-'+commit[:24]))
    report=dict(production_applied=False,annotation_revision=commit,new_genomes=len(additions),updated_directory_rows=len(additions)*2,
        no_directory_or_taxonomy_clones=True,no_FTS_rebuild=True,gem_version=GEM,legacy_version=legacy,legacy_storage=STORAGE,
        sql_order=['00-preconditions.sql',*scripts,'99-release-headers.sql'],local_changed_rows='passed',unrelated_target_fields='unchanged',point_lookup_plan=plan,
        projected_gem_missing=gem_summary['counts']['annotation']['Missing'])
    save_json(out/'registration-verified.json',report);print(json.dumps(report),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--snapshot',type=Path,required=True)
    prepare(parser.parse_args().snapshot)
