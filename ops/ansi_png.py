"""Render an ANSI snapshot (.txt) into a PNG, deterministically and headlessly.

The demo writes each scenario's statusline as a true-colour ANSI .txt (see
ops/demo.py --snapshots).  This turns one of those into a PNG suitable for
before/after comparison screenshots in PRs, without photographing a terminal:

    ANSI .txt  ->  Pango markup  ->  `magick` (Pangocairo)  ->  trimmed PNG

Pango resolves the Nerd Font Private-Use-Area glyphs through fontconfig and
honours per-span foreground/background/bold/italic, so the result matches what
the statusline looks like in a Nerd-Font terminal.  Everything is pinned (font,
size, background, padding) so the same .txt always yields a byte-stable PNG,
which is what makes a/b diffs meaningful.

Usage:
    uv run python3 ops/ansi_png.py demo/tasks.txt demo/tasks.png

Env knobs (all optional):
    YAS_DEMO_FONT  font family               (default: IosevkaTerm Nerd Font Mono)
    YAS_DEMO_SIZE  font size in points       (default: 14)
    YAS_DEMO_BG    terminal background hex    (default: #0d1117)
    YAS_DEMO_FG    default foreground hex     (default: #c9d1d9)
    YAS_DEMO_PAD   padding px around content  (default: 24)
    YAS_DEMO_DPI   render density / DPI       (default: 192, ~2x for crisp text)
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# Default render settings.  A *Mono* Nerd Font is required: the statusline aligns
# its box borders by cell count, so every glyph (icons and box-drawing included)
# must occupy exactly one cell.  Propo/non-mono variants would skew the borders.
DEFAULT_FONT = 'IosevkaTerm Nerd Font Mono'
DEFAULT_SIZE = '14'
DEFAULT_BG   = '#0d1117'
DEFAULT_FG   = '#c9d1d9'
DEFAULT_PAD  = '24'
DEFAULT_DPI  = '192'

# Splits a string into alternating literal-text and SGR-escape tokens.
SGR_RE   = re.compile(r'(\x1b\[[0-9;]*m)')
# Strips any stray non-SGR escape (cursor moves, OSC, ...) from literal text.
OTHER_RE = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)')

# Standard xterm 16-colour palette, for `38;5;0..15` / `48;5;0..15`.
PALETTE_16 = (
    (0x00, 0x00, 0x00), (0x80, 0x00, 0x00), (0x00, 0x80, 0x00), (0x80, 0x80, 0x00),
    (0x00, 0x00, 0x80), (0x80, 0x00, 0x80), (0x00, 0x80, 0x80), (0xc0, 0xc0, 0xc0),
    (0x80, 0x80, 0x80), (0xff, 0x00, 0x00), (0x00, 0xff, 0x00), (0xff, 0xff, 0x00),
    (0x00, 0x00, 0xff), (0xff, 0x00, 0xff), (0x00, 0xff, 0xff), (0xff, 0xff, 0xff),
)
# 6-level cube axis used for `38;5;16..231`.
CUBE_LEVELS = (0, 95, 135, 175, 215, 255)


def xterm256_to_hex(n: int) -> str:
    """Map an xterm 256-colour index to a #rrggbb string."""
    if n < 16:
        r, g, b = PALETTE_16[n]
    elif n < 232:
        i = n - 16
        r = CUBE_LEVELS[(i // 36) % 6]
        g = CUBE_LEVELS[(i //  6) % 6]
        b = CUBE_LEVELS[ i        % 6]
    else:
        v = 8 + (n - 232) * 10
        r = g = b = v
    return f'#{r:02x}{g:02x}{b:02x}'


def pango_escape(text: str) -> str:
    """Escape the three characters that are special in Pango markup."""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


class SgrState:
    """Mutable SGR attribute state, threaded across an ANSI string."""

    __slots__ = ('fg', 'bg', 'bold', 'italic', 'underline')

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.fg        = None
        self.bg        = None
        self.bold      = False
        self.italic    = False
        self.underline = False

    def apply(self, params: list[int]) -> None:
        """Fold one SGR escape's parameters into the current state."""
        # Empty params (`ESC[m`) is shorthand for reset.
        if not params:
            self.reset()
            return
        i = 0
        while i < len(params):
            p = params[i]
            if   p == 0:               self.reset()
            elif p == 1:               self.bold      = True
            elif p == 22:              self.bold      = False
            elif p == 3:               self.italic    = True
            elif p == 23:              self.italic    = False
            elif p == 4:               self.underline = True
            elif p == 24:              self.underline = False
            elif p == 39:              self.fg        = None
            elif p == 49:              self.bg        = None
            elif 30 <= p <= 37:        self.fg        = xterm256_to_hex(p - 30)
            elif 90 <= p <= 97:        self.fg        = xterm256_to_hex(p - 90 + 8)
            elif 40 <= p <= 47:        self.bg        = xterm256_to_hex(p - 40)
            elif 100 <= p <= 107:      self.bg        = xterm256_to_hex(p - 100 + 8)
            elif p in (38, 48):
                # Extended colour: `38;5;n`, `38;2;r;g;b` (and the 48 bg twins).
                target = 'fg' if p == 38 else 'bg'
                if i + 1 < len(params) and params[i + 1] == 5:
                    setattr(self, target, xterm256_to_hex(params[i + 2]))
                    i += 2
                elif i + 1 < len(params) and params[i + 1] == 2:
                    r, g, b = params[i + 2], params[i + 3], params[i + 4]
                    setattr(self, target, f'#{r:02x}{g:02x}{b:02x}')
                    i += 4
            i += 1

    def wrap(self, text: str) -> str:
        """Wrap already-escaped text in a <span> carrying the current attrs."""
        attrs = []
        if self.fg        is not None: attrs.append(f'foreground="{self.fg}"')
        if self.bg        is not None: attrs.append(f'background="{self.bg}"')
        if self.bold:                  attrs.append('weight="bold"')
        if self.italic:                attrs.append('style="italic"')
        if self.underline:             attrs.append('underline="single"')
        if not attrs:
            return text
        return f'<span {" ".join(attrs)}>{text}</span>'


def ansi_to_pango(ansi: str) -> str:
    """Convert an ANSI string into Pango markup."""
    state = SgrState()
    out   = []
    for tok in SGR_RE.split(ansi):
        if not tok:
            continue
        if tok.startswith('\x1b['):
            body   = tok[2:-1]
            params = [int(x) for x in body.split(';') if x != ''] if body else []
            state.apply(params)
        else:
            text = OTHER_RE.sub('', tok)
            if text:
                out.append(state.wrap(pango_escape(text)))
    return ''.join(out)


def render_png(txt_path: Path, png_path: Path) -> None:
    """Render an ANSI .txt snapshot to a trimmed PNG via Pango + ImageMagick."""
    font = os.environ.get('YAS_DEMO_FONT', DEFAULT_FONT)
    size = os.environ.get('YAS_DEMO_SIZE', DEFAULT_SIZE)
    bg   = os.environ.get('YAS_DEMO_BG',   DEFAULT_BG)
    fg   = os.environ.get('YAS_DEMO_FG',   DEFAULT_FG)
    pad  = os.environ.get('YAS_DEMO_PAD',  DEFAULT_PAD)
    dpi  = os.environ.get('YAS_DEMO_DPI',  DEFAULT_DPI)

    ansi = txt_path.read_text().strip('\n')
    body = ansi_to_pango(ansi)
    # A root span pins the font family/size and the default (non-SGR) foreground;
    # inner spans override colour/style per run.
    markup = f'<span font_family="{font}" font_size="{size}pt" foreground="{fg}">{body}</span>'

    png_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', suffix='.pango', delete=False) as fh:
        fh.write(markup)
        markup_path = fh.name
    try:
        subprocess.run(
            [
                'magick',
                '-background', bg,
                '-density',    dpi,
                f'pango:@{markup_path}',
                '-trim', '+repage',
                '-bordercolor', bg, '-border', pad,
                str(png_path),
            ],
            check=True,
        )
    finally:
        os.unlink(markup_path)
    print(f'  wrote {png_path}')


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(f'usage: {argv[0]} <input.txt> <output.png>', file=sys.stderr)
        return 2
    render_png(Path(argv[1]), Path(argv[2]))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
