#!/usr/bin/env python3
"""Drift guard: the YAML lambda and the host harness copy must stay in step.

test/matrix_logic.h is a COPY of the display lambda in ApolloMatrix.yaml (the YAML
is authoritative for the device). Nothing can make a copy self-updating, so this
script asserts that a set of load-bearing expressions - the gating conditions, the
trend thresholds, the text formats and the layout anchors - still appear in BOTH
files after whitespace/identifier normalization.

This is a SMOKE CHECK, not proof of equivalence: it catches renames, moved
coordinates and changed formats. When you edit the lambda, still diff this file
against it by eye.

Usage: check_sync.py [repo_root]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def normalize(text: str) -> str:
    t = text.replace("\\xC2\\xB0", "\u00b0")   # C++ escape -> the degree sign
    t = t.replace('"', "")                      # drop quotes (C++ adjacent literals
                                                # like "FEELS %.1f\xC2\xB0""C" split tokens)
    t = re.sub(r"\s+", "", t)                   # drop all whitespace
    return t


def lambda_block(yaml_text: str) -> str:
    """The display lambda body (the part that must match the harness)."""
    m = re.search(r"^    lambda:\s*\|-\n(.*)$", yaml_text, re.M | re.S)
    if not m:
        raise SystemExit("could not locate the display lambda in ApolloMatrix.yaml")
    return m.group(1)


# (label, yaml token, harness token)
CHECKS = [
    ("window is substitution-driven",
     "now.hour>=${start_hour}&&now.hour<off_h",
     "in.hour>=8&&in.hour<off_h"),
    ("override respects cutoff",
     "id(manual_override)&&now.hour<off_h",
     "manual_override&&in.hour<off_h"),
    ("presence gate needs state",
     "id(room_presence).has_state()&&id(room_presence).state",
     "in.presence_sensor_has_state&&in.presence_present"),
    ("date line anchor",
     "strftime(32,6",
     "text(32,6"),
    ("temperature line anchor",
     "printf(31,22",
     "text(31,22"),
    ("FEELS line anchor",
     "printf(32,38",
     "text(32,38"),
    ("HMDTY line anchor",
     "printf(32,48",
     "text(32,48"),
    ("DEWPT line anchor",
     "printf(32,58",
     "text(32,58"),
    ("trend anchor x", "ax=54", "ax=54"),
    ("trend anchor y", "ay=21", "ay=21"),
    ("trend up threshold", "if(temp>prev+0.1)", "if(temp>prev+0.1)"),
    ("trend down threshold", "elseif(temp<prev-0.1)", "elseif(temp<prev-0.1)"),
    ("FEELS format", "FEELS%.1f\u00b0C", "FEELS%.1f\u00b0C"),
    ("HMDTY format", "HMDTY%.0f%%", "HMDTY%.0f%%"),
    ("DEWPT format", "DEWPT%.1f\u00b0C", "DEWPT%.1f\u00b0C"),
    ("ramp: <=2C", "temp<=2.0", "temp<=2.0"),
    ("ramp: <10C", "temp<10.0", "temp<10.0"),
    ("ramp: <20C", "temp<20.0", "temp<20.0"),
    ("ramp: <25C", "temp<25.0", "temp<25.0"),
    ("ramp: <30C", "temp<30.0", "temp<30.0"),
    ("temperature text dimmed by brightness",
     "tc.red*=bri;tc.green*=bri;tc.blue*=bri;",
     "tc.r*bri,tc.g*bri,tc.b*bri"),
    ("date/time format zero-padded",
     "%d/%m%H:%M",
     "%02d/%02d%02d:%02d"),
]


def parse_substitutions(yaml_text: str) -> dict:
    """Top-level `substitutions:` block -> {name: value} (quotes and comments stripped)."""
    m = re.search(r"^substitutions:\n(.*?)(?=^\S)", yaml_text, re.M | re.S)
    if not m:
        return {}
    subs = {}
    for line in m.group(1).splitlines():
        line = line.split("#", 1)[0]          # drop trailing comments
        mm = re.match(r"\s+([A-Za-z_]\w*):\s*(.*?)\s*$", line)
        if mm and mm.group(2):
            subs[mm.group(1)] = mm.group(2).strip().strip("'\"")
    return subs


def mirror_checks(subs: dict, harness_text: str, scenarios_text: str) -> list[str]:
    """The harness mirrors the YAML's *defaults*; assert the numbers still agree.

    Since the visibility window became substitution-driven, a string compare against
    the harness literal is no longer meaningful - compare the values instead, so a
    change to `start_hour`/`off_hour` in the config block cannot silently leave the
    harness testing a different window.
    """
    problems = []

    # A missing key must FAIL, not skip: silently passing here would mean the harness
    # could be testing a different window from the one the config actually uses.
    start = subs.get("start_hour")
    if start is None:
        problems.append("start_hour: missing from the `substitutions:` block — "
                        "cannot verify the harness's window start")
    else:
        m = re.search(r"in\.hour\s*>=\s*(\d+)", harness_text)
        if not m:
            problems.append("harness: no `in.hour >= N` to mirror start_hour")
        elif int(m.group(1)) != int(start):
            problems.append(f"start_hour: YAML default {start} vs test/matrix_logic.h {m.group(1)}")

    off = subs.get("off_hour")
    if off is None:
        problems.append("off_hour: missing from the `substitutions:` block — "
                        "cannot verify the harness's cutoff")
    else:
        m = re.search(r"in\.off_hour\s*=\s*(\d+)", scenarios_text)
        if not m:
            problems.append("scenarios: no `in.off_hour = N` to mirror off_hour")
        elif int(m.group(1)) != int(off):
            problems.append(f"off_hour: YAML default {off} vs test/main.cpp {m.group(1)}")

    return problems


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
    yaml_text = (root / "ApolloMatrix.yaml").read_text(encoding="utf-8")
    harness_text = (root / "test" / "matrix_logic.h").read_text(encoding="utf-8")
    scenarios_text = (root / "test" / "main.cpp").read_text(encoding="utf-8")

    hay_yaml = normalize(lambda_block(yaml_text))
    hay_harness = normalize(harness_text)

    problems = []
    for label, yaml_token, harness_token in CHECKS:
        y = normalize(yaml_token)
        h = normalize(harness_token)
        if y not in hay_yaml and h not in hay_harness:
            problems.append(f"{label}: missing from BOTH files ({yaml_token!r})")
        elif y not in hay_yaml:
            problems.append(f"{label}: {yaml_token!r} not found in the YAML lambda")
        elif h not in hay_harness:
            problems.append(f"{label}: {harness_token!r} not found in test/matrix_logic.h")

    subs = parse_substitutions(yaml_text)
    if not subs:
        problems.append("no `substitutions:` block found in ApolloMatrix.yaml")
    problems += mirror_checks(subs, harness_text, scenarios_text)

    if problems:
        print("LOGIC SYNC: DRIFT DETECTED")
        for p in problems:
            print(f"  - {p}")
        print("\nUpdate test/matrix_logic.h to mirror ApolloMatrix.yaml (or vice versa),")
        print("then re-run test/run_tests.sh.")
        return 1

    print(f"logic sync: {len(CHECKS)} canonical expressions present in both; "
          f"{len(subs)} substitution(s) parsed and the window defaults mirror the harness")
    return 0


if __name__ == "__main__":
    sys.exit(main())
