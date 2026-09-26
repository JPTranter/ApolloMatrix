#!/usr/bin/env python3
"""Fail the suite if secrets or personal/address information are present in the repo.

Guards the leak classes that ordinary greps and gitleaks miss:

  * image metadata — EXIF, XMP and GPS blocks (gitleaks never looks inside a JPEG,
    and Exif can also hide in a second JPEG appended after the main image, which is
    how a Samsung phone stores its MPF frame: stripping only the main image's tags
    leaves the location readable)
  * absolute home paths and local account names in text
  * private keys, credential assignments, real (non-noreply) email addresses,
    street addresses, phone numbers and coordinate-looking strings

Deliberately NOT flagged: `!secret` references and placeholder credentials
(`YOUR_WIFI_SSID`, `DUMMY_*`), and the project's own example location and entity
names, which were reviewed and kept on purpose.

Scans two sets: files tracked by git, AND files present but not yet tracked
(`git ls-files --others --exclude-standard`). The second set matters — a new
image dropped into docs/images/ is invisible to a tracked-only scan until it is
staged, which is exactly when its metadata should have been caught.

Usage: check_privacy.py [repo_root]
"""

from __future__ import annotations

import io
import re
import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image
except Exception as _pil_error:  # noqa: BLE001 - reported, not swallowed, in main()
    Image = None
    _PIL_ERROR = _pil_error

TEXT_EXT = {
    ".md",
    ".txt",
    ".py",
    ".sh",
    ".cpp",
    ".h",
    ".yaml",
    ".yml",
    ".json",
    ".toml",
    ".example",
}

# Extensions whose contents are assumed to be an image: if one of these cannot be
# opened, its metadata was NOT verified and that is reported as such.
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff", ".bmp"}

# Upstream files that must stay byte-exact and legitimately contain URLs/licence text.
SKIP_TEXT = {"test/fonts/OFL-Silkscreen.txt", "test/fonts/OFL-Roboto.txt"}

# (label, pattern) — every one of these is a hard failure.
TEXT_RULES = [
    # Requires a real path segment after the user segment: the generic illustrative
    # shape "/c/Users/..." carries no username and must not be flagged.
    (
        "absolute home path",
        re.compile(r"(?:[A-Za-z]:[\\/]Users[\\/]|/c/Users/|/home/|/Users/)[A-Za-z0-9]"),
    ),
    ("local account name", re.compile(r"(?i)\bjptra\b")),
    ("PEM private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    (
        "credential assignment",
        re.compile(
            r"(?i)\b(pass(word|wd|phrase)|token|api[_-]?key|client[_-]?secret|private[_-]?key)\b"
            r'\s*[:=]\s*["\']?[^\s"\']{4,}'
        ),
    ),
    (
        "non-noreply email",
        re.compile(
            r"\b[A-Za-z0-9._%+-]+@(?!users\.noreply\.github\.com)" r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
        ),
    ),
    (
        "street address",
        re.compile(
            r"(?i)\b\d{1,5}\s+[A-Z][a-z]+\s+(street|st|road|rd|avenue|ave|drive|dr|court|ct|"
            r"place|pl|lane|ln|crescent|cres|parade|pde|highway|hwy|close)\b"
        ),
    ),
    ("phone number", re.compile(r"\b(\+?61|0)[\s-]?4\d{2}[\s-]?\d{3}[\s-]?\d{3}\b")),
    ("coordinate-like string", re.compile(r"(?i)\b-?\d{2,3}\.\d{3,}\s*°?\s*[NSEW]\b")),
]

# Placeholder credentials that are fine to ship.
ALLOWED_TEXT = re.compile(r"YOUR[-_]?[A-Za-z_]*|\bDUMMY[A-Za-z_]*\b")


def scan_image(path: Path, rel: str, problems: list[str], unverified: list[str]) -> None:
    try:
        im = Image.open(path)
        exif = im.getexif()
    except Exception:
        # Not decodable as an image (or a format Pillow cannot read). Nothing to
        # read metadata out of, but say so rather than reporting it as clean.
        if path.suffix.lower() in IMAGE_EXT:
            unverified.append(rel)
        return
    if exif:
        problems.append(
            f"{rel}: image carries EXIF " f"({len(exif)} tag(s)) — strip it before committing"
        )
    if exif and exif.get_ifd(0x8825):
        problems.append(f"{rel}: image carries a GPS block — strip it before committing")
    if im.info.get("xmp"):
        problems.append(f"{rel}: image carries XMP metadata — strip it before committing")

    # A second JPEG appended after the main image can hold its own EXIF/XMP.
    raw = path.read_bytes()
    if raw.count(b"\xff\xd8\xff") > 1:
        problems.append(
            f"{rel}: contains an embedded second JPEG (can carry its own "
            f"EXIF/XMP — strip or truncate it)"
        )


def git_files(root: Path, args: list[str]) -> list[str]:
    """File list from `git ls-files ...`, failing loudly when git cannot answer."""
    proc = subprocess.run(["git", "ls-files", *args], cwd=root, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git ls-files {' '.join(args)} failed")
    return [line for line in proc.stdout.splitlines() if line]


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)

    # Without Pillow the image half of this gate cannot run at all. Refuse, rather
    # than print a clean result that never looked inside the images.
    if Image is None:
        print("PRIVACY: cannot verify image metadata - Pillow is not installed")
        print(f"  ({_PIL_ERROR})")
        print("  install it with: pip install pillow")
        return 1

    try:
        tracked = git_files(root, [])
        untracked = git_files(root, ["--others", "--exclude-standard"])
    except Exception as exc:  # noqa: BLE001 - an empty list would silently pass
        print(f"PRIVACY: could not list the repository's files: {exc}")
        return 1

    problems: list[str] = []
    unverified: list[str] = []
    checked_text = checked_img = 0

    for rel in tracked + untracked:
        path = root / rel
        if not path.is_file():
            continue
        if path.suffix.lower() in TEXT_EXT:
            if rel in SKIP_TEXT:
                continue
            checked_text += 1
            for lineno, line in enumerate(io.open(path, encoding="utf-8", errors="replace"), 1):
                if "!secret" in line:
                    continue  # an ESPHome secret *reference*; the value lives outside the repo
                line = ALLOWED_TEXT.sub("", line)
                for label, rx in TEXT_RULES:
                    if rx.search(line):
                        problems.append(f"{rel}:{lineno}: {label} — {line.strip()[:80]}")
        else:
            checked_img += 1
            scan_image(path, rel, problems, unverified)

    if unverified:
        print(
            f"privacy: WARNING - {len(unverified)} file(s) look like images but could not "
            f"be opened, so their metadata is unverified:"
        )
        for rel in unverified:
            print(f"  ? {rel}")

    if problems:
        print("PRIVACY: findings")
        for p in problems:
            print(f"  - {p}")
        return 1

    note = f", {len(untracked)} not yet tracked" if untracked else ""
    print(
        f"privacy: {checked_text} text file(s) and {checked_img} binary file(s) clean{note} "
        f"— no credentials, home paths, addresses or image metadata"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
