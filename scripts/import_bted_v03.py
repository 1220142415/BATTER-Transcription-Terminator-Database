#!/usr/bin/env python3
"""Validate a BTED release and build or verify its offline bundle.

Examples::

    python3 scripts/import_bted_v03.py validate
    python3 scripts/import_bted_v03.py materialize \
        --release-root data/public/v0.3.0 \
        --output-dir /tmp/bted-v03-staging \
        --asset-origin-base https://example.test/assets \
        --generated-at-utc 2026-08-21T00:00:00Z
    python3 scripts/import_bted_v03.py verify-bundle \
        --bundle-dir /tmp/bted-v03-staging
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bted_pipeline import (  # noqa: E402
    BundleVerificationError,
    MaterializationError,
    materialize_release,
    validate_release,
    verify_bundle,
    verify_summary,
)
from bted_pipeline.materialize import TABLE_ORDER, _atomic_write_bundle  # noqa: E402
from scripts.v03_legacy_inputs import legacy_inputs, workspace_scratch  # noqa: E402
from scripts.v03_tables import iter_endpoints  # noqa: E402
from scripts.bted_v04_d1 import materialize_v04_d1  # noqa: E402


V03_RELEASE = "data/public/v0.3.0"


def _is_v03_release(path: str | Path) -> bool:
    return (Path(path) / "release.json").is_file()


def _v03_repo_root(path: str | Path, repo_root: str | None) -> Path:
    return Path(repo_root).resolve() if repo_root else Path(path).resolve().parents[2]


def _check_v03(repo_root: Path) -> dict[str, object]:
    from scripts.validate_bted_v0_3 import validate_release as validate_v03

    summary = validate_v03(repo_root)
    if summary.get("release_version") != "v0.3.0":
        raise ValueError("expected v0.3.0 release")
    return summary


def _study_metadata_index(repo_root: Path) -> dict[str, Path]:
    """Locate the metadata document that owns each source dataset."""

    study_root = repo_root / V03_RELEASE / "studies"
    result: dict[str, Path] = {}
    for path in sorted(study_root.glob("PMID_*/metadata.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for source in document.get("sources", []):
            source_id = str(source["source_id"])
            if source_id in result:
                raise ValueError(f"Source is listed in two study metadata files: {source_id}")
            result[source_id] = path
    if not result:
        raise ValueError(f"No study metadata found under {study_root}")
    return result


def _canonical_data_file_refs(repo_root: Path) -> dict[str, object]:
    """Record the actual study files and shared tables used by the bundle."""

    release_dir = repo_root / V03_RELEASE

    def file_ref(path: Path) -> dict[str, str]:
        if not path.is_file():
            raise ValueError(f"Missing v0.3.0 input: {path}")
        return {
            "path": path.relative_to(repo_root).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    studies = []
    for metadata in sorted((release_dir / "studies").glob("PMID_*/metadata.json")):
        study_files: dict[str, object] = {
            "pmid": metadata.parent.name.removeprefix("PMID_"),
            "endpoints": file_ref(metadata.parent / "endpoints.gff3.gz"),
            "metadata": file_ref(metadata),
            "metadata_tsv": file_ref(metadata.parent / "metadata.tsv"),
        }
        for table in ("gene_associations", "condition_observations"):
            table_path = metadata.parent / f"{table}.tsv.gz"
            if table_path.is_file():
                study_files[table] = file_ref(table_path)
        studies.append(study_files)
    if not studies:
        raise ValueError("v0.3.0 has no study files")
    if sum("gene_associations" in study for study in studies) != 1 or sum("condition_observations" in study for study in studies) != 1:
        raise ValueError("v0.3.0 related tables must each belong to exactly one study")
    return {"studies": studies}


def _promote_bundle(legacy_bundle: Path, output: Path, repo_root: Path) -> dict[str, object]:
    """Promote equivalent rows while retaining only current browser assets."""

    old_manifest = json.loads((legacy_bundle / "manifest.json").read_text(encoding="utf-8"))
    tables: dict[str, list[dict[str, object]]] = {}

    def replace_version(value: object) -> object:
        if value == "v0.2.0":
            return "v0.3.0"
        if isinstance(value, dict):
            return {key: replace_version(item) for key, item in value.items()}
        if isinstance(value, list):
            return [replace_version(item) for item in value]
        return value

    for name in TABLE_ORDER:
        path = legacy_bundle / f"{name}.jsonl"
        tables[name] = [replace_version(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines()]
    # Read D1 endpoint values from the current GFF3 release. The archived bundle
    # supplies relational keys, while this comparison guards every original field.
    current_endpoints = {
        (row["source_id"], row["end_id"]): row
        for row in iter_endpoints(repo_root / V03_RELEASE)
    }
    if len(current_endpoints) != len(tables["endpoints"]):
        raise ValueError("GFF3 endpoint count differs from the archived bundle")
    for row in tables["endpoints"]:
        key = (str(row["source_id_ref"]), str(row["end_id"]))
        current = current_endpoints.pop(key, None)
        if current is None:
            raise ValueError(f"GFF3 endpoint missing from archived bundle: {key}")
        for field, value in current.items():
            if str(row[field]) != value:
                raise ValueError(f"GFF3 endpoint field differs from archived bundle: {key}.{field}")
            row[field] = int(value) if field in {
                "biological_coordinate_1based", "bed_start_0based", "bed_end_0based"
            } else value
    if current_endpoints:
        raise ValueError("GFF3 contains endpoints absent from the archived bundle")
    release_path = repo_root / V03_RELEASE / "release.json"
    release_sha = hashlib.sha256(release_path.read_bytes()).hexdigest()
    study_metadata = _study_metadata_index(repo_root)
    archive_path = repo_root / "data/archive/BTED-v0.2.0.tar.gz"
    archive_sha = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    for row in tables["release_versions"]:
        row["canonical_manifest_path"] = f"{V03_RELEASE}/release.json"
        row["canonical_manifest_sha256"] = release_sha
    for row in tables["import_runs"]:
        row["input_manifest_path"] = f"{V03_RELEASE}/release.json"
        row["input_manifest_sha256"] = release_sha
    source_rows = {str(row["source_id"]): row for row in tables["sources"]}
    old_manifest_sha_by_source = {
        source_id: str(row["manifest_sha256"])
        for source_id, row in source_rows.items()
    }
    for source_id, row in source_rows.items():
        metadata_path = study_metadata[source_id]
        row["manifest_path"] = metadata_path.relative_to(repo_root).as_posix() + f"#source={source_id}"
        row["manifest_sha256"] = hashlib.sha256(metadata_path.read_bytes()).hexdigest()
        row["record_root"] = f"downloads/v0.3.0/records/{source_id}/"

    # Drop v0.2 per-source metadata, checksum, and BED objects. Keep only the
    # browser reference and raw-signal objects; the latter remain immutable
    # source assets with their original IDs and paths.
    browser_asset_kinds = {"fasta", "fai", "gff3", "tbi", "bigwig"}
    retained_browser_assets: list[dict[str, object]] = []
    historical_asset_id_map: list[dict[str, str]] = []
    for row in tables["assets"]:
        if str(row.get("asset_kind")) not in browser_asset_kinds:
            continue
        original_asset_id = str(row["asset_id"])
        if original_asset_id.startswith("v0.2.0--"):
            row["asset_id"] = "v0.3.0--" + original_asset_id[len("v0.2.0--"):]
            historical_asset_id_map.append(
                {"asset_id": str(row["asset_id"]), "historical_asset_id": original_asset_id}
            )
        retained_browser_assets.append(row)
    tables["assets"] = sorted(retained_browser_assets, key=lambda row: str(row["asset_id"]))

    manifest = replace_version(old_manifest)
    manifest["canonical_manifest"] = {"path": f"{V03_RELEASE}/release.json", "sha256": release_sha}
    manifest["derived_from"] = {
        "release_version": "v0.2.0",
        "archive_path": "data/archive/BTED-v0.2.0.tar.gz",
        "archive_sha256": archive_sha,
        "relationship": "row-and-field equivalent source, validated before materialization",
    }
    inventory = manifest.get("jbrowse_asset_inventory")
    if isinstance(inventory, dict):
        inventory_path = repo_root / "data/registry/jbrowse_assets.v0.2.0.json"
        inventory["path"] = "data/registry/jbrowse_assets.v0.2.0.json"
        inventory["sha256"] = hashlib.sha256(inventory_path.read_bytes()).hexdigest()
    contigs = manifest.get("contig_registry")
    if isinstance(contigs, dict):
        contig_path = repo_root / "data/registry/reference_contigs.v0.2.0.json"
        contigs["path"] = "data/registry/reference_contigs.v0.2.0.json"
        contigs["sha256"] = hashlib.sha256(contig_path.read_bytes()).hexdigest()
    field_provenance = manifest.get("annotation_field_provenance")
    if isinstance(field_provenance, list):
        for item in field_provenance:
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("source_id", ""))
            metadata_path = study_metadata[source_id]
            item["fields_json_path"] = metadata_path.relative_to(repo_root).as_posix() + f"#source={source_id}/fields"
            item["fields_json_sha256"] = hashlib.sha256(metadata_path.read_bytes()).hexdigest()
            item["source_annotations_path"] = (
                f"data/archive/BTED-v0.2.0.tar.gz::"
                f"data/public/v0.2.0/records/{source_id}/source_annotations.tsv"
                if item.get("source_annotations_path") else None
            )
    manifest["canonical_data_files"] = _canonical_data_file_refs(repo_root)
    manifest["historical_asset_id_map"] = {
        "audit_policy": "v0.2.0 remote audit identities are historical and are not reused as v0.3.0 verification",
        "rows": historical_asset_id_map,
    }
    manifest["legacy_source_manifest_sha256"] = {
        "path_template": "data/archive/BTED-v0.2.0.tar.gz::data/public/v0.2.0/records/{source_id}/manifest.json",
        "sha256_by_source": old_manifest_sha_by_source,
    }
    manifest.pop("tables", None)
    return _atomic_write_bundle(output.resolve(), tables, manifest)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="校验 canonical release；不写数据库")
    validate.add_argument(
        "--release-root",
        default=V03_RELEASE,
        help="release root (default: data/public/v0.3.0)",
    )
    validate.add_argument(
        "--repo-root",
        default=None,
        help="repository root; defaults to the conventional parent of --release-root",
    )
    validate.add_argument(
        "--plan-json",
        default=None,
        help="write the deterministic import plan to this path",
    )
    validate.add_argument(
        "--contig-registry",
        default=None,
        help=(
            "reference contig provenance TSV; defaults to "
            "reference contig registry; optional for legacy release inputs"
        ),
    )
    materialize = subparsers.add_parser(
        "materialize",
        help="在不连接数据库的情况下生成确定性的 JSONL 写库前 staging bundle",
    )
    materialize.add_argument(
        "--release-root",
        default=V03_RELEASE,
        help="release root (default: data/public/v0.3.0)",
    )
    materialize.add_argument(
        "--repo-root",
        default=None,
        help="repository root; defaults to the conventional parent of --release-root",
    )
    materialize.add_argument(
        "--contig-registry",
        default=None,
        help="reference contig provenance TSV; defaults to the tracked registry",
    )
    materialize.add_argument(
        "--output-dir",
        required=True,
        help="new or empty directory for the materialization bundle; non-empty directories are refused",
    )
    materialize.add_argument(
        "--asset-origin-base",
        required=True,
        help="HTTPS-only planned origin prefix; no remote request is made",
    )
    materialize.add_argument(
        "--generated-at-utc",
        default=None,
        help="fixed ISO-8601 timestamp for reproducible output (default: current UTC time)",
    )
    materialize.add_argument(
        "--jbrowse-asset-inventory",
        default=None,
        help=(
            "tracked browser asset TSV/JSON to merge; defaults to the repository inventory"
        ),
    )
    materialize.add_argument(
        "--jbrowse-bundle-root",
        default=None,
        help=(
            "local JBrowse bundle root containing the registered reference GFF3/FAI files; "
            "gene import is enabled only together with --jbrowse-asset-inventory"
        ),
    )
    verify = subparsers.add_parser(
        "verify-bundle",
        help="只读验证 B1 JSONL bundle，不连接数据库",
    )
    verify.add_argument(
        "--bundle-dir",
        required=True,
        help="B1 materialization bundle directory",
    )
    materialize_v04 = subparsers.add_parser(
        "materialize-v04",
        help="从 v0.4.0 genome GFF3 与内部来源清单生成 D1 staging bundle",
    )
    materialize_v04.add_argument(
        "--release-root", default="data/public/v0.4.0",
        help="canonical v0.4.0 release directory",
    )
    materialize_v04.add_argument(
        "--source-provenance", default="data/registry/internal/v0.4.0/source_provenance.json",
        help="internal source defaults and annotation maps with SHA256SUMS.txt",
    )
    materialize_v04.add_argument(
        "--asset-manifest", default="data/registry/browser_assets.v0.4.0.tsv",
        help="single allowlist for fixed HF assets, sizes and SHA-256 values",
    )
    materialize_v04.add_argument(
        "--contig-registry", default=None,
        help="additional verified contigs TSV (defaults to data/registry/browser_refs/contigs.tsv)",
    )
    materialize_v04.add_argument(
        "--output-dir", required=True,
        help="new or empty directory for the v0.4.0 D1 staging bundle",
    )
    materialize_v04.add_argument(
        "--origin-verified", action="store_true",
        help="assert after independent remote checks that every fixed asset passed size/SHA and required Range checks",
    )
    materialize_v04.add_argument(
        "--generated-at-utc", default=None,
        help="fixed ISO-8601 timestamp for reproducible output",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "materialize-v04":
        try:
            manifest = materialize_v04_d1(
                release_root=args.release_root,
                source_provenance_path=args.source_provenance,
                asset_manifest_path=args.asset_manifest,
                output_dir=args.output_dir,
                repo_root=REPO_ROOT,
                contig_registry_path=args.contig_registry,
                origin_verified=args.origin_verified,
                generated_at_utc=args.generated_at_utc,
            )
            verification = verify_bundle(args.output_dir)
            json.dump(
                {
                    "ok": True,
                    "output_dir": str(Path(args.output_dir).expanduser().resolve()),
                    "release_version": verification.release_version,
                    "table_counts": verification.table_counts,
                    "asset_origin_status": manifest["asset_origin"]["asset_origin_status"],
                },
                sys.stdout,
                ensure_ascii=False,
                indent=2,
            )
            sys.stdout.write("\n")
            return 0
        except (ValueError, OSError, MaterializationError, BundleVerificationError) as exc:
            json.dump({"ok": False, "error": str(exc)}, sys.stderr, ensure_ascii=False)
            sys.stderr.write("\n")
            return 1
    if args.command in {"validate", "materialize"} and _is_v03_release(args.release_root):
        repo_root = _v03_repo_root(args.release_root, args.repo_root)
        try:
            summary = _check_v03(repo_root)
            with legacy_inputs(repo_root) as (temporary_repo, legacy_release, inventory):
                report = validate_release(
                    legacy_release,
                    repo_root=temporary_repo,
                    contig_registry=temporary_repo / "data/registry/reference_contigs.v0.2.0.tsv",
                )
                if not report.ok:
                    raise ValueError("archived source validation failed: " + "; ".join(
                        issue.message for issue in report.issues[:5]
                    ))
                if args.command == "validate":
                    result = {"ok": True, "summary": summary, "legacy_bridge": "validated"}
                    if args.plan_json:
                        target = Path(args.plan_json).expanduser()
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
                    sys.stdout.write("\n")
                    return 0
                with workspace_scratch(repo_root, "bted-v03-materialize-") as directory:
                    temporary_bundle = directory / "bundle"
                    old_result = materialize_release(
                        legacy_release,
                        repo_root=temporary_repo,
                        contig_registry=temporary_repo / "data/registry/reference_contigs.v0.2.0.tsv",
                        output_dir=temporary_bundle,
                        asset_origin_base=args.asset_origin_base,
                        generated_at_utc=args.generated_at_utc,
                        jbrowse_asset_inventory=inventory,
                        jbrowse_bundle_root=(
                            str(Path(args.jbrowse_bundle_root).resolve())
                            if args.jbrowse_bundle_root else None
                        ),
                    )
                    promoted = _promote_bundle(temporary_bundle, Path(args.output_dir), repo_root)
                    verification = verify_bundle(args.output_dir)
                    json.dump(
                        {"ok": True, "output_dir": str(Path(args.output_dir).resolve()),
                         "release_version": verification.release_version,
                         "table_counts": verification.table_counts,
                         "legacy_materialized_asset_count": old_result.table_counts["assets"],
                         "retained_browser_asset_count": verification.table_counts["assets"],
                         "manifest": promoted},
                        sys.stdout, ensure_ascii=False, indent=2,
                    )
                    sys.stdout.write("\n")
                    return 0
        except (ValueError, OSError, MaterializationError, BundleVerificationError) as exc:
            json.dump({"ok": False, "error": str(exc)}, sys.stderr, ensure_ascii=False)
            sys.stderr.write("\n")
            return 1
    if args.command == "validate":
        report = validate_release(
            args.release_root,
            repo_root=args.repo_root,
            contig_registry=args.contig_registry,
        )
        if args.plan_json:
            plan_path = Path(args.plan_json).expanduser()
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text(
                json.dumps(report.plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        json.dump(report.as_dict(), sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0 if report.ok else 1
    if args.command == "materialize":
        try:
            result = materialize_release(
                args.release_root,
                repo_root=args.repo_root,
                contig_registry=args.contig_registry,
                output_dir=args.output_dir,
                asset_origin_base=args.asset_origin_base,
                generated_at_utc=args.generated_at_utc,
                jbrowse_asset_inventory=args.jbrowse_asset_inventory,
                jbrowse_bundle_root=args.jbrowse_bundle_root,
            )
        except MaterializationError as exc:
            json.dump({"ok": False, "error": str(exc)}, sys.stderr, ensure_ascii=False)
            sys.stderr.write("\n")
            return 1
        json.dump(
            {"ok": True, "output_dir": str(result.output_dir), "manifest": result.manifest},
            sys.stdout,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        sys.stdout.write("\n")
        return 0
    if args.command == "verify-bundle":
        try:
            verification = verify_bundle(args.bundle_dir)
            json.dump(verify_summary(verification), sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
            sys.stdout.write("\n")
            return 0
        except BundleVerificationError as exc:
            json.dump({"ok": False, "error": str(exc)}, sys.stderr, ensure_ascii=False)
            sys.stderr.write("\n")
            return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
