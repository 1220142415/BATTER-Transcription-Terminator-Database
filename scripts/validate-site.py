#!/usr/bin/env python3
"""BTED GitHub Pages 静态演示站点安全验证脚本。

对站点产物目录（默认 site/）执行以下检查，任一检查失败即以退出码 1 结束：

1. 文件类型与体积：拒绝原始测序文件、工作簿和压缩包；站点下载只允许指定格式并限制大小。
2. 绝对路径：无根相对链接（href="/..."）、无 file:// 与本地文件系统路径。
3. 凭据扫描：无 API key、密码、令牌等占位或真实凭据格式。
4. 证据标签：无未经批准的证据标签（如 "experimentally validated" / "实验验证"）。
5. 内部链接完整性：HTML 中的相对链接必须能解析到产物内的真实文件。

用法：
    python3 scripts/validate-site.py [站点目录]   # 默认 site/
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

MAX_FILE_BYTES = 1024 * 1024  # 1 MiB；站点页面与样式均为 KB 级
MAX_JBROWSE_FILE_BYTES = 64 * 1024 * 1024
MAX_DOWNLOAD_FILE_BYTES = 16 * 1024 * 1024

# 原始数据、表格下载、BED 和未经允许的压缩包不得进入站点产物。
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

# 绝对路径 / 根相对链接 / 本地文件系统路径
ABSOLUTE_PATH_PATTERNS = [
    (re.compile(r"""(?:href|src|action)\s*=\s*["']/(?!/)""", re.IGNORECASE),
     "根相对链接（href=\"/...\"），GitHub Pages 项目子路径下会失效"),
    (re.compile(r"""url\(\s*["']?/(?!/)""", re.IGNORECASE),
     "CSS 根相对资源引用（url(/...)）"),
    (re.compile(r"""(?:href|src)\s*=\s*["']//""", re.IGNORECASE),
     "协议相对 URL（//...），应使用显式 https://"),
    (re.compile(r"file://", re.IGNORECASE), "file:// 本地文件引用"),
    (re.compile(r"(?:/Users/|/home/|/opt/|/var/|/tmp/|/private/)[^\s\"'<)]*"),
     "本地文件系统绝对路径"),
    (re.compile(r"[A-Za-z]:\\\\[^\s\"'<)]+"), "Windows 本地路径"),
]

# localhost / 127.0.0.1 / old local API endpoint 不应出现在正式 site/；当前
# Cloudflare preview site intentionally uses its same-origin catalogue API for JBrowse config.
LOCALHOST_API_PATTERNS = [
    (re.compile(r"127\.0\.0\.1|localhost", re.IGNORECASE), "localhost / 127.0.0.1 引用"),
    (re.compile(r"/api/augmentation\b|bted-augmentation\.html", re.IGNORECASE), "已移除的增强页面或 API"),
]

# 凭据 / 密钥 / 口令占位
SECRET_PATTERNS = [
    (re.compile(r"\bapi[_-]?key\b", re.IGNORECASE), "API key 字样"),
    (re.compile(r"\bpassword\b", re.IGNORECASE), "password 字样"),
    (re.compile(r"\bpasswd\b", re.IGNORECASE), "passwd 字样"),
    (re.compile(r"\bsecret\b", re.IGNORECASE), "secret 字样"),
    (re.compile(r"\baccess[_-]?token\b", re.IGNORECASE), "access token 字样"),
    (re.compile(r"\bauth[_-]?token\b", re.IGNORECASE), "auth token 字样"),
    (re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE), "Bearer 令牌"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "PEM 私钥"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS Access Key ID"),
    (re.compile(r"\bghp_[A-Za-z0-9]{30,}\b"), "GitHub personal access token"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "GitHub fine-grained token"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "Slack token"),
    (re.compile(r"\byour[_-]?(api[_-]?key|token|password|secret)\b", re.IGNORECASE),
     "凭据占位符（YOUR_...）"),
]

# 未经批准的证据标签（骨架阶段一律禁止出现，包括否定语境，以免被误读）
FORBIDDEN_LABEL_PATTERNS = [
    (re.compile(r"experimentally\s+validated", re.IGNORECASE), "未批准证据标签"),
    (re.compile(r"experimentally\s+verified", re.IGNORECASE), "未批准证据标签"),
    (re.compile(r"experimentally\s+confirmed", re.IGNORECASE), "未批准证据标签"),
    (re.compile(r"experimental\s+validation", re.IGNORECASE), "未批准证据标签"),
    (re.compile(r"validated\s+terminator", re.IGNORECASE), "未批准证据标签"),
    (re.compile(r"confirmed\s+terminator", re.IGNORECASE), "未批准证据标签"),
    (re.compile(r"实验验证"), "未批准证据标签"),
    (re.compile(r"实验证实"), "未批准证据标签"),
    (re.compile(r"经实验确认"), "未批准证据标签"),
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
    """收集 HTML 中的 href/src 引用，用于相对链接完整性检查。"""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[int, str, str]] = []  # (行号, 属性, 值)

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
        return  # 非 UTF-8 文本由扩展名/体积检查覆盖
    for regex, desc in ABSOLUTE_PATH_PATTERNS:
        for m in regex.finditer(text):
            problems.append(f"{rel}:{line_of(text, m.start())} 绝对路径 —— {desc}: {m.group(0)[:80]}")
    for regex, desc in SECRET_PATTERNS:
        for m in regex.finditer(text):
            problems.append(f"{rel}:{line_of(text, m.start())} 疑似凭据 —— {desc}: {m.group(0)[:40]}")
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
        problems.append("assets/data-release.json 的 v0.4.0 版本或固定资产版本无效")
        return set()

    allowed_urls: set[str] = set()
    allowed_local: set[str] = set()
    for logical_path, entry in assets.items():
        if (
            not isinstance(logical_path, str)
            or not logical_path
            or logical_path.startswith("/")
            or ".." in Path(logical_path).parts
            or not isinstance(entry, dict)
        ):
            problems.append(f"资产清单路径无效: {logical_path!r}")
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
            problems.append(f"资产清单字段无效: {logical_path}")
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
                problems.append(f"本地发布资产缺失或校验失败: {rel}")
        elif published_url and url == published_url and asset_revision == revision:
            pass
        else:
            problems.append(f"资产 URL 未固定到批准版本: {logical_path}")
            continue
        allowed_urls.add(url)

    if revision is not None and (site_dir / "downloads").exists():
        problems.append("已固定到 Hugging Face 的站点不应重复打包 downloads 目录")
    if revision is None and not allowed_local:
        problems.append("本地 v0.4.0 站点缺少发布资产")

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
                problems.append(f"{rel} 引用未列入清单的 Hugging Face 文件: {url[:120]}")

    jbrowse_root = site_dir / "jbrowse"
    config_paths = [*jbrowse_root.glob("assemblies/*.config.json")]
    if not config_paths:
        problems.append("v0.4.0 站点缺少基因组 JBrowse 配置")
    plugin_file = jbrowse_root / "plugins/bted-track-plugin.js"
    if not plugin_file.is_file():
        problems.append("v0.4.0 站点缺少 BTED JBrowse 插件")
    for config_path in config_paths:
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            problems.append(f"{config_path.relative_to(site_dir).as_posix()} 不是有效 JSON")
            continue
        for uri in config_uris(config):
            normalized = uri.removeprefix("../../")
            if uri not in allowed_urls and normalized not in allowed_urls:
                problems.append(f"{config_path.relative_to(site_dir).as_posix()} 的数据 URI 未列入清单: {uri}")
        configured_plugins = config.get("plugins", [])
        if len(configured_plugins) != 1:
            problems.append(f"{config_path.relative_to(site_dir).as_posix()} 缺少唯一 BTED 插件配置")
        for plugin in configured_plugins:
            uri = plugin.get("esmUrl") if isinstance(plugin, dict) else None
            if not isinstance(plugin, dict) or plugin.get("name") != "BTEDTrackPlugin" or uri != "plugins/bted-track-plugin.js":
                problems.append(f"{config_path.relative_to(site_dir).as_posix()} 的 BTED 插件配置无效")
            elif not (jbrowse_root / uri).is_file():
                problems.append(f"{config_path.relative_to(site_dir).as_posix()} 缺少 BTED 插件文件")
        for track in config.get("tracks", []):
            if not isinstance(track, dict):
                problems.append(f"{config_path.relative_to(site_dir).as_posix()} 包含无效轨道")
                continue
            about = track.get("metadata", {}).get("btedAbout", {})
            kind = about.get("kind") if isinstance(about, dict) else None
            if kind not in {"endpoint", "signal", "reference"}:
                problems.append(f"{config_path.relative_to(site_dir).as_posix()} 轨道 About 缺少 BTED 证据类型")
            if kind == "endpoint":
                display = (track.get("displays") or [{}])[0]
                renderer = display.get("renderer", {}) if isinstance(display, dict) else {}
                if renderer.get("color1") != "jexl:btedStrandColor(feature)":
                    problems.append(f"{config_path.relative_to(site_dir).as_posix()} 端点轨道未按链着色")
            if kind == "signal":
                display = (track.get("displays") or [{}])[0]
                color = display.get("renderers", {}).get("XYPlotRenderer", {}).get("color") if isinstance(display, dict) else None
                expected_color = "#0f766e" if about.get("strand") == "+" else "#be123c" if about.get("strand") == "-" else "#64748b"
                if color != expected_color:
                    problems.append(f"{config_path.relative_to(site_dir).as_posix()} 信号轨道链向颜色错误")
    return allowed_local


def validate_fixed_hf_release(site_dir: Path, problems: list[str]) -> set[str]:
    """Validate either the legacy v0.3 site or the v0.4 dual-revision site."""
    manifest_path = site_dir / "assets/data-release.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        problems.append("缺少或无法读取 assets/data-release.json")
        return set()
    if isinstance(manifest, dict) and manifest.get("releaseVersion") == "v0.4.0":
        return validate_v04_release(site_dir, manifest, problems)
    base = manifest.get("baseUrl") if isinstance(manifest, dict) else None
    release_version = manifest.get("releaseVersion") if isinstance(manifest, dict) else None
    revision = manifest.get("revision") if isinstance(manifest, dict) else None
    match = HF_RELEASE_BASE_PATTERN.fullmatch(base or "") if isinstance(base, str) else None
    if not match or release_version != "v0.3.0" or revision != match.group(1):
        problems.append("assets/data-release.json 必须指向固定的 liurulong/terminator v0.3.0 commit")
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
                problems.append(f"{rel} 使用了未固定或其他 Hugging Face revision: {value[:120]}")

    jbrowse_root = site_dir / "jbrowse"
    for config_path in [*jbrowse_root.glob("*.config.json"), *jbrowse_root.glob("assemblies/*.config.json")]:
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            problems.append(f"{config_path.relative_to(site_dir).as_posix()} 不是有效 JSON")
            continue
        for uri in config_uris(config):
            if not uri.startswith(expected_prefix):
                problems.append(
                    f"{config_path.relative_to(site_dir).as_posix()} 的 JBrowse 数据 URI 未固定到 HF revision: {uri}"
                )

    if (site_dir / "downloads").exists():
        problems.append("站点不应重复打包数据下载目录；请只生成 HF manifest 和外部下载链接")
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
            problems.append(f"{rel}:{lineno} 内部链接越出站点目录: {target}")
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
                problems.append(f"{rel}:{lineno} 内部链接无法解析: {target}")
                continue
            if not staged_root.exists():
                continue
            problems.append(f"{rel}:{lineno} 内部链接无法解析: {target}")


def check_assembly_zip(path: Path) -> list[str]:
    """Require genome ZIPs to contain only GFF3 and readable metadata tables."""
    try:
        with zipfile.ZipFile(path) as archive:
            members = [name for name in archive.namelist() if not name.endswith("/")]
    except (OSError, zipfile.BadZipFile) as exc:
        return [f"{path.name} 不是有效的组装 ZIP: {exc}"]

    return check_assembly_zip_members(members, path.name)


def check_assembly_zip_members(members: list[str], archive_name: str = "assembly.zip") -> list[str]:
    """Validate the archive member names without touching the filesystem."""
    if not any(name == "metadata.tsv" or name.endswith("/metadata.tsv") for name in members):
        return [f"{archive_name} 缺少 metadata.tsv"]
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
        return [f"{archive_name} 含有 GFF3 和 TSV 以外的文件: {unexpected}"]
    if len(members) != len(set(members)):
        return [f"{archive_name} 含有重复文件名"]
    return []


def main() -> int:
    site_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "site").resolve()
    if not site_dir.is_dir():
        print(f"FAIL 站点目录不存在: {site_dir}")
        return 1

    problems: list[str] = []
    warnings: list[str] = []
    file_count = 0
    total_bytes = 0
    allowed_v04_paths: set[str] = set()

    # 0. 必需文件
    for name in REQUIRED_FILES:
        if not (site_dir / name).is_file():
            problems.append(f"缺少必需文件: {name}")

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

            # 1. 文件类型与体积
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
                problems.append(f"{rel} 禁止的文件类型（原始数据/工作簿/压缩包/坐标文件）")
            size_limit = MAX_JBROWSE_FILE_BYTES if in_jbrowse else (MAX_DOWNLOAD_FILE_BYTES if in_downloads else MAX_FILE_BYTES)
            if size > size_limit:
                problems.append(f"{rel} 文件过大（{size} 字节 > {size_limit} 字节上限）")

            lower_name = fname.lower()
            if lower_name == "bted-augmentation.html" or rel.startswith("data/augmentation/"):
                problems.append(f"{rel} 属于已移除的增强页面或增强数据目录")

            if in_downloads and fpath.suffix.lower() == ".zip":
                problems.extend(check_assembly_zip(fpath))

            # 2-4. 文本内容扫描
            if fpath.suffix.lower() in TEXT_EXTENSIONS and not is_pinned_jbrowse_vendor_asset(rel):
                scan_text(fpath, rel, problems)

            # 2-4b. localhost / API 依赖扫描（仅项目自产文本）
            if fpath.suffix.lower() in TEXT_EXTENSIONS and not is_pinned_jbrowse_vendor_asset(rel):
                scan_localhost_api(fpath, rel, problems)

            # 5. HTML 内部链接完整性
            if fpath.suffix.lower() in (".html", ".htm"):
                check_links(fpath, site_dir, rel, problems)

    print("=" * 60)
    print("BTED 站点产物验证")
    print(f"站点目录: {site_dir}")
    print(f"文件总数: {file_count}，总体积: {total_bytes} 字节")
    print("检查项: 必需文件 / GFF3 下载与 ZIP 内容 / 文件类型与体积 / 绝对路径 / 凭据 / 证据标签 / 内部链接")
    print("=" * 60)

    for w in warnings:
        print(f"WARN  {w}")
    if problems:
        for p in problems:
            print(f"FAIL  {p}")
        print(f"\n验证未通过：{len(problems)} 个问题。")
        return 1
    print("PASS  全部检查通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
