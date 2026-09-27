# Internal BATTER augmentation assets

Source: BATTER augmentation pipeline; dataset derived from Xu et al. 2026 (https://doi.org/10.1186/s40168-026-02454-5). The original page described this as C-layer evidence.

The pipeline starts with experimentally mapped Term-seq 3-prime ends, clusters them by sequence identity with cd-hit at 40%, searches 42,905 bacterial genomes in the GEMs catalog for homologs with hmmsearch (Pfam), and predicts stem-loop structures with CMfinder.

These six files contain OTU-level summaries, cluster/family tables, and predicted structural or Rho-dependency summaries. They do not contain traceable per-instance genomic coordinates. The reported stem-loop instances are bioinformatic predictions homologous to experimentally observed 3-prime ends; they have not been experimentally confirmed. Do not publish the OTU summaries as genome features. Revisit browser GFF3 tracks only after obtaining traceable instance-level coordinates and generation provenance.

Original filenames and SHA-256 (verified after byte-preserving copy):
- combined-statistics.txt  47097103a15c0a2bf15163a4ac5008e12cbc01b796453afd23676dbcbed7940a
- gene_clusters.tsv  3ed4e4d4c23acf9fdebc56f9ccf24e59885aae9aeb6aa333ff4bca2d07d6a578
- per_otu_index.json  80d53772aa2b18496c185b3d1d523a79758e4666d9a3a9874801f02c6a9306a7
- rfam_families.tsv  826fe4525e61013ab085481f481754f058f240e649ee6bb890aa6d2d8fa84d05
- rho_dependency.tsv  2bbf85457522b4ba051314ffab7cb9d3ca7b990d1689b70e7a31208ec51314ad
- stem_loop_properties.tsv  29f64e0899236b3bfff09acea424efa8c0d9f3bb11211fd3a7c0c2a868f7de8f
