"""Text measurement and formatting helpers."""

from __future__ import annotations
import os
import unicodedata

from yas.constants import (
    _ANSI_RE,
    ASCII_TRANSLATE,
    CLAUDE_DIR,
    DEFAULT_MAX_WIDTH,
    ELLIPSIS,
    GITHUB_TRANSLATE,
    MIDDLE_DOT,
    UNICODE_TRANSLATE,
)


def terminal_width() -> int:
    # Deferred: only sessions running under tmux pay the subprocess import +
    # fork/exec; a plain terminal never touches subprocess at all.
    if 'TMUX_PANE' in os.environ:
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

    # os.get_terminal_size (stdout) replaces shutil.get_terminal_size: same
    # probe minus the COLUMNS check already done above, and it avoids pulling
    # shutil -> bz2/lzma/zlib at import time.
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


SINGLEWIDTH_PLACEHOLDER = MIDDLE_DOT  # width-1 stand-in for an unfoldable wide char


def to_singlewidth(s: str) -> str:
    """Fold every double-width char in ``s`` to a width-1 equivalent.

    Walks char-by-char (ANSI escape bytes are ASCII, so ``_is_wide`` is False for
    them and they pass through untouched). For each wide char, try an NFKC
    single-char narrow form (e.g. Fullwidth Forms -> ASCII); if none exists, emit
    SINGLEWIDTH_PLACEHOLDER. Already-width-1 chars (including the statusline's own
    PUA glyphs) are left unchanged, so only genuinely wide dynamic content folds."""
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
    """Apply the selected glyph mode as a single final pass over a finished render.

    nerdfont -> identity (no pass); ascii -> PUA+frame ASCII fallback table;
    unicode -> PUA-only non-PUA Unicode table; github -> browser-wide+PUA fold to
    EAW-narrow/ASCII (paste-safe). An unknown mode is treated as nerdfont
    (identity) — defensive; config already validates the value upstream.
    Single-width folding is orthogonal (see ``apply_glyphs``)."""
    if mode == 'ascii':
        return s.translate(ASCII_TRANSLATE).translate(_SUPERSCRIPT_TO_ASCII)
    if mode == 'unicode':
        return s.translate(UNICODE_TRANSLATE)
    if mode == 'github':
        return s.translate(GITHUB_TRANSLATE).translate(_SUPERSCRIPT_TO_ASCII)
    return s


def apply_glyphs(s: str, mode: str, single_width: bool) -> str:
    """Combine the glyph ``mode`` with the orthogonal ``single_width`` fold.

    Runs ``apply_glyph_mode`` first, then folds double-width chars to width-1
    when ``single_width`` is set, so single-width folding can pair with any
    mode (nerdfont, ascii, or unicode)."""
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


# ASCII -> Unicode superscript glyphs for section labels. Every glyph is a
# non-PUA, width-1 character (modifier letters + the superscript block), so
# `_visible_width(superscript(s)) == len(s)` holds. Characters with no standard
# superscript form (e.g. 'q', and capitals C/F/Q/S/X/Y/Z) are intentionally
# absent and pass through unchanged — substituting a wrong-letter or wide glyph
# would break the width-equals-length invariant the label overlay relies on.
_SUPERSCRIPT = {
    'a': 'ᵃ', 'b': 'ᵇ', 'c': 'ᶜ', 'd': 'ᵈ', 'e': 'ᵉ', 'f': 'ᶠ', 'g': 'ᵍ',
    'h': 'ʰ', 'i': 'ⁱ', 'j': 'ʲ', 'k': 'ᵏ', 'l': 'ˡ', 'm': 'ᵐ', 'n': 'ⁿ',
    'o': 'ᵒ', 'p': 'ᵖ', 'r': 'ʳ', 's': 'ˢ', 't': 'ᵗ', 'u': 'ᵘ', 'v': 'ᵛ',
    'w': 'ʷ', 'x': 'ˣ', 'y': 'ʸ', 'z': 'ᶻ',
    'A': 'ᴬ', 'B': 'ᴮ', 'D': 'ᴰ', 'E': 'ᴱ', 'G': 'ᴳ', 'H': 'ᴴ', 'I': 'ᴵ',
    'J': 'ᴶ', 'K': 'ᴷ', 'L': 'ᴸ', 'M': 'ᴹ', 'N': 'ᴺ', 'O': 'ᴼ', 'P': 'ᴾ',
    'R': 'ᴿ', 'T': 'ᵀ', 'U': 'ᵁ', 'V': 'ⱽ', 'W': 'ᵂ',
    '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵', '6': '⁶',
    '7': '⁷', '8': '⁸', '9': '⁹',
    '+': '⁺', '/': 'ᐟ', ' ': ' ',
}


def superscript(s: str) -> str:
    # Map each character to its superscript glyph, passing unmapped characters
    # through unchanged. Every mapped glyph is width-1, so the result keeps the
    # same visible column width as the input.
    return ''.join(_SUPERSCRIPT.get(ch, ch) for ch in s)


# Inverse of _SUPERSCRIPT: fold the wide-layout section-label superscripts back to
# plain ASCII for the paste-safe glyph modes. The superscript/modifier-letter block
# is non-ASCII (so `ascii` mode would leak it) and partly EAW-ambiguous/browser-wide
# (e.g. ⁿ U+207F, so `github` mode would render it double-width). Every value is a
# distinct width-1 glyph, so this {codepoint: ascii} map is a clean width-preserving
# str.translate table. `unicode` mode keeps the superscripts — they render fine there.
_SUPERSCRIPT_TO_ASCII = {ord(v): k for k, v in _SUPERSCRIPT.items()}


def _token_offsets(plain: str) -> list[int]:
    """0-indexed start positions of each whitespace-separated run in `plain`.

    Used to anchor section labels over the value they name: the caller strips
    ANSI from a rendered content string, finds the value token's start here, and
    adds the section's absolute start column. The glyphs that precede/compose the
    measured values (Nerd-Font PUA icons, arrows) are all width-1, so a codepoint
    position equals a column position for the content this is used on."""
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
