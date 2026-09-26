# Contributing

This is a small project: one ESPHome configuration plus a host test harness. PRs that
keep those two in step are very welcome.

## Before you open a PR

```bash
cd ApolloMatrix          # every path in the docs is relative to the repo root
test/run_tests.sh        # must be green
```

That runs the whole gate: builds the harness, checks `test/matrix_logic.h` still mirrors
the display lambda in `ApolloMatrix.yaml`, checks the glyph fixtures, checks the docs'
links and images, runs 20 scenario assertions, and renders both image styles.

- **Touching `ApolloMatrix.yaml`?** Mirror the change in `test/matrix_logic.h`. The sync
  check tells you if you missed it.
- **Changing displayed text** (a label, a unit letter)? Extend that font's `glyphs:` entry
  and re-run `test/export_font_metrics.py`. Glyph bitmaps are baked at build time, and a
  missing character renders as a solid block.
- **Changing the configuration surface?** Update the README's table *and* the User Guide's
  substitution block — `docs/USER_GUIDE.md` is what a new owner follows.

Optional hygiene: `pip install pre-commit && pre-commit install` adds the secret scan and
whitespace/EOF hooks. CI runs the same secret scan over full history anyway.

## Commits

Conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:` …), one logical change
per commit, imperative subject line.

## What cannot be tested here

The firmware is built and flashed by ESPHome on a Home Assistant add-on, not by this repo,
and only the physical panel confirms what it *looks* like. If your change is verified by
the harness alone, say so in the PR description.

## Fonts

`test/fonts/*.ttf` are third-party font software and deliberately **not** distributed:
`python test/fetch_fonts.py --download` fetches them. Everything still renders without
them (the caption font falls back), so you do not need them to run the suite.
