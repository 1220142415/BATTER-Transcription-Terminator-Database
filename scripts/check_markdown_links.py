#!/usr/bin/env python3
"""Check local Markdown links in current maintainer documentation."""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {
    ".git", ".pages-preview", ".wrangler", "dist", "node_modules",
    "__pycache__", ".venv", "venv", "temp", "tmp",
}
LINK = re.compile(r"!?\[[^\]\n]+\]\((<[^>]+>|[^)]+)\)")


def markdown_files() -> list[Path]:
    found: list[Path] = []
    for parent, directories, files in os.walk(ROOT):
        directories[:] = [
            name for name in directories
            if name not in SKIP_DIRS
            and not (Path(parent) == ROOT and name.lower().startswith(("tmp", "temp")))
        ]
        found.extend(Path(parent) / name for name in files if name.endswith(".md"))
    return sorted(found)


def check_file(path: Path) -> list[str]:
    issues: list[str] = []
    in_fence = False
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for match in LINK.finditer(line):
            target = match.group(1).strip().strip("<>").split(" ", 1)[0]
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path or parsed.path.startswith("/"):
                continue
            resolved = path.parent / unquote(parsed.path)
            if not resolved.exists():
                issues.append(f"{path.relative_to(ROOT)}:{number}: {target}")
    return issues


def main() -> int:
    issues = [issue for path in markdown_files() for issue in check_file(path)]
    if issues:
        print("Broken local Markdown links:\n" + "\n".join(issues))
        return 1
    print("PASS: local Markdown links")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
