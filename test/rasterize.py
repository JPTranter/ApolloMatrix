#!/usr/bin/env python3
"""Rasterize apollomatrix draw-op traces into PNGs that simulate the 64x64 panel.

Reads the JSON traces written by `render_scenarios` and paints them with the REAL
Silkscreen / Roboto fonts that the device uses (test/fonts/), so text widths and
line positions are representative of the panel. The geometry and colours in the
trace come from the compiled C++ (test/matrix_logic.h), not from this script.

Outputs:
  <out_dir>/<name>.png        one 8x-zoomed image per scenario (+ caption strip)
  <out_dir>/_contact_sheet.png  all scenarios in one grid for quick review

Usage: rasterize.py [traces_dir] [out_dir]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PANEL_W, PANEL_H = 64, 64
ZOOM = 8          # individual images
SHEET_ZOOM = 4    # contact-sheet tiles
BG = (12, 12, 16)
FG = (235, 235, 240)
DIM = (140, 140, 150)
OK = (120, 220, 140)
BAD = (235, 110, 110)

FONT_SMALL = "Silkscreen-Regular.ttf"   # device: gfonts://Silkscreen, size 8
FONT_LARGE = "Roboto-Regular.ttf"       # device: gfonts://Roboto, size 14


def load_fonts(font_dir: Path):
    small = ImageFont.truetype(str(font_dir / FONT_SMALL), 8)
    large = ImageFont.truetype(str(font_dir / FONT_LARGE), 14)
    return small, large


def clamp(v: int, lo: int, hi: int) -> int:
    return lo if v < lo else hi if v > hi else v


def render_panel(trace: dict, font_small, font_large) -> Image.Image:
    """Paint the trace's ops into a 64x64 RGB image."""
    panel = trace.get("panel", {})
    bg = tuple(panel.get("bg", [0, 0, 0]))
    w = int(panel.get("width", PANEL_W))
    h = int(panel.get("height", PANEL_H))

    img = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(img)

    for op in trace.get("ops", []):
        kind = op.get("kind")
        color = tuple(op.get("color", [0, 0, 0]))

        if kind == "fill":
            # background fill (the lambda clears to black each frame)
            draw.rectangle([0, 0, w - 1, h - 1], fill=color)

        elif kind == "line":
            draw.line(
                [int(op["x1"]), int(op["y1"]), int(op["x2"]), int(op["y2"])],
                fill=color,
                width=1,
            )

        elif kind == "pixel":
            x, y = int(op["x"]), int(op["y"])
            if 0 <= x < w and 0 <= y < h:
                draw.point((x, y), fill=color)

        elif kind == "text":
            x, y = int(op["x"]), int(op["y"])
            font = font_large if op.get("font") == "large" else font_small
            # ESPHome TextAlign::CENTER is CENTER_VERTICAL | CENTER_HORIZONTAL, and
            # Display::get_text_bounds() computes the box top-left as
            #   x1 = x - (width + x_offset) / 2
            #   y1 = y - height / 2          (height = top of text -> bottom)
            # so `y` is the vertical centre of the line, not its top. Mirror that:
            # measure with PIL, then draw with the ascender-top anchored at (x1, y1).
            if op.get("align") == "center":
                ascent, descent = font.getmetrics()
                height = ascent + descent
                width = int(round(font.getlength(op.get("text", ""))))
                x1 = x - width // 2
                y1 = y - height // 2
            else:
                x1, y1 = x, y
            draw.text((x1, y1), op.get("text", ""), font=font, fill=color, anchor="la")

    return img


def caption_lines(trace: dict) -> list[str]:
    led = trace.get("status_led", {})
    led_txt = f"LED {led.get('state', '?')}"
    if led.get("state") == "on":
        r, g, b = led.get("color", [0, 0, 0])
        led_txt += f" rgb({r},{g},{b}) bri {led.get('brightness', 0):.2f}"
    return [
        f"{trace.get('name', '?')}   {'PASS' if trace.get('pass') else 'FAIL'}",
        f"display {'on' if trace.get('display_active') else 'off'}   {led_txt}",
    ]


def with_caption(panel: Image.Image, trace: dict, zoom: int) -> Image.Image:
    big = panel.resize((panel.width * zoom, panel.height * zoom), Image.NEAREST)
    # 1px border so panel extent is visible even when fully black
    bordered = Image.new("RGB", (big.width + 2, big.height + 2), (60, 60, 70))
    bordered.paste(big, (1, 1))

    pad, line_h = 8, 15
    lines = caption_lines(trace)
    cap_h = pad * 2 + line_h * len(lines)
    out = Image.new("RGB", (bordered.width + pad * 2, bordered.height + cap_h), BG)
    out.paste(bordered, (pad, pad))

    d = ImageDraw.Draw(out)
    try:
        f = ImageFont.truetype(str(FONT_SMALL_PATH), 9)
    except Exception:
        f = ImageFont.load_default()
    for i, text in enumerate(lines):
        col = FG if i == 0 else DIM
        if i == 0:
            col = OK if trace.get("pass") else BAD
        d.text((pad, bordered.height + pad + i * line_h), text, font=f, fill=col)
    return out


def build_contact_sheet(items: list[tuple[dict, Image.Image]], font_small, font_large) -> Image.Image:
    cols = 4
    rows = (len(items) + cols - 1) // cols
    tile_w = PANEL_W * SHEET_ZOOM + 2 + 16
    tile_h = PANEL_H * SHEET_ZOOM + 2 + 44
    sheet = Image.new("RGB", (cols * tile_w, rows * tile_h), BG)
    d = ImageDraw.Draw(sheet)
    try:
        f = ImageFont.truetype(str(FONT_SMALL_PATH), 10)
    except Exception:
        f = ImageFont.load_default()

    for i, (trace, panel) in enumerate(items):
        cx, cy = (i % cols) * tile_w, (i // cols) * tile_h
        big = panel.resize((PANEL_W * SHEET_ZOOM, PANEL_H * SHEET_ZOOM), Image.NEAREST)
        border = Image.new("RGB", (big.width + 2, big.height + 2), (60, 60, 70))
        border.paste(big, (1, 1))
        sheet.paste(border, (cx + 8, cy + 8))
        col = OK if trace.get("pass") else BAD
        label = trace.get("name", "?")
        d.text((cx + 8, cy + big.height + 12), label[:40], font=f, fill=col)
        state = "display on" if trace.get("display_active") else "display off"
        d.text((cx + 8, cy + big.height + 26), state, font=f, fill=DIM)
    return sheet


def main() -> int:
    traces_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "output/traces")
    out_dir = Path(sys.argv[2] if len(sys.argv) > 2 else "output/png")
    out_dir.mkdir(parents=True, exist_ok=True)

    global FONT_SMALL_PATH
    FONT_SMALL_PATH = Path(__file__).resolve().parent / "fonts" / FONT_SMALL

    files = sorted(traces_dir.glob("*.json"))
    if not files:
        print(f"no traces found in {traces_dir} - run render_scenarios first")
        return 1

    font_small, font_large = load_fonts(Path(__file__).resolve().parent / "fonts")

    items = []
    for path in files:
        trace = json.loads(path.read_text(encoding="utf-8"))
        panel = render_panel(trace, font_small, font_large)
        with_caption(panel, trace, ZOOM).save(out_dir / f"{path.stem}.png")
        items.append((trace, panel))

    sheet = build_contact_sheet(items, font_small, font_large)
    sheet.save(out_dir / "_contact_sheet.png")

    failed = [t["name"] for t, _ in items if not t.get("pass")]
    print(f"rendered {len(items)} scenario image(s) -> {out_dir}")
    print(f"contact sheet      -> {out_dir / '_contact_sheet.png'}")
    if failed:
        print(f"FAILING scenarios: {', '.join(failed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
