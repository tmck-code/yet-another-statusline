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
    BOX_T_DOWN,
    BOX_T_LEFT,
    BOX_T_RIGHT,
    BOX_T_UP,
    BOX_V,
    ELLIPSIS,
    ITALIC,
    RESET,
)
from yas.render.gradient import GradientEngine
from yas.render.pill import Pill
from yas.render.text import _visible_width, superscript


def _overlay_labels(chars: list[str], fills: list[bool], labels: tuple[tuple[str, int], ...]) -> None:
    """Overlay superscript labels onto fill-only columns of a 0-indexed buffer.

    Each label is `(text, start_col)` with `start_col` 1-indexed. Glyphs are
    written left-to-right from the anchor across contiguous fill columns only,
    truncating at the first non-fill column and dropping entirely if the anchor
    is not a fill column. Writes in place, never changing buffer length, so
    elbows / corners / session id / pill columns are never disturbed.

    A column a label writes is itself marked non-fill, so a later label in the
    same call cannot overwrite an earlier one: a colliding label truncates (or
    drops, when its anchor is already taken) rather than garbling into it.
    Labels are processed in the given order, so anchors should be left-to-right.
    """
    n = len(chars)
    for text, start_col in labels:
        glyphs = superscript(text)
        col = start_col
        for g in glyphs:
            idx = col - 1
            if idx < 0 or idx >= n or not fills[idx]:
                break
            chars[idx] = g
            fills[idx] = False  # claim the column so later labels yield to it
            col += 1


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
        # Per-column base glyph + fill-only mask (1..width stored 0-indexed). A
        # column is fill only when it is plain '─' (overwritable by a label);
        # corners, elbows, session id, and pill columns are never fill.
        chars: list[str] = [''] * width
        fills: list[bool] = [False] * width
        # Colour prefix per column; session-id run is emitted as one block on
        # its first column so the ordered pass stays byte-identical to before.
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
            # cols 2 and 3 are fill-form '─'/'┬'/pill; the session id occupies
            # the next sid_w columns as a single coloured italic run.
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

    def border_bottom(self, width: int, ups: tuple[int, ...] = (), fill: float = 1.0) -> str:
        ups_set = set(ups)
        parts = [self.gradient.grad_at(0, width, fill=fill), BOX_ARC_BL]
        for i in range(width - 2):
            ch = BOX_T_UP if (i + 2) in ups_set else BOX_H
            parts += [self.gradient.grad_at(i + 1, width, fill=fill), ch]
        parts += [self.gradient.grad_at(width - 1, width, fill=fill), BOX_ARC_BR, self.R]
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
                # Per-column dim factor stays baked into the colour prefix, so an
                # overlaid label glyph inherits the same dim for free.
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
