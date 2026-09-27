"""Build temporary v0.2-shaped inputs for the existing bundle validator.

The public v0.3 tables are checked against the frozen v0.2 archive before this
adapter is used. Nothing here restores the old per-source tree in the repo.
"""

from __future__ import annotations

import csv
import json
import shutil
import tarfile
import uuid
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Iterator

from bted_pipeline.canonical import REFERENCE_CONTIG_COLUMNS
from bted_pipeline.materialize import JBROWSE_INVENTORY_COLUMNS


SOURCE_REGISTRY_COLUMNS = (
    "source_id", "published_year", "species", "phylum", "reference_genome", "pmid",
    "paper_title", "doi", "pmc", "raw_data_accessions", "assay_family",
    "used_for_batter_augmentation", "accessibility_status", "coordinate_status",
    "processing_status", "blocker_or_note",
)
ASSET_POLICY_COLUMNS = (
    "source_id", "asset_scope", "license", "redistribution_status", "is_public",
    "license_source", "note",
)


@contextmanager
def workspace_scratch(repo_root: Path, prefix: str) -> Iterator[Path]:
    """Use the ignored workspace tmp directory with inherited Windows ACLs."""

    scratch = repo_root / "tmp"
    scratch.mkdir(exist_ok=True)
    directory = scratch / f"{prefix}{uuid.uuid4().hex}"
    directory.mkdir()
    try:
        yield directory
    finally:
        shutil.rmtree(directory)


def _write_tsv(path: Path, rows: list[dict[str, object]], fields: tuple[str, ...] | list[str]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(fields)
    if any(set(row) != set(fields) for row in rows):
        raise ValueError(f"inconsistent columns for {path.name}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _unpack_archive(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle:
            relative = PurePosixPath(member.name)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or not member.isfile()
                or relative.parts[:3] != ("data", "public", "v0.2.0")
            ):
                raise ValueError(f"unsafe or unexpected archive member: {member.name}")
            output = destination.joinpath(*relative.parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            source = bundle.extractfile(member)
            if source is None:
                raise ValueError(f"cannot read archive member: {member.name}")
            with source, output.open("wb") as target:
                while block := source.read(1024 * 1024):
                    target.write(block)


@contextmanager
def legacy_inputs(repo_root: Path) -> Iterator[tuple[Path, Path, Path]]:
    """Yield (temporary repo, legacy release, legacy inventory TSV)."""

    repo_root = repo_root.resolve()
    archive = repo_root / "data/archive/BTED-v0.2.0.tar.gz"
    study_root = repo_root / "data/public/v0.3.0/studies"
    sources = [
        source
        for metadata_path in sorted(study_root.glob("PMID_*/metadata.json"))
        for source in json.loads(metadata_path.read_text(encoding="utf-8"))["sources"]
    ]
    sources.sort(key=lambda source: source["source_id"])
    if len(sources) != 22:
        raise ValueError("v0.3 sources must contain 22 entries")
    with workspace_scratch(repo_root, "bted-v03-legacy-") as temporary_repo:
        _unpack_archive(archive, temporary_repo)
        registry = temporary_repo / "data/registry"
        registry.mkdir(parents=True, exist_ok=True)
        _write_tsv(
            registry / "batter_s1_source_registry.tsv",
            [dict(source["registry_row"]) for source in sources],
            SOURCE_REGISTRY_COLUMNS,
        )
        policies: list[dict[str, object]] = []
        for source in sources:
            source_id = str(source["source_id"])
            manifest = source["registry_manifest"]
            manifest_path = registry / "manifests" / f"{source_id}.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            policy = source.get("asset_redistribution", [])
            if isinstance(policy, dict):
                policies.append(policy)
            else:
                policies.extend(policy)
        _write_tsv(registry / "batter_s1_asset_redistribution.v0.3.tsv", policies, ASSET_POLICY_COLUMNS)
        contigs = json.loads(
            (repo_root / "data/registry/reference_contigs.v0.2.0.json").read_text(encoding="utf-8")
        )
        _write_tsv(registry / "reference_contigs.v0.2.0.tsv", contigs["rows"], REFERENCE_CONTIG_COLUMNS)
        inventory = json.loads(
            (repo_root / "data/registry/jbrowse_assets.v0.2.0.json").read_text(encoding="utf-8")
        )
        inventory_path = registry / "jbrowse_assets.v0.2.0.tsv"
        _write_tsv(inventory_path, inventory["rows"], JBROWSE_INVENTORY_COLUMNS)
        yield temporary_repo, temporary_repo / "data/public/v0.2.0", inventory_path
