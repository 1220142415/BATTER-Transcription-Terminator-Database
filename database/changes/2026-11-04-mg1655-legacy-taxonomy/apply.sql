-- Production-only metadata correction: GCF_000005845.1 (legacy assembly), experimental D1 storage.
-- NCBI Taxonomy 511145 confirms the K-12 substr. MG1655 strain identity.
-- The legacy assembly version was not returned by current NCBI Datasets API;
-- do NOT describe the taxonomy mapping as an exact NCBI assembly API match.
-- No changes to experimental endpoints, predictions or reference asset paths.
INSERT INTO hf_directory_search(hf_directory_search,rowid,search_text)
SELECT 'delete',d.id,d.search_text
FROM hf_directory_genomes AS d
WHERE d.version='202610220000000000000006' AND d.genome_id='GCF_000005845.1'
AND d.phylum='' AND EXISTS (
  SELECT 1 FROM bted_taxonomy_records AS t
  WHERE t.version=d.version AND t.genome_id=d.genome_id
    AND t.system='ncbi' AND t.taxonomy_version=''
    AND t.status='pending' AND t.tax_id IS NULL
);
UPDATE bted_taxonomy_records
SET status='verified', tax_id=511145,
  scientific_name='Escherichia coli str. K-12 substr. MG1655',
  matched_accession='',
  match_method='legacy_assembly_strain_taxid_verified',
  domain='Bacteria', phylum='Pseudomonadota', class='Gammaproteobacteria',
  "order"='Enterobacterales', family='Enterobacteriaceae',
  genus='Escherichia', species='Escherichia coli',
  source_url='https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?id=511145',
  retrieved_at=strftime('%Y-%m-%dT%H:%M:%SZ','now'),
  evidence_json=json_object(
    'legacy_assembly','GCF_000005845.1',
    'legacy_assembly_report_url','https://api.ncbi.nlm.nih.gov/datasets/v2/genome/accession/GCF_000005845.1/dataset_report',
    'current_assembly','GCF_000005845.2',
    'taxonomy_report_url','https://www.ncbi.nlm.nih.gov/datasets/taxonomy/511145/',
    'verified_organism','Escherichia coli str. K-12 substr. MG1655',
    'note','Taxon assigned from confirmed strain identity; exact legacy assembly accession was not resolved through current NCBI Datasets API. Do not imply an exact assembly-version match.'
  )
WHERE version='202610220000000000000006' AND genome_id='GCF_000005845.1'
  AND system='ncbi' AND taxonomy_version='' AND status='pending' AND tax_id IS NULL;
UPDATE hf_directory_genomes
SET phylum='Pseudomonadota', class='Gammaproteobacteria',
 "order"='Enterobacterales', family='Enterobacteriaceae',genus='Escherichia',
 species='Escherichia coli',
 search_text=search_text || ' pseudomonadota gammaproteobacteria enterobacterales enterobacteriaceae escherichia escherichia coli'
WHERE version='202610220000000000000006' AND genome_id='GCF_000005845.1'
AND phylum='' AND EXISTS (
 SELECT 1 FROM bted_taxonomy_records AS t
 WHERE t.version=hf_directory_genomes.version AND t.genome_id=hf_directory_genomes.genome_id
   AND t.system='ncbi' AND t.taxonomy_version='' AND t.status='verified'
   AND t.tax_id=511145
);
INSERT INTO hf_directory_search(rowid,search_text)
SELECT id,search_text FROM hf_directory_genomes
WHERE version='202610220000000000000006' AND genome_id='GCF_000005845.1'
 AND phylum='Pseudomonadota';
UPDATE hf_directory_releases
SET summary_json=json_set(summary_json,
 '$.counts.phylum',json_set(
   json_extract(summary_json,'$.counts.phylum'),
   '$.Pseudomonadota',json_extract(summary_json,'$.counts.phylum.Pseudomonadota')+1,
   '$.""',json_extract(summary_json,'$.counts.phylum.""')-1))
WHERE version='202610310000000000000005' AND status='ready'
 AND json_extract(summary_json,'$.storage_version')='202610220000000000000006'
 AND json_extract(summary_json,'$.counts.phylum.""')=1
 AND (SELECT COUNT(*) FROM bted_taxonomy_records
      WHERE version='202610220000000000000006' AND system='ncbi' AND status='pending')=0
 AND EXISTS (SELECT 1 FROM bted_taxonomy_records WHERE
   version='202610220000000000000006' AND genome_id='GCF_000005845.1'
   AND tax_id=511145 AND status='verified');
