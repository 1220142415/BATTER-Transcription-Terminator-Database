"""Project v0.5 release paths into existing site and D1 interfaces."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import mimetypes
import re
import shutil
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

from bted_v05 import VERSION, HF_REPO, json_write, rows, safe_path, sha256, verify

RELEASE_LABEL = "v5"
RELEASE_DISPLAY_NAME = "Latest · v5"


class ReleasePresentation(HTMLParser):
    """Render the current release label without changing asset paths or code."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.parts = []
        self.code_tag = None

    def handle_starttag(self, tag, attrs):
        raw = self.get_starttag_text()
        attributes = dict(attrs)
        if tag in {"script", "style"}:
            self.code_tag = tag
        if tag == "meta" and attributes.get("name") == "description":
            raw = re.sub(r"v0\.[45]\.0", RELEASE_LABEL, raw)
        if "data-genome-page" in attributes:
            raw = re.sub(r'\sdata-release-label="[^"]*"', "", raw)
            raw = raw[:-1] + ' data-release-label="' + RELEASE_LABEL + '">'
        self.parts.append(raw)

    def handle_startendtag(self, tag, attrs):
        self.parts.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        self.parts.append("</" + tag + ">")
        if self.code_tag == tag:
            self.code_tag = None

    def handle_data(self, data):
        if not self.code_tag:
            # Previously generated previews may still contain the old release label.
            data = data.replace("最新版 v5", RELEASE_DISPLAY_NAME)
            if data.strip() in {"BTED v0.4.0", "BTED v0.5.0", RELEASE_DISPLAY_NAME}:
                data = data.replace(data.strip(), RELEASE_DISPLAY_NAME)
            elif re.fullmatch(r"BTED v0\.[45]\.0 · genome-first experimental endpoint data", data):
                data = "BTED · " + RELEASE_DISPLAY_NAME + " · bacterial transcript 3′ end data"
            else:
                data = re.sub(r"\bv0\.[45]\.0\b", RELEASE_LABEL, data)
        self.parts.append(data)

    def handle_entityref(self, name): self.parts.append("&" + name + ";")
    def handle_charref(self, name): self.parts.append("&#" + name + ";")
    def handle_comment(self, data): self.parts.append("<!--" + data + "-->")
    def handle_decl(self, decl): self.parts.append("<!" + decl + ">")


def present_release(html):
    parser = ReleasePresentation()
    parser.feed(html)
    parser.close()
    return "".join(parser.parts)


def present_site_page(html, relative):
    from bted_unified_site import navigation
    html = re.sub(r'<header class="site-header">.*?</header>',
                  lambda _match: navigation(len(relative.parts) - 1), html, flags=re.S)
    return present_release(html)


def kind(path):
    if path.endswith((".fa.gz", ".fna")): return "fasta"
    if path.endswith(".fai"): return "fai"
    if path.endswith(".gzi"): return "gzi"
    if path.endswith((".gff3", ".gff3.gz")): return "gff3"
    if path.endswith(".tbi"): return "tbi"
    if path.endswith(".bw"): return "bigwig"
    return "metadata"


def data_url(relative, revision):
    if revision == "local":
        return "downloads/" + VERSION + "/" + relative
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Published assets require a fixed 40-character commit")
    return "https://huggingface.co/datasets/" + HF_REPO + "/resolve/" + revision + "/" + VERSION + "/" + quote(relative, safe="/")


def map_url(value, mapping, revision):
    match = re.search(r"(?:downloads/|/resolve/[0-9a-f]{40}/)(v0\.[345]\.0)/([^?\"<> ]+)", value)
    if not match:
        return value
    old = match.group(2)
    if match.group(1) == VERSION:
        return data_url(old, revision)
    if old not in mapping:
        # Old release control downloads are replaced by the complete new controls.
        if old in {"release.json", "SHA256SUMS.txt", "ASSET_SHA256SUMS.txt"}:
            return data_url("release.json" if old == "release.json" else "SHA256SUMS.txt", revision)
        raise ValueError("Unmapped legacy asset URL: " + value)
    return data_url(mapping[old], revision)


def rewrite_config(value, mapping, revision, aliases=None):
    aliases = aliases or {}
    if isinstance(value, list):
        return [rewrite_config(v, mapping, revision, aliases) for v in value]
    if not isinstance(value, dict):
        if isinstance(value, str):
            if value == "v0.4.0": return VERSION
            if value == "BTED v0.4.0": return "BTED " + RELEASE_LABEL
            result = aliases.get(value, map_url(value, mapping, revision))
            return "/" + result if revision == "local" and result.startswith("downloads/") else result
        return value
    result = {key: rewrite_config(v, mapping, revision, aliases) for key, v in value.items()}
    if result.get("type") == "IndexedFastaAdapter" and result.get("fastaLocation", {}).get("uri", "").endswith(".fa.gz"):
        result["type"] = "BgzipFastaAdapter"
        result["gziLocation"] = {"uri": result["fastaLocation"]["uri"] + ".gzi", "locationType": "UriLocation"}
    if result.get("type") == "Gff3Adapter" and result.get("gffLocation", {}).get("uri", "").endswith(".gff3.gz"):
        result["type"] = "Gff3TabixAdapter"
        result["gffGzLocation"] = result.pop("gffLocation")
        result["index"] = {"location": {"uri": result["gffGzLocation"]["uri"] + ".tbi", "locationType": "UriLocation"}, "indexType": "TBI"}
    return result


def publication_status(release, revision, publication_report=None):
    if revision == "local": return "local_prepared"
    data_url("release.json", revision)
    if publication_report is None: return "planned_not_verified"
    report = json.loads(Path(publication_report).read_text(encoding="utf-8"))
    release_sha = sha256(release / "release.json")
    verified = (report.get("status") == "branch_verified" and report.get("revision") == revision
                and report.get("SHA256_verified") is True)
    if report.get("status") == "complete":
        manifest = json.loads((release / "release.json").read_text(encoding="utf-8"))
        counts = manifest["counts"]["batter"]
        groups = ["batter-%03d" % n for n in range(counts["batches"])] + ["experimental", "catalogues", "release-controls"]
        verified = (report.get("hf_revision") == revision and report.get("hf_sha256_verified") is True
                    and report.get("hf_repo") == HF_REPO
                    and report.get("hf_branch") == "v05-preparation-" + release_sha[:12]
                    and report.get("completed_groups") == groups
                    and report.get("hf_file_count") == len(manifest["files"]) + 3
                    and report.get("genome_count") == counts["genomes"])
    if not verified or report.get("release_manifest_sha256") != release_sha:
        raise ValueError("Publication proof does not match the fixed revision and release manifest")
    return "public_download"


def asset_manifest(release, revision, publication_report=None):
    doc = json.loads((release / "release.json").read_text(encoding="utf-8"))
    assets = {}
    for row in doc["files"]:
        # BATTER assets are looked up by genome in D1, rather than loading a
        # repository-wide 370k-object allowlist for every experimental request.
        if not row["path"].startswith("experimental/"):
            continue
        assets[row["path"]] = {"url": data_url(row["path"], revision), "byte_size": row["byte_size"],
                               "sha256": row["sha256"], "revision": None if revision == "local" else revision,
                               "asset_kind": kind(row["path"]), "asset_key": VERSION + "--" + hashlib.sha256(row["path"].encode()).hexdigest()}
    for name in ("release.json", "SHA256SUMS.txt"):
        path = release / name
        assets[name] = {"url": data_url(name, revision), "byte_size": path.stat().st_size,
                        "sha256": sha256(path), "revision": None if revision == "local" else revision,
                        "asset_kind": "metadata" if name.endswith("json") else "checksum", "asset_key": VERSION + "--" + hashlib.sha256(name.encode()).hexdigest()}
    return {"releaseVersion": VERSION, "releaseLabel": RELEASE_LABEL, "releaseDisplayName": RELEASE_DISPLAY_NAME,
            "releaseRevision": None if revision == "local" else revision,
            "publicationStatus": publication_status(release, revision, publication_report),
            "sharedAssets": {"releaseVersion": VERSION, "revision": None if revision == "local" else revision},
            "batterBrowser": {"route": "/api/genomes/{genome_id}/jbrowse-config", "preparedGenomeIds": [r["genome_id"] for r in rows(release / "batter/genomes.tsv")]},
            "assets": assets}


def stage(release, baseline, output, revision, publication_report=None):
    verify(release)
    if output.exists():
        raise ValueError("Choose a new staging directory")
    shutil.copytree(baseline, output, ignore=shutil.ignore_patterns("downloads"))
    doc = json.loads((release / "release.json").read_text(encoding="utf-8"))
    mapping = doc["experimental_asset_mapping"]
    for path in list(output.rglob("*.json")):
        if path.name == "data-release.json":
            continue
        value = json.loads(path.read_text(encoding="utf-8"))
        aliases = {}
        if path.parent.name == "assemblies":
            meta = release / "experimental/genomes" / path.name.replace(".config.json", "") / "metadata.json"
            if meta.is_file():
                aliases = json.loads(meta.read_text(encoding="utf-8"))["reference_validation"].get("contig_aliases", {})
        json_write(path, rewrite_config(value, mapping, revision, aliases))
    for path in list(output.rglob("*.html")) + list(output.glob("assets/*.js")):
        text = path.read_text(encoding="utf-8")
        pattern = r"(?:https://huggingface\.co/datasets/liurulong/terminator/resolve/[0-9a-f]{40}/|downloads/)(?:v0\.[345]\.0)/[^\s\"'<>)]+"
        text = re.sub(pattern, lambda m: map_url(m.group(0), mapping, revision), text)
        path.write_text(text.replace("v0.4.0", VERSION), encoding="utf-8")
    from build_batter_catalog_preview import build
    build(output)
    for p in (output / "batter-genomes.html",):
        p.write_text(p.read_text(encoding="utf-8").replace("v0.4.0", VERSION), encoding="utf-8")
    for path in output.rglob("*.html"):
        if "jbrowse" not in path.relative_to(output).parts:
            path.write_text(present_site_page(path.read_text(encoding="utf-8"), path.relative_to(output)), encoding="utf-8")
    # Use the maintained genome interaction code, including the display label.
    shutil.copyfile(Path(__file__).resolve().parents[1] / "site/assets/genome-page.js", output / "assets/genome-page.js")
    json_write(output / "assets/data-release.json", asset_manifest(release, revision, publication_report))
    if revision == "local":
        # Hard links remain immutable; neither the site nor its server rewrites data.
        from bted_v05 import copy_payload
        for item in doc["files"] + [{"path": p} for p in ("release.json", "SHA256SUMS.txt")]:
            copy_payload(release / item["path"], output / "downloads" / VERSION / item["path"])
        copy_payload(release.parent / "README.md", output / "downloads" / "README.md")
    return {"release_version": VERSION, "site": str(output), "revision": revision,
            "experimental_assets": len(asset_manifest(release, revision)["assets"]),
            "batter_genomes": doc["counts"]["batter"]["genomes"]}


def materialize(release, baseline_bundle, output, revision, publication_report=None):
    """Keep published observations; change path/provenance projection only."""
    if output.exists():
        raise ValueError("Choose a new D1 bundle directory")
    for line in (baseline_bundle / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        if sha256(safe_path(baseline_bundle, name)) != digest:
            raise ValueError("Baseline bundle checksum differs: " + name)
    verify(release)
    output.mkdir(parents=True)
    doc = json.loads((release / "release.json").read_text(encoding="utf-8"))
    mapping = doc["experimental_asset_mapping"]
    files = {r["path"]: r for r in doc["files"]}
    metadata = {p.parent.name: json.loads(p.read_text(encoding="utf-8")) for p in (release / "experimental/genomes").glob("*/metadata.json")}
    source_rows = {s["source_id"]: s for meta in metadata.values() for s in meta["sources"]}
    def transform(value):
        if isinstance(value, dict): return {k: transform(v) for k, v in value.items()}
        if isinstance(value, list): return [transform(v) for v in value]
        if isinstance(value, str):
            if value == "v0.4.0": return VERSION
            if value in mapping: return mapping[value]
            return value
        return value
    for source in baseline_bundle.glob("*.jsonl"):
        if source.name in {"assets.jsonl", "contigs.jsonl"}:
            continue
        with source.open(encoding="utf-8") as inp, (output / source.name).open("w", encoding="utf-8") as out:
            for line in inp:
                original = json.loads(line)
                row = transform(original)
                genome = row.get("reference_assembly") or row.get("assembly_id_ref")
                if source.name == "endpoints.jsonl" and genome in metadata:
                    aliases = metadata[genome]["reference_validation"].get("contig_aliases", {})
                    row["reference_name"] = aliases.get(row["reference_name"], row["reference_name"])
                if source.name == "sources.jsonl":
                    row["record_root"] = mapping.get(original.get("record_root"), original.get("record_root"))
                if source.name == "release_versions.jsonl":
                    row.update(canonical_manifest_path=VERSION + "/release.json", canonical_manifest_sha256=sha256(release / "release.json"))
                out.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    assets = []
    status = publication_status(release, revision, publication_report)
    for relative, item in asset_manifest(release, revision, publication_report)["assets"].items():
        pieces = relative.split("/")
        genome = pieces[2] if pieces[:2] == ["experimental", "genomes"] else None
        source_id = pieces[pieces.index("sources") + 1] if "sources" in pieces else None
        assets.append({"asset_id": VERSION + "--" + hashlib.sha256(relative.encode()).hexdigest(),
                       "release_version": VERSION, "assembly_id_ref": genome, "source_id_ref": source_id,
                       "asset_kind": "metadata" if item["asset_kind"] == "gzi" else item["asset_kind"],
                       "logical_path": relative, "origin_url": item["url"], "origin_host": "huggingface.co" if revision != "local" else "localhost",
                       "byte_size": item["byte_size"], "sha256": item["sha256"],
                       "mime_type": mimetypes.guess_type(relative)[0] or "application/octet-stream",
                       "supports_range": True, "redistribution_status": "local_prepared" if revision == "local" else "verified_redistributable", "is_public": True})
    contigs = []
    from bted_v05 import read_fasta
    for genome, meta in metadata.items():
        fasta = release / "experimental/genomes" / genome / "reference.fa.gz"
        if not fasta.exists(): continue
        for name, sequence in read_fasta(fasta).items():
            contigs.append({"assembly_id_ref": genome, "assembly_accession": genome, "contig_accession": name,
                            "contig_name": name, "length_bp": len(sequence), "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
                            "provenance_json": meta["reference_validation"]})
    for name, values in (("assets.jsonl", assets), ("contigs.jsonl", contigs)):
        with (output / name).open("w", encoding="utf-8") as handle:
            for row in values: handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    manifest = json.loads((baseline_bundle / "manifest.json").read_text(encoding="utf-8"))
    manifest.update(release_version=VERSION, materializer_version="bted-materializer-0.5.0",
                    canonical_manifest={"path": VERSION + "/release.json", "sha256": sha256(release / "release.json")},
                    asset_origin={"base": data_url("", revision), "host": "localhost" if revision == "local" else "huggingface.co",
                                  "asset_origin_status": "local_verified" if revision == "local" else "verified" if status == "public_download" else "planned_not_verified"},
                    contig_count=len(contigs), v05_release_payload_count=len(files))
    manifest["tables"] = {p.stem: {"file": p.name, "byte_size": p.stat().st_size,
                                   "sha256": sha256(p), "row_count": len(p.read_text(encoding="utf-8").splitlines())}
                          for p in sorted(output.glob("*.jsonl"))}
    json_write(output / "manifest.json", manifest)
    with (output / "SHA256SUMS.txt").open("w", encoding="utf-8") as handle:
        for p in sorted(output.iterdir()):
            if p.name != "SHA256SUMS.txt": handle.write(sha256(p) + "  " + p.name + "\n")
    return manifest


def batter_projection(release, database, revision, publication_report=None):
    import sqlite3
    doc = json.loads((release / "release.json").read_text(encoding="utf-8"))
    status = publication_status(release, revision, publication_report)
    if status == "planned_not_verified":
        raise ValueError("BATTER published asset projection requires a matching remote verification report")
    index = {r["path"]: r for r in doc["files"]}
    conn = sqlite3.connect(str(database))
    conn.execute("CREATE TABLE IF NOT EXISTS batter_release_assets (genome_id TEXT NOT NULL, release_version TEXT NOT NULL, publication_status TEXT NOT NULL, metadata_json TEXT NOT NULL, PRIMARY KEY(genome_id,release_version))")
    values = []
    for batch in sorted((release / "batter/batches").iterdir()):
        for row in rows(batch / "genomes.tsv"):
            genome = row["genome_id"]
            prefix = "batter/batches/" + batch.name + "/genomes/" + genome + "/"
            meta = json.loads((release / prefix / "metadata.json").read_text(encoding="utf-8"))
            fasta_index = (release / prefix / "reference.fa.gz.fai").read_text(encoding="utf-8").splitlines()
            contigs = [{"seqid": v.split("\t")[0], "length_bp": int(v.split("\t")[1])} for v in fasta_index]
            data = {"reference_contigs": contigs, "annotation": meta["annotation"], "validation": meta["validation"], "files": {}}
            shared = release / "experimental/genomes" / genome / "metadata.json"
            data["shared_reference_verified"] = shared.is_file() and json.loads(shared.read_text(encoding="utf-8"))["reference_validation"]["status"] == "experimental_contigs_sequence_identical_to_GEM"
            for name in ("reference.fa.gz", "reference.fa.gz.fai", "reference.fa.gz.gzi", "prediction.gff3.gz", "prediction.gff3.gz.tbi", "augmentation.gff3.gz", "augmentation.gff3.gz.tbi", "genes.gff3.gz", "genes.gff3.gz.tbi"):
                if prefix + name in index:
                    entry = index[prefix + name]
                    data["files"][name] = {"url": data_url(prefix + name, revision), "sha256": entry["sha256"], "byte_size": entry["byte_size"]}
            values.append((genome, VERSION, status, json.dumps(data)))
    for row in rows(release / "batter/held_genomes.tsv"):
        values.append((row["genome_id"], VERSION, "held", json.dumps(row)))
    with conn:
        conn.executemany("INSERT OR REPLACE INTO batter_release_assets VALUES (?,?,?,?)", values)
    conn.close()
    return len(values)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("stage", "materialize", "batter-projection"):
        p = sub.add_parser(command)
        p.add_argument("--release", type=Path, required=True)
        p.add_argument("--revision", default="local")
        p.add_argument("--publication-report", type=Path)
        if command != "batter-projection":
            p.add_argument("--baseline", type=Path, required=True)
            p.add_argument("--output", type=Path, required=True)
        else:
            p.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()
    result = batter_projection(args.release, args.database, args.revision, args.publication_report) if args.command == "batter-projection" else (
        stage(args.release, args.baseline, args.output, args.revision, args.publication_report) if args.command == "stage" else materialize(args.release, args.baseline, args.output, args.revision, args.publication_report))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__": main()
