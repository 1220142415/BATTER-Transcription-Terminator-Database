UPDATE sources
SET metadata_json = json_remove(metadata_json, '$.raw_data_links')
WHERE release_version='v0.4.0' AND source_id IN ('BATTER_S1_017','BATTER_S1_021')
  AND json_type(metadata_json,'$.raw_data_links')='array'
  AND ((source_id='BATTER_S1_017' AND json_extract(metadata_json,'$.raw_data_links[0].accession')='GSE138325')
    OR (source_id='BATTER_S1_021' AND json_extract(metadata_json,'$.raw_data_links[0].accession')='GSE222087'));
