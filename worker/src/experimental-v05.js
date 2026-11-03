const VERSION = "v0.5.0";
const ID = /^GCF_\d+\.\d+$/;
const PREFIX = "genomes/experimental-only/";

function response(data, status = 200) {
  return new Response(JSON.stringify(data), {status, headers:{"content-type":"application/json; charset=utf-8","cache-control":"public, max-age=60"}});
}
function uri(request, path) {
  const u = new URL("/api/experimental-v05/files", request.url);
  u.searchParams.set("path", path);
  return {uri:u.href,locationType:"UriLocation"};
}
async function loadGenome(env, id) {
  return env.BTED_DB.prepare("SELECT * FROM bted_experimental_v05_assemblies WHERE accession=?").bind(id).first();
}
async function loadData(env, id) {
  const [sources,files] = await Promise.all([
    env.BTED_DB.prepare("SELECT * FROM bted_experimental_v05_sources WHERE assembly_accession=? ORDER BY source_id").bind(id).all(),
    env.BTED_DB.prepare("SELECT logical_path,source_id,file_kind,byte_size,sha256,hf_revision FROM bted_experimental_v05_files WHERE assembly_accession=? ORDER BY logical_path").bind(id).all()
  ]);
  return {sources:sources.results || [],files:files.results || []};
}
function toFile(files, needle) {
  return files.find(item=>item.logical_path.endsWith(needle));
}
function track(request, id, name, path, files, category, extra={}) {
  const gff=files.find(f=>f.logical_path===path);
  const tbi=files.find(f=>f.logical_path===path+".tbi");
  if (!gff||!tbi) return null;
  const trackId="bted_v05_"+(extra.source_id || name).replace(/[^A-Za-z0-9_-]/g,"_");
  return {
    type:"FeatureTrack", trackId,name,assemblyNames:[id],category,
    adapter:{type:"Gff3TabixAdapter",gffGzLocation:uri(request,gff.logical_path),index:{location:uri(request,tbi.logical_path),indexType:"TBI"}},
    displays:[btedExperimentalDisplay(trackId+"_display",category[0]==="Reference annotation"?"reference":"endpoint")],
    metadata:{...extra,sha256:gff.sha256,btedAbout:{kind:category[0]==="Reference annotation"?"reference":"endpoint",assembly:id,...extra}}
  };
}
async function experimentalV05Config(request,env,genome) {
  const id=genome.accession;
  const contigs=JSON.parse(genome.contigs_json);
  const {sources,files}=await loadData(env,id);
  const fasta=toFile(files,"/reference/reference.fa.gz");
  const fai=toFile(files,"/reference/reference.fa.gz.fai");
  const gzi=toFile(files,"/reference/reference.fa.gz.gzi");
  if (!fasta||!fai||!gzi) return response({error:"reference_files_missing"},503);
  const refTrack={type:"ReferenceSequenceTrack",trackId:"bted_v05_reference",name:"Reference sequence",adapter:{
    type:"BgzipFastaAdapter",fastaLocation:uri(request,fasta.logical_path),faiLocation:uri(request,fai.logical_path),gziLocation:uri(request,gzi.logical_path)
  }};
  const tracks=[];
  const gene=toFile(files,"/annotations/genes.gff3.gz");
  if (gene) {
    const t=track(request,id,"Reference gene annotation",gene.logical_path,files,["Reference annotation"],{
      reference:`${genome.organism} · ${id}`,reference_name:Object.keys(JSON.parse(genome.contigs_json))[0],
      reference_url:`https://www.ncbi.nlm.nih.gov/datasets/genome/${id}/`,explanation:"NCBI gene annotation.",
      btedDownloads:[{kind:"reference",label:"Reference annotation GFF3",url:uri(request,gene.logical_path).uri,filename:`${id}.genes.gff3.gz`}]
    });
    if(t)tracks.push(t);
  }
  for (const s of sources) {
    const endpoint=files.find(f=>f.source_id===s.source_id&&f.logical_path.endsWith("/endpoints.gff3.gz"));
    if(!endpoint)continue;
    const m=JSON.parse(s.metadata_json);
    const t=track(request,id,`PMID ${s.pmid} · ${s.assay} · 3′ ends`,endpoint.logical_path,files,["Experimental 3' ends"],{
      source_id:s.source_id,record_count:s.record_count,
      btedContigCounts:Object.keys(contigs).length===1?{[Object.keys(contigs)[0]]:s.record_count}:m.contig_counts || null,
      evidence_class:s.evidence_class,assay:s.assay,
      paper_title:m.paper_title,title:m.paper_title,pmid:s.pmid,doi:s.doi,
      pubmed_url:`https://pubmed.ncbi.nlm.nih.gov/${s.pmid}/`,doi_url:`https://doi.org/${s.doi}`,
      evidence:s.evidence_class,limitations:m.scientific_caveat || "",gff3_url:uri(request,endpoint.logical_path).uri,
      explanation:"Study records counted separately.",
      btedDownloads:[{kind:"endpoint",label:"3′ end GFF3",url:uri(request,endpoint.logical_path).uri,filename:`${s.source_id}.endpoints.gff3.gz`,source_id:s.source_id}],
    });
    if(t)tracks.push(t);
  }
  const first=Object.entries(contigs).sort((a,b)=>b[1]-a[1])[0];
  const sessionTracks=tracks.map((t,i)=>({
    id:"exp_v05_t"+(i+1),type:"FeatureTrack",configuration:t.trackId,
    displays:[{id:"exp_v05_d"+(i+1),type:"LinearBasicDisplay",configuration:t.displays[0].displayId}]
  }));
  sessionTracks.unshift({id:"exp_v05_ref",type:"ReferenceSequenceTrack",configuration:refTrack.trackId,
    displays:[{id:"exp_v05_ref_d",type:"LinearReferenceSequenceDisplay",configuration:refTrack.trackId+"-LinearReferenceSequenceDisplay",showTranslation:true,heightPreConfig:120}]});
  return response({
    plugins:[{name:"BTEDTrackPlugin",esmUrl:new URL(BTED_PLUGIN_PATH,request.url).href}],
    configuration:btedExperimentalTheme(),
    assemblies:[{name:id,displayName:genome.organism,sequence:refTrack}],
    tracks,defaultSession:{name:"BTED experimental v0.5.0",views:[{
      id:"exp_v05_view",type:"LinearGenomeView",name:genome.organism,bpPerPx:1,offsetPx:0,
      displayedRegions:[{refName:first[0],start:0,end:first[1],reversed:false,assemblyName:id}],
      tracks:sessionTracks
    }]},
    metadata:{assembly_accession:id,release_version:VERSION,hf_revision:genome.hf_revision,source_count:sources.length,endpoint_count:genome.endpoint_count}
  });
}

export async function experimentalV05PageMetadata(request,env,genome,directory,classifications) {
  const {sources,files}=await loadData(env,genome.accession);
  const sourceData=sources.map(source=>{
    const metadata=JSON.parse(source.metadata_json);
    return {
      source_id:source.source_id,assembly_accession:genome.accession,
      publication_pmid:source.pmid,species:genome.organism,assay_family:source.assay,
      evidence_class:source.evidence_class,record_count:source.record_count,
      release_status:"published_standardized",signals:[],
      metadata:{...metadata,title:metadata.paper_title,
        interpretation_note:metadata.scientific_caveat || metadata.interpretation_note,
        raw_data_accessions:(metadata.raw_accessions || metadata.original_experiment_accessions || []).join(";")},
      publication:{pmid:source.pmid,doi:source.doi,paper_title:metadata.paper_title,
        journal:metadata.journal,published_year:metadata.publication_year,citation:{}}
    };
  });
  return {
    release_version:VERSION,metadata_source:"d1",hf_revision:genome.hf_revision,
    assembly:{accession:genome.accession,organism_name:genome.organism,
      reference_url:`https://www.ncbi.nlm.nih.gov/datasets/genome/${genome.accession}/`,
      directory,classifications,contigs:Object.entries(JSON.parse(genome.contigs_json)).map(([contig_accession,length_bp])=>({contig_accession,length_bp}))},
    predictions:null,sources:sourceData,record_count:genome.endpoint_count,
    study_count:new Set(sources.map(source=>source.pmid)).size,
    downloads:[{path:`${genome.accession}/metadata.tsv`,url:`/api/assemblies/${genome.accession}/metadata.tsv`},
      ...files.filter(file=>file.source_id).map(file=>({
        path:`${genome.accession}/sources/${file.source_id}/${file.file_kind}`,
        url:uri(request,file.logical_path).uri}))]
  };
}
async function fileProxy(request,env,url) {
  const path=url.searchParams.get("path")||"";
  if(!path.startsWith(PREFIX)||path.length>1024||path.includes("..")||path.includes("?")||path.includes("#"))return response({error:"invalid_file"},400);
  const f=await env.BTED_DB.prepare("SELECT * FROM bted_experimental_v05_files WHERE logical_path=?").bind(path).first();
  if(!f || !/^[0-9a-f]{40}$/.test(f.hf_revision))return response({error:"unregistered_file"},404);
  const origin="https://huggingface.co/datasets/liurulong/terminator/resolve/"+f.hf_revision+"/"+VERSION+"/"+path.split("/").map(encodeURIComponent).join("/");
  const range=request.headers.get("range");
  if(range && !/^bytes=(?:\d+-\d*|-\d+)$/.test(range))return response({error:"invalid_range"},416);
  const header={};if(range)header.range=range;
  let upstream;
  try{upstream=await fetch(origin,{method:request.method,headers:header,redirect:"follow"});}
  catch{return response({error:"origin_unavailable"},502);}
  if(![200,206,304,416].includes(upstream.status))return response({error:"upstream_unavailable"},502);
  if(upstream.status===206) {
    const match=/^bytes (\d+)-(\d+)\/(\d+)$/.exec(upstream.headers.get("content-range")||"");
    if(!match || Number(match[3])!==f.byte_size || Number(match[2])<Number(match[1])) return response({error:"upstream_range_mismatch"},502);
  }
  const headers=new Headers();
  for(const h of ["content-type","content-length","content-range","accept-ranges"]) {
    if(upstream.headers.has(h))headers.set(h,upstream.headers.get(h));
  }
  headers.set("cache-control","public,max-age=300");
  headers.set("x-bted-revision",f.hf_revision);
  headers.set("x-bted-sha256",f.sha256);
  return new Response(request.method==="HEAD"?null:upstream.body,{status:upstream.status,headers});
}
export async function experimentalV05Api(request,env) {
  if (!["GET","HEAD"].includes(request.method)) return new Response(null,{status:405,headers:{allow:"GET, HEAD"}});
  const url=new URL(request.url);
  if(url.pathname==="/api/experimental-v05/files")return fileProxy(request,env,url);
  if(url.pathname==="/api/experimental-v05/assemblies") {
    const {results}=await env.BTED_DB.prepare("SELECT accession,organism,endpoint_count,source_count,hf_revision FROM bted_experimental_v05_assemblies ORDER BY accession").all();
    const revisions=[...new Set((results||[]).map(row=>row.hf_revision))];
    return response({release_version:VERSION,hf_revision:revisions.length===1?revisions[0]:null,assemblies:results||[]});
  }
  const match=/^\/api\/experimental-v05\/assemblies\/(GCF_\d+\.\d+)(?:\/(config))?$/.exec(url.pathname);
  if(!match)return response({error:"not_found"},404);
  const genome=await loadGenome(env,match[1]);
  if(!genome)return response({error:"not_found"},404);
  if(match[2]==="config")return experimentalV05Config(request,env,genome);
  const {sources,files}=await loadData(env,genome.accession);
  return response({assembly:{...genome,contigs:JSON.parse(genome.contigs_json),contigs_json:undefined},
    source_count:sources.length,sources:sources.map(s=>({source_id:s.source_id,record_count:s.record_count,pmid:s.pmid,doi:s.doi,assay:s.assay,evidence_class:s.evidence_class,metadata:JSON.parse(s.metadata_json)})),
    files:files.map(f=>({...f,url:"/api/experimental-v05/files?path="+encodeURIComponent(f.logical_path)})),hf_revision:genome.hf_revision});
}

