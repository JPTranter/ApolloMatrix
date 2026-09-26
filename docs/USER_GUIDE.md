# ApolloMatrix — User Guide

For anyone who has the hardware (an **Apollo Automation M-1** 64×64 HUB75 panel on an
**ESP32-S3**) and wants this weather display running on their own Home Assistant.

Follow the steps in order. Steps 1–5 are the whole job; the rest is troubleshooting
and optional tweaks.

---

## What you need

- The panel and ESP32-S3, assembled. The default pin map is the M-1's, so nothing
  needs rewiring.
- A **USB data cable** (not charge-only) for the very first flash.
- Home Assistant with the **ESPHome (Device Builder) add-on** installed.
- **ESPHome 2026.8 or newer** in that add-on. Older versions reject the
  `channel_colors` line in the light config.
- Internet access **on the Home Assistant host** for the first build — ESPHome fetches
  the two fonts from Google Fonts and the `esp-hub75` component.
- Your WiFi SSID and password, on a **2.4 GHz** network (the ESP32 cannot see 5 GHz).
- Your Home Assistant weather entities — see step 0.

## Step 0 — Collect four things from Home Assistant

Write these down; you paste them into one block in step 2.

| What | Where to find it | Example |
|---|---|---|
| Timezone | Settings → System → General → **Time zone** (use the IANA name) | `Australia/Melbourne` |
| Temperature, feels-like, humidity, dew point | **Developer Tools → States**, filter `sensor.` | `sensor.bom_temp` |
| *(optional)* occupancy sensor for the panel's room | same place, filter `binary_sensor.` | `binary_sensor.room_presence` |

Any weather source works — BOM, Met.no, Weather Underground, an Ecowitt/PWS
integration, your own station — as long as those four values are **in °C**. The colour
ramp and the trend maths are Celsius; if your entities are in °F, see
[°F instead of °C](#f-instead-of-c) below.

## Step 1 — Put the file on the ESPHome add-on

1. Open the **ESPHome dashboard**. Its config directory is `/config/esphome/`.
2. Copy `ApolloMatrix.yaml` from this project into that directory — drag it into the
   file editor, or use the Samba / File editor / SSH add-on. **It is the only file
   this project needs.**
3. Make sure `/config/esphome/secrets.yaml` exists and holds your WiFi credentials:

   ```yaml
   wifi_ssid: "your-ssid"
   wifi_password: "your-password"
   ```

   If you have used ESPHome before, it is probably already there. If not, create it —
   it is git-ignored and never leaves your host.

## Step 2 — Edit the substitutions block

Open `ApolloMatrix.yaml` in the ESPHome editor. Everything you need to change is in the
block at the very top:

```yaml
substitutions:
  weather_temp: sensor.your_outdoor_temp          # ← your entities
  weather_feels_like: sensor.your_apparent_temp
  weather_humidity: sensor.your_humidity
  weather_dew_point: sensor.your_dew_point
  weather_condition: sensor.your_cloud_condition  # optional, see note
  presence_sensor: binary_sensor.your_room_presence
  timezone: Australia/Melbourne                   # ← your IANA timezone
  start_hour: "8"                                 # window opens  (inclusive)
  off_hour: "22"                                  # window closes (exclusive)
  device_name: apollomatrix                       # hostname — lowercase only
  device_friendly_name: ApolloMatrix              # name shown in Home Assistant
```

Leave the `panel_*`, `shift_driver`, `bit_depth` and pin entries alone unless you
rewired the panel.

- **`weather_condition`** — if you have no cloud-condition entity, either point it at
  something harmless or delete the `weather_condition` text sensor and the
  `show_weather_timer` script further down the file. The current firmware only feeds
  them to an unused path, so it makes no visible difference either way.
- **No presence sensor?** Under `# ── Presence gate ──` further down, delete the
  **Option A** block and uncomment **Option B**. The panel then follows the time window
  alone. See [Time-based only](#time-based-only-no-presence-sensor).
- **`device_name`** must stay lowercase letters/digits/dashes — it is the network
  hostname. The capitalised name users see is `device_friendly_name`.

Then validate: **⋮ → Validate**. You want `INFO Configuration is valid!`.

## Step 3 — First flash over USB (the first one cannot be wireless)

The device has no WiFi credentials yet, so the first upload has to be over the cable.

1. Plug the ESP32-S3 into your computer with a USB data cable.
2. In the ESPHome dashboard: **Install → Plug into this computer**. This uses
   WebSerial, so do it in **Chrome or Edge**. The build still runs on your Home
   Assistant host; only the flashing happens locally.
3. Pick the serial port. On Windows it is a `COM` port (you may need the USB-serial
   driver), on macOS something like `/dev/cu.usbserial-*`, on Linux `/dev/ttyUSB0`.
   *No port listed?* Put the board in download mode: hold **BOOT**, tap **RESET**,
   release **BOOT**, then re-check.
4. Wait for **Successfully uploaded**.

Prefer a file? **Install → Manual download** produces a factory `.bin` you can flash
with `esptool.py` or the web installer at <https://web.esphome.io>.

After this first upload, the WiFi credentials are stored on the device, so every later
update is wireless — **Install → Wirelessly (OTA)**, as described in the README.

**Things that look alarming but are not:** the build prints strapping-pin warnings for
`GPIO3` and `GPIO45` (both are used by this board's design), and the first build is
slow while it downloads the ESP-IDF toolchain.

**If the panel stays dark right after flashing, that is usually correct** — it only
lights inside your window while the room is occupied. Go to step 5 to force it on and
prove the panel works.

## Step 4 — Add it to Home Assistant

Home Assistant normally discovers it automatically a few seconds after it joins WiFi:
**Settings → Devices & Services → ESPHome → Configure**, and it appears as
**ApolloMatrix**. If it does not show up, add it manually by hostname
(`apollomatrix.local`) or by IP address.

You get three entities (entity IDs follow `device_name`, so they stay `apollomatrix_*`
with the default):

| Entity | What it does |
|---|---|
| `number.apollomatrix_matrix_brightness` | Panel brightness, 0.1–1.0. A fresh device starts at 0.5 and remembers whatever you set (the reference unit runs 0.2 — dim, easy on the eyes and the LEDs); 1.0 is much brighter. |
| `switch.apollomatrix_matrix_toggle` | **Manual override** — forces the display on regardless of the presence sensor. It still blanks at `off_hour`, which is also when the override resets. |

That is the whole entity list: the config no longer creates an onboard-LED entity (the
board's status LED never lit on this hardware — see the README's Known issues). To tell
whether the panel is currently displaying, look at it, or reason from the inputs:
in-window **and** occupied, or the manual override is on.

## Step 5 — Confirm it works

- Inside the window with the room occupied, weather appears. To test immediately,
  turn on `switch.apollomatrix_matrix_toggle` — that bypasses the presence sensor.
- The panel refreshes every **10 seconds**; allow that long for a change to show.
- Set `number.apollomatrix_matrix_brightness` to `1.0` momentarily: if the panel is
  alive you will see it get much brighter.
- Values travel from Home Assistant over the API. If HA is down or an entity is
  missing, the affected line is simply not drawn — that is by design, not a fault.

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Panel blank inside the window | Room sensor reads unoccupied, or has no state yet. Check `presence_sensor`; force on with **Matrix Toggle** to prove the panel itself is fine. |
| Blank before `start_hour` or after `off_hour` | Expected — that is the window. Widen it in the substitutions block. |
| Very dim | `matrix_brightness` — a fresh device starts at 0.5, the reference unit runs at 0.2. Raise it. |
| A solid block where a character should be | That character is not in the font's baked glyph list (the minus sign was the original offender). Add it to the relevant `glyphs:` entry. See the README's warning about changing text. |
| Right text, wrong colours | Your entities are probably in °F — the ramp is Celsius. See below. |
| Panel dark and nothing at all | Outside the window; or Home Assistant/time not reachable yet — the device needs HA up to get the clock and the readings. |
| Entity "unavailable" in Home Assistant | WiFi or API dropped. Check **Logs** on the device page in the ESPHome dashboard. |
| Build fails on `channel_colors` | Your ESPHome add-on is older than 2026.8. Update it. |
| Build fails fetching fonts | The Home Assistant host has no internet access (Google Fonts). Connect it and rebuild. |
| `GPIO3/GPIO45 strapping pin` warnings | Normal for this board — informational only. |

**Reading logs:** ESPHome dashboard → your device → **Logs**. That is the first place to
look for anything unexpected.

## °F instead of °C

The ramp (−2 … 30 °C), the trend threshold (±0.1 °C) and the formats are all Celsius.
Do not re-scale the ramp. Instead add a template sensor that converts, and point the
substitution at it:

```yaml
sensor:
  - platform: template
    id: temp_c
    lambda: 'return id(temp_f).state;'   # or: (x - 32) * 5 / 9
```

## Time-based only (no presence sensor)

Under `# ── Presence gate ──`, delete the active **Option A** block and uncomment
**Option B** right below it. Option B reports permanently occupied, so the window alone
decides when the panel is lit. The manual override still respects `off_hour`.

## Optional tweaks

- **Window**: `start_hour` / `off_hour` in the substitutions block.
- **Brightness at boot**: `number.apollomatrix_matrix_brightness` is restored across
  reboots, so set it once in Home Assistant and leave it.
- **Preview before flashing**: the `test/` harness renders the panel on a PC
  (`test/run_tests.sh`) — see the README. Handy for checking whether longer text still
  fits, since the widest line currently uses 62 of the 64 pixels. The two fonts it uses
  are not shipped with the project; `python test/fetch_fonts.py --download` fetches
  them (renders work without, just with a plainer caption font).
- **Any change to displayed text** needs the font's `glyphs:` entry extended, because
  glyph bitmaps are baked into the firmware. The README explains the procedure.

## Where to go next

- **README** — the configuration table, hardware details, and renders of the display.
- **`docs/lessons/LESSONS_LEARNT.md`** — why the panel behaves the way it does: the
  window/override logic, why there is no antialiasing, the font internals, and the
  burn-in trade-offs. Worth reading before making behavioural changes.
