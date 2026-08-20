"""Text measurement and formatting helpers."""

from __future__ import annotations
import os
import unicodedata

from yas.constants import (
    _ANSI_RE,
    ASCII_TRANSLATE,
    DEFAULT_MAX_WIDTH,
    ELLIPSIS,
    GITHUB_TRANSLATE,
    MIDDLE_DOT,
    STRIKE,
    UNICODE_TRANSLATE,
    UNSTRIKE,
    terminal_width_path,
)


def terminal_width() -> int:
    if 'TMUX_PANE' in os.environ:  # deferred import: only tmux sessions pay the subprocess cost
        import subprocess
        try:
            w = int(subprocess.run([
                "tmux", "display-message", "-p", "-t", f"{os.environ['TMUX_PANE']}", "'#{pane_width}'"
            ], capture_output=True, text=True, timeout=0.2).stdout.strip().replace("'", ""))
            if w > 0:
                return w
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass

    try:
        w = int(terminal_width_path().read_text().strip())
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

    try:
        w = os.get_terminal_size().columns
    except OSError:
        w = 0
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
    if 0x1F800 <= cp <= 0x1F8FF:  # Supplemental Arrows-C is EAW=N; exclude despite being in the emoji range
        return False
    return 0x1F300 <= cp <= 0x1FAFF


def _visible_width(s: str) -> int:
    plain = _ANSI_RE.sub('', s)
    return sum(2 if _is_wide(ch) else 1 for ch in plain)


def strike(s: str) -> str:
    """Wrap `s`'s non-blank core in SGR 9 (strikethrough); leading/trailing spaces stay outside the escape."""
    core = s.strip(' ')
    if not core:
        return s
    lead  = len(s) - len(s.lstrip(' '))
    trail = len(s) - len(s.rstrip(' '))
    return f'{" " * lead}{STRIKE}{core}{UNSTRIKE}{" " * trail}'


def to_ascii(s: str) -> str:
    """Replace every Nerd Font PUA glyph with its single-char ASCII fallback (width-preserving)."""
    return s.translate(ASCII_TRANSLATE)


SINGLEWIDTH_PLACEHOLDER = MIDDLE_DOT  # width-1 stand-in for an unfoldable wide char


def to_singlewidth(s: str) -> str:
    """Fold every double-width char in `s` to a width-1 equivalent (NFKC narrow form, else placeholder)."""
    out: list[str] = []
    for ch in s:
        if not _is_wide(ch):
            out.append(ch)
            continue
        folded = unicodedata.normalize('NFKC', ch)
        if len(folded) == 1 and not _is_wide(folded):
            out.append(folded)
        else:
            out.append(SINGLEWIDTH_PLACEHOLDER)
    return ''.join(out)


def apply_glyph_mode(s: str, mode: str) -> str:
    """Final pass over a finished render: nerdfont=identity, ascii/unicode/github swap PUA glyphs per table."""
    if mode == 'ascii':
        return s.translate(ASCII_TRANSLATE).translate(_SUPERSCRIPT_TO_ASCII)
    if mode == 'unicode':
        return s.translate(UNICODE_TRANSLATE)
    if mode == 'github':
        return s.translate(GITHUB_TRANSLATE).translate(_SUPERSCRIPT_TO_ASCII)
    return s


def apply_glyphs(s: str, mode: str, single_width: bool) -> str:
    """Apply glyph `mode`, then fold double-width chars to width-1 if `single_width`."""
    out = apply_glyph_mode(s, mode)
    if single_width:
        out = to_singlewidth(out)
    return out


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


# ASCII -> Unicode superscript glyphs, all width-1 so _visible_width(superscript(s)) == len(s).
# Letters with no standard superscript form pass through unchanged.
_SUPERSCRIPT = {
    'a': 'ᵃ', 'b': 'ᵇ', 'c': 'ᶜ', 'd': 'ᵈ', 'e': 'ᵉ', 'f': 'ᶠ', 'g': 'ᵍ',
    'h': 'ʰ', 'i': 'ⁱ', 'j': 'ʲ', 'k': 'ᵏ', 'l': 'ˡ', 'm': 'ᵐ', 'n': 'ⁿ',
    'o': 'ᵒ', 'p': 'ᵖ', 'r': 'ʳ', 's': 'ˢ', 't': 'ᵗ', 'u': 'ᵘ', 'v': 'ᵛ',
    'w': 'ʷ', 'x': 'ˣ', 'y': 'ʸ', 'z': 'ᶻ',
    'A': 'ᴬ', 'B': 'ᴮ', 'C': 'ꟲ', 'D': 'ᴰ', 'E': 'ᴱ', 'G': 'ᴳ', 'H': 'ᴴ', 'I': 'ᴵ',
    'J': 'ᴶ', 'K': 'ᴷ', 'L': 'ᴸ', 'M': 'ᴹ', 'N': 'ᴺ', 'O': 'ᴼ', 'P': 'ᴾ',
    'R': 'ᴿ', 'T': 'ᵀ', 'U': 'ᵁ', 'V': 'ⱽ', 'W': 'ᵂ',
    '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵', '6': '⁶',
    '7': '⁷', '8': '⁸', '9': '⁹',
    '+': '⁺', '/': 'ᐟ', ' ': ' ',
}


def superscript(s: str) -> str:
    return ''.join(_SUPERSCRIPT.get(ch, ch) for ch in s)


# inverse of _SUPERSCRIPT, width-preserving, for paste-safe glyph modes (ascii/github)
_SUPERSCRIPT_TO_ASCII = {ord(v): k for k, v in _SUPERSCRIPT.items()}


def _token_offsets(plain: str) -> list[int]:
    """0-indexed start positions of each whitespace-separated run in `plain`."""
    offs: list[int] = []
    i, n = 0, len(plain)
    while i < n:
        if plain[i] != ' ':
            offs.append(i)
            while i < n and plain[i] != ' ':
                i += 1
        else:
            i += 1
    return offs


def fmt_tok(n: int) -> str:
    # promotes at the .1f rounding boundary so output never exceeds 6 visible chars (token column budget)
    if n >= 999_950_000:
        return f'{n/1_000_000_000:.1f}B'
    if n >= 999_950:
        return f'{n/1_000_000:.1f}M'
    if n >= 1000:
        return f'{n/1000:.1f}K'
    return str(n)


def fmt_tok_fixed(n: int) -> str:
    """3-significant-figure `fmt_tok` variant for constant-width subagent-row columns (not used for session/day totals)."""
    if n >= 999_950_000:
        div, suf = 1_000_000_000, 'B'
    elif n >= 999_950:
        div, suf = 1_000_000, 'M'
    elif n >= 1000:
        div, suf = 1_000, 'K'
    else:
        return str(n)
    val = n / div
    for decimals in (2, 1, 0):
        s = f'{val:.{decimals}f}'
        if len(s.split('.')[0]) == 3 - decimals:
            return f'{s}{suf}'
    return f'{val:.0f}{suf}'  # defensive fallback; every n above should hit the loop


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
