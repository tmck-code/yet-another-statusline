from __future__ import annotations

from dataclasses import dataclass

from yas.constants import (
    PILL_BL,
    PILL_BOT,
    PILL_BR,
    PILL_TL,
    PILL_TOP,
    PILL_TR,
)
from yas.render.gradient import pill_gradient_fg


@dataclass(slots=True)
class Pill:
    start:  int = -1
    end:    int = -1
    anchor: tuple[int, int, int] = (0, 0, 0)
    shift:  tuple[int, int, int] = (0, 0, 0)
    pct:    int = 0

    @property
    def active(self) -> bool:
        return self.pct > 0

    _EDGE_GLYPHS = {
        'top':    (PILL_TL, PILL_TR, PILL_TOP),
        'bottom': (PILL_BL, PILL_BR, PILL_BOT),
    }

    def border_char(self, col: int, edge: str = 'top') -> str:
        if not self.active or not (self.start <= col <= self.end):
            return ''
        left, right, mid = self._EDGE_GLYPHS[edge if edge == 'top' else 'bottom']
        if col == self.start:
            return left
        if col == self.end:
            return right
        return mid

    def border_fg(self, col: int) -> str:
        return pill_gradient_fg(
            col - self.start, 0, self.end - self.start,
            self.anchor, self.shift, self.pct,
        )
