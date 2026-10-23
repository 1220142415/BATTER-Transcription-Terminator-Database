"""GFF-derived gene tables preserve reference bounds and circular coordinates."""

from __future__ import annotations

import csv
import hashlib
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from typing import Any

from bted_pipeline.materialize import (
    JBROWSE_INVENTORY_COLUMNS,
    _build_gff_gene_tables,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bgzf_block(payload: bytes) -> bytes:
    compressor = zlib.compressobj(level=9, wbits=-15)
    compressed = compressor.compress(payload) + compressor.flush()
    header = struct.pack("<BBBBIBBH", 31, 139, 8, 4, 0, 0, 255, 6)
    block_size = len(header) + 8 + len(compressed) + 8
    extra = b"BC" + struct.pack("<HH", 2, block_size - 1)
    trailer = struct.pack("<II", zlib.crc32(payload) & 0xFFFFFFFF, len(payload))
    return header + extra + compressed + trailer


def _write_bgzf(path: Path, text: str) -> None:
    path.write_bytes(_bgzf_block(text.encode("utf-8")) + _bgzf_block(b""))


def _write_synthetic_gene_inventory(root: Path) -> tuple[Path, Path, str]:
    assembly = "GCF_000000001.1"
    bundle_root = root / "bundle"
    asset_root = bundle_root / "assets"
    asset_root.mkdir(parents=True)
    fai_path = asset_root / "reference.fna.fai"
    fai_path.write_text(
        "ctgA\t100\t0\t50\t51\nctgB\t100\t0\t50\t51\n",
        encoding="utf-8",
    )
    gff_path = asset_root / "genes.gff3.gz"
    _write_bgzf(
        gff_path,
        "##gff-version 3\n"
        "ctgA\tRefSeq\tgene\t5\t20\t.\t+\t.\t"
        "ID=gene-1;Name=display%20name;gene=preferred%20name;"
        "locus_tag=LT1;product=alpha%2Cbeta\n"
        "ctgB\tRefSeq\tgene\t80\t125\t.\t-\t.\t"
        "ID=gene-2;Name=second%20name;locus_tag=LT2\n",
    )
    rows: list[dict[str, str]] = []
    common = {
        "release_version": "v0.2.0",
        "source_id": "S",
        "assembly_accession": assembly,
        "canonical_path": "",
        "object_path": "",
        "supports_range": "false",
        "redistribution_status": "verified_redistributable",
        "is_public": "true",
    }
    for role, kind, path, asset_id, mime in (
        (
            "reference_fai",
            "fai",
            "assets/reference.fna.fai",
            "v0.2.0--assembly-GCF_000000001.1--fai",
            "text/plain",
        ),
        (
            "reference_gff3",
            "gff3",
            "assets/genes.gff3.gz",
            "v0.2.0--assembly-GCF_000000001.1--gff3",
            "application/gzip",
        ),
    ):
        source_path = bundle_root / path
        rows.append(
            {
                **common,
                "asset_id": asset_id,
                "asset_role": role,
                "asset_kind": kind,
                "bundle_path": path,
                "byte_size": str(source_path.stat().st_size),
                "sha256": _sha256(source_path),
                "mime_type": mime,
            }
        )
    inventory_path = root / "inventory.tsv"
    with inventory_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=JBROWSE_INVENTORY_COLUMNS,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    return inventory_path, bundle_root, assembly


class GeneTableTests(unittest.TestCase):
    def test_synthetic_gff_fixture_decodes_and_extends_contigs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inventory, bundle_root, assembly = _write_synthetic_gene_inventory(
                Path(directory)
            )
            tables: dict[str, list[dict[str, Any]]] = {
                "assemblies": [{"assembly_accession": assembly}],
                "contigs": [
                    {
                        "assembly_id_ref": assembly,
                        "assembly_accession": assembly,
                        "contig_accession": "ctgA",
                        "contig_name": "ctgA",
                        "length_bp": 100,
                        "sequence_sha256": None,
                        "provenance_json": {},
                    }
                ],
                "genes": [],
            }
            summary = _build_gff_gene_tables(
                tables,
                {
                    "release": {"release_version": "v0.2.0"},
                    "repo_root": str(Path(directory)),
                },
                inventory,
                bundle_root,
            )
            self.assertEqual(summary["gene_count"], 2)
            self.assertEqual(summary["canonical_contig_count"], 1)
            self.assertEqual(summary["contig_count"], 2)
            genes = {row["gene_id"]: row for row in tables["genes"]}
            first = genes[f"{assembly}:gene-1"]
            self.assertEqual(first["gene_name"], "preferred name")
            self.assertEqual(first["attributes_json"]["Name"], "display name")
            self.assertEqual(first["attributes_json"]["product"], "alpha,beta")
            self.assertEqual(first["locus_tag"], "LT1")
            second = genes[f"{assembly}:gene-2"]
            self.assertEqual(second["gene_name"], "second name")
            self.assertEqual(second["end_1based"], 125)
            self.assertEqual(
                second["attributes_json"]["_bted_contig_length"],
                "100",
            )
            self.assertIn("_bted_coordinate_note", second["attributes_json"])
            extra = next(
                row
                for row in tables["contigs"]
                if row["contig_accession"] == "ctgB"
            )
            self.assertEqual(
                extra["provenance_json"]["source"],
                "jbrowse_reference_fai",
            )
