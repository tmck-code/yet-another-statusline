"""Text measurement and formatting helpers."""

from __future__ import annotations
import os
import shutil
import subprocess

from yas.constants import (
    _ANSI_RE,
    ASCII_TRANSLATE,
    CLAUDE_DIR,
    DEFAULT_MAX_WIDTH,
    ELLIPSIS,
)


def terminal_width() -> int:
    try:
        w = int(subprocess.run([
            "tmux", "display-message", "-p", "-t", f"{os.environ['TMUX_PANE']}", "'#{pane_width}'"
        ], capture_output=True, text=True, timeout=0.2).stdout.strip().replace("'", ""))
        if w > 0:
            return w
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        pass

    try:
        w = int((CLAUDE_DIR / 'terminal-width').read_text().strip())
        if w > 0:
            return w
    except (OSError, ValueError):
        pass

    try:
        cols = int(os.environ.get('COLUMNS', '0'))
        if cols > 0:
            return cols
    except ValueError:
        pass

    w = shutil.get_terminal_size(fallback=(0, 0)).columns
    if w > 0:
        return w

    for fd in (2, 1, 0):
        try:
            return os.get_terminal_size(fd).columns
        except OSError:
            pass

    try:
        tty_fd = os.open('/dev/tty', os.O_RDONLY)
        try:
            return os.get_terminal_size(tty_fd).columns
        finally:
            os.close(tty_fd)
    except OSError:
        pass

    return DEFAULT_MAX_WIDTH


def _is_wide(ch: str) -> bool:
    cp = ord(ch)
    # Supplemental Arrows-C (U+1F800-U+1F8FF) are EAW=N despite being in the
    # emoji range — exclude them so arrow icons like 🡅/🡇 count as 1 col.
    if 0x1F800 <= cp <= 0x1F8FF:
        return False
    return 0x1F300 <= cp <= 0x1FAFF


def _visible_width(s: str) -> int:
    plain = _ANSI_RE.sub('', s)
    return sum(2 if _is_wide(ch) else 1 for ch in plain)


def to_ascii(s: str) -> str:
    """Replace every Nerd Font PUA glyph with its single-char ASCII fallback.

    Width-preserving (1 PUA col -> 1 ASCII col), so applying it to a finished
    render leaves every border/elbow column exactly where it was."""
    return s.translate(ASCII_TRANSLATE)


def _middle_ellipsis(text: str, max_w: int) -> str:
    if max_w <= 1:
        return ELLIPSIS
    if _visible_width(text) <= max_w:
        return text
    left_vis  = (max_w - 1) // 2
    right_vis = max_w - 1 - left_vis

    # Tokenise into (is_escape, string) pairs to preserve ANSI across the cut.
    tokens: list[tuple[bool, str]] = []
    i = 0
    while i < len(text):
        m = _ANSI_RE.match(text, i)
        if m:
            tokens.append((True, m.group()))
            i = m.end()
        else:
            tokens.append((False, text[i]))
            i += 1

    def _take(toks: list[tuple[bool, str]], n: int) -> list[str]:
        out: list[str] = []
        seen = 0
        for is_esc, tok in toks:
            if is_esc:
                out.append(tok)
            elif seen < n:
                out.append(tok)
                seen += 1
            else:
                break
        return out

    prefix = _take(tokens, left_vis)
    suffix = _take(list(reversed(tokens)), right_vis)
    suffix.reverse()

    result = ''.join(prefix) + ELLIPSIS + ''.join(suffix)
    if _visible_width(result) <= max_w:
        return result
    # Trim one visible char from prefix to fix wide-char overshoot.
    for j in range(len(prefix) - 1, -1, -1):
        if not _ANSI_RE.fullmatch(prefix[j]):
            prefix.pop(j)
            break
    return ''.join(prefix) + ELLIPSIS + ''.join(suffix)


def fmt_tok(n: int) -> str:
    # Promote at the rounding boundary (>= 999.95 rounds to 1000.0 at .1f) so the
    # result never exceeds 6 visible chars ("999.9B") and stays within the token
    # column budget (IN_W/CACHE_W/OUT_W = 6). Without the billions tier, a
    # multi-billion day total renders as "4660.5M" (7 chars) and pushes that
    # row's dividers one cell out of alignment.
    if n >= 999_950_000:
        return f'{n/1_000_000_000:.1f}B'
    if n >= 999_950:
        return f'{n/1_000_000:.1f}M'
    if n >= 1000:
        return f'{n/1000:.1f}K'
    return str(n)


def fmt_dur(seconds: float) -> str:
    s = int(seconds)
    if s < 0:
        s = 0
    if s < 60:
        return f'{s}s'
    if s < 3600:
        return f'{s // 60}m{s % 60:02d}s'
    return f'{s // 3600}h{(s % 3600) // 60:02d}m'


def sparkline_width(terminal_width: int) -> int:
    if terminal_width >= 130:
        return 30
    if terminal_width >= 110:
        return 20
    if terminal_width >= 90:
        return 10
    return 0
