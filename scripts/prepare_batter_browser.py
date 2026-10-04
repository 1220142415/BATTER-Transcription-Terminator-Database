"""Refresh the small browser catalogue; genome files remain on Hugging Face."""
import argparse
import csv
import json
import gzip
import hashlib
import re
import urllib.request
from pathlib import Path

REVISION = "6588c4242246fcfd40086a08a94fe3a6c378c029"
ROOT = Path(__file__).resolve().parents[1]
COLUMNS = ["genome_id", "batch", "otu_id", "organism", "genome_type",
           "otu_augmentation_span", "otu_augmentation_window", "rfam_training_span",
           "rfam_training_window", "annotation_status", "tes_prediction", "taxonomy", "source_collection"]


def build(tables, revision):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Use an immutable HF commit SHA")
    genomes, seen = [], set()
    for batch, path in tables:
        for row in csv.DictReader(path.open(encoding="utf-8"), delimiter="\t"):
            genome = row["genome_id"]
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", genome) or genome in seen:
                raise ValueError(f"Invalid or duplicate genome: {genome}")
            seen.add(genome)
            species = next((t[3:] for t in row["taxonomy"].split(";") if t.startswith("s__")), "")
            values = [genome, batch, row["otu_id"], species or genome, row["genome_type"]]
            values += [int(row[key]) for key in COLUMNS[5:9]]
            if any(v < 0 for v in values[5:]):
                raise ValueError("Negative feature count")
            genomes.append(values + [row["annotation_status"], int(row["tes_prediction"]), row["taxonomy"], row["source_collection"]])
    if not genomes:
        raise ValueError("No uploaded genomes found")
    return {"revision": revision, "partial": True, "columns": COLUMNS, "genomes": genomes}


def sequence_hashes(data):
    sequences = {}
    name, sequence = None, []
    for line in data.decode("ascii").splitlines() + [">"]:
        if line.startswith(">"):
            if name:
                if name in sequences:
                    raise ValueError("Duplicate FASTA sequence ID")
                bases = "".join(sequence).upper().encode("ascii")
                sequences[name] = {"length": len(bases), "sha256": hashlib.sha256(bases).hexdigest()}
            name, sequence = line[1:].split(" ", 1)[0], []
        else:
            sequence.append(line.strip())
    return sequences


def verify_overlaps(catalogue, cache_dir):
    release = json.loads((ROOT / "data/public/v0.4.0/release.json").read_text(encoding="utf-8"))
    ids = {genome["assembly"] for genome in release["genomes"]}
    with (ROOT / "data/registry/browser_assets.v0.4.0.tsv").open(encoding="utf-8") as handle:
        assets = list(csv.DictReader(handle, delimiter="\t"))
    result = {"revision": catalogue["revision"], "genomes": {}}
    def download(url, name, expected=None):
        path = cache_dir / name
        if not path.exists():
            with urllib.request.urlopen(url, timeout=120) as response:
                path.write_bytes(response.read())
        data = path.read_bytes()
        if expected and hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f"Checksum mismatch: {name}")
        return data
    for row in catalogue["genomes"]:
        genome, batch = row[:2]
        if genome not in ids:
            continue
        asset = next(item for item in assets if item["asset_kind"] == "fasta" and genome in item["logical_path"].split("/"))
        base = f"https://huggingface.co/datasets/liurulong/terminator/resolve/{catalogue['revision']}/v0.5.0/batter/batches/{batch}/genomes/{genome}/"
        metadata = json.loads(download(base + "metadata.json", f"{catalogue['revision']}-{genome}-metadata.json"))
        batter_sha = metadata["files"]["reference.fa.gz"]["sha256"]
        batter = sequence_hashes(gzip.decompress(download(base + "reference.fa.gz", f"{batter_sha}.fa.gz", batter_sha)))
        experimental = sequence_hashes(download(asset["url"], f"{asset['sha256']}.fna", asset["sha256"]))
        aliases = {}
        for ref, digest in experimental.items():
            candidates = [name for name, value in batter.items() if value == digest]
            if batter.get(ref) == digest:
                aliases[ref] = ref
            elif len(candidates) == 1:
                aliases[ref] = candidates[0]
        compatible = bool(experimental) and len(aliases) == len(experimental)
        result["genomes"][genome] = {"compatible": compatible, "experimental_reference_url": asset["url"],
            "experimental_reference_sha256": asset["sha256"], "batter_reference_sha256": batter_sha,
            "experimental_contigs": experimental, "batter_contigs": batter, "aliases": aliases}
        print(f"{genome}: {'matching reference sequences' if compatible else 'different references; separate views'}")
    (ROOT / "data/registry/batter-overlays.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default=REVISION)
    parser.add_argument("--batches", type=int, default=40)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--verify-overlaps", action="store_true")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--output", type=Path, default=ROOT / "data/registry/batter-browser.json")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision) or not 1 <= args.batches <= 1000:
        parser.error("Specify a commit SHA and 1–1000 uploaded batches")
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    tables = []
    for number in range(args.batches):
        batch = f"{number:03}"
        path = args.cache_dir / f"hf-v05-{batch}-genomes.tsv"
        if args.download:
            url = f"https://huggingface.co/datasets/liurulong/terminator/resolve/{args.revision}/v0.5.0/batter/batches/{batch}/genomes.tsv"
            with urllib.request.urlopen(url, timeout=90) as response:
                path.write_bytes(response.read())
        tables.append((batch, path))
    catalogue = build(tables, args.revision)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(catalogue, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
    print(f"Indexed {len(catalogue['genomes']):,} genomes at {args.revision}")
    if args.verify_overlaps:
        verify_overlaps(catalogue, args.cache_dir)


if __name__ == "__main__":
    main()
