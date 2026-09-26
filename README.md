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
| `update.apollomatrix_firmware` | update | OTA updates |

A weather-condition change in `sensor.scoresby_cloud_situation` triggers the
`show_weather_timer` script (display forced active for 60 s).

## Requirements

- **ESPHome** with the `hub75` display platform available (the **esp-hub75**
  component — see the `external_components` note below).
- Fonts are fetched at build time from Google Fonts (`gfonts://Silkscreen`, `gfonts://Roboto`).

## Setup

```bash
cp secrets.yaml.example secrets.yaml   # then fill in wifi_ssid / wifi_password
esphome run apollomatrix.yaml
```

`secrets.yaml` is git-ignored.

## Known issues / TODO

- **No `external_components:` block.** The config uses `platform: hub75`, which
  comes from the esp-hub75 component (the compiled firmware references
  `/managed_components/esphome__esp-hub75/...`). Add the appropriate
  `external_components:` source, or confirm it is installed on the build host.
- `sensor.scoresby_cloud_situation` is referenced by the `weather_condition`
  text sensor — confirm this entity exists on the HA instance.
- `global_brightness` is declared but unused (brightness is driven by the
  `matrix_brightness` number entity instead).
