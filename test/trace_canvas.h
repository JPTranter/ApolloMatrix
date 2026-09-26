// test/trace_canvas.h
//
// A Canvas implementation that does not rasterize: it RECORDS the draw calls
// made by matrix_logic.h and serializes them to JSON. rasterize.py turns that
// trace into a PNG using the real Silkscreen/Roboto fonts (see test/fonts/).
//
// Splitting it this way means the geometry/colour logic is genuinely compiled
// from C++ (the part under test), while glyph rasterization uses the actual
// typefaces instead of an approximation.

#pragma once

#include <string>
#include <vector>

#include "matrix_logic.h"

namespace matrix {

class TraceCanvas {
 public:
  struct Op {
    std::string kind;  // "fill" | "text" | "line" | "pixel"
    int x = 0, y = 0, x2 = 0, y2 = 0;
    Rgb color{0, 0, 0};
    Font font = Font::Small;
    Align align = Align::Left;
    std::string text;
  };

  static constexpr int kWidth = 64;
  static constexpr int kHeight = 64;

  void fill(Rgb c) { ops_.push_back(Op{"fill", 0, 0, 0, 0, c, Font::Small, Align::Left, ""}); }
  void text(int x, int y, Font f, Rgb c, Align a, const std::string &s) {
    ops_.push_back(Op{"text", x, y, 0, 0, c, f, a, s});
  }
  void line(int x1, int y1, int x2, int y2, Rgb c) {
    ops_.push_back(Op{"line", x1, y1, x2, y2, c, Font::Small, Align::Left, ""});
  }
  void pixel(int x, int y, Rgb c) {
    ops_.push_back(Op{"pixel", x, y, 0, 0, c, Font::Small, Align::Left, ""});
  }

  const std::vector<Op> &ops() const { return ops_; }

 private:
  std::vector<Op> ops_;
};

}  // namespace matrix
