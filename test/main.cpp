// test/main.cpp
//
// Scenario runner for the apollomatrix display logic.
//
// For each scenario it runs matrix::render() (the host-side port of the ESPHome
// display lambda) through a TraceCanvas, ASSERTS the gating result, and writes a
// draw-op trace to JSON. rasterize.py turns those traces into PNGs with the real
// Silkscreen/Roboto fonts.
//
// Exit code 0 = every scenario matched its expectation, 1 = at least one did not.
//
// Usage: render_scenarios [output_dir]      (default: output/traces)

#include <cstdio>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

#include "matrix_logic.h"
#include "trace_canvas.h"

namespace {

struct Scenario {
  std::string name;
  std::string description;
  matrix::Inputs in;
  bool expect_active;
};

// Baseline: a plausible live reading from the device's HA sensors at 10:32,
// with the brightness the device currently reports (0.2).
matrix::Inputs base() {
  matrix::Inputs in{};
  in.time_valid = true;
  in.hour = 10;
  in.minute = 32;
  in.day = 26;
  in.month = 9;

  in.presence_sensor_has_state = true;
  in.presence_present = true;

  in.manual_override = false;
  in.brightness = 0.2f;
  in.off_hour = 22;          // mirrors `off_hour` in apollomatrix.yaml (checked by check_sync.py)

  in.temp_valid = true;
  in.temp = 11.4f;
  in.temp_prev = 11.4f;

  in.feels_valid = true;
  in.feels = 9.3f;
  in.humidity_valid = true;
  in.humidity = 99.0f;
  in.dew_valid = true;
  in.dew = 11.2f;

  return in;
}

std::vector<Scenario> build_scenarios() {
  std::vector<Scenario> s;
  auto add = [&](const std::string &name, const std::string &desc, matrix::Inputs in,
                 bool active) {
    s.push_back(Scenario{name, desc, in, active});
  };

  // ---- the room-presence gate ---------------------------------------------
  {
    auto in = base();
    add("window_occupied_10am", "In window (08:00-22:00) and room occupied -> shown", in,
        true);
  }
  {
    auto in = base();
    in.hour = 14; in.presence_present = false;
    add("window_vacant_1400", "In window but room empty -> blank", in, false);
  }
  {
    auto in = base();
    in.hour = 12; in.presence_sensor_has_state = false; in.presence_present = true;
    add("presence_sensor_no_state", "HA presence sensor has no state -> fail dark", in, false);
  }

  // ---- the 08:00 start / 22:00 cutoff window ------------------------------
  {
    auto in = base();
    in.hour = 7; in.minute = 30;
    add("before_8am_0730", "Occupied but before the 08:00 start -> blank", in, false);
  }
  {
    auto in = base();
    in.hour = 8; in.minute = 0;
    add("first_minute_0800", "08:00 exactly is inside the window (hour >= 8) -> shown", in, true);
  }
  {
    auto in = base();
    in.hour = 21; in.minute = 59;
    add("last_minute_2159", "21:59 is the last showing minute -> shown", in, true);
  }
  {
    auto in = base();
    in.hour = 22; in.minute = 0;
    add("at_cutoff_2200", "22:00 exactly is outside the window (hour < 22) -> blank", in, false);
  }

  // ---- manual override (Matrix Toggle) ------------------------------------
  {
    auto in = base();
    in.hour = 7; in.presence_present = false; in.manual_override = true;
    add("override_before_8am", "Manual override bypasses BOTH presence and the 08:00 start",
        in, true);
  }
  {
    auto in = base();
    in.hour = 14; in.presence_present = false; in.manual_override = true;
    add("override_room_empty", "Manual override with the room empty -> shown", in, true);
  }
  {
    auto in = base();
    in.hour = 23; in.minute = 10; in.presence_present = false; in.manual_override = true;
    add("override_after_cutoff", "Manual override does NOT survive the 22:00 cutoff -> blank",
        in, false);
  }

  // ---- temperature colour ramp + trend arrow ------------------------------
  {
    auto in = base();
    in.temp = 1.0f; in.temp_prev = 1.0f;
    add("temp_cold_ice", "temp <= 2C -> ice white, no trend arrow", in, true);
  }
  {
    auto in = base();
    in.temp = 6.0f; in.temp_prev = 6.0f;
    add("temp_freezing_blue", "temp in the 2-10C ramp -> white->blue mix", in, true);
  }
  {
    auto in = base();
    in.temp = 32.0f; in.temp_prev = 32.0f;
    add("temp_hot_red", "temp >= 30C -> red", in, true);
  }
  {
    auto in = base();
    in.temp = -5.4f; in.temp_prev = -5.4f;
    add("temp_negative",
        "Sub-zero temperature: a real minus sign is drawn (the Roboto glyph set now "
        "includes '-'; before that it drew Font::print()'s placeholder rectangle)", in,
        true);
  }
  {
    auto in = base();
    in.temp = 12.0f; in.temp_prev = 11.0f;
    add("trend_up", "temp > anchor + 0.1 -> upward red arrow", in, true);
  }
  {
    auto in = base();
    in.temp = 11.0f; in.temp_prev = 12.0f;
    add("trend_down", "temp < anchor - 0.1 -> downward blue arrow", in, true);
  }
  {
    auto in = base();
    in.temp = 11.4f; in.temp_prev = 11.4f;
    add("trend_flat", "temp within +/-0.1 of the anchor -> no arrow", in, true);
  }

  // ---- brightness + missing HA sensors ------------------------------------
  {
    auto in = base();
    in.brightness = 1.0f;
    add("full_brightness", "brightness 1.0 for comparison against the 0.2 baseline", in, true);
  }
  {
    auto in = base();
    in.temp_valid = false; in.feels_valid = false;
    in.humidity_valid = false; in.dew_valid = false;
    add("no_ha_sensors", "No weather data: only the date/time is drawn",
        in, true);
  }
  {
    auto in = base();
    in.time_valid = false;
    add("time_invalid", "HA time not yet valid -> blank even though occupied", in, false);
  }

  return s;
}

std::string json_escape(const std::string &s) {
  std::string out;
  for (char c : s) {
    if (c == '"' || c == '\\') { out += '\\'; out += c; }
    else if (c == '\n') { out += "\\n"; }
    else if (static_cast<unsigned char>(c) < 0x20) { /* drop control chars */ }
    else { out += c; }
  }
  return out;
}

std::string rgb_json(const matrix::Rgb &c) {
  char buf[32];
  snprintf(buf, sizeof(buf), "[%u,%u,%u]", c.r, c.g, c.b);
  return buf;
}

void write_trace(const std::filesystem::path &path, int index, const Scenario &sc,
                 const matrix::TraceCanvas &canvas, const matrix::Result &res, bool pass) {
  std::ofstream f(path, std::ios::binary);
  f << "{\n";
  f << "  \"name\": \"" << json_escape(sc.name) << "\",\n";
  f << "  \"description\": \"" << json_escape(sc.description) << "\",\n";
  f << "  \"index\": " << index << ",\n";
  f << "  \"panel\": {\"width\": " << matrix::TraceCanvas::kWidth
    << ", \"height\": " << matrix::TraceCanvas::kHeight << ", \"bg\": "
    << rgb_json(canvas.ops().empty() ? matrix::Rgb{0, 0, 0} : canvas.ops().front().color) << "},\n";
  f << "  \"display_active\": " << (res.display_active ? "true" : "false") << ",\n";
  f << "  \"pass\": " << (pass ? "true" : "false") << ",\n";
  f << "  \"expect\": {\"display_active\": " << (sc.expect_active ? "true" : "false") << "},\n";
  f << "  \"ops\": [\n";
  const auto &ops = canvas.ops();
  for (size_t i = 0; i < ops.size(); ++i) {
    const auto &op = ops[i];
    f << "    {\"kind\": \"" << op.kind << "\"";
    if (op.kind == "text") {
      f << ", \"x\": " << op.x << ", \"y\": " << op.y
        << ", \"align\": \"" << (op.align == matrix::Align::Center ? "center" : "left") << "\""
        << ", \"font\": \"" << (op.font == matrix::Font::Large ? "large" : "small") << "\""
        << ", \"color\": " << rgb_json(op.color)
        << ", \"text\": \"" << json_escape(op.text) << "\"";
    } else if (op.kind == "line") {
      f << ", \"x1\": " << op.x << ", \"y1\": " << op.y << ", \"x2\": " << op.x2
        << ", \"y2\": " << op.y2 << ", \"color\": " << rgb_json(op.color);
    } else if (op.kind == "pixel") {
      f << ", \"x\": " << op.x << ", \"y\": " << op.y << ", \"color\": " << rgb_json(op.color);
    } else {
      f << ", \"color\": " << rgb_json(op.color);
    }
    f << "}" << (i + 1 < ops.size() ? "," : "") << "\n";
  }
  f << "  ]\n}\n";
}

}  // namespace

int main(int argc, char **argv) {
  const std::string out_dir = (argc > 1) ? argv[1] : "output/traces";
  std::filesystem::create_directories(out_dir);

  const auto scenarios = build_scenarios();

  int failures = 0;
  printf("%-28s %-9s %s\n", "scenario", "display", "result");
  printf("%s\n", std::string(64, '-').c_str());

  int index = 0;
  for (const auto &sc : scenarios) {
    matrix::TraceCanvas canvas;
    const matrix::Result res = matrix::render(canvas, sc.in);

    const bool pass = (res.display_active == sc.expect_active);
    if (!pass) ++failures;

    char name_buf[64];
    snprintf(name_buf, sizeof(name_buf), "%02d_%s", index, sc.name.c_str());
    write_trace(std::filesystem::path(out_dir) / (std::string(name_buf) + ".json"), index, sc,
                canvas, res, pass);

    char detail[128];
    snprintf(detail, sizeof(detail), "display=%s (want display=%s)",
             res.display_active ? "on" : "off", sc.expect_active ? "on" : "off");
    printf("%-28s %-9s %s\n", sc.name.c_str(), res.display_active ? "on" : "off",
           pass ? "PASS" : "FAIL");
    if (!pass) printf("    %s\n", detail);

    ++index;
  }

  printf("%s\n", std::string(64, '-').c_str());
  printf("%d scenario(s), %d failure(s)\n", static_cast<int>(scenarios.size()), failures);
  printf("traces -> %s\n", out_dir.c_str());
  return failures == 0 ? 0 : 1;
}
