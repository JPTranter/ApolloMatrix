#!/usr/bin/env python3
"""Export ESPHome's exact font metrics + glyph bitmaps for the render harness.

Runs ESPHome's OWN glyph generation code (`esphome.components.font`,
FreeType-backed) over the `font:` blocks in apollomatrix.yaml, so the fixtures are
what the device firmware actually contains - coverage quantised to `bpp` bits,
FreeType's advances/offsets, and the same font-level metrics the `Font(...)`
constructor receives.

Requires esphome + freetype-py (both present in the interpreter that runs ESPHome):

    python test/export_font_metrics.py                 # write test/fonts/metrics.json
    python test/export_font_metrics.py --verify <path/to/generated/main.cpp>

--verify parses the glyph table and Font(...) args out of an actual ESPHome build
and asserts every advance/offset/dimension/bitmap matches. That is the check that
proves the harness renders what the device renders.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
YAML = REPO / "apollomatrix.yaml"
OUT = Path(__file__).resolve().parent / "fonts" / "metrics.json"

# Trace font names ("small"/"large", see test/matrix_logic.h Font enum) -> YAML font id
FONT_ID_FOR_TRACE_NAME = {"small": "weather_font", "large": "weather_font_l"}


def parse_yaml_fonts(text: str) -> list[dict]:
    """Pull the two / three font: entries out of apollomatrix.yaml."""
    m = re.search(r"^font:\n(.*?)(?=^\S)", text, re.M | re.S)
    if not m:
        raise SystemExit("no font: block found in apollomatrix.yaml")
    fonts, cur = [], None
    for line in m.group(1).splitlines():
        mm = re.match(r"\s*-\s*file:\s*['\"]?(.*?)['\"]?\s*$", line)
        if mm:
            cur = {"file": mm.group(1)}
            fonts.append(cur)
            continue
        if cur is None:
            continue
        for key in ("id", "size", "bpp", "glyphs"):
            km = re.match(rf"\s*{key}:\s*(.+?)\s*$", line)
            if km:
                val = km.group(1).strip().strip("'\"")
                if key in ("size", "bpp"):
                    cur[key] = int(val)
                else:
                    cur[key] = val
    for f in fonts:
        f.setdefault("bpp", 1)
        f["file"] = re.sub(r"^gfonts://", "", f["file"])
    return fonts


def font_file_for(name: str) -> Path:
    """gfonts://Silkscreen -> test/fonts/Silkscreen-Regular.ttf (vendored copy)."""
    return REPO / "test" / "fonts" / f"{name}-Regular.ttf"


def export(fonts: list[dict]) -> dict:
    from freetype import FT_LOAD_NO_BITMAP, FT_LOAD_RENDER
    from esphome.components.font import glyph_to_glyphinfo, pt_to_px

    out = {"fonts": []}
    for spec in fonts:
        path = font_file_for(spec["file"])
        if not path.exists():
            raise SystemExit(f"font file not found: {path}")

        import freetype
        face = freetype.Face(str(path))
        size, bpp = spec["size"], spec["bpp"]

        codepoints = sorted(ord(c) for c in spec["glyphs"])
        infos = {}
        for cp in codepoints:
            g = glyph_to_glyphinfo(chr(cp), face, size, bpp)
            infos[cp] = {
                "advance": g.advance,
                "offset_x": g.offset_x,
                "offset_y": g.offset_y,
                "width": g.width,
                "height": g.height,
                "bitmap": bytes(g.bitmap_data).hex(),
            }

        # Font-level metrics, exactly as esphome/components/font/__init__.py:605-611
        font_height = pt_to_px(face.size.height)
        ascender = pt_to_px(face.size.ascender)
        descender = abs(pt_to_px(face.size.descender))
        gx = glyph_to_glyphinfo("x", face, size, bpp)
        xheight = gx.height if len(gx.bitmap_data) > 1 else 0
        gX = glyph_to_glyphinfo("X", face, size, bpp)
        capheight = gX.height if len(gX.bitmap_data) > 1 else 0

        out["fonts"].append({
            "id": spec["id"],
            "trace_name": next((k for k, v in FONT_ID_FOR_TRACE_NAME.items() if v == spec["id"]), None),
            "source": spec["file"],
            "file": f"fonts/{path.name}",
            "size": size,
            "bpp": bpp,
            "baseline": ascender,      # Font(...) arg 3
            "height": font_height,     # Font(...) arg 4  (line height)
            "descender": descender,
            "xheight": xheight,
            "capheight": capheight,
            "glyphs": {str(k): v for k, v in sorted(infos.items())},
        })
        print(f"exported {spec['id']}: {len(infos)} glyphs, bpp={bpp}, size={size}, "
              f"baseline={ascender}, height={font_height}")
    return out


def unpack_bitmap(packed: bytes, w: int, h: int, bpp: int) -> list[int]:
    """Same MSB-first unpacking as Font::print()."""
    vals, bitpos = [], 0
    for _ in range(w * h):
        v = 0
        for _ in range(bpp):
            v = (v << 1) | ((packed[bitpos // 8] >> (7 - (bitpos % 8))) & 1)
            bitpos += 1
        vals.append(v)
    return vals


def verify(fixtures: dict, main_cpp: Path) -> int:
    text = main_cpp.read_text(encoding="utf-8", errors="replace")
    problems = []

    blobs = {}
    for m in re.finditer(r"static constexpr uint8_t (\w+)\[\] PROGMEM = \{(.*?)\};", text, re.S):
        blobs[m.group(1)] = bytes(int(b, 16) for b in re.findall(r"0x([0-9A-Fa-f]{2})", m.group(2)))

    for font in fixtures["fonts"]:
        # The generated name for the raw glyph array ("font_glyph_id" for id weather_font)
        arr = "font_glyph_" + ("id" if font["id"] == "weather_font" else "id_2")
        m = re.search(r"static const font::Glyph " + arr + r"\[\] = \{(.*?)\};", text, re.S)
        if not m:
            problems.append(f"{font['id']}: glyph table {arr} not found in {main_cpp.name}")
            continue
        blob_name = re.search(r"\((\w+)\s*\+\s*\d+\)", m.group(1)).group(1)
        blob = blobs[blob_name]

        device = {}
        for g in re.finditer(r"\{(\d+),\s*\(\w+\s*\+\s*(\d+)\),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+)\}", m.group(1)):
            cp, off, adv, ox, oy, w, h = (int(x) for x in g.groups())
            device[cp] = (off, adv, ox, oy, w, h)

        # Font(m, len, baseline, height, descender, xheight, capheight, bpp)
        fm = re.search(r"new\(" + font["id"] + r"\) font::Font\([^,]+,\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\)", text)
        if not fm:
            problems.append(f"{font['id']}: Font(...) ctor not found")
            continue
        n, baseline, height, descender, xheight, capheight, bpp = (int(x) for x in fm.groups())

        for label, want, got in [("glyph count", len(font["glyphs"]), n),
                                 ("baseline", font["baseline"], baseline),
                                 ("height", font["height"], height),
                                 ("descender", font["descender"], descender),
                                 ("xheight", font["xheight"], xheight),
                                 ("capheight", font["capheight"], capheight),
                                 ("bpp", font["bpp"], bpp)]:
            if want != got:
                problems.append(f"{font['id']}: {label} fixture={want} device={got}")

        for cp_s, gi in font["glyphs"].items():
            cp = int(cp_s)
            if cp not in device:
                problems.append(f"{font['id']}: U+{cp:04X} in fixture but not in device table")
                continue
            off, adv, ox, oy, w, h = device[cp]
            mine = (gi["advance"], gi["offset_x"], gi["offset_y"], gi["width"], gi["height"])
            if mine != (adv, ox, oy, w, h):
                problems.append(f"{font['id']}: U+{cp:04X} metrics fixture={mine} device={(adv, ox, oy, w, h)}")
                continue
            nbytes = (w * h * bpp + 7) // 8
            if blob[off:off + nbytes].hex() != gi["bitmap"]:
                problems.append(f"{font['id']}: U+{cp:04X} bitmap differs from the device build")
        if not any(p.startswith(font["id"] + ":") for p in problems):
            print(f"verified {font['id']}: all glyph metrics + bitmaps byte-identical to the device build")

    if problems:
        print("\nFIXTURE MISMATCH:")
        for p in problems:
            print("  -", p)
        return 1
    print(f"\nOK: {OUT.name} reproduces the device build in {main_cpp.name}")
    return 0


def check(fonts: list[dict], out_path: Path) -> int:
    """Compare the committed fixtures against the YAML font blocks (no freetype needed)."""
    if not out_path.exists():
        print(f"{out_path} missing - run: python test/export_font_metrics.py")
        return 1
    data = json.loads(out_path.read_text(encoding="utf-8"))
    by_id = {f["id"]: f for f in data["fonts"]}
    problems = []
    for spec in fonts:
        f = by_id.get(spec["id"])
        if not f:
            problems.append(f"{spec['id']}: missing from {out_path.name}")
            continue
        want = sorted(ord(c) for c in spec["glyphs"])
        have = sorted(int(k) for k in f["glyphs"])
        if want != have:
            extra = [chr(c) for c in want if c not in have]
            gone = [chr(c) for c in have if c not in want]
            problems.append(
                f"{spec['id']}: glyph set differs (YAML {len(want)} vs fixtures {len(have)}); "
                f"missing from fixtures: {extra!r}; no longer in YAML: {gone!r}")
        for key in ("size", "bpp"):
            if spec[key] != f[key]:
                problems.append(f"{spec['id']}: {key} YAML={spec[key]} fixtures={f[key]}")
        if f.get("source") != spec["file"]:
            problems.append(f"{spec['id']}: font file YAML={spec['file']} fixtures={f.get('source')}")

    if problems:
        print("FONT FIXTURES OUT OF DATE:")
        for p in problems:
            print("  -", p)
        print("\nRe-export them (needs esphome + freetype-py):")
        print("    python test/export_font_metrics.py")
        return 1
    print(f"font fixtures: {out_path.name} matches the YAML font blocks "
          f"({len(fonts)} fonts, {sum(len(f['glyphs']) for f in data['fonts'])} glyphs)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", metavar="MAIN_CPP", help="compare against a generated main.cpp")
    ap.add_argument("--check", action="store_true",
                    help="compare the committed fixtures with the YAML (no export)")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    fonts = parse_yaml_fonts(YAML.read_text(encoding="utf-8"))
    if args.check:
        return check(fonts, Path(args.out))

    fixtures = export(fonts)
    Path(args.out).write_text(json.dumps(fixtures, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")

    if args.verify:
        return verify(fixtures, Path(args.verify))
    return 0


if __name__ == "__main__":
    sys.exit(main())
