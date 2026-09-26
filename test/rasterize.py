#!/usr/bin/env python3
"""Rasterize apollomatrix draw-op traces into PNGs that simulate the 64x64 panel.

FAITHFUL, not flattering: text is drawn glyph-by-glyph from `fonts/metrics.json`,
which is ESPHome's own font output (FreeType advances/offsets + `bpp`-bit coverage
quantisation) exported by `export_font_metrics.py` and verified byte-for-byte
against a real device build. This script reproduces the device's rendering rules:

  * geometry: x1 = x - (width + x_offset)/2, y1 = y - height/2   (TextAlign::CENTER
    centres vertically too; `height` is the font line height)
  * one pen step per glyph advance; ink at (pen + offset_x, y1 + offset_y)
  * coverage 0 -> nothing drawn, coverage == bpp_max -> the text colour, anything
    between -> colour * (coverage/bpp_max), truncated, blended against COLOR_OFF
    (black) - i.e. the device's own antialiasing, at its own bit depth
  * an unknown codepoint draws Font::print()'s filled rectangle (width = first
    glyph's advance, height = the font height)

Consequence: Silkscreen renders hard-edged (its bitmaps contain no partial pixels)
while the Roboto temperature is antialiased at 4 levels - exactly what the panel
does.

The geometry and colours come from the compiled C++ (test/matrix_logic.h), not from
this script.

Outputs:
  <out_dir>/<name>.png          one 8x-zoomed image per scenario (+ caption strip)
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
                v = vals[gy * gi["width"] + gx]
                if v == 0:
                    continue               # nothing drawn: background shows through
                px = pen + gi["offset_x"] + gx
                py = y1 + gi["offset_y"] + gy
                if v == font.bpp_max:
                    put(img, px, py, color)
                else:
                    # blend against COLOR_OFF (0,0,0), truncated to uint8, as the firmware does
                    on = v / font.bpp_max
                    put(img, px, py, tuple(int(c * on) for c in color))
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


def caption_font(size: int):
    try:
        return ImageFont.truetype(str(CAPTION_FONT_PATH), size)
    except Exception:
        return ImageFont.load_default()


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


def build_contact_sheet(items: list[tuple[dict, Image.Image]]) -> Image.Image:
    cols = 4
    rows = (len(items) + cols - 1) // cols
    tile_w = PANEL_W * SHEET_ZOOM + 2 + 16
    tile_h = PANEL_H * SHEET_ZOOM + 2 + 44
    sheet = Image.new("RGB", (cols * tile_w, rows * tile_h), BG)
    d = ImageDraw.Draw(sheet)
    f = caption_font(10)

    for i, (trace, panel) in enumerate(items):
        cx, cy = (i % cols) * tile_w, (i // cols) * tile_h
        big = panel.resize((PANEL_W * SHEET_ZOOM, PANEL_H * SHEET_ZOOM), Image.NEAREST)
        border = Image.new("RGB", (big.width + 2, big.height + 2), (60, 60, 70))
        border.paste(big, (1, 1))
        sheet.paste(border, (cx + 8, cy + 8))
        d.text((cx + 8, cy + big.height + 12), trace.get("name", "?")[:40],
               font=f, fill=OK if trace.get("pass") else BAD)
        d.text((cx + 8, cy + big.height + 26),
               "display on" if trace.get("display_active") else "display off", font=f, fill=DIM)
    return sheet


def main() -> int:
    traces_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "output/traces")
    out_dir = Path(sys.argv[2] if len(sys.argv) > 2 else "output/png")
    out_dir.mkdir(parents=True, exist_ok=True)

    global CAPTION_FONT_PATH
    fonts_dir = Path(__file__).resolve().parent / "fonts"
    CAPTION_FONT_PATH = fonts_dir / CAPTION_FONT

    files = sorted(traces_dir.glob("*.json"))
    if not files:
        print(f"no traces found in {traces_dir} - run render_scenarios first")
        return 1

    fonts = load_device_fonts(fonts_dir)
    print("device fonts: " + ", ".join(
        f"{k}={v.id} (bpp {v.bpp}, height {v.height}, {len(v.table)} glyphs)"
        for k, v in sorted(fonts.items())))

    items = []
    for path in files:
        trace = json.loads(path.read_text(encoding="utf-8"))
        panel = render_panel(trace, fonts)
        with_caption(panel, trace, ZOOM).save(out_dir / f"{path.stem}.png")
        items.append((trace, panel))

    build_contact_sheet(items).save(out_dir / "_contact_sheet.png")

    failed = [t["name"] for t, _ in items if not t.get("pass")]
    print(f"rendered {len(items)} scenario image(s) -> {out_dir}")
    print(f"contact sheet      -> {out_dir / '_contact_sheet.png'}")
    if failed:
        print(f"FAILING scenarios: {', '.join(failed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
