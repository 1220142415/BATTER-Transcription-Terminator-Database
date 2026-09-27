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
    "scripts",
    "site",
    "tests",
    "prototype",
}
REQUIRED_PATHS = {
    "README.md",
    "CONTRIBUTING.md",
    "docs/releases/v0.3.0.md",
    "docs/SOURCES.md",
    "docs/v0.3/deployment.md",
    "data/public/v0.3.0/studies/PMID_31594819/gene_associations.tsv.gz",
    "data/public/v0.3.0/studies/PMID_37402717/condition_observations.tsv.gz",
    "data/public/v0.3.0/release.json",
    "data/public/v0.3.0/SHA256SUMS.txt",
    "data/registry/internal/augmentation/README.md",
    "data/archive/BTED-v0.2.0.tar.gz",
    "data/archive/BTED-v0.2.0.tar.gz.sha256",
    "data/archive/BTED-v0.2.0.SHA256SUMS.txt",
}
ALLOWED_DOC_FILES = {
    "docs/releases/v0.3.0.md",
    "docs/SOURCES.md",
    "docs/v0.3/deployment.md",
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
    for public_root in (ROOT / "data/public/v0.3.0", ROOT / "site"):
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

    if not (ROOT / "data/public/v0.3.0").is_dir():
        errors.append("current public release directory is missing: data/public/v0.3.0")
    else:
        root_names = {path.name for path in (ROOT / "data/public/v0.3.0").iterdir()}
        expected_root_names = {"studies", "release.json", "SHA256SUMS.txt"}
        if root_names != expected_root_names:
            errors.append(f"v0.3.0 has unexpected root entries: {sorted(root_names - expected_root_names)}")
    study_root = ROOT / "data/public/v0.3.0/studies"
    study_dirs = sorted(path for path in study_root.iterdir() if path.is_dir()) if study_root.is_dir() else []
    if len(study_dirs) != 13:
        errors.append(f"expected 13 study folders in v0.3.0, found {len(study_dirs)}")
    for study_dir in study_dirs:
        names = {path.name for path in study_dir.iterdir()}
        expected_names = {"endpoints.gff3.gz", "metadata.json", "metadata.tsv"}
        if study_dir.name == "PMID_31594819":
            expected_names.add("gene_associations.tsv.gz")
        if study_dir.name == "PMID_37402717":
            expected_names.add("condition_observations.tsv.gz")
        if not study_dir.name.startswith("PMID_") or names != expected_names:
            errors.append(f"study folder has unexpected name or files: {study_dir.relative_to(ROOT)}")
    for retired_name in ("endpoints.gff3.gz", "sources.json", "gene_associations.tsv.gz", "condition_observations.tsv.gz"):
        if (ROOT / "data/public/v0.3.0" / retired_name).exists():
            errors.append(f"retired combined release file remains: {retired_name}")
    if (ROOT / "data/public/v0.3.0/sources.tsv").exists():
        errors.append("sources.tsv is a staging-only download and must not be stored in data/public/v0.3.0")
    retired_jsonl = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "data/public/v0.3.0").glob("*.jsonl.gz")
    ) if (ROOT / "data/public/v0.3.0").is_dir() else []
    if retired_jsonl:
        errors.append(f"retired v0.3.0 JSONL release files remain: {retired_jsonl}")

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

    print("PASS: repository layout and three essential docs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
