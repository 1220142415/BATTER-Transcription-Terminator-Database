#!/usr/bin/env python3
"""Assemble Pages or Worker site assets from a verified BTED JBrowse release."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
import uuid
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlsplit

from build_assembly_downloads import RELEASE_VERSION, build as build_assembly_downloads, load_sources
from build_v0_3_site import build_site as build_v03_site
import build_v0_4_site as v04_site
from build_v0_4_site import SiteBuildError, build_site as build_v04_site, materialize_browser_tracks, read_release as read_v04_release


REPO_ROOT = Path(__file__).resolve().parent.parent
BTED_PLUGIN_SOURCE = REPO_ROOT / "jbrowse-plugin/dist/bted-track-plugin.js"
BTED_CITATIONS = REPO_ROOT / "data/registry/study_citations.v0.4.0.tsv"
PLUS_STRAND_COLOR = "#0f766e"
MINUS_STRAND_COLOR = "#be123c"
UNKNOWN_STRAND_COLOR = "#64748b"
PACKAGE_NAME = "BTED-v0.2.0-jbrowse"
ARCHIVE_NAME = f"{PACKAGE_NAME}-assets.tar.gz"
RUNTIME_FILES = ("index.html", "manifest.json", "favicon.ico", "robots.txt", "version.txt")
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
STAGE_MARKER = ".bted-stage.json"
SHA_LINE = re.compile(r"^([0-9a-fA-F]{64})(?:\s+\*?(.+))?$")
HF_DATA_BASE_PATTERN = re.compile(
    r"^https://huggingface\.co/datasets/liurulong/terminator/resolve/([0-9a-f]{40})/v0\.3\.0$"
)
HF_V04_DATA_BASE_PATTERN = re.compile(
    r"^https://huggingface\.co/datasets/liurulong/terminator/resolve/([0-9a-f]{40})/v0\.4\.0$"
)
HF_DATASET_ROOT = "https://huggingface.co/datasets/liurulong/terminator/resolve"
V03_SHARED_REVISION = "90651318aedf5a5ca26b8308070927d36fd3d6c9"
V03_SHARED_BASE_URL = f"{HF_DATASET_ROOT}/{V03_SHARED_REVISION}/v0.3.0"
V04_BROWSER_ASSET_FIELDS = ("logical_path", "url", "byte_size", "sha256", "revision", "asset_kind")
class StageError(RuntimeError):
    """Raised when a requested site artifact cannot be safely assembled."""


def load_study_citations(path: Path = BTED_CITATIONS) -> dict[str, dict[str, str]]:
    if not path.is_file():
        raise StageError(f"Study citation table is missing: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {"pmid", "title", "authors", "journal", "year", "doi", "pubmed_url"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise StageError("Study citation table lacks required columns")
        rows = list(reader)
    citations = {row["pmid"]: row for row in rows}
    if len(rows) != 14 or len(citations) != len(rows):
        raise StageError("Expected 14 distinct study citations")
    return citations


def install_bted_plugin(package_root: Path) -> None:
    if not BTED_PLUGIN_SOURCE.is_file():
        raise StageError("BTED JBrowse plugin is not built; run npm ci and npm run build in jbrowse-plugin/")
    if (package_root / "version.txt").read_text(encoding="utf-8").strip() != "4.3.0":
        raise StageError("BTED JBrowse plugin requires the pinned 4.3.0 application")
    destination = package_root / "plugins" / BTED_PLUGIN_SOURCE.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(BTED_PLUGIN_SOURCE, destination)
    if destination.stat().st_size > 100_000:
        raise StageError("BTED JBrowse plugin is unexpectedly large")


class _LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name in {"href", "src"} and value:
                self.references.append(value)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_archive_sha256(archive: Path, checksum_file: Path) -> str:
    if not archive.is_file():
        raise StageError(f"Release archive does not exist: {archive}")
    if not checksum_file.is_file():
        raise StageError(f"Release checksum file does not exist: {checksum_file}")
    lines = [line.strip() for line in checksum_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) != 1:
        raise StageError(f"Expected one SHA-256 entry in {checksum_file}")
    match = SHA_LINE.fullmatch(lines[0])
    if not match:
        raise StageError(f"Malformed SHA-256 entry in {checksum_file}")
    expected, named_file = match.groups()
    if named_file and Path(named_file).name != archive.name:
        raise StageError(f"Checksum names {named_file!r}, but the archive is {archive.name!r}")
    actual = sha256_file(archive)
    if actual.lower() != expected.lower():
        raise StageError(f"Release archive SHA-256 mismatch: expected {expected.lower()}, got {actual}")
    return actual


def safe_extract_release(archive: Path, destination: Path) -> Path:
    """Extract only regular files beneath the expected package directory."""
    destination.mkdir(parents=True, exist_ok=True)
    package_root = destination / PACKAGE_NAME
    seen: set[tuple[str, ...]] = set()
    extracted_bytes = 0
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        if len(members) > 50_000:
            raise StageError(f"Release archive has too many entries: {len(members)}")
        for member in members:
            raw_name = member.name
            if "\\" in raw_name or ":" in raw_name:
                raise StageError(f"Unsafe path in release archive: {raw_name!r}")
            relative = PurePosixPath(raw_name)
            parts = tuple(part for part in relative.parts if part not in {"", "."})
            if relative.is_absolute() or not parts or ".." in parts:
                raise StageError(f"Unsafe path in release archive: {raw_name!r}")
            if parts[0] != PACKAGE_NAME:
                raise StageError(f"Unexpected top-level path in release archive: {raw_name!r}")
            if parts in seen:
                raise StageError(f"Duplicate path in release archive: {raw_name!r}")
            seen.add(parts)
            if not (member.isdir() or member.isfile()):
                raise StageError(f"Non-regular entry in release archive: {raw_name!r}")
            if member.isfile():
                extracted_bytes += member.size
                if member.size < 0 or extracted_bytes > MAX_ARCHIVE_BYTES:
                    raise StageError("Release archive expands beyond the 1 GiB safety limit")

            target = destination.joinpath(*parts)
            try:
                target.resolve().relative_to(destination.resolve())
            except ValueError as exc:
                raise StageError(f"Archive path escapes extraction directory: {raw_name!r}") from exc
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            stream = tar.extractfile(member)
            if stream is None:
                raise StageError(f"Cannot read archive entry: {raw_name!r}")
            with stream, target.open("wb") as output:
                shutil.copyfileobj(stream, output)

    if not (package_root / "catalog.json").is_file():
        raise StageError(f"Release archive is missing {PACKAGE_NAME}/catalog.json")
    return package_root


def run_validator(script_name: str, package_root: Path, *arguments: str) -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / script_name), str(package_root), *arguments],
        cwd=REPO_ROOT,
        check=False,
    )
    if result.returncode:
        raise StageError(f"{script_name} rejected {package_root}")


def _endpoint_track(source: dict[str, object], assembly_name: str, gff3_uri: str) -> dict[str, object]:
    source_id = str(source["source_id"])
    track_id = f"bted_v03_{source_id.lower()}_endpoints"
    display_id = f"{track_id}-LinearBasicDisplay"
    return {
        "type": "FeatureTrack",
        "trackId": track_id,
        "name": f"{source_id} · BTED v0.3.0 endpoints",
        "description": "BTED v0.3.0 endpoint records. See the source record for provenance and file metadata.",
        "adapter": {
            "type": "Gff3Adapter",
            "gffLocation": {"uri": gff3_uri, "locationType": "UriLocation"},
        },
        "displays": [{"type": "LinearBasicDisplay", "displayId": display_id, "showLabels": False}],
        "category": ["BTED v0.3.0", "Endpoint records"],
        "assemblyNames": [assembly_name],
        "metadata": {
            "release_version": RELEASE_VERSION,
            "source_id": source_id,
            "record_count": int(source["record_count"]),
            "evidence_class": source["evidence_class"],
        },
    }


def _add_track_to_config(config: dict[str, object], track: dict[str, object]) -> None:
    tracks = config.setdefault("tracks", [])
    if not isinstance(tracks, list):
        raise StageError("JBrowse config tracks must be a list")
    track_id = str(track["trackId"])
    existing = next((item for item in tracks if item.get("trackId") == track_id), None)
    if existing is None:
        tracks.append(track)
    elif existing != track:
        raise StageError(f"Conflicting generated endpoint track in JBrowse config: {track_id}")

    session = config.get("defaultSession", {})
    views = session.get("views", []) if isinstance(session, dict) else []
    if not views:
        raise StageError(f"JBrowse config has no default linear view for {track_id}")
    view = views[0]
    view_tracks = view.setdefault("tracks", [])
    if not any(item.get("configuration") == track_id for item in view_tracks):
        view_tracks.append({
            "id": f"{track_id}-view",
            "type": "FeatureTrack",
            "configuration": track_id,
            "minimized": False,
            "displays": [{
                "id": f"{track_id}-display",
                "type": "LinearBasicDisplay",
                "configuration": str(track["displays"][0]["displayId"]),
            }],
        })


def _remove_legacy_endpoint_tracks(config: dict[str, object]) -> None:
    """Replace old endpoint/candidate features while keeping reference and signal tracks."""

    tracks = config.get("tracks", [])
    if not isinstance(tracks, list) or any(not isinstance(track, dict) for track in tracks):
        raise StageError("JBrowse config tracks must be a list of objects")

    def is_reference(track: dict[str, object]) -> bool:
        category = track.get("category", [])
        categories = category if isinstance(category, list) else [category]
        labels = [str(track.get("name", "")), *map(str, categories)]
        label = " ".join(labels).lower()
        return "reference annotation" in label or "gene annotation" in label

    removed = {
        str(track["trackId"])
        for track in tracks
        if track.get("type") == "FeatureTrack"
        and not is_reference(track)
        and not str(track.get("trackId", "")).startswith("bted_v03_")
    }
    if not removed:
        return
    config["tracks"] = [track for track in tracks if str(track.get("trackId", "")) not in removed]
    session = config.get("defaultSession")
    if isinstance(session, dict):
        for view in session.get("views", []):
            if isinstance(view, dict) and isinstance(view.get("tracks"), list):
                view["tracks"] = [
                    track for track in view["tracks"]
                    if not isinstance(track, dict) or track.get("configuration") not in removed
                ]


def _remove_nonredistributable_signal_tracks(config: dict[str, object]) -> set[str]:
    """Drop derived signed-log display tracks while retaining licensed raw signals."""
    tracks = config.get("tracks", [])
    if not isinstance(tracks, list) or any(not isinstance(track, dict) for track in tracks):
        raise StageError("JBrowse config tracks must be a list of objects")
    removed = {
        str(track["trackId"])
        for track in tracks
        if track.get("trackId")
        and any("signed-log10-ui-v4" in uri for uri in _all_config_uris(track))
    }
    if not removed:
        return removed
    config["tracks"] = [track for track in tracks if str(track.get("trackId", "")) not in removed]
    session = config.get("defaultSession")
    if isinstance(session, dict):
        for view in session.get("views", []):
            if isinstance(view, dict) and isinstance(view.get("tracks"), list):
                view["tracks"] = [
                    track for track in view["tracks"]
                    if not isinstance(track, dict) or track.get("configuration") not in removed
                ]
    return removed


def _remove_unpublished_text_search_indices(
    config: dict[str, object],
    asset_paths: dict[str, dict[str, str]],
) -> set[str]:
    """Drop optional JBrowse text-search adapters backed by unpublished indexes."""
    adapters = config.get("aggregateTextSearchAdapters", [])
    if not isinstance(adapters, list) or any(not isinstance(adapter, dict) for adapter in adapters):
        raise StageError("JBrowse aggregateTextSearchAdapters must be a list of objects")
    removed = set()
    retained = []
    for adapter in adapters:
        uris = _all_config_uris(adapter)
        if any(_normalize_bundled_asset_uri(uri) not in asset_paths for uri in uris):
            adapter_id = adapter.get("textSearchAdapterId")
            if adapter_id:
                removed.add(str(adapter_id))
            continue
        retained.append(adapter)
    if retained:
        config["aggregateTextSearchAdapters"] = retained
    else:
        config.pop("aggregateTextSearchAdapters", None)
    return removed


def _read_config(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StageError(f"Could not read JBrowse config {path}") from exc
    if not isinstance(payload, dict):
        raise StageError(f"JBrowse config must be a JSON object: {path}")
    return payload


def normalize_hf_data_base_url(value: str) -> tuple[str, str]:
    """Require a fixed commit URL for the public v0.3.0 Hugging Face objects."""
    base = value.strip().rstrip("/")
    match = HF_DATA_BASE_PATTERN.fullmatch(base)
    if not match:
        raise StageError(
            "--hf-data-base-url must be the fixed v0.3.0 URL "
            "https://huggingface.co/datasets/liurulong/terminator/resolve/<40-character-commit>/v0.3.0"
        )
    return base, match.group(1)


def load_public_jbrowse_asset_paths(
    inventory_path: Path | None = None,
    bundle_catalog: dict[str, object] | None = None,
) -> dict[str, dict[str, str]]:
    """Map bundled JBrowse URIs to the approved v0.3.0 logical object paths."""
    inventory = inventory_path or REPO_ROOT / "data/registry/jbrowse_assets.v0.2.0.json"
    try:
        payload = json.loads(inventory.read_text(encoding="utf-8"))
        rows = payload["rows"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise StageError(f"Could not read JBrowse asset inventory: {inventory}") from exc
    if not isinstance(rows, list):
        raise StageError(f"JBrowse asset inventory has no rows list: {inventory}")

    allowed_kinds = {"fasta", "fai", "gff3", "tbi", "bigwig"}
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise StageError(f"JBrowse asset inventory contains a non-object row: {inventory}")
        if (
            row.get("is_public") != "true"
            or row.get("redistribution_status") != "verified_redistributable"
            or row.get("asset_kind") not in allowed_kinds
        ):
            continue
        bundle_path = str(row.get("bundle_path", "")).strip().replace("\\", "/")
        object_path = str(row.get("object_path", "")).strip().replace("\\", "/")
        if not bundle_path or not object_path:
            continue
        bundle_rel = PurePosixPath(bundle_path)
        object_rel = PurePosixPath(object_path)
        if (
            bundle_rel.is_absolute()
            or object_rel.is_absolute()
            or ".." in bundle_rel.parts
            or ".." in object_rel.parts
        ):
            raise StageError(f"Unsafe JBrowse inventory path: {bundle_path!r} -> {object_path!r}")
        item = {
            "object_path": object_rel.as_posix(),
            "sha256": str(row.get("sha256", "")).lower(),
            "asset_kind": str(row.get("asset_kind", "")),
        }
        if not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            raise StageError(f"Invalid SHA-256 in JBrowse asset inventory for {bundle_path}")
        key = bundle_rel.as_posix()
        if key in result and result[key] != item:
            raise StageError(f"Conflicting JBrowse inventory rows for {key}")
        result[key] = item

    if bundle_catalog is not None:
        source_catalog = bundle_catalog.get("sources", {})
        if not isinstance(source_catalog, dict):
            raise StageError("JBrowse release catalog must contain a source mapping")
        for shared in payload.get("deduplicated_shared_references", []):
            if not isinstance(shared, dict):
                raise StageError("JBrowse asset inventory has an invalid shared-reference entry")
            representative = str(shared.get("representative_source_id", ""))
            source_ids = shared.get("source_ids", [])
            if not representative or not isinstance(source_ids, list):
                raise StageError("JBrowse shared-reference entry is missing source identifiers")
            representative_rows = [
                row for row in rows
                if isinstance(row, dict)
                and row.get("source_id") == representative
                and str(row.get("asset_role", "")).startswith("reference_")
                and row.get("is_public") == "true"
                and row.get("redistribution_status") == "verified_redistributable"
            ]
            for source_id in source_ids:
                alias_source = str(source_id)
                if alias_source == representative:
                    continue
                alias_entry = source_catalog.get(alias_source)
                if not isinstance(alias_entry, dict):
                    continue
                alias_assets = alias_entry.get("assets", []) if isinstance(alias_entry, dict) else []
                if not isinstance(alias_assets, list):
                    raise StageError(f"JBrowse catalog assets are invalid for {alias_source}")
                for row in representative_rows:
                    kind = str(row.get("asset_kind", ""))
                    representative_path = str(row.get("bundle_path", "")).replace("\\", "/").lower()
                    gff3_extension = (
                        ".gff3.gz" if representative_path.endswith(".gff3.gz") else ".gff3"
                    ) if kind == "gff3" else None
                    candidates = [
                        str(asset).replace("\\", "/")
                        for asset in alias_assets
                        if isinstance(asset, str)
                        and _bundled_asset_kind(asset) == kind
                        and (gff3_extension is None or asset.lower().endswith(gff3_extension))
                    ]
                    if len(candidates) != 1:
                        raise StageError(
                            f"Expected one {kind} reference alias for {alias_source}; found {len(candidates)}"
                        )
                    alias_path = candidates[0]
                    item = {
                        "object_path": str(row["object_path"]).replace("\\", "/"),
                        "sha256": str(row["sha256"]).lower(),
                        "asset_kind": kind,
                    }
                    if alias_path in result and result[alias_path] != item:
                        raise StageError(f"Conflicting shared-reference inventory rows for {alias_path}")
                    result[alias_path] = item
    if not result:
        raise StageError(f"JBrowse asset inventory has no public assets: {inventory}")
    return result


def _bundled_asset_kind(path: str) -> str:
    lower = path.lower()
    if lower.endswith(".fai"):
        return "fai"
    if lower.endswith(".tbi"):
        return "tbi"
    if lower.endswith(".bw"):
        return "bigwig"
    if lower.endswith((".fna", ".fa", ".fasta")):
        return "fasta"
    if lower.endswith((".gff3", ".gff", ".gff3.gz")):
        return "gff3"
    return ""


def _normalize_bundled_asset_uri(uri: str) -> str:
    if "://" in uri or uri.startswith(("/", "data:")) or "?" in uri or "#" in uri:
        raise StageError(f"Expected a local JBrowse bundle URI, found {uri!r}")
    normalized = uri.replace("\\", "/")
    if normalized.startswith("../assets/"):
        normalized = normalized[3:]
    elif normalized.startswith("./assets/"):
        normalized = normalized[2:]
    parts = list(PurePosixPath(normalized).parts)
    if not parts or parts[0] != "assets" or ".." in parts:
        raise StageError(f"JBrowse asset URI is outside its assets directory: {uri!r}")
    return PurePosixPath(*parts).as_posix()


def rewrite_jbrowse_asset_uris(
    config: dict[str, object],
    package_root: Path,
    hf_data_base_url: str,
    asset_paths: dict[str, dict[str, str]],
) -> None:
    """Point every remaining release asset URI at its fixed Hugging Face object."""
    package_root = package_root.resolve()

    def visit(value: object) -> None:
        if isinstance(value, dict):
            uri = value.get("uri")
            if isinstance(uri, str):
                bundle_rel = _normalize_bundled_asset_uri(uri)
                entry = asset_paths.get(bundle_rel)
                if entry is None:
                    raise StageError(f"No approved HF object maps JBrowse URI {uri!r}")
                source_path = (package_root / PurePosixPath(bundle_rel)).resolve()
                try:
                    source_path.relative_to(package_root)
                except ValueError as exc:
                    raise StageError(f"JBrowse asset escapes package root: {uri}") from exc
                if not source_path.is_file():
                    raise StageError(f"JBrowse release is missing configured asset: {source_path}")
                if sha256_file(source_path) != entry["sha256"]:
                    raise StageError(f"JBrowse asset SHA-256 differs from the approved inventory: {bundle_rel}")
                value["uri"] = f"{hf_data_base_url}/{quote(entry['object_path'], safe='/')}"
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(config)


def _all_config_uris(value: object) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        if isinstance(value.get("uri"), str):
            found.append(str(value["uri"]))
        for child in value.values():
            found.extend(_all_config_uris(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_all_config_uris(child))
    return found


def apply_v03_jbrowse_configs(
    package_root: Path,
    downloads_root: Path,
    mode: str,
    hf_data_base_url: str,
    studies_path: Path | None = None,
) -> dict[str, object]:
    """Overlay v0.3 tracks and pin every browser data URI to the HF release."""
    if mode not in {"pages", "worker"}:
        raise StageError(f"Unknown JBrowse config build mode: {mode}")
    hf_data_base_url, _revision = normalize_hf_data_base_url(hf_data_base_url)
    catalog_path = package_root / "catalog.json"
    catalog = _read_config(catalog_path)
    asset_paths = load_public_jbrowse_asset_paths(bundle_catalog=catalog)
    source_catalog = catalog.get("sources", {})
    assembly_catalog = catalog.get("assemblies", {})
    if not isinstance(source_catalog, dict) or not isinstance(assembly_catalog, dict):
        raise StageError("JBrowse release catalog must contain source and assembly mappings")

    sources = load_sources(studies_path) if studies_path is not None else load_sources()
    source_by_id = {str(source["source_id"]): source for source in sources}
    generated_ids: dict[str, str] = {}

    def source_config_path(source_id: str) -> Path:
        source_entry = source_catalog.get(source_id)
        if not isinstance(source_entry, dict) or not source_entry.get("config"):
            raise StageError(f"JBrowse release catalog has no config for {source_id}")
        config_path = (package_root / str(source_entry["config"])).resolve()
        try:
            config_path.relative_to(package_root.resolve())
        except ValueError as exc:
            raise StageError(f"JBrowse config escapes package root: {config_path}") from exc
        if not config_path.is_file():
            raise StageError(f"JBrowse release is missing config for {source_id}: {config_path}")
        return config_path

    for source_id, source in source_by_id.items():
        if not source["has_jbrowse"] or not source["record_count"]:
            continue
        source_path = source_config_path(source_id)
        config = _read_config(source_path)
        _remove_legacy_endpoint_tracks(config)
        _remove_nonredistributable_signal_tracks(config)
        _remove_unpublished_text_search_indices(config, asset_paths)
        rewrite_jbrowse_asset_uris(config, package_root, hf_data_base_url, asset_paths)
        assemblies = config.get("assemblies", [])
        if not assemblies or not isinstance(assemblies[0], dict) or not assemblies[0].get("name"):
            raise StageError(f"{source_id}: config has no assembly name")
        gff3_uri = f"{hf_data_base_url}/records/{quote(source_id, safe='')}/endpoints.gff3"
        track = _endpoint_track(source, str(assemblies[0]["name"]), gff3_uri)
        _add_track_to_config(config, track)
        source_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        generated_ids[source_id] = str(track["trackId"])
        source_catalog[source_id]["v0_3_endpoint_track_id"] = track["trackId"]
        source_catalog[source_id]["v0_3_endpoint_count"] = source["record_count"]
        source_catalog[source_id]["release_version"] = RELEASE_VERSION
        source_catalog[source_id]["track_count"] = len(config["tracks"])

    for assembly, entry in assembly_catalog.items():
        if not isinstance(entry, dict) or not entry.get("config"):
            continue
        source_ids = [source_id for source_id in entry.get("source_ids", []) if source_id in generated_ids]
        if not source_ids:
            continue
        assembly_path = (package_root / str(entry["config"])).resolve()
        try:
            assembly_path.relative_to(package_root.resolve())
        except ValueError as exc:
            raise StageError(f"JBrowse assembly config escapes package root: {assembly_path}") from exc
        if not assembly_path.is_file():
            raise StageError(f"JBrowse release is missing combined config for {assembly}: {assembly_path}")
        config = _read_config(assembly_path)
        _remove_legacy_endpoint_tracks(config)
        _remove_nonredistributable_signal_tracks(config)
        _remove_unpublished_text_search_indices(config, asset_paths)
        rewrite_jbrowse_asset_uris(config, package_root, hf_data_base_url, asset_paths)
        assemblies = config.get("assemblies", [])
        if not assemblies or not isinstance(assemblies[0], dict) or not assemblies[0].get("name"):
            raise StageError(f"{assembly}: combined config has no assembly name")
        for source_id in source_ids:
            source = source_by_id[source_id]
            gff3_uri = f"{hf_data_base_url}/records/{quote(source_id, safe='')}/endpoints.gff3"
            _add_track_to_config(config, _endpoint_track(source, str(assemblies[0]["name"]), gff3_uri))
        assembly_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        entry["v0_3_endpoint_track_ids"] = [generated_ids[source_id] for source_id in source_ids]
        entry["release_version"] = RELEASE_VERSION
        entry["endpoint_track_ids"] = entry["v0_3_endpoint_track_ids"]

    catalog["release_version"] = RELEASE_VERSION
    catalog.pop("endpoint_gff3", None)
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    validate_v03_jbrowse_configs(
        package_root,
        downloads_root,
        source_by_id,
        generated_ids,
        source_catalog,
        assembly_catalog,
        hf_data_base_url,
    )
    return catalog


def validate_v03_jbrowse_configs(
    package_root: Path,
    downloads_root: Path,
    source_by_id: dict[str, dict[str, object]],
    generated_ids: dict[str, str],
    source_catalog: dict[str, object],
    assembly_catalog: dict[str, object],
    hf_data_base_url: str,
) -> None:
    hf_data_base_url, _revision = normalize_hf_data_base_url(hf_data_base_url)
    for source_id, track_id in generated_ids.items():
        path = package_root / str(source_catalog[source_id]["config"])
        config = _read_config(path)
        tracks = [item for item in config.get("tracks", []) if item.get("trackId") == track_id]
        if len(tracks) != 1:
            raise StageError(f"{source_id}: generated endpoint track is absent or duplicated")
        track = tracks[0]
        uri = track.get("adapter", {}).get("gffLocation", {}).get("uri")
        expected = f"{hf_data_base_url}/records/{quote(source_id, safe='')}/endpoints.gff3"
        if uri != expected:
            raise StageError(f"{source_id}: generated endpoint URI is {uri!r}, expected {expected!r}")
        gff3 = downloads_root / "records" / source_id / "endpoints.gff3"
        if not gff3.is_file():
            raise StageError(f"{source_id}: generated endpoint GFF3 is missing: {gff3}")
        with gff3.open(encoding="utf-8") as handle:
            count = sum(1 for line in handle if line and not line.startswith("#"))
        if count != int(source_by_id[source_id]["record_count"]):
            raise StageError(f"{source_id}: JBrowse endpoint GFF3 count does not match v0.3.0 sources metadata")
        for configured_uri in _all_config_uris(config):
            if not configured_uri.startswith(f"{hf_data_base_url}/"):
                raise StageError(f"{source_id}: JBrowse data URI is not pinned to the HF release: {configured_uri}")
            if configured_uri.endswith("/endpoints.gff3"):
                expected_source_prefix = f"{hf_data_base_url}/records/{quote(source_id, safe='')}/"
                if not configured_uri.startswith(expected_source_prefix):
                    raise StageError(f"{source_id}: endpoint track points at another source: {configured_uri}")
        default_tracks = config.get("defaultSession", {}).get("views", [{}])[0].get("tracks", [])
        if not any(item.get("configuration") == track_id for item in default_tracks):
            raise StageError(f"{source_id}: generated endpoint track is not in the default session")

    for assembly, entry in assembly_catalog.items():
        if not isinstance(entry, dict) or not entry.get("v0_3_endpoint_track_ids"):
            continue
        config = _read_config(package_root / str(entry["config"]))
        actual = {track.get("trackId") for track in config.get("tracks", [])}
        missing = set(entry["v0_3_endpoint_track_ids"]) - actual
        if missing:
            raise StageError(f"{assembly}: combined config is missing v0.3.0 endpoint tracks {sorted(missing)}")
        for configured_uri in _all_config_uris(config):
            if not configured_uri.startswith(f"{hf_data_base_url}/"):
                raise StageError(f"{assembly}: JBrowse data URI is not pinned to the HF release: {configured_uri}")


def refresh_checksums(package_root: Path) -> None:
    run_validator("refresh_jbrowse_checksums.py", package_root)


def copy_v03_download_tables(destination: Path) -> None:
    release_root = REPO_ROOT / "data" / "public" / RELEASE_VERSION
    names = (
        "release.json",
        "SHA256SUMS.txt",
    )
    for name in names:
        source = release_root / name
        if not source.is_file():
            raise StageError(f"v0.3.0 release is missing required download file: {source}")
        shutil.copyfile(source, destination / name)

    study_source = release_root / "studies"
    if not study_source.is_dir():
        raise StageError(f"v0.3.0 release is missing study packages: {study_source}")
    studies_destination = destination / "studies"
    if studies_destination.exists():
        raise StageError(f"Refusing to overwrite staged study packages: {studies_destination}")
    shutil.copytree(study_source, studies_destination, copy_function=shutil.copyfile)

    for study_dir in sorted(studies_destination.glob("PMID_*")):
        expected = {"endpoints.gff3.gz", "metadata.json", "metadata.tsv"}
        actual = {path.name for path in study_dir.iterdir() if path.is_file()}
        if not expected.issubset(actual):
            missing = sorted(expected - actual)
            raise StageError(f"{study_dir.name}: study package is missing required files {missing}")


def normalize_v04_data_base_url(value: str) -> tuple[str, str]:
    """Require an immutable Hugging Face commit URL for a published v0.4.0 build."""
    base = value.strip().rstrip("/")
    match = HF_V04_DATA_BASE_PATTERN.fullmatch(base)
    if not match:
        raise StageError(
            "v0.4.0 published assets must use https://huggingface.co/datasets/liurulong/terminator/"
            "resolve/<40-character-commit>/v0.4.0"
        )
    return base, match.group(1)


def _safe_logical_asset_path(raw: str) -> str:
    normalized = raw.strip().replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ":" in normalized or ".." in path.parts:
        raise StageError(f"Unsafe browser asset logical path: {raw!r}")
    return path.as_posix()


def _asset_url_revision(url: str) -> tuple[str, str, str] | None:
    match = re.fullmatch(
        r"https://huggingface\.co/datasets/liurulong/terminator/resolve/([0-9a-f]{40})/(v0\.3\.0|v0\.4\.0)/(.+)",
        url,
    )
    if not match:
        return None
    return match.group(1), match.group(2), match.group(3)


def _resolve_local_v04_asset(logical_path: str, release_root: Path, browser_objects_root: Path) -> Path:
    candidates = (
        release_root / Path(*PurePosixPath(logical_path).parts),
        browser_objects_root / "v0.4.0" / Path(*PurePosixPath(logical_path).parts),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise StageError(f"Local v0.4.0 browser asset is missing: {logical_path}")


def load_v04_browser_assets(
    manifest_path: Path,
    release_root: Path,
    browser_objects_root: Path,
    hf_v04_data_base_url: str | None = None,
) -> tuple[dict[str, dict[str, object]], str | None]:
    """Load the canonical allowlist and verify its bytes, revisions and URLs."""
    try:
        with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            fields = reader.fieldnames or []
            missing = sorted(set(V04_BROWSER_ASSET_FIELDS) - set(fields))
            if missing:
                raise StageError(f"Browser asset manifest is missing columns: {missing}")
            rows = list(reader)
    except OSError as exc:
        raise StageError(f"Could not read browser asset manifest: {manifest_path}") from exc

    _release, release_files = read_v04_release(release_root)
    assets: dict[str, dict[str, object]] = {}
    remote_v04_bases: set[str] = set()
    versions_seen: set[str] = set()
    for raw in rows:
        logical_path = _safe_logical_asset_path(str(raw.get("logical_path", "")))
        if logical_path in assets:
            raise StageError(f"Duplicate browser asset logical path: {logical_path}")
        url = str(raw.get("url", "")).strip()
        sha256 = str(raw.get("sha256", "")).strip().lower()
        asset_kind = str(raw.get("asset_kind", "")).strip()
        revision = str(raw.get("revision", "")).strip()
        try:
            byte_size = int(str(raw.get("byte_size", "")))
        except ValueError as exc:
            raise StageError(f"Invalid byte_size for browser asset {logical_path}") from exc
        if byte_size < 0 or not re.fullmatch(r"[0-9a-f]{64}", sha256) or not asset_kind:
            raise StageError(f"Invalid size, checksum, or asset kind for {logical_path}")

        remote = _asset_url_revision(url)
        if remote:
            remote_revision, version, remote_path = remote
            if remote_path != logical_path or revision != remote_revision:
                raise StageError(f"Browser asset URL/revision does not match its logical path: {logical_path}")
            if version == "v0.3.0" and remote_revision != V03_SHARED_REVISION:
                raise StageError(f"Shared v0.3.0 asset is not pinned to the approved commit: {logical_path}")
            if version == "v0.4.0":
                remote_v04_bases.add(f"{HF_DATASET_ROOT}/{remote_revision}/v0.4.0")
            versions_seen.add(version)
        else:
            if not url.startswith("downloads/v0.4.0/") or url != f"downloads/v0.4.0/{logical_path}":
                raise StageError(f"Browser asset URL is outside the local or pinned allowlist: {url!r}")
            if revision not in {"", "local"}:
                raise StageError(f"A local v0.4.0 asset must not claim a Hugging Face revision: {logical_path}")
            versions_seen.add("local-v0.4.0")

        if logical_path in release_files:
            declared = release_files[logical_path]
            if int(declared["byte_size"]) != byte_size or str(declared["sha256"]).lower() != sha256:
                raise StageError(f"Browser allowlist differs from release.json for {logical_path}")
            release_version = "v0.4.0"
        else:
            release_version = "v0.4.0" if remote and remote[1] == "v0.4.0" else "v0.3.0" if remote else "v0.4.0"

        local_path: Path | None = None
        if release_version == "v0.4.0":
            try:
                local_path = _resolve_local_v04_asset(logical_path, release_root, browser_objects_root)
            except StageError:
                # Remote-only builds still need reference indexes locally to
                # create a usable initial JBrowse location. Other remote files
                # are verified by their pinned manifest entry and API proxy.
                if asset_kind in {"fasta", "fai", "gff3", "tbi"} and logical_path.startswith("browser/"):
                    raise
                if logical_path.startswith("tracks/"):
                    raise
                if url.startswith("downloads/v0.4.0/"):
                    raise
            if local_path is not None:
                if local_path.stat().st_size != byte_size or sha256_file(local_path) != sha256:
                    raise StageError(f"Local v0.4.0 asset checksum does not match allowlist: {logical_path}")
        assets[logical_path] = {
            "url": url,
            "byte_size": byte_size,
            "sha256": sha256,
            "revision": revision,
            "asset_kind": asset_kind,
            "local_path": local_path,
            "version": release_version,
        }

    missing_release = sorted(set(release_files) - set(assets))
    if missing_release:
        raise StageError(f"Browser allowlist omits public v0.4.0 release files: {missing_release[:5]}")
    if len(remote_v04_bases) > 1:
        raise StageError("v0.4.0 browser assets use more than one Hugging Face revision")
    if "local-v0.4.0" in versions_seen and any(version == "v0.4.0" for version in versions_seen):
        raise StageError("v0.4.0 browser allowlist mixes local and remote assets")

    selected_base = next(iter(remote_v04_bases), None)
    if hf_v04_data_base_url:
        requested_base, requested_revision = normalize_v04_data_base_url(hf_v04_data_base_url)
        if selected_base and selected_base != requested_base:
            raise StageError("Browser asset manifest does not match --hf-v04-data-base-url")
        if not selected_base and "local-v0.4.0" in versions_seen:
            raise StageError("--hf-v04-data-base-url cannot be used with a local v0.4.0 allowlist")
        if selected_base and not selected_base.endswith(f"/{requested_revision}/v0.4.0"):
            raise StageError("v0.4.0 browser asset revision does not match the requested revision")
        selected_base = requested_base
    elif any(version == "v0.4.0" for version in versions_seen) and not selected_base:
        raise StageError("Remote v0.4.0 assets do not identify one pinned Hugging Face revision")

    # release.json and its checksum file are machine-readable verification
    # resources. They are allowlisted for API integrity but never linked as
    # user-facing downloads.
    for filename in ("release.json", "SHA256SUMS.txt"):
        path = release_root / filename
        if path.is_file():
            url = f"{selected_base}/{filename}" if selected_base else f"downloads/v0.4.0/{filename}"
            assets[filename] = {
                "url": url,
                "byte_size": path.stat().st_size,
                "sha256": sha256_file(path),
                "revision": selected_base.rsplit("/", 2)[-2] if selected_base else "local",
                "asset_kind": "release_manifest" if filename == "release.json" else "checksum_list",
                "local_path": path.resolve(),
                "version": "v0.4.0",
            }
    return assets, selected_base


def _v04_jbrowse_uri(asset: dict[str, object]) -> str:
    url = str(asset["url"])
    if url.startswith("downloads/v0.4.0/"):
        return f"../../{url}"
    return url


def _session_view(config: dict[str, object]) -> dict[str, object]:
    session = config.setdefault("defaultSession", {"name": "BTED genome view", "views": []})
    if not isinstance(session, dict):
        raise StageError("JBrowse defaultSession must be an object")
    views = session.setdefault("views", [])
    if not isinstance(views, list):
        raise StageError("JBrowse defaultSession views must be a list")
    if not views:
        views.append({"id": "bted_v04_genome_view", "type": "LinearGenomeView", "tracks": []})
    view = views[0]
    if not isinstance(view, dict):
        raise StageError("JBrowse defaultSession contains an invalid view")
    view_tracks = view.setdefault("tracks", [])
    if not isinstance(view_tracks, list):
        raise StageError("JBrowse defaultSession view tracks must be a list")
    return view


def _add_default_track(config: dict[str, object], track_id: str, track_type: str, display_type: str) -> None:
    view = _session_view(config)
    view_tracks = view.setdefault("tracks", [])
    if any(isinstance(item, dict) and item.get("configuration") == track_id for item in view_tracks):
        return
    view_tracks.append({
        "id": f"{track_id}-v04-view",
        "type": track_type,
        "configuration": track_id,
        "minimized": False,
        "displays": [{
            "id": f"{track_id}-v04-display",
            "type": display_type,
            "configuration": f"{track_id}-{display_type}",
            **({"showSidebar": False} if display_type == "MultiLinearWiggleDisplay" else {}),
        }],
    })


def _sanitize_v04_source_config(
    source_id: str,
    package_root: Path,
    asset_paths: dict[str, dict[str, str]],
) -> dict[str, object] | None:
    config_path = package_root / f"{source_id}.config.json"
    if not config_path.is_file():
        return None
    config = _read_config(config_path)
    return _sanitize_v04_config(config, package_root, asset_paths)


def _sanitize_v04_config(
    config: dict[str, object],
    package_root: Path,
    asset_paths: dict[str, dict[str, str]],
) -> dict[str, object]:
    _remove_legacy_endpoint_tracks(config)
    _remove_nonredistributable_signal_tracks(config)
    _remove_unpublished_text_search_indices(config, asset_paths)
    rewrite_jbrowse_asset_uris(config, package_root, V03_SHARED_BASE_URL, asset_paths)
    return config


def _is_reference_annotation(track: dict[str, object]) -> bool:
    category = track.get("category", [])
    labels = category if isinstance(category, list) else [category]
    label = " ".join([str(track.get("name", "")), *map(str, labels)]).casefold()
    return "reference annotation" in label or "gene annotation" in label


def _merge_source_configs(
    base: dict[str, object],
    additional: dict[str, object],
) -> None:
    tracks = base.setdefault("tracks", [])
    if not isinstance(tracks, list):
        raise StageError("JBrowse track collection must be a list")
    existing_ids = {str(item.get("trackId", "")) for item in tracks if isinstance(item, dict)}
    for track in additional.get("tracks", []):
        if not isinstance(track, dict) or _is_reference_annotation(track):
            continue
        track_id = str(track.get("trackId", ""))
        if not track_id or track_id in existing_ids:
            continue
        tracks.append(track)
        existing_ids.add(track_id)

    view = _session_view(base)
    view_tracks = view.setdefault("tracks", [])
    existing_configurations = {
        str(item.get("configuration", "")) for item in view_tracks if isinstance(item, dict)
    }
    other_views = additional.get("defaultSession", {}).get("views", [])
    if other_views and isinstance(other_views[0], dict):
        for view_track in other_views[0].get("tracks", []):
            if not isinstance(view_track, dict):
                continue
            configuration = str(view_track.get("configuration", ""))
            matching_track = next(
                (track for track in additional.get("tracks", [])
                 if isinstance(track, dict) and str(track.get("trackId", "")) == configuration),
                None,
            )
            if matching_track and _is_reference_annotation(matching_track):
                continue
            if configuration and configuration not in existing_configurations:
                view_tracks.append(view_track)
                existing_configurations.add(configuration)


def _assembly_ref_assets(
    assembly: str,
    asset_map: dict[str, dict[str, object]],
) -> tuple[dict[str, object], dict[str, dict[str, object]], Path | None]:
    candidates = {
        path: item for path, item in asset_map.items()
        if path.startswith((f"browser/{assembly}/", f"assemblies/{assembly}/"))
    }
    fasta = next(((path, item) for path, item in candidates.items() if item["asset_kind"] == "fasta"), None)
    fai = next(((path, item) for path, item in candidates.items() if item["asset_kind"] == "fai"), None)
    if not fasta or not fai:
        raise StageError(f"No allowlisted FASTA/FAI reference assets for {assembly}")
    fna_path, fna_asset = fasta
    fai_path, fai_asset = fai
    local_fai = fai_asset.get("local_path")
    if not isinstance(local_fai, Path) or not local_fai.is_file():
        local_fai = None
    gff3 = next(((path, item) for path, item in candidates.items() if item["asset_kind"] == "gff3"), None)
    tbi = next(((path, item) for path, item in candidates.items() if item["asset_kind"] == "tbi"), None)
    extra: dict[str, dict[str, object]] = {}
    if gff3:
        extra["gff3"] = {"path": gff3[0], **gff3[1]}
    if tbi:
        extra["tbi"] = {"path": tbi[0], **tbi[1]}
    return {
        "fasta_path": fna_path,
        "fasta": fna_asset,
        "fai_path": fai_path,
        "fai": fai_asset,
    }, extra, local_fai


def _reference_fai_file(
    assembly: str, asset_map: dict[str, dict[str, object]], package_root: Path,
    asset_paths: dict[str, dict[str, str]],
) -> Path:
    reference, _, local_fai = _assembly_ref_assets(assembly, asset_map)
    if local_fai is not None:
        return local_fai
    logical = str(reference["fai_path"])
    expected_sha = str(reference["fai"]["sha256"])
    for bundle_path, entry in sorted(asset_paths.items()):
        if entry.get("object_path") != logical:
            continue
        candidate = (package_root / bundle_path).resolve()
        if candidate.is_file() and sha256_file(candidate) == expected_sha:
            return candidate
    raise StageError(f"Verified reference FAI is not available locally for {assembly}: {logical}")


def _longest_fai_reference(fai_file: Path, assembly: str) -> tuple[str, int]:
    records: list[tuple[str, int]] = []
    with fai_file.open("r", encoding="utf-8") as handle:
        for line in handle:
            columns = line.rstrip("\r\n").split("\t")
            if len(columns) < 2 or not columns[0]:
                raise StageError(f"Reference FAI is malformed for {assembly}")
            try:
                length = int(columns[1])
            except ValueError as exc:
                raise StageError(f"Reference FAI has an invalid length for {assembly}") from exc
            if length < 1:
                raise StageError(f"Reference FAI has an invalid length for {assembly}")
            records.append((columns[0], length))
    if not records:
        raise StageError(f"Reference FAI has no sequences for {assembly}")
    return sorted(records, key=lambda row: (-row[1], row[0]))[0]


def _new_v04_assembly_config(
    assembly: str,
    species: str,
    asset_map: dict[str, dict[str, object]],
) -> dict[str, object]:
    reference, annotation, fai_file = _assembly_ref_assets(assembly, asset_map)
    if fai_file is None:
        raise StageError(f"Reference FAI is not available locally for {assembly}")
    ref_name, ref_length = _longest_fai_reference(fai_file, assembly)
    assembly_name = re.sub(r"[^A-Za-z0-9_]", "_", f"BTED_{assembly}")
    reference_track = {
        "type": "ReferenceSequenceTrack",
        "trackId": f"bted_{assembly_name}_reference",
        "adapter": {
            "type": "IndexedFastaAdapter",
            "fastaLocation": {"uri": _v04_jbrowse_uri(reference["fasta"]), "locationType": "UriLocation"},
            "faiLocation": {"uri": _v04_jbrowse_uri(reference["fai"]), "locationType": "UriLocation"},
        },
    }
    config: dict[str, object] = {
        "assemblies": [{
            "name": assembly_name,
            "displayName": f"{species} · {assembly}" if species else assembly,
            "sequence": reference_track,
        }],
        "configuration": {},
        "connections": [],
        "defaultSession": {
            "name": f"BTED · {assembly}",
            "views": [{
                "id": "bted_v04_genome_view",
                "type": "LinearGenomeView",
                "offsetPx": 0,
                "bpPerPx": 5,
                "displayedRegions": [{
                    "refName": ref_name,
                    "start": 0,
                    "end": min(ref_length, 10000),
                    "reversed": False,
                    "assemblyName": assembly_name,
                }],
                "tracks": [],
            }],
        },
        "tracks": [],
    }
    if "gff3" in annotation:
        ann = annotation["gff3"]
        if "tbi" in annotation:
            index = annotation["tbi"]
            gene_track = {
                "type": "FeatureTrack",
                "trackId": f"bted_{assembly_name}_reference_annotation",
                "name": "Reference gene annotation",
                "adapter": {
                    "type": "Gff3TabixAdapter",
                    "gffGzLocation": {"uri": _v04_jbrowse_uri(ann), "locationType": "UriLocation"},
                    "index": {"location": {"uri": _v04_jbrowse_uri(index), "locationType": "UriLocation"}, "indexType": "TBI"},
                },
                "category": ["Reference annotation"],
                "assemblyNames": [assembly_name],
            }
        else:
            gene_track = {
                "type": "FeatureTrack",
                "trackId": f"bted_{assembly_name}_reference_annotation",
                "name": "Reference gene annotation",
                "adapter": {
                    "type": "Gff3Adapter",
                    "gffLocation": {"uri": _v04_jbrowse_uri(ann), "locationType": "UriLocation"},
                },
                "category": ["Reference annotation"],
                "assemblyNames": [assembly_name],
            }
        config["tracks"].append(gene_track)
        _add_default_track(config, str(gene_track["trackId"]), "FeatureTrack", "LinearBasicDisplay")
    return config


def _endpoint_track_v04(
    source: dict[str, str],
    assembly_name: str,
    asset: dict[str, object],
    citation: dict[str, str],
    all_assets: dict[str, dict[str, object]],
) -> dict[str, object]:
    source_id = source["source_id"]
    track_id = f"bted_v04_{source_id.lower()}_endpoints"
    evidence = str(source.get("evidence_class", ""))
    title = f"{source_id} · PMID {source['pmid']} · endpoint records"
    description = (
        f"Study-level endpoint records from PMID {source['pmid']}. "
        f"Evidence class: {evidence or 'not specified'}. "
        "Endpoint records are shown separately from experimental signal tracks."
    )
    evidence_text = (
        "Paper-reported transcript 3′ end; this is not proof of terminator function."
        if evidence == "author_called_endpoint" else
        "Literature-curated 3′ end; BTED did not re-call this position from reads."
    )
    accession = str(source.get("raw_data_accessions", "")).split(";", 1)[0].strip()
    raw_data_url = (
        f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={quote(accession)}"
        if accession.startswith("GSE") else
        f"https://www.ncbi.nlm.nih.gov/sra/?term={quote(accession)}"
        if accession.startswith(("SRP", "SRR")) else
        f"https://www.ebi.ac.uk/ena/browser/view/{quote(accession)}"
        if accession.startswith("PRJEB") else ""
    )
    genome = source["assembly"]
    study_gff3 = (PurePosixPath("genomes") / genome / source["study_gff3"]).as_posix()
    source_track = asset.get("local_path")
    reference_name = ""
    if isinstance(source_track, Path) and source_track.is_file():
        with source_track.open(encoding="utf-8") as handle:
            reference_name = next((line.split("\t", 1)[0] for line in handle if line.strip() and not line.startswith("#")), "")
    study_asset = all_assets.get(study_gff3)
    if not study_asset:
        raise StageError(f"Study GFF3 download is missing from asset allowlist: {study_gff3}")
    about = {
        "kind": "endpoint", "title": citation["title"], "authors": citation["authors"],
        "journal": citation["journal"], "year": citation["year"],
        "pmid": citation["pmid"], "pubmed_url": citation["pubmed_url"],
        "doi_url": f"https://doi.org/{quote(citation['doi'], safe='/')}" if citation["doi"] else "",
        "source_id": source_id, "assay": source["assay"],
        "record_count": source["record_count_number"], "evidence": evidence_text,
        "explanation": "GFF3 rows are independent by source; same-coordinate studies are not merged.",
        "assembly": genome, "reference_name": reference_name,
        "limitations": source["known_limitations"],
        "raw_data_accessions": source["raw_data_accessions"], "raw_data_url": raw_data_url,
        "gff3_url": _v04_jbrowse_uri(study_asset),
    }
    return {
        "type": "FeatureTrack",
        "trackId": track_id,
        "name": title,
        "description": description,
        "adapter": {
            "type": "Gff3Adapter",
            "gffLocation": {"uri": _v04_jbrowse_uri(asset), "locationType": "UriLocation"},
        },
        "displays": [{
            "type": "LinearBasicDisplay",
            "displayId": f"{track_id}-LinearBasicDisplay",
            "renderer": {
                "type": "SvgFeatureRenderer",
                "color1": "jexl:btedStrandColor(feature)",
                "color2": "jexl:btedStrandColor(feature)",
                "height": 14,
            },
            "showLabels": False,
            "height": 64,
        }],
        "category": ["BTED v0.4.0", "Endpoint features", str(source["pmid"])],
        "assemblyNames": [assembly_name],
        "metadata": {
            "release_version": "v0.4.0",
            "source_id": source_id,
            "pmid": str(source["pmid"]),
            "record_count": int(source["record_count_number"]),
            "evidence_class": evidence,
            "btedAbout": about,
            "btedDownloads": [{
                "kind": "endpoint", "label": "3′ end GFF3", "url": _v04_jbrowse_uri(asset),
                "filename": f"{source_id}.endpoints.gff3", "source_id": source_id,
            }],
        },
    }


def _default_signal_tracks(
    config: dict[str, object], sources: dict[str, dict[str, str]],
    citations: dict[str, dict[str, str]],
) -> int:
    tracks = config.get("tracks", [])
    if not isinstance(tracks, list):
        raise StageError("JBrowse tracks must be a list")
    by_source: dict[str, dict[str, dict[str, object]]] = {}
    old_ids: set[str] = set()
    for track in tracks:
        if not isinstance(track, dict) or track.get("type") != "QuantitativeTrack":
            continue
        uris = _all_config_uris(track)
        if not uris or any("signed-log10-ui-v4" in uri for uri in uris):
            continue
        if not any(uri.lower().endswith((".bw", ".bigwig")) for uri in uris):
            continue
        track_id = str(track.get("trackId", ""))
        if not track_id:
            continue
        strand = "plus" if track_id.endswith((".forward", "_forward")) else "minus" if track_id.endswith((".reverse", "_reverse")) else ""
        if not strand:
            continue
        source_match = next((source_id for source_id in sources if any(f"/tracks/{source_id}/" in uri for uri in uris)), "")
        if not source_match:
            continue
        if strand in by_source.setdefault(source_match, {}):
            raise StageError(f"Duplicate {strand} experimental signal for {source_match}")
        by_source[source_match][strand] = track
        old_ids.add(track_id)

    if not by_source:
        return 0
    view = _session_view(config)
    view["tracks"] = [item for item in view["tracks"] if not isinstance(item, dict) or item.get("configuration") not in old_ids]
    config["tracks"] = [item for item in tracks if not isinstance(item, dict) or item.get("trackId") not in old_ids]
    for source_match, pair in by_source.items():
        if set(pair) != {"plus", "minus"}:
            raise StageError(f"Experimental signal needs both strands for {source_match}")
        source = sources[source_match]
        citation = citations.get(source.get("pmid", ""), {})
        track_id = f"bted_v04_{source_match.lower()}_mirrored_signal"
        subadapters = []
        for strand, color in (("plus", PLUS_STRAND_COLOR), ("minus", MINUS_STRAND_COLOR)):
            original = pair[strand]
            uri = _all_config_uris(original)
            if len(uri) != 1:
                raise StageError(f"Expected one {strand} BigWig URI for {source_match}")
            subadapters.append({
                "type": "BigWigAdapter", "source": strand, "name": f"{'+' if strand == 'plus' else '−'} strand",
                "color": color, "bigWigLocation": {"uri": uri[0], "locationType": "UriLocation"},
            })
        merged = {
            "type": "MultiQuantitativeTrack", "trackId": track_id,
            "name": f"{source_match} · experimental signal (+ / −)",
            "description": "Measured BigWig signal mirrored around zero for display; raw values are unchanged.",
            "adapter": {"type": "MultiWiggleAdapter", "subadapters": subadapters},
            "category": ["Observed experimental signal", source_match],
            "assemblyNames": pair["plus"].get("assemblyNames", []),
            "metadata": {
                "evidence_class": "observed_signal", "release_version": "v0.4.0",
                "btedMirroredSignal": True,
                "signal_display": "Mirrored for viewing; raw BigWig values are unchanged",
                "btedDownloads": [{
                    "kind": "bigwig", "label": f"{'+' if item['source'] == 'plus' else '−'} strand BigWig",
                    "url": item["bigWigLocation"]["uri"],
                    "filename": f"{source_match}.signal.{'forward' if item['source'] == 'plus' else 'reverse'}.bw",
                } for item in subadapters],
                "btedAbout": {
                    "kind": "signal", "source_id": source_match, "strand": "+ / −",
                    "title": citation.get("title", ""), "authors": citation.get("authors", ""),
                    "journal": citation.get("journal", ""), "year": citation.get("year", ""),
                    "pmid": citation.get("pmid", ""), "pubmed_url": citation.get("pubmed_url", ""),
                    "doi_url": f"https://doi.org/{quote(citation['doi'], safe='/')}" if citation.get("doi") else "",
                    "assay": source.get("assay", ""), "assembly": source.get("assembly", ""),
                    "raw_data_accessions": source.get("raw_data_accessions", ""),
                    "limitations": source.get("known_limitations", ""),
                    "explanation": "Measured signal from the study. The graph mirrors + and − around zero; the original BigWig values are unchanged. This track does not mark called 3′ ends.",
                },
            },
            "displays": [{
                "type": "MultiLinearWiggleDisplay", "displayId": f"{track_id}-MultiLinearWiggleDisplay",
                "defaultRendering": "xyplot", "height": 180,
            }],
        }
        config["tracks"].append(merged)
        _add_default_track(config, track_id, "MultiQuantitativeTrack", "MultiLinearWiggleDisplay")
    return len(by_source) * 2


def build_v04_jbrowse_configs(
    package_root: Path,
    release_root: Path,
    assets: dict[str, dict[str, object]],
    asset_paths: dict[str, dict[str, str]],
) -> tuple[dict[str, str], dict[str, str], dict[str, object]]:
    """Create one combined genome config with independent per-source GFF3 tracks."""
    release, release_files = read_v04_release(release_root)
    genomes = release.get("genomes", [])
    if not isinstance(genomes, list):
        raise StageError("v0.4.0 release.json genomes must be a list")
    browser_configs: dict[str, str] = {}
    track_ids: dict[str, str] = {}
    catalog: dict[str, object] = {"release_version": "v0.4.0", "assemblies": {}}
    citations = load_study_citations()

    for genome in genomes:
        if not isinstance(genome, dict):
            continue
        assembly = str(genome.get("assembly", ""))
        metadata_path = str(genome.get("metadata_path", ""))
        metadata_file = release_root.joinpath(*PurePosixPath(metadata_path).parts)
        try:
            import build_v0_4_site
            metadata_rows = build_v0_4_site.read_tsv(metadata_file, build_v0_4_site.REQUIRED_METADATA_COLUMNS)
        except SiteBuildError as exc:
            raise StageError(str(exc)) from exc
        published = [
            {**row, "record_count_number": int(row["record_count"])}
            for row in metadata_rows
            if v04_site.is_published_status(row.get("release_status")) and int(row["record_count"]) > 0
        ]
        if not published:
            continue
        species = next((row.get("species", "") for row in published if row.get("species")), "")

        combined_path = package_root / "assemblies" / f"{assembly}.config.json"
        config: dict[str, object] | None = (
            _sanitize_v04_config(_read_config(combined_path), package_root, asset_paths)
            if combined_path.is_file() else None
        )
        source_ids: list[str] = []
        for source in published:
            source_id = str(source["source_id"])
            source_ids.append(source_id)
            source_config = _sanitize_v04_source_config(source_id, package_root, asset_paths)
            if source_config is None:
                continue
            if config is None:
                config = source_config
            elif not combined_path.is_file():
                _merge_source_configs(config, source_config)

        if config is None:
            config = _new_v04_assembly_config(assembly, species, assets)
        assemblies = config.get("assemblies", [])
        if not isinstance(assemblies, list) or not assemblies or not isinstance(assemblies[0], dict):
            raise StageError(f"JBrowse config has no assembly for {assembly}")
        assembly_name = str(assemblies[0].get("name", ""))
        if not assembly_name:
            raise StageError(f"JBrowse config has an unnamed assembly for {assembly}")

        for source in published:
            source_id = str(source["source_id"])
            logical = f"tracks/{source_id}/endpoints.gff3"
            asset = assets.get(logical)
            if not asset:
                raise StageError(f"Source-specific endpoint browser asset is not allowlisted: {logical}")
            if asset.get("asset_kind") != "gff3":
                raise StageError(f"Source endpoint browser asset is not GFF3: {logical}")
            local_track = asset.get("local_path")
            if not isinstance(local_track, Path) or not local_track.is_file():
                raise StageError(f"Source endpoint browser file is missing locally: {logical}")
            with local_track.open("r", encoding="utf-8") as track_handle:
                actual_count = sum(1 for line in track_handle if line.strip() and not line.startswith("#"))
            if actual_count != source["record_count_number"]:
                raise StageError(
                    f"{source_id}: browser GFF3 has {actual_count} features, expected {source['record_count_number']}"
                )
            citation = citations.get(source["pmid"])
            if citation is None:
                raise StageError(f"No verified PubMed citation for PMID {source['pmid']}")
            track = _endpoint_track_v04(source, assembly_name, asset, citation, assets)
            tracks = config.setdefault("tracks", [])
            if not isinstance(tracks, list):
                raise StageError("JBrowse config tracks must be a list")
            track_id = str(track["trackId"])
            existing = next((item for item in tracks if isinstance(item, dict) and item.get("trackId") == track_id), None)
            if existing is None:
                tracks.append(track)
            elif existing != track:
                raise StageError(f"Conflicting endpoint track configuration: {track_id}")
            _add_default_track(config, track_id, "FeatureTrack", "LinearBasicDisplay")
            track_ids[source_id] = track_id

        source_lookup = {row["source_id"]: row for row in published}
        _default_signal_tracks(config, source_lookup, citations)
        fai_file = _reference_fai_file(assembly, assets, package_root, asset_paths)
        reference_name, reference_length = _longest_fai_reference(fai_file, assembly)
        first_site: int | None = None
        for source in published:
            local_track = assets[f"tracks/{source['source_id']}/endpoints.gff3"]["local_path"]
            with local_track.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line or line.startswith("#"):
                        continue
                    columns = line.split("\t", 5)
                    if columns[0] == reference_name:
                        position = int(columns[3])
                        first_site = position if first_site is None else min(first_site, position)
        start = max(0, first_site - 501) if first_site is not None else 0
        end = min(reference_length, start + (1000 if first_site is not None else 10000))
        bp_per_px = max(0.001, (end - start) / 1000)
        session = config["defaultSession"]
        session["name"] = f"BTED · {assembly}"
        view = _session_view(config)
        view["name"] = species or assembly
        view["displayedRegions"] = [{
            "refName": reference_name, "start": 0, "end": reference_length,
            "reversed": False, "assemblyName": assembly_name,
        }]
        view["bpPerPx"] = bp_per_px
        view["offsetPx"] = start / bp_per_px
        for track in config.get("tracks", []):
            if not isinstance(track, dict) or not _is_reference_annotation(track):
                continue
            track_id = str(track["trackId"])
            track["displays"] = [{
                "type": "LinearBasicDisplay",
                "displayId": f"{track_id}-LinearBasicDisplay",
                "height": 130,
                "renderer": {
                    "type": "SvgFeatureRenderer",
                    "color1": "jexl:btedStrandColor(feature)",
                    "color2": "jexl:btedStrandColor(feature)",
                },
            }]
            uris = _all_config_uris(track)
            annotation_asset = next((item for item in assets.values() if item.get("url") in uris and item.get("asset_kind") == "gff3"), None)
            annotation_hash = str(annotation_asset.get("sha256", "")) if annotation_asset else ""
            track["metadata"] = {
                **(track.get("metadata", {}) if isinstance(track.get("metadata"), dict) else {}),
                "btedDownloads": [{
                    "kind": "reference", "label": "Reference annotation GFF3",
                    "url": str(annotation_asset["url"]),
                    "filename": f"{assembly}.genes.gff3.gz" if str(annotation_asset["url"]).endswith(".gz") else f"{assembly}.genes.gff3",
                }] if annotation_asset else [],
                "btedAbout": {
                    "kind": "reference", "assembly": assembly,
                    "reference": f"{species} · {assembly}", "reference_name": reference_name,
                    "annotation_version": f"GFF3 SHA-256 {annotation_hash[:16]}" if annotation_hash else "",
                    "reference_url": f"https://www.ncbi.nlm.nih.gov/datasets/genome/{quote(assembly)}/",
                    "explanation": "NCBI-derived gene annotation for the displayed reference assembly.",
                },
            }
        config_file = package_root / "assemblies" / f"{assembly}.config.json"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        relative_config = f"assemblies/{assembly}.config.json"
        browser_configs[assembly] = relative_config
        catalog["assemblies"][assembly] = {
            "assembly": assembly,
            "species": species,
            "config": relative_config,
            "source_ids": source_ids,
            "endpoint_track_ids": [track_ids[source_id] for source_id in source_ids],
        }

    (package_root / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return browser_configs, track_ids, catalog


def write_data_release_json(destination: Path, assets: dict[str, dict[str, object]], v04_revision: str | None) -> None:
    payload_assets: dict[str, dict[str, object]] = {}
    for logical_path, asset in sorted(assets.items()):
        payload_assets[logical_path] = {
            "url": asset["url"],
            "byte_size": int(asset["byte_size"]),
            "sha256": asset["sha256"],
            "revision": asset["revision"],
            "asset_kind": asset["asset_kind"],
        }
    payload = {
        "releaseVersion": "v0.4.0",
        "sharedAssets": {"releaseVersion": "v0.3.0", "revision": V03_SHARED_REVISION},
        "releaseRevision": v04_revision,
        "assets": payload_assets,
    }
    path = destination / "assets" / "data-release.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def copy_v04_local_assets(
    destination: Path,
    assets: dict[str, dict[str, object]],
) -> None:
    root = destination / "downloads" / "v0.4.0"
    for logical_path, asset in assets.items():
        if asset.get("version") != "v0.4.0" or not str(asset.get("url", "")).startswith("downloads/v0.4.0/"):
            continue
        source = asset.get("local_path")
        if not isinstance(source, Path) or not source.is_file():
            raise StageError(f"Local v0.4.0 allowlisted asset is missing: {logical_path}")
        relative = PurePosixPath(logical_path)
        target = root.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def validate_v04_jbrowse_configs(
    package_root: Path,
    assets: dict[str, dict[str, object]],
    catalog: dict[str, object],
    expected_endpoint_count: int,
) -> None:
    allowed_uris = {_v04_jbrowse_uri(asset) for asset in assets.values()}
    endpoint_count = 0
    signal_track_count = 0
    assembly_catalog = catalog.get("assemblies", {})
    if not isinstance(assembly_catalog, dict):
        raise StageError("Generated v0.4.0 JBrowse catalog has no assembly mapping")
    for assembly, entry in assembly_catalog.items():
        if not isinstance(entry, dict):
            raise StageError(f"Invalid browser catalog entry for {assembly}")
        config = _read_config(package_root / str(entry["config"]))
        tracks = config.get("tracks", [])
        default_tracks = config.get("defaultSession", {}).get("views", [{}])[0].get("tracks", [])
        track_ids = {str(track.get("trackId", "")) for track in tracks if isinstance(track, dict)}
        default_ids = {str(track.get("configuration", "")) for track in default_tracks if isinstance(track, dict)}
        endpoint_tracks = [
            track for track in tracks
            if isinstance(track, dict) and track.get("type") == "FeatureTrack"
            and str(track.get("trackId", "")).startswith("bted_v04_")
        ]
        endpoint_count += len(endpoint_tracks)
        for track in endpoint_tracks:
            track_id = str(track["trackId"])
            if track_id not in default_ids:
                raise StageError(f"{assembly}: endpoint track is not shown by default: {track_id}")
            if "Endpoint features" not in track.get("category", []):
                raise StageError(f"{assembly}: endpoint track is not clearly categorized: {track_id}")

        for track in tracks:
            if not isinstance(track, dict):
                continue
            if track.get("type") == "MultiQuantitativeTrack" and track.get("metadata", {}).get("btedMirroredSignal") is True:
                subadapters = track.get("adapter", {}).get("subadapters", [])
                if len(subadapters) != 2 or {item.get("source") for item in subadapters} != {"plus", "minus"}:
                    raise StageError(f"{assembly}: mirrored signal must have one BigWig per strand")
                if any(item.get("color") != (PLUS_STRAND_COLOR if item.get("source") == "plus" else MINUS_STRAND_COLOR) for item in subadapters):
                    raise StageError(f"{assembly}: mirrored signal has the wrong strand colors")
                signal_track_count += len(subadapters)
                track_id = str(track.get("trackId", ""))
                if track_id not in default_ids:
                    raise StageError(f"{assembly}: experimental signal track is not shown by default: {track_id}")
                if "experimental signal" not in str(track.get("name", "")).casefold():
                    raise StageError(f"{assembly}: signal track is not labelled as experimental signal: {track_id}")

        for uri in _all_config_uris(config):
            if uri not in allowed_uris:
                raise StageError(f"{assembly}: JBrowse URI is not in the browser asset allowlist: {uri}")
        for identifier in default_ids:
            if identifier and identifier not in track_ids:
                raise StageError(f"{assembly}: default session points to a missing JBrowse track: {identifier}")

    if endpoint_count != expected_endpoint_count:
        raise StageError(
            f"JBrowse configs contain {endpoint_count} endpoint tracks, expected {expected_endpoint_count}"
        )
    if signal_track_count != 8:
        raise StageError(f"JBrowse configs contain {signal_track_count} raw experimental BigWig tracks, expected 8")


def assemble_v04(
    mode: str,
    output: Path,
    jbrowse_dir: Path | None,
    archive: Path | None,
    checksum_file: Path | None,
    release_root: Path,
    browser_assets_manifest: Path,
    browser_objects_root: Path,
    hf_v04_data_base_url: str | None = None,
) -> None:
    """Assemble the genome-first v0.4.0 Pages or Worker static site."""
    check_output_path(output, jbrowse_dir)
    if archive is not None:
        if checksum_file is None:
            raise StageError("--release-sha256-file is required with --release-archive")
        verify_archive_sha256(archive, checksum_file)
    elif checksum_file is not None:
        raise StageError("--release-sha256-file only applies to --release-archive")

    release_root = release_root.resolve()
    browser_assets_manifest = browser_assets_manifest.resolve()
    browser_objects_root = browser_objects_root.resolve()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_stage = _new_work_directory(output.parent, f"{output.name}.stage")
    temp_bundle: Path | None = None
    try:
        temp_bundle = _new_work_directory(output.parent, "bted-v04-jbrowse-release")
        if archive is not None:
            package_root = safe_extract_release(archive, temp_bundle)
        else:
            if jbrowse_dir is None or not jbrowse_dir.is_dir():
                raise StageError("--jbrowse-dir must point to an unpacked JBrowse release package")
            package_root = temp_bundle / PACKAGE_NAME
            shutil.copytree(jbrowse_dir.resolve(), package_root, copy_function=shutil.copyfile)

        run_validator("validate_jbrowse_release.py", package_root, "--legacy-compact-baseline")
        release, release_files = read_v04_release(release_root)
        # Keep the filtered browser GFF3 objects reproducible from the public
        # study GFF3s before the manifest or any JBrowse config is accepted.
        materialize_browser_tracks(release_root, browser_objects_root)
        assets, v04_base_url = load_v04_browser_assets(
            browser_assets_manifest,
            release_root,
            browser_objects_root,
            hf_v04_data_base_url,
        )

        bundle_catalog_path = package_root / "catalog.json"
        bundle_catalog = _read_config(bundle_catalog_path)
        asset_paths = load_public_jbrowse_asset_paths(bundle_catalog=bundle_catalog)
        for mapping in asset_paths.values():
            logical_path = str(mapping["object_path"])
            approved = assets.get(logical_path)
            expected_url = f"{V03_SHARED_BASE_URL}/{logical_path}"
            if (
                approved is None
                or approved.get("version") != "v0.3.0"
                or approved.get("url") != expected_url
                or approved.get("sha256") != mapping.get("sha256")
                or approved.get("asset_kind") != mapping.get("asset_kind")
            ):
                raise StageError(f"Shared JBrowse asset is not pinned by the v0.4.0 asset manifest: {logical_path}")

        browser_configs, track_ids, browser_catalog = build_v04_jbrowse_configs(
            package_root,
            release_root,
            assets,
            asset_paths,
        )
        # Published-source count is the expected number of source-filtered
        # endpoint tracks, including sources sharing Cascino's study GFF3.
        counts = release.get("counts", {})
        if not isinstance(counts, dict):
            raise StageError("v0.4.0 release.json counts must be an object")
        try:
            expected_endpoints = int(counts["published_source_count"])
        except (KeyError, TypeError, ValueError) as exc:
            raise StageError("v0.4.0 release.json is missing published_source_count") from exc
        if len(track_ids) != expected_endpoints:
            raise StageError(
                f"Generated {len(track_ids)} source endpoint tracks, expected {expected_endpoints} published sources"
            )
        validate_v04_jbrowse_configs(package_root, assets, browser_catalog, expected_endpoints)
        install_bted_plugin(package_root)
        for config_path in (package_root / "assemblies").glob("*.config.json"):
            config = _read_config(config_path)
            config.setdefault("configuration", {})["theme"] = {
                "palette": {
                    "primary": {"main": "#343674"},
                    "secondary": {"main": "#6660a9"},
                    "tertiary": {"main": "#eeedf9"},
                },
                "typography": {
                    "fontFamily": '"Segoe UI", -apple-system, BlinkMacSystemFont, Arial, sans-serif',
                },
            }
            config["plugins"] = [{
                "name": "BTEDTrackPlugin",
                "esmUrl": "plugins/bted-track-plugin.js",
            }]
            config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # The upstream package also contains v0.2 source configs with relative
        # BED paths. v0.4 links only to generated assembly configs; do not ship
        # the stale entry points alongside them.
        for stale in package_root.glob("*.config.json"):
            stale.unlink()
        current_configs = {
            str(entry["config"])
            for entry in browser_catalog["assemblies"].values()
        }
        for candidate in (package_root / "assemblies").glob("*.config.json"):
            if candidate.relative_to(package_root).as_posix() not in current_configs:
                candidate.unlink()
        refresh_checksums(package_root)

        copy_site_source(temp_stage)
        v04_revision = normalize_v04_data_base_url(v04_base_url)[1] if v04_base_url else None
        write_data_release_json(temp_stage, assets, v04_revision)
        if not v04_base_url:
            copy_v04_local_assets(temp_stage, assets)
        build_v04_site(temp_stage, release_root, assets, browser_configs, track_ids)

        file_count, total_bytes = copy_worker_shell(package_root, temp_stage / "jbrowse")
        run_validator("validate-site.py", temp_stage)
        if mode == "worker":
            print(f"PASS  Worker v0.4.0 shell staged: {file_count} files, {total_bytes:,} bytes")
        elif mode == "pages":
            print(f"PASS  Pages v0.4.0 site staged at {output}")
        else:
            raise StageError(f"Unknown staging mode: {mode}")
        _publish_stage(temp_stage, output)
    finally:
        if temp_stage.exists():
            shutil.rmtree(temp_stage)
        if temp_bundle is not None:
            shutil.rmtree(temp_bundle)


def validate_worker_shell(shell_root: Path) -> tuple[int, int]:
    for name in RUNTIME_FILES:
        if not (shell_root / name).is_file():
            raise StageError(f"JBrowse shell is missing its runtime file: {name}")
    static_root = shell_root / "static"
    if not static_root.is_dir() or not any(static_root.rglob("*.js")) or not any(static_root.rglob("*.css")):
        raise StageError("JBrowse shell is missing static JavaScript or CSS")

    index = shell_root / "index.html"
    parser = _LinkCollector()
    parser.feed(index.read_text(encoding="utf-8"))
    for reference in parser.references:
        if reference.startswith(("https://", "http://", "data:", "#")):
            continue
        target = reference.split("?", 1)[0].split("#", 1)[0]
        if not target:
            continue
        relative = PurePosixPath(target)
        if relative.is_absolute() or ".." in relative.parts:
            raise StageError(f"JBrowse shell has a non-portable entrypoint reference: {reference}")
        if not shell_root.joinpath(*relative.parts).is_file():
            raise StageError(f"JBrowse shell entrypoint points to a missing file: {reference}")

    manifest = json.loads((shell_root / "manifest.json").read_text(encoding="utf-8"))
    for icon in manifest.get("icons", []):
        source = icon.get("src")
        if not isinstance(source, str):
            continue
        relative = PurePosixPath(source)
        if relative.is_absolute() or ".." in relative.parts or not shell_root.joinpath(*relative.parts).is_file():
            raise StageError(f"JBrowse manifest points to a missing or unsafe file: {source}")

    files = [path for path in shell_root.rglob("*") if path.is_file()]
    if any(path.suffix == ".map" for path in files):
        raise StageError("Worker JBrowse shell must not include source maps")
    if (shell_root / "assets").exists() or any(path.name.endswith((".fna", ".fai", ".gff3", ".bed", ".bw", ".tbi")) for path in files):
        raise StageError("Worker JBrowse directory contains release data rather than the app shell only")
    return len(files), sum(path.stat().st_size for path in files)


def copy_worker_shell(package_root: Path, shell_root: Path) -> tuple[int, int]:
    shell_root.mkdir(parents=True)
    for name in RUNTIME_FILES:
        shutil.copyfile(package_root / name, shell_root / name)

    # The user-facing browser opens these small generated configs by URL. Heavy
    # reference and signal assets continue to use the existing asset service.
    if (package_root / "catalog.json").is_file():
        shutil.copyfile(package_root / "catalog.json", shell_root / "catalog.json")
    for config in sorted(package_root.glob("*.config.json")):
        shutil.copyfile(config, shell_root / config.name)
    if (package_root / "assemblies").is_dir():
        shutil.copytree(
            package_root / "assemblies",
            shell_root / "assemblies",
            ignore=shutil.ignore_patterns("*.fna", "*.fai", "*.gff3", "*.bed", "*.bw", "*.tbi", "*.map"),
        )
    if (package_root / "plugins").is_dir():
        shutil.copytree(package_root / "plugins", shell_root / "plugins", copy_function=shutil.copyfile)

    def ignore_source_maps(_directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name.endswith(".map")}

    shutil.copytree(
        package_root / "static",
        shell_root / "static",
        copy_function=shutil.copyfile,
        ignore=ignore_source_maps,
    )
    return validate_worker_shell(shell_root)


def copy_site_source(destination: Path) -> None:
    source = REPO_ROOT / "site"

    generated_root_paths = {"records", "assemblies", "jbrowse", "downloads"}
    generated_data_files = {"catalog.json", "assemblies.json"}

    def ignore_generated_outputs(directory: str, names: list[str]) -> set[str]:
        directory_path = Path(directory).resolve()
        ignored = set(names) & generated_root_paths if directory_path == source.resolve() else set()
        if directory_path == (source / "data").resolve():
            ignored |= set(names) & generated_data_files
        return ignored

    shutil.copytree(
        source,
        destination,
        ignore=ignore_generated_outputs,
        dirs_exist_ok=True,
        copy_function=shutil.copyfile,
    )


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _new_work_directory(parent: Path, label: str) -> Path:
    for _attempt in range(20):
        candidate = parent / f".{label}-{uuid.uuid4().hex}"
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
    raise StageError(f"Could not create a temporary staging directory under {parent}")


def check_output_path(output: Path, source: Path | None) -> None:
    protected = [(REPO_ROOT / "site").resolve(), (REPO_ROOT / "data").resolve()]
    resolved = output.resolve()
    if resolved == REPO_ROOT.resolve():
        raise StageError("The repository root cannot be a staging output directory")
    for protected_root in protected:
        if resolved == protected_root or _is_within(resolved, protected_root) or _is_within(protected_root, resolved):
            raise StageError(f"Staging output must not overlap tracked content: {protected_root}")
    if source is not None:
        source_resolved = source.resolve()
        if resolved == source_resolved or _is_within(resolved, source_resolved) or _is_within(source_resolved, resolved):
            raise StageError(f"Staging output must not overlap its JBrowse source: {source_resolved}")


def _publish_stage(stage_root: Path, output: Path) -> None:
    marker = output.with_name(output.name + STAGE_MARKER)
    if output.exists():
        if output.is_symlink() or not output.is_dir():
            raise StageError(f"Refusing to replace non-directory staging output: {output}")
        if not marker.is_file():
            raise StageError(
                f"Refusing to replace an unmanaged directory: {output}. Choose another output path or move it yourself."
            )
        try:
            existing = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StageError(f"Invalid staging marker in {output}") from exc
        if existing.get("generated_by") != "scripts/stage_site.py":
            raise StageError(f"Refusing to replace a directory not generated by this script: {output}")
        shutil.rmtree(output)
    stage_root.replace(output)
    marker.write_text(json.dumps({"generated_by": "scripts/stage_site.py"}, indent=2) + "\n", encoding="utf-8")


def assemble(
    mode: str,
    output: Path,
    jbrowse_dir: Path | None,
    archive: Path | None,
    checksum_file: Path | None,
    hf_data_base_url: str,
) -> None:
    hf_data_base_url, _revision = normalize_hf_data_base_url(hf_data_base_url)
    check_output_path(output, jbrowse_dir)
    if archive is not None:
        if checksum_file is None:
            raise StageError("--release-sha256-file is required with --release-archive")
        verify_archive_sha256(archive, checksum_file)
    else:
        if checksum_file is not None:
            raise StageError("--release-sha256-file only applies to --release-archive")

    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_stage = _new_work_directory(output.parent, f"{output.name}.stage")
    temp_bundle: Path | None = None
    try:
        temp_bundle = _new_work_directory(output.parent, "bted-jbrowse-release")
        if archive is not None:
            package_root = safe_extract_release(archive, temp_bundle)
        else:
            if jbrowse_dir is None or not jbrowse_dir.is_dir():
                raise StageError("--jbrowse-dir must point to an unpacked JBrowse release package")
            source_package = jbrowse_dir.resolve()
            package_root = temp_bundle / PACKAGE_NAME
            shutil.copytree(source_package, package_root, copy_function=shutil.copyfile)

        # Check the downloaded v0.2 shell and heavy assets before replacing only
        # its catalogue/config overlays with generated v0.3 endpoint tracks.
        run_validator("validate_jbrowse_release.py", package_root, "--legacy-compact-baseline")
        copy_site_source(temp_stage)
        # Build complete download objects beside the temporary JBrowse package.
        # Pages and Worker receive only links plus data-release.json; large data
        # stays in the fixed Hugging Face release prefix.
        version_downloads = temp_bundle / "hf-release" / RELEASE_VERSION
        version_downloads.parent.mkdir(parents=True)
        build_assembly_downloads(version_downloads)
        copy_v03_download_tables(version_downloads)
        apply_v03_jbrowse_configs(package_root, version_downloads, mode, hf_data_base_url)
        refresh_checksums(package_root)
        build_v03_site(
            temp_stage,
            version_downloads,
            package_root,
            studies_path=version_downloads / "studies",
            hf_data_base_url=hf_data_base_url,
        )

        file_count, total_bytes = copy_worker_shell(package_root, temp_stage / "jbrowse")
        if mode == "worker":
            run_validator("validate-site.py", temp_stage)
            print(f"PASS  Worker shell staged: {file_count} files, {total_bytes:,} bytes")
        elif mode == "pages":
            run_validator("validate-site.py", temp_stage)
            print(f"PASS  Pages site staged at {output}")
        else:
            raise StageError(f"Unknown staging mode: {mode}")

        _publish_stage(temp_stage, output)
    finally:
        if temp_stage.exists():
            shutil.rmtree(temp_stage)
        if temp_bundle is not None:
            shutil.rmtree(temp_bundle)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("pages", "worker"), required=True)
    parser.add_argument("--data-version", choices=("v0.3.0", "v0.4.0"), default="v0.4.0")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--release-archive", type=Path, help="Versioned JBrowse release tar.gz")
    source.add_argument("--jbrowse-dir", type=Path, help="Local unpacked package fallback")
    parser.add_argument("--release-sha256-file", type=Path, help="Sidecar checksum for --release-archive")
    parser.add_argument("--output-dir", type=Path, help="Staging directory (default depends on --mode)")
    parser.add_argument(
        "--hf-data-base-url",
        help="Legacy v0.3.0 fixed Hugging Face base URL (required with --data-version v0.3.0)",
    )
    parser.add_argument("--hf-v04-data-base-url", help="Fixed Hugging Face v0.4.0 resolve URL with a commit SHA")
    parser.add_argument(
        "--release-root",
        type=Path,
        default=REPO_ROOT / "data" / "public" / "v0.4.0",
        help="Local v0.4.0 canonical release directory",
    )
    parser.add_argument(
        "--browser-assets-manifest",
        type=Path,
        default=REPO_ROOT / "data" / "registry" / "browser_assets.v0.4.0.tsv",
        help="Canonical browser asset allowlist TSV",
    )
    parser.add_argument(
        "--browser-objects-root",
        type=Path,
        default=REPO_ROOT / "dist" / "v04-browser-objects",
        help="Local generated browser asset objects root",
    )
    args = parser.parse_args()
    default_output = "dist/pages-site" if args.mode == "pages" else "dist/worker-site"
    try:
        if args.data_version == "v0.3.0":
            if not args.hf_data_base_url:
                raise StageError("--hf-data-base-url is required with --data-version v0.3.0")
            assemble(
                mode=args.mode,
                output=args.output_dir or Path(default_output),
                jbrowse_dir=args.jbrowse_dir.expanduser().resolve() if args.jbrowse_dir else None,
                archive=args.release_archive.expanduser().resolve() if args.release_archive else None,
                checksum_file=args.release_sha256_file.expanduser().resolve() if args.release_sha256_file else None,
                hf_data_base_url=args.hf_data_base_url,
            )
        else:
            if args.hf_data_base_url:
                legacy_shared_base, _legacy_revision = normalize_hf_data_base_url(args.hf_data_base_url)
                if legacy_shared_base != V03_SHARED_BASE_URL:
                    raise StageError("v0.4.0 builds require the approved fixed v0.3.0 shared asset revision")
            assemble_v04(
                mode=args.mode,
                output=args.output_dir or Path(default_output),
                jbrowse_dir=args.jbrowse_dir.expanduser().resolve() if args.jbrowse_dir else None,
                archive=args.release_archive.expanduser().resolve() if args.release_archive else None,
                checksum_file=args.release_sha256_file.expanduser().resolve() if args.release_sha256_file else None,
                release_root=args.release_root.expanduser().resolve(),
                browser_assets_manifest=args.browser_assets_manifest.expanduser().resolve(),
                browser_objects_root=args.browser_objects_root.expanduser().resolve(),
                hf_v04_data_base_url=args.hf_v04_data_base_url,
            )
    except (StageError, SiteBuildError, OSError, ValueError, tarfile.TarError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"FAIL  {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
