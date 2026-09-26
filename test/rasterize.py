#!/usr/bin/env python3
"""Rasterize apollomatrix draw-op traces into PNGs that simulate the 64x64 panel.

FAITHFUL, not flattering: text is drawn glyph-by-glyph from `fonts/metrics.json`,
which is ESPHome's own font output (FreeType advances/offsets + `bpp`-bit coverage
quantisation) exported by `export_font_metrics.py` and verified byte-for-byte
against a real device build. This script reproduces the device's rendering rules:

  * geometry: x1 = x - (width + x_offset)/2, y1 = y - height/2   (TextAlign::CENTER
    centres vertically too; `height` is the font line height)
  * one pen step per glyph advance; ink at (pen + offset_x, y1 + offset_y)
  * every pixel with coverage > 0 is drawn at the FULL text colour. ESPHome's
    Font::print() blends partial coverage, but the panel does not show it - all
    inked pixels render at the same brightness (measured from a photo of the
    device; see README "Rendering fidelity" and lesson 19). `bpp` therefore only
    decides WHICH pixels are inked, not how bright they are.
  * an unknown codepoint draws Font::print()'s filled rectangle (width = first
    glyph's advance, height = the font height)

Consequence: Silkscreen and the Roboto temperature both render hard-edged / binary,
matching the panel.

The geometry and colours come from the compiled C++ (test/matrix_logic.h), not from
this script.

Outputs (all in one directory, prefixed by style):
  <out_dir>/crisp_<name>.png        faithful 64x64 pixel grid, 8x zoom (+ caption)
  <out_dir>/device_<name>.png       LED-panel look
  <out_dir>/crisp_contact_sheet.png all crisp scenarios in one grid
  <out_dir>/device_contact_sheet.png
Default out_dir is output/images.

Usage: rasterize.py [traces_dir] [out_dir] [--style crisp|device]
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

# Trace font name (test/matrix_logic.h Font enum) -> metrics.json font id
TRACE_FONT_ID = {"small": "weather_font", "large": "weather_font_l"}

CAPTION_FONT = "Silkscreen-Regular.ttf"   # only used for the annotation chrome
CAPTION_FONT_PATH: Path | None = None


class DeviceFont:
    """A font exactly as the firmware has it."""

    def __init__(self, spec: dict):
        self.id = spec["id"]
        self.bpp = spec["bpp"]
        self.bpp_max = (1 << self.bpp) - 1
        self.height = spec["height"]        # Font(..., height, ...) = line height
        self.baseline = spec["baseline"]
        self.table = {int(k): v for k, v in spec["glyphs"].items()}
        first = self.table[min(self.table)]  # glyphs_[] is sorted by codepoint
        self.first_advance = first["advance"]
        self._bitmaps: dict[int, list[int]] = {}

    def coverage(self, cp: int) -> list[int] | None:
        gi = self.table.get(cp)
        if gi is None:
            return None
        if cp not in self._bitmaps:
            self._bitmaps[cp] = unpack(gi["bitmap"], gi["width"], gi["height"], self.bpp)
        return self._bitmaps[cp]

    def measure(self, text: str) -> tuple[int, int]:
        """ESPHome Font::measure() -> (width, x_offset)."""
        min_x, has_char, x = 0, False, 0
        for ch in text:
            gi = self.table.get(ord(ch))
            if gi is None:
                x += self.first_advance    # unknown char: advance like glyphs_[0]
                continue
            if not has_char:
                min_x = gi["offset_x"]
            else:
                min_x = min(min_x, x + gi["offset_x"])
            x += gi["advance"]
            has_char = True
        return x - min_x, min_x


def unpack(packed_hex: str, w: int, h: int, bpp: int) -> list[int]:
    """Same MSB-first, bpp-bits-per-pixel unpacking as Font::print()."""
    packed = bytes.fromhex(packed_hex)
    vals, bitpos = [], 0
    for _ in range(w * h):
        v = 0
        for _ in range(bpp):
            v = (v << 1) | ((packed[bitpos // 8] >> (7 - (bitpos % 8))) & 1)
            bitpos += 1
        vals.append(v)
    return vals


def load_device_fonts(fonts_dir: Path) -> dict[str, DeviceFont]:
    path = fonts_dir / "metrics.json"
    if not path.exists():
        raise SystemExit(
            f"{path} is missing - generate it with:\n"
            f"    python test/export_font_metrics.py\n"
            f"(needs esphome + freetype-py; it is committed, so this should be rare)"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    by_id = {f["id"]: DeviceFont(f) for f in data["fonts"]}
    return {trace: by_id[font_id] for trace, font_id in TRACE_FONT_ID.items() if font_id in by_id}


def put(img: Image.Image, x: int, y: int, color: tuple[int, int, int]) -> None:
    if 0 <= x < img.width and 0 <= y < img.height:
        img.putpixel((x, y), color)


def draw_device_text(img: Image.Image, font: DeviceFont, text: str, x: int, y: int,
                     align: str, color: tuple[int, int, int]) -> None:
    width, x_off = font.measure(text)
    if align == "center":
        x1 = x - (width + x_off) // 2
        y1 = y - font.height // 2
    else:
        x1, y1 = x, y

    pen = x1
    for ch in text:
        cp = ord(ch)
        gi = font.table.get(cp)
        if gi is None:
            # Font::print(): unknown glyph -> filled rectangle in the text colour
            for gy in range(font.height):
                for gx in range(font.first_advance):
                    put(img, pen + gx, y1 + gy, color)
            pen += font.first_advance
            continue

        vals = font.coverage(cp)
        for gy in range(gi["height"]):
            for gx in range(gi["width"]):
                if vals[gy * gi["width"] + gx] == 0:
                    continue               # nothing drawn: background shows through
                # ESPHome's Font::print() computes a blended colour for partial
                # coverage, but the panel does NOT show it: every inked pixel renders
                # at the same brightness. Measured from a photo of the device - see
                # "Rendering fidelity" in the README and lesson 19. So any non-zero
                # coverage is drawn at the full colour, and bpp only decides *which*
                # pixels are inked.
                put(img, pen + gi["offset_x"] + gx, y1 + gi["offset_y"] + gy, color)
        pen += gi["advance"]


def render_panel(trace: dict, fonts: dict[str, DeviceFont]) -> Image.Image:
    """Paint the trace's ops into a 64x64 RGB image the way the display would."""
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
            draw.rectangle([0, 0, w - 1, h - 1], fill=color)

        elif kind == "line":
            draw.line([int(op["x1"]), int(op["y1"]), int(op["x2"]), int(op["y2"])],
                      fill=color, width=1)

        elif kind == "pixel":
            put(img, int(op["x"]), int(op["y"]), color)

        elif kind == "text":
            font = fonts.get(op.get("font", "small"))
            if font is None:
                continue
            draw_device_text(img, font, op.get("text", ""), int(op["x"]), int(op["y"]),
                             op.get("align", "left"), color)

    return img


# --- device look -------------------------------------------------------------
# PRESENTATION ONLY. Renders the 64x64 logical frame the way the physical LED
# matrix appears in a photo: round LEDs on a dark mask, faint unlit packages, a
# glow halo on lit ones. The crisp renderer above stays the faithful one - see
# README "Rendering fidelity" and lesson 19.
DEVICE_CELL = 16        # px per LED in the device-style output
DEVICE_EXPOSURE = 2.2   # gain on the LEDs' emitted light (1.0 = the true brightness)
PANEL_BG = (6, 6, 8)    # the mask between LEDs
UNLIT_LEVEL = 7         # faint dots the unlit packages catch (lower = more contrast)
CORE_RADIUS = 0.30      # LED die radius, in cell units
GLOW_SIGMA = 0.52
GLOW_GAIN = 0.32
# Deliberately uniform: no per-LED brightness spread and no vignette, so every LED
# of the same colour renders identically.


def device_look(panel: Image.Image, cell: int = DEVICE_CELL,
                exposure: float = DEVICE_EXPOSURE) -> Image.Image:
    import numpy as np

    n = panel.width
    size = n * cell
    led_grid = np.asarray(panel.convert("RGB"), dtype=np.float32)

    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    fx = (xx + 0.5) / cell - 0.5          # LED-centre coordinates (centre = integer)
    fy = (yy + 0.5) / cell - 0.5
    cj = np.clip(np.floor(fx + 0.5).astype(np.int32), 0, n - 1)
    ci = np.clip(np.floor(fy + 0.5).astype(np.int32), 0, n - 1)
    r = np.hypot(fx - cj, fy - ci)        # distance from the LED centre, in cell units

    led = led_grid[ci, cj]                # the LED colour behind every pixel
    lit = led.max(axis=2) > 0.5

    out = np.empty((size, size, 3), np.float32)
    out[:] = PANEL_BG

    # unlit packages: faint round dots, visible on the real panel.
    # NB: these and the mask are NOT scaled by `exposure` - exposure models the
    # camera's gain on emitted light, so scaling the background with it would lift
    # the whole panel to grey.
    dot = np.clip(1.0 - (r / 0.30) ** 2, 0.0, 1.0)
    out += (~lit)[..., None] * dot[..., None] * UNLIT_LEVEL

    # lit LEDs: a bright die with a soft halo
    core = np.clip(1.0 - (r / CORE_RADIUS) ** 4, 0.0, 1.0)
    halo = np.exp(-(r / GLOW_SIGMA) ** 2)
    out += lit[..., None] * led * exposure * (core + GLOW_GAIN * halo)[..., None]

    return Image.fromarray(np.clip(out, 0.0, 255.0).astype(np.uint8))


def caption_font(size: int):
    try:
        return ImageFont.truetype(str(CAPTION_FONT_PATH), size)
    except Exception:
        return ImageFont.load_default()


def caption_lines(trace: dict) -> list[str]:
    return [
        f"{trace.get('name', '?')}   {'PASS' if trace.get('pass') else 'FAIL'}",
        f"display {'on' if trace.get('display_active') else 'off'}",
    ]


def with_caption(panel: Image.Image, trace: dict, zoom: int) -> Image.Image:
    big = panel.resize((panel.width * zoom, panel.height * zoom), Image.NEAREST)
    # 1px border so the panel extent is visible even when fully black
    bordered = Image.new("RGB", (big.width + 2, big.height + 2), (60, 60, 70))
    bordered.paste(big, (1, 1))

    pad, line_h = 8, 15
    lines = caption_lines(trace)
    out = Image.new("RGB",
                    (bordered.width + pad * 2, bordered.height + pad * 2 + line_h * len(lines)),
                    BG)
    out.paste(bordered, (pad, pad))

    d = ImageDraw.Draw(out)
    f = caption_font(9)
    for i, text in enumerate(lines):
        col = (OK if trace.get("pass") else BAD) if i == 0 else DIM
        d.text((pad, bordered.height + pad + i * line_h), text, font=f, fill=col)
    return out


def build_contact_sheet(items: list[tuple[dict, Image.Image]],
                        tile_zoom: int = SHEET_ZOOM) -> Image.Image:
    cols = 4
    rows = (len(items) + cols - 1) // cols
    if not items:
        return Image.new("RGB", (16, 16), BG)
    w0, h0 = items[0][1].width * tile_zoom, items[0][1].height * tile_zoom
    tile_w = w0 + 2 + 16
    tile_h = h0 + 2 + 44
    sheet = Image.new("RGB", (cols * tile_w, rows * tile_h), BG)
    d = ImageDraw.Draw(sheet)
    f = caption_font(10)

    for i, (trace, panel) in enumerate(items):
        cx, cy = (i % cols) * tile_w, (i // cols) * tile_h
        big = panel.resize((panel.width * tile_zoom, panel.height * tile_zoom), Image.NEAREST)
        border = Image.new("RGB", (big.width + 2, big.height + 2), (60, 60, 70))
        border.paste(big, (1, 1))
        sheet.paste(border, (cx + 8, cy + 8))
        d.text((cx + 8, cy + big.height + 12), trace.get("name", "?")[:40],
               font=f, fill=OK if trace.get("pass") else BAD)
        d.text((cx + 8, cy + big.height + 26),
               "display on" if trace.get("display_active") else "display off", font=f, fill=DIM)
    return sheet


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Rasterize apollomatrix draw-op traces to PNG")
    ap.add_argument("traces_dir", nargs="?", default="output/traces")
    ap.add_argument("out_dir", nargs="?", default=None)
    ap.add_argument("--style", choices=("crisp", "device"), default="crisp",
                    help="crisp = faithful pixel grid (default); device = LED look")
    ap.add_argument("--cell", type=int, default=DEVICE_CELL,
                    help="pixels per LED for --style device")
    ap.add_argument("--exposure", type=float, default=DEVICE_EXPOSURE,
                    help="gain for --style device (1.0 = the true brightness)")
    args = ap.parse_args()

    traces_dir = Path(args.traces_dir)
    out_dir = Path(args.out_dir or "output/images")
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = args.style + "_"

    global CAPTION_FONT_PATH
    fonts_dir = Path(__file__).resolve().parent / "fonts"
    CAPTION_FONT_PATH = fonts_dir / CAPTION_FONT

    files = sorted(traces_dir.glob("*.json"))
    if not files:
        print(f"no traces found in {traces_dir} - run render_scenarios first")
        return 1

    fonts = load_device_fonts(fonts_dir)
    print(f"style: {args.style}   device fonts: " + ", ".join(
        f"{k}={v.id} (bpp {v.bpp}, height {v.height}, {len(v.table)} glyphs)"
        for k, v in sorted(fonts.items())))

    device = args.style == "device"
    sheet_cell = max(4, args.cell // 3)

    items = []
    for path in files:
        trace = json.loads(path.read_text(encoding="utf-8"))
        panel = render_panel(trace, fonts)
        shown = device_look(panel, cell=args.cell, exposure=args.exposure) if device else panel
        with_caption(shown, trace, 1 if device else ZOOM).save(out_dir / f"{prefix}{path.stem}.png")
        items.append((trace, device_look(panel, cell=sheet_cell, exposure=args.exposure)
                      if device else panel))

    build_contact_sheet(items, tile_zoom=1 if device else SHEET_ZOOM).save(
        out_dir / f"{prefix}contact_sheet.png")

    failed = [t["name"] for t, _ in items if not t.get("pass")]
    print(f"rendered {len(items)} {args.style} image(s) -> {out_dir}")
    print(f"contact sheet      -> {out_dir / f'{prefix}contact_sheet.png'}")
    if failed:
        print(f"FAILING scenarios: {', '.join(failed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
