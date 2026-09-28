from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "bted_validate_site", ROOT / "scripts/validate-site.py"
)
assert SPEC is not None and SPEC.loader is not None
validate_site = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validate_site
SPEC.loader.exec_module(validate_site)


class SiteFormatValidationTests(unittest.TestCase):
    def test_pinned_hf_base_url_in_release_manifest_is_accepted(self) -> None:
        commit = "0123456789abcdef0123456789abcdef01234567"
        base = f"https://huggingface.co/datasets/liurulong/terminator/resolve/{commit}/v0.3.0"
        test_root = ROOT / "tmp"
        test_root.mkdir(exist_ok=True)
        site = test_root / f"validate-hf-release-{uuid.uuid4().hex}"
        site.mkdir()
        try:
            assets = site / "assets"
            assets.mkdir()
            (assets / "data-release.json").write_text(json.dumps({
                "releaseVersion": "v0.3.0",
                "baseUrl": base,
                "revision": commit,
            }), encoding="utf-8")
            problems: list[str] = []

            validate_site.validate_fixed_hf_release(site, problems)
        finally:
            shutil.rmtree(site)

        self.assertEqual(problems, [])

    def test_only_canonical_versioned_v03_download_tables_are_allowed(self) -> None:
        canonical = {
            "studies/PMID_31594819/endpoints.gff3.gz": ".gff3.gz",
            "studies/PMID_31594819/gene_associations.tsv.gz": ".tsv.gz",
            "studies/PMID_37402717/condition_observations.tsv.gz": ".tsv.gz",
        }
        for name, compound_suffix in canonical.items():
            with self.subTest(name=name):
                self.assertTrue(validate_site.is_allowed_download_file(
                    f"downloads/v0.3.0/{name}", ".gz", compound_suffix
                ))

        self.assertTrue(validate_site.is_allowed_download_file(
            "downloads/v0.3.0/studies/PMID_31594819/metadata.tsv", ".tsv", ".tsv"
        ))
        for rel, compound_suffix in (
            ("downloads/v0.3.0/endpoints.gff3.gz", ".gff3.gz"),
            ("downloads/v0.3.0/sources.tsv", ".tsv"),
            ("downloads/gene_associations.tsv.gz", ".tsv.gz"),
            ("downloads/v0.2.0/gene_associations.tsv.gz", ".tsv.gz"),
            ("downloads/v0.3.0/other.tsv.gz", ".tsv.gz"),
            ("downloads/v0.3.0/endpoints.tsv", ".tsv"),
            ("downloads/v0.3.0/annotations.jsonl.gz", ".jsonl.gz"),
        ):
            with self.subTest(rel=rel):
                self.assertFalse(validate_site.is_allowed_download_file(
                    rel, ".gz" if rel.endswith(".gz") else ".tsv", compound_suffix
                ))

    def test_assembly_zip_allows_only_gff3_and_metadata(self) -> None:
        self.assertEqual(
            validate_site.check_assembly_zip_members(
                ["GCF_000012525.1/studies/PMID_42148773/endpoints.gff3.gz", "GCF_000012525.1/metadata.tsv"], "assembly.zip"
            ),
            [],
        )

    def test_metadata_only_assembly_zip_is_allowed(self) -> None:
        self.assertEqual(
            validate_site.check_assembly_zip_members(["GCF_000005845.2/metadata.tsv"]), []
        )

    def test_assembly_zip_rejects_bed_and_other_exports(self) -> None:
        issues = validate_site.check_assembly_zip_members(
            ["endpoints.bed", "endpoints.tsv", "metadata.tsv", "metadata.json"], "assembly.zip"
        )
        self.assertEqual(len(issues), 1)
        self.assertIn("endpoints.bed", issues[0])
        self.assertIn("metadata.json", issues[0])


if __name__ == "__main__":
    unittest.main()
