#!/usr/bin/env python3
"""Validate the public repository layout without inspecting biological data."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALLOWED_TOP_LEVEL = {
    ".gitattributes",
    ".github",
    ".gitignore",
    "CONTRIBUTING.md",
    "README.md",
    "bted_pipeline",
    "data",
    "docs",
    "jbrowse-plugin",
    "scripts",
    "site",
    "tests",
    "prototype",
}
REQUIRED_PATHS = {
    "README.md",
    "CONTRIBUTING.md",
    "docs/releases/v0.4.0.md",
    "docs/SOURCES.md",
    "docs/deployment.md",
    "data/public/v0.4.0/genomes/GCF_000006765.1/studies/PMID_31594819/gene_associations.tsv.gz",
    "data/public/v0.4.0/genomes/GCF_000008685.2/studies/PMID_37402717/condition_observations.tsv.gz",
    "data/public/v0.4.0/release.json",
    "data/public/v0.4.0/SHA256SUMS.txt",
    "data/registry/internal/v0.4.0/source_provenance.json",
    "data/registry/browser_assets.v0.4.0.tsv",
    "data/registry/genome_taxonomy.tsv",
    "data/registry/browser_refs/GCF_000012525.1.ncbi.zip",
    "data/registry/study_citations.v0.4.0.tsv",
    "jbrowse-plugin/package.json",
    "jbrowse-plugin/package-lock.json",
    "jbrowse-plugin/src/plugin.js",
    "data/registry/batter_s1_asset_redistribution.v0.3.tsv",
    "data/registry/internal/augmentation/README.md",
    "data/archive/BTED-v0.2.0.tar.gz",
    "data/archive/BTED-v0.2.0.tar.gz.sha256",
    "data/archive/BTED-v0.2.0.SHA256SUMS.txt",
    "data/archive/BTED-v0.3.0.tar.gz",
    "data/archive/BTED-v0.3.0.tar.gz.sha256",
    "data/archive/BTED-v0.3.0.SHA256SUMS.txt",
    "data/archive/BTED-external-intake-2026-08-10.tar.gz",
    "data/archive/BTED-external-intake-2026-08-10.tar.gz.sha256",
}
ALLOWED_DOC_FILES = {
    "docs/releases/v0.4.0.md",
    "docs/PROMOTER_COMPARISON.md",
    "docs/SOURCES.md",
    "docs/UI_REVIEW.md",
    "docs/USAGE_ANALYTICS.md",
    "docs/deployment.md",
}
REMOVED_ROOT_FILES = {
    "PROGRESS.md",
    "accession_list_verified.csv",
    "data_verification_report.md",
    "report_BATTER_supplementary.md",
    "report_zenodo_and_documents.md",
}


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={ROOT.as_posix()}", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    paths = [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]
    return [path for path in paths if (ROOT / path).exists()]


def main() -> int:
    tracked = tracked_files()
    tracked_set = set(tracked)
    errors: list[str] = []

    top_level = {path.split("/", 1)[0] for path in tracked}
    unexpected = sorted(top_level - ALLOWED_TOP_LEVEL)
    if unexpected:
        errors.append(f"unexpected top-level tracked entries: {unexpected}")

    missing = sorted(path for path in REQUIRED_PATHS if not (ROOT / path).is_file())
    if missing:
        errors.append(f"required files are missing: {missing}")

    augmentation_files = [
        path for path in (ROOT / "data/registry/internal/augmentation").rglob("*")
        if path.is_file() and path.name not in {"README.md", ".gitignore"}
    ] if (ROOT / "data/registry/internal/augmentation").is_dir() else []
    if len(augmentation_files) != 6:
        errors.append(
            "internal augmentation registry must preserve exactly six source data files; "
            f"found {len(augmentation_files)}"
        )

    legacy_endpoint_exports = {
        "endpoints.csv", "endpoints.tsv", "endpoints.tsv.gz", "endpoints.bed",
    }
    for public_root in (ROOT / "data/public/v0.4.0", ROOT / "site"):
        if not public_root.exists():
            continue
        legacy = sorted(
            path.relative_to(ROOT).as_posix()
            for path in public_root.rglob("*")
            if path.is_file() and path.name.lower() in legacy_endpoint_exports
        )
        if legacy:
            errors.append(f"legacy endpoint downloads remain in public source paths: {legacy}")

    extra_docs = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "docs").rglob("*")
        if path.is_file() and path.relative_to(ROOT).as_posix() not in ALLOWED_DOC_FILES
    )
    if extra_docs:
        errors.append(f"extra files remain under docs/: {extra_docs}")

    lingering_root = sorted(REMOVED_ROOT_FILES & tracked_set)
    if lingering_root:
        errors.append(f"legacy files remain at repository root: {lingering_root}")

    forbidden = sorted(
        path
        for path in tracked
        if path.startswith("docs/legacy/original-directories/")
        or "/__MACOSX/" in f"/{path}"
        or Path(path).name.startswith("._")
        or Path(path).name.endswith("_read_starts.txt")
    )
    if forbidden:
        errors.append(f"forbidden legacy/raw paths remain tracked: {forbidden}")

    retired = [
        path for path in (
            "backend", "frontend", "docker-compose.yml", "requirements-v03.txt",
            ".dockerignore", ".env.example",
            "data/public/records", "data/public/v0.2.0", "site/jbrowse",
            "scripts/stage_pages.py", "scripts/build_v0_2_site.py",
            "scripts/build_v0_2_release.py", "scripts/validate_bted_v0_2.py",
            "scripts/build_release_archives.py", "scripts/audit_v0_2_priority_sources.py",
            "scripts/audit_v0_2_external_links.py", "site/records", "site/assemblies",
            "site/data/catalog.json", "site/data/assemblies.json",
        )
        if (ROOT / path).exists()
    ]
    if retired:
        errors.append(f"retired or generated paths remain in the source tree: {retired}")

    if (ROOT / "data/public/v0.3.0").exists():
        errors.append("v0.3.0 per-file tree remains after archival")
    v04 = ROOT / "data/public/v0.4.0"
    if not v04.is_dir():
        errors.append("current public release directory is missing: data/public/v0.4.0")
    else:
        root_names = {path.name for path in v04.iterdir()}
        if root_names != {"genomes", "release.json", "SHA256SUMS.txt"}:
            errors.append(f"v0.4.0 has unexpected root entries: {sorted(root_names)}")
        genomes = sorted(path for path in (v04 / "genomes").iterdir() if path.is_dir()) if (v04 / "genomes").is_dir() else []
        if len(genomes) != 21:
            errors.append(f"expected 21 genome folders in v0.4.0, found {len(genomes)}")
        for genome in genomes:
            if not genome.name.startswith("GCF_") or not (genome / "metadata.tsv").is_file():
                errors.append(f"invalid genome folder: {genome.relative_to(ROOT)}")
            forbidden_json = list(genome.rglob("*.json"))
            if forbidden_json:
                errors.append(f"user-facing genome folder contains JSON: {genome.relative_to(ROOT)}")

    retired_augmentation_paths = [
        path for path in ("site/bted-augmentation.html", "site/data/augmentation")
        if (ROOT / path).exists()
    ]
    if retired_augmentation_paths:
        errors.append(f"retired augmentation site paths remain: {retired_augmentation_paths}")

    old_source_manifests = sorted(
        path for path in tracked if path.startswith("data/registry/manifests/")
    )
    if old_source_manifests:
        errors.append(f"per-source registry manifests were not consolidated: {old_source_manifests}")

    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1

    print("PASS: repository layout and documented file inventory")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
