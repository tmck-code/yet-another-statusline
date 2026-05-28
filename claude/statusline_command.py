#!/usr/bin/env python3
'Claude Code statusLine command (Python port).'

from __future__ import annotations
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from collections.abc import Sequence

# This script runs as a top-level file (not inside a package), so put its own
# directory on sys.path to make the `statusline` subpackage importable — the
# same approach mon.py uses. This is what lets the renderer be split into
# submodules (statusline/*.py) that import one another normally.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from statusline.themes import CLAUDE_DARK, THEMES, Theme  # noqa: E402,F401
from statusline.textutil import _atomic_write_text, _is_wide, _middle_ellipsis, _visible_width, fmt_dur, fmt_tok, sparkline_width  # noqa: E402,F401
from statusline import clock, config, transcript  # noqa: E402,F401
from statusline.git import GIT_CACHE_TTL, GitInfo  # noqa: E402,F401
from statusline.transcript import (  # noqa: E402,F401
    LoadedSkills, RunningSubagent, RunningSubagents, Task, TaskList, TranscriptScan,
    TranscriptUsage, _SCAN_CACHE, _SCAN_STATE_V, _incremental_enabled,
    _parse_iso_to_epoch, _resume_point, _save_scan_state, _scan_state_path,
    _scan_transcript, _scan_with_state,
)
from statusline.models import Cost, ContextWindow, CurrentUsage, Effort, Model, OutputStyle, RateBucket, RateLimits, SessionInfo, Thinking, TokenAccounting, Workspace, _as_float, _as_int, _as_str, _model_version, model_key  # noqa: E402,F401
from statusline.accounting import TokenLog, TokenRate, _model_log_key, compute_day_cost, compute_session_cost, elapsed_from_transcript, session_cost_display  # noqa: E402,F401


class BarChars:
    FILLED = '█'
    HEAVY  = '▆'
    MID    = '▌'
    EMPTY  = '░'


MIN_WIDTH    = 40
DEFAULT_MAX_WIDTH = 140
MAX_WIDTH    = int(os.environ.get('YAS_MAX_WIDTH') or DEFAULT_MAX_WIDTH)
NARROW_WIDTH = 55
MEDIUM_WIDTH = 80
SOFT_LIMIT = 150_000

FIVE_HOUR_MINUTES        = 300
SEVEN_DAY_MINUTES        = 10080
FIVE_HOUR_WARMUP_MINUTES = 5
SEVEN_DAY_WARMUP_MINUTES = 30


def burndown_delta(
    used_pct: float,
    resets_at: int,
    window_minutes: int,
    warmup_minutes: int,
    now: float | None = None,
) -> float | None:
    if not resets_at:
        return None
    t = now if now is not None else time.time()
    if t >= resets_at:
        return None
    window_start_ts = resets_at - window_minutes * 60
    elapsed_minutes = (t - window_start_ts) / 60
    if elapsed_minutes < warmup_minutes:
        return None
    ideal_pct = (elapsed_minutes / window_minutes) * 100
    return used_pct - ideal_pct


def subagent_avg_tpm(
    total_input: int,
    output: int,
    first_timestamp: float,
    now: float,
    floor_seconds: float = 3.0,
) -> int | None:
    if first_timestamp == 0 or now - first_timestamp < floor_seconds:
        return None
    return round((total_input + output) / ((now - first_timestamp) / 60))


def subagent_share(sub_inout: int, session_inout: int) -> float | None:
    if session_inout <= 0:
        return None
    return sub_inout / session_inout


def terminal_width() -> int:
    try:
        w = int(subprocess.run([
            "tmux", "display-message", "-p", "-t", f"{os.environ['TMUX_PANE']}", "'#{pane_width}'"
        ], capture_output=True, text=True).stdout.strip().replace("'", ""))
        if w > 0:
            return w
    except (OSError, ValueError, KeyError):
        pass
    try:
        w = int((config.CLAUDE_DIR / 'terminal-width').read_text().strip())
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
    w = shutil.get_terminal_size(fallback=(0, 0)).columns
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
    return MAX_WIDTH

RESET  = '\033[0m'
BOLD   = '\033[1m'
ITALIC = '\033[3m'

CLR_GREY_DIM   = '\033[38;5;244m'
CLR_GREY_DARK  = '\033[38;5;238m'
CLR_BORDER_OFF = '\033[38;5;242m'
CLR_SKY_BLUE   = '\033[38;5;75m'
CLR_GREEN_OK   = '\033[38;5;114m'
CLR_GREEN_DIM  = '\033[38;5;77m'
CLR_GREEN_BRT  = '\033[38;5;46m'
CLR_PURPLE     = '\033[38;5;183m'
CLR_GOLD       = '\033[38;5;222m'
CLR_YELLOW     = '\033[38;5;226m'
CLR_YELLOW_BRT = '\033[38;5;11m'
CLR_CYAN       = '\033[38;5;116m'
CLR_CYAN_DIM   = '\033[38;5;244m'
CLR_CYAN_DAY   = '\033[38;5;109m'
CLR_CYAN_DAY_DIM = '\033[38;5;240m'
CLR_CYAN_ICON  = '\033[38;5;117m'
CLR_PINK       = '\033[38;5;210m'
CLR_PEACH      = '\033[38;5;216m'
CLR_WHITE_BRT  = '\033[38;5;15m'
CLR_WARN       = '\033[38;5;214m'
CLR_ALERT      = '\033[38;5;167m'

# Glyphs. Default to clean, universal Unicode that renders in any monospace
# font; set YAS_NERD_FONT=1 for the original Nerd Font Private-Use glyphs
# (which need a Nerd Font, otherwise they show as '?'). Both alternatives
# are one cell wide, so the layout is identical either way.
_NERD_FONT = os.environ.get('YAS_NERD_FONT') not in (None, '', '0')


def _glyph(clean: str, nerd: str) -> str:
    return nerd if _NERD_FONT else clean


ICON_COST          = _glyph('$', '\uefc8')           # $        cost row
ICON_TOK_RATE      = _glyph('~', '\U000f18a7')       # ~        t/m rate label
GLYPH_MODEL        = _glyph('\u25c6', '\U000f08b9') # diamond  model
GLYPH_THINKING     = _glyph('\u2726', '\U000f1a53') # star     thinking
GLYPH_BURN_FAST    = _glyph('\u00bb', '\uef76')     # >>       burn rate too fast
GLYPH_BURN_SLOW    = _glyph('\u00b7', '\uf490')     # middot   burn rate ok
GLYPH_FOLDER       = _glyph('\u25cf', '\uef85')     # disc     path row
GLYPH_BRANCH       = _glyph('\u21b3', '\ue0a0')     # hook     path -> branch
GLYPH_SUBAGENT     = _glyph('\u25b8', '\uf135')     # triangle subagent list
GLYPH_SUBAGENT_ROW = '\u25b6'                        # per-row subagent marker
GLYPH_TASKS        = _glyph('\u2713', '\U000f0755') # check    task row
GLYPH_SKILLS       = _glyph('\u25c7', '\U000f07df') # diamond  skills label
GLYPH_PLUGINS      = _glyph('\u25c8', '\uf1e6')     # diamond  plugins label
GLYPH_HELPER       = _glyph('\u2605', '\uf4cd')     # star     5h rate-limit helper
GLYPH_TRASH        = _glyph('\u2717', '\U000f0a7a') # x        git deleted count
GLYPH_RENAMED      = _glyph('\u2192', '\U000f1031') # arrow    git renamed count
GLYPH_CONTINUATION = '\u2514'                        # box up-right (universal)
GLYPH_REPLYING     = _glyph('\u2026', '\U000f0189') # ellipsis replying state
GLYPH_HOURGLASS    = _glyph('\u25f7', '\uf253')     # arc      subagent context size
GLYPH_PIE          = _glyph('\u25d4', '\uf200')     # pie      subagent session share

TOOL_ARG_KEY: dict[str, str] = {
    'Bash':        'command',
    'Read':        'file_path',
    'Edit':        'file_path',
    'Write':       'file_path',
    'NotebookEdit':'file_path',
    'Grep':        'pattern',
    'Glob':        'pattern',
    'Task':        'subagent_type',
}

# Dim factor for the in-flight (currently-open) sparkline bucket.
LIVE_DIM = 0.5


PILL_TL    = '▗'  # U+2597 lower-right quadrant
PILL_TOP   = '▄'  # U+2584 lower half block
PILL_TR    = '▖'  # U+2596 lower-left quadrant
PILL_LEFT  = '▐'  # U+2590 right half block
PILL_RIGHT = '▌'  # U+258C left half block
PILL_BL    = '▝'  # U+259D upper-right quadrant
PILL_BOT   = '▀'  # U+2580 upper half block
PILL_BR    = '▘'  # U+2598 upper-left quadrant


@dataclass
class Pill:
    start: int = -1
    end: int = -1
    anchor: tuple[int, int, int] = (0, 0, 0)
    shift: tuple[int, int, int] = (0, 0, 0)
    pct: int = 0

    @property
    def active(self) -> bool:
        return self.pct > 0

    def gradient_fg(self, col: int) -> str:
        return pill_gradient_fg(col - self.start, 0, self.end - self.start, self.anchor, self.shift, self.pct)

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
        return pill_gradient_fg(col - self.start, 0, self.end - self.start, self.anchor, self.shift, self.pct)




@dataclass
class OpenSpec:
    changes: list[tuple[str, int, int]] = field(default_factory=list)

    @classmethod
    def from_cwd(cls, cwd: str) -> OpenSpec:
        root = cls._find_root(cwd)
        if not root:
            return cls()
        out: list[tuple[str, int, int]] = []
        open_re = re.compile(r'^\s*- \[ \]')
        done_re = re.compile(r'^\s*- \[x\]')
        for tasks in sorted(Path(root).rglob('tasks.md')):
            if '/archive/' in str(tasks):
                continue
            try:
                text = tasks.read_text()
            except OSError:
                continue
            t = sum(1 for ln in text.splitlines() if open_re.match(ln))
            d = sum(1 for ln in text.splitlines() if done_re.match(ln))
            total = t + d
            if total == 0:
                continue
            out.append((tasks.parent.name, d, total))
        return cls(changes=out)

    @staticmethod
    def _find_root(cwd: str) -> str:
        curr = Path(cwd) if cwd else None
        while curr:
            if (curr / 'openspec').is_dir():
                return str(curr / 'openspec')
            if curr == curr.parent:
                break
            curr = curr.parent
        return ''


# Monochrome: the former time-cycling rainbow accent (on the thinking / 5h-helper
# / skills / plugins / marker glyphs) is now a single calm static grey — no hue,
# no per-second animation. Length is preserved so rainbow_step()'s modulo and the
# existing index-wrap tests are unaffected; every entry resolves to the same grey.
RAINBOW_PALETTE = (250,) * 30


def rainbow_step() -> int:
    return int(time.time()) % len(RAINBOW_PALETTE)


def rainbow_at(step: int, offset: int = 0) -> str:
    color = RAINBOW_PALETTE[(step + offset) % len(RAINBOW_PALETTE)]
    return f'\033[38;5;{color}m'


def rainbow_color() -> str:
    return rainbow_at(rainbow_step())


LEVEL_PCT = {
    'low':    30,
    'medium': 55,
    'high':   80,
    'xhigh':  100,
    'max':    140,
}

BG_LUM_THRESHOLD = 110




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
    return f'[38;2;{r};{g};{b}m'


class GradientEngine:
    FADE        = 0.06
    SPARK_CHARS = '▁▂▃▄▅▆▇█'

    def __init__(self, theme: Theme | None = None) -> None:
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
            parts = [p.border_fg(p.start), PILL_TL]
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


class Renderer:
    def __init__(self, bg_shift: str = 'warm', theme: Theme | None = None) -> None:
        self.bg_shift = bg_shift if bg_shift in ('warm', 'cool') else 'warm'
        self.theme    = theme if theme is not None else CLAUDE_DARK
        self.gradient = GradientEngine(self.theme)
        self.border   = BorderRenderer(self.gradient)
        self._apply_theme(self.theme)

    def _apply_theme(self, t: Theme) -> None:
        self.BORDER      = t.border
        self.PWD         = t.pwd
        self.BRANCH      = t.branch
        self.COMMIT      = t.commit
        self.SESSION     = t.session
        self.MODEL       = t.model
        self.SKILLS      = t.skills
        self.TIME        = t.time
        self.TOK         = t.tok
        self.TOK_DIM     = t.tok_dim
        self.TOK_DAY     = t.tok_day
        self.TOK_DAY_DIM = t.tok_day_dim
        self.COST        = t.cost
        self.BAR_FILL    = t.bar_fill
        self.BAR_EMPTY   = t.bar_empty
        self.DIM_GREEN   = t.dim_green
        self.LABEL       = t.label
        self.CTX         = t.ctx
        self.CTX_DIM     = t.ctx_dim
        self.BOLDW       = BOLD + t.white_brt
        self.BOLDY       = t.tok_arrow
        self.DIRTY       = t.dirty
        self.ICON_PATH   = t.icon_path
        self.ARROW       = t.arrow
        self.TOK_ICON    = t.tok_icon
        self.OPUS        = t.models['opus'].label
        self.SONNET      = t.models['sonnet'].label
        self.HAIKU       = t.models['haiku'].label
        self.safe        = t.safe
        self.warn        = t.warn
        self.alert       = t.alert
        self.yellow      = t.yellow
        self.white_brt   = t.white_brt
        self.pill_fg_dark    = t.pill_fg_dark
        self.pill_fg_light   = t.pill_fg_light
        self.SPEC_GRADIENTS  = t.spec_gradients
        self.spec_empty_ansi = t.spec_empty_ansi

    def _model_bg_pct(self, effort_level: str) -> int:
        return LEVEL_PCT.get(effort_level.lower(), 0)

    def _model_anchor_pair(self, model_name: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
        mc    = self.theme.models[model_key(model_name)]
        shift = mc.warm_shift if self.bg_shift == 'warm' else mc.cool_shift
        return mc.anchor, shift

    def model_bg_lead(self, model_name: str, effort_level: str) -> str:
        pct = self._model_bg_pct(effort_level)
        if not pct:
            return ''
        anchor, _ = self._model_anchor_pair(model_name)
        r, g, b   = _scale(anchor, pct)
        return f'\033[48;2;{r};{g};{b}m'

    def model_bg_trail(self, model_name: str, effort_level: str) -> str:
        pct = self._model_bg_pct(effort_level)
        if not pct:
            return ''
        _, shift = self._model_anchor_pair(model_name)
        r, g, b  = _scale(shift, pct)
        return f'\033[48;2;{r};{g};{b}m'

    R         = RESET
    BORDER    = CLR_GREY_DIM
    PWD       = CLR_SKY_BLUE
    BRANCH    = CLR_GREEN_OK
    COMMIT    = CLR_GREY_DIM
    SESSION   = CLR_GREY_DIM
    MODEL     = CLR_PURPLE
    SKILLS    = CLR_GOLD
    TIME      = CLR_GREY_DIM
    TOK       = CLR_CYAN
    TOK_DIM   = CLR_CYAN_DIM
    TOK_DAY     = CLR_CYAN_DAY
    TOK_DAY_DIM = CLR_CYAN_DAY_DIM
    COST      = CLR_PINK
    BAR_FILL  = CLR_GREEN_OK
    BAR_EMPTY = CLR_GREY_DARK
    DIM_GREEN = CLR_GREEN_DIM
    LABEL     = CLR_GREY_DIM
    CTX       = CLR_PEACH
    CTX_DIM   = CLR_PEACH
    BOLDW     = BOLD + CLR_WHITE_BRT
    BOLDY     = CLR_YELLOW
    DIRTY     = CLR_WARN
    ICON_PATH = CLR_CYAN_ICON
    ARROW     = CLR_GREEN_BRT
    TOK_ICON  = CLR_YELLOW_BRT
    OPUS      = CLR_YELLOW
    SONNET    = CLR_GREEN_OK
    HAIKU     = CLR_SKY_BLUE

    # --- Gradient delegations (backward compat) ---
    # GRAD_STOPS / GREY_RGB / SPARK_STOPS now live on the GradientEngine
    # instance (driven by the active Theme). The legacy class-level constants
    # are gone; callers reach them via r.gradient.GRAD_STOPS etc.
    FADE        = GradientEngine.FADE
    SPARK_CHARS = GradientEngine.SPARK_CHARS

    def gradient_rgb(self, t: float, dim: float = 1.0) -> tuple[int, int, int]:
        return self.gradient.gradient_rgb(t, dim)

    def gradient_color(self, t: float, dim: float = 1.0) -> str:
        return self.gradient.gradient_color(t, dim)

    def grad_at(self, col: int, width: int, dim: float = 1.0, fill: float = 1.0) -> str:
        return self.gradient.grad_at(col, width, dim, fill)

    def gradient_bar(self, filled: int, bar_w: int) -> str:
        return self.gradient.gradient_bar(filled, bar_w)

    def vsep_block(self, col: int, width: int, fill: float = 1.0, *, leader: bool = False) -> str:
        color    = self.gradient.grad_at(col - 1, width, fill=fill)
        trailing = ' ' if leader else '  '
        return f'  {color}│{self.R}{trailing}'

    def sparkline(self, history: list[int], live: bool = False) -> tuple[str, str]:
        return self.gradient.sparkline(history, live)

    def spark_rgb(self, t: float, dim: float = 1.0) -> tuple[int, int, int]:
        return self.gradient.spark_rgb(t, dim)

    def spark_color(self, t: float, dim: float = 1.0) -> str:
        return self.gradient.spark_color(t, dim)

    # --- Border delegations (backward compat) ---
    def border_top(self, width: int, session_id: str = '', downs: tuple[int, ...] = (), fill: float = 1.0, pill: Pill | None = None) -> str:
        return self.border.border_top(width, session_id, downs, fill, pill)

    def border_bottom(self, width: int, ups: tuple[int, ...] = (), fill: float = 1.0) -> str:
        return self.border.border_bottom(width, ups, fill)

    def border_separator(self, width: int, ups: tuple[int, ...] = (), fill: float = 1.0) -> str:
        return self.border.border_separator(width, ups, fill)

    def border_separator_dim(self, width: int, downs: tuple[int, ...] = (), ups: tuple[int, ...] = (), fill: float = 1.0, pill: Pill | None = None, pill_edge: str = 'bottom') -> str:
        return self.border.border_separator_dim(width, downs, ups, fill, pill, pill_edge)

    def border_line(self, content: str, width: int, fill: float = 1.0, bg_lead: str = '', bg_trail: str = '', pill_flush: bool = False, right_pill: str = '') -> str:
        return self.border.border_line(content, width, fill, bg_lead, bg_trail, pill_flush, right_pill)

    def path_git(
        self, short_pwd: str, git: GitInfo, elapsed: str = '',
        *, show_commit: bool = True, show_dirty: bool = True, show_elapsed: bool = True,
    ) -> str:
        dirty = ''
        if show_dirty:
            if git.untracked > 0:
                dirty += f'{self.DIRTY}•{git.untracked}{RESET}'
            if git.modified > 0:
                dirty += f'{self.DIRTY}*{git.modified}{RESET}'
            if git.deleted > 0:
                dirty += f'{self.DIRTY}-{git.deleted}{RESET}'
            if git.renamed > 0:
                dirty += f'{self.DIRTY}{GLYPH_RENAMED} {git.renamed}{RESET}'
            if dirty:
                dirty = ' ' + dirty
        tail = f' {self.SESSION}[{elapsed}]{self.R}' if (show_elapsed and elapsed and elapsed != '0m') else ''
        commit_part = f'{self.LABEL}/{self.R}{self.COMMIT}{git.commit}{self.R}' if show_commit else ''

        return (
            f'{self.ICON_PATH}{GLYPH_FOLDER}  {self.PWD}{short_pwd}{self.R}'
            f' {self.LABEL}{self.ARROW}{BOLD}{GLYPH_BRANCH}{self.R}'
            f' {self.BRANCH}{git.branch}{self.R}'
            f'{commit_part}{dirty}{tail}'
        )

    def path_git_compact(self, short_pwd: str, git: GitInfo) -> str:
        return (
            f'{self.ICON_PATH}  {self.PWD}{short_pwd}{self.R}'
            f' {self.LABEL}{self.ARROW}{BOLD}{GLYPH_BRANCH}{self.R}'
            f' {self.BRANCH}{git.branch}{self.R}'
        )

    def fit_path(
        self, short_pwd: str, git: GitInfo, elapsed: str, target_w: int,
        *, compact_only: bool = False,
    ) -> str:
        def fits(s: str) -> bool:
            return _visible_width(s) <= target_w

        if not compact_only:
            for kwargs in (
                {},
                {'show_commit': False},
                {'show_commit': False, 'show_elapsed': False},
                {'show_commit': False, 'show_elapsed': False, 'show_dirty': False},
            ):
                candidate = self.path_git(short_pwd, git, elapsed, **kwargs)
                if fits(candidate):
                    return candidate

        compact = self.path_git_compact(short_pwd, git)
        if fits(compact):
            return compact

        # Ellipsis on short_pwd only
        for pwd_w in range(target_w - 1, 0, -1):
            trunc_pwd = _middle_ellipsis(short_pwd, pwd_w)
            candidate = self.path_git_compact(trunc_pwd, git)
            if fits(candidate):
                return candidate

        # Ellipsis on both short_pwd and branch
        # Overhead of path_git_compact with empty strings is 5 visible chars.
        half = max(1, (target_w - 5) // 2)
        trunc_pwd    = _middle_ellipsis(short_pwd,  half)
        trunc_branch = _middle_ellipsis(git.branch, half)
        truncated_git = GitInfo(
            branch=trunc_branch, commit=git.commit,
            modified=git.modified, untracked=git.untracked,
            deleted=git.deleted, renamed=git.renamed,
        )
        return self.path_git_compact(trunc_pwd, truncated_git)

    def model_colour(self, model_name: str) -> str:
        return self.theme.models[model_key(model_name)].label

    def fill_colour(self, pct: float) -> str:
        if pct >= 90:
            return self.alert
        if pct >= 70:
            return self.warn
        return self.safe

    def risk_zone_color(self, tokens: int) -> str:
        if tokens <= 50_000:
            return self.safe
        if tokens <= 80_000:
            return self.yellow
        if tokens <= 150_000:
            return self.warn
        return self.alert

    def day_cost_colour(self, cost: float) -> str:
        if cost > 50:
            return self.alert
        if cost >= 25:
            return self.yellow
        return self.safe

    def model_section_compact(self, model_name: str, rate_limits: RateLimits, max_width: int, effort_level: str = '') -> tuple[str, int]:
        model_clr = self.model_colour(model_name)
        pct_bg    = self._model_bg_pct(effort_level)
        anchor, shift = self._model_anchor_pair(model_name) if pct_bg else ((0, 0, 0), (0, 0, 0))
        pct       = rate_limits.five_hour.used_percentage or 0
        pct_clr   = self.fill_colour(float(pct))
        step      = rainbow_step()
        c_helper  = rainbow_at(step, 9)
        rate_pct  = f'{pct_clr}{pct}%{self.R}'

        rate_with_time = None
        try:
            if rate_limits.five_hour.resets_at:
                resets_at = datetime.fromtimestamp(rate_limits.five_hour.resets_at).astimezone()
                delta = resets_at - clock.now().astimezone().replace(microsecond=0)
                if delta.total_seconds() > 0:
                    total_s = int(delta.total_seconds())
                    h, rem  = divmod(total_s, 3600)
                    m       = rem // 60
                    time_str       = f'{h}h{m}m' if h else f'{m}m'
                    rate_with_time = f'{rate_pct} {self.COMMIT}{time_str}{self.R}'
        except Exception:
            pass

        def _build(name: str, rate: str) -> tuple[str, int]:
            if pct_bg:
                cells: list[tuple[str, tuple[int, int, int] | None, bool, bool]] = []
                cells.append((GLYPH_MODEL, anchor, False, False))
                cells.append((' ', anchor, False, False))
                cells.append((' ', anchor, False, False))
                for ch in name:
                    cells.append((ch, anchor, False, False))
                cells.append((' ', anchor, False, False))
                pill_l = pill_gradient_fg(0, 0, len(cells), anchor, shift, pct_bg) + PILL_LEFT
                pill_r = pill_gradient_fg(len(cells), 0, len(cells), anchor, shift, pct_bg) + PILL_RIGHT
                painted = pill_l + paint_bg_span(cells, anchor, shift, pct_bg, self.pill_fg_dark, self.pill_fg_light) + pill_r + RESET
                pw = _visible_width(painted)
                return (
                    f'{painted}'
                    f'{self.LABEL}|{self.R}'
                    f' {c_helper}{BOLD}{GLYPH_HELPER}{self.R} {rate}'
                ), pw
            return (
                f'{model_clr}{GLYPH_MODEL}  {name}{self.R}'
                f' {self.LABEL}|{self.R}'
                f' {c_helper}{BOLD}{GLYPH_HELPER}{self.R} {rate}'
            ), 0

        if rate_with_time:
            line, pw = _build(model_name, rate_with_time)
            if _visible_width(line) <= max_width:
                return line, pw

        line, pw = _build(model_name, rate_pct)
        if _visible_width(line) <= max_width:
            return line, pw

        base_w      = _visible_width(_build('', rate_pct)[0])
        name_budget = max(3, max_width - base_w - 1)
        return _build(model_name[:name_budget] + '…', rate_pct)

    def model_right_section(self, model_name: str, model_thinking: str, rate_limits: RateLimits, effort_level: str = '', fast_mode: bool = False) -> tuple[str, str, int]:
        step      = rainbow_step()
        c_think   = rainbow_at(step, 0)
        c_helper  = rainbow_at(step, 9)
        model_clr = self.model_colour(model_name)
        pct       = self._model_bg_pct(effort_level)
        glyph     = GLYPH_BURN_FAST if fast_mode else GLYPH_THINKING

        if pct:
            anchor, shift = self._model_anchor_pair(model_name)
            cells: list[tuple[str, tuple[int, int, int] | None, bool, bool]] = []
            cells.append((GLYPH_MODEL,    anchor, False, False))
            cells.append((' ',            anchor, False, False))
            cells.append((' ',            anchor, False, False))
            for ch in model_name:
                cells.append((ch, anchor, False, False))
            cells.append((' ',            anchor, False, False))
            cells.append((glyph,          anchor, True,  False))
            cells.append((' ',            anchor, True,  False))
            cells.append((' ',            anchor, True,  False))
            for ch in model_thinking:
                cells.append((ch, anchor, False, True))
            cells.append((' ', anchor, False, False))
            pill_l    = pill_gradient_fg(0, 0, len(cells), anchor, shift, pct) + PILL_LEFT
            pill_r    = pill_gradient_fg(len(cells), 0, len(cells), anchor, shift, pct) + PILL_RIGHT
            right_text = pill_l + paint_bg_span(cells, anchor, shift, pct, self.pill_fg_dark, self.pill_fg_light) + pill_r + RESET
        elif model_thinking:
            right_text = f'{model_clr}{GLYPH_MODEL}  {model_name}{self.R} {c_think}{BOLD}{glyph}  {self.R}{model_clr}{ITALIC}{model_thinking}{RESET}'
        else:
            right_text = f'{model_clr}{GLYPH_MODEL}  {model_name}{self.R}'

        right_w = _visible_width(right_text)

        helper_text = f'{c_helper}{BOLD}{GLYPH_HELPER}{self.R}  {self.white_brt}{BOLD}{self.helper(rate_limits.five_hour)}{self.R}'
        seven_day = rate_limits.seven_day
        if seven_day.used_percentage != 0 or seven_day.resets_at != 0:
            seven_clr = self.fill_colour(float(seven_day.used_percentage or 0))
            seven_trend = self.burndown_trend(
                float(seven_day.used_percentage or 0),
                seven_day.resets_at,
                SEVEN_DAY_MINUTES,
                SEVEN_DAY_WARMUP_MINUTES,
            )
            seven_trend_part = f' {seven_trend}' if seven_trend else ''
            helper_text += f' {self.LABEL}| {seven_clr}{seven_day.used_percentage}%{self.R}{seven_trend_part}'

        return helper_text, right_text, right_w

    def model_right_section_compact(self, model_name: str, rate_limits: RateLimits, max_right_width: int, effort_level: str = '') -> tuple[str, str, int]:
        model_clr = self.model_colour(model_name)
        pct_bg    = self._model_bg_pct(effort_level)
        anchor, shift = self._model_anchor_pair(model_name) if pct_bg else ((0, 0, 0), (0, 0, 0))
        pct       = rate_limits.five_hour.used_percentage or 0
        pct_clr   = self.fill_colour(float(pct))
        rate_text = f'{pct_clr}{pct}%{self.R}'
        try:
            if rate_limits.five_hour.resets_at:
                resets_at = datetime.fromtimestamp(rate_limits.five_hour.resets_at).astimezone()
                delta = resets_at - clock.now().astimezone().replace(microsecond=0)
                if delta.total_seconds() > 0:
                    trend = self.burndown_trend(
                        float(pct),
                        rate_limits.five_hour.resets_at,
                        FIVE_HOUR_MINUTES,
                        FIVE_HOUR_WARMUP_MINUTES,
                    )
                    trend_part = f' {trend}' if trend else ''
                    total_s = int(delta.total_seconds())
                    h, rem  = divmod(total_s, 3600)
                    m       = rem // 60
                    time_str = f'{h}h{m}m' if h else f'{m}m'
                    rate_text = f'{rate_text}{trend_part} {self.COMMIT}{time_str}{self.R}'
        except Exception:
            pass

        def _make_right(name: str) -> tuple[str, int]:
            if pct_bg:
                cells: list[tuple[str, tuple[int, int, int] | None, bool, bool]] = []
                cells.append((GLYPH_MODEL, anchor, False, False))
                cells.append((' ', anchor, False, False))
                cells.append((' ', anchor, False, False))
                for ch in name:
                    cells.append((ch, anchor, False, False))
                cells.append((' ', anchor, False, False))
                pill_l  = pill_gradient_fg(0, 0, len(cells), anchor, shift, pct_bg) + PILL_LEFT
                pill_r  = pill_gradient_fg(len(cells), 0, len(cells), anchor, shift, pct_bg) + PILL_RIGHT
                painted = pill_l + paint_bg_span(cells, anchor, shift, pct_bg, self.pill_fg_dark, self.pill_fg_light) + pill_r + RESET
                return painted, _visible_width(painted)
            text = f'{model_clr}{GLYPH_MODEL}  {name}{self.R}'
            return text, _visible_width(text)

        right_text, right_w = _make_right(model_name)
        if right_w > max_right_width and max_right_width > 0:
            _, base_w = _make_right('')
            budget    = max(3, max_right_width - base_w - 1)
            right_text, right_w = _make_right(model_name[:budget] + '…')
        return rate_text, right_text, right_w

    def plugins_skills(self, skills_count: int, skills_names: str, plugin_names: str, width: int = 0) -> str:
        step = rainbow_step()
        c_skills = rainbow_at(step, 3)
        c_plugins = rainbow_at(step, 6)
        segs: list[tuple[str, str, str]] = []   # (colour, glyph, names)
        if skills_count > 0:
            segs.append((c_skills, GLYPH_SKILLS, skills_names))
        if plugin_names:
            segs.append((c_plugins, GLYPH_PLUGINS, plugin_names))
        if not segs:
            return ''
        # Budget the visible content to the box like the sibling rows (width-4),
        # truncating the comma-lists with '…' so the row never overflows. With
        # width==0 (or when it already fits) the output is unchanged.
        if width > 0:
            fixed = 3 * len(segs) + 3 * (len(segs) - 1)   # glyph+'  ' per seg, ' | ' joiners
            names_budget = max(0, (width - 4) - fixed)
            widths = [_visible_width(n) for _, _, n in segs]
            if sum(widths) > names_budget:
                total     = sum(widths) or 1
                remaining = names_budget
                fitted: list[tuple[str, str, str]] = []
                for i, (clr, glyph, names) in enumerate(segs):
                    share = remaining if i == len(segs) - 1 else names_budget * widths[i] // total
                    if share <= 0:
                        names = ''
                    elif _visible_width(names) > share:
                        names = names[:max(0, share - 1)] + '…'
                    remaining -= _visible_width(names)
                    fitted.append((clr, glyph, names))
                segs = fitted
        parts = [
            f'{clr}{BOLD}{glyph}  {self.R}{self.SKILLS}{names}{self.R}'
            for clr, glyph, names in segs
        ]
        return f' {self.LABEL}|{self.R} '.join(parts)

    SUBAGENT_TOK_W = 6  # fmt_tok('999.9K') is 6 chars; reserve to avoid jitter

    def subagent_activity(self, last_activity: tuple[str, str, dict[str, object]]) -> str:
        kind, name, inp = last_activity
        if kind == 'tool_use':
            key = TOOL_ARG_KEY.get(name)
            if key and key in inp:
                raw = str(inp[key])
                if key == 'file_path':
                    raw = Path(raw).name
            elif inp:
                raw = str(next(iter(inp.values())))
            else:
                raw = ''
            if _visible_width(raw) > 36:
                raw = raw[:36] + '…'  # U+2026 HORIZONTAL ELLIPSIS
            return f'{GLYPH_TASKS} {name}[{raw}]'
        if kind == 'thinking':
            return f'{GLYPH_THINKING} (thinking)'
        if kind == 'text':
            return f'{GLYPH_REPLYING} (replying)'
        return ''

    def subagent_row(self, sub: RunningSubagent, width: int, session_inout: int = 0) -> str:
        now     = time.time()
        dur     = max(0.0, now - sub.first_timestamp) if sub.first_timestamp > 0 else 0.0
        dur_s   = fmt_dur(dur).rjust(5)
        out_s   = fmt_tok(sub.output)
        tok_s   = fmt_tok(sub.total_input)

        short_model = model_key(sub.model)  # 'opus'/'sonnet'/'haiku'/'other'
        model_clr   = self.model_colour(sub.model)
        ctx_clr     = self.risk_zone_color(sub.total_input)

        step     = rainbow_step()
        c_marker = rainbow_at(step, 12)
        type_text = sub.agent_type or '?'

        target_w = width - 4  # content width (2 for '│ ' left, 2 for ' │' right)

        if width > 100:
            # --- identity line (▶) : agent type · description (full width) ---
            head1_w  = 3 + _visible_width(type_text) + 3  # '▶  ' + type + ' · '
            desc_budget = max(0, target_w - head1_w)
            desc_text   = sub.description or ''
            if _visible_width(desc_text) > desc_budget:
                desc_text = (desc_text[:desc_budget - 1] + '…') if desc_budget > 0 else ''

            left1 = (
                f'{c_marker}{BOLD}{GLYPH_SUBAGENT_ROW}{self.R}  '
                f'{self.SKILLS}{type_text}{self.R}'
                f' {self.LABEL}·{self.R} '
                f'{self.CTX}{desc_text}{self.R}'
            )
            left1_w = head1_w + _visible_width(desc_text)
            pad1    = max(1, target_w - left1_w)
            line1   = f'{left1}{" " * pad1}'  # right side empty; pad keeps equal widths

            # --- continuation line (└) : burn-metric cluster ---
            # Stats live here as ' · '-joined fields; duration and model relocate
            # from the identity line. When width is tight, stats are shed in
            # priority order — share % first, then ↑output, then the t/m rate.
            # The token count, elapsed, and model always remain.
            tpm   = subagent_avg_tpm(sub.total_input, sub.output, sub.first_timestamp, now)
            share = subagent_share(sub.total_input + sub.output, session_inout)

            sep       = f' {self.LABEL}·{self.R} '
            tok_field = fmt_tok(sub.total_input).rjust(5)
            out_plain = f'↑ {out_s}'
            out_pad   = ' ' * max(0, 6 - len(out_plain))

            tpm_str = f'{tpm:,d}'.rjust(5) if tpm is not None else ''
            if share is not None:
                share_clr = self.gradient.gradient_color(share)
                share_str = f'{share * 100:.1f}%'.rjust(6)

            activity = self.subagent_activity(sub.last_activity)
            left2_w  = 6 + _visible_width(activity)
            left2 = (
                f'   {self.CTX_DIM}{GLYPH_CONTINUATION}{self.R}  '
                f'{self.CTX_DIM}{activity}{self.R}'
            )

            def cluster(show_tpm: bool, show_share: bool, show_out: bool) -> str:
                frags: list[str] = []
                if show_tpm:
                    frags.append(f'{self.TOK}{tpm_str}{self.R}{self.LABEL} t/m{self.R}')
                if show_share:
                    frags.append(f'{share_clr}{GLYPH_PIE} {share_str}{self.R}')
                # tok and ↑out are one space-grouped field (no · between them).
                tok_seg = f'{ctx_clr}{tok_field}{self.R}'
                if show_out:
                    tok_seg += f' {out_pad}{self.LABEL}{BOLD}↑ {self.R}{self.CTX}{out_s}{self.R}'
                frags.append(tok_seg)
                frags.append(f'{self.CTX}{dur_s}{self.R}')
                frags.append(f'{model_clr}{short_model.rjust(6)}{self.R}')
                return sep.join(frags)

            show_tpm, show_share, show_out = tpm is not None, share is not None, True

            def fits() -> bool:
                return left2_w + _visible_width(cluster(show_tpm, show_share, show_out)) + 1 <= target_w

            if not fits() and show_share:
                show_share = False
            if not fits() and show_out:
                show_out = False
            if not fits() and show_tpm:
                show_tpm = False

            right2 = cluster(show_tpm, show_share, show_out)
            pad2   = max(1, target_w - left2_w - _visible_width(right2))
            line2  = f'{left2}{" " * pad2}{right2}'

            return f'{line1}\n{line2}'

        else:
            # --- narrow single-line collapse ---
            kind = sub.last_activity[0]
            tool_verb = sub.last_activity[1] if kind == 'tool_use' else (
                '(thinking)' if kind == 'thinking' else
                '(replying)' if kind == 'text' else ''
            )

            right_n = (
                f'{ctx_clr}{GLYPH_HOURGLASS} {tok_s}{self.R}'
                f'  {self.LABEL}{BOLD}↑{self.R}{self.CTX}{out_s}{self.R}'
                f'  {self.CTX}{dur_s}{self.R}'
            )
            right_n_w = _visible_width(right_n)

            left_n = (
                f'{c_marker}{BOLD}{GLYPH_SUBAGENT_ROW}{self.R}  '
                f'{self.SKILLS}{type_text}{self.R}'
                f'  {model_clr}{short_model}{self.R}'
                f'  {self.CTX}{tool_verb}{self.R}'
            )
            left_n_w = _visible_width(left_n)
            pad_n    = max(1, target_w - left_n_w - right_n_w)
            return f'{left_n}{" " * pad_n}{right_n}'

    def task_row(self, tasks: TaskList, width: int, compact: bool = False) -> str:
        step    = rainbow_step()
        c_glyph = rainbow_at(step, 9)
        done    = tasks.completed
        total   = tasks.total
        count_s = f'{done}/{total}'

        head = f'{c_glyph}{BOLD}{GLYPH_TASKS}{self.R}  {self.SKILLS}{count_s}{self.R}'
        if compact:
            return head

        if done == total:
            text = ''
        else:
            active = tasks.active
            if active is not None:
                text = active.active_form or active.subject
            else:
                nxt = tasks.next_pending
                text = nxt.subject if nxt else ''

        if not text:
            return head

        target_w = width - 4
        head_w   = 3 + len(count_s) + 2  # glyph + '  ' + count + '  '
        budget   = max(0, target_w - head_w)
        if len(text) > budget:
            text = (text[:budget - 1] + '…') if budget > 0 else ''
        return f'{head}  {self.CTX}{text}{self.R}'

    RATE_W  = 6
    IN_W    = 6
    CACHE_W = 6
    OUT_W   = 6

    def tokens_cost(self, sess_in: int, sess_cache: int, sess_out: int, day_in: int, day_cache: int, day_out: int, sess_cost: float, day_cost: float, tok_rate: int, session_id: str = '', box_width: int = 80, fill: float = 1.0) -> tuple[list[str], tuple[int, int], int]:
        day_clr = self.day_cost_colour(day_cost)
        in_active, out_active = TokenRate.recently_active(session_id)
        in_icon  = (_glyph('↓', '\U0001f847') if in_active  else '↓') + ' '  # 🡇+space or ↓+space (both 2 cols)
        out_icon = (_glyph('↑', '\U0001f845') if out_active else '↑') + ' '  # 🡅+space or ↑+space (both 2 cols)

        sess_in_s    = fmt_tok(sess_in).rjust(self.IN_W)
        day_in_s     = fmt_tok(day_in).rjust(self.IN_W)
        sess_cache_s = fmt_tok(sess_cache).rjust(self.CACHE_W)
        day_cache_s  = fmt_tok(day_cache).rjust(self.CACHE_W)
        sess_out_s   = fmt_tok(sess_out).rjust(self.OUT_W)
        day_out_s    = fmt_tok(day_out).rjust(self.OUT_W)

        vsep_w        = 4
        vsep_leader_w = 4

        middle1 = f'{self.LABEL}{self.BOLDY}{in_icon}{self.R}{self.TOK}{sess_in_s}{self.R} {self.TOK_DIM}({sess_cache_s}){self.R}{self.LABEL} {self.BOLDY}{out_icon}{self.R}{self.TOK}{sess_out_s}{self.R}'
        middle2 = f'{self.LABEL}{self.BOLDY}{in_icon}{self.R}{self.TOK_DAY}{day_in_s}{self.R} {self.TOK_DAY_DIM}({day_cache_s}){self.R}{self.LABEL} {self.BOLDY}{out_icon}{self.R}{self.TOK_DAY}{day_out_s}{self.R}'

        cost1 = f'${sess_cost:,.2f}'
        cost2 = f'${day_cost:,.2f}'
        cost_width = max(_visible_width(cost1), _visible_width(cost2))

        end1 = f'{self.safe}{ICON_COST}{self.R} {self.COST}{cost1.rjust(cost_width)}{self.R}'
        end2 = f'  {self.LABEL}{self.R}{day_clr}{cost2.rjust(cost_width)}{self.R}'

        label_w = 15
        w_middle = _visible_width(middle1)
        w_end    = max(_visible_width(end1), _visible_width(end2))
        content_w = box_width - 3
        leader_w = max(label_w + 1, content_w - w_middle - w_end - vsep_w - vsep_leader_w)

        col1 = w_middle + 5                  # 1-indexed position of vsep │
        col2 = w_middle + vsep_w + w_end + 5  # 1-indexed position of vsep_leader │
        vsep        = self.vsep_block(col1, box_width, fill=fill, leader=True)
        vsep_leader = self.vsep_block(col2, box_width, fill=fill, leader=True)
        # bar_w = leader_w - label_w

        rate_label = f'{self.TOK_ICON}{ICON_TOK_RATE} {self.TOK}{fmt_tok(tok_rate)}{self.R}{self.LABEL} t/m{self.R}'
        rate_label_w = _visible_width(rate_label)
        rate_label_padded = f'{rate_label}' #{" " * max(0, label_w - rate_label_w)}'
        bar_w = leader_w - rate_label_w

        if bar_w <= 0:
            leader1 = rate_label_padded
            leader2 = ' ' * label_w
        else:
            if session_id:
                spark_history = TokenRate.history(session_id, bar_w, TokenRate.WINDOW * 2)
                top_row, bot_row = self.sparkline(spark_history[::-1], live=True)
            else:
                top_row, bot_row = ' ' * bar_w, ' ' * bar_w
            leader1 = f'{rate_label_padded}{top_row}'
            # leader2 = f'{" " * label_w}{bot_row}'
            leader2 = f'{" " * rate_label_w}{bot_row}'

        # 1-indexed column of the WINDOW (60s) tick inside the sparkline. History
        # spans WINDOW*2 (=120s) across bar_w buckets reversed so index 0 is "now",
        # which puts the 60s boundary at bar_w // 2. col2 is the vsep_leader │
        # column; sparkline starts rate_label_w cells past that.
        mark_col = col2 + rate_label_w + (bar_w // 2) if bar_w > 0 else 0

        return [
            f'{middle1}{vsep}{end1}{vsep_leader}{leader1}',
            f'{middle2}{vsep}{end2}{vsep_leader}{leader2}',
        ], (col1, col2), mark_col

    def context_bar(self, fill_ratio: float) -> str:
        ratio = min(max(fill_ratio, 0.0), 1.0)
        filled = int(ratio * 30)
        bar_filled = BarChars.FILLED * filled
        bar_empty = BarChars.EMPTY * (30 - filled)
        if ratio >= 0.9:
            color = self.alert
        elif ratio >= 0.7:
            color = self.warn
        else:
            color = self.safe
        return f'{color}{bar_filled}{self.R}{self.BAR_EMPTY}{bar_empty}{self.R}'

    def context_bar_color(self, fill_ratio: float) -> str:
        ratio = min(max(fill_ratio, 0.0), 1.0)
        if ratio >= 0.9:
            return self.alert
        elif ratio >= 0.7:
            return self.warn
        else:
            return self.safe

    _EMPTY_FADE_256 = re.compile(r'\x1b\[38;5;(\d+)m')
    _EMPTY_FADE_RGB = re.compile(r'\x1b\[38;2;(\d+);(\d+);(\d+)m')

    def _empty_fade_colors(self) -> list[str]:
        # 3-step ramp going from a darker shade up to BAR_EMPTY, so the fill→empty
        # seam blends instead of butting a coloured glyph against flat grey.
        m = self._EMPTY_FADE_256.search(self.BAR_EMPTY)
        if m:
            n = int(m.group(1))
            return [f'\033[38;5;{max(232, n - k)}m' for k in (6, 4, 2)]
        m = self._EMPTY_FADE_RGB.search(self.BAR_EMPTY)
        if m:
            r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return [f'\033[38;2;{int(r*k)};{int(g*k)};{int(b*k)}m' for k in (0.3, 0.5, 0.7)]
        return [self.BAR_EMPTY] * 3

    def _empty_section(self, empty: int, blend: bool = True) -> str:
        if empty <= 0:
            return ''
        if not blend:
            return f'{self.BAR_EMPTY}{BarChars.EMPTY * empty}'
        fade  = self._empty_fade_colors()
        n     = min(len(fade), empty)
        parts = [f'{fade[i]}{BarChars.EMPTY}' for i in range(n)]
        if empty > n:
            parts.append(f'{self.BAR_EMPTY}{BarChars.EMPTY * (empty - n)}')
        return ''.join(parts)

    def context_line(self, ctx: ContextWindow, available: int = 76) -> str:
        total_tokens = ctx.total_input_tokens + ctx.total_output_tokens
        # Real context-window fill, 0-100% -- never the old tokens/150K
        # "pressure" number (which could read e.g. 524%). Fall back to the soft
        # limit as the scale only when the model's window size is unknown.
        scale      = ctx.context_window_size if ctx.context_window_size > 0 else SOFT_LIMIT
        fill_ratio = min(total_tokens / scale, 1.0) if scale > 0 else 0.0
        pct        = fill_ratio * 100
        clr        = self.fill_colour(pct)
        prefix = f'{clr}{self.R}{self.DIM_GREEN}{fmt_tok(total_tokens)}{self.R} {clr}{BOLD}{pct:.0f}%{self.R} '
        bar_w  = max(4, available - _visible_width(prefix) - 3)
        filled = int(fill_ratio * bar_w)
        empty  = max(0, bar_w - filled - (1 if filled < bar_w else 0))
        bar    = f'{self.gradient_bar(filled, bar_w)}{self.R}{self._empty_section(empty, blend=filled > 0)}{self.R}'
        return f'{clr}{self.R} {prefix}{bar}'


    def context_line_compact(self, ctx: ContextWindow, available: int) -> str:
        total_tokens = ctx.total_input_tokens + ctx.total_output_tokens
        scale      = ctx.context_window_size if ctx.context_window_size > 0 else SOFT_LIMIT
        fill_ratio = min(total_tokens / scale, 1.0) if scale > 0 else 0.0
        pct        = fill_ratio * 100
        clr        = self.fill_colour(pct)
        prefix  = f'{clr}{BOLD}{pct:.0f}%{self.R} '
        bar_w   = max(4, available - _visible_width(prefix) - 3)
        filled  = int(fill_ratio * bar_w)
        empty   = max(0, bar_w - filled - (1 if filled < bar_w else 0))
        bar     = f'{self.gradient_bar(filled, bar_w)}{self.R}{self._empty_section(empty, blend=filled > 0)}{self.R}'
        return f' {prefix}{bar}'

    SPEC_GRADIENTS: Sequence[tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]] = [
        ((20, 60, 200),  (30, 200, 180),  (220, 255, 120)),     # Ocean    blue → teal → pale green
        ((60, 20, 160),  (240, 60, 140),  (255, 200, 60)),      # Sunset   indigo → magenta → gold
        ((10, 80, 120),  (120, 220, 40),  (240, 240, 60)),      # Forest   navy → lime → yellow
        ((80, 20, 200),  (240, 100, 220), (255, 200, 160)),     # Lavender purple → hot-pink → peach
        ((140, 20, 30),  (240, 120, 20),  (255, 230, 80)),      # Ember    dark-red → orange → yellow
        ((30, 40, 140),  (60, 200, 240),  (220, 240, 255)),     # Arctic   navy → cyan → white
        ((90, 30, 10),   (220, 120, 30),  (255, 220, 100)),     # Copper   brown → orange → gold
        ((160, 10, 50),  (240, 100, 160), (255, 220, 220)),     # Rose     wine → pink → cream
        ((10, 90, 100),  (60, 220, 160),  (220, 255, 180)),     # Mint     dark-teal → mint → pale-yellow
        ((40, 10, 140),  (220, 40, 200),  (60, 220, 240)),      # Nebula   violet → magenta → cyan
        ((140, 30, 200), (40, 180, 240),  (60, 230, 120)),      # Aurora   violet → cyan → green
        ((60, 0, 20),    (220, 60, 20),   (255, 220, 40)),      # Volcano  black-red → orange → yellow
    ]

    SPEC_MID_MIN_WIDTH = 20

    def _spec_rgb_at(self, t: float, idx: int, three_stops: bool = True) -> tuple[int, int, int]:
        stops: tuple[tuple[int, int, int], ...] = self.SPEC_GRADIENTS[idx % len(self.SPEC_GRADIENTS)]
        if not three_stops:
            stops = (stops[0], stops[-1])
        n = len(stops)
        seg = max(0.0, min(1.0, t)) * (n - 1)
        s0 = min(int(seg), n - 2)
        s1 = s0 + 1
        u = seg - s0
        c0, c1 = stops[s0], stops[s1]
        return (
            int(c0[0] + (c1[0] - c0[0]) * u),
            int(c0[1] + (c1[1] - c0[1]) * u),
            int(c0[2] + (c1[2] - c0[2]) * u),
        )

    def spec_gradient_bar(self, filled: int, bar_w: int, idx: int) -> str:
        if filled <= 0 or bar_w <= 0:
            return ''
        denom = max(1, bar_w - 1)
        three_stops = bar_w >= self.SPEC_MID_MIN_WIDTH
        parts = []
        for i in range(filled):
            r, g, b = self._spec_rgb_at(i / denom, idx, three_stops)
            parts.append(f'\033[38;2;{r};{g};{b}m{BarChars.HEAVY}')
        return ''.join(parts)

    def openspec_bar(self, name: str, done: int, total: int, box_width: int = 80, title_w: int = 25, idx: int = 0) -> str:
        pct = done * 100 // total
        if len(name) > title_w:
            title = name[:max(1, title_w - 3)] + '...'
        else:
            title = name.ljust(title_w)
        suffix_visible = 7 + len(str(done)) + len(str(total))
        bar_w = max(4, (box_width - 3) - (title_w + 1) - suffix_visible)
        filled = done * bar_w // total
        empty = bar_w - filled

        bar_filled = self.spec_gradient_bar(filled, bar_w, idx)
        if filled > 0 and empty > 0:
            denom = max(1, bar_w - 1)
            three_stops = bar_w >= self.SPEC_MID_MIN_WIDTH
            cr, cg, cb = self._spec_rgb_at(filled / denom, idx, three_stops)
            r, g, b = int(cr * 0.45), int(cg * 0.45), int(cb * 0.45)
            bar_filled += f'\033[38;2;{r};{g};{b}m{BarChars.HEAVY}'
            empty -= 1
        bar_empty = f'{self.spec_empty_ansi}{BarChars.HEAVY * empty}\033[0m'

        return (
            f'{CLR_WHITE_BRT}{ITALIC}{title}{RESET}{self.R} '
            f'{bar_filled}{self.R}{bar_empty}'
            f' {self.LABEL}{done}/{total}{self.R} {BOLD}{pct:>3d}%{RESET}'
        )

    def burndown_trend(self, used_pct: float, resets_at: int, window_minutes: int, warmup_minutes: int, now: float | None = None) -> str:
        delta = burndown_delta(used_pct, resets_at, window_minutes, warmup_minutes, now=now)
        if delta is None:
            return ''
        abs_delta = abs(delta)
        # Map delta onto the fill gradient: t=0 (green) at max under-burn,
        # t=0.5 (yellow-orange midpoint) at neutral, t=1 (red/purple) at max over-burn.
        t = max(0.0, min(1.0, 0.5 + delta / 50.0))
        colour = self.gradient.gradient_color(t)
        glyph = GLYPH_BURN_FAST if delta > 0 else GLYPH_BURN_SLOW # colour modulation carries over/under-burn direction
        sign  = '-' if delta < 0 else '+'
        return f'{colour}{glyph} {sign}{abs_delta:05.2f}%{self.R}'

    def helper(self, five_hour: RateBucket) -> str:
        pct_clr = self.fill_colour(float(five_hour.used_percentage or 0))
        try:
            if not five_hour.resets_at:
                if not five_hour.used_percentage:
                    return '∞'
                return f'{pct_clr}{five_hour.used_percentage}%{self.R} {self.COMMIT}∞'
            resets_at = datetime.fromtimestamp(five_hour.resets_at).astimezone()
            delta = resets_at - clock.now().astimezone().replace(microsecond=0)
            if delta.total_seconds() <= 0:
                if not five_hour.used_percentage:
                    return '∞'
                return f'{pct_clr}{five_hour.used_percentage}%{self.R} {self.COMMIT}∞'
            trend = self.burndown_trend(
                float(five_hour.used_percentage or 0),
                five_hour.resets_at,
                FIVE_HOUR_MINUTES,
                FIVE_HOUR_WARMUP_MINUTES,
            )
            trend_part = f' {trend}' if trend else ''
            return f'{pct_clr}{five_hour.used_percentage}%{self.R}{trend_part} {self.COMMIT}T-{delta}'
        except Exception as e:
            return f'{e.__class__.__name__}, {str(e)}'

@dataclass
class RowSpec:
    kind: str  # 'top_border', 'bottom_border', 'separator', 'separator_dim', 'content'
    content: str = ''
    bg_lead: str = ''
    bg_trail: str = ''
    pill_flush: bool = False
    ups: tuple[int, ...] = ()
    downs: tuple[int, ...] = ()
    pill: Pill | None = None
    pill_edge: str = 'bottom'
    right_pill: str = ''


@dataclass
class LayoutSpec:
    width: int
    fill: float
    session_id: str
    rows: list[RowSpec] = field(default_factory=list)


def build_narrow(session: SessionInfo, width: int, r: Renderer) -> LayoutSpec:
    ctx          = session.context_window
    total_tokens = ctx.total_input_tokens + ctx.total_output_tokens
    fill         = min(total_tokens / SOFT_LIMIT, 1.0)

    effort_for_bg = session.effort.level if session.thinking.enabled else ''
    pill_pct      = r._model_bg_pct(effort_for_bg)
    pill_anchor, pill_shift = r._model_anchor_pair(session.model_name) if pill_pct else ((0, 0, 0), (0, 0, 0))

    max_right    = max(8, width // 2)
    rate_text, right_text, right_w = r.model_right_section_compact(
        session.model_name, session.rate_limits, max_right, effort_for_bg,
    )
    line_context = r.context_line_compact(ctx, width - 3)

    pill: Pill | None = None
    if pill_pct:
        pill = Pill(start=width - right_w + 1, end=width, anchor=pill_anchor, shift=pill_shift, pct=pill_pct)

    subagents = RunningSubagents.from_session(session.session_id, session.workspace.project_dir)
    spec = LayoutSpec(width=width, fill=fill, session_id=session.session_id)
    if pill_pct:
        rows: list[RowSpec] = [
            RowSpec('top_border', pill=pill),
            RowSpec('content', content=rate_text, right_pill=right_text),
            RowSpec('separator_dim', pill=pill),
        ]
    else:
        rate_w = _visible_width(rate_text)
        pad    = max(1, (width - 4) - rate_w - right_w)
        full   = f'{rate_text}{" " * pad}{right_text}'
        rows = [
            RowSpec('top_border'),
            RowSpec('content', content=full),
            RowSpec('separator_dim'),
        ]
    if subagents.subagents:
        for sub in subagents.subagents:
            for line in r.subagent_row(sub, width, session_inout=0).split('\n'):
                rows.append(RowSpec('content', content=line))
        rows.append(RowSpec('separator_dim'))
    rows.append(RowSpec('content', content=line_context))
    rows.append(RowSpec('bottom_border'))
    spec.rows = rows
    return spec


def build_medium(session: SessionInfo, width: int, r: Renderer) -> LayoutSpec:
    ctx          = session.context_window
    total_tokens = ctx.total_input_tokens + ctx.total_output_tokens
    fill         = min(total_tokens / SOFT_LIMIT, 1.0)

    effort_for_bg = session.effort.level if session.thinking.enabled else ''
    pill_pct      = r._model_bg_pct(effort_for_bg)
    pill_anchor, pill_shift = r._model_anchor_pair(session.model_name) if pill_pct else ((0,0,0), (0,0,0))

    git          = GitInfo.from_cwd(session.cwd, session.session_id)
    line_context = r.context_line_compact(ctx, width - 3)

    max_right    = max(8, width // 2)
    rate_text, right_text, right_w = r.model_right_section_compact(
        session.model_name, session.rate_limits, max_right, effort_for_bg,
    )

    spec = LayoutSpec(width=width, fill=fill, session_id=session.session_id)

    vsep_w   = 5
    rate_w   = _visible_width(rate_text)
    target_w = (width - 4) - vsep_w - rate_w - right_w
    line_path = r.fit_path(session.short_pwd, git, '', target_w, compact_only=True)
    path_w   = _visible_width(line_path)

    pill: Pill | None = None
    if pill_pct:
        pill = Pill(start=width - right_w + 1, end=width, anchor=pill_anchor, shift=pill_shift, pct=pill_pct)

    path_div_col = 3 + path_w + 2
    vsep = r.vsep_block(path_div_col, width, fill=fill, leader=True)
    content = f'{line_path}{vsep}{rate_text}'
    if pill_pct:
        top_row     = RowSpec('top_border', downs=(path_div_col,), pill=pill)
        content_row = RowSpec('content', content=content, right_pill=right_text)
        sep_row     = RowSpec('separator_dim', ups=(path_div_col,), pill=pill)
    else:
        pad = max(1, (width - 3) - (path_w + vsep_w + rate_w + right_w))
        full = f'{content}{" " * pad}{right_text}'
        top_row     = RowSpec('top_border', downs=(path_div_col,))
        content_row = RowSpec('content', content=full)
        sep_row     = RowSpec('separator_dim', ups=(path_div_col,))
    tasks     = TaskList.from_session(session.transcript_path)
    subagents = RunningSubagents.from_session(session.session_id, session.workspace.project_dir)
    rows: list[RowSpec] = [top_row, content_row, sep_row]
    if tasks.is_visible():
        rows.append(RowSpec('content', content=r.task_row(tasks, width, compact=True)))
        rows.append(RowSpec('separator_dim'))
    if subagents.subagents:
        for sub in subagents.subagents:
            for line in r.subagent_row(sub, width, session_inout=0).split('\n'):
                rows.append(RowSpec('content', content=line))
        rows.append(RowSpec('separator_dim'))
    rows.append(RowSpec('content', content=line_context))
    rows.append(RowSpec('bottom_border'))
    spec.rows = rows
    return spec


def build_wide(session: SessionInfo, width: int, r: Renderer) -> LayoutSpec:
    ctx          = session.context_window
    total_tokens = ctx.total_input_tokens + ctx.total_output_tokens
    fill         = min(total_tokens / SOFT_LIMIT, 1.0)

    effort_for_bg = session.effort.level if session.thinking.enabled else ''
    pill_pct      = r._model_bg_pct(effort_for_bg)
    pill_anchor, pill_shift = r._model_anchor_pair(session.model_name) if pill_pct else ((0,0,0), (0,0,0))

    skills        = LoadedSkills.from_transcript(session.transcript_path)
    skill_display = ','.join(s.split(':', 1)[-1] for s in skills.names)
    usage         = TranscriptUsage.from_transcript(session.transcript_path)
    today         = clock.now().strftime('%Y-%m-%d')
    token_log     = TokenLog.update(session.session_id, today, usage.billed_in, usage.cache_read, usage.out, _model_log_key(session.model))
    tok_rate      = TokenRate.update(session.session_id, usage.billed_in, usage.out)
    sess_cost     = session_cost_display(session, usage)
    day_cost      = compute_day_cost(session.model, token_log)
    subagents     = RunningSubagents.from_session(session.session_id, session.workspace.project_dir)
    session_inout = (
        (usage.billed_in + usage.cache_read) + usage.out
        + sum(s.total_input + s.output for s in subagents.subagents)
    )
    tasks         = TaskList.from_session(session.transcript_path)
    elapsed       = elapsed_from_transcript(session.transcript_path)

    git          = GitInfo.from_cwd(session.cwd, session.session_id)
    helper_text, right_text, right_w = r.model_right_section(
        session.model_name, session.model_thinking, session.rate_limits,
        session.effort.level if session.thinking.enabled else '',
        fast_mode=session.fast_mode,
    )
    line_tokens, vsep_cols, spark_mark_col = r.tokens_cost(
        usage.billed_in, usage.cache_read, usage.out,
        token_log.day_in, token_log.day_cache_read, token_log.day_out,
        sess_cost, day_cost, tok_rate,
        session.session_id, width, fill,
    )
    plugins_line = r.plugins_skills(len(skills.names), skill_display, session.workspace.plugins, width)
    changes      = OpenSpec.from_cwd(session.cwd).changes
    title_cap    = max(10, width - 45)
    title_w      = min(40, title_cap, max((len(n) for n, _, _ in changes), default=25))
    openspec_bars = [r.openspec_bar(name, d, t, width, title_w, i) for i, (name, d, t) in enumerate(changes)]

    line_context = r.context_line(ctx, width - 3)

    spec = LayoutSpec(width=width, fill=fill, session_id=session.session_id)
    rows: list[RowSpec] = []

    vsep_w   = 5
    helper_w = _visible_width(helper_text)
    target_w = (width - 4) - vsep_w - helper_w - right_w
    line_path = r.fit_path(session.short_pwd, git, elapsed, target_w, compact_only=False)
    path_w   = _visible_width(line_path)

    pill: Pill | None = None
    if pill_pct:
        pill = Pill(start=width - right_w + 1, end=width, anchor=pill_anchor, shift=pill_shift, pct=pill_pct)

    path_div_col = 3 + path_w + 2
    vsep = r.vsep_block(path_div_col, width, fill=fill, leader=True)
    content = f'{line_path}{vsep}{helper_text}'
    if pill_pct:
        rows += [
            RowSpec('top_border', downs=(path_div_col,), pill=pill),
            RowSpec('content', content=content, right_pill=right_text),
        ]
    else:
        pad = max(1, (width - 3) - (path_w + vsep_w + helper_w + right_w))
        content_full = f'{content}{" " * pad}{right_text}'
        rows += [
            RowSpec('top_border', downs=(path_div_col,)),
            RowSpec('content', content=content_full),
        ]

    rows.append(RowSpec('separator_dim', ups=(path_div_col,), pill=pill))
    rows.append(RowSpec('content', content=line_context))

    tokens_downs = vsep_cols + ((spark_mark_col,) if spark_mark_col else ())
    rows.append(RowSpec('separator_dim', downs=tokens_downs))
    for lt in line_tokens:
        rows.append(RowSpec('content', content=lt))

    # First post-tokens separator threads `ups` back into the tokens vseps and
    # is drawn as the heavy "seam" marking the static→dynamic split. Only the
    # first one — later inter-section separators keep their normal style. When
    # nothing dynamic follows, no seam is drawn (the bottom border closes off).
    pending_ups: tuple[int, ...] = vsep_cols
    seam_pending = True

    def sep_kind(normal: str) -> str:
        nonlocal seam_pending
        if seam_pending:
            seam_pending = False
            return 'separator_seam'
        return normal

    if plugins_line:
        rows.append(RowSpec(sep_kind('separator_dim'), ups=pending_ups))
        rows.append(RowSpec('content', content=plugins_line))
        pending_ups = ()

    if tasks.is_visible():
        rows.append(RowSpec(sep_kind('separator_dim'), ups=pending_ups))
        rows.append(RowSpec('content', content=r.task_row(tasks, width)))
        pending_ups = ()

    if subagents.subagents:
        rows.append(RowSpec(sep_kind('separator_dim'), ups=pending_ups))
        for sub in subagents.subagents:
            for line in r.subagent_row(sub, width, session_inout=session_inout).split('\n'):
                rows.append(RowSpec('content', content=line))
        pending_ups = ()

    if openspec_bars:
        rows.append(RowSpec(sep_kind('separator'), ups=pending_ups))
        for bar in openspec_bars:
            rows.append(RowSpec('content', content=bar))
        rows.append(RowSpec('bottom_border'))
    else:
        rows.append(RowSpec('bottom_border', ups=pending_ups))

    spec.rows = rows
    return spec


def render_layout(spec: LayoutSpec, r: Renderer) -> list[str]:
    lines: list[str] = []
    for row in spec.rows:
        if row.kind == 'top_border':
            lines.append(r.border_top(spec.width, spec.session_id, downs=row.downs, fill=spec.fill, pill=row.pill))
        elif row.kind == 'bottom_border':
            lines.append(r.border_bottom(spec.width, ups=row.ups, fill=spec.fill))
        elif row.kind == 'separator':
            lines.append(r.border_separator(spec.width, ups=row.ups, fill=spec.fill))
        elif row.kind == 'separator_seam':
            # Static→dynamic split: a full-brightness solid rule (vs the dotted-dim
            # separators between dynamic sections). Renders via the solid separator.
            lines.append(r.border_separator(spec.width, ups=row.ups, fill=spec.fill))
        elif row.kind == 'separator_dim':
            lines.append(r.border_separator_dim(spec.width, downs=row.downs, ups=row.ups, fill=spec.fill, pill=row.pill, pill_edge=row.pill_edge))
        elif row.kind == 'content':
            lines.append(r.border_line(row.content, spec.width, fill=spec.fill, bg_lead=row.bg_lead, bg_trail=row.bg_trail, pill_flush=row.pill_flush, right_pill=row.right_pill))
    return lines


def resolve_theme(cli_name: str | None) -> Theme:
    """Layered theme selection: CLI → env → config file → CLAUDE_DARK."""
    if cli_name and cli_name in THEMES:
        return THEMES[cli_name]
    env = os.environ.get('CLAUDE_STATUSLINE_THEME', '').strip()
    if env in THEMES:
        return THEMES[env]
    try:
        cfg = (config.CLAUDE_DIR / 'statusline-theme').read_text().strip()
        if cfg in THEMES:
            return THEMES[cfg]
    except OSError:
        pass
    return CLAUDE_DARK


def render(session_info: dict[str, object], width: int, *, bg_shift: str = 'warm', theme: Theme | None = None) -> str:
    if width < MIN_WIDTH:
        return ''
    session = SessionInfo.from_dict(session_info)
    r       = Renderer(bg_shift=bg_shift, theme=theme)
    if width < NARROW_WIDTH:
        spec = build_narrow(session, width, r)
    elif width < MEDIUM_WIDTH:
        spec = build_medium(session, width, r)
    else:
        spec = build_wide(session, width, r)
    return '\n'.join(render_layout(spec, r))


def main() -> None:
    # Force UTF-8 on stdout so the script renders correctly on Windows
    # (cp1252 default codec can't encode box-drawing or Nerd Font glyphs,
    # crashes with UnicodeEncodeError on the first border char). Python's
    # PEP 540 UTF-8 mode and PYTHONIOENCODING env var both fix this from
    # the outside; reconfiguring stdout here removes the requirement that
    # callers set either. No-op on platforms whose default codec is
    # already UTF-8 (most Unix systems since Python 3.7).
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    bg_shift   = 'warm'
    theme_name: str | None = None
    args = sys.argv[1:]
    while args:
        a = args.pop(0)
        if a == '--bg-shift' and args:
            v = args.pop(0).lower()
            if v in ('warm', 'cool'):
                bg_shift = v
        elif a.startswith('--bg-shift='):
            v = a.split('=', 1)[1].lower()
            if v in ('warm', 'cool'):
                bg_shift = v
        elif a == '--theme' and args:
            theme_name = args.pop(0)
        elif a.startswith('--theme='):
            theme_name = a.split('=', 1)[1]

    info  = json.loads(sys.stdin.read())
    theme = resolve_theme(theme_name)

    # Write payload so the multi-session observer can index it. Keyed by
    # session_id and overwritten in place, so the dir holds one file per
    # session rather than one per render tick. The observer already collapses
    # to the newest payload per session (mon/discovery.index_payloads_by_session),
    # so the old timestamped filenames only ever accumulated dead weight.
    session_id = _as_str(info.get('session_id')) or 'unknown'
    _atomic_write_text(config.CLAUDE_DIR / 'statusline-output' / f'statusline.{session_id}.json', json.dumps(info))

    raw_tw = terminal_width()
    if raw_tw < MIN_WIDTH:
        return
    if os.environ.get('YAS_FULL_WIDTH'):
        width = max(MIN_WIDTH, raw_tw-6)
    else:
        width = max(MIN_WIDTH, min(MAX_WIDTH, raw_tw - 6))

    sys.stdout.write(render(info, width, bg_shift=bg_shift, theme=theme))


if __name__ == '__main__':
    main()
