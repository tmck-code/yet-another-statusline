from __future__ import annotations

from dataclasses import dataclass

from statusline.constants import (
    PILL_BL,
    PILL_BOT,
    PILL_BR,
    PILL_TL,
    PILL_TOP,
    PILL_TR,
)
from statusline.gradient import pill_gradient_fg


@dataclass
class Pill:
    start:  int = -1
    end:    int = -1
    anchor: tuple[int, int, int] = (0, 0, 0)
    shift:  tuple[int, int, int] = (0, 0, 0)
    pct:    int = 0

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
