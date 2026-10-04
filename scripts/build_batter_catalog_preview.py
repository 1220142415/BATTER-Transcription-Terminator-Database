#!/usr/bin/env python3
"""Build the small BATTER catalogue shell into a local Worker asset directory."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PILOT_SITE = ROOT / "dist/batter-tes-pilot/site"
PILOT_CATALOG = PILOT_SITE / "pilot_catalog.json"
sys.path.insert(0, str(ROOT / "scripts"))
import build_v0_4_site  # noqa: E402


def build(output_dir: Path) -> Path:
    target = output_dir.resolve()
    try:
        target.relative_to((ROOT / "dist").resolve())
    except ValueError as exc:
        raise ValueError("Output directory must stay inside the ignored dist/ preview area") from exc
    if target == (ROOT / "dist").resolve():
        raise ValueError("Choose a subdirectory of dist/ for the preview output")
    target.mkdir(parents=True, exist_ok=True)
    for relative in (
        "css/style.css",
        "css/batter-catalog.css",
        "assets/favicon.svg",
        "assets/batter-catalog.js",
    ):
        source = ROOT / "site" / relative
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    if PILOT_CATALOG.is_file():
        pilot_rows = json.loads(PILOT_CATALOG.read_text(encoding="utf-8"))
        pilot_ids = {str(row.get("genome_id", "")) for row in pilot_rows if row.get("genome_id")}
        if len(pilot_rows) != 100 or len(pilot_ids) != 100:
            raise ValueError(f"Expected 100 unique BATTER pilot genome IDs in {PILOT_CATALOG}")
        for genome_id in pilot_ids:
            config = PILOT_SITE / "jbrowse" / "assemblies" / f"BATTER_TES_{genome_id}.config.json"
            if not config.is_file():
                raise ValueError(f"Pilot browser config is missing for {genome_id}: {config}")
        shutil.copyfile(PILOT_CATALOG, target / "assets" / "batter-preview-catalog.json")
    build_v0_4_site.write_batter_catalog_page(target)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist/worker-site")
    args = parser.parse_args()
    try:
        output = build(args.output_dir)
    except (OSError, ValueError) as exc:
        print(f"FAIL  {exc}", file=sys.stderr)
        return 1
    print(f"PASS  Unified genome catalogue shell written to {output / 'batter-genomes.html'}")
    print(f"PASS  Local BATTER browser manifest {'copied' if (output / 'assets' / 'batter-preview-catalog.json').is_file() else 'not available'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
