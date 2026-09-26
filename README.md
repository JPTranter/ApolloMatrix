# apollomatrix

ESPHome configuration for an **Apollo Automation M-1** 64×64 HUB75 LED matrix
panel driven by an **ESP32-S3** (DevKitC-1). The panel shows the date/time and
live Bureau-of-Meteorology weather for **Scoresby** (Melbourne), colour-coded by
temperature, with a 30-minute trend arrow. It only lights up while someone is in
the lounge room, within an 08:00–22:00 window, and can be forced on from Home Assistant.

## Hardware

| Item | Value |
|---|---|
| MCU | ESP32-S3 (esp32-s3-devkitc-1), ESP-IDF framework |
| Panel | 64×64 HUB75, shift driver `FM6126A`, `STANDARD_TWO_SCAN`, 10-bit depth |
| Status LED | 1× WS2812 on GPIO3 (`esp32_rmt_led_strip`) |
| Power gate | GPIO7 (`onboard_power_gate`) |

HUB75 pins: `R1=42 G1=41 B1=40 R2=38 G2=39 B2=37 A=45 B=36 C=48 D=35 E=21 CLK=2 LAT=47 OE=14`.

## What it displays

- **Date/time** `%d/%m %H:%M`, drifting gently (±1.5 px sinusoidal) to avoid burn-in.
- **Temperature** from `sensor.scoresby_temp`, interpolated white→blue→cyan→green→orange→red across −2 °C … 30 °C.
- **Trend arrow** ▲/▼ comparing the current temperature against the 30-minute anchor (`temp_30m`), which is rotated by the `update_temp_trend` script every 10 min.
- **FEELS / HMDTY / DEWPT** lines from the matching Scoresby sensors.
- **Onboard status LED** pulses with the "Heartbeat" effect, tinted to the current temperature colour.

### Visibility window

Shown when the lounge is occupied **and** the time is within the window:

- hour ≥ 08:00 and < 22:00 (`off_hour_cutoff`), and
- `binary_sensor.sonoff_snzb_06p24` reports presence (someone in the lounge)

or when **manual override** is on and hour < 22:00 (overrides both the presence
gate and the 08:00 start, but still blanks at the cutoff).

At 22:00 the `manual_override` is reset and the matrix blanks.

## Home Assistant entities

| Entity | Type | Purpose |
|---|---|---|
| `number.apollomatrix_matrix_brightness` | number | Matrix brightness 0.1–1.0 (restored) |
| `switch.apollomatrix_matrix_toggle` | switch | Manual override — force the display on |
| `light.apollomatrix_onboard_status_led` | light | Onboard WS2812 status LED |
| `binary_sensor.sonoff_snzb_06p24` | binary_sensor | Lounge presence gate (from HA) |

There is **no** `update.apollomatrix_firmware` entity and no `update:` platform
in the config — OTA updates are triggered from the ESPHome dashboard, not HA.

The `weather_condition` text sensor (`sensor.scoresby_cloud_situation`) feeds the
`show_weather_timer` script, but that script only sets the `display_active`
global, which the display lambda never reads — so a weather change does **not**
actually force the display on (dead code; see Known issues).

## Requirements

- **ESPHome** with the `hub75` display platform. The `esp-hub75` component
  (v0.3.5) is pulled automatically via the ESP-IDF component manager
  (`idf_component.yml` in the generated build) — **no `external_components:`
  block is needed**.
- Fonts are fetched at build time from Google Fonts (`gfonts://Silkscreen`, `gfonts://Roboto`).

## Build / flash (ESPHome addon on the HA server)

Firmware is built and pushed from the **ESPHome addon on the Home Assistant
server**, not from this repo's machine.

1. Copy `apollomatrix.yaml` from this repo into the addon's config dir on the HA
   host, e.g. `/config/esphome/apollomatrix.yaml`. The addon already has
   `secrets.yaml` with the WiFi credentials (`!secret wifi_ssid` /
   `!secret wifi_password`); this repo's `secrets.yaml` is deliberately absent
   (git-ignored).
   ⚠️ Copy the file from disk — don't paste it through chat: runs of 10+ digits
   get redacted to `[PHONE]`, which corrupts the font `glyphs` lines.
2. In the ESPHome dashboard: select **apollomatrix** → ⋮ → **Install** →
   **Wirelessly** (OTA). The addon compiles (fetches the two Google fonts,
   resolves `esp-hub75`) and flashes over Wi-Fi.

`cp secrets.yaml.example secrets.yaml` is only needed if you build with the CLI
from a different host.

### Local validation (this repo)

- `python -m esphome config apollomatrix.yaml` validates schema and fetches the
  fonts — works from here and is a good first check. It needs a `secrets.yaml`;
  run it from a scratch copy with dummy WiFi creds so real ones never enter the
  repo.
- **Version skew:** the local CLI is *older* (2026.7.4) than the ESPHome addon on
  the HA server. Options added after 2026.7.4 — e.g. `channel_colors` — fail here
  with `[channel_colors] is an invalid option for [light.esp32_rmt_led_strip]`
  while the addon accepts them. Treat a local failure on a *new* option as a
  version-skew signal, not a config error.
- **Do not trust `python -m esphome compile` in this git-bash/MSYS
  environment** — ESP-IDF refuses to build there and ESPHome prints
  `Successfully compiled program` even when no `.elf`/`.bin` is produced.
  Inspect `.esphome/build/apollomatrix/src/main.cpp` for the translated logic,
  and build on the addon host (details in `docs/lessons/`).

## Testing (host render harness)

`test/` compiles the display logic on the PC and renders what the 64×64 panel
would show — no ESP-IDF, no flashing.

```bash
test/run_tests.sh
```

Four steps:

1. **Build** `test/main.cpp` (CMake + Ninja, host g++) with the ported display
   logic in `test/matrix_logic.h`.
2. **Logic sync check** (`test/check_sync.py`) — asserts the load-bearing
   expressions (gating conditions, trend thresholds, text formats, layout anchors)
   still match between `apollomatrix.yaml` and `test/matrix_logic.h`.
3. **Font fixtures check** (`test/export_font_metrics.py --check`) — asserts
   `test/fonts/metrics.json` still matches the YAML `font:` blocks (glyph set, size,
   bpp), so the render cannot silently keep using a stale font.
4. **Run 20 scenarios** asserting the expected display/LED state, then rasterize
   each to PNG.

Output: `test/output/png/<NN>_<scenario>.png` (8× zoom) and
`test/output/png/_contact_sheet.png` (all scenarios in one grid).

Coverage: window boundaries (07:30 / 08:00 / 21:59 / 22:00), lounge occupied vs
empty, presence sensor with no state, manual override inside/outside the window and
past the cutoff, the temperature colour ramp (1 / 6 / 32 °C), a sub-zero reading,
trend up/down/flat, brightness 0.2 vs 1.0, and missing HA sensor data.

### Rendering fidelity

The PNGs are rendered from the device's own font data rather than an approximation.
`test/fonts/metrics.json` is ESPHome's font output — FreeType advances/offsets plus
`bpp`-bit coverage — produced by `test/export_font_metrics.py`, which drives
ESPHome's own glyph generator. It is verified **byte-for-byte** against a real build:

```bash
python test/export_font_metrics.py --verify <build>/src/main.cpp
```

`rasterize.py` then applies the firmware's rendering rules: `x1 = x - (width +
x_offset)/2`, `y1 = y - height/2` (CENTER centres vertically too), one pen step per
glyph advance, and every pixel with coverage > 0 drawn at the full text colour.

**The panel does not antialias.** ESPHome *does* blend partial coverage, but a
LED-by-LED measurement of a photo of the device shows every inked pixel at identical
brightness — medians 146 / 146 / 146 for coverage 1 / 2 / 3 against a background of
66 — and the ink shape matches "coverage > 0" (IoU 0.86) rather than a 50% threshold
(0.61) or full coverage only (0.45). So `bpp` decides *which* pixels are inked, not
how bright they are, and the renderer thresholds coverage the same way. An unknown
codepoint would draw `Font::print()`'s placeholder rectangle; the renderer models
that too, but the glyph sets no longer need it.

**`test/matrix_logic.h` is a copy** of the YAML lambda — `apollomatrix.yaml` stays
the source of truth for the device. Changes must be mirrored in both; the sync
check catches most drift. Fonts are vendored in `test/fonts/` (see its NOTICE).

## Known issues / TODO

- **`sensor.scoresby_cloud_situation` does not exist on HA** (confirmed
  2026-09-26) — the `weather_condition` text sensor never updates and
  `show_weather_timer` never fires. Harmless because it's dead code (below);
  remove or repoint it if a cloud-situation entity is ever added.
- **`display_active` + `show_weather_timer` are dead**: the display lambda never
  reads `display_active`, so a weather change does not force the display on
  (a previous version of this README claimed it did for 60 s).
- **`global_brightness` is declared but unused** — brightness is driven by the
  `matrix_brightness` number entity instead.
- **No `update:` platform** — there is no `update.apollomatrix_firmware` HA
  entity; OTA is via the ESPHome dashboard.
