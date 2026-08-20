"""BorderRenderer: elbow/pill/fill math for top, bottom, separator, and line borders."""

from __future__ import annotations

from yas.constants import (
    BOX_ARC_BL,
    BOX_ARC_BR,
    BOX_ARC_TL,
    BOX_ARC_TR,
    BOX_CROSS,
    BOX_H,
    BOX_H_DASH,
    BOX_H_DASH2,
    BOX_H_DASH4,
    BOX_T_DOWN,
    BOX_T_LEFT,
    BOX_T_RIGHT,
    BOX_T_UP,
    BOX_V,
    ELLIPSIS,
    BOLD,
    BOLD_OFF,
    ITALIC,
    LABEL_ABBREVIATIONS,
    RESET,
)
from yas.render.gradient import GradientEngine
from yas.render.pill import Pill
from yas.render.text import _visible_width, superscript


def _shrink_to_boundary(text: str, run_len: int) -> str | None:
    """Longest whole-word prefix of `text` + `ELLIPSIS` that fits `run_len` columns, or `None`."""
    tokens = text.split(' ')
    for i in range(len(tokens), 0, -1):
        prefix = ' '.join(tokens[:i])
        cand = superscript(prefix) + ELLIPSIS
        if len(cand) <= run_len:
            return cand
    return None


def _fit_label(text: str, run_len: int) -> str | None:
    """Best renderable form of `text` fitting `run_len` columns: full, abbreviation, shrunk, or `None` to drop."""
    sup = superscript(text)
    if len(sup) <= run_len:
        return sup
    abbrev = LABEL_ABBREVIATIONS.get(text, '')
    if abbrev:
        sup_abbrev = superscript(abbrev)
        if len(sup_abbrev) <= run_len:
            return sup_abbrev
        shrunk = _shrink_to_boundary(abbrev, run_len)
        if shrunk is not None:
            return shrunk
    return _shrink_to_boundary(text, run_len)


def _overlay_labels(chars: list[str], fills: list[bool], labels: tuple[tuple[str, int], ...]) -> None:
    """Overlay superscript labels onto fill-only columns; elbows/corners/pill columns are never fill."""
    n = len(chars)
    for text, start_col in labels:
        idx = start_col - 1
        if idx < 0 or idx >= n or not fills[idx]:
            continue  # anchor not on a fill column -> drop
        # contiguous fill run containing the anchor
        run_start = idx
        while run_start - 1 >= 0 and fills[run_start - 1]:
            run_start -= 1
        run_end = idx
        while run_end + 1 < n and fills[run_end + 1]:
            run_end += 1
        run_len = run_end - run_start + 1
        out = _fit_label(text, run_len)
        if out is None:
            continue  # nothing fits; drop
        length = len(out)
        # shift left to fit, never past run_start or the anchor
        start = min(idx, run_end - length + 1)
        start = max(start, run_start)
        for offset, g in enumerate(out):
            i = start + offset
            chars[i] = g
            fills[i] = False  # claim column so later labels yield to it


class BorderRenderer:
    def __init__(self, gradient: GradientEngine):
        self.gradient = gradient
        self.SESSION  = gradient.theme.session

    R = RESET

    def border_top(self, width: int, session_id: str = '', downs: tuple[int, ...] = (), fill: float = 1.0, pill: Pill | None = None, labels: tuple[tuple[str, int], ...] = ()) -> str:
        downs_set = set(downs)
        p = pill or Pill()
        def _ch(col: int) -> str:
            pc = p.border_char(col, 'top')
            if pc:
                return pc
            return BOX_T_DOWN if col in downs_set else BOX_H
        def _clr(col: int, pos: int) -> str:
            if p.active and p.start <= col <= p.end:
                return p.border_fg(col)
            return self.gradient.grad_at(pos, width, fill=fill)
        # per-column glyph + fill mask, 1..width stored 0-indexed; corners/elbows/session id/pill are never fill
        chars: list[str] = [''] * width
        fills: list[bool] = [False] * width
        prefix: list[str] = [''] * width
        suffix: list[str] = [''] * width

        if p.active and p.start <= 1:
            prefix[0] = p.border_fg(p.start)
            chars[0] = p.border_char(p.start, 'top')
        else:
            prefix[0] = self.gradient.grad_at(0, width, fill=fill)
            chars[0] = BOX_ARC_TL
        if session_id:
            avail = max(0, width - 4)
            if p.active and p.end == width and p.start > 5:
                avail = max(0, min(avail, p.start - 5))
            sid = session_id if len(session_id) <= avail else session_id[:max(0, avail - 1)] + ELLIPSIS
            sid_w = _visible_width(sid)
            for col in (2, 3):
                prefix[col - 1] = _clr(col, col - 1)
                chars[col - 1] = _ch(col)
                fills[col - 1] = (chars[col - 1] == BOX_H)
            prefix[3] = self.SESSION + ITALIC
            chars[3] = sid
            suffix[3 + sid_w - 1] = '\033[23m'
            offset = 3 + sid_w
            rest = max(0, width - 4 - sid_w)
            for i in range(rest):
                col = offset + i + 1
                prefix[col - 1] = _clr(col, offset + i)
                chars[col - 1] = _ch(col)
                fills[col - 1] = (chars[col - 1] == BOX_H)
        else:
            for i in range(1, width - 1):
                col = i + 1
                prefix[col - 1] = _clr(col, i)
                chars[col - 1] = _ch(col)
                fills[col - 1] = (chars[col - 1] == BOX_H)

        if p.active and p.start <= width <= p.end:
            prefix[width - 1] = p.border_fg(width)
            chars[width - 1] = p.border_char(width, 'top')
        else:
            prefix[width - 1] = self.gradient.grad_at(width - 1, width, fill=fill)
            chars[width - 1] = BOX_ARC_TR

        _overlay_labels(chars, fills, labels)

        parts: list[str] = []
        for i in range(width):
            parts += [prefix[i], chars[i], suffix[i]]
        parts.append(self.R)
        return ''.join(parts)

    # version-tag glyphs sweep theme grey -> brighter grey, left to right
    VERSION_BRIGHT_RGB = (160, 160, 160)

    def border_bottom(self, width: int, ups: tuple[int, ...] = (), fill: float = 1.0, timing: str = '', version: str = '') -> str:
        ups_set = set(ups)
        chars: list[str] = [BOX_ARC_BL]
        for i in range(width - 2):
            chars.append(BOX_T_UP if (i + 2) in ups_set else BOX_H)
        chars.append(BOX_ARC_BR)
        # `[timing ]version` overlaid right-aligned into the bottom edge; glyphs only land on plain fill columns
        annotation = f'{timing}{BOX_H_DASH4}{version}' if timing and version else (timing or version)
        version_cols: set[int] = set()
        if annotation:
            start = width - 3 - _visible_width(annotation)
            if start >= 1:
                version_from = len(annotation) - len(version) if version else len(annotation)
                for off, g in enumerate(annotation):
                    idx = start + off
                    if 0 <= idx < width and chars[idx] == BOX_H:
                        chars[idx] = g
                        if off >= version_from:
                            version_cols.add(idx)
                # dashed lead-in/out ramp on each side of the annotation, only over plain fill cells
                for dist, dash in enumerate((BOX_H_DASH4, BOX_H_DASH, BOX_H_DASH2), 1):
                    left, right = start - dist, start + len(annotation) - 1 + dist
                    if left >= 1 and chars[left] == BOX_H:
                        chars[left] = dash
                    if right < width - 1 and chars[right] == BOX_H:
                        chars[right] = dash
        parts: list[str] = []
        # same fill/off boundary formula as grad_at, so the version tag lands on the exact same column
        denom = max(1, width - 1)
        for i in range(width):
            if i in version_cols:
                if (i / denom) <= fill:
                    clr = self.gradient.grad_at(i, width, fill=fill)  # already inside the fill -> merge with it
                else:
                    lo, hi = min(version_cols), max(version_cols)
                    u = (i - lo) / max(1, hi - lo)
                    gr, gg, gb = self.gradient.GREY_RGB
                    br, bg, bb = self.VERSION_BRIGHT_RGB
                    vr, vg, vb = (int(gr + (br - gr) * u), int(gg + (bg - gg) * u), int(gb + (bb - gb) * u))
                    clr = f'\033[38;2;{vr};{vg};{vb}m'
                parts += [f'{BOLD}{clr}', chars[i]]
            else:
                clr = self.gradient.grad_at(i, width, fill=fill)
                if (i - 1) in version_cols:
                    clr = BOLD_OFF + clr
                parts += [clr, chars[i]]
        parts.append(self.R)
        return ''.join(parts)

    def border_separator(self, width: int, ups: tuple[int, ...] = (), downs: tuple[int, ...] = (), fill: float = 1.0, labels: tuple[tuple[str, int], ...] = ()) -> str:
        ups_set = set(ups)
        downs_set = set(downs)
        chars: list[str] = [''] * width
        fills: list[bool] = [False] * width
        prefix: list[str] = [''] * width
        prefix[0] = self.gradient.grad_at(0, width, fill=fill)
        chars[0] = BOX_T_RIGHT
        for i in range(width - 2):
            col = i + 2
            if col in downs_set and col in ups_set:
                ch = BOX_CROSS
            elif col in downs_set:
                ch = BOX_T_DOWN
            elif col in ups_set:
                ch = BOX_T_UP
            else:
                ch = BOX_H
            prefix[col - 1] = self.gradient.grad_at(i + 1, width, fill=fill)
            chars[col - 1] = ch
            fills[col - 1] = (ch == BOX_H)
        prefix[width - 1] = self.gradient.grad_at(width - 1, width, fill=fill)
        chars[width - 1] = BOX_T_LEFT
        _overlay_labels(chars, fills, labels)
        parts: list[str] = []
        for i in range(width):
            parts += [prefix[i], chars[i]]
        parts.append(self.R)
        return ''.join(parts)

    DIM_MIN  = 0.6
    DIM_RAMP = 5

    def _dim_for_col(self, col: int, elbow_cols: set[int]) -> float:
        d = min(abs(col - e) for e in elbow_cols)
        if d == 0:
            return 1.0
        return max(self.DIM_MIN, 1.0 - (1.0 - self.DIM_MIN) * (d / self.DIM_RAMP))

    def border_separator_dim(self, width: int, downs: tuple[int, ...] = (), ups: tuple[int, ...] = (), fill: float = 1.0, pill: Pill | None = None, pill_edge: str = 'bottom', labels: tuple[tuple[str, int], ...] = ()) -> str:
        downs_set = set(downs)
        ups_set = set(ups)
        elbow_cols = {1, width} | downs_set | ups_set
        p = pill or Pill()
        edge = pill_edge if pill_edge == 'top' else 'bottom'
        chars: list[str] = [''] * width
        fills: list[bool] = [False] * width
        prefix: list[str] = [''] * width
        if p.active and p.start <= 1:
            prefix[0] = p.border_fg(p.start)
            chars[0] = p.border_char(p.start, edge)
        else:
            prefix[0] = self.gradient.grad_at(0, width, self._dim_for_col(1, elbow_cols), fill=fill)
            chars[0] = BOX_T_RIGHT
        for i in range(width - 2):
            col = i + 2
            pc = p.border_char(col, edge) if p.active else ''
            if pc:
                prefix[col - 1] = p.border_fg(col)
                chars[col - 1] = pc
            else:
                if col in downs_set and col in ups_set:
                    ch = BOX_CROSS
                elif col in downs_set:
                    ch = BOX_T_DOWN
                elif col in ups_set:
                    ch = BOX_T_UP
                else:
                    ch = BOX_H_DASH
                # dim factor baked into the colour prefix, so an overlaid label glyph inherits it for free
                prefix[col - 1] = self.gradient.grad_at(i + 1, width, self._dim_for_col(col, elbow_cols), fill=fill)
                chars[col - 1] = ch
                fills[col - 1] = (ch == BOX_H_DASH)
        if p.active and p.start <= width <= p.end:
            prefix[width - 1] = p.border_fg(width)
            chars[width - 1] = p.border_char(width, edge)
        else:
            prefix[width - 1] = self.gradient.grad_at(width - 1, width, self._dim_for_col(width, elbow_cols), fill=fill)
            chars[width - 1] = BOX_T_LEFT
        _overlay_labels(chars, fills, labels)
        parts: list[str] = []
        for i in range(width):
            parts += [prefix[i], chars[i]]
        parts.append(self.R)
        return ''.join(parts)

    def border_line(self, content: str, width: int, fill: float = 1.0, bg_lead: str = '', bg_trail: str = '', pill_flush: bool = False, right_pill: str = '') -> str:
        if right_pill:
            pill_w  = _visible_width(right_pill)
            pad     = max(0, width - 2 - _visible_width(content) - pill_w)
            left    = self.gradient.grad_at(0, width, fill=fill)
            lead    = f'{bg_lead} \033[49m' if bg_lead else ' '
            return f'{left}{BOX_V}{self.R}{lead}{content}{" " * pad}{right_pill}{self.R}'
        if pill_flush:
            pad = max(0, width - 1 - _visible_width(content))
            right = self.gradient.grad_at(width - 1, width, fill=fill)
            pad_str = ' ' * pad
            return f'{content}{pad_str}{right}{BOX_V}{self.R}'
        pad = max(0, width - 3 - _visible_width(content))
        left  = self.gradient.grad_at(0, width, fill=fill)
        right = self.gradient.grad_at(width - 1, width, fill=fill)
        lead = f'{bg_lead} \033[49m' if bg_lead else ' '
        if bg_trail and pad > 0:
            pad_str = f'{" " * (pad - 1)}{bg_trail} \033[49m'
        else:
            pad_str = ' ' * pad
        return f'{left}{BOX_V}{self.R}{lead}{content}{pad_str}{right}{BOX_V}{self.R}'
