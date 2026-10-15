# Gene annotation 校正 · 2026-10-14

按当前目录约定，257 个恢复条目已合并到 `v0.5.0/genomes/batter-<batch>/<genome>/annotations/recovered/`，GFF3 与 provenance.json 保留原字节。清单位于 `v0.5.0/catalogues/annotation-recovery.json`，根目录只登记一次，各文件路径由已有批次和基因组编号生成；每个条目仍保存大小、SHA-256、来源和覆盖范围。`v0.5.1` 从当前分支移除，原固定提交仍保留历史版本。原始 `annotations/batter/` 与参考序列不变。新提交为 `2acf28d9cf0a276f05e6a1456d56c92ccc2292b7`，新清单 SHA-256 为 `5a712f860b0740271661b9602e28fa3a409aa3103dfea92ac481fdb7b178b12f`；后文记录原补充发布过程。

目录只显示 `Available` 和 `Missing`。旧 URL 中的 `Incompatible`、`Unavailable`、`Not cataloged` 映射到 `Missing`；原始失败原因保留在悬停说明和 metadata 中。恢复补充文件已发布，最终 Worker 版本为 `aedd0eb9-00af-4b97-836f-d523e02e718f`；初次恢复发布为 `551560de-22f8-42aa-99f9-520da49c5de0`，随后同步内嵌配置缓存参数到 v=30。之前的二类界面版本为 `e79e7297-0e45-4626-b090-ceead7b1a465`。

当前线上为 14,593 个 Available、28,330 个 Missing，共 42,923 个基因组，已经包含本轮恢复的 257 个条目。之前为 14,336 个 Available、28,587 个 Missing。Genome type 和 Assembly size 的 `Not cataloged` 表示其他字段未登记，不属于 Gene annotation 状态。

最终恢复包已核验 257 个基因组：241 个完整覆盖、16 个部分覆盖。其中 NCBI 为 4 个完整和 16 个部分，GEM 为 1 个完整，Almeida 为 236 个完整。包内共 515 个文件、109,320,403 字节；全部文件在固定 HF 提交下重新下载，大小和 SHA-256 与本地一致，匿名跨站 Range 读取返回 206。

`Available` 表示有通过当前参考核验的注释，包括已明确标注覆盖范围的部分注释。`Missing` 表示目前没有可用注释，可能是未登记来源、来源没有发布文件、网络未取得文件或参考不匹配；不能据此判断该基因组没有基因。

## 原因和核验

计算目录的原始状态为：matched 14,318，no_ncbi_accession 24,407，unavailable 4,124，mismatch 53，download_failed 1，invalid_gff 1。另有 19 个纯实验条目，其中 18 个有注释，1 个未登记。

恢复遵循固定参考版本 `9f81698a3cee64f4eaf90b90cd36d640f38d9315`。先按 metadata 的字节数和 SHA-256 检查参考文件，再逐 contig 比较完整 DNA。只在完全相同的序列上沿用原始坐标；允许重命名 seqid，但不进行序列比对、坐标移动或裁剪。部分参考 contig 可核对时，单独记录覆盖范围。

55 个异常 NCBI 条目已全部核验：4 个完整参考可恢复，16 个可恢复部分 contig，35 个不能沿用现有注释。早期网络失败已重试完成，结论以 `dist/annotation-recovery-2026-10-14/partial-verified-report.json` 为准。

完整恢复的 NCBI 条目：

| Genome ID | 原因及校正 |
|---|---|
| GCF_000472605.1 | Datasets 下载失败，但官方 FTP 的 GFF 和参考完全匹配 |
| GCF_002942785.1 | 参考 contig 完全匹配；重命名 seqid，排除不在当前参考中的额外来源 contig |
| GCF_004004555.1 | 参考 contig 完全匹配；排除额外来源 contig |
| GCF_000972785.3 | 7 条特征采用 NCBI 合法的环状跨原点坐标；修正校验并保留原坐标 |

全部 4,124 个 unavailable 的精确组装版本目录均没有发布 GFF。另检查了 213 个官方登记的 RefSeq/GenBank 配对来源：169 个没有 GFF，42 个不能通过序列或坐标核验，2 个对应上表中的 mismatch 条目，未新增独立基因组。

## 非 NCBI 来源

24,407 个未登记 NCBI accession 的条目来自 GEM 12,793、IMG 7,791、Pasolli et al. 2,637、Almeida et al. 602、Nayfach et al. 584。未登记 accession 不等于原研究没有注释。

- [GEM 官方说明](https://portal.nersc.gov/GEM/README.md)登记了公开 Prodigal CDS。FFN 归档约 39 GB；当前工作盘空间不足以完整落盘，按 HTTP Range 读取指定成员。`3300009503_23` 已核验：483/483 条参考 contig 完全匹配，4,513 条 CDS 的核苷酸序列、坐标和链向逐条一致。当前只核验了一个归档成员，不能把其他 GEM 条目直接标为可用。
- [Almeida 原始 UMGS 目录](https://ftp.ebi.ac.uk/pub/databases/metagenomics/umgs_analyses/)提供 FASTA 和 Prodigal 蛋白文件。`taxonomy_umgs.tab` 可精确对应本站 490/602 个编号。蛋白标题保留 CDS 坐标；仅在完整来源 contig 与本站参考 DNA 相同、坐标合法且蛋白长度符合 CDS 区间时恢复。本轮 602 个条目的尝试已完成：236 个完整恢复、112 个未找到原始 UMGS 编号映射、254 个因网络失败未取得文件。降低并发重试后，恢复数从 214 增至 236。结果以 `almeida-verified-report.json` 为准；`complete: true` 表示本轮尝试结束，不表示所有原始文件都已取得。网络失败条目仍待获取，不能归为原始来源未发布注释。
- [Pasolli 官方页面](https://segatalab.cibio.unitn.it/data/Pasolli_et_al.html)提供基因组 FASTA 和功能汇总，未在该发布清单中找到逐基因组坐标文件。功能汇总不能代替 CDS 坐标。
- [Nayfach 官方数据说明](https://github.com/snayfach/IGGdb)提供 HGM/IGG 基因组序列、分类和质量 metadata；该 README 未登记可直接恢复的完整 CDS 坐标文件。
- IMG 样本入口本轮请求失败，未取得可供核验的注释。尚未核验的数据继续保留 Missing，不推断它不存在。

以上调查尚未覆盖所有非 NCBI 原始资产，不构成“全部无法恢复”的结论，也没有重新执行基因预测或功能注释。

纯实验条目 `GCF_000005845.2` 为 BATTER_S1_002 的 audit-only 记录，只有 metadata、没有已发布参考和注释。不能把其他版本的文件套用到这个条目，也不发布其内部审计记录。

## 恢复补充版本

`scripts/audit_annotation_recovery.py` 保存源文件、序列核验、contig 映射和恢复文件校验值。下载缓存可复用；批量核验每 25 条写入一次报告，区分进行中与完成。

```powershell
py -3.13 scripts/audit_annotation_recovery.py --verify --partial --status mismatch download_failed invalid_gff --proxy http://127.0.0.1:7997
py -3.13 scripts/audit_annotation_recovery.py --almeida --workers 4 --proxy http://127.0.0.1:7997
py -3.13 scripts/prepare_annotation_recovery.py
py -3.13 scripts/verify_annotation_correspondence.py
```

打包目录为 `dist/annotation-recovery-2026-10-14/publish/`，仅包含已验证条目。新文件使用独立路径 `v0.5.1/annotation-recovery/2026-10-14/`，保留原有 HF 快照与文件。每个条目提供原始坐标的 GFF3 和 provenance.json；manifest 记录原参考 SHA-256、完整/部分覆盖、来源、字节数及新 GFF3 SHA-256。使用 JBrowse 原生 Gff3Adapter，不把普通 gzip 文件当成 Tabix 文件。

最终 manifest 的 SHA-256 为 `5e0192daaa25baeedd4d0637d037d5dc605c9363c8df96d1c750b814974d3d81`。补充文件固定到 [HF 提交 82180c1e12905470b9c3e3e56c80e5ea510e8460](https://huggingface.co/datasets/liurulong/terminator/tree/82180c1e12905470b9c3e3e56c80e5ea510e8460/v0.5.1/annotation-recovery/2026-10-14)。本次上传使用授权 Token，仅在上传进程内使用，不把凭据写入源码、registry 或报告。

发布步骤（本轮已完成）：

1. 使用具有 `liurulong/terminator` 写权限的专用 Hugging Face Token，通过本机提示输入，不在聊天中传递 token。
2. 上传上述补充目录；取得新的 40 位提交号。逐文件按 manifest 校验远端字节数和 SHA-256，并核对浏览器跨站读取。
3. 将 manifest 加上 `annotation_revision` 后登记为 `data/registry/annotation-recovery.json`。`reference_revision` 继续固定到原参考版本。
4. 将同一提交号写入 Wrangler 的 `BTED_ANNOTATION_REVISION`，按 [部署流程](deployment.md)重建、验证并发布。没有这个显式变量时，补充版本不启用。

Worker 从现有静态浏览器 registry 读取补充清单，合并到目录、metadata、配置和文件下载。D1 中的原快照不修改，不复制另一份完整 metadata；合并补充清单本身不增加 D1 查询。已有 24 小时边缘缓存继续使用，缓存键增加注释补充提交号。科学文件仍优先读取固定 HF 地址；网络回退复用已有文件路由、metadata 缓存和校验机制。插件、静态配置和 Worker 配置已同步发布为 v=30。原始状态保留为 `original_status`，annotation_revision 和覆盖范围可追溯。

部分恢复仍显示 Available，因为已有可用注释；悬停、下载区和 About track 明确显示覆盖的 contig 数和 partial。尚未匹配的 contig 不附加注释。

## 验证与限制

`scripts/verify_annotation_correspondence.py` 独立读取发布 GFF3、原始 GFF/FFN/FAA、原始参考 FASTA、本站固定参考和 metadata，不调用恢复生成器的序列映射或 GFF 转换函数。复核 257 个基因组、29,921 条匹配 contig、544,906 条注释记录全部通过：参考文件 SHA-256 和大小相同，完整 contig DNA 一致，原始坐标、链向和保留属性逐行相同，覆盖范围和特征计数一致。Almeida 另核对原始 taxonomy 表的 MAG_ID/UMGS_ID 映射；GEM CDS 核苷酸逐条核对。记录见 `dist/annotation-recovery-2026-10-14/correspondence-report.json`。

论文统计中，241 个“完整覆盖”指全部参考 contig 通过序列对应核验，不表示所有基因或功能均已注释。20 个条目沿用已发布 GFF3，237 个条目恢复已发布 CDS 坐标。FAA 来源保留坐标和 partial 属性并检查区间与蛋白长度，未验证蛋白翻译或功能；没有执行新的基因预测。不能把这批数据描述为新的全基因组功能注释。

恢复测试覆盖序列差异与歧义拒绝、部分覆盖、合法环状坐标、正负链 CDS 核对、蛋白区间长度和打包校验。浏览器/API 测试覆盖原状态保留、不同参考拒绝、单一原生 GFF3 轨道、下载、目录筛选和补充版本缓存隔离。

线上 13 个关键静态文件与本地产物的 SHA-256 一致，目录 API 已返回完整恢复清单和 14,593 个 Available、28,330 个 Missing。逐项核对完整 NCBI、环状坐标、部分 NCBI、GEM、Almeida 五个代表条目的 metadata、参考 SHA、原始状态、覆盖范围、单一原生 Gff3Adapter 轨道、插件版本和 206 下载字节，均通过；记录见 `dist/annotation-recovery-2026-10-14/deployment-verified.json`。

内置浏览器初次连接线上超时；用户开启代理后，线上页面已实际核验 Available 14,593、Missing 28,330，两类筛选正常，截图为 `dist/annotation-recovery-2026-10-14/available-live.png`。GEM 样本 `3300009503_23` 的独立和内嵌 JBrowse 均已实际显示恢复的原生 Gff3Adapter 轨道、参考序列、augmentation 和 predicted 区域，正链绿色、负链红色；内嵌配置为 v=30。线上截图为 `dist/annotation-recovery-2026-10-14/recovered-annotation-live.png` 和 `dist/annotation-recovery-2026-10-14/recovered-annotation-embedded-live.png`，结果补记在 `deployment-verified.json` 的 `live_browser` 中。早期截图 `recovered-annotation-preview.png` 是本地验证，不是线上截图。
