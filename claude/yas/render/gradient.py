"""Gradient, sparkline, and colour-math helpers for the statusline."""

from __future__ import annotations
import time
from typing import TYPE_CHECKING

from yas.constants import (
    RAINBOW_PALETTE,
    BG_LUM_THRESHOLD,
    BarChars,
    LIVE_DIM,
    RESET,
    SPARK_RISE_SMALL,
    SPARK_FALL_SMALL,
    SPARK_RISE_MED,
    SPARK_FALL_MED,
    SPARK_RISE_TALL,
    SPARK_FALL_TALL,
    SPARK_RISE_TOP,
    SPARK_FALL_TOP,
)

if TYPE_CHECKING:
    from yas.themes import Theme


# ---------------------------------------------------------------------------
# Rainbow helpers
# ---------------------------------------------------------------------------

def rainbow_step() -> int:
    return int(time.time()) % len(RAINBOW_PALETTE)


def rainbow_at(step: int, offset: int = 0) -> str:
    color = RAINBOW_PALETTE[(step + offset) % len(RAINBOW_PALETTE)]
    return f'\033[38;5;{color}m'


def rainbow_color() -> str:
    return rainbow_at(rainbow_step())


# ---------------------------------------------------------------------------
# Model key
# ---------------------------------------------------------------------------

def model_key(name: str) -> str:
    m = name.lower()
    if 'opus'   in m: return 'opus'
    if 'sonnet' in m: return 'sonnet'
    if 'haiku'  in m: return 'haiku'
    return 'other'


# ---------------------------------------------------------------------------
# Colour scale / paint helpers
# ---------------------------------------------------------------------------

def _scale(rgb: tuple[int, int, int], pct: int) -> tuple[int, int, int]:
    r, g, b = rgb
    return (min(255, max(0, r * pct // 100)),
            min(255, max(0, g * pct // 100)),
            min(255, max(0, b * pct // 100)))


def paint_bg_span(cells: list[tuple[str, tuple[int, int, int] | None, bool, bool]],
                  anchor: tuple[int, int, int],
                  shift: tuple[int, int, int],
                  pct: int,
                  pill_fg_dark:  tuple[int, int, int] = (15, 15, 15),
                  pill_fg_light: tuple[int, int, int] | None = None) -> str:
    c0 = _scale(anchor, pct)
    c1 = _scale(shift, pct)
    n = max(1, len(cells) - 1)
    parts: list[str] = []
    prev_bg = prev_fg = None
    prev_bold = prev_italic = False
    for i, (ch, fg, bold, italic) in enumerate(cells):
        t = i / n
        r = int(c0[0] + (c1[0] - c0[0]) * t)
        g = int(c0[1] + (c1[1] - c0[1]) * t)
        b = int(c0[2] + (c1[2] - c0[2]) * t)
        lum = (r * 299 + g * 587 + b * 114) // 1000
        fg_rgb: tuple[int, int, int] | None
        if lum >= BG_LUM_THRESHOLD:
            fg_rgb = pill_fg_dark
        elif pill_fg_light is not None:
            fg_rgb = pill_fg_light
        else:
            fg_rgb = fg
        cur_bg = (r, g, b)
        if cur_bg != prev_bg:
            parts.append(f'\033[48;2;{r};{g};{b}m')
            prev_bg = cur_bg
        if fg_rgb != prev_fg:
            if fg_rgb is None:
                parts.append('\033[39m')
            else:
                parts.append(f'\033[38;2;{fg_rgb[0]};{fg_rgb[1]};{fg_rgb[2]}m')
            prev_fg = fg_rgb
        if bold != prev_bold:
            parts.append('\033[1m' if bold else '\033[22m')
            prev_bold = bold
        if italic != prev_italic:
            parts.append('\033[3m' if italic else '\033[23m')
            prev_italic = italic
        parts.append(ch)
    parts.append('\033[49m')
    if prev_bold:
        parts.append('\033[22m')
    if prev_italic:
        parts.append('\033[23m')
    parts.append('\033[39m')
    return ''.join(parts)


def pill_gradient_fg(col: int, pill_start: int, pill_end: int,
                     anchor: tuple[int, int, int], shift: tuple[int, int, int],
                     pct: int) -> str:
    c0 = _scale(anchor, pct)
    c1 = _scale(shift, pct)
    span = max(1, pill_end - pill_start)
    t = (col - pill_start) / span
    t = max(0.0, min(1.0, t))
    r = int(c0[0] + (c1[0] - c0[0]) * t)
    g = int(c0[1] + (c1[1] - c0[1]) * t)
    b = int(c0[2] + (c1[2] - c0[2]) * t)
    return f'\x1b[38;2;{r};{g};{b}m'


# ---------------------------------------------------------------------------
# GradientEngine
# ---------------------------------------------------------------------------

class GradientEngine:
    FADE        = 0.06
    SPARK_CHARS = '▁▂▃▄▅▆▇█'

    def __init__(self, theme: 'Theme | None' = None) -> None:
        from yas.themes import CLAUDE_DARK
        t = theme if theme is not None else CLAUDE_DARK
        self.theme       = t
        self.GRAD_STOPS  = t.grad_stops
        self.GREY_RGB    = t.grey_rgb
        self.SPARK_STOPS = t.spark_stops
        self.BORDER_OFF  = t.border_off

    def spark_rgb(self, t: float, dim: float = 1.0) -> tuple[int, int, int]:
        t = max(0.0, min(1.0, t))
        for i in range(len(self.SPARK_STOPS) - 1):
            t0, c0 = self.SPARK_STOPS[i]
            t1, c1 = self.SPARK_STOPS[i + 1]
            if t <= t1:
                u = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
                r = int((c0[0] + (c1[0] - c0[0]) * u) * dim)
                g = int((c0[1] + (c1[1] - c0[1]) * u) * dim)
                b = int((c0[2] + (c1[2] - c0[2]) * u) * dim)
                return r, g, b
        r, g, b = self.SPARK_STOPS[-1][1]
        return int(r * dim), int(g * dim), int(b * dim)

    def spark_color(self, t: float, dim: float = 1.0) -> str:
        r, g, b = self.spark_rgb(t, dim)
        return f'\033[38;2;{r};{g};{b}m'

    def gradient_rgb(self, t: float, dim: float = 1.0) -> tuple[int, int, int]:
        t = max(0.0, min(1.0, t))
        for i in range(len(self.GRAD_STOPS) - 1):
            t0, c0 = self.GRAD_STOPS[i]
            t1, c1 = self.GRAD_STOPS[i + 1]
            if t <= t1:
                u = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
                r = int((c0[0] + (c1[0] - c0[0]) * u) * dim)
                g = int((c0[1] + (c1[1] - c0[1]) * u) * dim)
                b = int((c0[2] + (c1[2] - c0[2]) * u) * dim)
                return r, g, b
        r, g, b = self.GRAD_STOPS[-1][1]
        return int(r * dim), int(g * dim), int(b * dim)

    def gradient_color(self, t: float, dim: float = 1.0) -> str:
        r, g, b = self.gradient_rgb(t, dim)
        return f'\033[38;2;{r};{g};{b}m'

    def grad_at(self, col: int, width: int, dim: float = 1.0, fill: float = 1.0) -> str:
        denom = max(1, width - 1)
        t = col / denom
        if fill <= 0:
            return self.BORDER_OFF
        fade = self.FADE
        if t <= fill - fade:
            return self.gradient_color(t, dim)
        if t >= fill + fade:
            return self.BORDER_OFF
        er, eg, eb = self.gradient_rgb(min(t, fill), dim)
        gr, gg, gb = self.GREY_RGB
        u = max(0.0, min(1.0, (t - (fill - fade)) / (2 * fade)))
        r = int(er + (gr - er) * u)
        g = int(eg + (gg - eg) * u)
        b = int(eb + (gb - eb) * u)
        return f'\033[38;2;{r};{g};{b}m'

    def gradient_bar(self, filled: int, bar_w: int) -> str:
        if filled <= 0 or bar_w <= 0:
            return ''
        denom = max(1, bar_w - 1)
        parts = []
        for i in range(filled):
            r, g, b = self.gradient_rgb(i / denom)
            parts.append(f'\033[48;2;{r};{g};{b}m ')
        if filled <= bar_w:
            parts.append(f'\033[49m{self.gradient_color(filled / denom)}{BarChars.MID}')
        return ''.join(parts)

    def _spark_flat(self, idx: int) -> tuple[str, str]:
        if idx <= 0:
            return ' ', self.SPARK_CHARS[0]
        if idx <= 8:
            return ' ', self.SPARK_CHARS[idx - 1]
        return self.SPARK_CHARS[idx - 9], '█'

    def _spark_rise(self, idx: int) -> tuple[str, str]:
        if idx <= 0:
            return ' ', self.SPARK_CHARS[0]
        if idx <= 3:
            return ' ', SPARK_RISE_SMALL
        if idx <= 7:
            return ' ', SPARK_RISE_MED
        if idx <= 8:
            return ' ', SPARK_RISE_TALL
        return SPARK_RISE_TOP, SPARK_RISE_TALL

    def _spark_fall(self, idx: int) -> tuple[str, str]:
        if idx <= 0:
            return ' ', self.SPARK_CHARS[0]
        if idx <= 3:
            return ' ', SPARK_FALL_SMALL
        if idx <= 7:
            return ' ', SPARK_FALL_MED
        if idx <= 8:
            return ' ', SPARK_FALL_TALL
        return SPARK_FALL_TOP, SPARK_FALL_TALL

    def sparkline(self, history: list[int], live: bool = False) -> tuple[str, str]:
        if not history:
            return '', ''
        max_val = max(history)
        indices = [
            min(int(((v / max_val) if max_val > 0 else 0.0) * 16), 16)
            for v in history
        ]
        last_i  = len(indices) - 1
        top_parts = []
        bot_parts = []
        for i, idx in enumerate(indices):
            prev_idx = indices[i - 1] if i > 0 else 0
            if idx > prev_idx:
                top_ch, bot_ch = self._spark_rise(idx)
                tint_idx       = idx
            elif prev_idx > idx:
                top_ch, bot_ch = self._spark_fall(prev_idx)
                tint_idx       = prev_idx
            else:
                top_ch, bot_ch = self._spark_flat(idx)
                tint_idx       = idx
            ratio     = tint_idx / 16.0
            ratio_bot = ratio * 0.5
            ratio_top = 0.5 + ratio * 0.5
            if live and i == last_i:
                bot_clr = self.spark_color(ratio_bot, dim=LIVE_DIM)
                top_clr = self.spark_color(ratio_top, dim=LIVE_DIM)
            else:
                bot_clr = self.spark_color(ratio_bot)
                top_clr = self.spark_color(ratio_top)
            top_parts.append(f'{top_clr}{top_ch}{RESET}')
            bot_parts.append(f'{bot_clr}{bot_ch}{RESET}')
        return ''.join(top_parts), ''.join(bot_parts)
