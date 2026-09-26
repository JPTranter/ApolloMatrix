#!/usr/bin/env python3
"""Copy a few harness renders into docs/images/ for the README to embed.

The renders themselves are generated output (test/output/images/, git-ignored), so
these are snapshots that need refreshing when the look changes:

    test/run_tests.sh                 # regenerate the renders
    python test/make_readme_images.py # refresh docs/images/

The `device` picks show how the panel appears; the `crisp` pick is the faithful
pixel grid the panel actually receives.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "test" / "output" / "images"
DST = REPO / "docs" / "images"

# source render -> README image name
PICKS = {
    "device_00_window_occupied_10am.png": "device-normal.png",
    "device_17_full_brightness.png": "device-full-brightness.png",
    "device_14_trend_up.png": "device-trend-up.png",
    "device_12_temp_hot_red.png": "device-temp-hot.png",
    "device_01_window_vacant_1400.png": "device-panel-off.png",
    "crisp_00_window_occupied_10am.png": "crisp-normal.png",
}


def main() -> int:
    if not SRC.exists():
        print(f"{SRC} not found - run test/run_tests.sh first")
        return 1
    DST.mkdir(parents=True, exist_ok=True)

    copied = 0
    for src_name, dst_name in PICKS.items():
        src = SRC / src_name
        if not src.exists():
            print(f"  MISSING {src_name} (scenario renamed?) - skipped")
            continue
        shutil.copy2(src, DST / dst_name)
        print(f"  {src_name} -> docs/images/{dst_name}")
        copied += 1

    print(f"\ncopied {copied}/{len(PICKS)} image(s) to {DST}")
    return 0 if copied == len(PICKS) else 1


if __name__ == "__main__":
    sys.exit(main())
