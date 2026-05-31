"""BorderRenderer: elbow/pill/fill math for top, bottom, separator, and line borders."""

from __future__ import annotations

from statusline.constants import ITALIC, RESET
from statusline.gradient import GradientEngine
from statusline.pill import Pill
from statusline.text import _visible_width


class BorderRenderer:
    def __init__(self, gradient: GradientEngine):
        self.gradient = gradient
        self.SESSION  = gradient.theme.session

    R = RESET

    def border_top(self, width: int, session_id: str = '', downs: tuple[int, ...] = (), fill: float = 1.0, pill: Pill | None = None) -> str:
        downs_set = set(downs)
        p = pill or Pill()
        def _ch(col: int) -> str:
            pc = p.border_char(col, 'top')
            if pc:
                return pc
            return '┬' if col in downs_set else '─'
        def _clr(col: int, pos: int) -> str:
            if p.active and p.start <= col <= p.end:
                return p.border_fg(col)
            return self.gradient.grad_at(pos, width, fill=fill)
        if p.active and p.start <= 1:
            parts = [p.border_fg(p.start), p.border_char(p.start, 'top')]
        else:
            parts = [self.gradient.grad_at(0, width, fill=fill), '╭']
        if session_id:
            avail = max(0, width - 4)
            if p.active and p.end == width and p.start > 5:
                avail = max(0, min(avail, p.start - 5))
            sid = session_id if len(session_id) <= avail else session_id[:max(0, avail - 1)] + '…'
            sid_w = _visible_width(sid)
            parts += [_clr(2, 1), _ch(2), _clr(3, 2), _ch(3), self.SESSION, ITALIC, sid, '\033[23m']
            offset = 3 + sid_w
            rest = max(0, width - 4 - sid_w)
            for i in range(rest):
                col = offset + i + 1
                parts += [_clr(col, offset + i), _ch(col)]
        else:
            for i in range(1, width - 1):
                col = i + 1
                parts += [_clr(col, i), _ch(col)]
        if p.active and p.start <= width <= p.end:
            parts += [p.border_fg(width), p.border_char(width, 'top'), self.R]
        else:
            parts += [self.gradient.grad_at(width - 1, width, fill=fill), '╮', self.R]
        return ''.join(parts)

    def border_bottom(self, width: int, ups: tuple[int, ...] = (), fill: float = 1.0) -> str:
        ups_set = set(ups)
        parts = [self.gradient.grad_at(0, width, fill=fill), '╰']
        for i in range(width - 2):
            ch = '┴' if (i + 2) in ups_set else '─'
            parts += [self.gradient.grad_at(i + 1, width, fill=fill), ch]
        parts += [self.gradient.grad_at(width - 1, width, fill=fill), '╯', self.R]
        return ''.join(parts)

    def border_separator(self, width: int, ups: tuple[int, ...] = (), fill: float = 1.0) -> str:
        ups_set = set(ups)
        parts = [self.gradient.grad_at(0, width, fill=fill), '├']
        for i in range(width - 2):
            ch = '┴' if (i + 2) in ups_set else '─'
            parts += [self.gradient.grad_at(i + 1, width, fill=fill), ch]
        parts += [self.gradient.grad_at(width - 1, width, fill=fill), '┤', self.R]
        return ''.join(parts)

    DIM_MIN  = 0.6
    DIM_RAMP = 5

    def _dim_for_col(self, col: int, elbow_cols: set[int]) -> float:
        d = min(abs(col - e) for e in elbow_cols)
        if d == 0:
            return 1.0
        return max(self.DIM_MIN, 1.0 - (1.0 - self.DIM_MIN) * (d / self.DIM_RAMP))

    def border_separator_dim(self, width: int, downs: tuple[int, ...] = (), ups: tuple[int, ...] = (), fill: float = 1.0, pill: Pill | None = None, pill_edge: str = 'bottom') -> str:
        downs_set = set(downs)
        ups_set = set(ups)
        elbow_cols = {1, width} | downs_set | ups_set
        p = pill or Pill()
        edge = pill_edge if pill_edge == 'top' else 'bottom'
        if p.active and p.start <= 1:
            parts = [p.border_fg(p.start), p.border_char(p.start, edge)]
        else:
            parts = [self.gradient.grad_at(0, width, self._dim_for_col(1, elbow_cols), fill=fill), '├']
        for i in range(width - 2):
            col = i + 2
            pc = p.border_char(col, edge) if p.active else ''
            if pc:
                parts += [p.border_fg(col), pc]
            else:
                if col in downs_set and col in ups_set:
                    ch = '┼'
                elif col in downs_set:
                    ch = '┬'
                elif col in ups_set:
                    ch = '┴'
                else:
                    ch = '┄'
                parts += [self.gradient.grad_at(i + 1, width, self._dim_for_col(col, elbow_cols), fill=fill), ch]
        if p.active and p.start <= width <= p.end:
            parts += [p.border_fg(width), p.border_char(width, edge), self.R]
        else:
            parts += [self.gradient.grad_at(width - 1, width, self._dim_for_col(width, elbow_cols), fill=fill), '┤', self.R]
        return ''.join(parts)

    def border_line(self, content: str, width: int, fill: float = 1.0, bg_lead: str = '', bg_trail: str = '', pill_flush: bool = False, right_pill: str = '') -> str:
        if right_pill:
            pill_w  = _visible_width(right_pill)
            pad     = max(0, width - 2 - _visible_width(content) - pill_w)
            left    = self.gradient.grad_at(0, width, fill=fill)
            lead    = f'{bg_lead} \033[49m' if bg_lead else ' '
            return f'{left}│{self.R}{lead}{content}{" " * pad}{right_pill}{self.R}'
        if pill_flush:
            pad = max(0, width - 1 - _visible_width(content))
            right = self.gradient.grad_at(width - 1, width, fill=fill)
            pad_str = ' ' * pad
            return f'{content}{pad_str}{right}│{self.R}'
        pad = max(0, width - 3 - _visible_width(content))
        left  = self.gradient.grad_at(0, width, fill=fill)
        right = self.gradient.grad_at(width - 1, width, fill=fill)
        lead = f'{bg_lead} \033[49m' if bg_lead else ' '
        if bg_trail and pad > 0:
            pad_str = f'{" " * (pad - 1)}{bg_trail} \033[49m'
        else:
            pad_str = ' ' * pad
        return f'{left}│{self.R}{lead}{content}{pad_str}{right}│{self.R}'
