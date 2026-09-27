from __future__ import annotations

import hashlib
import io
import json
import shutil
import sys
import tarfile
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


ROOT = Path(__file__).resolve().parents[1]
TEST_TEMP_ROOT = ROOT / "tmp"
TEST_TEMP_ROOT.mkdir(exist_ok=True)
sys.path.insert(0, str(ROOT / "scripts"))
import stage_site  # noqa: E402


@contextmanager
def temporary_directory() -> Iterator[Path]:
    path = TEST_TEMP_ROOT / f"stage-site-test-{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path)


class StageSiteTests(unittest.TestCase):
    HF_BASE = "https://huggingface.co/datasets/liurulong/terminator/resolve/0123456789abcdef0123456789abcdef01234567/v0.3.0"

    def write_archive(self, path: Path, entries: dict[str, bytes]) -> None:
        with tarfile.open(path, "w:gz") as archive:
            for name, content in entries.items():
                info = tarfile.TarInfo(name)
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))

    def test_release_archive_checksum_is_required_to_match(self) -> None:
        with temporary_directory() as root:
            archive = root / stage_site.ARCHIVE_NAME
            archive.write_bytes(b"release bytes")
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            checksum = root / f"{archive.name}.sha256"
            checksum.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")

            self.assertEqual(stage_site.verify_archive_sha256(archive, checksum), digest)
            checksum.write_text(f"{'0' * 64}  {archive.name}\n", encoding="utf-8")
            with self.assertRaisesRegex(stage_site.StageError, "mismatch"):
                stage_site.verify_archive_sha256(archive, checksum)

    def test_staged_release_keeps_one_public_package_per_pmid(self) -> None:
        with temporary_directory() as root:
            output = root / "downloads/v0.3.0"
            output.mkdir(parents=True)
            stage_site.copy_v03_download_tables(output)

            study_root = output / "studies"
            study_dirs = sorted(path for path in study_root.glob("PMID_*") if path.is_dir())
            self.assertEqual(len(study_dirs), 13)
            self.assertEqual(
                {path.name for path in output.iterdir()},
                {"studies", "release.json", "SHA256SUMS.txt"},
            )
            release = json.loads((output / "release.json").read_text(encoding="utf-8"))
            for relative, entry in release["files"].items():
                self.assertEqual(entry["path"], relative)
                self.assertTrue((output / entry["path"]).is_file())
            for study_dir in study_dirs:
                metadata = json.loads((study_dir / "metadata.json").read_text(encoding="utf-8"))
                self.assertEqual(study_dir.name, f"PMID_{metadata['pmid']}")
                self.assertTrue(metadata["sources"])
                self.assertTrue((study_dir / "endpoints.gff3.gz").is_file())
                self.assertTrue((study_dir / "metadata.tsv").is_file())
            self.assertTrue((study_root / "PMID_31594819/gene_associations.tsv.gz").is_file())
            self.assertTrue((study_root / "PMID_37402717/condition_observations.tsv.gz").is_file())
            self.assertFalse((output / "endpoints.gff3.gz").exists())
            self.assertFalse((output / "sources.json").exists())
            self.assertFalse((output / "sources.tsv").exists())

    def test_safe_extraction_requires_expected_root_and_rejects_traversal(self) -> None:
        with temporary_directory() as root:
            archive = root / "valid.tar.gz"
            self.write_archive(
                archive,
                {f"{stage_site.PACKAGE_NAME}/catalog.json": b"{}\n"},
            )
            extracted = stage_site.safe_extract_release(archive, root / "valid")
            self.assertEqual((extracted / "catalog.json").read_bytes(), b"{}\n")

            unsafe = root / "unsafe.tar.gz"
            self.write_archive(
                unsafe,
                {f"{stage_site.PACKAGE_NAME}/../../outside.txt": b"blocked"},
            )
            destination = root / "unsafe"
            with self.assertRaisesRegex(stage_site.StageError, "Unsafe path"):
                stage_site.safe_extract_release(unsafe, destination)
            self.assertFalse((root / "outside.txt").exists())

    def test_hf_base_requires_fixed_dataset_commit_and_release_prefix(self) -> None:
        base, revision = stage_site.normalize_hf_data_base_url(self.HF_BASE)
        self.assertEqual(revision, "0123456789abcdef0123456789abcdef01234567")
        self.assertEqual(base, self.HF_BASE)
        for value in (
            "https://huggingface.co/datasets/liurulong/terminator/resolve/main/v0.3.0",
            "https://huggingface.co/datasets/other/repo/resolve/0123456789abcdef0123456789abcdef01234567/v0.3.0",
            self.HF_BASE + "?download=true",
        ):
            with self.subTest(value=value), self.assertRaises(stage_site.StageError):
                stage_site.normalize_hf_data_base_url(value)

    def test_nonredistributable_signed_log_track_is_removed_but_raw_tracks_remain(self) -> None:
        derived = {
            "trackId": "derived_signal",
            "type": "MultiQuantitativeTrack",
            "adapter": {
                "type": "MultiWiggleAdapter",
                "subadapters": [
                    {"type": "BigWigAdapter", "bigWigLocation": {"uri": "assets/signed-log.forward.bw"}},
                    {"type": "BigWigAdapter", "bigWigLocation": {"uri": "assets/signed-log.reverse.bw"}},
                ],
            },
        }
        derived["adapter"]["subadapters"][0]["bigWigLocation"]["uri"] = (
            "assets/BATTER_S1_001__signal.forward.signed-log10-ui-v4.bw"
        )
        derived["adapter"]["subadapters"][1]["bigWigLocation"]["uri"] = (
            "assets/BATTER_S1_001__signal.reverse.signed-log10-ui-v4.bw"
        )
        raw = {
            "trackId": "raw_signal",
            "type": "QuantitativeTrack",
            "adapter": {"type": "BigWigAdapter", "bigWigLocation": {"uri": "assets/signal.forward.bw"}},
        }
        config = {
            "tracks": [derived, raw],
            "defaultSession": {"views": [{"tracks": [
                {"configuration": "derived_signal"}, {"configuration": "raw_signal"}
            ]}]},
            "aggregateTextSearchAdapters": [{
                "textSearchAdapterId": "derived_search",
                "ixFilePath": {"uri": "assets/generated.ix"},
                "ixxFilePath": {"uri": "assets/generated.ixx"},
            }],
        }

        removed = stage_site._remove_nonredistributable_signal_tracks(config)
        removed_search = stage_site._remove_unpublished_text_search_indices(config, {})

        self.assertEqual(removed, {"derived_signal"})
        self.assertEqual(removed_search, {"derived_search"})
        self.assertEqual([track["trackId"] for track in config["tracks"]], ["raw_signal"])
        self.assertNotIn("aggregateTextSearchAdapters", config)
        self.assertEqual(
            [track["configuration"] for track in config["defaultSession"]["views"][0]["tracks"]],
            ["raw_signal"],
        )

    def test_jbrowse_uri_rewrite_uses_approved_logical_path_and_checks_hash(self) -> None:
        with temporary_directory() as root:
            package = root / "package"
            assets = package / "assets"
            assets.mkdir(parents=True)
            asset = assets / "reference.fna"
            asset.write_bytes(b">ctg\nACGT\n")
            digest = hashlib.sha256(asset.read_bytes()).hexdigest()
            config = {"assemblies": [{"sequence": {"adapter": {"fastaLocation": {"uri": "../assets/reference.fna"}}}}]}
            mapping = {
                "assets/reference.fna": {
                    "object_path": "assemblies/GCF_TEST.1/reference/reference.fna",
                    "sha256": digest,
                    "asset_kind": "fasta",
                }
            }
            stage_site.rewrite_jbrowse_asset_uris(config, package, self.HF_BASE, mapping)
            uri = config["assemblies"][0]["sequence"]["adapter"]["fastaLocation"]["uri"]
            self.assertEqual(uri, f"{self.HF_BASE}/assemblies/GCF_TEST.1/reference/reference.fna")

            asset.write_bytes(b"changed")
            config["assemblies"][0]["sequence"]["adapter"]["fastaLocation"]["uri"] = "../assets/reference.fna"
            with self.assertRaisesRegex(stage_site.StageError, "SHA-256"):
                stage_site.rewrite_jbrowse_asset_uris(config, package, self.HF_BASE, mapping)

    def test_shared_reference_aliases_map_to_the_approved_assembly_objects(self) -> None:
        with temporary_directory() as root:
            inventory_path = root / "inventory.json"
            kinds = {
                "fasta": ("reference.fna", "reference.fna"),
                "fai": ("reference.fna.fai", "reference.fna.fai"),
                "gff3": ("genes.gff3.gz", "reference.gff3.gz"),
                "tbi": ("genes.gff3.gz.tbi", "reference.gff3.gz.tbi"),
            }
            rows = []
            representative_assets = []
            alias_assets = []
            for kind, (rep_name, alias_name) in kinds.items():
                rep_path = f"assets/SOURCE_A__{rep_name}"
                alias_path = f"assets/SOURCE_B__{alias_name}"
                representative_assets.append(rep_path)
                alias_assets.append(alias_path)
                rows.append({
                    "source_id": "SOURCE_A",
                    "asset_role": f"reference_{kind}",
                    "asset_kind": kind,
                    "bundle_path": rep_path,
                    "object_path": f"assemblies/GCF_TEST.1/reference/{rep_name}",
                    "sha256": "a" * 64,
                    "is_public": "true",
                    "redistribution_status": "verified_redistributable",
                })
            inventory_path.write_text(json.dumps({
                "rows": rows,
                "deduplicated_shared_references": [{
                    "representative_source_id": "SOURCE_A",
                    "source_ids": ["SOURCE_A", "SOURCE_B"],
                }],
            }), encoding="utf-8")

            mapping = stage_site.load_public_jbrowse_asset_paths(
                inventory_path,
                {"sources": {
                    "SOURCE_A": {"assets": representative_assets},
                    "SOURCE_B": {"assets": alias_assets},
                }},
            )

            for alias in alias_assets:
                with self.subTest(alias=alias):
                    self.assertIn(alias, mapping)
                    self.assertTrue(mapping[alias]["object_path"].startswith("assemblies/GCF_TEST.1/"))

    def test_worker_shell_keeps_runtime_and_excludes_release_data(self) -> None:
        with temporary_directory() as root:
            package = root / "package"
            (package / "static/js").mkdir(parents=True)
            (package / "static/css").mkdir(parents=True)
            (package / "index.html").write_text(
                '<script src="static/js/main.js"></script><link href="static/css/main.css">',
                encoding="utf-8",
            )
            (package / "manifest.json").write_text('{"icons":[{"src":"favicon.ico"}]}', encoding="utf-8")
            (package / "favicon.ico").write_bytes(b"icon")
            (package / "robots.txt").write_text("User-agent: *\n", encoding="utf-8")
            (package / "version.txt").write_text("4.3.0\n", encoding="utf-8")
            (package / "static/js/main.js").write_text("// runtime", encoding="utf-8")
            (package / "static/js/main.js.map").write_text("source map", encoding="utf-8")
            (package / "static/css/main.css").write_text("body {}", encoding="utf-8")
            (package / "assets").mkdir()
            (package / "assets/reference.fna").write_bytes(b"sequence")

            shell = root / "worker/jbrowse"
            files, size = stage_site.copy_worker_shell(package, shell)

            self.assertEqual(files, 7)
            self.assertGreater(size, 0)
            self.assertFalse((shell / "assets").exists())
            self.assertFalse((shell / "assets/reference.fna").exists())
            self.assertFalse((shell / "static/js/main.js.map").exists())

    def test_v03_jbrowse_overlay_points_to_generated_versioned_endpoint_gff3(self) -> None:
        with temporary_directory() as root:
            studies_path = root / "studies"
            study_dir = studies_path / "PMID_12345678"
            study_dir.mkdir(parents=True)
            source = {
                "source_id": "BATTER_S1_001",
                "registry_manifest": {
                    "source_id": "BATTER_S1_001",
                    "published_year": "2018",
                    "species": "Test species",
                    "reference_genome": "GCF_TEST.1",
                    "pmid": "12345678",
                    "paper_title": "Test paper",
                    "doi": "10.1000/test",
                    "raw_data_accessions": "GSE1",
                    "assay_family": "Term-seq",
                    "has_jbrowse": True,
                },
                "release_manifest": None,
                "registry_row": {},
                "publication_status": {
                    "release_status": "published_standardized",
                    "record_count": "1",
                    "evidence_class": "author_called_endpoint",
                    "has_jbrowse": "true",
                },
                "license_status": {},
            }
            (study_dir / "metadata.json").write_text(
                json.dumps({"release_version": "v0.3.0", "pmid": "12345678", "record_count": 1, "sources": [source]}),
                encoding="utf-8",
            )

            for mode in ("pages", "worker"):
                package = root / mode / stage_site.PACKAGE_NAME
                (package / "assemblies").mkdir(parents=True)
                old_tracks = [
                    {"trackId": "legacy_endpoints", "type": "FeatureTrack", "adapter": {"type": "BedAdapter"}, "category": ["Published experimental endpoints"]},
                    {"trackId": "signal", "type": "QuantitativeTrack", "adapter": {"type": "BigWigAdapter"}, "category": ["Observed signal"]},
                    {"trackId": "genes", "type": "FeatureTrack", "adapter": {"type": "Gff3TabixAdapter"}, "category": ["Reference annotation"]},
                ]
                old_view_tracks = [{"configuration": track["trackId"]} for track in old_tracks]
                source_config = {
                    "assemblies": [{"name": "test_assembly"}],
                    "tracks": old_tracks,
                    "defaultSession": {"views": [{"type": "LinearGenomeView", "tracks": old_view_tracks}]},
                }
                (package / "BATTER_S1_001.config.json").write_text(json.dumps(source_config), encoding="utf-8")
                (package / "assemblies/GCF_TEST.1.config.json").write_text(json.dumps(source_config), encoding="utf-8")
                (package / "catalog.json").write_text(json.dumps({
                    "sources": {"BATTER_S1_001": {"config": "BATTER_S1_001.config.json", "track_count": 3}},
                    "assemblies": {"GCF_TEST.1": {
                        "config": "assemblies/GCF_TEST.1.config.json",
                        "source_ids": ["BATTER_S1_001"],
                        "endpoint_track_ids": ["legacy_endpoints", "signal"],
                    }},
                }), encoding="utf-8")
                downloads = root / mode / "downloads" / "v0.3.0"
                gff3 = downloads / "records/BATTER_S1_001/endpoints.gff3"
                gff3.parent.mkdir(parents=True)
                gff3.write_text("##gff-version 3\nNC_000001.1\tBATTER_S1_001\ttranscript_3_prime_end\t10\t10\t.\t+\t.\tID=end-1\n", encoding="utf-8")

                catalog = stage_site.apply_v03_jbrowse_configs(
                    package, downloads, mode, self.HF_BASE, studies_path
                )

                config = json.loads((package / "BATTER_S1_001.config.json").read_text(encoding="utf-8"))
                endpoint = next(track for track in config["tracks"] if track.get("metadata", {}).get("release_version") == "v0.3.0")
                self.assertEqual(endpoint["adapter"]["type"], "Gff3Adapter")
                self.assertEqual(
                    endpoint["adapter"]["gffLocation"]["uri"],
                    f"{self.HF_BASE}/records/BATTER_S1_001/endpoints.gff3",
                )
                self.assertEqual(endpoint["metadata"]["record_count"], 1)
                self.assertTrue(any(view_track["configuration"] == endpoint["trackId"] for view_track in config["defaultSession"]["views"][0]["tracks"]))
                self.assertEqual({track["trackId"] for track in config["tracks"]}, {"signal", "genes", endpoint["trackId"]})
                self.assertEqual(catalog["sources"]["BATTER_S1_001"]["track_count"], 3)
                assembly_config = json.loads((package / "assemblies/GCF_TEST.1.config.json").read_text(encoding="utf-8"))
                self.assertEqual({track["trackId"] for track in assembly_config["tracks"]}, {"signal", "genes", endpoint["trackId"]})
                self.assertEqual(catalog["assemblies"]["GCF_TEST.1"]["endpoint_track_ids"], [endpoint["trackId"]])


if __name__ == "__main__":
    unittest.main()
