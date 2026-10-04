#!/usr/bin/env python3
"""Prepare and verify the self-contained BTED experimental/BATTER v0.5 release.

Preparation never uploads, deletes a release, changes source packages, or runs
gene prediction. HTS executables are only needed for experimental browser assets.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

VERSION = "v0.5.0"
HF_REPO = "liurulong/terminator"
EXCLUDED = {"release.json", "SHA256SUMS.txt"}


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def safe_path(root, relative):
    value = PurePosixPath(relative)
    if not relative or value.is_absolute() or ".." in value.parts or "\\" in relative:
        raise ValueError("Unsafe release path: " + relative)
    path = Path(root).joinpath(*value.parts)
    if Path(root).resolve() not in path.resolve().parents:
        raise ValueError("Path escapes release: " + relative)
    return path


def json_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(str(temp), str(path))


def rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def tsv_write(path, values, columns=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = columns or list(values[0])
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(values)
    os.replace(str(temporary), str(path))


def copy_payload(source, target, digest=None):
    """Immutable payloads can share inodes; generated metadata never does."""
    source, target = Path(source), Path(target)
    if source.is_symlink() or not source.is_file():
        raise ValueError("Source payload missing or symlinked: " + str(source))
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.is_symlink() or target.stat().st_size != source.stat().st_size:
            raise ValueError("Existing payload differs: " + str(target))
        if not os.path.samefile(str(source), str(target)) and sha256(target) != (digest or sha256(source)):
            raise ValueError("Existing payload checksum differs: " + str(target))
        return
    try:
        os.link(str(source), str(target))
    except OSError:
        shutil.copy2(str(source), str(target))


def read_fasta(path):
    opened = gzip.open(path, "rt") if str(path).endswith(".gz") else Path(path).open()
    result, name, chunks = {}, None, []
    with opened as handle:
        for line in handle:
            if line.startswith(">"):
                if name is not None:
                    result[name] = "".join(chunks).upper()
                name = line[1:].split()[0]
                if name in result:
                    raise ValueError("Duplicate contig: " + name)
                chunks = []
            else:
                chunks.append(line.strip())
        if name is not None:
            result[name] = "".join(chunks).upper()
    if not result:
        raise ValueError("Empty FASTA: " + str(path))
    return result


def sequence_aliases(source, target):
    aliases = {}
    for name, sequence in source.items():
        matches = [key for key, value in target.items() if value == sequence]
        if name in matches:
            aliases[name] = name
        elif len(matches) == 1:
            aliases[name] = matches[0]
        else:
            raise ValueError("Reference sequence cannot be uniquely matched: " + name)
    if len(set(aliases.values())) != len(aliases):
        raise ValueError("Reference mapping is not one-to-one")
    return aliases


def hts(tool_dir, name, *args):
    subprocess.run([str(Path(tool_dir) / name), *map(str, args)], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def bgzf_lines(path, lines, tool_dir):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        process = subprocess.Popen([str(Path(tool_dir) / "bgzip"), "-c"],
                                   stdin=subprocess.PIPE, stdout=handle, stderr=subprocess.PIPE)
        _, error = process.communicate("".join(lines).encode("utf-8"))
        if process.returncode:
            raise ValueError(error.decode("utf-8", errors="replace"))


def topology_evidence(directory, sequences, aliases):
    evidence = {}
    if directory is None: return evidence
    for header in Path(directory).glob("*.header.txt"):
        text = header.read_text(encoding="utf-8")
        accession = header.name[:-len(".header.txt")]
        target = aliases.get(accession, accession)
        locus = re.search(r"^LOCUS\s+\S+\s+(\d+) bp\s+.*\bcircular\b", text, re.M)
        version = re.search(r"^VERSION\s+(\S+)", text, re.M)
        if target in sequences and locus and version and version.group(1) == accession and int(locus.group(1)) == len(sequences[target]):
            evidence[target] = {"accession": accession, "length_bp": int(locus.group(1)), "topology": "circular",
                                "source_url": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=nuccore&id=" + accession + "&rettype=gb&retmode=text",
                                "header_sha256": sha256(header)}
    return evidence


def indexed_gff(source, target, sequences, aliases, tool_dir, allow_circular=False, circular_evidence=None):
    features, circular = [], 0
    circular_contigs = set(circular_evidence or {}) if allow_circular else set()
    def opener():
        return gzip.open(source, "rt", encoding="utf-8") if str(source).endswith(".gz") else Path(source).open(encoding="utf-8")
    if allow_circular:
        with opener() as handle:
            for line in handle:
                parts = line.rstrip("\n").split("\t")
                if len(parts) == 9 and parts[2] == "region" and "Is_circular=true" in parts[8].split(";"):
                    name = aliases.get(parts[0], parts[0])
                    if name in sequences and int(parts[3]) == 1 and int(parts[4]) == len(sequences[name]):
                        circular_contigs.add(name)
    opened = opener()
    with opened as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 9:
                raise ValueError("Invalid GFF3 row: " + str(source))
            parts[0] = aliases.get(parts[0], parts[0])
            start, end = int(parts[3]), int(parts[4])
            if parts[0] not in sequences or start < 1 or start > end:
                raise ValueError("Invalid feature reference/coordinates: " + str(source))
            length = len(sequences[parts[0]])
            if end > length:
                if parts[0] not in circular_contigs or start > length or end > 2 * length:
                    raise ValueError("Feature exceeds reference: " + str(source))
                circular += 1
            features.append(parts)
    features.sort(key=lambda p: (p[0], int(p[3]), int(p[4])))
    bgzf_lines(target, ["##gff-version 3\n"] + ["\t".join(p) + "\n" for p in features], tool_dir)
    if features:
        hts(tool_dir, "tabix", "-f", "-p", "gff", target)
    return {"features": len(features), "circular_overhang_features": circular}


def reference_asset(legacy, current, genome, filename):
    old = legacy / "assemblies" / genome / "reference" / filename
    if old.is_file():
        return old
    modern_names = {"reference.fna": "reference.fna", "genes.gff3.gz": "annotation.gff3"}
    candidate = current / "browser" / genome / modern_names.get(filename, filename)
    return candidate if candidate.is_file() else None


def prepare_experimental(args, release, batter_folders):
    current, legacy = args.experimental_release, args.legacy_assets
    original = json.loads((current / "release.json").read_text(encoding="utf-8"))
    sources, mappings, summaries = {}, {}, []
    for meta_file in sorted((current / "genomes").glob("*/metadata.tsv")):
        genome = meta_file.parent.name
        members = rows(meta_file)
        sources.update({row["source_id"]: row for row in members})
        folder = release / "experimental" / "genomes" / genome
        folder.mkdir(parents=True, exist_ok=True)
        copy_payload(meta_file, folder / "metadata.tsv")
        mappings["genomes/" + genome + "/metadata.tsv"] = (folder / "metadata.tsv").relative_to(release).as_posix()
        fasta = reference_asset(legacy, current, genome, "reference.fna")
        reference, aliases, validation = {}, {}, {"status": "not_available"}
        if fasta is not None:
            source_sequences = read_fasta(fasta)
            if genome in batter_folders:
                gem = batter_folders[genome] / "reference.fa.gz"
                reference = read_fasta(gem)
                aliases = sequence_aliases(source_sequences, reference)
                for name in ("reference.fa.gz", "reference.fa.gz.fai", "reference.fa.gz.gzi"):
                    copy_payload(batter_folders[genome] / name, folder / name)
                validation = {"status": "experimental_contigs_sequence_identical_to_GEM",
                              "contig_aliases": aliases,
                              "extra_GEM_contigs": sorted(set(reference) - set(aliases.values()))}
            else:
                reference, aliases = source_sequences, {name: name for name in source_sequences}
                # Write temporary outputs first so a resumed preparation cannot
                # truncate a source hard link.
                temporary = folder / "reference.build.gz"
                with fasta.open("rb") as inp, temporary.open("wb") as out:
                    subprocess.run([str(args.tools_bin / "bgzip"), "-c"], stdin=inp, stdout=out, check=True)
                os.replace(str(temporary), str(folder / "reference.fa.gz"))
                hts(args.tools_bin, "samtools", "faidx", folder / "reference.fa.gz")
                validation = {"status": "source_sequences_preserved", "contig_aliases": aliases}
            for old_name, new_name in (("reference.fna", "reference.fa.gz"),
                                       ("reference.fna.fai", "reference.fa.gz.fai")):
                mappings["assemblies/" + genome + "/reference/" + old_name] = (folder / new_name).relative_to(release).as_posix()
                mappings["browser/" + genome + "/" + old_name] = (folder / new_name).relative_to(release).as_posix()
            genes = reference_asset(legacy, current, genome, "genes.gff3.gz")
            if genes is not None:
                validation["annotation"] = indexed_gff(genes, folder / "genes.gff3.gz", reference, aliases,
                                                       args.tools_bin, allow_circular=True,
                                                       circular_evidence=topology_evidence(args.topology_dir, reference, aliases))
                validation["annotation"]["source_sha256"] = sha256(genes)
                mappings["assemblies/" + genome + "/reference/genes.gff3.gz"] = (folder / "genes.gff3.gz").relative_to(release).as_posix()
                mappings["assemblies/" + genome + "/reference/genes.gff3.gz.tbi"] = (folder / "genes.gff3.gz.tbi").relative_to(release).as_posix()
                mappings["browser/" + genome + "/annotation.gff3"] = (folder / "genes.gff3.gz").relative_to(release).as_posix()
        by_study = defaultdict(list)
        for member in members:
            by_study[member["pmid"]].append(member)
        browser_count = 0
        for pmid, study_rows in sorted(by_study.items()):
            study = folder / "studies" / ("PMID_" + pmid)
            tsv_write(study / "metadata.tsv", study_rows)
            source_study = meta_file.parent / "studies" / ("PMID_" + pmid)
            for name in ("endpoints.gff3.gz", "gene_associations.tsv.gz", "condition_observations.tsv.gz"):
                source_file = source_study / name
                if source_file.is_file():
                    copy_payload(source_file, study / name)
                    mappings[source_file.relative_to(current).as_posix()] = (study / name).relative_to(release).as_posix()
            for member in study_rows:
                sid = member["source_id"]
                source_track = current / "tracks" / sid / "endpoints.gff3"
                source_folder = study / "sources" / sid
                if source_track.is_file():
                    if not reference:
                        raise ValueError("Published experimental track lacks reference: " + sid)
                    result = indexed_gff(source_track, source_folder / "endpoints.gff3.gz",
                                         reference, aliases, args.tools_bin)
                    if result["features"] != int(member["record_count"]):
                        raise ValueError("Experimental source count changed: " + sid)
                    browser_count += result["features"]
                    mappings["tracks/" + sid + "/endpoints.gff3"] = (source_folder / "endpoints.gff3.gz").relative_to(release).as_posix()
                for old_name, new_name in (("signal.forward.bw", "signal.plus.bw"),
                                           ("signal.reverse.bw", "signal.minus.bw")):
                    signal = legacy / "tracks" / sid / old_name
                    if signal.is_file():
                        copy_payload(signal, source_folder / new_name)
                        mappings["tracks/" + sid + "/" + old_name] = (source_folder / new_name).relative_to(release).as_posix()
        summary = {"genome_id": genome, "path": folder.relative_to(release).as_posix(),
                   "reference_status": validation["status"], "source_count": len(members),
                   "endpoint_count": sum(int(row["record_count"]) for row in members),
                   "browser_endpoint_count": browser_count}
        json_write(folder / "metadata.json", {**summary, "collection": "experimental",
                                               "sources": members, "reference_validation": validation})
        summaries.append(summary)
        print("experimental " + genome, flush=True)
    if len(sources) != original["counts"]["source_count"] or sum(r["endpoint_count"] for r in summaries) != original["counts"]["endpoint_count"]:
        raise ValueError("Experimental source or endpoint totals changed")
    tsv_write(release / "experimental/genomes.tsv", summaries)
    return original["counts"], mappings


def file_manifest(path):
    result = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            name, size, digest = line.rstrip("\n").split("\t")
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("Invalid SHA-256: " + str(path))
            result.append((name, int(size), digest))
    if len({r[0] for r in result}) != len(result):
        raise ValueError("Duplicate file manifest entry")
    return result


def prepare(args):
    from concurrent.futures import as_completed
    source, output = args.batter_release.resolve(), args.output.resolve()
    if source == output or source in output.parents or output in source.parents:
        raise ValueError("Output must be independent from BATTER source")
    audit = json.loads((source / "audit.json").read_text(encoding="utf-8"))
    if not audit.get("complete"):
        raise ValueError("BATTER source preparation is incomplete")
    release = output / VERSION
    release.mkdir(parents=True, exist_ok=True)
    batches = sorted((source / "batches").glob("[0-9][0-9][0-9]"))
    selected, folders, remaining = [], {}, args.pilot_limit
    for batch in batches:
        values = rows(batch / "genomes.tsv")
        if args.pilot_limit:
            values = values[:remaining]
            remaining -= len(values)
        if values:
            selected.append((batch, values))
            for value in values:
                folders[value["genome_id"]] = batch / "genomes" / value["genome_id"]
        if args.pilot_limit and remaining <= 0:
            break
    experimental_counts, mappings = prepare_experimental(args, release, folders)
    all_rows, known = [], {}
    def batch_copy(item):
        batch, values = item
        names = {value["genome_id"] for value in values}
        target = release / "batter/batches" / batch.name
        for relative, size, digest in file_manifest(batch / "files.tsv"):
            parts = PurePosixPath(relative).parts
            if len(parts) < 3 or parts[0] != "genomes" or parts[1] not in names:
                continue
            source_file = safe_path(batch, relative)
            if source_file.stat().st_size != size:
                raise ValueError("BATTER source size mismatch: " + str(source_file))
            copy_payload(source_file, safe_path(target, relative), digest)
        if args.pilot_limit:
            tsv_write(target / "genomes.tsv", values)
            entries = [(p.relative_to(target).as_posix(), p.stat().st_size, sha256(p))
                       for p in sorted(target.rglob("*")) if p.is_file() and p.name != "files.tsv"]
            with (target / "files.tsv").open("w", encoding="utf-8") as handle:
                for name, size, digest in entries:
                    handle.write("%s\t%d\t%s\n" % (name, size, digest))
        else:
            for name in ("genomes.tsv", "files.tsv"):
                copy_payload(batch / name, target / name)
        expected = {}
        for name, size, digest in file_manifest(target / "files.tsv"):
            expected["batter/batches/" + batch.name + "/" + name] = (size, digest)
        return values, expected, batch.name
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for future in as_completed([pool.submit(batch_copy, item) for item in selected]):
            values, expected, name = future.result()
            all_rows.extend(values)
            known.update(expected)
            print("batter batch " + name, flush=True)
    all_rows.sort(key=lambda value: int(value["batch_rank"]))
    tsv_write(release / "batter/genomes.tsv", all_rows)
    for name in ("held_genomes.tsv", "prediction_end_corrections.tsv"):
        copy_payload(source / name, release / "batter" / name)
    if args.pilot_limit:
        for name in ("prediction_end_corrections.tsv",):
            values = rows(source / name)
            values = [row for row in values if row["genome_id"] in folders]
            columns = list(rows(source / name)[0]) if rows(source / name) else ["genome_id"]
            tsv_write(release / "batter" / name, values, columns)
    expected_names, inventory = set(), []
    for file in sorted(p for p in release.rglob("*") if p.is_file()):
        relative = file.relative_to(release).as_posix()
        if relative in EXCLUDED:
            continue
        size, digest = known.get(relative, (None, None))
        size = file.stat().st_size if size is None else size
        digest = sha256(file) if digest is None else digest
        inventory.append({"path": relative, "byte_size": size, "sha256": digest})
        expected_names.add(relative)
    # A completed preparation is immutable: changing a pilot's selection requires
    # a new output directory, preventing stale genomes from entering the manifest.
    packaged = {p.parent.name for p in (release / "batter/batches").glob("*/genomes/*/metadata.json")}
    if packaged != set(folders):
        raise ValueError("Output contains genomes outside selected source ranks")
    summary = {"experimental": experimental_counts, "batter": {
        "genomes": len(all_rows), "batches": len(selected), "held_genomes": len(rows(source / "held_genomes.tsv")),
        "annotations": sum((folders[r["genome_id"]] / "genes.gff3.gz").is_file() for r in all_rows),
        "empty_augmentation": sum(r.get("augmentation_status") == "no_records_in_source" for r in all_rows)},
        "payload_files": len(inventory), "payload_bytes": sum(r["byte_size"] for r in inventory)}
    doc = {"release_version": VERSION, "schema_version": "1.0", "preparation_complete": True,
           "scope": "pilot" if args.pilot_limit else "full", "publication_status": "local_prepared",
           "counts": summary, "files": inventory, "experimental_asset_mapping": mappings,
           "source_audit_sha256": sha256(source / "audit.json"),
           "checksums_exclude_self": True, "manifest_excludes_self_and_checksums": True}
    json_write(release / "release.json", doc)
    with (release / "SHA256SUMS.txt").open("w", encoding="utf-8") as handle:
        for row in inventory:
            handle.write(row["sha256"] + "  " + row["path"] + "\n")
        handle.write(sha256(release / "release.json") + "  release.json\n")
    (output / "README.md").write_text(readme(summary, doc["scope"]), encoding="utf-8")
    finalize_controls(release)
    print(json.dumps(summary), flush=True)
    return summary


def finalize_controls(release):
    """Include the one repository README without a checksum self-reference."""
    doc = json.loads((release / "release.json").read_text(encoding="utf-8"))
    if doc.get("publication_status") != "local_prepared":
        raise ValueError("Only a local preparation can have its controls updated")
    readme_file = release.parent / "README.md"
    if readme_file.is_symlink(): raise ValueError("Repository README must not be a symlink")
    doc["repository_readme"] = {"repository_path": "README.md", "checksum_path": "../README.md",
                               "byte_size": readme_file.stat().st_size, "sha256": sha256(readme_file)}
    json_write(release / "release.json", doc)
    with (release / "SHA256SUMS.txt").open("w", encoding="utf-8") as handle:
        for row in doc["files"]: handle.write(row["sha256"] + "  " + row["path"] + "\n")
        handle.write(sha256(release / "release.json") + "  release.json\n")
        handle.write(doc["repository_readme"]["sha256"] + "  ../README.md\n")
    return doc["repository_readme"]


def readme(counts, scope):
    return """---
pretty_name: BTED experimental transcript ends and BATTER predictions
---
# BTED v0.5.0

实验与模型数据分别位于 `v0.5.0/experimental/` 和 `v0.5.0/batter/`。
每个集合按完整基因组 ID 整理，NCBI accession 保留版本号。当前是 %s 准备副本，尚未发布。

| 入口 | 内容 |
| --- | --- |
| `experimental/genomes.tsv` | 实验研究基因组与来源、端点数量 |
| `experimental/genomes/<genome_id>/` | 参考、基因注释、按 PMID 保存的原始研究文件、按来源保存的浏览器轨道与原始 BigWig |
| `batter/genomes.tsv` | BATTER 可上传基因组与原始排序 |
| `batter/batches/000..042/` | 每批最多 1,000 个基因组，含 GEMs 参考、预测、训练扩增、匹配的 NCBI 注释与元数据 |
| `batter/held_genomes.tsv` | 核对失败的隔离记录，不包含可上传包 |
| `batter/prediction_end_corrections.tsv` | 发布副本中预测终点恰多 1 bp 的原始和修正坐标 |
| `release.json`、`SHA256SUMS.txt` | 完整文件清单和校验值；SHA 清单含 release.json 与 ../README.md，不含自身；release.json 不循环收录这两份清单 |

实验集合含 %d 个基因组、%d 条来源归属的转录本 3′ 端记录；BATTER 本副本含 %d 个基因组。
有端点记录不等于已证明功能的终止子；预测坐标核对和训练窗口序列一致也不表示实验验证。
保留同坐标的不同研究记录。原始研究 GFF3 保留原序列名，浏览器副本仅使用经过序列核对的名称映射。

参考为 BGZF FASTA，配 .fai 和 .gzi；浏览器 GFF3 配 .tbi。缺少现成匹配注释时不提供 genes.gff3.gz；
无训练扩增时保留有效空 GFF3，不强制索引。只有元数据的实验条目不补造轨道或参考。
每份实验 metadata.tsv 保留论文、方法、证据、许可及来源限制；本集合不替所有研究指定同一许可。
新版全部资产在本版本内，不依赖旧版目录。缓存、脚本和运行历史保留在服务器。

## 按批下载与校验

发布后用固定提交号下载所需批次；当前本地准备副本没有公开下载提交号。
例如 `hf download liurulong/terminator --repo-type dataset --revision <固定提交号> --include 'v0.5.0/batter/batches/000/**' --local-dir ./BTED`。
实验集合可把 include 改为 `v0.5.0/experimental/**`，也可以指定一个完整基因组目录。
各批 files.tsv 列出相对该批目录的路径、字节数与 SHA-256。
完整下载还需根 README.md、v0.5.0/release.json 和 v0.5.0/SHA256SUMS.txt；
在 v0.5.0 目录执行 `sha256sum -c SHA256SUMS.txt`，其中 ../README.md 校验唯一的根说明。
""" % (scope, counts["experimental"]["genome_count"], counts["experimental"]["endpoint_count"], counts["batter"]["genomes"])


class HtsIndexReader:
    """Read indexes through installed HTSlib, avoiding a subprocess per file."""
    def __init__(self, library):
        import ctypes
        self.c = ctypes
        self.lib = ctypes.CDLL(str(library))
        self.free = ctypes.CDLL(None).free
        self.free.argtypes = [ctypes.c_void_p]
        self.free.restype = None
        signatures = {
            "tbx_index_load": ([ctypes.c_char_p], ctypes.c_void_p),
            "tbx_seqnames": ([ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)], ctypes.POINTER(ctypes.c_char_p)),
            "tbx_destroy": ([ctypes.c_void_p], None),
            "fai_load3": ([ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int], ctypes.c_void_p),
            "faidx_fetch_seq": ([ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int)], ctypes.c_void_p),
            "fai_destroy": ([ctypes.c_void_p], None),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.lib, name); function.argtypes = arguments; function.restype = result

    def tabix(self, file):
        index = self.lib.tbx_index_load(os.fsencode(str(file)))
        if not index: raise ValueError("Unreadable Tabix: " + str(file))
        try:
            count = self.c.c_int()
            names = self.lib.tbx_seqnames(index, self.c.byref(count))
            try:
                if count.value <= 0 or not names or any(not names[i] for i in range(count.value)):
                    raise ValueError("Tabix has no readable contig dictionary")
            finally:
                if names: self.free(self.c.cast(names, self.c.c_void_p))
        finally: self.lib.tbx_destroy(index)

    def fasta(self, file, seqid):
        # flags=0 requires existing indexes; never creates or rewrites them.
        index = self.lib.fai_load3(os.fsencode(str(file)), os.fsencode(str(file) + ".fai"), os.fsencode(str(file) + ".gzi"), 0)
        if not index: raise ValueError("Unreadable BGZF FASTA indexes: " + str(file))
        try:
            count = self.c.c_int()
            sequence = self.lib.faidx_fetch_seq(index, seqid.encode("utf-8"), 0, 0, self.c.byref(count))
            try:
                if not sequence or count.value != 1: raise ValueError("BGZF random access failed: " + str(file))
            finally:
                if sequence: self.free(sequence)
        finally: self.lib.fai_destroy(index)


def verify(release, tools_bin=None, deep=False, workers=4, hts_library=None):
    release = Path(release).resolve()
    reader = HtsIndexReader(hts_library) if hts_library else None
    doc = json.loads((release / "release.json").read_text(encoding="utf-8"))
    if doc.get("release_version") != VERSION or not doc.get("preparation_complete"):
        raise ValueError("Release is not a complete v0.5 preparation")
    expected = {row["path"]: row for row in doc["files"]}
    actual = set()
    for parent, directories, names in os.walk(str(release)):
        for directory in directories:
            if (Path(parent) / directory).is_symlink(): raise ValueError("Symlink directory in release")
        prefix = Path(parent).relative_to(release)
        actual.update((prefix / name).as_posix() for name in names)
    if actual != set(expected) | EXCLUDED:
        raise ValueError("Release file inventory differs")
    checksum_rows = {}
    for line in (release / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        if name in checksum_rows:
            raise ValueError("Duplicate SHA checksum row")
        checksum_rows[name] = digest
    readme_meta = doc.get("repository_readme")
    control_paths = {"release.json", "../README.md"} if readme_meta else {"release.json"}
    if set(checksum_rows) != set(expected) | control_paths or checksum_rows["release.json"] != sha256(release / "release.json"):
        raise ValueError("Checksum coverage or release digest differs")
    if readme_meta:
        file = release.parent / "README.md"
        if readme_meta.get("checksum_path") != "../README.md" or readme_meta.get("repository_path") != "README.md" or file.is_symlink() or file.stat().st_size != readme_meta["byte_size"] or sha256(file) != readme_meta["sha256"] or checksum_rows["../README.md"] != readme_meta["sha256"]:
            raise ValueError("Repository README checksum differs")
    for name, entry in expected.items():
        if checksum_rows[name] != entry["sha256"]:
            raise ValueError("Manifest/checksum disagreement: " + name)
    def check(entry):
        # The inventory walk rejected parent symlinks once per directory. Avoid
        # resolving all ancestors for each of the 370k files on shared storage.
        relative = PurePosixPath(entry["path"])
        if not entry["path"] or relative.is_absolute() or ".." in relative.parts or "\\" in entry["path"]:
            raise ValueError("Unsafe release path")
        file = release.joinpath(*relative.parts)
        if file.is_symlink() or file.stat().st_size != entry["byte_size"]:
            raise ValueError("Size or symlink mismatch: " + entry["path"])
        if deep and sha256(file) != entry["sha256"]:
            raise ValueError("SHA mismatch: " + entry["path"])
        if (tools_bin or reader) and file.name.endswith(".tbi"):
            if reader: reader.tabix(Path(str(file)[:-4]))
            else: hts(tools_bin, "tabix", "-l", str(file)[:-4])
        if (tools_bin or reader) and file.name == "reference.fa.gz.fai":
            line = file.read_text(encoding="utf-8").splitlines()[0].split("\t")
            if reader: reader.fasta(Path(str(file)[:-4]), line[0])
            else: hts(tools_bin, "samtools", "faidx", str(file)[:-4], line[0] + ":1-1")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for offset in range(0, len(doc["files"]), 2048):
            for _ in pool.map(check, doc["files"][offset:offset + 2048]): pass
            if deep and offset % 16384 == 0:
                print("verified_files " + str(min(offset + 2048, len(doc["files"]))) + "/" + str(len(doc["files"])), flush=True)
    all_batter = rows(release / "batter/genomes.tsv")
    ranks = [int(row["batch_rank"]) for row in all_batter]
    if ranks != sorted(set(ranks)):
        raise ValueError("BATTER source rank order/uniqueness changed")
    seen = []
    for batch in sorted((release / "batter/batches").iterdir()):
        batch_rows = rows(batch / "genomes.tsv")
        if not 1 <= len(batch_rows) <= 1000:
            raise ValueError("Invalid batch size")
        seen.extend(batch_rows)
        for name, size, digest in file_manifest(batch / "files.tsv"):
            rel = (batch / name).relative_to(release).as_posix()
            if expected[rel]["sha256"] != digest or expected[rel]["byte_size"] != size:
                raise ValueError("Batch file manifest differs: " + rel)
    if seen != all_batter:
        raise ValueError("Batch membership/order differs from global catalogue")
    counts = doc["counts"]
    if counts["payload_files"] != len(expected) or counts["payload_bytes"] != sum(row["byte_size"] for row in expected.values()):
        raise ValueError("Release payload totals differ from inventory")
    if counts["batter"]["genomes"] != len(all_batter) or counts["batter"]["batches"] != len(list((release / "batter/batches").iterdir())):
        raise ValueError("BATTER release counts differ")
    if counts["batter"]["held_genomes"] != len(rows(release / "batter/held_genomes.tsv")):
        raise ValueError("Held genome count differs")
    if counts["batter"]["empty_augmentation"] != sum(row.get("augmentation_status") == "no_records_in_source" for row in all_batter):
        raise ValueError("Empty augmentation count differs")
    experimental_rows = rows(release / "experimental/genomes.tsv")
    if counts["experimental"]["genome_count"] != len(experimental_rows) or counts["experimental"]["endpoint_count"] != sum(int(row["endpoint_count"]) for row in experimental_rows):
        raise ValueError("Experimental genome/endpoint totals differ")
    stats = {"complete": True, "scope": doc["scope"], "files_checked": len(expected),
             "sha256_recomputed": bool(deep), "indexes_read": bool(tools_bin or reader), "counts": doc["counts"],
             "index_reader": "HTSlib" if reader else "samtools_tabix" if tools_bin else None}
    stats["release_manifest_sha256"] = sha256(release / "release.json")
    stats["repository_readme_checked"] = bool(readme_meta)
    print(json.dumps(stats), flush=True)
    return stats


def audit_sources(release, batter, source_report, experimental, legacy, deep_report, topology_dir=None):
    """Bind the new deep inventory to the previously accepted biological packages."""
    doc = json.loads((release / "release.json").read_text(encoding="utf-8"))
    report = json.loads(deep_report.read_text(encoding="utf-8"))
    original = json.loads(source_report.read_text(encoding="utf-8"))
    if not report.get("complete") or not report.get("sha256_recomputed") or report.get("release_manifest_sha256") != sha256(release / "release.json"):
        raise ValueError("New release needs matching deep SHA verification")
    if not original.get("complete") or original.get("references_matched") != 42904 or original.get("pilot_fingerprints_checked") != 200 or original.get("prediction_end_corrected_features") != 1019:
        raise ValueError("Original BATTER biological acceptance report is incomplete")
    if sha256(batter / "audit.json") != doc["source_audit_sha256"]:
        raise ValueError("Original BATTER audit changed")
    inventory = {r["path"]: r for r in doc["files"]}
    count = 0
    for batch in sorted((release / "batter/batches").iterdir()):
        source_files = {name: (size, digest) for name, size, digest in file_manifest(batter / "batches" / batch.name / "files.tsv")}
        for name, size, digest in file_manifest(batch / "files.tsv"):
            if name == "genomes.tsv" and doc["scope"] == "pilot": continue
            if source_files.get(name) != (size, digest): raise ValueError("Accepted BATTER package changed: " + name)
            entry = inventory["batter/batches/" + batch.name + "/" + name]
            if (entry["byte_size"], entry["sha256"]) != (size, digest): raise ValueError("New inventory differs from accepted package")
            count += 1
    for name in ("held_genomes.tsv", "prediction_end_corrections.tsv"):
        if doc["scope"] == "full" and sha256(release / "batter" / name) != sha256(batter / name):
            raise ValueError("BATTER held/correction provenance changed")
    references, raw_files, circular_features = 0, 0, 0
    topology = {}
    for folder in sorted((release / "experimental/genomes").iterdir()):
        meta = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
        source_fasta = reference_asset(legacy, experimental, folder.name, "reference.fna")
        if source_fasta:
            old, new = read_fasta(source_fasta), read_fasta(folder / "reference.fa.gz")
            aliases = sequence_aliases(old, new)
            if aliases != meta["reference_validation"]["contig_aliases"]: raise ValueError("Experimental reference mapping changed")
            references += 1
            genes = reference_asset(legacy, experimental, folder.name, "genes.gff3.gz")
            if genes:
                # Validate the existing annotation using its explicit circular region evidence.
                verified_topology = topology_evidence(topology_dir, new, aliases)
                topology.update(verified_topology)
                circular_contigs = set(verified_topology)
                opened = gzip.open(genes, "rt", encoding="utf-8") if str(genes).endswith(".gz") else genes.open(encoding="utf-8")
                with opened as handle: lines = [line.rstrip().split("\t") for line in handle if line.strip() and not line.startswith("#")]
                for parts in lines:
                    if len(parts) == 9 and parts[2] == "region" and "Is_circular=true" in parts[8].split(";"):
                        name = aliases.get(parts[0], parts[0])
                        if name in new and int(parts[3]) == 1 and int(parts[4]) == len(new[name]): circular_contigs.add(name)
                for parts in lines:
                    name = aliases.get(parts[0], parts[0]); start, end = int(parts[3]), int(parts[4])
                    if name not in new or start < 1 or start > end or start > len(new[name]): raise ValueError("Invalid annotation coordinate")
                    if end > len(new[name]):
                        if name not in circular_contigs or end > 2 * len(new[name]): raise ValueError("Unproven circular annotation overhang")
                        circular_features += 1
    for old_path, new_path in doc["experimental_asset_mapping"].items():
        if new_path.endswith((".bw", "metadata.tsv", "gene_associations.tsv.gz", "condition_observations.tsv.gz")) or "/studies/" in new_path and "/sources/" not in new_path:
            source = experimental / old_path
            if not source.is_file(): source = legacy / old_path
            if source.is_file():
                if sha256(source) != inventory[new_path]["sha256"]: raise ValueError("Original experimental record changed: " + old_path)
                raw_files += 1
    return {"complete": True, "release_manifest_sha256": report["release_manifest_sha256"],
            "batter_accepted_files_identical": count, "batter_biological_checks": "inherited_through_identical_SHA256_packages",
            "source_acceptance_report_sha256": sha256(source_report), "source_acceptance": original,
            "experimental_references_recompared": references, "experimental_raw_assets_preserved": raw_files,
            "explicit_circular_annotation_features": circular_features, "NCBI_topology_evidence": topology}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    for name in ("experimental-release", "legacy-assets", "batter-release", "output", "tools-bin"):
        prepare_parser.add_argument("--" + name, type=Path, required=True)
    prepare_parser.add_argument("--pilot-limit", type=int, default=0)
    prepare_parser.add_argument("--workers", type=int, default=8)
    prepare_parser.add_argument("--topology-dir", type=Path)
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--release", type=Path, required=True)
    verify_parser.add_argument("--tools-bin", type=Path)
    verify_parser.add_argument("--hts-library", type=Path)
    verify_parser.add_argument("--deep", action="store_true")
    verify_parser.add_argument("--workers", type=int, default=8)
    verify_parser.add_argument("--output", type=Path)
    audit_parser = commands.add_parser("audit-sources")
    for name in ("release", "batter-release", "source-report", "experimental-release", "legacy-assets", "deep-report", "output"):
        audit_parser.add_argument("--" + name, type=Path, required=True)
    audit_parser.add_argument("--topology-dir", type=Path)
    controls_parser = commands.add_parser("finalize-controls")
    controls_parser.add_argument("--release", type=Path, required=True)
    args = parser.parse_args()
    if getattr(args, "workers", 1) < 1:
        parser.error("workers must be positive")
    if args.command == "prepare":
        if args.pilot_limit < 0:
            parser.error("pilot-limit must be nonnegative")
        prepare(args)
    elif args.command == "verify":
        report = verify(args.release, args.tools_bin, args.deep, args.workers, args.hts_library)
        if args.output:
            json_write(args.output, report)
    elif args.command == "audit-sources":
        report = audit_sources(args.release, args.batter_release, args.source_report,
                               args.experimental_release, args.legacy_assets, args.deep_report, args.topology_dir)
        json_write(args.output, report)
        print(json.dumps(report), flush=True)
    else:
        print(json.dumps(finalize_controls(args.release)), flush=True)


if __name__ == "__main__":
    main()
