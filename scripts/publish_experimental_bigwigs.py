"""Prepare or publish explicit experimental BigWig mappings to the existing HF dataset.

New samples are additive to the pinned v0.5.0 release. This uploader does not
rewrite the original release proof, replace legacy signals, or deploy a site.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import struct
import urllib.request
from pathlib import Path

REPO = "liurulong/terminator"
VERSION = "v0.5.0"
INDEX = VERSION + "/catalogues/experimental_signals.json"


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def component(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
        raise ValueError("Invalid identifier: " + repr(value))
    return value


def sample_root(sample):
    pmid = str(sample["pmid"])
    if not pmid.isdigit():
        raise ValueError("PMID must be numeric")
    return (VERSION + "/genomes/" + component(sample["group"]) + "/"
            + component(sample["genome_id"]) + "/studies/PMID_" + pmid
            + "/sources/" + component(sample["source_id"]) + "/samples/"
            + component(sample["sample_id"]))


def chromosome_tree(path):
    """Read UCSC BigWig chromosome B+ tree and exact key offsets, without decoding signals."""
    file_size = Path(path).stat().st_size
    with Path(path).open("rb") as handle:
        header = handle.read(64)
        if len(header) != 64:
            raise ValueError("Truncated BigWig header")
        if header[:4] == struct.pack("<I", 0x888FFC26):
            endian = "<"
        elif header[:4] == struct.pack(">I", 0x888FFC26):
            endian = ">"
        else:
            raise ValueError("Not a BigWig file")
        tree_offset, data_offset, index_offset = struct.unpack_from(endian + "QQQ", header, 8)
        if not all(64 <= offset < file_size for offset in (tree_offset, data_offset, index_offset)):
            raise ValueError("Invalid BigWig section offsets")
        handle.seek(tree_offset)
        tree = handle.read(32)
        magic, _, key_size, val_size, count, _ = struct.unpack(endian + "IIIIQQ", tree)
        if magic != 0x78CA8C91 or val_size != 8 or not 0 < key_size <= 4096:
            raise ValueError("Unsupported BigWig chromosome tree")
        pending, visited, keys, chromosomes = [tree_offset + 32], set(), [], {}
        while pending:
            offset = pending.pop()
            if offset in visited or not tree_offset + 32 <= offset < data_offset:
                raise ValueError("Invalid chromosome tree node")
            visited.add(offset)
            handle.seek(offset)
            leaf, _, entries = struct.unpack(endian + "BBH", handle.read(4))
            if leaf not in (0, 1):
                raise ValueError("Invalid chromosome tree leaf flag")
            for _ in range(entries):
                key_offset = handle.tell()
                name = handle.read(key_size).split(b"\0", 1)[0].decode("utf-8")
                payload = handle.read(8)
                keys.append((key_offset, key_size, name))
                if leaf:
                    _, length = struct.unpack(endian + "II", payload)
                    if name in chromosomes:
                        raise ValueError("Duplicate BigWig chromosome")
                    chromosomes[name] = length
                else:
                    pending.append(struct.unpack(endian + "Q", payload)[0])
        if len(chromosomes) != count or not chromosomes:
            raise ValueError("BigWig chromosome count mismatch")
        # The total-summary min value catches signed sources incompatible with this mirror renderer.
        summary_offset = struct.unpack_from(endian + "Q", header, 44)[0]
        summary = None
        if summary_offset:
            handle.seek(summary_offset)
            covered, minimum, maximum, total, squared = struct.unpack(endian + "Qdddd", handle.read(40))
            summary = dict(bases_covered=covered, min_value=minimum, max_value=maximum,
                           sum_values=total, sum_squared_values=squared)
    return chromosomes, keys, summary


def prepare_bigwig(source, target, reference, aliases):
    chromosomes, keys, summary = chromosome_tree(source)
    if set(aliases) - set(chromosomes):
        raise ValueError("Alias does not name a source chromosome")
    normalized = {aliases.get(name, name): length for name, length in chromosomes.items()}
    if len(normalized) != len(chromosomes):
        raise ValueError("Chromosome aliases collide")
    for name, length in normalized.items():
        if reference.get(name) != length:
            raise ValueError("Reference name/length mismatch: " + name)
    # Same-length aliases can be patched in the fixed-width tree without rewriting any data block.
    for old, new in aliases.items():
        if len(old.encode()) != len(new.encode()):
            raise ValueError("Regenerate the BigWig for a chromosome alias with a different byte length")
    source_hash = sha256(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    changed_bytes = 0
    with target.open("r+b") as handle:
        for offset, key_size, name in keys:
            if name in aliases and aliases[name] != name:
                old, new = name.encode(), aliases[name].encode()
                changed_bytes += sum(a != b for a, b in zip(old, new))
                handle.seek(offset)
                handle.write(new + b"\0" * (key_size - len(new)))
    actual, _, actual_summary = chromosome_tree(target)
    if actual != normalized or actual_summary != summary or sha256(source) != source_hash:
        raise ValueError("Source or summary changed during preparation")
    return dict(source_filename=source.name, source_sha256=source_hash,
                sha256=sha256(target), byte_size=target.stat().st_size,
                chromosomes=normalized, chromosome_aliases=aliases,
                changed_header_bytes=changed_bytes, signal_summary=summary)


def fetch(api, path, revision):
    from huggingface_hub import hf_hub_url
    url = hf_hub_url(REPO, path, repo_type="dataset", revision=revision)
    request = urllib.request.Request(url, headers={"User-Agent": "BTED experimental signals"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read()


def identity_check(sample, metadata):
    if metadata["genome_id"] != sample["genome_id"] or metadata["group"] != sample["group"]:
        raise ValueError("Genome/group mapping mismatch")
    sources = metadata.get("records", {}).get("experimental", {}).get("sources", [])
    source = next((s for s in sources if s["source_id"] == sample["source_id"]), None)
    if not source or str(source["pmid"]) != str(sample["pmid"]) or source["assembly"] != sample["genome_id"]:
        raise ValueError("Study/source mapping mismatch")
    if sample.get("series_accession") and sample["series_accession"] not in re.split(r"[;,\s]+", source["raw_data_accessions"]):
        raise ValueError("Series does not match the registered study")
    return source


def remote_sha(api, path, revision):
    items = api.get_paths_info(REPO, paths=[path], repo_type="dataset", revision=revision)
    if not items:
        return None
    item = items[0]
    lfs = getattr(item, "lfs", None)
    digest = lfs.get("sha256") if isinstance(lfs, dict) else getattr(lfs, "sha256", None)
    return digest or hashlib.sha256(fetch(api, path, revision)).hexdigest()


def verify_download(path, expected, revision):
    from huggingface_hub import hf_hub_url
    url = hf_hub_url(REPO, path, repo_type="dataset", revision=revision)
    digest = hashlib.sha256()
    size = 0
    request = urllib.request.Request(url, headers={"User-Agent": "BTED experimental signals"})
    with urllib.request.urlopen(request, timeout=60) as response:
        for chunk in iter(lambda: response.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    if size != expected["byte_size"] or digest.hexdigest() != expected["sha256"]:
        raise ValueError("Fixed-revision download differs: " + path)
    result = dict(path=path, byte_size=size, sha256=digest.hexdigest(), url=url)
    if path.endswith(".bw"):
        request = urllib.request.Request(url, headers={"User-Agent": "BTED experimental signals",
            "Range": "bytes=0-63", "Origin": "http://127.0.0.1:8787"})
        with urllib.request.urlopen(request, timeout=45) as response:
            data = response.read(65)
            cors = response.headers.get("Access-Control-Allow-Origin")
            content_range = response.headers.get("Content-Range", "")
            if response.status != 206 or len(data) != 64 or not content_range.startswith("bytes 0-63/"):
                raise ValueError("BigWig Range request did not return bytes 0-63: " + path)
            if cors not in ("*", "http://127.0.0.1:8787"):
                raise ValueError("BigWig CORS does not allow the browser: " + path)
            if data[:4] not in (struct.pack("<I", 0x888FFC26), struct.pack(">I", 0x888FFC26)):
                raise ValueError("Downloaded Range is not a BigWig header")
        result.update(range_verified=True, cors_verified=True)
    return result


def prepare(api, spec, output, parent):
    if spec.get("schema") != "bted-experimental-bigwig-intake-v1" or not spec.get("samples"):
        raise ValueError("Expected a nonempty explicit sample intake manifest")
    if output.exists():
        raise ValueError("Use a fresh output directory")
    info = api.get_paths_info(REPO, paths=[INDEX], repo_type="dataset", revision=parent)
    index = json.loads(fetch(api, INDEX, parent)) if info else dict(schema="bted-experimental-signals-v1", release_version=VERSION, samples=[])
    if index.get("schema") != "bted-experimental-signals-v1" or index.get("release_version") != VERSION:
        raise ValueError("Unsupported signal catalogue")
    existing = {row["path"]: row for row in index["samples"]}
    if len(existing) != len(index["samples"]):
        raise ValueError("Duplicate paths in signal catalogue")
    payload, roots = {}, set()
    for sample in spec["samples"]:
        root = sample_root(sample)
        if root in roots:
            raise ValueError("Duplicate sample identity; combine its signal entries")
        roots.add(root)
        genome_root = root.split("/studies/")[0]
        metadata = json.loads(fetch(api, genome_root + "/metadata.json", parent))
        source = identity_check(sample, metadata)
        reference = {line.split("\t")[0]: int(line.split("\t")[1]) for line in
                     fetch(api, genome_root + "/reference/reference.fa.gz.fai", parent).decode().splitlines()}
        signals, strands = [], set()
        for entry in sample["signals"]:
            strand = entry["strand"]
            if strand not in ("plus", "minus", "unstranded") or strand in strands:
                raise ValueError("Use one file per plus/minus/unstranded signal; distinct conditions need separate sample IDs")
            strands.add(strand)
            path = root + "/signal." + strand + ".bw"
            target = output / "payload" / path
            record = prepare_bigwig(Path(entry["path"]), target, reference, sample.get("chrom_aliases", {}))
            if entry.get("expected_source_sha256") and entry["expected_source_sha256"] != record["source_sha256"]:
                raise ValueError("Local file does not match the recorded server SHA-256")
            if strand in ("plus", "minus") and record["signal_summary"] and record["signal_summary"]["min_value"] < 0:
                raise ValueError("The mirror renderer requires nonnegative strand signals")
            record.update(path=path, strand=strand)
            if entry.get("source_url"):
                record["source_url"] = entry["source_url"]
            signals.append(record)
            payload[path] = target
        if not signals or ("unstranded" in strands and len(strands) > 1):
            raise ValueError("Provide strand-separated signals or a single unstranded signal")
        sample_metadata = dict(schema="bted-experimental-signal-sample-v1", release_version=VERSION,
            genome_id=sample["genome_id"], group=sample["group"], pmid=str(sample["pmid"]),
            source_id=sample["source_id"], sample_id=sample["sample_id"],
            series_accession=sample.get("series_accession"), assay=source["assay"],
            description=sample.get("description", ""), evidence_class="experimental_signal",
            signal_processing="WIG to BigWig; values and coordinates preserved; explicit chromosome aliases only",
            mirror_display=len(strands) == 2 and strands == {"plus", "minus"}, signals=signals)
        metadata_path = root + "/metadata.json"
        metadata_file = output / "payload" / metadata_path
        metadata_file.write_bytes(encode(sample_metadata))
        payload[metadata_path] = metadata_file
        sums = "".join(sha256(payload[p]) + "  " + p.rsplit("/", 1)[-1] + "\n" for p in
                       sorted([s["path"] for s in signals] + [metadata_path]))
        sums_path = root + "/SHA256SUMS.txt"
        sums_file = output / "payload" / sums_path
        sums_file.write_text(sums, encoding="utf-8", newline="\n")
        payload[sums_path] = sums_file
        catalogue_row = dict(path=root, metadata_path=metadata_path,
            metadata_sha256=sha256(metadata_file), genome_id=sample["genome_id"],
            group=sample["group"], source_id=sample["source_id"], pmid=str(sample["pmid"]),
            sample_id=sample["sample_id"], series_accession=sample.get("series_accession"),
            signals=[{k: signal[k] for k in ("path", "strand", "sha256", "byte_size")} for signal in signals])
        if root in existing and any(existing[root].get(key) != value for key, value in catalogue_row.items()):
            raise ValueError("Existing sample has different content; choose a distinct sample ID")
        catalogue_row["reference_contigs"] = {name: length for signal in signals for name, length in signal["chromosomes"].items()}
        if root in existing:
            for key in ("revision", "verification"):
                if key in existing[root]:
                    catalogue_row[key] = existing[root][key]
        existing[root] = catalogue_row
    index["samples"] = [existing[key] for key in sorted(existing)]
    index_file = output / "payload" / INDEX
    index_file.parent.mkdir(parents=True, exist_ok=True)
    index_file.write_bytes(encode(index))
    payload[INDEX] = index_file
    rows = {path: dict(byte_size=file.stat().st_size, sha256=sha256(file)) for path, file in payload.items()}
    # Scientific payloads and sample provenance are immutable once registered.
    for path, row in rows.items():
        if path != INDEX:
            old = remote_sha(api, path, parent)
            if old and old != row["sha256"]:
                raise ValueError("Refusing to replace an existing sample file: " + path)
    plan = dict(repo=REPO, release_version=VERSION, parent_revision=parent, files=rows)
    (output / "upload-plan.json").write_bytes(encode(plan))
    return payload, plan


def publish(api, payload, plan, output):
    from huggingface_hub import CommitOperationAdd
    parent = plan["parent_revision"]
    source_roots = {path.split("/samples/")[0] for path in payload if "/samples/" in path}
    preserved = {}
    for root in sorted(source_roots):
        for item in api.list_repo_tree(REPO, path_in_repo=root, repo_type="dataset", revision=parent, recursive=True):
            if hasattr(item, "size") and item.path not in payload:
                preserved[item.path] = (item.size, item.blob_id)
    scientific_files = {path: row for path, row in plan["files"].items() if path != INDEX}
    operations = [CommitOperationAdd(path_in_repo=path, path_or_fileobj=str(file))
                  for path, file in payload.items() if path != INDEX and remote_sha(api, path, parent) != plan["files"][path]["sha256"]]
    if operations:
        try:
            commit = api.create_commit(REPO, repo_type="dataset", revision="main", parent_commit=parent,
                commit_message="Add experimental BigWig samples with reference and strand provenance",
                operations=operations)
            revision = commit.oid
        except Exception:
            # A timed-out commit may have landed; do not blindly retry a mutation.
            revision = api.dataset_info(REPO, revision="main").sha
            if not all(remote_sha(api, path, revision) == row["sha256"] for path, row in scientific_files.items()):
                raise
    else:
        revision = parent
    receipt = dict(repo=REPO, hf_revision=revision, status="uploaded_verification_pending", files=[])
    (output / "upload-receipt.json").write_bytes(encode(receipt))
    for path, row in sorted(scientific_files.items()):
        receipt["files"].append(verify_download(path, row, revision))
        print("Verified " + path, flush=True)
        (output / "upload-receipt.json").write_bytes(encode(receipt))
    # Enroll samples for automatic loading only after real fixed-revision downloads pass.
    index = json.loads(payload[INDEX].read_text(encoding="utf-8"))
    published_roots = {path.rsplit("/", 1)[0] for path in scientific_files}
    for sample in index["samples"]:
        if sample["path"] in published_roots:
            sample.setdefault("revision", revision)
            sample["verification"] = dict(status="complete", sha256=True,
                http_range=True, cors=True, reference_names_and_lengths=True)
    payload[INDEX].write_bytes(encode(index))
    plan["files"][INDEX] = dict(byte_size=payload[INDEX].stat().st_size, sha256=sha256(payload[INDEX]))
    (output / "upload-plan.json").write_bytes(encode(plan))
    if remote_sha(api, INDEX, revision) != plan["files"][INDEX]["sha256"]:
        try:
            commit = api.create_commit(REPO, repo_type="dataset", revision="main", parent_commit=revision,
                commit_message="Enroll verified experimental BigWig samples for automatic browser loading",
                operations=[CommitOperationAdd(path_in_repo=INDEX, path_or_fileobj=str(payload[INDEX]))])
            catalogue_revision = commit.oid
        except Exception:
            catalogue_revision = api.dataset_info(REPO, revision="main").sha
            if remote_sha(api, INDEX, catalogue_revision) != plan["files"][INDEX]["sha256"]:
                raise
    else:
        catalogue_revision = revision
    receipt["files"].append(verify_download(INDEX, plan["files"][INDEX], catalogue_revision))
    receipt["payload_revision"] = revision
    receipt["hf_revision"] = catalogue_revision
    (output / "experimental-signals.json").write_bytes(encode(index))
    after = {}
    for root in sorted(source_roots):
        for item in api.list_repo_tree(REPO, path_in_repo=root, repo_type="dataset", revision=catalogue_revision, recursive=True):
            if hasattr(item, "size") and item.path not in payload:
                after[item.path] = (item.size, item.blob_id)
    if preserved != after:
        raise ValueError("An unrelated source asset changed")
    receipt.update(status="complete", hf_sha256_verified=True,
                   preserved_source_files=len(preserved), hf_file_count=len(payload))
    (output / "upload-receipt.json").write_bytes(encode(receipt))
    return receipt


def main():
    from huggingface_hub import HfApi
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--publish", action="store_true", help="Commit the validated explicit mapping to main")
    args = parser.parse_args()
    spec = json.loads(args.manifest.read_text(encoding="utf-8"))
    api = HfApi()
    account = api.whoami()["name"]
    if account != "liurulong":
        raise ValueError("Expected the existing liurulong HF account")
    parent = api.dataset_info(REPO, revision="main").sha
    payload, plan = prepare(api, spec, args.output, parent)
    print(json.dumps(plan, ensure_ascii=False, indent=2), flush=True)
    if args.publish:
        receipt = publish(api, payload, plan, args.output)
        print(json.dumps({k: receipt[k] for k in ("status", "hf_revision", "hf_file_count")}), flush=True)


if __name__ == "__main__":
    main()
