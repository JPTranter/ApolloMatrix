#!/usr/bin/env python3
"""Check the docs would render on GitHub.

Guards the properties that quietly break a README once it is published:

  * every relative link target exists
  * every same-file anchor (#heading) matches a real heading
  * every image exists
  * no absolute or file:// link targets (GitHub renders those as dead text)

GitHub's anchor rule: lowercase, drop punctuation, spaces become hyphens — so
punctuation surrounded by spaces leaves double hyphens ("Build / flash" ->
#build--flash-esphome-addon-on-the-ha-server).

Usage: check_docs.py [repo_root]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DOCS = ["README.md", "docs/USER_GUIDE.md", "docs/lessons/LESSONS_LEARNT.md"]


def slug(heading: str) -> str:
    s = heading.strip().lower()
    s = re.sub(r"[^a-z0-9 \-]", "", s)
    return s.replace(" ", "-")


def anchors(text: str) -> set[str]:
    return {slug(m.group(2)) for m in re.finditer(r"^(#{1,6})\s+(.*)$", text, re.M)}


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
    problems: list[str] = []

    for rel in DOCS:
        path = root / rel
        if not path.exists():
            problems.append(f"{rel}: file is missing (linked from the README?)")
            continue
        text = path.read_text(encoding="utf-8")
        have = anchors(text)

        for m in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", text):
            target = m.group(1).strip()
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            if target.startswith("#"):
                if target[1:] not in have:
                    problems.append(f"{rel}: anchor {target} has no matching heading")
                continue
            base, _, frag = target.partition("#")
            if re.match(r"^[A-Za-z]:[/\\]", base) or base.startswith("file:"):
                problems.append(f"{rel}: link target {base} is an absolute/local path")
                continue
            resolved = (path.parent / base).resolve()
            if not resolved.exists():
                problems.append(f"{rel}: link target {base} does not exist")
            elif frag and resolved.suffix == ".md":
                if frag not in anchors(resolved.read_text(encoding="utf-8")):
                    problems.append(f"{rel}: {base}#{frag} has no matching heading")

        for m in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", text):
            src = m.group(1).strip()
            if src.startswith(("http://", "https://")):
                continue
            if not (path.parent / src).exists():
                problems.append(f"{rel}: image {src} does not exist")

    if problems:
        print("DOCS: BROKEN LINKS")
        for p in problems:
            print(f"  - {p}")
        return 1

    print(f"docs: {len(DOCS)} files — all relative links, anchors and images resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
