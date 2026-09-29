# 添加或修订 BTED 来源

每份可单独核查的数据使用一个 `source_id`。同一篇论文若有不同样本或参考基因组，可以有多个编号。修改前先看[来源说明](docs/SOURCES.md)，确认该研究是否已经登记。

## 入库前要核对

1. 记录 PMID、DOI、原始数据登录号、补充表文件及工作表、参考组装、参考序列、坐标规则、链方向和许可。保存原始文件的下载地址与 SHA-256；不要凭名称猜参考版本。
2. 分开记录论文明确报告的端点、从实验信号计算的候选位置，以及纯预测。只有通过当前发布规则审核的记录才能进入公开 GFF3。不同研究即使坐标相同，也保留各自的来源编号。
3. 作者序列名与本站浏览器序列名不同时，先核对序列是否完全一致，再记录映射依据。没有核对结果时，不生成浏览器轨道。
4. 许可按具体文件核查。无法确认能否再发布的补充表留在内部审核区，公开页面只给出原始来源链接。

完整原值、字段对应关系和审核依据保存在内部来源清单。公开目录 `data/public/v0.4.0/genomes/<组装编号>/` 使用 GFF3 与 `metadata.tsv`；网页从清单生成说明页，不手改生成文件，也不把内部 JSON 直接作为用户下载。

基因组目录的分类筛选读取 `data/registry/genome_taxonomy.tsv`。新增基因组时，按组装编号补上已核对的门和属；没有把握的分类留空，不猜。当前门名称沿用已登记的来源名称，不代表最新的 NCBI 命名。今后需要更细的筛选时，可在这张表增加 `class`、`order` 或 `family` 列；网页只显示有值的分类层级。

## 修改后运行

```bash
python scripts/build_bted_v0_4_release.py
python scripts/validate_bted_v0_4.py
python scripts/validate_repo_layout.py
python scripts/check_markdown_links.py
python -m unittest discover -s tests -p 'test*.py' -q
```

再按[运行手册](docs/deployment.md)组装 Pages 与 Worker，检查基因组页面、JBrowse 和 `/api`。提交说明写清新增或排除的记录数、参考序列、许可判断及尚未解决的问题。原始 FASTQ/BAM、出版商工作簿、凭据和本机临时目录不进入 Git。
