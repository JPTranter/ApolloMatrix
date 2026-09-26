# apollomatrix — Lessons Learnt

Hardware: **Apollo Automation M-1**, 64×64 HUB75 panel, ESP32-S3 (DevKitC-1), ESP-IDF.
Repo: `C:/Users/jptra/Projects/apollomatrix`.

Convention (inherited from eClock/ChromaWOTD): entries marked **verified <date>**
were confirmed against this repo, the generated build output, or live Home
Assistant state. Unmarked entries are reasoned from documentation or observation
and are labelled as such — do not recite them as fact.

---

## 1. All visibility gating lives in the display lambda, not in HA (verified 2026-09-26)

There is no Home Assistant automation for this device. The `display:` lambda is the
single gate; it decides every update whether to draw or to blank and turn the status
LED off. Current conditions:

```cpp
int off_h = id(off_hour_cutoff);              // 22
bool in_window = (now.hour >= 8 && now.hour < off_h);
bool lounge_present = id(lounge_presence).has_state() && id(lounge_presence).state;
bool auto_on = (in_window && lounge_present);
bool forced_on = (id(manual_override) && now.hour < off_h);
if (now.is_valid() && (auto_on || forced_on)) { /* draw */ } else { /* blank + LED off */ }
```

Consequences worth remembering:

- Grep the lambda first when asked "when does it turn on/off" — the README and the
  HA entity list do not describe behaviour; the lambda does.
- `off_hour_cutoff` = 22 is the single source of the off time; `time.on_time`
  at 22:00 only resets `manual_override`.
- `manual_override` (Matrix Toggle) deliberately bypasses **both** the presence gate
  and the 08:00 start, and is still bounded by the 22:00 cutoff.
- `has_state()` on the HA binary sensor matters: before the first state arrives the
  guard makes the display stay **off** (fail-dark) rather than defaulting on.

## 2. A presence gate belongs in firmware, not in an HA automation (verified 2026-09-26)

The obvious HA-side alternative — an automation flipping `switch.apollomatrix_matrix_toggle`
on presence — is wrong for this device: that switch sets `manual_override`, which
**latches** until 22:00 and is never cleared when the room empties. Pulling the HA
presence entity onto the device (`binary_sensor: platform: homeassistant`) keeps the
gate stateless and evaluated every refresh. Use the HA binary sensor, not the switch.

## 3. The onboard status LED is a usable proxy for "display active" (verified 2026-09-26)

The device exposes no "display on/off" entity, but the same lambda branch that draws
the panel also drives the WS2812 heartbeat. So `light.apollomatrix_onboard_status_led
== on` proves the active branch executed. With `switch.apollomatrix_matrix_toggle == off`
that means the *automatic* path ran — i.e. in-window **and** occupied. This is how the
presence gate was verified without eyes on the panel.

## 4. `esphome compile` reports success when it built nothing (verified 2026-09-26)

ESPHome printed `INFO Successfully compiled program.` with **exit code 0** while the
same run warned `Firmware not found` / `ELF not found`, and no `.elf`/`.bin` existed
on disk. Never treat that message or the exit code as proof of a build — check the
artifact (`.esphome/build/<name>/build/<name>.elf`) or, better, that a factory `.bin`
appeared.

## 5. ESP-IDF will not build under MSYS/Mingw, and clearing `MSYSTEM` is not enough (verified 2026-09-26)

Running `python -m esphome compile` from this git-bash shell produces:

```
MSys/Mingw is no longer supported. Please follow the getting started guide ...
```

Prepending `MSYSTEM=` to the command does **not** clear it (the MSYS directory layout
on `PATH` is still detected). The toolchain step is skipped and lesson 4 applies.
Build on the **ESPHome addon on the HA server** instead — that is where the device's
firmware has actually been produced.

## 6. Windows 260-character path limit breaks the ESP-IDF toolchain (observed, not exercised)

ESPHome warned that `C:\Users\jptra\AppData\Local\esphome\Cache\idf` (46 chars)
projects to ~291 chars with the compiler's internal relative paths, over the 260
limit, producing "cryptic build failures such as `fatal error: bits/c++config.h: No
such file or directory`". Fixes if a local build is ever wanted:

- `ESPHOME_ESP_IDF_PREFIX=C:\ESPHome\idf`, then delete the old tools dir so it
  reinstalls cleanly, **or**
- enable Windows long paths (`HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem`
  → `LongPathsEnabled = 1`) and reboot.

Not exercised here — the builds happen on the addon host.

## 7. Runs of 10+ digits are redacted to `[PHONE]` — and that silently corrupted the font glyphs (verified 2026-09-26)

The `font:` `glyphs` strings were imported as `-[PHONE]°CEFLSKMPUIWDHTY .:%/` and
`[PHONE].C°`. That is not cosmetic: `esphome config` then fails with

```
Found duplicate glyphs: P (b'P'), H (b'H'), E (b'E').
```

because the literal letters in `PHONE` collide with the real `P`/`H`/`E` glyphs.
The real content was the ten digits 0–9 (the display formats `%d/%m %H:%M` and `%.1f°C`).

Rules:

- **Never type a long digit run into a file via the assistant** — it comes back
  redacted. Build it programmatically, e.g.
  `"".join(str(d) for d in range(10))`, then assert the file no longer contains the
  token before writing.
- **Verify digit content by hex, not by eye** — terminal echoes, `git diff`, and
  tool output are redacted too, so a correct file and a corrupted one look identical
  on screen. Digits are `0x30`–`0x39` in the hex dump.

## 8. `esphome config` is the right local check, and it stops short of C++ (verified 2026-09-26)

`python -m esphome config <file>` validates the YAML/schema, resolves `!secret`,
downloads the gfonts, and catches real errors (lesson 7). It does **not** compile the
lambdas — a lambda typo survives `config` and only fails at build. It also needs a
`secrets.yaml`: run it on a scratch copy with dummy WiFi values so real credentials
never enter the repo.

## 9. The generated `main.cpp` is how you confirm what a lambda actually does (verified 2026-09-26)

`.esphome/build/<name>/src/main.cpp` contains the translated C++, so it answers
questions the YAML cannot:

- `id(lounge_presence).has_state()` → `lounge_presence->has_state()`, confirming the
  HA binary_sensor platform exposes both `has_state()` and `state`.
- Whether a component becomes an HA entity: `App.register_binary_sensor(lounge_presence,
  "lounge_presence", …, 16777216);  // internal` — flagged **internal**, so it never
  appears in Home Assistant. Adding it therefore required **no HA change at all**;
  the HA-side entity is only the presence *source* (`binary_sensor.sonoff_snzb_06p24`).

## 10. Two dead paths in this config, confirmed against live HA (verified 2026-09-26)

- `sensor.scoresby_cloud_situation` **does not exist** on the HA instance (the live
  Scoresby sensors are temp / feels-like / humidity / dew point / rain / wind). The
  `weather_condition` text sensor therefore never updates.
- `display_active` is only ever **written** (by `show_weather_timer`), never read by
  the lambda — so "a weather change forces the display on for 60 s" was never true.
  `global_brightness` is likewise declared and unused.

Both are harmless now; don't "fix" them into the presence logic without checking what
the user actually wants.

## 11. Deploy loop for this device (verified 2026-09-26)

The repo is the source of truth, but the **build host is the ESPHome addon on the HA
server** (config dir `/config/esphome/`, which already holds the real `secrets.yaml`).

1. Copy `apollomatrix.yaml` from the repo into the addon's config dir on the HA host
   (dashboard file editor, Samba, or SCP). Copy the **file**, don't paste text —
   see lesson 7.
2. ESPHome dashboard → apollomatrix → ⋮ → Install → **Wirelessly** (OTA). The addon
   compiles and flashes over Wi-Fi; no serial needed.
3. HA's ESPHome integration reconnects on its own — no HA restart, and the firmware
   change added no entity to HA (lesson 9).

## 12. Editing the HA dashboard from an agent needs the WebSocket API (verified 2026-09-26)

The lounge presence row was added to the dashboard's **Living Room** mushroom stack
via `{"type": "lovelace/config"}` / `lovelace/config/save` — REST has no endpoint for
card config, and `save` takes the **entire** dashboard. Back up first, assert the exact
target was found, and re-read after saving to verify. Full procedure lives in the
`home-assistant-control` skill; don't re-derive it here.

## 13. Newer ESPHome options fail local validation — the local CLI lags the addon (verified 2026-09-26)

The ESPHome addon offered a config migration:

> `rgb_order` and its flags folded into `channel_colors` in `light.esp32_rmt_led_strip`.
> Changed in ESPHome 2026.8, the old spelling is removed in 2027.3.

The rewrite is a literal rename — `rgb_order: GRB` → `channel_colors: GRB`
(per the current docs, `channel_colors` is now **Required**, takes each of `R`,
`G`, `B` exactly once, optionally one `W` anywhere, case-insensitive).

The trap: the local CLI is ESPHome **2026.7.4**, and it rejects the new spelling:

```
[channel_colors] is an invalid option for [light.esp32_rmt_led_strip]. Please check the indentation.
```

So on this repo `esphome config` can now produce **false failures** for options the
addon (≥2026.8) accepts. Read a local error on a *new* option as version skew, not
as a config bug — and validate against the addon's version. The migration is
cosmetic for the running device (the old spelling still builds until 2027.3), so it
does not require a reflash to keep working.

## 14. Host render harness: simulate the panel before flashing (verified 2026-09-26)

`test/` compiles the display logic on the PC and renders PNGs of what the panel
would show, with no ESP-IDF and no device. Layout: `test/matrix_logic.h` (ported
logic) + `test/trace_canvas.h` (records draw calls) + `test/main.cpp` (19 scenarios
that ASSERT the expected display/LED state) + `test/rasterize.py` (PIL, real fonts).
Entry point: `test/run_tests.sh`.

Two design consequences worth keeping:

- **The logic is a deliberate copy.** The user chose "device untouched, zero risk"
  over a shared header, so `apollomatrix.yaml` stays authoritative and
  `test/check_sync.py` exists purely to make drift *detectable* — it asserts ~22
  load-bearing expressions (conditions, formats, coordinates) appear in both files.
  It is a smoke check, not proof; mirror changes by hand.
- **Frame it as an assertion runner, not just a renderer.** Each scenario declares
  the expected `display_active`/LED state, so a regression in the gate fails the run
  (non-zero exit) instead of silently producing a wrong picture.

Because the harness cannot execute the firmware, it also cannot catch things the
device does with the LED object (effects, restore state) — it models the LED as
`on`/`off`/`unchanged` only.

## 15. ESPHome's `TextAlign::CENTER` centres VERTICALLY as well (verified 2026-09-26)

Getting this wrong makes every simulated render lie about clipping. In ESPHome,
`CENTER = CENTER_VERTICAL | CENTER_HORIZONTAL` (`components/display/display.h`), and
`Display::get_text_bounds()` computes the box top-left as:

```
x1 = x - (width + x_offset) / 2
y1 = y - height / 2          // height = "top of text -> bottom" (Font::height_)
```

So in `it.printf(32, 58, font, ...)` the 58 is the **middle** of the line, not its
top. Top-aligning the same coordinate in a renderer pushes an 8 px line to 58–66 and
shows a 2 px clip at the bottom of a 64 px panel that the real device does not have.

The first render of this harness had exactly that bug: it top-aligned (`anchor="ma"`
in PIL) and the DEWPT line appeared cut off, implying a firmware layout problem that
did not exist. Fix by measuring with the renderer's own metrics and drawing with the
ascender-top at `(x - width/2, y - height/2)`. Verify against the ESPHome source in
the installed package
(`<site-packages>/esphome/components/display/display.cpp`) — not from memory.

## 16. The harness produced "Successfully compiled" then a silent exit 127 (verified 2026-09-26)

The MinGW-built exe linked fine, `ldd` resolved every DLL, yet every run exited
`127` with no output (from bash *and* from `cmd.exe`). Cause: the exe resolved
`libstdc++-6.dll` from **MSYS2's msvcrt** `/mingw64/bin` rather than the **UCRT**
WinLibs toolchain that compiled it (both are on `PATH`). Fix: link the runtime
statically (`target_link_options(... -static)` under `if(MINGW)`), which removes the
whole class of problem for a host tool.

Related build nits from the same session:

- `M_PI` is not defined under `-std=c++17` (strict ANSI) with MinGW/glibc; supply a
  fallback `#ifndef M_PI` define rather than dropping `-std=c++17`.
- Native Windows programs (cmake, python, the harness exe) do **not** understand
  MSYS paths like `/c/Users/...`. Convert with `cygpath -m` before passing them, or
  cmake fails with "The source directory ... does not exist" and the exe writes
  nothing.

## 17. The DEWPT line has ZERO spare width, and the drift is quantised (verified 2026-09-26)

A render showed the final `C` of `DEWPT 11.2°C` crossing the right edge, so it was
checked against the device's own glyph metrics — extracted from the generated
`main.cpp` of an actual build (`font_glyph_id`, and the `Font(...)` ctor args
`baseline=9, height=10` for Silkscreen 8). Line widths, using
`x1 = x - (width + x_offset)/2` and one pen step per glyph advance:

| line | width | spare vs 64 px |
|---|---|---|
| `26/09 10:32` (Silkscreen 8) | 58 | 6 |
| `11.4°C` (Roboto 14) | 41 | 23 |
| `FEELS 9.3°C` | 55 | 9 |
| `HMDTY 99%` | 53 | 11 |
| **`DEWPT 11.2°C`** | **62** | **2** |

So `DEWPT` is 62 px in a 64 px panel: at `dx=+1` its last ink column is **63**, the
final column. It fits — the device does not clip the `C` — but with nothing to
spare. Any longer value (a third digit, or a `-` sign) overflows.

**All five lines fit at every drift the device can actually reach.** The important
part is *reachable*: the lambda runs on `update_interval: 10s`, so the 60 s drift
cycle is sampled at only six phases per minute, giving offsets
`(-1,-1) (-1,1) (0,-2) (0,2) (1,-1) (1,1)` — `dx` is only ever `-1/0/+1`.
`dx=+2` needs `sin(phase) >= 1.0` *exactly*, so it is essentially unreachable.

The render that showed the clipping was wrong twice over: it used `millis = 15000`
(`phase = π/2` → `dx=+2`, an unreachable state) **and** measured text width with the
rasterizer's own TTF metrics instead of ESPHome's glyph advances. Scenario drift
phases now use the reachable set, with the baseline pinned at `millis = 10000`
(`dx=+1`, `dy=+1`) — the worst realistic case for the right edge.

**Bonus latent bug found the same way:** `-` (U+002D) is *not* in the Roboto glyph
set (`glyphs: '[PHONE].C°'`), while `%.1f` formats a minus for sub-zero
temperatures. `Font::print()` draws an **unknown glyph as a filled rectangle**
(width = `glyphs_[0].advance`, height = the font height), so a `-5.4°C` reading would
put a solid block where the minus belongs. Fix by adding `-` to that font's glyphs.
The small font already has `-`; only the large (temperature) font is missing it.

## 18. Rendering text faithfully means driving ESPHome's own font generator (verified 2026-09-26)

A desktop text stack is not the device's text stack. The first harness rendered with
PIL/FreeType at PIL's own metrics and antialiasing, which produced a ~1 px position
error and a false "clipped C" (lesson 17), and gave Silkscreen smoothing the panel
never shows (lesson 19).

The fix is not to reimplement better - it is to use ESPHome's own generator:
`esphome/components/font/__init__.py` exposes `glyph_to_glyphinfo(glyph, face, size,
bpp)` (FreeType → advance/offset_x/offset_y/width/height + `bpp`-bit packed coverage)
and `pt_to_px()`, and the `Font(...)` constructor takes
`(baseline=ascender, height=pt_to_px(size.height), descender, xheight, capheight,
bpp)`. `test/export_font_metrics.py` drives exactly those functions and writes
`test/fonts/metrics.json`, which `rasterize.py` then consumes - so the fixtures are
the firmware's data, not a lookalike.

Verification is byte-exact: `python test/export_font_metrics.py --verify <build>/src/main.cpp`
parses the glyph table and `Font(...)` args out of a real build and compares every
metric and bitmap. It reported all 45 glyphs identical, which is what makes the
renders trustworthy.

Rendering rules to mirror (all in `Display::get_text_bounds` / `Font::measure` /
`Font::print`):

- `width = total_advance - min_x`, `x_offset = min_x` (`min_x` = min of
  `x + offset_x` over the glyphs)
- `x1 = x - (width + x_offset)/2`, `y1 = y - height/2`
- pen starts **at x1** (not x1 - min_x); ink at `(pen + offset_x, y1 + offset_y)`
- coverage 0 → draw nothing; `== bpp_max` → the text colour; otherwise
  `(uint8_t)(colour * coverage/bpp_max)` blended against `COLOR_OFF = (0,0,0)` — the
  device's antialiasing, at its own bit depth
- unknown codepoint → a filled rectangle `first_glyph.advance` wide and
  `font.height` tall, in the text colour

A `--check` mode compares the committed fixtures against the YAML `font:` blocks
(glyph set, size, bpp) without needing FreeType, so `run_tests.sh` fails loudly if
the glyphs change but the fixtures were not re-exported.

## 19. Antialiasing is per-font and lives in the glyph bitmaps (verified 2026-09-26)

`bpp:` sets the glyph coverage depth (2 bits = 4 levels). `Font::print()` unpacks
each pixel and blends partial coverage:

```cpp
on = pixel / bpp_max;
blended = (uint8_t)(colour * on + background * (1 - on));   // truncated
```

The lambda's `printf(x, y, font, colour, align, fmt, ...)` overload passes
`background = COLOR_OFF`, and `COLOR_OFF` is `Color(0, 0, 0, 0)`
(`display.h:300`). So a partial pixel is the text colour **dimmed by its coverage** -
antialiasing against black, correct for a panel that clears to black each frame.

Whether it does anything depends entirely on the generated bitmaps, and the two fonts
here differ completely:

| font | glyphs with partial pixels | inked pixels that are partial |
|---|---|---|
| Silkscreen 8 (the four small lines) | 0 / 32 | **0 %** (values are only 0 or 3) |
| Roboto 14 (the temperature) | 13 / 13 | **44 %** (levels 1-2) |

So the big temperature number is antialiased at 4 levels, and the small lines are
hard-edged. That is expected: Silkscreen is a pixel font rendered at its native size,
where FreeType's coverage lands on 0 % or 100 % anyway. Raising `bpp: 4` (16 levels)
would sharpen only the Roboto text, at a flash cost.

Consequence for tooling: never let a renderer smooth what the device does not.
Rasterise from the coverage bitmaps (lesson 18) instead of a desktop text stack,
which would smooth Silkscreen *and* apply finer shading than 4 levels to Roboto.
