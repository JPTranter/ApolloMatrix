// test/matrix_logic.h
//
// Host-side PORT of the display lambda in ../apollomatrix.yaml.
//
// SYNC CONTRACT
// -------------
// ../apollomatrix.yaml is the source of truth for device behaviour. This file is
// a COPY of its lambda so the gating + drawing logic can be compiled and
// rendered on a PC without the ESP-IDF toolchain (which does not build here).
// A copy can drift.
//
// Whenever the YAML lambda changes, mirror the change here, then run:
//     test/run_tests.sh
// `test/check_sync.py` (invoked by run_tests.sh) asserts that the canonical
// expressions listed there still appear in BOTH files. It catches renames and
// coordinate/format changes, not every possible drift — keep them in step by hand.
//
// Everything below mirrors the lambda line-for-line, including ESPHome's
// truncating esphome::Color(float,float,float) conversion, so pixel colours and
// text positions match the panel.

#pragma once

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <string>

// MinGW/glibc hide M_PI under -std=c++17 (strict ANSI). ESPHome's build has it,
// so provide the same value here to keep the port literal.
#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

namespace matrix {

struct Rgb {
  uint8_t r, g, b;
};

// font: entries in apollomatrix.yaml
//   weather_font   = Silkscreen 8px  -> Font::Small
//   weather_font_l = Roboto 14px     -> Font::Large
enum class Font { Small, Large };
enum class Align { Left, Center };

// Mirrors the state of the ESPHome globals/entities the lambda reads.
struct Inputs {
  // id(ha_time).now()
  bool time_valid;
  int hour;
  int minute;
  int day;
  int month;

  // id(lounge_presence): the lambda tests has_state() && state
  bool presence_sensor_has_state;
  bool presence_present;

  bool manual_override;   // id(manual_override)           (Matrix Toggle switch)
  float brightness;       // id(matrix_brightness).state    (Matrix Brightness number)
  int off_hour;           // id(off_hour_cutoff)            (= 22)

  // id(current_temp) / id(temp_30m)
  bool temp_valid;
  float temp;
  float temp_prev;

  bool feels_valid;    float feels;      // id(current_feels_like)
  bool humidity_valid; float humidity;   // id(current_humidity)
  bool dew_valid;      float dew;        // id(current_dew_point)

  uint32_t millis;        // drives the burn-in drift phase
};

enum class LedState { Off, On, Unchanged };

struct Result {
  bool display_active = false;
  LedState led = LedState::Off;
  Rgb led_color{0, 0, 0};      // status LED colour (pre-brightness, as set_rgb gets it)
  float led_brightness = 0.0f; // call.set_brightness(bri)
};

// esphome::Color(float, float, float) truncates toward zero into uint8_t.
static inline uint8_t u8(float v) { return static_cast<uint8_t>(v); }

static inline Rgb rgb(float r, float g, float b) { return Rgb{u8(r), u8(g), u8(b)}; }

// The temperature -> colour ramp, ported verbatim (white->blue->cyan->green->orange->red).
static inline Rgb temp_color(float temp) {
  const Rgb ice = Rgb{255, 255, 255}, blue = Rgb{0, 0, 255}, cyan = Rgb{0, 255, 255},
            green = Rgb{0, 255, 0}, orange = Rgb{255, 120, 0}, red = Rgb{255, 0, 0};

  if (temp <= 2.0) {
    return ice;
  } else if (temp < 10.0) {
    float r = (temp - 2.0) / 8.0;
    return rgb(ice.r + r * (blue.r - ice.r), ice.g + r * (blue.g - ice.g), ice.b + r * (blue.b - ice.b));
  } else if (temp < 20.0) {
    float r = (temp - 10.0) / 10.0;
    return rgb(blue.r + r * (cyan.r - blue.r), blue.g + r * (cyan.g - blue.g), blue.b + r * (cyan.b - blue.b));
  } else if (temp < 25.0) {
    float r = (temp - 20.0) / 5.0;
    return rgb(cyan.r + r * (green.r - cyan.r), cyan.g + r * (green.g - cyan.g), cyan.b + r * (green.b - cyan.b));
  } else if (temp < 30.0) {
    float r = (temp - 25.0) / 5.0;
    return rgb(green.r + r * (orange.r - green.r), green.g + r * (orange.g - green.g), green.b + r * (orange.b - green.b));
  }
  return red;
}

// One frame of the panel. Canvas must provide:
//   void fill(Rgb), void text(int x,int y,Font,Rgb,Align,const std::string&),
//   void line(int x1,int y1,int x2,int y2,Rgb), void pixel(int x,int y,Rgb)
template <typename Canvas>
Result render(Canvas &it, const Inputs &in) {
  Result res;

  const float bri = in.brightness;
  const int off_h = in.off_hour;

  const bool in_window = (in.hour >= 8 && in.hour < off_h);
  const bool lounge_present = in.presence_sensor_has_state && in.presence_present;
  const bool auto_on = (in_window && lounge_present);
  const bool forced_on = (in.manual_override && in.hour < off_h);

  char buf[64];

  if (in.time_valid && (auto_on || forced_on)) {
    res.display_active = true;
    res.led = LedState::Unchanged;  // the lambda only touches the LED when temp has state
    it.fill(Rgb{0, 0, 0});

    const float drift_phase = (in.millis % 60000) / 60000.0f * 2.0f * M_PI;
    const int dx = static_cast<int8_t>(roundf(sinf(drift_phase) * 1.5f));
    const int dy = static_cast<int8_t>(roundf(cosf(drift_phase) * 1.5f));

    snprintf(buf, sizeof(buf), "%02d/%02d %02d:%02d", in.day, in.month, in.hour, in.minute);
    it.text(32 + dx, 6 + dy, Font::Small, rgb(255 * bri, 255 * bri, 255 * bri), Align::Center, buf);

    if (in.temp_valid) {
      const float temp = in.temp;
      const float prev = in.temp_prev;
      const Rgb tc = temp_color(temp);

      // --- UPDATE ONBOARD STATUS LED WITH HEARTBEAT ---
      // (LED takes the temperature colour at brightness bri; the matrix below is
      //  dimmed by bri the same way the lambda scales tc by bri.)
      res.led = LedState::On;
      res.led_color = tc;
      res.led_brightness = bri;

      const Rgb dimmed = rgb(tc.r * bri, tc.g * bri, tc.b * bri);
      snprintf(buf, sizeof(buf), "%.1f\xC2\xB0""C", temp);
      it.text(31 + dx, 22 + dy, Font::Large, dimmed, Align::Center, buf);

      // --- TREND ARROW (30m Anchor) ---
      const int ax = 54 + dx;
      const int ay = 21 + dy;

      if (temp > prev + 0.1) {
        const Rgb up_col = rgb(255 * bri, 0, 0);
        it.pixel(ax + 2, ay - 3, up_col);
        it.line(ax + 1, ay - 2, ax + 3, ay - 2, up_col);
        it.line(ax, ay - 1, ax + 4, ay - 1, up_col);
        it.line(ax - 1, ay, ax + 5, ay, up_col);
      } else if (temp < prev - 0.1) {
        const Rgb dn_col = rgb(0, 0, 255 * bri);
        it.line(ax - 1, ay - 3, ax + 5, ay - 3, dn_col);
        it.line(ax, ay - 2, ax + 4, ay - 2, dn_col);
        it.line(ax + 1, ay - 1, ax + 3, ay - 1, dn_col);
        it.pixel(ax + 2, ay, dn_col);
      }
    }

    if (in.feels_valid) {
      snprintf(buf, sizeof(buf), "FEELS %.1f\xC2\xB0""C", in.feels);
      it.text(32 + dx, 38 + dy, Font::Small, rgb(255 * bri, 20 * bri, 60 * bri), Align::Center, buf);
    }
    if (in.humidity_valid) {
      snprintf(buf, sizeof(buf), "HMDTY %.0f%%", in.humidity);
      it.text(32 + dx, 48 + dy, Font::Small, rgb(0, 255 * bri, 255 * bri), Align::Center, buf);
    }
    if (in.dew_valid) {
      snprintf(buf, sizeof(buf), "DEWPT %.1f\xC2\xB0""C", in.dew);
      it.text(32 + dx, 58 + dy, Font::Small, rgb(0, 255 * bri, 0), Align::Center, buf);
    }

  } else {
    res.display_active = false;
    it.fill(Rgb{0, 0, 0});
    res.led = LedState::Off;
    res.led_color = Rgb{0, 0, 0};
    res.led_brightness = 0.0f;
  }

  return res;
}

}  // namespace matrix
