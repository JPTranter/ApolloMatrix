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
