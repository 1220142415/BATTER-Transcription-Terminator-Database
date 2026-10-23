#!/usr/bin/env python3
"""Validate site files, evidence labels, credentials and internal links.

Usage: python scripts/validate-site.py [site-directory]
"""

from __future__ import annotations

import os
import re
import sys
import zipfile
import json
import hashlib
from html.parser import HTMLParser
from pathlib import Path
from experimental_predictions import prediction_assets, load_predictions
from experimental_signals import signal_assets

MAX_FILE_BYTES = 1024 * 1024  # 1 MiB limit for site files
MAX_JBROWSE_FILE_BYTES = 64 * 1024 * 1024
MAX_DOWNLOAD_FILE_BYTES = 16 * 1024 * 1024

# Exclude raw data, spreadsheet downloads, BED and unapproved archives from site output.
FORBIDDEN_EXTENSIONS = {
    ".fastq", ".fq", ".gz", ".sra", ".csv", ".tsv",
    ".xlsx", ".xls", ".ods",
    ".zip", ".tar", ".tgz", ".bz2", ".xz", ".7z", ".rar",
    ".bam", ".sam", ".cram",
    ".bed", ".gff", ".gff3", ".gtf", ".vcf", ".bcf",
    ".wig", ".bw", ".bigwig",
    ".fa", ".fasta", ".fna",
}

# The staged Pages artifact may contain the separately released JBrowse bundle.
# These file types remain forbidden in the checked-in ``site/`` source, but are
# expected under ``jbrowse/`` after the versioned asset is unpacked.
ALLOWED_JBROWSE_SUFFIXES = {
    ".html", ".css", ".js", ".json", ".txt", ".ico",
    ".fna", ".fai", ".bw", ".gff3", ".gff3.gz", ".tbi", ".ix", ".ixx",
}
ALLOWED_DOWNLOAD_SUFFIXES = {".gff3", ".json", ".txt", ".zip"}
ALLOWED_VERSIONED_COMPRESSED_DOWNLOADS = {
    "downloads/v0.3.0/studies/PMID_31594819/gene_associations.tsv.gz",
    "downloads/v0.3.0/studies/PMID_37402717/condition_observations.tsv.gz",
}
TEXT_EXTENSIONS = {".html", ".htm", ".css", ".js", ".json", ".xml", ".txt", ".md", ".svg", ".tsv"}

# Absolute paths, root-relative links and local filesystem paths
ABSOLUTE_PATH_PATTERNS = [
    (re.compile(r"""(?:href|src|action)\s*=\s*["']/(?!/)""", re.IGNORECASE),
     "Root-relative link (href=\"/...\"); breaks GitHub Pages project paths"),
    (re.compile(r"""url\(\s*["']?/(?!/)""", re.IGNORECASE),
     "Root-relative CSS resource (url(/...))"),
    (re.compile(r"""(?:href|src)\s*=\s*["']//""", re.IGNORECASE),
     "Protocol-relative URL (//...); use explicit https://"),
    (re.compile(r"file://", re.IGNORECASE), "Local file:// reference"),
    (re.compile(r"(?:/Users/|/home/|/opt/|/var/|/tmp/|/private/)[^\s\"'<)]*"),
     "Absolute local filesystem path"),
    (re.compile(r"[A-Za-z]:\\\\[^\s\"'<)]+"), "Local Windows path"),
]

# Exclude localhost and retired local APIs from production output.
# Cloudflare preview site intentionally uses its same-origin catalogue API for JBrowse config.
LOCALHOST_API_PATTERNS = [
    (re.compile(r"127\.0\.0\.1|localhost", re.IGNORECASE), "localhost / 127.0.0.1 reference"),
    (re.compile(r"/api/augmentation\b|bted-augmentation\.html", re.IGNORECASE), "Retired augmentation page or API"),
]

# Credentials, keys and password placeholders
SECRET_PATTERNS = [
    (re.compile(r"\bapi[_-]?key\b", re.IGNORECASE), "API key text"),
    (re.compile(r"\bpassword\b", re.IGNORECASE), "password text"),
    (re.compile(r"\bpasswd\b", re.IGNORECASE), "passwd text"),
    (re.compile(r"\bsecret\b", re.IGNORECASE), "secret text"),
    (re.compile(r"\baccess[_-]?token\b", re.IGNORECASE), "access token text"),
    (re.compile(r"\bauth[_-]?token\b", re.IGNORECASE), "auth token text"),
    (re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE), "Bearer token"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "PEM private key"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS Access Key ID"),
    (re.compile(r"\bghp_[A-Za-z0-9]{30,}\b"), "GitHub personal access token"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "GitHub fine-grained token"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "Slack token"),
    (re.compile(r"\byour[_-]?(api[_-]?key|token|password|secret)\b", re.IGNORECASE),
     "Credential placeholder (YOUR_...)"),
]

# Reject unsupported evidence claims, including negative constructions.
FORBIDDEN_LABEL_PATTERNS = [
    (re.compile(r"experimentally\s+validated", re.IGNORECASE), "Unsupported evidence claim"),
    (re.compile(r"experimentally\s+verified", re.IGNORECASE), "Unsupported evidence claim"),
    (re.compile(r"experimentally\s+confirmed", re.IGNORECASE), "Unsupported evidence claim"),
    (re.compile(r"experimental\s+validation", re.IGNORECASE), "Unsupported evidence claim"),
    (re.compile(r"validated\s+terminator", re.IGNORECASE), "Unsupported evidence claim"),
    (re.compile(r"confirmed\s+terminator", re.IGNORECASE), "Unsupported evidence claim"),
    (re.compile(r"\u5b9e\u9a8c\u9a8c\u8bc1"), "Unsupported evidence claim"),
    (re.compile(r"\u5b9e\u9a8c\u8bc1\u5b9e"), "Unsupported evidence claim"),
    (re.compile(r"\u7ecf\u5b9e\u9a8c\u786e\u8ba4"), "Unsupported evidence claim"),
]

REQUIRED_FILES = ["index.html", "sources.html", "catalog.html", "methodology.html", "about.html", "css/style.css"]
HF_RELEASE_BASE_PATTERN = re.compile(
    r"^https://huggingface\.co/datasets/liurulong/terminator/resolve/([0-9a-f]{40})/v0\.3\.0$"
)
HF_RESOLVE_URL_PATTERN = re.compile(
    r"https://huggingface\.co/datasets/[^\s\"'<>]+/resolve/[^\s\"'<>]+"
)
V03_SHARED_REVISION = "90651318aedf5a5ca26b8308070927d36fd3d6c9"
HF_DATASET_PREFIX = "https://huggingface.co/datasets/liurulong/terminator/resolve"


class LinkCollector(HTMLParser):
    """Collect HTML href/src references for relative-link checks."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[int, str, str]] = []  # (line, attribute, value)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name in ("href", "src", "action") and value:
                self.links.append((self.getpos()[0], name, value))


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def is_allowed_download_file(
    rel: str, suffix: str, compound_suffix: str, allowed_v04_paths: set[str] | None = None,
) -> bool:
    """Allow exactly the v0.4 manifest files or the legacy v0.3 downloads."""
    return (
        rel in (allowed_v04_paths or set())
        or rel in ALLOWED_VERSIONED_COMPRESSED_DOWNLOADS
        or bool(re.fullmatch(r"downloads/v0\.3\.0/studies/PMID_[0-9]+/endpoints\.gff3\.gz", rel))
        or bool(re.fullmatch(r"downloads/v0\.3\.0/studies/PMID_[0-9]+/metadata\.tsv", rel))
        or suffix in ALLOWED_DOWNLOAD_SUFFIXES
    )


def scan_text(path: Path, rel: str, problems: list[str]) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, ValueError):
        return  # Non-UTF-8 content is covered by extension/size checks.
    for regex, desc in ABSOLUTE_PATH_PATTERNS:
        for m in regex.finditer(text):
            problems.append(f"{rel}:{line_of(text, m.start())} Absolute path -- {desc}: {m.group(0)[:80]}")
    for regex, desc in SECRET_PATTERNS:
        for m in regex.finditer(text):
            problems.append(f"{rel}:{line_of(text, m.start())} Possible credential -- {desc}: {m.group(0)[:40]}")
    for regex, desc in FORBIDDEN_LABEL_PATTERNS:
        for m in regex.finditer(text):
            problems.append(f"{rel}:{line_of(text, m.start())} {desc}: {m.group(0)}")


def scan_localhost_api(path: Path, rel: str, problems: list[str]) -> None:
    """Scan project-authored text for localhost or internal API dependencies."""
    text = path.read_text(encoding="utf-8")
    for regex, desc in LOCALHOST_API_PATTERNS:
        for m in regex.finditer(text):
            problems.append(f"{rel}:{line_of(text, m.start())} {desc}: {m.group(0)[:80]}")


def config_uris(value: object) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        if isinstance(value.get("uri"), str):
            found.append(str(value["uri"]))
        for key, child in value.items():
            if key == "plugins":
                continue
            found.extend(config_uris(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(config_uris(child))
    return found


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_v04_release(site_dir: Path, manifest: dict[str, object], problems: list[str]) -> set[str]:
    """Validate one v0.4 data revision plus the reused, pinned v0.3 assets."""
    shared = manifest.get("sharedAssets")
    revision = manifest.get("releaseRevision")
    assets = manifest.get("assets")
    if (
        not isinstance(shared, dict)
        or shared.get("releaseVersion") != "v0.3.0"
        or shared.get("revision") != V03_SHARED_REVISION
        or not isinstance(assets, dict)
        or not assets
        or (revision is not None and (not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision)))
    ):
        problems.append("Invalid v0.4.0 release or fixed asset revision in assets/data-release.json")
        return set()

    allowed_urls: set[str] = set()
    allowed_local: set[str] = set()
    registered_signals = prediction_assets(signal_assets({}))
    for logical_path, entry in assets.items():
        if (
            not isinstance(logical_path, str)
            or not logical_path
            or logical_path.startswith("/")
            or ".." in Path(logical_path).parts
            or not isinstance(entry, dict)
        ):
            problems.append(f"Invalid asset manifest path: {logical_path!r}")
            continue
        url = entry.get("url")
        asset_revision = entry.get("revision")
        sha256 = entry.get("sha256")
        size = entry.get("byte_size")
        if (
            not isinstance(url, str)
            or not isinstance(sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", sha256)
            or not isinstance(size, int)
            or size < 0
            or not isinstance(entry.get("asset_kind"), str)
        ):
            problems.append(f"Invalid asset manifest field: {logical_path}")
            continue
        shared_url = f"{HF_DATASET_PREFIX}/{V03_SHARED_REVISION}/v0.3.0/{logical_path}"
        local_url = f"downloads/v0.4.0/{logical_path}"
        published_url = f"{HF_DATASET_PREFIX}/{revision}/v0.4.0/{logical_path}" if revision else None
        if url == shared_url and asset_revision == V03_SHARED_REVISION:
            pass
        elif revision is None and url == local_url and asset_revision == "local":
            rel = local_url
            allowed_local.add(rel)
            path = site_dir / rel
            if not path.is_file() or path.stat().st_size != size or _sha256_file(path) != sha256:
                problems.append(f"Local release asset missing or integrity check failed: {rel}")
        elif published_url and url == published_url and asset_revision == revision:
            pass
        elif (registered := registered_signals.get(logical_path)) and all(entry.get(k) == registered[k] for k in ('url', 'revision', 'sha256', 'byte_size', 'asset_kind')):
            pass
        else:
            problems.append(f"Asset URL is not pinned to the approved revision: {logical_path}")
            continue
        allowed_urls.add(url)

    if revision is not None and (site_dir / "downloads").exists():
        problems.append("HF-backed sites must not duplicate the downloads directory")
    if revision is None and not allowed_local:
        problems.append("Local v0.4.0 site lacks release assets")

    for path in site_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        rel = path.relative_to(site_dir).as_posix()
        if is_pinned_jbrowse_vendor_asset(rel):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for found in HF_RESOLVE_URL_PATTERN.finditer(content):
            url = found.group(0).rstrip("),.;")
            if url not in allowed_urls:
                problems.append(f"{rel} references an unregistered Hugging Face file: {url[:120]}")

    jbrowse_root = site_dir / "jbrowse"
    config_paths = [*jbrowse_root.glob("assemblies/*.config.json")]
    if not config_paths:
        problems.append("v0.4.0 site lacks genome JBrowse configs")
    plugin_file = jbrowse_root / "plugins/bted-track-plugin.js"
    if not plugin_file.is_file():
        problems.append("v0.4.0 site lacks the BTED JBrowse plugin")
    for config_path in config_paths:
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            problems.append(f"{config_path.relative_to(site_dir).as_posix()} is not valid JSON")
            continue
        for uri in config_uris(config):
            normalized = uri.removeprefix("../../")
            if uri not in allowed_urls and normalized not in allowed_urls:
                problems.append(f"{config_path.relative_to(site_dir).as_posix()} has unregistered data URI: {uri}")
        configured_plugins = config.get("plugins", [])
        if len(configured_plugins) != 1:
            problems.append(f"{config_path.relative_to(site_dir).as_posix()} requires exactly one BTED plugin config")
        for plugin in configured_plugins:
            uri = plugin.get("esmUrl") if isinstance(plugin, dict) else None
            if not isinstance(plugin, dict) or plugin.get("name") != "BTEDTrackPlugin" or uri not in {"plugins/bted-track-plugin.js", "plugins/bted-track-plugin.js?v=41"}:
                problems.append(f"{config_path.relative_to(site_dir).as_posix()} has invalid BTED plugin config")
            elif not (jbrowse_root / uri.split("?", 1)[0]).is_file():
                problems.append(f"{config_path.relative_to(site_dir).as_posix()} lacks the BTED plugin file")
        for track in config.get("tracks", []):
            if not isinstance(track, dict):
                problems.append(f"{config_path.relative_to(site_dir).as_posix()} contains an invalid track")
                continue
            about = track.get("metadata", {}).get("btedAbout", {})
            kind = about.get("kind") if isinstance(about, dict) else None
            if kind not in {"endpoint", "signal", "reference", "prediction"}:
                problems.append(f"{config_path.relative_to(site_dir).as_posix()} track About lacks a BTED evidence type")
            if kind == "endpoint":
                display = (track.get("displays") or [{}])[0]
                renderer = display.get("renderer", {}) if isinstance(display, dict) else {}
                if renderer.get("color1") != "jexl:btedStrandColor(feature)":
                    problems.append(f"{config_path.relative_to(site_dir).as_posix()} endpoint track lacks strand colors")
            if kind == "prediction":
                registered = load_predictions()['genomes'].get(config_path.name.removesuffix('.config.json'))
                counts = track.get('metadata', {}).get('btedContigCounts', {})
                if not registered or counts != registered['contig_counts'] or about.get('record_count') != registered['prediction_count'] or about.get('evidence') != 'Model prediction':
                    problems.append(f"{config_path.relative_to(site_dir).as_posix()} prediction track differs from verified registration")
            if kind == "reference":
                display = (track.get("displays") or [{}])[0]
                renderer = display.get("renderer", {}) if isinstance(display, dict) else {}
                if (renderer.get("color1") != "jexl:btedStrandColor(feature)"
                        or renderer.get("color2") != "jexl:btedStrandColor(feature)"):
                    problems.append(f"{config_path.relative_to(site_dir).as_posix()} annotation track lacks strand colors")
            if kind == "signal":
                display = (track.get("displays") or [{}])[0]
                subadapters = track.get("adapter", {}).get("subadapters", [])
                by_source = {item.get("source"): item for item in subadapters if isinstance(item, dict)}
                if (track.get("type") != "MultiQuantitativeTrack" or not track.get("metadata", {}).get("btedMirroredSignal")
                        or display.get("type") != "MultiLinearWiggleDisplay" or set(by_source) != {"plus", "minus"}
                        or by_source["plus"].get("color") != "#0f766e" or by_source["minus"].get("color") != "#be123c"):
                    problems.append(f"{config_path.relative_to(site_dir).as_posix()} signal track lacks mirrored strand display")
    return allowed_local


def validate_fixed_hf_release(site_dir: Path, problems: list[str]) -> set[str]:
    """Validate either the legacy v0.3 site or the v0.4 dual-revision site."""
    manifest_path = site_dir / "assets/data-release.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        problems.append("Missing or unreadable assets/data-release.json")
        return set()
    if isinstance(manifest, dict) and manifest.get("releaseVersion") == "v0.4.0":
        return validate_v04_release(site_dir, manifest, problems)
    base = manifest.get("baseUrl") if isinstance(manifest, dict) else None
    release_version = manifest.get("releaseVersion") if isinstance(manifest, dict) else None
    revision = manifest.get("revision") if isinstance(manifest, dict) else None
    match = HF_RELEASE_BASE_PATTERN.fullmatch(base or "") if isinstance(base, str) else None
    if not match or release_version != "v0.3.0" or revision != match.group(1):
        problems.append("assets/data-release.json must pin a liurulong/terminator v0.3.0 commit")
        return set()

    expected_prefix = f"{base}/"
    for path in site_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        rel = path.relative_to(site_dir).as_posix()
        if is_pinned_jbrowse_vendor_asset(rel):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match_url in HF_RESOLVE_URL_PATTERN.finditer(text):
            value = match_url.group(0).rstrip("),.;")
            if value != base and not value.startswith(expected_prefix):
                problems.append(f"{rel} uses an unpinned or different Hugging Face revision: {value[:120]}")

    jbrowse_root = site_dir / "jbrowse"
    for config_path in [*jbrowse_root.glob("*.config.json"), *jbrowse_root.glob("assemblies/*.config.json")]:
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            problems.append(f"{config_path.relative_to(site_dir).as_posix()} is not valid JSON")
            continue
        for uri in config_uris(config):
            if not uri.startswith(expected_prefix):
                problems.append(
                    f"{config_path.relative_to(site_dir).as_posix()} has a JBrowse data URI not pinned to the HF revision: {uri}"
                )

    if (site_dir / "downloads").exists():
        problems.append("Do not duplicate data downloads; generate the HF manifest and external links")
    return set()


def is_pinned_jbrowse_vendor_asset(rel: str) -> bool:
    """Return whether a file belongs to the pinned upstream JBrowse runtime.

    Minified upstream bundles legitimately contain terms such as ``password``
    (UI labels) and source-map build paths.  They are not project-authored
    content and are integrity-checked by ``validate_jbrowse_release.py``.
    BTED configs, catalogs and data assets remain subject to the strict scan.
    """

    return rel.startswith("jbrowse/static/")


def check_links(path: Path, site_root: Path, rel: str, problems: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    parser = LinkCollector()
    parser.feed(text)
    for lineno, attr, value in parser.links:
        target = value.strip()
        if target.startswith(("http://", "https://", "mailto:", "data:", "#")):
            continue
        target_path = target.split("#", 1)[0].split("?", 1)[0]
        if not target_path:
            continue
        resolved = (path.parent / target_path).resolve()
        try:
            resolved.relative_to(site_root)
        except ValueError:
            problems.append(f"{rel}:{lineno} internal link escapes the site directory: {target}")
            continue
        if not resolved.exists():
            # JBrowse is intentionally delivered as a versioned GitHub Release
            # asset and unpacked beside the site during Pages deployment.  The
            # source-only site may therefore contain valid future links before
            # the bundle is staged.  Once a ``jbrowse`` directory exists in the
            # validation root, missing files inside it are treated as errors.
            for staged_name in ("jbrowse", "downloads"):
                staged_root = site_root / staged_name
                try:
                    resolved.relative_to(staged_root)
                    if not staged_root.exists():
                        break
                except ValueError:
                    continue
            else:
                problems.append(f"{rel}:{lineno} unresolved internal link: {target}")
                continue
            if not staged_root.exists():
                continue
            problems.append(f"{rel}:{lineno} unresolved internal link: {target}")


def check_assembly_zip(path: Path) -> list[str]:
    """Require genome ZIPs to contain only GFF3 and readable metadata tables."""
    try:
        with zipfile.ZipFile(path) as archive:
            members = [name for name in archive.namelist() if not name.endswith("/")]
    except (OSError, zipfile.BadZipFile) as exc:
        return [f"{path.name} is not a valid assembly ZIP: {exc}"]

    return check_assembly_zip_members(members, path.name)


def check_assembly_zip_members(members: list[str], archive_name: str = "assembly.zip") -> list[str]:
    """Validate the archive member names without touching the filesystem."""
    if not any(name == "metadata.tsv" or name.endswith("/metadata.tsv") for name in members):
        return [f"{archive_name} missing metadata.tsv"]
    unexpected = sorted(
        name for name in members
        if name.startswith("/")
        or ".." in Path(name).parts
        or not (
            name.endswith(("/endpoints.gff3", "/endpoints.gff3.gz"))
            or Path(name).name in {
                "metadata.tsv", "gene_associations.tsv.gz", "condition_observations.tsv.gz"
            }
        )
    )
    if unexpected:
        return [f"{archive_name} contains files other than GFF3 and TSV: {unexpected}"]
    if len(members) != len(set(members)):
        return [f"{archive_name} contains duplicate filenames"]
    return []


def main() -> int:
    site_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "site").resolve()
    if not site_dir.is_dir():
        print(f"FAIL Site directory does not exist: {site_dir}")
        return 1

    problems: list[str] = []
    warnings: list[str] = []
    file_count = 0
    total_bytes = 0
    allowed_v04_paths: set[str] = set()

    # 0. Required files
    for name in REQUIRED_FILES:
        if not (site_dir / name).is_file():
            problems.append(f"Missing required file: {name}")

    # The raw checked-in ``site/`` source has no bundled JBrowse shell. A
    # Pages/Worker artifact does and must carry the same fixed HF revision.
    if (site_dir / "jbrowse").is_dir():
        allowed_v04_paths = validate_fixed_hf_release(site_dir, problems)

    for root, _dirs, files in os.walk(site_dir):
        for fname in files:
            fpath = Path(root) / fname
            rel = str(fpath.relative_to(site_dir)).replace("\\", "/")
            file_count += 1
            size = fpath.stat().st_size
            total_bytes += size

            # 1. File type and size
            suffixes = [s.lower() for s in fpath.suffixes]
            in_jbrowse = rel == "jbrowse" or rel.startswith("jbrowse/")
            in_downloads = rel == "downloads" or rel.startswith("downloads/")
            compound_suffix = "".join(suffixes[-2:]) if len(suffixes) >= 2 else (suffixes[-1] if suffixes else "")
            jbrowse_allowed = in_jbrowse and (
                fpath.suffix.lower() in ALLOWED_JBROWSE_SUFFIXES
                or compound_suffix in ALLOWED_JBROWSE_SUFFIXES
            )
            download_allowed = in_downloads and is_allowed_download_file(
                rel, fpath.suffix.lower(), compound_suffix, allowed_v04_paths
            )
            if any(s in FORBIDDEN_EXTENSIONS for s in suffixes) and not (
                jbrowse_allowed or download_allowed
            ):
                problems.append(f"{rel} disallowed file type (raw data/workbook/archive/coordinates)")
            size_limit = MAX_JBROWSE_FILE_BYTES if in_jbrowse else (MAX_DOWNLOAD_FILE_BYTES if in_downloads else MAX_FILE_BYTES)
            if rel == "assets/batter-browser.json":
                size_limit = MAX_DOWNLOAD_FILE_BYTES  # Compact metadata only; no genome/track files.
            if size > size_limit:
                problems.append(f"{rel} file too large ({size} bytes > {size_limit} byte limit)")

            lower_name = fname.lower()
            if lower_name == "bted-augmentation.html" or rel.startswith("data/augmentation/"):
                problems.append(f"{rel} belongs to a retired augmentation page or data directory")

            if in_downloads and fpath.suffix.lower() == ".zip":
                problems.extend(check_assembly_zip(fpath))

            # 2-4. Text-content checks
            if fpath.suffix.lower() in TEXT_EXTENSIONS and not is_pinned_jbrowse_vendor_asset(rel):
                scan_text(fpath, rel, problems)

            # 2-4b. localhost / API dependency checks (project-owned text only)
            if fpath.suffix.lower() in TEXT_EXTENSIONS and not is_pinned_jbrowse_vendor_asset(rel):
                scan_localhost_api(fpath, rel, problems)

            # 5. HTML internal links
            if fpath.suffix.lower() in (".html", ".htm"):
                check_links(fpath, site_dir, rel, problems)

    print("=" * 60)
    print("BTED site validation")
    print(f"Site directory: {site_dir}")
    print(f"Files: {file_count}, total size: {total_bytes} bytes")
    print("Checks: required files / GFF3 and ZIP / types and sizes / paths / credentials / evidence / links")
    print("=" * 60)

    for w in warnings:
        print(f"WARN  {w}")
    if problems:
        for p in problems:
            print(f"FAIL  {p}")
        print(f"\nValidation failed: {len(problems)} problems.")
        return 1
    print("PASS  All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
