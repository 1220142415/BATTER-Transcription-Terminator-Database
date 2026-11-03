-- Add role-labeled source accessions already verified against the paper and GEO records.
-- No files, counts or accession values are changed.
UPDATE sources
SET metadata_json = json_set(metadata_json, '$.raw_data_links', json('[
  {"accession":"GSE138325","url":"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE138325","data_role":"primary_3prime","description":"Term-seq series","article_url":"https://pmc.ncbi.nlm.nih.gov/articles/PMC8269248/","article_locator":"Data availability / data set list","verification":"Article accession and role matched to the official GEO record"},
  {"accession":"GSE128216","url":"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE128216","data_role":"supporting","description":"RNA-seq, dRNA-seq and ribosome-profiling series","article_url":"https://pmc.ncbi.nlm.nih.gov/articles/PMC8269248/","article_locator":"Data availability / data set list","verification":"Article accession and role matched to the official GEO record"}
]'))
WHERE release_version='v0.4.0' AND source_id='BATTER_S1_017'
  AND json_type(metadata_json,'$.raw_data_links') IS NULL;

UPDATE sources
SET metadata_json = json_set(metadata_json, '$.raw_data_links', json('[
  {"accession":"GSE222087","url":"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE222087","data_role":"primary_3prime","description":"3-prime RNA-seq series","article_url":"https://pmc.ncbi.nlm.nih.gov/articles/PMC10319736/","article_locator":"Data availability / data set list","verification":"Article accession and role matched to the official GEO record"},
  {"accession":"GSE222084","url":"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE222084","data_role":"supporting","description":"Bulk RNA-seq series","article_url":"https://pmc.ncbi.nlm.nih.gov/articles/PMC10319736/","article_locator":"Data availability / data set list","verification":"Article accession and role matched to the official GEO record"},
  {"accession":"GSE222085","url":"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE222085","data_role":"supporting","description":"BCM RNA-seq series","article_url":"https://pmc.ncbi.nlm.nih.gov/articles/PMC10319736/","article_locator":"Data availability / data set list","verification":"Article accession and role matched to the official GEO record"},
  {"accession":"GSE222086","url":"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE222086","data_role":"supporting","description":"SPD RNA-seq series","article_url":"https://pmc.ncbi.nlm.nih.gov/articles/PMC10319736/","article_locator":"Data availability / data set list","verification":"Article accession and role matched to the official GEO record"},
  {"accession":"GSE222088","url":"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE222088","data_role":"parent_series","description":"SuperSeries containing the four component series","article_url":"https://pmc.ncbi.nlm.nih.gov/articles/PMC10319736/","article_locator":"Data availability / data set list","verification":"GEO SuperSeries membership matched to the article and component records"}
]'))
WHERE release_version='v0.4.0' AND source_id='BATTER_S1_021'
  AND json_type(metadata_json,'$.raw_data_links') IS NULL;
