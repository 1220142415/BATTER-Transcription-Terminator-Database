from __future__ import annotations

import csv
import gzip
import hashlib
import json
import re
import shutil
import sys
import uuid
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


ROOT = Path(__file__).resolve().parents[1]
TEMP_ROOT = ROOT / "tmp"
TEMP_ROOT.mkdir(exist_ok=True)
sys.path.insert(0, str(ROOT / "scripts"))

import build_v0_4_site  # noqa: E402
import build_batter_browser  # noqa: E402


@contextmanager
def temporary_directory() -> Iterator[Path]:
    path = TEMP_ROOT / f"v04-site-test-{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def feature(seqid: str, source: str, position: int, end_id: str) -> str:
    return (
        f"{seqid}\t{source}\tterminator_endpoint\t{position}\t{position}\t.\t+\t.\t"
        f"ID={end_id};score=3.5\n"
    )


def create_release(root: Path, *, mismatched_count: bool = False) -> tuple[Path, list[dict[str, str]]]:
    assembly = "GCF_000012525.1"
    genome = root / "genomes" / assembly
    study = genome / "studies" / "PMID_42148773"
    study.mkdir(parents=True)
    gff3_text = (
        "##gff-version 3\n"
        "##sequence-region CP000100.1 1 1000\n"
        + feature("CP000100.1", "BTED_EXT_2026_102", 10, "A1")
        + feature("CP000100.1", "BTED_EXT_2026_102", 20, "A2")
        + feature("CP000100.1", "BTED_EXT_2026_103", 30, "B1")
    )
    gff3_path = study / "endpoints.gff3.gz"
    with gzip.open(gff3_path, "wt", encoding="utf-8", newline="\n") as handle:
        handle.write(gff3_text)
    association_path = study / "gene_associations.tsv.gz"
    with gzip.open(association_path, "wt", encoding="utf-8", newline="\n") as handle:
        handle.write("source_id\tgene\tcoordinate\nBTED_EXT_2026_102\tgeneA\t10\n")

    rows = [
        {
            "source_id": "BTED_EXT_2026_102",
            "pmid": "42148773",
            "species": "Cyanobacterium test strain",
            "assembly": assembly,
            "title": "A study with two source records",
            "assay": "dRNA-seq",
            "record_count": "3" if mismatched_count else "2",
            "evidence_class": "author_called_endpoint",
            "release_status": "published_standardized",
            "article_license": "CC BY 4.0",
            "redistribution_status": "verified_redistributable",
            "raw_data_accessions": "PRJNA123456",
            "known_limitations": "Study-specific source note.",
            "study_gff3": "studies/PMID_42148773/endpoints.gff3.gz",
            "gene_associations": "studies/PMID_42148773/gene_associations.tsv.gz",
            "condition_observations": "",
        },
        {
            "source_id": "BTED_EXT_2026_103",
            "pmid": "42148773",
            "species": "Cyanobacterium test strain",
            "assembly": assembly,
            "title": "A study with two source records",
            "assay": "dRNA-seq",
            "record_count": "1",
            "evidence_class": "author_called_endpoint",
            "release_status": "published_standardized",
            "article_license": "CC BY 4.0",
            "redistribution_status": "verified_redistributable",
            "raw_data_accessions": "PRJNA123456",
            "known_limitations": "",
            "study_gff3": "studies/PMID_42148773/endpoints.gff3.gz",
            "gene_associations": "",
            "condition_observations": "",
        },
    ]
    metadata_path = genome / "metadata.tsv"
    with metadata_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=build_v0_4_site.REQUIRED_METADATA_COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    release_files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        release_files.append({"path": relative, "byte_size": path.stat().st_size, "sha256": sha256(path)})
    manifest = {
        "schema_version": "1.0",
        "release_version": "v0.4.0",
        "summary": "Synthetic fixture",
        "counts": {"published_source_count": 2, "endpoint_count": 3},
        "legacy_archive": {},
        "genomes": [{
            "assembly": assembly,
            "metadata_path": f"genomes/{assembly}/metadata.tsv",
            "source_count": 2,
            "study_count": 1,
            "endpoint_count": 3,
            "studies": [{"pmid": "42148773", "path": "studies/PMID_42148773", "source_ids": [row["source_id"] for row in rows]}],
        }],
        "files": release_files,
    }
    (root / "release.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return root, rows


class V04SiteBuildTests(unittest.TestCase):
    def test_home_counts_cover_all_datasets_without_counting_audit_only_records(self) -> None:
        records = [["GCF_1", *([""] * 4), 2, 20, 3, 30, "matched", 10, ""],
                   ["GCF_2", *([""] * 4), 1, 10, 0, 0, "matched", 20, ""]]
        content = build_v0_4_site.home_content([{"assembly": "GCF_1", "metadata_rows": [
            {"pmid": "1", "release_status": "published_standardized", "record_count_number": 3},
            {"pmid": "1", "release_status": "published_standardized", "record_count_number": 4},
            {"pmid": "2", "release_status": "audit_only", "record_count_number": 100},
        ]}, {"assembly": "GCF_3", "metadata_rows": [
            {"pmid": "2", "release_status": "audit_only", "record_count_number": 100},
            {"pmid": "3", "release_status": "published", "record_count_number": 0},
        ]}], records)
        self.assertIn("3</strong><span>Catalog genomes", content)
        self.assertIn("30</strong><span>Predicted regions", content)
        self.assertIn("6</strong><span>Augmentation / Rfam regions", content)
        self.assertIn("1</strong><span>Experimental genomes", content)
        self.assertIn("1</strong><span>Experimental publications", content)
        self.assertIn("7</strong><span>Experimental records", content)
        self.assertNotIn("107</strong>", content)

    def test_genome_site_combines_evidence_browser_downloads_and_legacy_redirects(self) -> None:
        with temporary_directory() as temp:
            release_root, rows = create_release(temp / "release")
            _, release_files = build_v0_4_site.read_release(release_root)
            asset_map = {
                path: {
                    "url": f"downloads/v0.4.0/{path}",
                    "byte_size": int(item["byte_size"]),
                    "sha256": item["sha256"],
                    "revision": "local",
                    "asset_kind": "tsv" if path.endswith(".tsv") else "gff3",
                }
                for path, item in release_files.items()
            }
            site = temp / "site"
            taxonomy = temp / "taxonomy.tsv"
            taxonomy.write_text(
                "assembly\tphylum\tclass\tgenus\n"
                "GCF_000012525.1\tCyanobacteria\tCyanophyceae\tCyanobacterium\n",
                encoding="utf-8",
            )
            build_v0_4_site.build_site(
                site,
                release_root,
                asset_map,
                {"GCF_000012525.1": "assemblies/GCF_000012525.1.config.json"},
                {row["source_id"]: f"bted_v04_{row['source_id'].lower()}_endpoints" for row in rows},
                taxonomy_path=taxonomy,
                computational_genomes=json.loads((ROOT / "data/registry/batter-browser.json").read_text(encoding="utf-8"))["genomes"],
            )

            landing = (site / "index.html").read_text(encoding="utf-8")
            home = (site / "genomes.html").read_text(encoding="utf-8")
            genome = (site / "genomes/GCF_000012525.1.html").read_text(encoding="utf-8")
            self.assertIn("GCF_000012525.1", home)
            self.assertIn("3</strong><span>Experimental records", landing)
            self.assertIn("1</strong><span>Experimental publications", landing)
            self.assertIn("40,000</strong><span>Catalog genomes", landing)
            self.assertIn("116,801,134</strong><span>Predicted regions", landing)
            self.assertIn("https://doi.org/10.1186/s40168-026-02454-1", landing)
            self.assertIn("https://github.com/xu-research-lab/BATTER", landing)
            self.assertNotIn("data-genome-search-form", landing)
            self.assertIn('href="genomes.html"', landing)
            self.assertIn('class="genome-directory-table"', home)
            self.assertIn('class="genome-taxonomy-panel"', home)
            for rank in ("phylum", "class", "order", "family", "genus"):
                self.assertIn(f'data-taxonomy-rank="{rank}"', home)
            self.assertIn('data-taxonomy-genus="Cyanobacterium"', home)
            for removed in ("Phylum", "Studies", "Methods", "Signal", "Open"):
                self.assertNotIn(f'data-label="{removed}"', home)
            for column in ("Genome ID", "Genome source", "Organism", "Taxonomy", "Assembly size", "Terminator data", "Annotation"):
                self.assertIn(f'data-label="{column}"', home)
            self.assertIn('<td data-label="Genome source">NCBI RefSeq</td>', home)
            self.assertIn('2,742,269 bp', home)
            self.assertIn('2 contigs', home)
            self.assertIn('experimental endpoints</span>', home)
            self.assertIn('<a class="genome-table-name" href="genomes/GCF_000012525.1.html"><code>GCF_000012525.1</code></a>', home)
            for removed in ("study", "assay", "evidence", "signal"):
                self.assertNotIn(f'data-filter-{removed}', home)
            self.assertLess(home.index('class="genome-directory-panel"'), home.index('data-genome-search-form'))
            self.assertLess(home.index('class="genome-filter-bar"'), home.index('class="genome-taxonomy-panel"'))
            self.assertEqual(home.count('data-genome-search-form'), 1)
            self.assertIn('data-source-filter', home)
            self.assertNotIn('class="genome-card"', home)
            self.assertIn("../css/style.css", genome)
            self.assertIn("../assets/genome-page.js", genome)
            self.assertIn("Study GFF3", genome)
            self.assertIn("Gene associations TSV", genome)
            self.assertIn("No experimental signal", genome)
            self.assertIn("data-share-view", genome)
            self.assertNotIn("Article licence", genome)
            self.assertNotIn("data-source-select", genome)
            self.assertIn("data-download-genome-package", genome)
            self.assertNotIn("genome-title-actions", genome)
            self.assertLess(genome.index('class="genome-studies"'), genome.index('class="genome-downloads"'))
            self.assertIn('data-zip-path="GCF_000012525.1/metadata.tsv"', genome)
            self.assertIn('data-zip-path="GCF_000012525.1/studies/PMID_42148773/endpoints.gff3.gz"', genome)
            self.assertIn('data-zip-path="GCF_000012525.1/studies/PMID_42148773/gene_associations.tsv.gz"', genome)
            self.assertNotIn("metadata.json", genome)
            self.assertNotIn('href="downloads/v0.4.0/release.json"', genome)

            old_browser = (site / "browser.html").read_text(encoding="utf-8")
            self.assertIn('"source_id", "loc", "session", "tracks", "highlight"', old_browser)
            self.assertIn('q.get(key)', old_browser)
            self.assertIn("genomes/", old_browser)
            old_assembly = (site / "assemblies/GCF_000012525.1.html").read_text(encoding="utf-8")
            self.assertIn('"source_id","loc","session","tracks","highlight"', old_assembly)
            self.assertIn('target.searchParams.set(k,v)', old_assembly)
            self.assertIn('"loc"', old_assembly)

            (site / "assets").mkdir(exist_ok=True)
            build_batter_browser.build(site)
            combined = (site / "genomes.html").read_text(encoding="utf-8")
            self.assertEqual(len(re.findall(r'<th[ >]', combined)), 7)
            self.assertEqual(len(re.findall(r'<td[ >]', combined)), 7)
            self.assertIn('data-sort="predictions" title="Sort by predictions">Terminator data', combined)
            catalogue = json.loads((site / "assets/batter-browser.json").read_text(encoding="utf-8"))
            self.assertEqual(catalogue["columns"][12], "source_collection")
            self.assertEqual(next(row[12] for row in catalogue["genomes"] if row[0] == "2228664028"), "IMG")
            self.assertEqual(catalogue["reference_sizes"]["GCF_000012525.1"], [2742269, 2])
            self.assertIn('Top phyla in this release', (site / "index.html").read_text(encoding="utf-8"))

    def test_home_phyla_deduplicate_assemblies_and_keep_unclassified(self) -> None:
        records = [[f"GCF_{i}", *([""] * 10), f"p__Group{i}"] for i in range(10)]
        records += [["GCF_UNKNOWN", *([""] * 10), "d__Bacteria;p__"]]
        chart = build_batter_browser.phylum_content(records, {"GCF_0": "Group1", "GCF_EXPERIMENT": "Group1"})
        self.assertIn('12 catalog genomes', chart)
        self.assertIn('phylum=Group1', chart)
        self.assertIn('<strong>3</strong>', chart)
        self.assertEqual(chart.count('class="home-phylum-row"'), 9)
        self.assertIn('<span>Unclassified</span>', chart)
        self.assertNotIn('phylum=Unclassified', chart)
        self.assertIn('width:100.00%', chart)

    def test_taxonomy_requires_an_entry_for_each_genome(self) -> None:
        with temporary_directory() as temp:
            taxonomy = temp / "taxonomy.tsv"
            taxonomy.write_text("assembly\tphylum\tgenus\n", encoding="utf-8")
            with self.assertRaisesRegex(build_v0_4_site.SiteBuildError, "missing assemblies"):
                build_v0_4_site.load_genome_taxonomy(
                    taxonomy, [{"assembly": "GCF_000012525.1"}],
                )

    def test_browser_tracks_are_source_filtered_and_reference_ids_are_mapped(self) -> None:
        with temporary_directory() as temp:
            release_root, _rows = create_release(temp / "release")
            original = release_root / "genomes/GCF_000012525.1/studies/PMID_42148773/endpoints.gff3.gz"
            original_hash = sha256(original)
            output_root = temp / "browser-objects"
            rows = build_v0_4_site.materialize_browser_tracks(release_root, output_root)
            self.assertEqual(len(rows), 2)
            first = output_root / "v0.4.0/tracks/BTED_EXT_2026_102/endpoints.gff3"
            second = output_root / "v0.4.0/tracks/BTED_EXT_2026_103/endpoints.gff3"
            first_lines = first.read_text(encoding="utf-8").splitlines()
            second_lines = second.read_text(encoding="utf-8").splitlines()
            first_features = [line for line in first_lines if line and not line.startswith("#")]
            second_features = [line for line in second_lines if line and not line.startswith("#")]
            self.assertEqual(len(first_features), 2)
            self.assertEqual(len(second_features), 1)
            self.assertTrue(all(line.split("\t")[1] == "BTED_EXT_2026_102" for line in first_features))
            self.assertTrue(all(line.split("\t")[1] == "BTED_EXT_2026_103" for line in second_features))
            self.assertTrue(all(line.split("\t")[0] == "NC_007604.1" for line in first_features + second_features))
            self.assertIn("ID=A1;score=3.5", first_features[0])
            self.assertEqual(sha256(original), original_hash)

    def test_materializer_rejects_metadata_count_mismatch(self) -> None:
        with temporary_directory() as temp:
            release_root, _rows = create_release(temp / "release", mismatched_count=True)
            with self.assertRaisesRegex(build_v0_4_site.SiteBuildError, "expected 3"):
                build_v0_4_site.materialize_browser_tracks(release_root, temp / "browser-objects")


if __name__ == "__main__":
    unittest.main()
