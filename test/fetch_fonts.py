#!/usr/bin/env python3
"""Fetch the two fonts the previews use into test/fonts/.

These fonts are deliberately NOT committed to this repository (they are third-party
font software - see test/fonts/NOTICE.txt). Nothing in the firmware path needs them:
the config uses `gfonts://Silkscreen` / `gfonts://Roboto` and ESPHome fetches them on
the build host. They are only read by:

  * test/rasterize.py          - the caption chrome around each render
  * test/export_font_metrics.py - regenerating the committed glyph fixtures

Rendering still works without them (the glyph fixtures `metrics.json` are committed and
the caption font falls back to PIL's default); only re-exporting needs a real TTF.

    python test/fetch_fonts.py                 # copy from an ESPHome font cache (best)
    python test/fetch_fonts.py --via-esphome   # run ESPHome to download them, then copy
    python test/fetch_fonts.py --download      # HTTPS from Google Fonts (no ESPHome)
    python test/fetch_fonts.py --cache PATH    # use a specific .esphome/font directory

The cache route is preferred because it is **byte-identical to what the firmware
embeds** - which is what you want if you are re-exporting the glyph fixtures. The
`--download` route pulls the upstream releases instead: Silkscreen is a static font
there, but Roboto ships as a variable font, so its metrics can differ slightly from the
firmware's static 400 instance. Fine for captions, not for regenerating fixtures.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DST = Path(__file__).resolve().parent / "fonts"

# family -> the filename the harness expects
TARGETS = {
    "Silkscreen": "Silkscreen-Regular.ttf",
    "Roboto": "Roboto-Regular.ttf",
}

DOWNLOADS = {
    "Silkscreen-Regular.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/silkscreen/Silkscreen-Regular.ttf",
    # upstream Roboto is a variable font (no static release in the Google Fonts repo)
    "Roboto-Regular.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/roboto/Roboto%5Bwdth%2Cwght%5D.ttf",
}

DUMMY_SECRETS = 'wifi_ssid: "DUMMY_SSID"\nwifi_password: "DUMMY_PASSWORD"\n'


def have() -> list[str]:
    return [n for n in TARGETS.values() if (DST / n).exists()]


def find_cache(explicit: str | None, config_dir: str | None) -> Path | None:
    """Where ESPHome keeps gfonts:// downloads: <config-dir>/.esphome/font/."""
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    if config_dir:
        candidates.append(Path(config_dir) / ".esphome" / "font")
    candidates.append(REPO / ".esphome" / "font")
    for c in candidates:
        if c.is_dir() and any(c.iterdir()):
            return c
    return None


def copy_from_cache(cache: Path) -> int:
    """ESPHome names them '<Family>@<weight>@<hash>.ttf'."""
    copied = 0
    for family, target_name in TARGETS.items():
        matches = sorted(cache.glob(f"{family}@*.ttf")) or sorted(cache.glob(f"{family}*.ttf"))
        if not matches:
            print(f"  {family}: not found in {cache}")
            continue
        shutil.copy2(matches[0], DST / target_name)
        print(f"  {family}: {matches[0].name} -> {target_name}")
        copied += 1
    return copied


def run_esphome() -> int:
    """Build a throwaway ESPHome cache, copy the fonts into place, clean up after."""
    tmp = Path(tempfile.mkdtemp(prefix="ApolloMatrix-fonts-"))
    try:
        shutil.copy2(REPO / "ApolloMatrix.yaml", tmp / "ApolloMatrix.yaml")
        (tmp / "secrets.yaml").write_text(DUMMY_SECRETS, encoding="utf-8")
        print(f"  running `esphome config` in {tmp} to fetch the fonts ...")
        proc = subprocess.run(
            [sys.executable, "-m", "esphome", "config", "ApolloMatrix.yaml"],
            cwd=tmp,
            capture_output=True,
            text=True,
        )
        cache = tmp / ".esphome" / "font"
        if cache.is_dir() and any(cache.iterdir()):
            print(
                f"  fonts downloaded (esphome exited {proc.returncode}; "
                f"a config error after the download is harmless)"
            )
            return copy_from_cache(cache)
        print("  esphome did not produce a font cache")
        if proc.returncode != 0:
            for line in (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]:
                print(f"    | {line}")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def download() -> int:
    copied = 0
    for target_name, url in DOWNLOADS.items():
        print(f"  {target_name}: {url}")
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                data = r.read()
        except (urllib.error.URLError, OSError) as exc:
            print(f"    FAILED: {exc}")
            continue
        (DST / target_name).write_bytes(data)
        print(f"    -> {target_name} ({len(data) // 1024} KB)")
        copied += 1
    if copied:
        print("\n  NOTE: upstream Roboto is a variable font, so this copy's metrics can")
        print("  differ slightly from the firmware's. Use the cache route if you intend")
        print("  to re-export test/fonts/metrics.json.")
    return copied


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cache", help="an ESPHome font cache dir (.esphome/font)")
    ap.add_argument("--config-dir", help="an ESPHome config dir containing .esphome/font")
    ap.add_argument(
        "--via-esphome", action="store_true", help="run ESPHome locally to download the fonts first"
    )
    ap.add_argument(
        "--download", action="store_true", help="fetch the upstream releases over HTTPS instead"
    )
    args = ap.parse_args()

    DST.mkdir(parents=True, exist_ok=True)

    present = have()
    if present and not (args.via_esphome or args.download):
        print(f"already present in test/fonts/: {', '.join(present)}")
        missing = [n for n in TARGETS.values() if n not in present]
        if not missing:
            return 0
        print(f"still missing: {', '.join(missing)}")

    print("fetching fonts ...")
    copied = 0

    if args.download:
        copied = download()
    else:
        cache = find_cache(args.cache, args.config_dir)
        if cache is not None:
            print(f"  using ESPHome font cache: {cache}")
            copied = copy_from_cache(cache)
        elif args.via_esphome:
            copied = run_esphome()

    if copied == len(TARGETS):
        print(f"\ndone - {DST}")
        return 0

    print(f"\nGot {copied} of {len(TARGETS)}. Options:")
    print("  1. easiest, no ESPHome needed:   python test/fetch_fonts.py --download")
    print("  2. highest fidelity (matches the firmware), needs esphome:")
    print("       python test/fetch_fonts.py --via-esphome")
    print("  3. from your Home Assistant / ESPHome host, the add-on keeps them in")
    print("       /config/esphome/.esphome/font/        (Silkscreen@*.ttf, Roboto@*.ttf)")
    print("     copy those two into test/fonts/ as Silkscreen-Regular.ttf and")
    print("     Roboto-Regular.ttf.")
    print("\nRendering works without them - only re-exporting metrics.json needs a TTF.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
