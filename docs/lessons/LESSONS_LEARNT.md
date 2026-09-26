# ApolloMatrix — Lessons Learnt

Hardware: **Apollo Automation M-1**, 64×64 HUB75 panel, ESP32-S3 (DevKitC-1), ESP-IDF.
Repo: **this repository**. Every path, command and file reference below is relative to
its root — `cd` into the repo folder first and run things from there.

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
bool room_present = id(room_presence).has_state() && id(room_presence).state;
bool auto_on = (in_window && room_present);
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

## 3. ~~The onboard status LED is a usable proxy for "display active"~~ — REMOVED, the LED never lit (disproved 2026-09-26)

**Original claim (now withdrawn):** the same lambda branch that draws the panel also
drove a WS2812 on `GPIO3`, so `light.apollomatrix_onboard_status_led == on` was taken as
proof that the active branch executed — and that is how the presence gate was
"verified without eyes on the panel".

**Why it was wrong:** the component's *state* was real, but the *hardware* was not.
Tested directly — a manual override with `number.apollomatrix_matrix_brightness` at
**1.0** made the panel visibly ~5× brighter while **nothing lit on the board at all**.
ESPHome happily reported `on, brightness 255, rgb (0,51,255), effect Heartbeat`
throughout, so an HA state is not evidence that an LED exists.

So there is currently **no remote "is the display lit?" signal**. To confirm the panel
is displaying you either look at it, or reason from the inputs (in-window + presence, or
the manual override switch). The `light:` block, its two lambda calls and the
`status_led_pin` substitution were removed; the code is in git history if the correct
pin ever turns up (`GPIO3` is a strapping pin on this board, so the pin choice was
likely assumed rather than schematic-derived).

Process lesson: verify *against the hardware*, not against the firmware's intent. An
entity reporting `on` says the software did its job; it says nothing about the wire.

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

ESPHome warned that the ESP-IDF tools directory under
`%LOCALAPPDATA%\esphome\Cache\idf` (46 characters on the machine this was found on)
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

- `id(room_presence).has_state()` → `room_presence->has_state()`, confirming the
  HA binary_sensor platform exposes both `has_state()` and `state`.
- Whether a component becomes an HA entity: `App.register_binary_sensor(room_presence,
  "room_presence", …, 16777216);  // internal` — flagged **internal**, so it never
  appears in Home Assistant. Adding it therefore required **no HA change at all**;
  the HA-side entity is only the presence *source* (`binary_sensor.sonoff_snzb_06p24`).

## 10. Two dead paths — diagnosed, then REMOVED (verified 2026-09-26)

Originally recorded here as harmless dead code; an external review flagged them and they
were removed the same day.

- `sensor.scoresby_cloud_situation` **does not exist** on the HA instance (the live
  Scoresby sensors are temp / feels-like / humidity / dew point / rain / wind), so the
  `weather_condition` text sensor never updated.
- `display_active` was only ever **written** (by `show_weather_timer`), never read by the
  lambda — so "a weather change forces the display on for 60 s" was never true.
  `global_brightness` was declared and unused; `last_weather` was read only by that path.

All of it is gone from the config — the `weather_condition` substitution and text_sensor,
`show_weather_timer`, `display_active`, `last_weather`, `global_brightness` — and the
code lives in git history.

Lesson: dead code that a *user* can see in their config is worth deleting even when it is
harmless. Removing it also took out the last reference to a non-existent HA entity,
which the User Guide had to warn users about.

## 11. Deploy loop for this device (verified 2026-09-26)

The repo is the source of truth, but the **build host is the ESPHome addon on the HA
server** (config dir `/config/esphome/`, which already holds the real `secrets.yaml`).

1. Copy `ApolloMatrix.yaml` from the repo into the addon's config dir on the HA host
   (dashboard file editor, Samba, or SCP). Copy the **file**, don't paste text —
   see lesson 7.
2. ESPHome dashboard → ApolloMatrix → ⋮ → Install → **Wirelessly** (OTA). The addon
   compiles and flashes over Wi-Fi; no serial needed.
3. HA's ESPHome integration reconnects on its own — no HA restart, and the firmware
   change added no entity to HA (lesson 9).

## 12. Editing the HA dashboard from an agent needs the WebSocket API (verified 2026-09-26)

The presence row was added to the dashboard's **Living Room** mushroom stack
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
  over a shared header, so `ApolloMatrix.yaml` stays authoritative and
  `test/check_sync.py` exists purely to make drift *detectable* — it asserts ~22
  load-bearing expressions (conditions, formats, coordinates) appear in both files.
  It is a smoke check, not proof; mirror changes by hand.
- **Frame it as an assertion runner, not just a renderer.** Each scenario declares the
  expected display state, so a regression in the gate fails the run (non-zero exit)
  instead of silently producing a wrong picture.

Because the harness cannot execute the firmware, it models only what the lambda
*decides* — the draw ops and whether the display is active. It cannot exercise ESPHome
components, and it no longer models the onboard LED at all, since that block was
removed (lesson 3).

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

**Bonus latent bug found the same way:** `-` (U+002D) was *not* in the Roboto glyph
set (`glyphs: '[PHONE].C°'`), while `%.1f` formats a minus for sub-zero
temperatures. `Font::print()` draws an **unknown glyph as a filled rectangle**
(width = `glyphs_[0].advance`, height = the font height), so a `-5.4°C` reading put a
solid block where the minus belongs. **Fixed 2026-09-26**: `-` added to
`weather_font_l`'s glyphs (13 → 14 glyphs), fixtures re-exported, and the scenario
renamed `temp_negative` (it now renders a real minus). The small font already had
`-`; only the large (temperature) font was missing it.

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
- coverage 0 → the firmware draws nothing; otherwise it computes
  `(uint8_t)(colour * coverage/bpp_max)` blended against `COLOR_OFF = (0,0,0)`.
  **The panel shows none of that dimming** — every inked pixel renders full on, so
  the renderer draws any `coverage > 0` at the full colour (lesson 19)
- unknown codepoint → a filled rectangle `first_glyph.advance` wide and
  `font.height` tall, in the text colour

A `--check` mode compares the committed fixtures against the YAML `font:` blocks
(glyph set, size, bpp) without needing FreeType, so `run_tests.sh` fails loudly if
the glyphs change but the fixtures were not re-exported.

## 19. The panel does NOT antialias — coverage is thresholded to on (verified 2026-09-26)

**This lesson replaces an earlier, wrong version of itself.** Reading the firmware
only — `bpp: 2` glyph bitmaps plus `Font::print()`'s blending:

```cpp
on = pixel / bpp_max;                                        // bpp_max = 3
blended = (uint8_t)(colour * on + background * (1 - on));    // background = COLOR_OFF = (0,0,0)
```

— it was concluded that the Roboto temperature is antialiased at 4 levels. **The
panel does not show that.** The blending exists in the firmware, but none of it
reaches the LEDs.

Measured from a photo of the device, LED by LED (method in lesson 20), for the
temperature line at `bri = 0.2` — the firmware hands the driver blue values of 17
(1/3), 34 (2/3) and 51 (full):

| | median LED brightness |
|---|---|
| background (coverage 0) | 66 |
| coverage 1 | **146** |
| coverage 2 | **146** |
| coverage 3 (full) | **146** |

The ink brightness histogram across the whole 66..146 range is
`[9, 0, 0, 0, 0, 0, 0, 71]` — every inked pixel in the top bin, nothing in between.
The ink *shape* matches `coverage > 0` (IoU **0.857**) rather than `coverage >= 2`
(0.613) or `coverage == 3` (0.449), so the device **is** running `bpp: 2` and simply
thresholds any covered pixel to full on.

What this means:

- `bpp` decides *which* pixels are inked, not how bright they are. Raising it to 4
  would buy nothing; lowering it to 1 **would** change the look (mono rendering is a
  50 % threshold, i.e. thinner glyphs than today's fat ink).
- The harness must draw every `coverage > 0` pixel at the full colour — `rasterize.py`
  now does.
- The loss is downstream of ESPHome: `HUB75Display::draw_pixel_at` passes
  `color.r/g/b` straight to `driver_->set_pixel()`. The esp-hub75 driver's colour path
  (CIE 1931 gamma LUT + 1–255 "basis" brightness, per its docs) is where it must go.
  **Not verified which step** — but testable: these values are already 5× reduced by
  `bri = 0.2`, so setting brightness to 1.0 may separate the levels again.
- Silkscreen was *never* at issue here: its bitmaps contain no partial pixels at all
  (verified: 0 of 32 glyphs), so it is binary by construction.

The process lesson: **the firmware's data and code are not evidence of what the panel
shows.** Where the hardware can be photographed, measure the hardware.

## 20. Verifying a render against the real panel (verified 2026-09-26)

A photo of the panel can be turned into ground truth for the renderer:

1. **Find the LED grid.** FFT the row/column luminance profiles and take the
   fundamental in a plausible band (`n/40 .. n/12` → ~64 cycles across a 1468 px
   photo of a 64×64 panel, i.e. ~23 px pitch). FFT phase gives a starting offset.
2. **Refine the phase** by maximising the total sampled energy — the dots are
   brightest at their centres.
3. **Sample each LED** into a 64×64 brightness map. Use a *tight* window (±1 px is
   enough); the ±4 px max window used first gave the same answer, but a tight sample
   removes any doubt about a neighbouring LED's glow.
4. **Build the expected map from the firmware's own bitmaps** (`test/fonts/metrics.json`)
   for the text that is legible in the photo.
5. **Align** by brute-forcing the drift offset (`dx`, `dy` ∈ -3..3) for best
   correlation, then ask two separate questions:
   - *Brightness:* median photo brightness per expected-coverage class → does the
     panel antialias? (It does not.)
   - *Shape:* IoU between the photo's lit set and each candidate ink mask
     (`coverage > 0` / `>= 2` / `== 3`) → which coverage counts as on? (All of it.)

This is what caught the wrong AA conclusion in lesson 19, and it is the method to
reach for whenever a render is meant to predict the panel: compare against a photo,
not against the source.

## 21. What the burn-in drift actually buys — and why it was removed (verified 2026-09-26)

> **Removed 2026-09-26** at the user's request. The lambda now draws at fixed
> coordinates (`dx = dy = 0`), where every line fits with margin (lesson 17: DEWPT
> 2 px, temperature 23 px). The analysis below is kept because it quantifies what was
> given up: with no drift every inked pixel is lit for 100 % of the display time, so
> there is now no burn-in spreading at all and the remaining wear levers are
> brightness (`bri = 0.2`) and the room-presence gate.

The lambda used to shift the whole image by `dx = roundf(sin(phase)*1.5)`,
`dy = roundf(cos(phase)*1.5)` over a 60 s phase cycle, which read as a gentle
±1.5 px anti-burn-in drift. Measured against the real content — for each reachable
offset, the lit-pixel mask from the firmware's bitmaps, then each pixel's duty across
the cycle:

| | ink px | union | mean duty | peak duty | pixels at 100% duty |
|---|---|---|---|---|---|
| no drift | 468 | 468 | 100 % | 100 % | 468 (all) |
| current drift (6 states) | 468 | **1672** | 28 % | **67 %** | **0** |
| hypothetical ±4 px (81 states) | 461 | 3567 | 13 % | 22 % | 0 |

So the drift is not useless — it spreads the same ink over **3.6×** the pixels, drops
the peak duty to 67 % and means **no pixel is permanently lit** (with no drift every
inked pixel ages at full rate). The latent ghost becomes a 1–2 px blur rather than
crisp text, and the hottest pixels age about a third slower.

Its ceiling is the amplitude versus the stroke width: Silkscreen's strokes are 1 px
(at 4×5 glyphs) and Roboto 14's are ~2 px, so pixels at a stroke's core are still lit
in 2–4 of the 6 states. It also cannot grow horizontally — `FEELS` (55 px) and
`DEWPT` (62 px) are centred in a 64 px panel with ~1 px of slack, which is why `dy`
carries the larger ±2.

What matters more than the drift, in order:

1. **Brightness.** `bri = 0.2` runs the LEDs at about a fifth of rated current, and
   LED aging is strongly superlinear in current (~I^1.5–2). This is a far bigger lever
   than any pixel shift, and it is already in place.
2. **On-time.** Total duty-hours is the other half of the aging equation; the
   room-presence gate cuts the hours the panel is lit at all.
3. **A wider drift, if the layout ever allows it.** ±4 px / 81 states drops the peak
   duty to ~22 % — but needs headroom the two long lines do not currently have.

Caveat: this is a duty-cycle / spatial-spread analysis of the pattern, not a lifetime
prediction — it says nothing about absolute LED hours, only about how evenly the
wear is distributed.

## 22. Two render styles with two different jobs (verified 2026-09-26)

`rasterize.py` produces two views of the same frame, into one directory
(`test/output/images/`, filenames prefixed by style):

| style | what it is | use it for |
|---|---|---|
| `crisp_*` | the faithful 64×64 pixel grid, 8× zoom | layout, margins, clipping, ink — the only style that represents what the panel receives |
| `device_*` | a presentation render of the physical panel: round dies with a glow halo on a dark mask, faint unlit packages between them | judging how the frame *appears* |

The device style is **not** evidence about the device: it carries a camera-like
`--exposure` gain and LED styling. Never read brightness levels or geometry off it —
lesson 19's wrong antialiasing conclusion came from reasoning about the data, and was
corrected by measuring a photo, never by looking at a render.

Nor is either style an automated test. What actually gates is: the 20 scenario
assertions in `render_scenarios` (display/LED state), `check_sync.py` (harness logic
vs the YAML) and `export_font_metrics.py --check` (font fixtures). The images are for
human review; there is no committed pixel-diff baseline.

**Apply gain to emitted light only.** The first device-look multiplied the whole image
by `exposure` (2.2), which lifted the LED mask and the unlit packages too: the mask
rendered at ~24/255 and the panel read as a grey wash instead of a black board. The
fix is to scale the lit-LED term alone and keep the mask and off-dots absolute
(`PANEL_BG = (6, 6, 8)`, `UNLIT_LEVEL = 7`). The same applies to any such gain in a
renderer.

Design decisions taken — keep them unless asked to change:

- **Uniform panel.** No per-LED brightness spread and no vignette: every LED of the
  same colour renders identically. Both were added for realism, then removed on
  request; the off-pixel grey was subsequently halved for contrast.
- **One output directory.** Renders go to `test/output/images/` (git-ignored) prefixed
  `crisp_`/`device_`; the README's copies live in `docs/images/` and are refreshed by
  `test/make_readme_images.py` after `test/run_tests.sh`.

## 23. The configuration surface is one substitutions block (verified 2026-09-26)

Everything a user must change now lives in a single documented `substitutions:` block
at the top of `ApolloMatrix.yaml` (30 keys): the four HA weather entities, the optional
condition entity, the presence entity, timezone, the window (`start_hour`/`off_hour`),
device name, panel geometry, shift driver, bit depth and all 16 pins. The rest of the
file is the engine and reads them as `${...}`.

Decisions to keep:

- **Home Assistant only, by choice.** The project takes its weather from HA entities
  rather than fetching an API itself: the user points four substitutions at their own
  source (BOM, Met.no, WU, their own station) and nothing else changes. No backend
  packages, no HTTP/JSON on the device.
- **°C is canonical.** The ramp (−2…30), the trend threshold (±0.1) and the formats
  are Celsius. A °F user converts with a `template` sensor at the *input*; re-scaling
  the ramp in three places is not offered.
- **`off_hour` now drives two things.** The window's upper bound *and* the
  `time.on_time` that resets `manual_override` were both hardcoded 22 independently, so
  a user changing one would have silently desynced the override reset. Both read
  `${off_hour}` now.
- **The window start had to leave the lambda.** `now.hour >= 8` was inline; it is now
  `${start_hour}`. Substitutions resolve before parsing, so they work inside the lambda
  text — verified with `esphome config` ("Configuration is valid!" once the local
  `channel_colors` version skew was worked around in a scratch copy only).

Consequences the guards had to absorb — both by design, both worth remembering:

1. **`check_sync.py`'s window anchor had to change.** It asserted the literal
   `now.hour>=8&&now.hour<off_h`; it now asserts the substituted form in the YAML and,
   separately, compares the harness's mirrored defaults *numerically*
   (`start_hour` ↔ `in.hour >= 8` in matrix_logic.h; `off_hour` ↔ `in.off_hour = 22` in
   main.cpp). Without that the guard would either fail loudly on a valid config or —
   worse — keep passing while the harness tested a different window. Verified by
   temporarily setting `start_hour: "7"` → `start_hour: YAML default 7 vs
   test/matrix_logic.h 8`.
2. **Text substitutions are not free.** Glyph bitmaps are baked at build time, so
   changing a unit letter or a label means extending `glyphs:` and re-running
   `export_font_metrics.py` (the fixture check catches a mismatch). And the longest line
   (`DEWPT 11.2°C`, 62 of 64 px) means a longer label clips — hence the README telling
   users to run the harness as a fit check.

Follow-up changes (same day), all user-requested:

- **`lounge_presence` → `presence_sensor`, internal id → `room_presence`.** The panel can
  live in any room, so naming it after one was wrong; the gate variable is
  `room_present`. Wording was neutralised across the README, the harness and these
  lessons.
- **Presence is now optional — as a commented block in the SAME file.** The `binary_sensor:`
  key carries Option A (the HA sensor, entity id from `${presence_sensor}`) with Option B
  (an always-occupied `template` sensor, i.e. time-based only) directly below, commented.
  A user with no sensor deletes A and uncomments B.
  An `!include`-based variant using `presence/homeassistant.yaml` + `presence/none.yaml`
  was tried first and **deliberately reverted**: it deployed fine (both modes validated,
  and `${presence_sensor}` *did* resolve inside the included file) but it meant an extra
  directory to copy to the ESPHome addon. Deployment simplicity — one self-contained YAML
  — beat tidiness, so variants belong in the file as commented blocks, not as extra files.
  The lambda is unchanged in both modes, so the harness needed no new scenarios.
- **`device_friendly_name: ApolloMatrix`.** ESPHome's `name` must be a hostname
  (lowercase letters/digits/dashes only), so `ApolloMatrix` is invalid there and goes in
  `friendly_name` — which is what Home Assistant shows. The hostname stays
  `ApolloMatrix`.
- **Documentation split into three docs with distinct jobs.**
  `README.md` = project reference (configuration table, hardware, renders, harness);
  `docs/USER_GUIDE.md` = the deployment walkthrough for someone who has just bought the
  hardware (gather entity IDs → edit the block → **first flash over USB, not OTA** →
  add the device in HA → troubleshooting → optional tweaks);
  `docs/lessons/LESSONS_LEARNT.md` = this technical record. Keep the User Guide in step
  with the config surface: a new substitution belongs in its step-2 block too.

## 24. The preview fonts are fetched, not redistributed (verified 2026-09-26)

Both fonts are **SIL OFL 1.1**: Silkscreen (Copyright 2001 The Silkscreen Project
Authors) and Roboto (Copyright 2011 The Roboto Project Authors, relicensed — it is
**not** Apache-2.0, which an earlier NOTICE here wrongly claimed). Neither declares a
Reserved Font Name. Metadata: `google/fonts/ofl/{silkscreen,roboto}`.

OFL clause 2 *does* permit bundling the fonts with software — "provided that each copy
contains the above copyright notice and this license" — so vendoring them would have
been legal with the OFL texts alongside. **The decision was not to redistribute them at
all**: the `.ttf` files are git-ignored, and `test/fetch_fonts.py` fetches them on
demand. The OFL texts stay in `test/fonts/` because the firmware *does* embed glyph
bitmaps derived from these fonts, and because anyone who fetches the files gets the
terms with them.

Nothing in the firmware path needs them: `font:` uses `gfonts://` and ESPHome downloads
the fonts on the build host. They are read only by `rasterize.py` (caption chrome) and
`export_font_metrics.py` (re-exporting the fixtures). Rendering without them works —
verified by moving the TTFs away and running the suite: 20 scenarios pass and all 42
images are still produced, with the caption font falling back to PIL's default.
`run_tests.sh` prints a one-line hint when they are absent so the fallback is visible
rather than mysterious.

Fetch routes, and why they are not equivalent:

| route | fidelity |
|---|---|
| copy from an ESPHome cache (`<config-dir>/.esphome/font/`) | **byte-identical to the firmware** — verified by SHA1 against the originals |
| `--via-esphome` — builds a throwaway cache, copies, cleans up | same, without you having to find the cache |
| `--download` — HTTPS from the Google Fonts repo | upstream releases: Silkscreen is static there, but **Roboto only ships as a variable font** (488 KB vs the firmware's 123 KB static 400), so its metrics can differ slightly. Fine for captions, not for regenerating `metrics.json`. |

Gotcha found while writing `--via-esphome`: the throwaway `secrets.yaml` needs a WiFi
password of **at least 8 characters**. With a shorter dummy, ESPHome fails validation
*before* downloading the fonts, so the fetch silently finds nothing and reports no
cache — the symptom is "esphome did not produce a font cache", not a secrets error.

## 25. The HUB75 power gate stays on — documented, not changed (2026-09-26)

`onboard_power_gate` (GPIO7) is switched on once in `esphome.on_boot` and never switched
off, so it stays powered while the panel is blanked. Blanking is done by drawing black
frames, not by cutting power. An external review raised this as a power/thermal note and
recommended documenting the reasoning rather than changing it.

Why it is left alone: the ESPHome `hub75` driver runs a **continuous DMA refresh chain**
— that is how it refreshes without CPU intervention — and that chain expects a powered
panel; the gate is what brings the panel up before the chain starts. Gating power on
presence/window transitions would power-cycle the panel every time the room empties, for
no functional gain.

Stated as caveats, because they are inferences, not measurements:

- **Not empirically verified.** Powering the gate off has never been tried on this
  hardware. "The driver needs it" follows from how the driver works, not from a test.
- **The blanked draw is not measured.** While blanked the panel still receives a full
  black frame clocked at the refresh rate and the ESP32 keeps running, so the device
  draws *something* continuously whenever it is plugged in. If that matters, the honest
  next step is to measure it — not to assume the gate can be cycled safely.
