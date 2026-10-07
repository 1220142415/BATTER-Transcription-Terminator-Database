"""Refresh the small browser catalogue; genome files remain on Hugging Face."""
import argparse
import csv
import json
import gzip
import hashlib
import re
import urllib.request
from pathlib import Path

REVISION = "9f81698a3cee64f4eaf90b90cd36d640f38d9315"
ROOT = Path(__file__).resolve().parents[1]
COLUMNS = ["genome_id", "batch", "otu_id", "organism", "genome_type",
           "otu_augmentation_span", "otu_augmentation_window", "rfam_training_span",
           "rfam_training_window", "annotation_status", "tes_prediction", "taxonomy", "source_collection"]


def build(tables, revision):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Use an immutable HF commit SHA")
    genomes, seen = [], set()
    for batch, path in tables:
        if not re.fullmatch(r"\d{3}", batch):
            raise ValueError(f"Invalid batch: {batch}")
        with path.open(encoding="utf-8") as handle:
            records = list(csv.DictReader(handle, delimiter="\t"))
        for row in records:
            genome = row["genome_id"]
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", genome) or genome in seen:
                raise ValueError(f"Invalid or duplicate genome: {genome}")
            seen.add(genome)
            species = next((t[3:] for t in row["taxonomy"].split(";") if t.startswith("s__")), "")
            values = [genome, batch, row["otu_id"], species or genome, row["genome_type"]]
            values += [int(row[key]) for key in COLUMNS[5:9]]
            prediction = int(row["tes_prediction"])
            if any(v < 0 for v in values[5:] + [prediction]):
                raise ValueError("Negative feature count")
            genomes.append(values + [row["annotation_status"], prediction, row["taxonomy"], row["source_collection"]])
    if not genomes:
        raise ValueError("No uploaded genomes found")
    return {"revision": revision, "partial": True, "columns": COLUMNS, "genomes": genomes}


def checked_bytes(path, expected):
    data = path.read_bytes()
    if len(data) != expected["byte_size"] or hashlib.sha256(data).hexdigest() != expected["sha256"]:
        raise ValueError(f"Checksum mismatch: {path}")
    return data


def complete_catalogue(catalogue, published, release, proof):
    """Require exact agreement before calling an upload complete."""
    expected = {g["genome_id"]: g for g in published if g["has_prediction"]}
    rows = {row[0]: row for row in catalogue["genomes"]}
    files = {f["path"] for f in release["files"]}
    if len({g["genome_id"] for g in published}) != len(published) or len(published) != release["counts"]["genomes"]:
        raise ValueError("Published genome count mismatch")
    if rows.keys() != expected.keys() or len(rows) != release["counts"]["batter_genomes"]:
        raise ValueError("Computational catalogue is incomplete")
    batches = {"batter-" + row[1] for row in rows.values()}
    if (proof.get("status") != "complete" or proof.get("hf_sha256_verified") is not True
            or proof.get("genome_count") != len(rows)
            or proof.get("hf_revision") != release["original_revision"]
            or proof.get("release_manifest_sha256") != release["original_release_manifest_sha256"]
            or not batches.issubset(proof.get("completed_groups", []))):
        raise ValueError("Release completion proof mismatch")
    for genome, row in rows.items():
        base = f"genomes/batter-{row[1]}/{genome}/"
        entry = expected[genome]
        if entry["group"] != "batter-" + row[1] or entry["metadata_path"] != base + "metadata.json":
            raise ValueError(f"Genome path mismatch: {genome}")
        required = ["metadata.json", "reference/reference.fa.gz", "reference/reference.fa.gz.fai", "reference/reference.fa.gz.gzi"]
        if row[10]:
            required += ["predictions/prediction.gff3.gz", "predictions/prediction.gff3.gz.tbi"]
        if any(row[5:9]):
            required += ["training/augmentation.gff3.gz", "training/augmentation.gff3.gz.tbi"]
        if row[9] == "matched":
            required += ["annotations/batter/genes.gff3.gz", "annotations/batter/genes.gff3.gz.tbi"]
        if any(base + file not in files for file in required):
            raise ValueError(f"Missing published genome file: {genome}")
    return {**catalogue, "layout": "genome-first", "partial": False}


def build_release(cache_dir, revision, download=False):
    """Read metadata only, from a revision-specific cache."""
    root = cache_dir / revision
    base = f"https://huggingface.co/datasets/liurulong/terminator/resolve/{revision}/v0.5.0/"
    def get(path, expected=None):
        target = root / path
        if download:
            with urllib.request.urlopen(base + path, timeout=180) as response:
                data = response.read()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        data = checked_bytes(target, expected) if expected else target.read_bytes()
        return data
    release = json.loads(get("release.json"))
    if release.get("schema") != "bted-genome-first-v5-v1" or release.get("hf_repo") != "liurulong/terminator":
        raise ValueError("Unsupported release manifest")
    files = {f["path"]: f for f in release["files"]}
    published = json.loads(get("catalogues/genomes.json", files["catalogues/genomes.json"]))
    proof_path = "catalogues/provenance/original-release.complete.json"
    if files[proof_path]["sha256"] != release["original_proof_sha256"]:
        raise ValueError("Completion proof checksum mismatch")
    proof = json.loads(get(proof_path, files[proof_path]))
    tables = []
    for path in sorted(files):
        match = re.fullmatch(r"catalogues/provenance/batter/batches/(\d{3})/genomes.tsv", path)
        if match:
            get(path, files[path])
            tables.append((match[1], root / path))
    return complete_catalogue(build(tables, revision), published, release, proof), release


def carry_overlays(catalogue, release, path):
    """Keep prior sequence comparisons only when the reference bytes are unchanged."""
    previous = json.loads(path.read_text(encoding="utf-8"))
    files = {f["path"]: f for f in release["files"]}
    rows = {row[0]: row for row in catalogue["genomes"]}
    kept = {}
    for genome, entry in previous["genomes"].items():
        if genome in rows:
            ref = files[f"genomes/batter-{rows[genome][1]}/{genome}/reference/reference.fa.gz"]
            if ref["sha256"] == entry["batter_reference_sha256"]:
                kept[genome] = entry
    path.write_text(json.dumps({"revision": catalogue["revision"], "genomes": kept}, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Retained {len(kept)} verified overlays with unchanged reference hashes")


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
        base = f"https://huggingface.co/datasets/liurulong/terminator/resolve/{catalogue['revision']}/v0.5.0/genomes/batter-{batch}/{genome}/"
        metadata = json.loads(download(base + "metadata.json", f"{catalogue['revision']}-{genome}-metadata.json"))["records"]["batter"]
        batter_sha = metadata["files"]["reference.fa.gz"]["sha256"]
        batter = sequence_hashes(gzip.decompress(download(base + "reference/reference.fa.gz", f"{batter_sha}.fa.gz", batter_sha)))
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
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--verify-overlaps", action="store_true")
    parser.add_argument("--carry-overlays", action="store_true", help="Reuse prior sequence comparisons by manifest hash; reads no sequence files")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "dist/hf-catalogue")
    parser.add_argument("--output", type=Path, default=ROOT / "data/registry/batter-browser.json")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        parser.error("Specify an immutable HF commit SHA")
    catalogue, release = build_release(args.cache_dir, args.revision, args.download)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(catalogue, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
    print(f"Indexed {len(catalogue['genomes']):,} genomes at {args.revision}")
    if args.carry_overlays:
        carry_overlays(catalogue, release, ROOT / "data/registry/batter-overlays.json")
    if args.verify_overlaps:
        verify_overlaps(catalogue, args.cache_dir)


if __name__ == "__main__":
    main()
