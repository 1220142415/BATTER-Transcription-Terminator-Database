"""Verify and unpack the small NCBI reference package used by v0.4 JBrowse."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
ASSEMBLY = "GCF_000012525.1"
SOURCE = ROOT / "data" / "registry" / "browser_refs" / f"{ASSEMBLY}.ncbi.zip"
SOURCE_URL = (
    "https://api.ncbi.nlm.nih.gov/datasets/v2/genome/accession/"
    f"{ASSEMBLY}/download?include_annotation_type=GENOME_FASTA,GENOME_GFF"
)
SOURCE_SHA256 = "86491ecddacba3faf49fb70e8758bb2dd406d1cb58d715832ae07866ae90ab33"
CHROMOSOME_SHA256 = "5fb438ec6391898e01a7774c114b37d7852c64cd115de2c1628cefecb6d5f4a6"
FASTA_MEMBER = f"ncbi_dataset/data/{ASSEMBLY}/{ASSEMBLY}_ASM1252v1_genomic.fna"
GFF_MEMBER = f"ncbi_dataset/data/{ASSEMBLY}/genomic.gff"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _verified_members() -> tuple[bytes, bytes]:
    if _sha256(SOURCE.read_bytes()) != SOURCE_SHA256:
        raise ValueError(f"{SOURCE} differs from the verified NCBI download")
    with ZipFile(SOURCE) as package:
        md5_lines = package.read("md5sum.txt").decode("ascii").splitlines()
        expected_md5 = dict(line.split("  ", 1)[::-1] for line in md5_lines if line)
        for name, expected in expected_md5.items():
            if hashlib.md5(package.read(name)).hexdigest() != expected:  # noqa: S324 - NCBI's supplied integrity file
                raise ValueError(f"NCBI package member checksum mismatch: {name}")
        fasta = package.read(FASTA_MEMBER)
        gff = package.read(GFF_MEMBER)
    return fasta, gff


def _fai_and_contigs(fasta: bytes) -> tuple[bytes, list[tuple[str, int, str]]]:
    offset = 0
    current: dict[str, object] | None = None
    rows: list[tuple[str, int, int, int, int]] = []
    contigs: list[tuple[str, int, str]] = []
    digest = hashlib.sha256()
    for line in fasta.splitlines(keepends=True):
        if line.startswith(b">"):
            if current is not None:
                name = str(current["name"])
                length = int(current["length"])
                rows.append((name, length, int(current["offset"]), int(current["bases"]), int(current["width"])))
                contigs.append((name, length, digest.hexdigest()))
            name = line[1:].split(None, 1)[0].decode("ascii")
            current = {"name": name, "length": 0, "offset": offset + len(line), "bases": 0, "width": 0}
            digest = hashlib.sha256()
        elif current is not None:
            bases = line.rstrip(b"\r\n").upper()
            if bases:
                if not current["bases"]:
                    current["bases"] = len(bases)
                    current["width"] = len(line)
                current["length"] = int(current["length"]) + len(bases)
                digest.update(bases)
        offset += len(line)
    if current is not None:
        name = str(current["name"])
        length = int(current["length"])
        rows.append((name, length, int(current["offset"]), int(current["bases"]), int(current["width"])))
        contigs.append((name, length, digest.hexdigest()))
    if not rows or contigs[0] != ("NC_007604.1", 2695903, CHROMOSOME_SHA256):
        raise ValueError("NCBI chromosome differs from the verified CP000100.1 sequence")
    fai = "".join("\t".join(map(str, row)) + "\n" for row in rows).encode("ascii")
    return fai, contigs


def prepare(output_root: Path) -> list[tuple[str, int, str]]:
    fasta, annotation = _verified_members()
    fai, contigs = _fai_and_contigs(fasta)
    with (SOURCE.parent / "contigs.tsv").open(encoding="utf-8", newline="") as handle:
        declared = [
            (row["contig_accession"], int(row["length_bp"]), row["sequence_sha256"])
            for row in csv.DictReader(handle, delimiter="\t")
            if row["assembly_accession"] == ASSEMBLY
        ]
    if declared != contigs:
        raise ValueError("reference contig registry differs from verified NCBI sequences")
    if not all(f"##sequence-region {name} ".encode() in annotation for name, _, _ in contigs):
        raise ValueError("NCBI annotation does not describe every reference sequence")
    target = output_root / "v0.4.0" / "browser" / ASSEMBLY
    target.mkdir(parents=True, exist_ok=True)
    objects = {
        "reference.fna": (fasta, "fasta"),
        "reference.fna.fai": (fai, "fai"),
        "annotation.gff3": (annotation, "gff3"),
    }
    for filename, (data, _) in objects.items():
        (target / filename).write_bytes(data)
    manifest = output_root / "reference_assets.tsv"
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(("logical_path", "local_path", "byte_size", "sha256", "asset_kind", "source_url"))
        for filename, (data, kind) in objects.items():
            writer.writerow((
                f"browser/{ASSEMBLY}/{filename}",
                f"v0.4.0/browser/{ASSEMBLY}/{filename}",
                len(data),
                _sha256(data),
                kind,
                SOURCE_URL,
            ))
    return contigs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    for name, length, digest in prepare(args.output_root):
        print(f"{ASSEMBLY}\t{name}\t{length}\t{digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
