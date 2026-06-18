---
name: yas-demo-text
description: Convert `make demo/img` statusline snapshots into ANSI-stripped plain text for diffing and PR embedding. Use when comparing statusline renders before/after a change, producing a text representation of a demo scenario, or preparing before/after statusline output for a pull request without screenshots.
---

# YAS demo text

`make demo/img` writes ANSI-coloured statusline snapshots to `demo/<scenario>.txt`
(and per-theme renders under `demo/themes/`). This skill strips the ANSI escape
sequences so the box-drawing layout survives as plain, diff-able, paste-able text.

## Quick start

Render the snapshots, then strip them into `demo/text/` (mirrors the `demo/` tree):

```bash
make demo/img                                   # or: DEMO_ONLY=tasks make demo/img
.claude/skills/yas-demo-text/scripts/demo-text.sh
```

`demo/text/<scenario>.txt` now holds the colour-free render. Both `demo/` and
`demo/text/` are gitignored, so these are scratch artifacts — diff them, paste
them, regenerate them; don't commit them.

## Strip arbitrary output

`scripts/strip-ansi.sh` is a plain ANSI filter (stdin or named files → stdout),
wrapping `sed 's/\x1B\[[0-9;]\{1,\}[A-Za-z]//g'`:

```bash
COLUMNS=160 uv run python claude/statusline_command.py < ops/session-info-example.json \
  | .claude/skills/yas-demo-text/scripts/strip-ansi.sh
```

## Before/after comparison

```bash
make demo/img && .claude/skills/yas-demo-text/scripts/demo-text.sh
cp -r demo/text /tmp/yas-before        # stash the baseline
# ... make your renderer change ...
make demo/img && .claude/skills/yas-demo-text/scripts/demo-text.sh
diff -ru /tmp/yas-before demo/text     # see exactly which cells moved
```

## Notes

- The strip regex matches CSI sequences (`\x1B[…<letter>`), removing colour,
  bold and italic; it leaves box-drawing and Nerd Font glyphs intact, so column
  alignment is preserved exactly.
- Nerd Font PUA glyphs render as boxes outside a Nerd-Font terminal (e.g. on
  GitHub), but the layout and text labels still read clearly.
- The repo's Python `strip_ansi` (`test/helper.py`) is SGR-only and for tests;
  this skill's sed filter is broader and for the demo snapshots.
