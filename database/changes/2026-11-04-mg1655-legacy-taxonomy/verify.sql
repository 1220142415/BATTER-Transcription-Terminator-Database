SELECT genome_id,status,tax_id,scientific_name,matched_accession,match_method,phylum,genus,species,evidence_json
 FROM bted_taxonomy_records WHERE version='202610220000000000000006' AND genome_id='GCF_000005845.1' AND system='ncbi';
SELECT genome_id,genome_type,phylum,genus,predictions,endpoints FROM hf_directory_genomes WHERE version='202610220000000000000006' AND genome_id='GCF_000005845.1';
SELECT status,COUNT(*) AS n FROM bted_taxonomy_records WHERE version='202610220000000000000006' AND system='ncbi' GROUP BY status;
SELECT json_extract(summary_json,'$.counts.phylum') AS phylum_counts FROM hf_directory_releases WHERE version='202610310000000000000005';