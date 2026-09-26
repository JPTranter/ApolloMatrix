#!/usr/bin/env bash
# apollomatrix host test harness: build -> sync check -> scenarios -> PNGs.
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

# cmake / python / the harness binary are NATIVE Windows programs: they do not
# understand MSYS paths like /c/Users/... . Hand them C:/Users/... instead.
win() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }

rc_sync=0
rc_scen=0

echo "== build =="
cmake -S "$(win "$HERE")" -B "$(win "$BUILD")" -G Ninja -DCMAKE_BUILD_TYPE=Release >/dev/null || exit 1
cmake --build "$(win "$BUILD")" || exit 1

echo
echo "== logic sync check (test/matrix_logic.h vs apollomatrix.yaml) =="
"$PY" "$(win "$HERE/check_sync.py")" "$(win "$HERE/..")" || rc_sync=$?

echo
echo "== font fixtures vs YAML =="
"$PY" "$(win "$HERE/export_font_metrics.py")" --check || rc_sync=$?

echo
echo "== scenarios =="
rm -rf "$OUT/traces" "$OUT/images" "$OUT/png" "$OUT/png_device"
mkdir -p "$OUT/traces"
BIN="$BUILD/render_scenarios"
[ -f "$BIN.exe" ] && BIN="$BIN.exe"
"$(win "$BIN")" "$(win "$OUT/traces")" || rc_scen=$?

echo
echo "== rasterize (crisp: faithful pixel grid) =="
"$PY" "$(win "$HERE/rasterize.py")" "$(win "$OUT/traces")" "$(win "$OUT/images")" --style crisp || exit 1

echo
echo "== rasterize (device: LED look) =="
"$PY" "$(win "$HERE/rasterize.py")" "$(win "$OUT/traces")" "$(win "$OUT/images")" --style device || exit 1

echo
echo "images: $OUT/images    (crisp_* = faithful, device_* = LED look)"

if [ "$rc_sync" -ne 0 ]; then
  echo "RESULT: FAILED - logic drift between apollomatrix.yaml and the harness"
  exit 1
fi
if [ "$rc_scen" -ne 0 ]; then
  echo "RESULT: FAILED - scenario expectation(s) not met"
  exit 1
fi
echo "RESULT: PASSED"
