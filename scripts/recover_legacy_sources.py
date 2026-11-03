"""Recover published CDS from exact assemblies; never run a gene caller.

Almeida preserves original Prodigal coordinates and checks protein translation.
UHGG is explicitly third-party Prokka reannotation, not the original study CDS.
NCBI uses an exact assembly or its officially recorded pair, never a newer one.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import sys
import threading
import time
from urllib.parse import quote, urljoin

from audit_annotation_recovery import sequences, matching_contigs, compatible_gff
from prepare_annotation_recovery import annotation_path, MANIFEST_PATH
import recover_gem_cds as gem
from annotation_transfer_budget import Budget

ROOT = Path(__file__).resolve().parents[1]/'_workspace/outputs/BTED-legacy-sources-2026-10-27'
PRIOR = ROOT.parent/'BTED-GEM-recovery-2026-10-27'
OLD = ROOT.parent/'BTED-publication-2026-10-22/retained-evidence/annotation-recovery-2026-10-14'
REFERENCE = '9f81698a3cee64f4eaf90b90cd36d640f38d9315'
METADATA = ROOT.parent/'BTED-publication-2026-10-22/retained-evidence/hf-metadata'/REFERENCE
UMGS = 'https://ftp.ebi.ac.uk/pub/databases/metagenomics/umgs_analyses/'
UHGG = 'https://ftp.ebi.ac.uk/pub/databases/metagenomics/mgnify_genomes/human-gut/v1.0/'
LOCAL = threading.local()

def get(url, target):
    """Cache public source bodies using direct connections, retry transient errors."""
    if target.exists():
        return target.read_bytes()
    import requests
    if not hasattr(LOCAL, 'http'):
        LOCAL.http=requests.Session();LOCAL.http.trust_env=False
    target.parent.mkdir(parents=True,exist_ok=True)
    for attempt in range(3):
        try:
            with LOCAL.http.get(url,stream=True,timeout=(15,90)) as r:
                r.raise_for_status()
                part=target.with_suffix(target.suffix+'.part')
                with part.open('wb') as out:
                    for block in r.iter_content(256*1024):out.write(block)
                part.replace(target)
            return target.read_bytes()
        except requests.RequestException as error:
            if error.response is not None and error.response.status_code in {400,401,403,404,410}:raise
            if attempt==2:raise
            time.sleep(2**attempt)

def metadata(row):
    data=json.loads((METADATA/'genomes'/('batter-'+row[1])/row[0]/'metadata.json').read_text())
    assert data['genome_id']==row[0] and data['records']['batter']['genome_id']==row[0]
    return data['records']['batter']

def json_body(url,path):
    """Keep large public API payloads compressed without changing source bytes."""
    packed=path.with_suffix(path.suffix+'.gz')
    if packed.exists():return gzip.decompress(packed.read_bytes())
    raw=get(url,path)
    temporary=packed.with_suffix(packed.suffix+'.part')
    temporary.write_bytes(gzip.compress(raw,compresslevel=1,mtime=0));temporary.replace(packed)
    path.unlink()
    return raw

def reference(row, work):
    expected=metadata(row)['files']['reference.fa.gz']
    previous=OLD/'reference'/(row[0]+'.fa.gz')
    data=previous.read_bytes() if previous.exists() else gem.download(
        f'{gem.REPO}{REFERENCE}/v0.5.0/genomes/batter-{row[1]}/{row[0]}/reference/reference.fa.gz',work/'reference.fa.gz')
    assert len(data)==expected['bytes'] and gem.sha(data)==expected['sha256'],'reference_checksum_mismatch'
    result=sequences(data)
    assert len(result)==metadata(row)['reference']['contigs'],'reference_contig_count'
    assert sum(map(len,result.values()))==metadata(row)['reference']['bases'],'reference_total_base_count'
    return result,expected['sha256']

def source_sequences(data):
    from Bio import SeqIO
    text=gzip.decompress(data) if data[:2]==b'\x1f\x8b' else data
    records=list(SeqIO.parse(io.StringIO(text.decode()),'fasta'))
    result={r.id:str(r.seq).upper().encode() for r in records}
    assert result and len(result)==len(records),'empty_or_duplicate_source_contigs'
    return result

def almeida(row, work, identifiers):
    from Bio import SeqIO
    from Bio.Seq import Seq
    genome=row[0];umgs=identifiers.get(genome)
    if not umgs:raise ValueError('original_UMGS_mapping_absent; require_UHGG_or_original_nonrepresentative_annotation')
    dna_url=UMGS+'umgs/genomes/'+umgs+'.fa.gz'
    faa_url=UMGS+'umgs/proteins/'+umgs+'_proteins.faa.gz'
    dna=get(dna_url,work/'original.fna.gz');faa=get(faa_url,work/'original.faa.gz')
    source=source_sequences(dna);ref,checksum=reference(row,work)
    mapping=matching_contigs(ref,source,partial=True)
    output=['##gff-version 3']+[f'##sequence-region {k} 1 {len(v)}' for k,v in ref.items()]
    expected=[];omitted=0;seen=set()
    for record in SeqIO.parse(io.StringIO(gzip.decompress(faa).decode()),'fasta'):
        identifier,start,end,direction,attrs=record.description.split(' # ')
        assert identifier not in seen and direction in {'1','-1'},'duplicate_CDS_or_invalid_strand'
        seen.add(identifier);old=identifier.rsplit('_',1)[0]
        if old not in mapping:omitted+=1;continue
        name=mapping[old];start,end=int(start),int(end)
        assert 1<=start<=end<=len(ref[name]),'CDS_outside_reference'
        original=source[old][start-1:end];registered=ref[name][start-1:end]
        assert original==registered,'CDS_nucleotide_mismatch'
        seq=Seq(registered.decode())
        if direction=='-1':seq=seq.reverse_complement()
        assert len(seq)%3==0,'CDS_frame_length'
        translated=str(seq.translate(table=11));protein=str(record.seq)
        qualifiers=dict(x.split('=',1) for x in attrs.split(';') if '=' in x)
        # Prodigal partial bits refer to genomic left/right, not protein N/C.
        # Its explicit start_type identifies initiation even on reverse CDS.
        if translated and protein.startswith('M') and qualifiers.get('start_type')==str(seq[:3]) and str(seq[:3]) in {'TTG','CTG','ATT','ATC','ATA','ATG','GTG'}:
            translated='M'+translated[1:]
        assert translated.rstrip('*')==protein.rstrip('*'),'CDS_protein_translation_mismatch:'+identifier
        attributes=['ID='+quote(identifier,safe=':._-')]+[a for a in attrs.split(';') if a and not a.startswith('ID=')]
        fields=[name,'Prodigal','CDS',str(start),str(end),'.','+' if direction=='1' else '-','0',';'.join(attributes)]
        expected.append(fields);output.append('\t'.join(fields))
    raw=('\n'.join(output)+'\n').encode()
    assert gem.features(raw.decode())==expected and expected,'independent_GFF_correspondence'
    return raw,ref,mapping,dict(source_url=faa_url,source_reference_url=dna_url,source_accession=umgs,
        source_annotation_type='published_Prodigal_CDS',annotation_origin='original_study',
        source_reference_sha256=gem.sha(dna),source_faa_sha256=gem.sha(faa),reference_sha256=checksum,
        features=len(expected),omitted_source_cds=omitted,protein_translation='all_retained_CDS_passed_table_11')

def gff_verified(data, ref, source):
    mapping=matching_contigs(ref,source,partial=True)
    for old,new in mapping.items():assert source[old]==ref[new],'contig_sequence_difference'
    raw,_,omitted=compatible_gff(gzip.compress(data,mtime=0),ref,mapping)
    before=gem.features(data.decode());after=gem.features(raw.decode())
    expected=[[mapping[f[0]],*f[1:]] for f in before if f[0] in mapping]
    assert after==expected,'independent_source_GFF_coordinate_correspondence'
    cds=[f for f in after if f[2]=='CDS'];inverse={v:k for k,v in mapping.items()}
    assert cds,'no_CDS_annotations'
    for fields in cds:
        assert fields[6] in {'+','-'} and fields[7] in {'0','1','2'},'invalid_CDS_strand_or_phase'
        old=inverse[fields[0]]
        start,end=int(fields[3])-1,int(fields[4]);length=len(ref[fields[0]])
        # Preserve NCBI's declared circular-origin coordinates without clipping.
        src=(source[old]+source[old])[start:end] if end>length else source[old][start:end]
        dst=(ref[fields[0]]+ref[fields[0]])[start:end] if end>length else ref[fields[0]][start:end]
        assert src==dst and len(dst)==end-start,'CDS_nucleotide_correspondence'
    return raw,mapping,len(cds),omitted

def uhgg(row,work,identifiers):
    item=identifiers.get(row[0])
    if not item:raise ValueError('exact_original_genome_ID_not_in_UHGG_v1_metadata')
    url=item['FTP_download'].replace('ftp://','https://')
    assert url.startswith(UHGG+'all_genomes/'),'unexpected_UHGG_host_or_layout'
    data=get(url,work/'original.uhgg.gff.gz');text=gzip.decompress(data)
    gff,marker,fasta=text.partition(b'##FASTA')
    assert marker,'UHGG_combined_GFF_missing_reference_FASTA'
    source=source_sequences(fasta.lstrip());ref,checksum=reference(row,work)
    raw,mapping,count,omitted=gff_verified(gff,ref,source)
    return raw,ref,mapping,dict(source_url=url,source_reference_url=url,source_accession=item['Genome'],
        source_annotation_type='published_UHGG_Prokka_GFF3',annotation_origin='third_party_reannotation',
        source_release='UHGG_v1.0',mapping_evidence=item,source_gff_sha256=gem.sha(data),
        source_reference_sha256=gem.sha(fasta),reference_sha256=checksum,features=count,
        omitted_source_features=omitted)

def ncbi_location(accession,work):
    digits=accession.split('_')[1].split('.')[0]
    url=f'https://ftp.ncbi.nlm.nih.gov/genomes/all/{accession[:3]}/{digits[:3]}/{digits[3:6]}/{digits[6:]}/'
    listing=get(url,work/(accession+'-directory.html')).decode()
    folders=re.findall(r'href="('+re.escape(accession)+r'_[^"/]+/)',listing)
    if len(folders)!=1:raise ValueError('exact_NCBI_assembly_directory_absent:'+accession)
    return url+folders[0],folders[0].rstrip('/')

def ncbi(row,work,identifiers):
    accession=row[0];attempts=[]
    base,stem=ncbi_location(accession,work)
    report=get(base+stem+'_assembly_report.txt',work/(accession+'-assembly_report.txt')).decode()
    assert re.search(r'^# (?:GenBank|RefSeq) assembly accession:\s+'+re.escape(accession)+r'\s*$',report,re.M),'assembly_identity_not_reported'
    candidates=[accession]
    candidates += [x for x in re.findall(r'^# (?:GenBank|RefSeq) assembly accession:\s+(GC[AF]_\d+\.\d+)',report,re.M) if x!=accession]
    for candidate in candidates:
        try:
            base,stem=ncbi_location(candidate,work)
            listing=get(base,work/(candidate+'-files.html')).decode()
            files=set(re.findall(r'href="([^"/]+)"',listing))
            gff_name=stem+'_genomic.gff.gz';gbff_name=stem+'_genomic.gbff.gz'
            if gff_name in files and stem+'_genomic.fna.gz' in files:
                gff=get(base+gff_name,work/(candidate+'.gff.gz'))
                dna=get(base+stem+'_genomic.fna.gz',work/(candidate+'.fna.gz'))
                ref,checksum=reference(row,work);source=source_sequences(dna)
                raw,mapping,count,omitted=gff_verified(gzip.decompress(gff),ref,source)
                return raw,ref,mapping,dict(source_url=base+gff_name,source_reference_url=base+stem+'_genomic.fna.gz',
                    source_accession=candidate,source_annotation_type='published_NCBI_GFF3',annotation_origin='primary_database_annotation',
                    assembly_report=report,source_gff_sha256=gem.sha(gff),source_reference_sha256=gem.sha(dna),
                    reference_sha256=checksum,features=count,omitted_source_features=omitted)
            if gbff_name in files:
                data=get(base+gbff_name,work/(candidate+'.gbff.gz'))
                return gbff(row,work,data,base+gbff_name,candidate,report)
            attempts.append(candidate+':GFF3_and_GBFF_not_published')
        except Exception as error:attempts.append(candidate+':'+str(error))
    raise ValueError('; '.join(attempts))

def gbff(row,work,data,url,accession,report):
    from Bio import SeqIO
    records=list(SeqIO.parse(io.StringIO(gzip.decompress(data).decode()),'genbank'))
    source={r.id:str(r.seq).upper().encode() for r in records}
    assert len(source)==len(records) and source,'duplicate_or_empty_GBFF_contigs'
    assert any(f.type=='CDS' for r in records for f in r.features),'GBFF_has_no_CDS'
    ref,checksum=reference(row,work);mapping=matching_contigs(ref,source,partial=True)
    output=['##gff-version 3']+[f'##sequence-region {k} 1 {len(v)}' for k,v in ref.items()]
    count=0;omitted=0
    for record in records:
        for feature in record.features:
            if feature.type!='CDS':continue
            if record.id not in mapping:omitted+=1;continue
            location=feature.location
            assert location is not None and location.strand in {-1,1},'GBFF_CDS_location_or_strand'
            # Uncommon joined/frameshift features need a full exon-aware conversion.
            if len(location.parts)!=1:raise ValueError('GBFF_joined_CDS_requires_review')
            start,end=int(location.start),int(location.end);name=mapping[record.id]
            assert 0<=start<end<=len(ref[name]),'GBFF_CDS_bounds'
            assert bytes(feature.extract(record.seq))==bytes(feature.extract(type(record.seq)(ref[name].decode()))),'GBFF_CDS_sequence'
            count+=1;qual=feature.qualifiers
            identifier=qual.get('locus_tag',qual.get('protein_id',[f'cds{count}']))[0]
            attrs=['ID='+quote(identifier,safe=':._-')]
            for key in ('gene','product','protein_id','note'):
                if key in qual:attrs.append(key+'='+quote(' '.join(qual[key]),safe=':._-'))
            phase=int(qual.get('codon_start',['1'])[0])-1
            output.append('\t'.join([name,'NCBI_GBFF','CDS',str(start+1),str(end),'.','+' if location.strand==1 else '-',str(phase),';'.join(attrs)]))
    assert count,'GBFF_has_no_CDS'
    return ('\n'.join(output)+'\n').encode(),ref,mapping,dict(source_url=url,source_reference_url=url,
        source_accession=accession,source_annotation_type='published_NCBI_GBFF_CDS',annotation_origin='primary_database_annotation',
        assembly_report=report,source_gbff_sha256=gem.sha(data),reference_sha256=checksum,features=count,omitted_source_cds=omitted)

def mapping_uhgg():
    path=ROOT/'mapping/genomes-all_metadata.tsv'
    get(UHGG+'genomes-all_metadata.tsv',path)
    targets=json.loads((ROOT/'targets.json').read_text());mapping={};duplicates=[]
    with path.open(encoding='utf-8',newline='') as stream:
        for item in csv.DictReader(stream,delimiter='\t'):
            original=item['Original_name']
            if original in targets:
                if original in mapping:duplicates.append(original)
                else:mapping[original]=item
    for name in duplicates:mapping.pop(name,None)
    gem.save_json(ROOT/'uhgg-mapping.json',mapping)
    gem.save_json(ROOT/'uhgg-mapping-report.json',dict(url=UHGG+'genomes-all_metadata.tsv',
        exact_unique_matches=len(mapping),ambiguous_ids=sorted(set(duplicates)),by_source=dict(Counter(targets[g][12] for g in mapping))))
    print('UHGG_EXACT_ID_MAPPING',len(mapping),dict(Counter(targets[g][12] for g in mapping)),flush=True)

def mapping_bvbrc():
    """Find exact accessions and officially reported pairs, not species neighbors."""
    targets=json.loads((ROOT/'targets.json').read_text());accessions={}
    for genome in targets:
        if not genome.startswith(('GCA_','GCF_')):continue
        result=ROOT/'results'/(genome+'.json')
        if result.exists() and json.loads(result.read_text())['result'] in {'full','partial'}:continue
        accessions.setdefault(genome,set()).add(genome)
        report=ROOT/'inputs'/genome/(genome+'-assembly_report.txt')
        if report.exists():
            for pair in re.findall(r'^# (?:GenBank|RefSeq) assembly accession:\s+(GC[AF]_\d+\.\d+)',report.read_text(),re.M):
                accessions.setdefault(pair,set()).add(genome)
    names=sorted(accessions);mapping={}
    for i in range(0,len(names),100):
        group=names[i:i+100]
        url='https://www.bv-brc.org/api/genome/?in(assembly_accession,('+','.join(group)+'))&limit(10000)&http_accept=application/json'
        data=json.loads(get(url,ROOT/'mapping'/f'bvbrc-{i//100:03}.json'))
        assert len(data)<10000,'BV_BRC_mapping_truncated'
        for item in data:
            if not item.get('public') or item.get('assembly_accession') not in accessions:continue
            if not (item.get('refseq_cds',0) or item.get('patric_cds',0)):continue
            for genome in accessions[item['assembly_accession']]:mapping.setdefault(genome,[]).append(item)
        print('BV_BRC_MAPPING',min(i+100,len(names)),'/',len(names),'target_matches',len(mapping),flush=True)
    gem.save_json(ROOT/'bvbrc-mapping.json',mapping)

def bvbrc(row,work,identifiers):
    from Bio.Seq import Seq
    failures=[]
    items=sorted(identifiers[row[0]],key=lambda x:x['genome_id'])
    candidates=[(item,annotation) for annotation in ['RefSeq','PATRIC'] for item in items if item.get(annotation.lower()+'_cds',0)]
    for item,annotation in candidates:
        gid=item['genome_id']
        try:
            sequence_url=f'https://www.bv-brc.org/api/genome_sequence/?eq(genome_id,{gid})&limit(25000)&http_accept=application/json'
            seq_data=json_body(sequence_url,work/(gid+'.sequences.json'));records=json.loads(seq_data)
            assert len(records)==item['contigs'] and len(records)<25000,'BV_BRC_contig_inventory_incomplete'
            source={r['accession']:r['sequence'].upper().encode() for r in records}
            assert len(source)==len(records) and sum(map(len,source.values()))==item['genome_length'],'BV_BRC_reference_dimensions'
            ref,checksum=reference(row,work);mapping=matching_contigs(ref,source,partial=True)
            url=f'https://www.bv-brc.org/api/genome_feature/?eq(genome_id,{gid})&eq(annotation,{annotation})&eq(feature_type,CDS)&limit(25000)&http_accept=application/json'
            data=json_body(url,work/(gid+'.'+annotation+'.features.json'));features=json.loads(data)
            assert len(features)==item[annotation.lower()+'_cds'] and len(features)<25000,'BV_BRC_CDS_inventory_incomplete'
            output=['##gff-version 3']+[f'##sequence-region {k} 1 {len(v)}' for k,v in ref.items()]
            count=0;omitted=0
            for feature in features:
                old=feature['accession']
                if old not in mapping:omitted+=1;continue
                assert len(feature.get('segments',[]))==1,'BV_BRC_joined_CDS_requires_review'
                start,end=feature['start'],feature['end'];strand=feature['strand'];name=mapping[old]
                assert strand in {'+','-'} and 1<=start<=end<=len(ref[name]),'BV_BRC_CDS_bounds_or_strand'
                dna=Seq(source[old][start-1:end].decode());registered=Seq(ref[name][start-1:end].decode())
                if strand=='-':dna=dna.reverse_complement();registered=registered.reverse_complement()
                assert dna==registered and len(dna)==feature['na_length'],'BV_BRC_CDS_nucleotide_correspondence'
                expected=feature.get('na_sequence_md5')
                assert expected and any(hashlib.md5(str(dna).encode()).hexdigest()==expected for dna in (dna,dna.lower())),'BV_BRC_published_CDS_md5_mismatch'
                # Confirm the coding phase against the published protein checksum,
                # rather than inventing codon_start when converting API records.
                aa_hash=feature.get('aa_sequence_md5');phase=None
                for offset in range(3):
                    coding=dna[offset:];coding=coding[:len(coding)//3*3]
                    protein=str(coding.translate(table=11))
                    text=str(coding)
                    alternatives=[protein.rstrip('*')]
                    if protein and text[:3] in {'TTG','CTG','ATT','ATC','ATA','ATG','GTG'}:
                        alternatives += ['M'+p[1:] for p in alternatives]
                    if aa_hash and any(hashlib.md5(p.encode()).hexdigest()==aa_hash for p in alternatives):phase=offset;break
                    # Archived RAST proteins use X for ambiguous DNA codons.
                    # Only visit those codons after the ordinary checksum fails.
                    ambiguous=list(re.finditer('[^ACGT]',text))
                    if ambiguous:
                        masked=list(protein)
                        for match in ambiguous:masked[match.start()//3]='X'
                        masked=''.join(masked).rstrip('*');alternatives=[masked]
                        if masked and text[:3] in {'TTG','CTG','ATT','ATC','ATA','ATG','GTG'}:alternatives.append('M'+masked[1:])
                        if aa_hash and any(hashlib.md5(p.encode()).hexdigest()==aa_hash for p in alternatives):phase=offset;break
                assert phase is not None,'BV_BRC_original_protein_or_phase_not_verified'
                attrs=['ID='+quote(feature['feature_id'],safe=':._-')]
                for key in ['product','protein_id','refseq_locus_tag','patric_id']:
                    if feature.get(key):attrs.append(key+'='+quote(str(feature[key]),safe=':._-'))
                output.append('\t'.join([name,'BV-BRC_'+annotation,'CDS',str(start),str(end),'.',strand,str(phase),';'.join(attrs)]));count+=1
            assert count,'BV_BRC_no_verified_reference_CDS'
            raw=('\n'.join(output)+'\n').encode()
            return raw,ref,mapping,dict(source_url=url,source_reference_url=sequence_url,source_accession=item['assembly_accession'],
                bvbrc_genome_id=gid,source_annotation_type='published_BVBRC_'+annotation+'_CDS',
                annotation_origin='archived_primary_database_annotation' if annotation=='RefSeq' else 'third_party_reannotation',
                source_metadata=item,source_features_sha256=gem.sha(data),source_reference_sha256=gem.sha(seq_data),reference_sha256=checksum,
                features=count,omitted_source_cds=omitted,protein_translation='published_protein_and_CDS_MD5_passed')
        except Exception as error:failures.append(gid+':'+annotation+':'+str(error))
    raise ValueError('; '.join(failures))

def recover(row,route,identifiers,retry_failed=False):
    path=ROOT/'results'/f'{row[0]}.json'
    if path.exists():
        prior=json.loads(path.read_text())
        if prior['result'] in {'full','partial'}:return prior
        if prior['result']=='failed' and prior.get('route')==route and not retry_failed:return prior
    work=ROOT/'inputs'/row[0];work.mkdir(parents=True,exist_ok=True)
    result=dict(genome_id=row[0],batch=row[1],source_collection=row[12],reference_revision=REFERENCE,route=route)
    try:
        assert shutil.disk_usage(ROOT).free>4*1024**3,'disk_free_below_4GiB'
        raw,ref,mapping,provenance=globals()[route](row,work,identifiers)
        assert ref and mapping and provenance['features']>0
        for fields in gem.features(raw.decode()):
            if fields[2]=='CDS':assert 1<=int(fields[3])<=int(fields[4])<=2*len(ref[fields[0]])
        result.update(provenance,result='full' if len(mapping)==len(ref) else 'partial',
            matched_reference_contigs=len(mapping),total_reference_contigs=len(ref),contig_map=mapping,
            reference_bases=sum(map(len,ref.values())),matched_reference_bases=sum(len(ref[name]) for name in mapping.values()),
            unmatched_reference_contigs=sorted(set(ref)-set(mapping.values())),independent_correspondence='passed',
            file=dict(bytes=len(raw),sha256=gem.sha(raw)),processed_at=datetime.now(timezone.utc).isoformat())
        target=ROOT/'publish'/annotation_path(row[0],row[1]);target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():assert target.read_bytes()==raw,'existing_local_output_conflict'
        else:target.write_bytes(raw)
    except Exception as error:result.update(result='failed',reason=type(error).__name__+': '+str(error))
    gem.save_json(path,result)
    return result

def run(route,pilot,workers,retry_failed=False):
    targets=json.loads((ROOT/'targets.json').read_text())
    if route=='almeida':
        with (OLD/'non-ncbi/taxonomy_umgs.tab').open() as f:identifiers={r['MAG_ID']:r['UMGS_ID'] for r in csv.DictReader(f,delimiter='\t')}
        selected=[r for r in targets.values() if r[12]=='Almeida et al.' and r[0] in identifiers]
    elif route=='uhgg':
        identifiers=json.loads((ROOT/'uhgg-mapping.json').read_text())
        selected=[r for r in targets.values() if r[0] in identifiers and r[12] in {'Pasolli et al.','Nayfach et al.','Almeida et al.'}]
        # Original Almeida restoration owns those genomes until its batch ends.
        if pilot:selected=[r for r in selected if r[12]!='Almeida et al.']
        selected=[r for r in selected if not ((ROOT/'results'/(r[0]+'.json')).exists() and
            json.loads((ROOT/'results'/(r[0]+'.json')).read_text())['result'] in {'full','partial'})]
    elif route=='bvbrc':
        identifiers=json.loads((ROOT/'bvbrc-mapping.json').read_text())
        selected=[targets[g] for g in identifiers if not ((ROOT/'results'/(g+'.json')).exists() and json.loads((ROOT/'results'/(g+'.json')).read_text())['result'] in {'full','partial'})]
    else:
        identifiers={};selected=[r for r in targets.values() if r[0].startswith(('GCA_','GCF_'))]
    selected.sort(key=lambda r:gem.sha(r[0].encode()))
    gate=ROOT/(route+'-pilot.json')
    if pilot:selected=selected[:16]
    else:assert gate.exists() and json.loads(gate.read_text())['accepted'],'source_pilot_not_accepted'
    gem.PROXY_BUDGET=Budget(ROOT/('proxy-reference-'+route+'.jsonl'),cap=1_000_000_000)
    results=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for task in as_completed([pool.submit(recover,row,route,identifiers,retry_failed) for row in selected]):
            result=task.result();results.append(result)
            if pilot or len(results)%25==0 or len(results)==len(selected):
                print(route,len(results),'/',len(selected),result['genome_id'],result['result'],result.get('reason',''),flush=True)
    counts=Counter(r['result'] for r in results)
    report=dict(route=route,pilot=pilot,attempted=len(results),eligible=len(selected),counts=dict(counts),
        features=sum(r.get('features',0) for r in results),gff_bytes=sum(r.get('file',{}).get('bytes',0) for r in results),
        accepted=counts['full']+counts['partial']>0,genomes=[r['genome_id'] for r in results],
        failure_reasons=dict(Counter(r['reason'] for r in results if r['result']=='failed')))
    gem.save_json(gate if pilot else ROOT/(route+'-batch.json'),report)
    print(json.dumps({k:v for k,v in report.items() if k not in {'genomes','failure_reasons'}}),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('route',choices=['almeida','uhgg','ncbi','bvbrc','map-uhgg','map-bvbrc'])
    parser.add_argument('--pilot',action='store_true');parser.add_argument('--workers',type=int,default=6)
    parser.add_argument('--retry-failed',action='store_true',help='Recheck completed failures; ordinary resume preserves them.')
    args=parser.parse_args()
    sys.path.insert(0,str(ROOT/'python-deps'))
    if args.route=='map-uhgg':mapping_uhgg()
    elif args.route=='map-bvbrc':mapping_bvbrc()
    else:run(args.route,args.pilot,args.workers,args.retry_failed)
