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

from PIL import Image

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

# Animated hero: the panel cycling through its most distinct states. Cropped to the
# panel itself (the renders carry a caption strip below it, which would just look like
# test output in a README), downscaled, and quantised to keep the file reasonable.
GIF_NAME = "device-states.gif"
GIF_FRAMES = [
    "device_00_window_occupied_10am.png",   # everyday, brightness 0.2
    "device_17_full_brightness.png",        # brightness 1.0
    "device_14_trend_up.png",               # trend arrow
    "device_12_temp_hot_red.png",           # 32 C, red end of the ramp
    "device_01_window_vacant_1400.png",     # blanked
]
GIF_PX = 420
GIF_FRAME_MS = 1200
GIF_COLORS = 128


def build_gif() -> int:
    frames = []
    for name in GIF_FRAMES:
        src = SRC / name
        if not src.exists():
            print(f"  MISSING {name} (scenario renamed?) - no GIF written")
            return 0
        im = Image.open(src).convert("RGB")
        # the panel is drawn at 8px padding with a 1px border, 64 LEDs x 16px cells
        panel = im.crop((7, 7, 7 + 64 * 16 + 2, 7 + 64 * 16 + 2))
        frames.append(panel.resize((GIF_PX, GIF_PX), Image.LANCZOS)
                      .convert("P", palette=Image.ADAPTIVE, colors=GIF_COLORS))

    out = DST / GIF_NAME
    frames[0].save(out, save_all=True, append_images=frames[1:],
                   duration=GIF_FRAME_MS, loop=0, optimize=True)
    print(f"  -> docs/images/{GIF_NAME} "
          f"({out.stat().st_size // 1024} KB, {len(frames)} frames)")
    return 1


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

    made_gif = build_gif()

    print(f"\ncopied {copied}/{len(PICKS)} image(s) to {DST}, "
          f"animated hero: {'written' if made_gif else 'not written'}")
    return 0 if (copied == len(PICKS) and made_gif) else 1


if __name__ == "__main__":
    sys.exit(main())
