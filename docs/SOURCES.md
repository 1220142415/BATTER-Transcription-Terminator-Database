# 来源与证据说明

本页先列出 BATTER Table S1 的 22 份原有来源，再说明 v0.4.0 新纳入和暂不纳入的研究。每行只保留影响数据解释的参考版本、证据和排除判断。完整原值保存在内部来源清单；公开目录的 `metadata.tsv` 可以直接用表格软件阅读。旧版原字节与路径保存在 `data/archive/`。

公开文件按 `data/public/v0.4.0/genomes/<组装编号>/` 整理。每个基因组的 `metadata.tsv` 一行代表一份来源；论文 GFF3 放在该基因组的 `studies/PMID_<pmid>/` 下。一个论文跨多个基因组时分别存放，不复制整篇论文的文件。GFF3 每条记录仍保留 `source_id`。

**13 篇论文对应 22 份来源数据。** 同一篇论文可能提供不同菌株或实验的数据，所以下表一行代表一份 `BATTER_S1` 来源。除 `S1_002` 外，其余 21 份共发布 28,399 条 3′ 端位置记录。文件通过格式和坐标检查，不表示每个位点都经过独立的终止功能实验。

读表时先看来源编号和最后一栏。来源编号用来区分数据，最后一栏写可能影响解释的情况。`GCF_…` 是参考基因组版本，`NC_…`、`CP…` 是坐标所在的序列；“条”指该来源的记录行数，不是全库去重后的位置数。浏览网页时不必记住这些编号，核对坐标或论文时再查即可。

## PMID 与来源记录

| PMID | 来源 / 物种或菌株 | 参考基因组与坐标序列 | v0.4.0 发布记录 | 需要注意的情况 |
|---|---|---|---|---|
| [29606352](https://pubmed.ncbi.nlm.nih.gov/29606352/) | `S1_001` · *E. coli* K-12 MG1655 | `GCF_000005845.1` · `NC_000913.2` | 607 条；`curated_record` | 来自 Lalanne Table S3 的整理记录；本站没有从 Rend-seq 原始信号重新识别端点。该研究的逐端点补充字段未在本版发布。 |
| [38030608](https://pubmed.ncbi.nlm.nih.gov/38030608/) | `S1_002` · *E. coli* K-12 MG1655 | `GCF_000005845.2` · `NC_000913.3` | 0 条；`audit_only` | Supplementary Data 3 的整合结果和各实验观察尚未按本站的字段与证据规则对应起来，因此不发布端点文件或 JBrowse 轨道。登记值 `published_year=2018` 与该 PMID 的 2023 年发表年份不符；保留原值，但不把它当作论文年份。 |
| [29606352](https://pubmed.ncbi.nlm.nih.gov/29606352/) | `S1_003` · *B. subtilis* 168 | `GCF_000009045.1` · `NC_000964.3` | 1,414 条；`curated_record` | 来自 Table S3 的整理记录。本站对单样本 Rend-seq 候选峰与文献记录做过坐标、信号比较，但没有因此改变证据类别。该研究的逐端点补充字段未在本版发布。 |
| [29606352](https://pubmed.ncbi.nlm.nih.gov/29606352/) | `S1_004` · *Caulobacter vibrioides* NA1000 | `GCF_000022005.1` · `CP001340.1` | 337 条；`curated_record` | WIG、补充表和样本信息都指向 `CP001340.1`，因此使用它作为坐标参考。GEO 中另有 `NC_000913.2`，与物种不符，已记录这一冲突。该研究的逐端点补充字段未在本版发布。 |
| [29606352](https://pubmed.ncbi.nlm.nih.gov/29606352/) | `S1_005` · *V. natriegens* NBRC 15636 | `GCF_001456255.1` · `CP009977.1`, `CP009978.1` | 1,154 条；`curated_record` | 两条参考序列分别核对和展示，不跨序列匹配。该研究的逐端点补充字段未在本版发布；坐标核查没有增加新的生物学判断。 |
| [30517198](https://pubmed.ncbi.nlm.nih.gov/30517198/) | `S1_006` · *Streptococcus pneumoniae* TIGR4 | `GCF_000006885.1` · `NC_003028.3` | 1,864 条；`author_called_endpoint` | 来自论文 Supplementary Table S2 的 Term-seq TTS。同一坐标、同一链有时对应多个基因，因此保留原表 1,864 行；它们对应 1,811 个位置，不能按坐标擅自去重。 |
| [31555254](https://pubmed.ncbi.nlm.nih.gov/31555254/) | `S1_007` · *Streptomyces lividans* TK24 | `GCF_000739105.1` · `CP009124.1` | 1,640 条；`author_called_endpoint` | 来自 Supplementary Dataset 3 的 TEP。原论文未对每个位点区分转录终止与 RNA 加工，因此称为 3′ 端或 TEP。 |
| [31594819](https://pubmed.ncbi.nlm.nih.gov/31594819/) | `S1_008` · *Pseudomonas aeruginosa* PAO1 | `GCF_000006765.1` · `NC_002516.2` | 1,965 条；`author_called_endpoint` | 端点取自 Table S1B 中可重复检出的 Term-seq 位点。Table S1A 的 805 条基因与 3′ 端对应记录位于 [`gene_associations.tsv.gz`](../data/public/v0.4.0/genomes/GCF_000006765.1/studies/PMID_31594819/gene_associations.tsv.gz)；正文写 804 条，两者的差异保留，不把这 805 条加进端点总数。 |
| [32694125](https://pubmed.ncbi.nlm.nih.gov/32694125/) | `S1_009` · *Zymomonas mobilis* ZM4 | `GCF_003054575.1` · `CP023715.1`–`CP023719.1`（5 条参考序列） | 2,091 条；`author_called_endpoint` | 发布的是论文排除 RNA 加工位点后的 TTS；1,746 个仅由 TransTermHP 预测的位点未纳入。正文报告 617 个预测匹配，作者列表标记 616 个；保留列表值并记录差异。 |
| [33319794](https://pubmed.ncbi.nlm.nih.gov/33319794/) | `S1_010` · *S. avermitilis* MA-4680 | `GCF_000009765.2` · `BA000030.4` | 1,159 条；`author_called_endpoint` | 原表使用的 `BA000030.4` 与该参考组装中的 `NC_003155.5` 序列一致，核对序列后直接对应坐标，没有做坐标转换。 |
| [33319794](https://pubmed.ncbi.nlm.nih.gov/33319794/) | `S1_011` · *S. griseus* NBRC 13350 | `GCF_000010605.1` · `NC_010572.1` | 2,024 条；`author_called_endpoint` | Lee 2020 论文报告的 Term-seq 端点。 |
| [33319794](https://pubmed.ncbi.nlm.nih.gov/33319794/) | `S1_012` · *S. coelicolor* A3(2) | `GCF_000203835.1` · `NC_003888.3` | 1,308 条；`author_called_endpoint` | Lee 2020 论文报告的 Term-seq 端点。 |
| [33319794](https://pubmed.ncbi.nlm.nih.gov/33319794/) | `S1_013` · *S. lividans* TK24 | `GCF_000739105.1` · `CP009124.1` | 1,208 条；`author_called_endpoint` | 与 `S1_007` 使用相同物种和参考序列，但来自另一篇论文；两份数据保留不同来源编号，不合并。 |
| [33319794](https://pubmed.ncbi.nlm.nih.gov/33319794/) | `S1_014` · *S. tsukubensis* | `GCF_003932715.1` · `CP020700.1` | 1,283 条；`author_called_endpoint` | Lee 2020 论文报告的 Term-seq 端点。 |
| [33319794](https://pubmed.ncbi.nlm.nih.gov/33319794/) | `S1_015` · *S. clavuligerus* | `GCF_005519465.1` · `CP027858.1`, `CP027859.1` | 1,140 条；`author_called_endpoint` | 染色体和质粒分别记录在同一参考组装中；不与 `S1_017` 的记录合并。 |
| [33319794](https://pubmed.ncbi.nlm.nih.gov/33319794/) | `S1_016` · *S. venezuelae* ATCC 15439 | `GCF_015710995.1` · `CP059991.1` | 870 条；`author_called_endpoint` | 论文、ATCC 和 ENA 称 *S. venezuelae*，NCBI 当前组装称 *S. gardneri*。原论文参考与本站所用序列一致，因此可对应坐标；物种名称的差异仍未解决。 |
| [33947798](https://pubmed.ncbi.nlm.nih.gov/33947798/) | `S1_017` · *S. clavuligerus* ATCC 27064 | `GCF_005519465.1` · `CP027858.1`, `CP027859.1` | 1,427 条；`author_called_endpoint` | 来自 Hwang 2021 的独立原表。虽然与 `S1_015` 使用相同菌株和参考序列，两份记录及注释不同，分别保留。原表横向排列，不能用工作表行数代替端点数。 |
| [34054774](https://pubmed.ncbi.nlm.nih.gov/34054774/) | `S1_018` · *Synechocystis* PCC 7338 | `GCF_018282115.1` · `CP054306.1`–`CP054309.1`（4 条参考序列） | 487 条；`author_called_endpoint` | 来自 Supplementary Data S2；染色体和 3 个质粒分别对应坐标。 |
| [34874777](https://pubmed.ncbi.nlm.nih.gov/34874777/) | `S1_019` · *Synechocystis* PCC 6803 | `GCF_000009725.1` · `NC_000911.1` | 784 条；`author_called_endpoint` | 来自原论文 Table S5 的 TEP。登记值 `published_year=2022`，PMID 则记录为 2021 年；尚不清楚两处年份是否指同一件事，因此保留原登记值。 |
| [35491820](https://pubmed.ncbi.nlm.nih.gov/35491820/) | `S1_020` · *Dickeya dadantii* 3937 | `GCF_000147055.1` · `NC_014500.1` | 1,165 条；`author_called_endpoint` | 只发布 Table S2D 中 Nanopore 原生 RNA 测序得到的 3′ 端。S2B/S2C 是 ARNold/RhoTermPredict 预测；S1C 混合了实验与预测结果，都不进入公开端点文件或 JBrowse。 |
| [37402717](https://pubmed.ncbi.nlm.nih.gov/37402717/) | `S1_021` · *Borreliella burgdorferi* B31 | `GCF_000008685.2` · 22 条参考序列中有 20 条含端点 | 1,905 条；`author_called_endpoint` | 两种条件共 2,277 条观察，合并为 1,905 条端点记录。观察位于 [`condition_observations.tsv.gz`](../data/public/v0.4.0/genomes/GCF_000008685.2/studies/PMID_37402717/condition_observations.tsv.gz)；其中 14 个位置的条件间注释有冲突，也保留原值，不重复计入端点数。 |
| [37096044](https://pubmed.ncbi.nlm.nih.gov/37096044/) | `S1_022` · *Mycobacterium tuberculosis* H37Rv | `GCF_000195955.2` · `NC_000962.3` | 2,567 条；`author_called_endpoint` | 原表的 `AL123456.3` 与 `NC_000962.3` 序列一致，可直接对应坐标，无需坐标转换。另有 29,096 条 RhoTermPredict 预测位点，均未纳入公开端点文件。 |

## 坐标与证据

`BATTER_S1_002` 的再分发状态在 2026-10-03 更正为 `verified_redistributable`，范围是作者 Supplementary Data 3 及其标准化派生记录。[出版社许可声明](https://www.nature.com/articles/s41467-023-43534-2#rightslink)为 CC BY 4.0，原始 XLSX 中未发现单独的版权限制。再分发须署名、链接许可并注明修改。原来的 `redistribution_status=audit_only` 混用了发布状态；`release_status=audit_only` 仍保留，因为逐记录实验来源与证据审核尚未完成。许可修正不增加端点或浏览器轨道。

- **坐标**：`endpoints.gff3.gz` 的坐标从 1 开始计数；一个端点只占一个碱基，起点与终点相同。含多条参考序列的来源按序列分别检查，不跨序列匹配或合并。`S1_002` 没有公开的 GFF3 端点记录。
- **证据**：`S1_006`–`S1_022` 是论文发表或整理的实验支持 3′ 端；`S1_001`、`S1_003`–`S1_005` 标为 `curated_record`，不表示本站从原始信号重新识别或逐位点验证。论文中的 TEP 或 3′ 端记录，也不表示每个位点的转录终止功能都已单独验证。保留预测字段不改变端点的证据类别。
- **排除**：仅有预测支持的位点不进入公开端点文件，包括 `S1_009` 的 TransTermHP 位点、`S1_020` 的 S2B/S2C 和 `S1_022` 的 RhoTermPredict 位点。`S1_020` 的 S1C 混合实验与预测，`S1_002` 的混合汇总与尚未对应到来源的条件观察，也没有作为端点发布。
- **增强数据**：原增强页面和接口已移除。六份原始文件按原字节保存在 [`data/registry/internal/augmentation/`](../data/registry/internal/augmentation/)；附带说明记录了来源，并注明这些内容是预测结果，尚无实验确认。目前没有每条预测的基因组坐标，因此不把 OTU 汇总数据写成 GFF3 位置记录。

**校验能说明什么**：校验通过表示文件字段、记录关联、坐标转换、编号和校验值符合 v0.4.0 的发布规则；校验程序不会重做论文的生物学判断。若早期笔记与本版发布记录不同，以内部来源清单中保留的原值和判断为准。`S1_002`、`S1_019` 的 `published_year` 与 PMID 年份不符，原因和保留方式见上表。

## 新纳入与暂不纳入的研究

| 研究 | 本版处理 | 理由 |
|---|---|---|
| [Cascino 2026，PMID 42148773](https://pubmed.ncbi.nlm.nih.gov/42148773/) | `BTED_EXT_2026_102`–`104`，*Synechococcus elongatus* PCC 7942，`GCF_000012525.1`；纳入 388、331、342 条，共 1,061 条 | 只收原 Table S1 写为 `defined end` 的位置；逐行核对工作表、链、坐标和分数。另 196 条分散峰或不确定位置留在内部审核区。作者 `CP000100.1` 与浏览器 `NC_007604.1` 序列完全相同。 |
| [Fuchs 2021，PMID 34131082](https://pubmed.ncbi.nlm.nih.gov/34131082/) | 暂不发布端点 | 已整理 1,967 条草稿，仍在内部审核；其中 75 条链方向未定。 |
| [TERMITe，PMID 40586304](https://pubmed.ncbi.nlm.nih.gov/40586304/) | 暂不发布端点 | 8 份来源共 7,229 个软件从实验数据计算的位置，与论文直接报告的端点不同；当前只保留内部审核材料。 |
| Cascino 的 Eco/Bsu 重分析来源 `BTED_EXT_2026_105` | 仅留审核记录 | 与已有 `BATTER_S1_001`、`S1_003` 所用数据重叠，不重复加入。 |
