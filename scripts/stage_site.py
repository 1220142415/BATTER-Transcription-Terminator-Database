#!/usr/bin/env python3
"""Assemble Pages or Worker site assets from a verified BTED JBrowse release."""

from __future__ import annotations

import argparse
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


REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_NAME = "BTED-v0.2.0-jbrowse"
ARCHIVE_NAME = f"{PACKAGE_NAME}-assets.tar.gz"
RUNTIME_FILES = ("index.html", "manifest.json", "favicon.ico", "robots.txt", "version.txt")
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
STAGE_MARKER = ".bted-stage.json"
SHA_LINE = re.compile(r"^([0-9a-fA-F]{64})(?:\s+\*?(.+))?$")
HF_DATA_BASE_PATTERN = re.compile(
    r"^https://huggingface\.co/datasets/liurulong/terminator/resolve/([0-9a-f]{40})/v0\.3\.0$"
)
class StageError(RuntimeError):
    """Raised when a requested site artifact cannot be safely assembled."""


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
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--release-archive", type=Path, help="Versioned JBrowse release tar.gz")
    source.add_argument("--jbrowse-dir", type=Path, help="Local unpacked package fallback")
    parser.add_argument("--release-sha256-file", type=Path, help="Sidecar checksum for --release-archive")
    parser.add_argument("--output-dir", type=Path, help="Staging directory (default depends on --mode)")
    parser.add_argument(
        "--hf-data-base-url",
        required=True,
        help="Fixed Hugging Face v0.3.0 resolve URL ending in /resolve/<40-character-commit>/v0.3.0",
    )
    args = parser.parse_args()
    default_output = "dist/pages-site" if args.mode == "pages" else "dist/worker-site"
    try:
        assemble(
            mode=args.mode,
            output=args.output_dir or Path(default_output),
            jbrowse_dir=args.jbrowse_dir.expanduser().resolve() if args.jbrowse_dir else None,
            archive=args.release_archive.expanduser().resolve() if args.release_archive else None,
            checksum_file=args.release_sha256_file.expanduser().resolve() if args.release_sha256_file else None,
            hf_data_base_url=args.hf_data_base_url,
        )
    except (StageError, OSError, ValueError, tarfile.TarError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"FAIL  {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
