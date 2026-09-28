# BTED

BTED 整理公开论文中的细菌转录本 3′ 端位置。每条记录保留研究来源、参考序列和原表线索，方便回查。3′ 端位置不等于已经单独验证功能的转录终止子。

仓库当前发布数据为 **v0.4.0**：14 篇论文、25 份来源登记（其中 1 份只供核查）、21 个参考组装和 29,460 条端点记录。新版按基因组存放 GFF3 和可读的 `metadata.tsv`。Cascino 论文新增的 1,061 条明确端点与旧版 28,399 条记录分开核对过；尚待审核的候选位置没有混入。

| 想了解什么 | 从这里开始 |
|---|---|
| 发布了哪些文件、怎样读和校验 | [v0.4.0 发布说明](docs/releases/v0.4.0.md) |
| 每篇论文和来源的关键判断 | [来源说明](docs/SOURCES.md) |
| 本地组装 Pages、Worker 与 JBrowse | [运行手册](docs/deployment.md) |
| 添加或修订来源 | [贡献指南](CONTRIBUTING.md) |

正式文件位于 [`data/public/v0.4.0/`](data/public/v0.4.0/)；内部来源判断与旧版可校验归档分别位于 `data/registry/` 和 [`data/archive/`](data/archive/)。网页由构建脚本生成，`site/` 只保存样式和交互脚本。

基因组目录可按研究、方法、证据和实验信号筛选。JBrowse 用青绿和红色区分正负链；每条轨道的 About 可直接查看研究来源、证据和下载入口。

本地检查：

```bash
python scripts/validate_bted_v0_4.py
python scripts/validate_repo_layout.py
python scripts/check_markdown_links.py
python -m unittest discover -s tests -p 'test*.py' -q
```

[现有线上网站](https://seu-yolo.github.io/BATTER-Transcription-Terminator-Database/)尚未部署本分支的 v0.4.0 改动。
