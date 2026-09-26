#!/usr/bin/env bash
# ApolloMatrix host test harness: privacy -> build -> sync checks -> scenarios -> PNGs.
#
# This runs entirely on the PC. It does NOT build or flash firmware: the ESPHome
# firmware is built on the HA server's ESPHome addon (see README).
#
# Usage: test/run_tests.sh
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD="$HERE/build"
OUT="$HERE/output"
PY="${PYTHON:-python}"
CMAKE="${CMAKE:-cmake}"

# cmake / python / the harness binary are NATIVE Windows programs: they do not
# understand MSYS paths like /c/Users/... . Hand them C:/Users/... instead.
win() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }

# Fail clearly instead of with "cmake: command not found" when the build tools
# aren't on this shell's PATH.
if ! command -v "$CMAKE" >/dev/null 2>&1; then
  echo "error: '$CMAKE' not found on PATH."
  echo "       Install CMake + Ninja, or point at them explicitly, e.g.:"
  echo "         CMAKE='/c/Program Files/CMake/bin/cmake.exe' bash test/run_tests.sh"
  exit 1
fi
if [ -n "${NINJA:-}" ] && ! command -v "$NINJA" >/dev/null 2>&1; then
  echo "error: NINJA='$NINJA' not found on PATH."
  exit 1
fi

# Name a missing Python package instead of dying with a traceback four steps later.
# CI hit exactly that: pillow was installed, numpy was not, and the device-style
# render - the last step of the run - was the first thing to notice.
missing=""
for mod in PIL numpy; do
  "$PY" -c "import $mod" >/dev/null 2>&1 || missing="$missing $mod"
done
if [ -n "$missing" ]; then
  echo "error: missing Python package(s):$missing"
  echo "       install them with: $PY -m pip install pillow numpy"
  exit 1
fi

rc_priv=0
rc_sync=0
rc_scen=0

# Privacy first: it needs no build, and it is the one gate that also looks at files
# that are not tracked yet - i.e. at the thing we are about to commit. Failing here
# costs nothing; failing after the build wastes it.
echo "== privacy (secrets, home paths, image metadata - tracked + untracked) =="
"$PY" "$(win "$HERE/check_privacy.py")" "$(win "$HERE/..")" || rc_priv=$?

echo
echo "== build =="
cmake_args=(-G Ninja)
[ -n "${NINJA:-}" ] && cmake_args+=("-DCMAKE_MAKE_PROGRAM=$(win "$NINJA")")
"$CMAKE" -S "$(win "$HERE")" -B "$(win "$BUILD")" "${cmake_args[@]}" \
  -DCMAKE_BUILD_TYPE=Release >/dev/null || exit 1
"$CMAKE" --build "$(win "$BUILD")" || exit 1

echo
echo "== logic sync check (test/matrix_logic.h vs ApolloMatrix.yaml) =="
"$PY" "$(win "$HERE/check_sync.py")" "$(win "$HERE/..")" || rc_sync=$?

echo
echo "== font fixtures vs YAML =="
"$PY" "$(win "$HERE/export_font_metrics.py")" --check || rc_sync=$?

echo
echo "== docs links / anchors (as GitHub would render them) =="
"$PY" "$(win "$HERE/check_docs.py")" "$(win "$HERE/..")" || rc_sync=$?

echo
echo "== scenarios =="
rm -rf "$OUT/traces" "$OUT/images" "$OUT/png" "$OUT/png_device"
mkdir -p "$OUT/traces"
BIN="$BUILD/render_scenarios"
[ -f "$BIN.exe" ] && BIN="$BIN.exe"
"$(win "$BIN")" "$(win "$OUT/traces")" || rc_scen=$?

echo
echo "== rasterize (crisp: faithful pixel grid) =="
if [ ! -f "$HERE/fonts/Silkscreen-Regular.ttf" ] || [ ! -f "$HERE/fonts/Roboto-Regular.ttf" ]; then
  echo "note: preview fonts are not present (not distributed with this repo)."
  echo "      Renders still work; only the caption font falls back."
  echo "      Fetch them with: python test/fetch_fonts.py --download"
fi
"$PY" "$(win "$HERE/rasterize.py")" "$(win "$OUT/traces")" "$(win "$OUT/images")" --style crisp || exit 1

echo
echo "== rasterize (device: LED look) =="
"$PY" "$(win "$HERE/rasterize.py")" "$(win "$OUT/traces")" "$(win "$OUT/images")" --style device || exit 1

echo
echo "images: $OUT/images    (crisp_* = faithful, device_* = LED look)"

if [ "$rc_priv" -ne 0 ]; then
  echo "RESULT: FAILED - secrets, personal data or image metadata present in the repo"
  exit 1
fi
if [ "$rc_sync" -ne 0 ]; then
  echo "RESULT: FAILED - logic drift between ApolloMatrix.yaml and the harness"
  exit 1
fi
if [ "$rc_scen" -ne 0 ]; then
  echo "RESULT: FAILED - scenario expectation(s) not met"
  exit 1
fi
echo "RESULT: PASSED"
