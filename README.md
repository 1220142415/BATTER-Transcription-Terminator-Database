# BTED

BTED 整理公开论文中的细菌转录本 3′ 端位置。每条记录保留研究来源、参考序列和原表线索，方便回查。3′ 端位置不等于已经单独验证功能的转录终止子。

仓库当前发布数据为 **v0.4.0**：14 篇论文、25 份来源登记（其中 1 份只供核查）、21 个参考组装和 29,460 条端点记录。新版按基因组存放 GFF3 和可读的 `metadata.tsv`。Cascino 论文新增的 1,061 条明确端点与旧版 28,399 条记录分开核对过；尚待审核的候选位置没有混入。

| 想了解什么 | 从这里开始 |
|---|---|
| 发布了哪些文件、怎样读和校验 | [v0.4.0 发布说明](docs/releases/v0.4.0.md) |
| 每篇论文和来源的关键判断 | [来源说明](docs/SOURCES.md) |
| 本地组装 Pages、Worker 与 JBrowse | [运行手册](docs/deployment.md) |
| 添加或修订来源 | [贡献指南](CONTRIBUTING.md) |
| 与 promoter 网站的功能差异和后续工作 | [功能对比](docs/PROMOTER_COMPARISON.md) |

正式文件位于 [`data/public/v0.4.0/`](data/public/v0.4.0/)；内部来源判断与旧版可校验归档分别位于 `data/registry/` 和 [`data/archive/`](data/archive/)。网页由构建脚本生成，`site/` 只保存样式和交互脚本。

基因组目录可按研究、方法、证据和实验信号筛选。JBrowse 用青绿和红色区分正负链；有双链实验信号的研究将两条 BigWig 显示为一条镜像轨道。基因组页可分享当前位置和轨道布局，轨道菜单可下载原文件或当前区段的端点 GFF3。

本地检查：

```bash
python scripts/validate_bted_v0_4.py
python scripts/validate_repo_layout.py
python scripts/check_markdown_links.py
python -m unittest discover -s tests -p 'test*.py' -q
```

线上网站：[bted.1052596411.workers.dev](https://bted.1052596411.workers.dev/)。首页展示当前发布统计和 BATTER 引用，基因组目录位于 `genomes.html`，Usage 提供地区访问统计。

BATTER 论文：Jin, Y., Cui, J., Liu, R. et al. *Conserved 3′ stem-loop structures enable comprehensive analysis of bacterial transcription termination in metagenomes.* Microbiome 14, 222 (2026). [DOI](https://doi.org/10.1186/s40168-026-02454-1)。作者代码：[xu-research-lab/BATTER](https://github.com/xu-research-lab/BATTER)。引用于 2026-10-03 根据 Crossref 正式出版记录核对，未采用作者 README 中的旧预印本引用。
