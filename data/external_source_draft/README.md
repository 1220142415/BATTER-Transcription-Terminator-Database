# External Source Draft Data (外部来源端点表草案)

本目录包含 BATTER Table S1 之外的三批外部实验来源的端点表标准化产物。

## 数据批次总览

| 批次 | 来源数 | 端点行数 | 状态 |
|------|--------|----------|------|
| Fuchs 2021 (PMID 34131082) | 1 (C. difficile) | 1,967 | Draft |
| Cascino 2026 (PMID 42148773) | 3 (S. elongatus) | 1,257 | Draft |
| TERMITe 8 sources | 8 (B. subtilis×4, E. coli×2, E. faecalis, L. monocytogenes) | 7,229 | Draft |
| **合计** | **12** | **10,453** | **Draft** |

## 文件清单

### 端点表 (12 files, 24-column schema)
- `BTED_EXT_2026_101_fuchs2021_endpoints.tsv` — Fuchs 2021
- `BTED_EXT_2026_102_cascino_synwt_endpoints.tsv` — Cascino 2026 Syn_WT
- `BTED_EXT_2026_103_cascino_mfdrep1_endpoints.tsv` — Cascino 2026 Syn_Δmfd_rep1
- `BTED_EXT_2026_104_cascino_mfdrep2_endpoints.tsv` — Cascino 2026 Syn_Δmfd_rep2
- `BTED_EXT_2026_106~113_*.tsv` — TERMITe 8 sources

### 构建脚本
- `build_fuchs_endpoints.py`
- `build_cascino_endpoints.py`
- `build_termite_endpoints.py`

### 辅助文件
- `README_endpoints_build.md` — 构建汇总与行数核对
- `cascino_exclusion_report.txt` — Cascino 排除明细
- `cascino_reclassification_changelog.md` — Cascino 重分级决策记录
- `termite_endpoints_summary.txt` — TERMITe 8 来源逐源校验
- `fuchs_2021_unresolved_strand_75rows.tsv` — Fuchs 链向无法确定的 75 行

### 字典提案
- `dictionary_patch_proposal.md` — 两份枚举值新增提案

### 来源登记
- `external_literature_source_intake_final.tsv` — 12 + 1（留痕）来源的完整元数据

## 状态说明

- 全部 12 个来源在 registry 中均为 `to_review` 状态
- 端点表已通过行数守恒校验和坐标换算验证
- 正式入库前需完成：字典提案确认、许可审核、Cascino 重分级评审
- 详细交接说明见同目录 `Wrapup.md`