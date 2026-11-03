"""Audit cached recovered CDS against both complete source and BTED sequences."""
import csv
import gzip
import io
import json
import sys
from collections import Counter

import recover_legacy_sources as r
from prepare_annotation_recovery import annotation_path


def audit():
    sys.path.insert(0,str(r.ROOT/'python-deps'))
    from Bio import SeqIO
    from Bio.Seq import Seq
    targets=json.loads((r.ROOT/'targets.json').read_text());rows=[];previous={};reused=0
    ledger=r.ROOT/'base-correspondence.tsv'
    if ledger.exists():
        with ledger.open(encoding='utf-8',newline='') as stream:
            previous={x['genome_id']:x for x in csv.DictReader(stream,delimiter='\t')}
    for path in sorted((r.ROOT/'results').glob('*.json')):
        result=json.loads(path.read_text())
        if result['result'] not in {'full','partial'}:continue
        genome=result['genome_id'];work=r.ROOT/'inputs'/genome
        cached=previous.get(genome)
        if cached and cached.get('output_sha256')==result['file']['sha256'] and cached.get('reference_revision')==r.REFERENCE:
            for key in ['reference_contigs','reference_bases','source_contigs','source_bases','matched_contigs','matched_bases','CDS_count','CDS_interval_bases']:cached[key]=int(cached[key])
            rows.append(cached);reused+=1;continue
        refpath=work/'reference.fa.gz'
        if not refpath.exists():refpath=r.OLD/'reference'/(genome+'.fa.gz')
        ref=r.sequences(refpath.read_bytes());meta=r.metadata(targets[genome])['reference']
        assert len(ref)==meta['contigs'] and sum(map(len,ref.values()))==meta['bases'],genome+':reference_dimensions'
        route=result['route']
        if route=='almeida':source=r.source_sequences((work/'original.fna.gz').read_bytes())
        elif route=='uhgg':source=r.source_sequences(gzip.decompress((work/'original.uhgg.gff.gz').read_bytes()).partition(b'##FASTA')[2].lstrip())
        elif route=='ncbi':
            accession=result['source_accession'];fna=work/(accession+'.fna.gz')
            if fna.exists():source=r.source_sequences(fna.read_bytes())
            else:
                text=gzip.decompress((work/(accession+'.gbff.gz')).read_bytes()).decode()
                source={x.id:str(x.seq).upper().encode() for x in SeqIO.parse(io.StringIO(text),'genbank')}
        elif route=='bvbrc':
            data=work/(result['bvbrc_genome_id']+'.sequences.json')
            body=gzip.decompress(data.with_suffix('.json.gz').read_bytes()) if data.with_suffix('.json.gz').exists() else data.read_bytes()
            source={x['accession']:x['sequence'].upper().encode() for x in json.loads(body)}
        else:raise ValueError(route)
        mapping=result['contig_map'];inverse={v:k for k,v in mapping.items()}
        assert len(inverse)==len(mapping),genome+':mapping_not_one_to_one'
        for old,new in mapping.items():assert source[old]==ref[new],genome+':contig_sequence_difference'
        assert len(mapping)==result['matched_reference_contigs'] and len(ref)==result['total_reference_contigs']
        assert (result['result']=='full')==(len(mapping)==len(ref))
        count=bases=0
        for f in r.gem.features((r.ROOT/'publish'/annotation_path(genome,result['batch'])).read_text()):
            if f[2]!='CDS':continue
            name=f[0];start,end=int(f[3])-1,int(f[4]);old=inverse[name];n=len(ref[name])
            assert 0<=start<n and start<end<=2*n and f[6] in {'+','-'} and f[7] in {'0','1','2'},genome+':CDS_bounds'
            a=(source[old]*2)[start:end] if end>n else source[old][start:end]
            b=(ref[name]*2)[start:end] if end>n else ref[name][start:end]
            if f[6]=='-':a=bytes(Seq(a.decode()).reverse_complement());b=bytes(Seq(b.decode()).reverse_complement())
            assert a==b and len(a)==end-start,genome+':CDS_bases_or_length'
            count+=1;bases+=end-start
        assert count==result['features'],genome+':CDS_count'
        rows.append(dict(genome_id=genome,source_collection=result['source_collection'],route=route,coverage=result['result'],
            reference_contigs=len(ref),reference_bases=meta['bases'],source_contigs=len(source),source_bases=sum(map(len,source.values())),
            matched_contigs=len(mapping),matched_bases=sum(len(ref[x]) for x in inverse),CDS_count=count,CDS_interval_bases=bases,
            validation='passed',output_sha256=result['file']['sha256'],reference_revision=r.REFERENCE))
        # Keep completed scientific checks usable across an interrupted audit,
        # without creating another per-genome file collection.
        needs_header=not ledger.exists()
        with ledger.open('a',newline='',encoding='utf-8') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[-1]),delimiter='\t')
            if needs_header:writer.writeheader()
            writer.writerow(rows[-1])
    assert rows,'no_recovered_results'
    with (r.ROOT/'base-correspondence.tsv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]),delimiter='\t');writer.writeheader();writer.writerows(rows)
    report=dict(passed=True,genomes=len(rows),reused_unchanged_verified_genomes=reused,by_route=dict(Counter(x['route'] for x in rows)),
        reference_bases=sum(x['reference_bases'] for x in rows),matched_bases=sum(x['matched_bases'] for x in rows),
        CDS_count=sum(x['CDS_count'] for x in rows),CDS_interval_bases=sum(x['CDS_interval_bases'] for x in rows),
        note='CDS interval bases include overlaps; they are not unique genome coverage. Extra source contigs are excluded, not remapped.')
    r.gem.save_json(r.ROOT/'base-correspondence.json',report);print(json.dumps(report),flush=True)


if __name__=='__main__':audit()
