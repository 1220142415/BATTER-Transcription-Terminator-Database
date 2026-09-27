# BTED

BTED 收集公开研究报告的细菌转录本 3′ 端位置。记录保留论文来源、样本、参考序列和原表行号，方便查回原始依据。这些位置有实验数据支持，但并非每个位点都做过单独的转录终止功能实验。

🌐 [打开 BTED 网站](https://seu-yolo.github.io/BATTER-Transcription-Terminator-Database/)

当前数据版本是 **v0.3.0**：13 篇论文、22 份来源数据、28,399 条 3′ 端位置记录。规范发布文件按 PMID 分目录；每个研究目录包含 `endpoints.gff3.gz`、方便阅读的 `metadata.tsv` 和保存完整来源对象的 `metadata.json`。研究专属关系 TSV 也放在对应目录。网站按来源或参考组装生成的文件只用于 JBrowse 和兼容下载。本次只改了文件格式，没有改变生物学记录或证据判断。

## 从哪里开始

| 要做什么 | 阅读 |
|---|---|
| 了解 v0.3.0 数据格式、下载和校验 | [v0.3.0 发布说明](docs/releases/v0.3.0.md) |
| 查论文与来源的关键判断 | [来源说明](docs/SOURCES.md) |
| 本地组装 Pages、Worker 或 JBrowse | [部署手册](docs/v0.3/deployment.md) |
| 接入或修订来源 | [贡献指南](CONTRIBUTING.md) |

发布文件在 [`data/public/v0.3.0/`](data/public/v0.3.0/)；每篇论文对应 `studies/PMID_<pmid>/`。版本目录根部只保留研究文件夹、`release.json` 和 `SHA256SUMS.txt`。完整的 v0.2.0 旧文件保存在 [`data/archive/`](data/archive/)；解压后仍使用原来的 `data/public/v0.2.0/` 路径。`site/` 保存网页源文件；按来源或参考基因组拆分的页面和 JBrowse 兼容文件在组装网站时生成。

## 本地检查

在仓库根目录运行：

```bash
python3 scripts/validate_bted_v0_3.py
python3 scripts/validate_repo_layout.py
python3 scripts/check_markdown_links.py
python3 -m unittest discover -s tests -p 'test*.py' -q
```

Pages 和 Worker 组装、API 检查及本地预览方式见[部署手册](docs/v0.3/deployment.md)。
