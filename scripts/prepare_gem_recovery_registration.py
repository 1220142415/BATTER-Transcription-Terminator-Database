"""Stage immutable D1 directory additions and website pins; never execute remotely."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile

from build_genome_directory import compact, directory_rows
from prepare_annotation_recovery import MANIFEST_PATH
from prepare_collections_d1 import COLS, literal
from recover_gem_cds import save_json

ROOT=Path(__file__).resolve().parents[1]
TAXONOMY=['version','genome_id','system','taxonomy_version','status','tax_id','scientific_name','matched_accession',
          'match_method','domain','phylum','class','order','family','genus','species','source_url','retrieved_at','evidence_json']


def columns(names):
    return ','.join('"'+name+'"' for name in names)


def legacy_binding_version(site, browser):
    """Use the same content-derived binding checked by the site builder."""
    with tempfile.TemporaryDirectory() as temporary:
        scratch=Path(temporary)
        (scratch/'assets').mkdir()
        for name in ['assets/batter-browser.json','genomes.html']:
            shutil.copyfile(site/name,scratch/name)
        (scratch/'assets/genome-browsers.json').write_text(json.dumps(browser),encoding='utf-8')
        reference,annotation,rows=directory_rows(scratch)
    return hashlib.sha256(('directory-v4:'+reference+annotation+compact(rows)).encode()).hexdigest()[:24]


def prepare(root, snapshot):
    uploaded=json.loads((root/'upload-state.json').read_text())
    assert uploaded['complete'], 'remote_verification_required'
    commit=uploaded['commit']
    manifest=json.loads(Path(uploaded.get('manifest_snapshot',root/'publish'/MANIFEST_PATH)).read_text())
    old=json.loads((root/'hf-manifest.json').read_text())
    additions={g:e for g,e in manifest['genomes'].items() if g not in old['genomes']}
    assert len(additions)==uploaded['new_genomes'], 'upload_manifest_count_mismatch'
    captured=json.loads((root/'d1-directory-before.json').read_text(encoding='utf-8-sig'))
    legacy=captured[0]['results'][0]; gem=captured[1]['results'][0]
    assert gem['taxonomy_system']=='gem_original'
    out=root/'website'/commit
    out.mkdir(parents=True,exist_ok=True)
    local=out/'verified.sqlite'
    if local.exists():
        raise ValueError('already_prepared_use_saved_report')
    src=sqlite3.connect(snapshot); db=sqlite3.connect(local); src.backup(db); src.close()
    db.execute('PRAGMA foreign_keys=ON')
    # Refresh only the current captured directory headers in the historical
    # local test snapshot. Production apply guards them rather than replacing.
    for release in [legacy,gem]:
        db.execute('UPDATE hf_directory_releases SET summary_json=? WHERE version=?',
                   (release['summary_json'],release['version']))
    db.execute('UPDATE bted_collections SET label=?,taxonomy_label=?,description=? WHERE collection=\'gem\'',
               (gem['label'],gem['taxonomy_label'],gem['description']))
    db.commit()
    # Keep audit-only fields out of browser responses; retain them in HF/local evidence.
    recovery={k:v for k,v in manifest.items() if k!='gem_prodigal_archive'}
    recovery['genomes']={g:{k:v for k,v in e.items() if k!='provenance'} for g,e in manifest['genomes'].items()}
    recovery['annotation_revision']=commit
    browser=json.loads((ROOT/'dist/worker-site/assets/genome-browsers.json').read_text(encoding='utf-8'))
    browser['annotation_recovery']=recovery
    versions={'gem':commit[:22]+'01','legacy':legacy_binding_version(ROOT/'dist/worker-site',browser)}
    guard='_gem_recovery_'+commit[:12]
    sql=[f'CREATE TABLE IF NOT EXISTS {guard}(stage TEXT PRIMARY KEY,ok INTEGER NOT NULL CHECK(ok=1));\n']
    def check(stage,condition):
        return f'INSERT OR REPLACE INTO {guard} VALUES({literal(stage)},CASE WHEN {condition} THEN 1 ELSE 0 END);\n'
    sql.append(check('active_collection',f"EXISTS(SELECT 1 FROM bted_collections WHERE collection='gem' AND version={literal(gem['version'])} AND taxonomy_system='gem_original')"))
    for name,release in [('gem',gem),('legacy',legacy)]:
        version=versions[name]; previous=release['version']; summary=json.loads(release['summary_json'])
        storage=summary.pop('storage_version',previous)
        summary['available']+=len(additions)
        summary['counts']['annotation']['Available']+=len(additions)
        summary['counts']['annotation']['Missing']-=len(additions)
        sql.append(check(name+'_prior',f"EXISTS(SELECT 1 FROM hf_directory_releases WHERE version={literal(previous)} AND reference_revision={literal(release['reference_revision'])} AND annotation_revision={literal(release['annotation_revision'])} AND summary_json={literal(release['summary_json'])} AND status='ready')"))
        sql.append(check(name+'_row_count',f"(SELECT COUNT(*) FROM hf_directory_genomes WHERE version={literal(storage)})={summary['total']}"))
        sql.append(f'INSERT OR IGNORE INTO hf_directory_releases VALUES({literal(version)},{literal(release["reference_revision"])},{literal(commit)},{literal(json.dumps(summary,separators=(",",":")))},\'loading\');\n')
        sql.append(check(name+'_new_release',f"EXISTS(SELECT 1 FROM hf_directory_releases WHERE version={literal(version)} AND annotation_revision={literal(commit)} AND reference_revision={literal(release['reference_revision'])})"))
        sql.append(f'INSERT OR IGNORE INTO hf_directory_genomes({columns(COLS)}) SELECT {literal(version)},{columns(COLS[1:])} FROM hf_directory_genomes WHERE version={literal(storage)};\n')
        for genome,entry in additions.items():
            sql.append(f"UPDATE hf_directory_genomes SET annotation='Available',recovered_matched={entry['matched_reference_contigs']},recovered_total={entry['total_reference_contigs']},recovered_coverage={literal(entry['coverage'])} WHERE version={literal(version)} AND genome_id={literal(genome)} AND source='GEM' AND (annotation='Missing' OR recovered_coverage IS NOT NULL);\n")
        if name=='gem':
            sql.append(f'INSERT OR IGNORE INTO bted_taxonomy_records({columns(TAXONOMY)}) SELECT {literal(version)},{columns(TAXONOMY[1:])} FROM bted_taxonomy_records WHERE version={literal(previous)};\n')
            sql.append(check('taxonomy_cloned',f"(SELECT COUNT(*) FROM bted_taxonomy_records WHERE version={literal(version)})=(SELECT COUNT(*) FROM bted_taxonomy_records WHERE version={literal(previous)}) AND (SELECT COUNT(*) FROM bted_taxonomy_records WHERE version={literal(version)} AND system='gem_original')={summary['total']}"))
        sql.append(check(name+'_available',f"(SELECT COUNT(*) FROM hf_directory_genomes WHERE version={literal(version)} AND annotation='Available')={summary['available']}"))
        sql.append(check(name+'_missing',f"(SELECT COUNT(*) FROM hf_directory_genomes WHERE version={literal(version)} AND annotation='Missing')={summary['counts']['annotation']['Missing']}"))
        sql.append(f"UPDATE hf_directory_releases SET status='ready' WHERE version={literal(version)};\n")
    sql.append("INSERT INTO hf_directory_search(hf_directory_search) VALUES('rebuild');\n")
    stage=''.join(sql)
    activate=check('activate_prior',f"EXISTS(SELECT 1 FROM bted_collections WHERE collection='gem' AND version={literal(gem['version'])})")
    activate+=f"UPDATE bted_collections SET version={literal(versions['gem'])} WHERE collection='gem' AND version={literal(gem['version'])} AND EXISTS(SELECT 1 FROM hf_directory_releases WHERE version={literal(versions['gem'])} AND annotation_revision={literal(commit)} AND status='ready');\n"
    rollback=f"UPDATE bted_collections SET version={literal(gem['version'])} WHERE collection='gem' AND version={literal(versions['gem'])};\n"
    for name,data in [('stage.sql',stage),('activate.sql',activate),('rollback.sql',rollback)]:
        (out/name).write_text(data,encoding='utf-8')
    before={v:db.execute('SELECT COUNT(*) FROM hf_directory_genomes WHERE version=?',(v,)).fetchone()[0] for v in [gem['version'],legacy['version']]}
    db.executescript('BEGIN;\n'+stage+'\nCOMMIT;')
    db.executescript('BEGIN;\n'+activate+'\nCOMMIT;')
    assert db.execute("SELECT version FROM bted_collections WHERE collection='gem'").fetchone()[0]==versions['gem']
    for name,release in [('gem',gem),('legacy',legacy)]:
        previous=release['version']; version=versions[name]
        assert db.execute('SELECT COUNT(*) FROM hf_directory_genomes WHERE version=?',(previous,)).fetchone()[0]==before[previous]
        current={r[0]:r[1:] for r in db.execute('SELECT genome_id,annotation,recovered_matched,recovered_total,recovered_coverage FROM hf_directory_genomes WHERE version=?',(version,))}
        for genome,entry in additions.items():
            assert current[genome]==('Available',entry['matched_reference_contigs'],entry['total_reference_contigs'],entry['coverage'])
        fields=COLS[1:]
        storage=json.loads(release['summary_json']).get('storage_version',previous)
        original={r[0]:r[1:] for r in db.execute(f'SELECT {columns(fields)} FROM hf_directory_genomes WHERE version=?',(storage,))}
        staged={r[0]:r[1:] for r in db.execute(f'SELECT {columns(fields)} FROM hf_directory_genomes WHERE version=?',(version,))}
        for genome in set(original)-set(additions):
            assert original[genome]==staged[genome], 'unrelated_row_changed'
    assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert not db.execute('PRAGMA foreign_key_check').fetchall()
    db.executescript(rollback)
    assert db.execute("SELECT version FROM bted_collections WHERE collection='gem'").fetchone()[0]==gem['version']
    db.executescript(activate)
    db.close()
    save_json(out/'registry/annotation-recovery.json',recovery)
    save_json(out/'registry/genome-directory.json',{'version':versions['legacy'],
        'reference_revision':manifest['reference_revision'],'annotation_revision':commit,'summary':summary})
    collections=json.loads((ROOT/'data/registry/collections.json').read_text(encoding='utf-8'))
    collections['gem']['version']=versions['gem'];save_json(out/'registry/collections.json',collections)
    browser['annotation_recovery']=recovery;save_json(out/'staged-assets/genome-browsers.json',browser)
    save_json(out/'staged-assets/genome-directory.json',{'version':versions['legacy'],
        'reference_revision':manifest['reference_revision'],'annotation_revision':commit})
    save_json(out/'worker-vars.json',{'BTED_ANNOTATION_REVISION':commit,
        'BTED_COLLECTION_REVISION':'gem-recovery-'+commit[:24],
        'BTED_METADATA_REVISION':manifest['reference_revision']})
    report={'annotation_revision':commit,'new_genomes':len(additions),'versions':versions,
            'previous_gem_version':gem['version'],'previous_legacy_version':legacy['version'],
            'local_integrity':'ok','foreign_keys':'ok','all_new_directory_rows':'Available',
            'unrelated_directory_rows':'unchanged','taxonomy_records':'cloned','rollback':'passed',
            'production_applied':False}
    save_json(out/'registration-verified.json',report)
    print(json.dumps(report),flush=True)
    return out


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--snapshot',type=Path,required=True)
    args=parser.parse_args();prepare(args.output,args.snapshot)
