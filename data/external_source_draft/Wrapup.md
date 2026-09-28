# BTED 项目实习交接文档

---

## 一、已实现与未完成功能总览

### 1.1 已实现功能清单

按模块组织，每个模块关联对应的仓库目录和网站页面（如适用）。

#### A. 文献溯源与数据获取

| 功能 | 说明 | 产出路径 |
|------|------|----------|
| BATTER Table S1 13 篇文献逐篇数据可用性核查 | PubMed、PMC、期刊官网三渠道交叉确认数据存储位置 | `data/文献N-PMIDxxxxxxxx/`（13 个子目录） |
| 登录号记录校正 | 发现并修正多处此前遗留的错误（如 PMID 32694125 误标 PRJNA587699 → 修正为 GSE139939） | `data/accession_list_verified.csv` |
| Zenodo 仓库内容审查 | 确认 v2/v3 版本差异，确认不包含实验坐标数据 | `report_zenodo_and_documents.md` |
| 补充材料批量下载与交叉核查 | 自动模式匹配 + 人工逐一打开 xlsx 验证坐标字段 | `data/data_verification_report.md` |

#### B. 数据标准化与发布（BTED v0.2.0，已在网站上线）

| 功能 | 说明 | 网站页面 / 文件路径 |
|------|------|---------------------|
| 24 列核心端点表 Schema | 统一字段定义、数据类型和枚举值 | `docs/standards/数据字段字典_v0.1.md` |
| 来源登记表 | 22 条来源记录的元数据（PMID、物种、参考组装、实验方法等） | `data/registry/batter_s1_source_registry.tsv` |
| 标准化端点表 + BED 格式输出 | 21 个公开来源的 `endpoints.tsv` + `endpoints.bed` | `data/public/v0.2.0/records/BATTER_S1_NNN/` |
| 来源特异注释表 | 无损保留作者原始字段（read count、fold change 等） | 同目录下 `source_annotations.tsv` + `fields.json` |
| Release Manifest | 集中记录所有来源的发布状态、记录数和校验和 | `data/public/v0.2.0/release_manifest.json` |
| 证据分层体系 | 六层证据（前四层公开，后两层仅审计） | `docs/standards/证据分层与发布边界.md` |

#### C. 外部来源端点表构建（草案状态，尚未进入网站）

| 批次 | 来源数 | 端点行数 | 处理要点 | 产出路径 |
|------|--------|----------|----------|----------|
| **Fuchs 2021**（PMID 34131082） | 1（C. difficile） | **1,967** | 链向从 GFF 推断（高置信 1,815 + 低置信 152）；75 行链向无法确定单独留存 | `draft/endpoints_output/BTED_EXT_2026_101_*.tsv` |
| **Cascino 2026**（PMID 42148773） | 3（S. elongatus） | **1,257** | 原仅纳入 defined end（1,061 行）；阅读作者补充方法后，将 diffuse peak（164 行）+ unclear 有峰位行（32 行）重分级为次级置信度纳入，共扩展 196 行 | 同上 `_102/103/104_*.tsv` |
| **TERMITe 8 来源** | 8（B. subtilis×4, E. coli×2, E. faecalis, L. monocytogenes） | **7,229** | 全部通过 coord_valid 检验；4 行 POT≠summit（1bp 差异）已在 note 标注 | 同上 `_106~113_*.tsv` |
| 合计 | **12** | **10,453** | — | `draft/endpoints_output/README_endpoints_build.md` |

配套产出：
- 构建脚本 3 个：`build_fuchs_endpoints.py` / `build_cascino_endpoints.py` / `build_termite_endpoints.py`
- 辅助文件：`fuchs_2021_unresolved_strand_75rows.tsv`、`cascino_exclusion_report.txt`、`cascino_reclassification_changelog.md`、`termite_endpoints_summary.txt`

#### D. BTED 网站（`BTED/repo/site/`）

| 页面/功能 | 说明 |
|-----------|------|
| **Home**（index.html） | 概览首页，中英双语，默认英文 |
| **Sources**（sources.html） | 22 个来源的搜索筛选列表，含年份、物种、实验方法、记录数、浏览器入口 |
| **Record 页面**（records/BATTER_S1_NNN.html） | 每来源独立页面，含 PMID/DOI/登录号超链接、下载文件入口 |
| **Assembly 页面**（assemblies/GCF_*.html） | 按参考基因组聚合的来源列表，20 个组装页面 |
| **Browser**（browser.html） | 统一 JBrowse 2 入口，`?assembly=` 参数驱动，支持同一基因组多来源轨道勾选 |
| **Augmentation**（bted-augmentation.html） | 增强数据展示：5 张数据表（OTU 实例 4.2 万+、基因簇、Rfam 家族、茎环属性、Rho 依赖性），含免责声明 |
| **Download**（catalog.html） | 按基因组一键打包下载 TSV/BED/校验和 |
| **信号双轨显示** | 4 个有 BigWig 信号的来源（001/003/004/005）生成线性 + 对数变换双轨道，JBrowse 原生选择器切换 |

#### E. CI/CD 与部署

| 功能 | 说明 |
|------|------|
| GitHub Actions 工作流 | `.github/workflows/pages.yml`，手动触发 → Build + Deploy + Validate |
| CI 问题修复 | 完成 3 项修复：CRLF→LF 校验和（`regenerate_checksums_lf.py`）、release_manifest 引用时序、旧测试用例更新 |
| 部署状态 | v0.2.0 已发布至 GitHub Pages |

#### F. 数据治理规范

| 文档 | 说明 |
|------|------|
| `BTED_数据入库标准流程_v0.2.md` | 来源登记 → 标准化 → 策展 → 发布的完整 SOP |
| `BTED_数据发布接口_v0.2.md` | 发布目录结构与文件格式规范 |
| `证据分层与发布边界.md` | 六层证据类别定义及公开/审计边界 |
| `dictionary_patch_proposal.md` | 两份枚举值新增提案（`excluded_duplicate` + `algorithm_called_endpoint`） |

---

### 1.2 未完成/待完善功能

#### 最优先：外部来源正式入库（Fuchs / Cascino / TERMITe 共 12 来源）

当前状态：端点表构建完成，12 个来源在 registry 中均为 `to_review` 状态。

**前置条件（需团队确认）：**

1. **字典提案评审**（`draft/dictionary_patch_proposal.md`）
   - **提案一**：`processing_status` 新增 `excluded_duplicate`，用于 Cascino 2026 的 Eco/Bsu 重分析留痕行（`BTED_EXT_2026_105`）
   - **提案二**：`primary_evidence_class` / `evidence_class` 新增 `algorithm_called_endpoint`，用于 TERMITe 8 个新来源（当前端点表已使用该值，提案确认前视为"提案中"状态）
   - 两提案互相独立，需分别批准

2. **许可审核**
   - Fuchs 2021：CC BY-NC-ND 4.0 需要确认是否能在 BTED 中标准化再发布（NC-ND 条款可能限制）
   - Cascino 2026：CC BY 4.0（开放获取，无限制）
   - TERMITe 8 来源：各原始论文许可不同（mBio CC BY 4.0 / eLife CC BY 4.0 / Science 含 INSDC 数据共享 / NAR CC BY-NC 4.0），需统一许可策略

3. **Cascino 重分级决策评审**
   - 重分级日志：`draft/endpoints_output/cascino_reclassification_changelog.md`
   - 关键点：196 行次级置信度数据（`diffuse end (diffuse peak)` + `unclear` 有峰位行）重新纳入端点表，使用了现有枚举值 `called_endpoint`，未新增枚举
   - 建议团队确认该决策是否接受

**后续技术工作：**
- Fuchs 75 行 unresolved strand：已单独留存，建议人工核查 GFF 补链向
- TERMITe 4 行 POT≠summit：已在 note 标注，建议人工复核低置信边界峰
- 更新 12 来源 registry 状态（`to_review` → 按流程推进）
- 外部来源的 JBrowse 2 配置生成与站点集成
- CI 接入新来源的验证和部署

#### 中期规划

| 待办项 | 说明 |
|--------|------|
| BATTER 深度学习预测数据层 | 按四层数据愿景（观测信号 → 实验端点 → 增强数据 → 预测数据），预测数据为独立层，需明确 UI 设计和发布策略 |
| 启动子（Promoter）数据管线 | 导师已确认终止子数据模型可复用至启动子数据整理 |

#### 远期/已知限制

| 待办项 | 说明 |
|--------|------|
| 后端查询接口 | 当前纯静态网站不适合跨来源基因级统计、信号强度比较等复杂查询 |
| Cascino 排除行逐行记录 | 2,540 行排除行未逐行落文件（exclusion report 仅含统计），如需逐行可追溯可补充生成 |

---

## 二、数据完整性确认

### 2.1 已发布数据（BTED v0.2.0）

| 数据范围 | 状态 | 记录数 |
|----------|------|--------|
| BATTER Table S1 13 篇文献 | **已完成**，已通过 CI/CD 发布至 GitHub Pages | 22 来源 / 21 公开 / 1 audit_only / 28,399 端点 / 20 组装 |

### 2.2 外部来源数据

| 批次 | 数据量 | 当前状态 | 登记 source_id |
|------|--------|----------|----------------|
| Fuchs 2021（C. difficile RNAtag-seq） | 1,967 端点 + 75 行辅助 | 端点表完成，registry 状态 `to_review` | `BTED_EXT_2026_101` |
| Cascino 2026 Syn_WT（S. elongatus） | 474 端点 | 同上 | `BTED_EXT_2026_102` |
| Cascino 2026 Syn_Δmfd_rep1 | 384 端点 | 同上 | `BTED_EXT_2026_103` |
| Cascino 2026 Syn_Δmfd_rep2 | 399 端点 | 同上 | `BTED_EXT_2026_104` |
| Cascino 2026 Eco/Bsu 重分析（留痕行） | 不收录（与 BATTER_S1_001/003 重叠） | `excluded_duplicate` 提案待确认 | `BTED_EXT_2026_105` |
| TERMITe B. subtilis a（Chabbra 2022） | 630 端点 | 端点表完成，registry 状态 `to_review` | `BTED_EXT_2026_106` |
| TERMITe B. subtilis b（Mandell 2021） | 1,153 端点 | 同上 | `BTED_EXT_2026_107` |
| TERMITe B. subtilis c（Dar 2016） | 974 端点 | 同上 | `BTED_EXT_2026_108` |
| TERMITe E. faecalis（Dar 2016） | 779 端点 | 同上 | `BTED_EXT_2026_109` |
| TERMITe L. monocytogenes（Dar 2016） | 860 端点 | 同上 | `BTED_EXT_2026_110` |
| TERMITe B. subtilis d（Mondal 2016） | 1,198 端点 | 同上 | `BTED_EXT_2026_111` |
| TERMITe E. coli b（Choe 2022） | 949 端点 | 同上 | `BTED_EXT_2026_112` |
| TERMITe E. coli a（TERMITe 自有数据） | 686 端点 | 同上 | `BTED_EXT_2026_113` |

**额外数据备注：**
- BATTER 增强数据（Augmentation data）：约 250 万条增强训练序列，42,637 OTU、2,385,587 个实例，已通过 `bted-augmentation.html` 页面展示，但属预测数据层，不属于核心端点发布
- 各外部来源的原始数据文件（xlsx/csv）保留在 `draft/` 对应子目录中

### 2.3 数据处理流程概要

**Table S1 标准化路径：**
原始补充材料（xlsx） → 坐标体系确认（1-based/0-based） → 24 列端点表 + BED6 坐标 → `endpoints.tsv` + `endpoints.bed` + `fields.json` + `manifest.json` → 发布目录 → 网站集成（JBrowse + record 页面）

**Fuchs 2021 构建路径：**
原始 Dataset S4（TTSs sheet） → 链向从 GFF 注释推断（`fuchs_strand_inference_result.tsv`） → 标准化端点表 + 75 行 unresolved 留存

**Cascino 2026 构建路径：**
原始 Table S1（s0003.xlsx，3 sheets） → 按定义重分级判断（diffuse peak + unclear 含峰位重新纳入） → 两级置信度端点表（`author_called_endpoint` + `called_endpoint`）

**TERMITe 构建路径：**
`termite_parsed.csv`（37 列） → coord_valid 筛选 → 坐标取 summit_coordinate（1-based） → 24 列端点表 + BED 格式换算

### 2.4 缺失/未导入数据标注

| 数据 | 状态 | 说明 |
|------|------|------|
| BATTER 全基因组预测（BED，约 242M+ OTU） | **未纳入** | 按"预测数据不混入实验数据库"原则，暂不纳入 BTED 公开版本，作未来规划 |
| Cascino 2026 排除行（2,540 行） | **未逐行落文件** | 可在源文件 `s0003.xlsx` 中按 sheet + gene_term 精确复现；exclusion report 仅含统计计数 |
| Fuchs 2021 unresolved strand 75 行 | **已单独留存，待人工核查** | 位于 `fuchs_2021_unresolved_strand_75rows.tsv`，含 locus_tag / 坐标 / confidence / note |
| BATTER 增强数据 | **已展示**，但非端点数据 | 已通过独立页面展示，不属于核心端点发布范围 |

---

## 三、交接要点与后续建议

### 3.1 关键文件索引

| 文件 | 路径（repo 相对路径） | 用途 |
|------|----------------------|------|
| 外部来源登记表 | `draft/external_literature_source_intake_final.tsv` | 12 + 1（留痕）来源的完整元数据 |
| 端点表构建汇总报告 | `draft/endpoints_output/README_endpoints_build.md` | 行数核对、排除去向、evidence_class 合规 |
| Cascino 重分级变更说明 | `draft/endpoints_output/cascino_reclassification_changelog.md` | 分级决策依据与逐项明细 |
| TERMITe 端点摘要 | `draft/endpoints_output/termite_endpoints_summary.txt` | 8 来源逐源校验数据 |
| 字典修改提案 | `draft/dictionary_patch_proposal.md` | 提案一（`excluded_duplicate`）+ 提案二（`algorithm_called_endpoint`） |
| 数据入库 SOP | `docs/standards/BTED_数据入库标准流程_v0.2.md` | 状态推进路径、发布流程 |
| 来源登记表 | `data/registry/batter_s1_source_registry.tsv` | 全部来源（含已发布 + 草案）的元数据 |

### 3.2 建议处理顺序

1. 审阅 `dictionary_patch_proposal.md` 确认两提案
2. 评审 Cascino 重分级决策（`cascino_reclassification_changelog.md`）
3. 确定 Fuchs CC BY-NC-ND 4.0 许可的再发布策略
4. 将 12 来源 registry 状态从 `to_review` 沿推进路径前进
5. 生成 JBrowse 2 配置并集成至站点
6. 更新 CI 工作流以覆盖新来源

---
