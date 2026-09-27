# 向 BTED 添加或修订来源

每份可单独核查的数据都有一个 `source_id`。同一篇论文如果提供不同菌株、参考版本或实验数据，也可能有多个编号。现有 BATTER 数据沿用 `BATTER_S1_NNN`；新增数据使用 `BTED_EXT_年份_三位序号`。开始前先查[来源说明](docs/SOURCES.md)和各 study 的 `metadata.json`，避免编号重复，并确认原始数据出处和再发布许可。

## 1. 登记来源和证据

登记新数据时，记录论文 PMID/DOI、物种与菌株、实验方法、样本及原始数据登录号、补充表文件和工作表、论文使用的参考基因组与序列、坐标、链方向、许可和处理人。`dataset_id` 使用小写英文和短横线。缺项填 `NA` 并说明原因；不要猜测登录号或参考版本。

原始工作簿和测序文件留在本地，同时登记下载网址、文件名、大小、SHA-256 和下载日期。不要提交 FASTQ/BAM/BigWig、出版商工作簿、凭据或本机绝对路径。整理发布数据时，把每份来源的原始对象、字段含义、许可决定、证据判断和取舍理由保存在所属 PMID 目录的 `metadata.json` 中，并生成对应的 `metadata.tsv` 供直接阅读；通用格式规则在发布说明中写一次即可。发布各研究的补充字段前，要确认许可允许。

处理状态有六种：`to_review`（待核查）、`accessible`（已找到数据）、`standardized`（格式和坐标已核对）、`curated`（人工复核完成）、`published`（进入指定版本）、`blocked`（缺少关键证据或存在冲突）。标为 `blocked` 时要写清还需补什么。当前处理进度和某个发布版本中的状态分别记录，不能互相代替。

## 2. 核对证据和坐标

- 分清原始实验信号、从信号识别的候选端点、论文发表的端点、文献整理记录、实验与预测混合结果，以及纯预测。发布规则见[v0.3.0 发布说明](docs/releases/v0.3.0.md)。纯预测或无法拆分的混合结果不能算作实验端点。
- 如果从原始信号识别峰，标记为 `called_endpoint`，并写明方法和阈值。论文已经给出端点表时，保留原论文的定义，不用统一算法重新解释。
- 固定带版本号的参考基因组和序列；核对 FASTA 序列名、长度、链方向及原论文的坐标规则。BTED 的 GFF3 坐标从 1 开始计数；单碱基端点的起点和终点相同。不同参考序列上的记录不得互相匹配或去重。
- 如果作者参考和浏览器参考不同，先证明序列一致或完成有记录的坐标转换。核查不完整时保持 `to_review` 或 `blocked`。
- 许可按资产核查。论文开放获取不等于其所有补充字段都可再发布；不能确认时只保留外部链接和字段说明。

## 3. 制作并审阅发布数据

每篇论文对应一个 `data/public/v0.3.0/studies/PMID_<pmid>/` 目录，包含该研究的 `endpoints.gff3.gz`、可读的 `metadata.tsv` 和完整 `metadata.json`。同一研究可能包含多个 `source_id`；GFF3 保留这些来源编号，不跨来源去重。逐端点补充字段以 `ann_<field>` 属性名保存在 GFF3 中；study 的 JSON 来源对象通过 `annotation_field_map` 和默认值说明如何还原。不同论文的分数不能直接比较。若研究有基因关联表或条件观察表，将对应压缩 TSV 放在同一目录；345 条未关联公开端点的基因记录仍保留自己的坐标。版本根目录的 `release.json` 和 `SHA256SUMS.txt` 用于检查研究文件。详见[v0.3.0 发布说明](docs/releases/v0.3.0.md)。

按来源生成的 GFF3、按参考基因组生成的 GFF3 及其 metadata、来源网页、目录数据和 JBrowse 配置，都由网站组装程序生成，仅供浏览器和兼容下载使用。主要下载路径始终是按 PMID 划分的 study 目录；不要在版本根目录另放全库 GFF3、来源 JSON 或关系 TSV。不要生成或发布端点 CSV、TSV、BED。`data/registry/internal/augmentation/` 保存六份预测数据及其来源说明；这些预测尚无实验确认，也缺少每条预测的基因组坐标，不能作为 GFF3 位置记录加入浏览器。下载地址应包含版本号。若来源、参考序列、坐标、排除或许可判断改变，要更新数据与发布记录，不覆盖旧版归档。

## 4. 提交前检查

在仓库根目录运行：

```bash
python3 scripts/validate_bted_templates.py
python3 scripts/validate_bted_v0_3.py
python3 scripts/validate_repo_layout.py
python3 scripts/check_markdown_links.py
python3 -m unittest discover -s tests -p 'test*.py' -q
git diff --check
```

涉及 Pages、JBrowse 或 Worker 时，再按[部署手册](docs/v0.3/deployment.md)检查 Pages/Worker 组装和 API。PR 使用 [模板](.github/pull_request_template.md)列明来源 ID、证据、参考坐标、未完成项及实际运行的检查。
