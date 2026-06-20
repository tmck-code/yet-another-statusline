from __future__ import annotations

from yas.constants import (
    PILL_BL,
    PILL_BOT,
    PILL_BR,
    PILL_TL,
    PILL_TOP,
    PILL_TR,
)
from yas.render.gradient import pill_gradient_fg


class Pill:
    __slots__ = ('start', 'end', 'anchor', 'shift', 'pct')

    def __init__(
        self,
        start:  int = -1,
        end:    int = -1,
        anchor: tuple[int, int, int] = (0, 0, 0),
        shift:  tuple[int, int, int] = (0, 0, 0),
        pct:    int = 0,
    ) -> None:
        self.start  = start
        self.end    = end
        self.anchor = anchor
        self.shift  = shift
        self.pct    = pct

    @property
    def active(self) -> bool:
        return self.pct > 0

    def gradient_fg(self, col: int) -> str:
        return pill_gradient_fg(
            col - self.start, 0, self.end - self.start,
            self.anchor, self.shift, self.pct,
        )

    def border_char(self, col: int, edge: str = 'top') -> str:
        if not self.active or not (self.start <= col <= self.end):
            return ''
        if edge == 'top':
            if col == self.start:
                return PILL_TL
            if col == self.end:
                return PILL_TR
            return PILL_TOP
        else:
            if col == self.start:
                return PILL_BL
            if col == self.end:
                return PILL_BR
            return PILL_BOT

    def border_fg(self, col: int) -> str:
        return pill_gradient_fg(
            col - self.start, 0, self.end - self.start,
            self.anchor, self.shift, self.pct,
        )
