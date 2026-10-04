"""Refresh the small browser catalogue; genome files remain on Hugging Face."""
import argparse
import csv
import json
import re
import urllib.request
from pathlib import Path

REVISION = "6588c4242246fcfd40086a08a94fe3a6c378c029"
ROOT = Path(__file__).resolve().parents[1]
COLUMNS = ["genome_id", "batch", "otu_id", "organism", "genome_type",
           "otu_augmentation_span", "otu_augmentation_window", "rfam_training_span",
           "rfam_training_window", "annotation_status"]


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
            genomes.append(values + [row["annotation_status"]])
    if not genomes:
        raise ValueError("No uploaded genomes found")
    return {"revision": revision, "partial": True, "columns": COLUMNS, "genomes": genomes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default=REVISION)
    parser.add_argument("--batches", type=int, default=40)
    parser.add_argument("--download", action="store_true")
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
    args.output.write_text(json.dumps(catalogue, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Indexed {len(catalogue['genomes']):,} genomes at {args.revision}")


if __name__ == "__main__":
    main()
