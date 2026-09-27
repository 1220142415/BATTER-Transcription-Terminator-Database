from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseDocumentationTests(unittest.TestCase):
    def test_release_notes_describe_per_study_packages(self) -> None:
        release = (ROOT / "docs/releases/v0.3.0.md").read_text(encoding="utf-8")
        for required in (
            "`endpoints.gff3.gz`",
            "`metadata.tsv`",
            "`metadata.json`",
            "`gene_associations.tsv.gz`",
            "`condition_observations.tsv.gz`",
            "`release.json`",
            "`SHA256SUMS.txt`",
            "studies/PMID_<pmid>/",
            "1-based",
            "`table_defaults.endpoints`",
            "345 条",
            "`ann_<field>`",
            "`annotation_field_map`",
            "raw_data_accessions",
        ):
            with self.subTest(required=required):
                self.assertIn(required, release)

        self.assertNotIn("`annotations.jsonl.gz`", release)
        self.assertNotIn("`gene_associations.jsonl.gz`", release)
        self.assertNotIn("`condition_observations.jsonl.gz`", release)
        self.assertNotIn("`endpoints.tsv.gz`", release)
        self.assertIn("本版没有根级 `endpoints.gff3.gz`、`sources.json` 或关系 TSV", release)
        source_header = next(line for line in release.splitlines() if line.startswith("source_id"))
        self.assertEqual(source_header.split("\t"), [
            "source_id", "species", "assembly", "pmid", "title", "assay",
            "record_count", "evidence_class", "release_status", "article_license",
            "redistribution_status", "raw_data_accessions", "known_limitations",
        ])

    def test_download_and_augmentation_boundaries_are_documented(self) -> None:
        release = (ROOT / "docs/releases/v0.3.0.md").read_text(encoding="utf-8")
        self.assertIn("网站下载页以 PMID 研究包为主入口", release)
        self.assertIn("站点组装时另生成按来源拆分的 GFF3", release)
        self.assertIn("研究目录内的压缩 TSV", release)
        self.assertIn("data/registry/internal/augmentation/", release)
        self.assertIn("预测结果，尚无实验确认", release)
        self.assertIn("逐实例坐标", release)

        deployment = (ROOT / "docs/v0.3/deployment.md").read_text(encoding="utf-8")
        self.assertNotIn("/api/augmentation", deployment)
        self.assertIn("GFF3 adapter", deployment)
        self.assertIn("studies/PMID_<pmid>/", deployment)


if __name__ == "__main__":
    unittest.main()
