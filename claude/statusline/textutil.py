"""Pure text / width / number-formatting helpers for the statusline.

No dependency on runtime config, themes, or the renderer — just stdlib. Split
out of statusline_command.py (Phase 2) so the renderer and the future
data-collection core can share them without importing the monolith.
"""
from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')

# Untrusted-string sanitizer. Strips C0/C1 control bytes and DEL so attacker-
# authored field values (git branch, model name, transcript/subagent content,
# repo settings keys) cannot inject terminal escapes (OSC-52 clipboard write,
# OSC-0/2 title spoof) or newline-based extra rows into the rendered statusline.
# ESC (0x1b), BEL (0x07), CR/LF/TAB and the 8-bit C1 introducers all fall in
# this class. Apply at the point a field is CAPTURED from an untrusted source,
# never to the final rendered line (which legitimately carries the renderer's
# own SGR colour codes).
_CTRL_RE = re.compile(r'[\x00-\x1f\x7f-\x9f]')


def _sanitize(s: str) -> str:
    'Strip C0/C1 control characters and DEL from an untrusted string.'
    return _CTRL_RE.sub('', s)


def _atomic_write_text(path: Path, text: str) -> None:
    '''Best-effort atomic write: write to a sibling temp file, then os.replace
    (atomic on POSIX and Windows) onto the target so a reader or a cancelled
    render never sees a half-written file. Swallows OSError — these are
    telemetry/cache files, and a failed write simply means the next render
    recomputes. The PID-suffixed temp name avoids concurrent-render collisions.'''
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
        with open(tmp, 'w', encoding='utf-8') as fh:
            fh.write(text)
        os.replace(tmp, path)
    except OSError:
        pass


def _char_width(ch: str) -> int:
    '''Display columns for a single character: 0, 1, or 2.

    Combining marks and format chars (ZWJ, variation selectors, BiDi controls)
    occupy no cell. East-Asian Wide/Fullwidth characters (CJK, Hangul,
    fullwidth forms) and emoji occupy two. Everything else is one. Previously
    only the emoji block was treated as wide, so CJK/fullwidth/Hangul in a cwd,
    branch, model, or session name under-counted and overflowed the box (Audit
    CWIDTH). Residual limits (per-codepoint, so unresolvable here): ZWJ emoji
    sequences, regional-indicator flag pairs, and U+FE0F-promoted glyphs.'''
    if unicodedata.combining(ch) or unicodedata.category(ch) in ('Mn', 'Me', 'Cf'):
        return 0
    cp = ord(ch)
    # Supplemental Arrows-C (U+1F800-U+1F8FF) are EAW=N despite being in the
    # emoji range — keep arrow icons like 🡅/🡇 at 1 col.
    if 0x1F800 <= cp <= 0x1F8FF:
        return 1
    if 0x1F300 <= cp <= 0x1FAFF:  # emoji / pictographs (render 2-wide even when EAW=N)
        return 2
    if unicodedata.east_asian_width(ch) in ('W', 'F'):
        return 2
    return 1


def _is_wide(ch: str) -> bool:
    'True iff the character occupies two display columns. Kept for callers/tests.'
    return _char_width(ch) == 2


def _visible_width(s: str) -> int:
    plain = _ANSI_RE.sub('', s)
    return sum(_char_width(ch) for ch in plain)


def _middle_ellipsis(text: str, max_w: int) -> str:
    if max_w <= 1:
        return '…'
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

    def _take(toks: list[tuple[bool, str]], budget: int) -> list[str]:
        # Accumulate by VISIBLE width, not codepoint count, so a wide char that
        # would push past the budget is refused rather than silently spending one
        # slot but two cells (Audit CTRUNC). Escapes are free (zero width).
        out: list[str] = []
        used = 0
        for is_esc, tok in toks:
            if is_esc:
                out.append(tok)
                continue
            w = _char_width(tok)
            if used + w > budget:
                break
            out.append(tok)
            used += w
        return out

    prefix = _take(tokens, left_vis)
    suffix = _take(list(reversed(tokens)), right_vis)
    suffix.reverse()

    result = ''.join(prefix) + '…' + ''.join(suffix)
    # Defensive: with width-aware _take the result already fits, but guard the
    # contract (visible width <= max_w) by trimming visible chars off the longer
    # side until it holds, degrading to '…' rather than ever overflowing.
    while _visible_width(result) > max_w:
        side = prefix if _visible_width(''.join(prefix)) >= _visible_width(''.join(suffix)) else suffix
        for j in range(len(side) - 1, -1, -1):
            if not _ANSI_RE.fullmatch(side[j]):
                side.pop(j)
                break
        else:
            break  # nothing left to trim but escapes
        result = ''.join(prefix) + '…' + ''.join(suffix)
    return result


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
