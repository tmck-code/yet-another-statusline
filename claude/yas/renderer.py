"""Renderer and all section-helper methods for the statusline."""

from __future__ import annotations

import re
import time
import zlib
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from yas.render.borders import BorderRenderer
from yas.constants import (
    BOLD,
    ITALIC,
    RESET,
    BarChars,
    CLR_CYAN,
    CLR_CYAN_DAY,
    CLR_CYAN_DAY_DIM,
    CLR_CYAN_DIM,
    CLR_CYAN_ICON,
    CLR_GOLD,
    CLR_GREEN_BRT,
    CLR_GREEN_DIM,
    CLR_GREEN_OK,
    CLR_GREY_DARK,
    CLR_GREY_DIM,
    CLR_PEACH,
    CLR_PINK,
    CLR_PURPLE,
    CLR_SKY_BLUE,
    CLR_WARN,
    CLR_WHITE_BRT,
    CLR_YELLOW,
    CLR_YELLOW_BRT,
    DEFAULT_SOFT_LIMIT,
    FIVE_HOUR_MINUTES,
    FIVE_HOUR_WARMUP_MINUTES,
    GLYPH_BURN_FAST,
    GLYPH_BURN_SLOW,
    GLYPH_CONTINUATION,
    GLYPH_FOLDER,
    GLYPH_CACHE,
    GLYPH_CLEAR,
    GLYPH_HOURGLASS,
    GLYPH_MODEL_LIGHT,
    GLYPH_PLUGINS,
    GLYPH_RENAMED,
    GLYPH_REPLYING,
    GLYPH_SKILLS,
    GLYPH_SUBAGENT_ROW,
    GLYPH_SUBAGENT_DONE,
    GLYPH_TASKS,
    GLYPH_TASK_ACTIVE,
    GLYPH_TASK_DONE,
    GLYPH_TASK_PENDING,
    GLYPH_THINKING,
    GLYPH_WF_CURRENT,
    GLYPH_WF_HEADER,
    GLYPH_WF_SUMMARY,
    ICON_COST,
    ICON_LIMIT_5H,
    ICON_LIMIT_7D,
    ICON_TOK_RATE,
    PILL_LEFT,
    PILL_RIGHT,
    SEVEN_DAY_MINUTES,
    SEVEN_DAY_WARMUP_MINUTES,
    TASK_HEADER_RIGHT_GAP_MIN,
    WF_NAME_MIN,
    WF_PHASE_DOT,
    WF_PHASE_GAP,
)
from yas.render.gradient import (
    GradientEngine,
    model_key,
    paint_bg_span,
    pill_gradient_fg,
    rainbow_at,
    rainbow_step,
    _scale,
)
from yas.info.git import GitInfo
from yas.render.metrics import burndown_delta, subagent_share
from yas.render.pill import Pill
from yas.render.tasks_view import fmt_duration, select_window, total_elapsed
from yas.session import ContextWindow, RateBucket, RateLimits
from yas.info.subagents import RunningSubagent
from yas.info.workflows import RunningWorkflow
from yas.info.tasks import TaskList
from yas.render.text import _middle_ellipsis, _visible_width, fmt_dur, fmt_tok
from yas.tokens import TokenRate

if TYPE_CHECKING:
    from yas.themes import Theme

# Runtime import of themes (the package module is always available when running
# as a package; no importlib shim needed).
from yas.themes import CLAUDE_DARK, Theme


# ---------------------------------------------------------------------------
# Module-level constants used only by the Renderer
# ---------------------------------------------------------------------------

LEVEL_PCT: dict[str, int] = {
    'low':    30,
    'medium': 55,
    'high':   80,
    'xhigh':  100,
    'max':    140,
}

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


# ---------------------------------------------------------------------------
# Context-fill helpers
# ---------------------------------------------------------------------------

def _ctx_used_tokens(ctx: ContextWindow) -> int:
    """The effective context-token count that drives the bar, label, and colour.

    Prefer the host-supplied `ctx.used_percentage` (Claude Code's own /context
    value, input-only): convert it back to an absolute count via
    `context_window_size`.  Fall back to `total_input_tokens` (input-only) when
    the host value is absent (`None`) or the window size is unknown.  Clamped to
    >= 0 so a negative host value never produces a negative count.

    This is the single source of truth: `_ctx_fill_ratio` scales it by the soft
    limit, and `context_line` renders the same number as the displayed figure,
    so the label and the fill can never disagree.
    """
    if ctx.used_percentage is not None and ctx.context_window_size > 0:
        return max(0, round(ctx.used_percentage / 100.0 * ctx.context_window_size))
    return max(0, ctx.total_input_tokens)


def _ctx_fill_ratio(ctx: ContextWindow, soft_limit: int) -> tuple[float, float]:
    """Return (fill_ratio, pct_soft) for the context bar.

    The bar fills relative to `soft_limit` (the compaction-risk threshold), so
    it reads 100% once usage reaches the soft limit, not the full model window.
    The token count comes from `_ctx_used_tokens`; divide-by-zero is guarded and
    the result is always in [0.0, 1.0].
    """
    if soft_limit <= 0:
        return 0.0, 0.0
    fill_ratio = min(_ctx_used_tokens(ctx) / soft_limit, 1.0)
    pct_soft   = fill_ratio * 100.0
    return fill_ratio, pct_soft


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

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

    def vsep_block(self, col: int, width: int, fill: float = 1.0, *, leader: bool = False, lead: int = 2) -> str:
        color    = self.gradient.grad_at(col - 1, width, fill=fill)
        trailing = ' ' if leader else '  '
        return f'{" " * lead}{color}│{self.R}{trailing}'

    def sparkline_1row(self, history: list[int], live: bool = False) -> str:
        return self.gradient.sparkline_1row(history, live)

    def spark_rgb(self, t: float, dim: float = 1.0) -> tuple[int, int, int]:
        return self.gradient.spark_rgb(t, dim)

    def spark_color(self, t: float, dim: float = 1.0) -> str:
        return self.gradient.spark_color(t, dim)

    # --- Border delegations (backward compat) ---
    def border_top(self, width: int, session_id: str = '', downs: tuple[int, ...] = (), fill: float = 1.0, pill: Pill | None = None, labels: tuple[tuple[str, int], ...] = ()) -> str:
        return self.border.border_top(width, session_id, downs, fill, pill, labels)

    def border_bottom(self, width: int, ups: tuple[int, ...] = (), fill: float = 1.0) -> str:
        return self.border.border_bottom(width, ups, fill)

    def border_separator(self, width: int, ups: tuple[int, ...] = (), downs: tuple[int, ...] = (), fill: float = 1.0, labels: tuple[tuple[str, int], ...] = ()) -> str:
        return self.border.border_separator(width, ups, downs, fill, labels)

    def border_separator_dim(self, width: int, downs: tuple[int, ...] = (), ups: tuple[int, ...] = (), fill: float = 1.0, pill: Pill | None = None, pill_edge: str = 'bottom', labels: tuple[tuple[str, int], ...] = ()) -> str:
        return self.border.border_separator_dim(width, downs, ups, fill, pill, pill_edge, labels)

    def border_line(self, content: str, width: int, fill: float = 1.0, bg_lead: str = '', bg_trail: str = '', pill_flush: bool = False, right_pill: str = '') -> str:
        return self.border.border_line(content, width, fill, bg_lead, bg_trail, pill_flush, right_pill)

    def path_git(
        self, short_pwd: str, git: GitInfo,
        *, show_path: bool = True, show_commit: bool = True, show_dirty: bool = True,
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
        commit_part = f'{self.LABEL}/{self.R}{self.COMMIT}{git.commit}{self.R}' if show_commit else ''
        # The cwd path is a whole unit: shown in full or omitted entirely (no
        # middle-ellipsis). show_path=False yields the branch-only rung (glyph +
        # arrow + branch) used as a width-degradation step below the path forms.
        path_part = f'{self.PWD}{short_pwd}{self.R} ' if show_path else ''

        return (
            f'{self.ICON_PATH}{GLYPH_FOLDER}  {path_part}'
            f'{self.LABEL}{self.ARROW}{BOLD}∈{self.R}'
            f' {self.BRANCH}{git.branch}{self.R}'
            f'{commit_part}{dirty}'
        )

    def path_glyph_only(self) -> str:
        """Presence-glyph floor: the folder glyph alone (1 visible column).

        The overflow-safe terminal state of the path ladder — it can never
        exceed the available width or disturb the box border math.
        """
        return f'{self.ICON_PATH}{GLYPH_FOLDER}{self.R}'

    def path_git_compact(self, short_pwd: str, git: GitInfo) -> str:
        return (
            f'{self.ICON_PATH}  {self.PWD}{short_pwd}{self.R}'
            f' {self.LABEL}{self.ARROW}{BOLD}∈{self.R}'
            f' {self.BRANCH}{git.branch}{self.R}'
        )

    def fit_path(
        self, short_pwd: str, git: GitInfo, target_w: int,
        *, compact_only: bool = False,
    ) -> str:
        def fits(s: str) -> bool:
            return _visible_width(s) <= target_w

        # Whole-unit include/omit ladder; first candidate that fits wins.
        # full → drop commit → drop commit+dirty → compact path+branch →
        # branch-only (path omitted) → glyph-only floor. The path is never
        # middle-ellipsized: it is shown in full or dropped whole, and the
        # branch outlives the path. compact_only enters at the compact rung.
        if not compact_only:
            for kwargs in (
                {},
                {'show_commit': False},
                {'show_commit': False, 'show_dirty': False},
            ):
                candidate = self.path_git(short_pwd, git, **kwargs)
                if fits(candidate):
                    return candidate

        compact = self.path_git_compact(short_pwd, git)
        if fits(compact):
            return compact

        # Path omitted whole, branch retained (glyph + arrow + branch).
        branch_only = self.path_git(
            short_pwd, git, show_path=False, show_commit=False, show_dirty=False,
        )
        if fits(branch_only):
            return branch_only

        # Glyph-only presence floor — 1 visible column, always within target.
        return self.path_glyph_only()

    def model_colour(self, model_name: str) -> str:
        return self.theme.models[model_key(model_name)].label

    def fill_colour(self, pct: float) -> str:
        if pct >= 90:
            return self.alert
        if pct >= 70:
            return self.warn
        return self.safe

    def elapsed_section(self, elapsed: str, clear_str: str = '') -> tuple[str, int]:
        """Compose the elapsed-cell content and its visible width.

        When *clear_str* is non-empty (session has been /clear-ed), the cell
        shows the clear timer first — ``GLYPH_CLEAR  <accent><clear_str>`` —
        followed by the grey right-justified session timer when *elapsed* is
        also non-empty.  Passing ``elapsed=''`` with a non-empty *clear_str*
        gives the clear-only degradation tier (no session timer).

        When both *clear_str* and *elapsed* follow their defaults (empty), the
        result is byte-identical to the pre-change single-timer form:
        ``<grey><elapsed rjust 8>``.
        """
        if clear_str:
            sess_part = (
                f'  {self.SESSION}{elapsed.rjust(8)}{self.R}'
                if elapsed else ''
            )
            text = f'{GLYPH_CLEAR}  {CLR_CYAN}{clear_str}{RESET}{sess_part}'
            return text, _visible_width(text)
        padded = elapsed.rjust(8)
        text   = f'{self.SESSION}{padded}{self.R}'
        return text, _visible_width(text)

    def cache_section(self, remaining: float, elapsed_pct: int) -> tuple[str, int]:
        total_s = int(remaining)
        if total_s >= 3600:
            h   = total_s // 3600
            rem = total_s % 3600
            m   = rem // 60
            sec = rem % 60
            dur = f'{h}:{m:02d}:{sec:02d}'
        else:
            m   = total_s // 60
            sec = total_s % 60
            dur = f'{m:02d}:{sec:02d}'
        colour = self.fill_colour(elapsed_pct)
        text   = f'{GLYPH_CACHE}  {colour}{dur}{RESET}'
        return text, _visible_width(text)

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
        rate_pct  = f'{pct_clr}{float(pct):.1f}%{self.R}'

        rate_with_time = None
        try:
            if rate_limits.five_hour.resets_at:
                resets_at = datetime.fromtimestamp(rate_limits.five_hour.resets_at).astimezone()
                delta = resets_at - datetime.now().astimezone().replace(microsecond=0)
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
                cells.append((GLYPH_MODEL_LIGHT, anchor, False, False))
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
                    f' {c_helper}{BOLD}{ICON_LIMIT_5H}{self.R} {rate}'
                ), pw
            return (
                f'{model_clr}{GLYPH_MODEL_LIGHT}  {name}{self.R}'
                f' {self.LABEL}|{self.R}'
                f' {c_helper}{BOLD}{ICON_LIMIT_5H}{self.R} {rate}'
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

    def _rate_helpers(self, rate_limits: RateLimits, gap_5h: int = 1, gap_7d: int = 1) -> tuple[str, str]:
        """Build the 5h and (optional) 7d limit sub-sections.

        ``gap_5h`` / ``gap_7d`` set the inter-stat separator width within each
        section (default 1). The justified top row widens them toward 3 to spend
        section slack as breathing room rather than only outer padding.
        """
        c_helper  = rainbow_at(rainbow_step(), 9)
        helper_5h = f'{c_helper}{BOLD}{ICON_LIMIT_5H}{self.R}  {self.white_brt}{BOLD}{self.helper(rate_limits.five_hour, gap_5h)}{self.R}'
        helper_7d = ''
        seven_day = rate_limits.seven_day
        if seven_day.used_percentage != 0 or seven_day.resets_at != 0:
            seven_clr     = self.fill_colour(float(seven_day.used_percentage or 0))
            seven_pct_str = f'{float(seven_day.used_percentage or 0):.1f}'
            seven_trend   = self.burndown_trend(
                float(seven_day.used_percentage or 0),
                seven_day.resets_at,
                SEVEN_DAY_MINUTES,
                SEVEN_DAY_WARMUP_MINUTES,
            )
            seven_trend_part = f'{" " * gap_7d}{seven_trend}' if seven_trend else ''
            helper_7d = f'{c_helper}{BOLD}{ICON_LIMIT_7D}{self.R}  {seven_clr}{seven_pct_str}%{self.R}{seven_trend_part}'
        return helper_5h, helper_7d

    def model_right_section(self, model_name: str, model_thinking: str, rate_limits: RateLimits, effort_level: str = '', fast_mode: bool = False) -> tuple[str, str, str, int]:
        model_clr  = self.model_colour(model_name)
        pct        = self._model_bg_pct(effort_level)
        lead_glyph = GLYPH_BURN_FAST if fast_mode else GLYPH_MODEL_LIGHT

        if pct:
            anchor, shift = self._model_anchor_pair(model_name)
            cells: list[tuple[str, tuple[int, int, int] | None, bool, bool]] = []
            cells.append((' ',          anchor, False, False))   # extra left padding
            cells.append((lead_glyph,  anchor, False, False))
            cells.append((' ',         anchor, False, False))
            cells.append((' ',         anchor, False, False))
            for ch in model_name:
                cells.append((ch, anchor, False, False))
            if model_thinking:
                cells.append((' ', anchor, False, False))
                cells.append(('(', anchor, False, False))
                for ch in model_thinking:
                    cells.append((ch, anchor, False, True))
                cells.append((')', anchor, False, False))
            cells.append((' ', anchor, False, False))
            pill_l    = pill_gradient_fg(0, 0, len(cells), anchor, shift, pct) + PILL_LEFT
            pill_r    = pill_gradient_fg(len(cells), 0, len(cells), anchor, shift, pct) + PILL_RIGHT
            right_text = pill_l + paint_bg_span(cells, anchor, shift, pct, self.pill_fg_dark, self.pill_fg_light) + pill_r + RESET
        elif model_thinking:
            right_text = f'{model_clr} {lead_glyph}  {model_name}{self.R} {model_clr}({model_thinking}){RESET}'
        else:
            right_text = f'{model_clr} {lead_glyph}  {model_name}{self.R}'

        right_w = _visible_width(right_text)

        helper_5h, helper_7d = self._rate_helpers(rate_limits)

        return helper_5h, helper_7d, right_text, right_w

    def model_right_section_compact(self, model_name: str, rate_limits: RateLimits, max_right_width: int, effort_level: str = '') -> tuple[str, str, int]:
        model_clr = self.model_colour(model_name)
        pct_bg    = self._model_bg_pct(effort_level)
        anchor, shift = self._model_anchor_pair(model_name) if pct_bg else ((0, 0, 0), (0, 0, 0))
        pct       = rate_limits.five_hour.used_percentage or 0
        pct_clr   = self.fill_colour(float(pct))
        rate_text = f'{pct_clr}{float(pct):.1f}%{self.R}'
        try:
            if rate_limits.five_hour.resets_at:
                resets_at = datetime.fromtimestamp(rate_limits.five_hour.resets_at).astimezone()
                delta = resets_at - datetime.now().astimezone().replace(microsecond=0)
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
                cells.append((GLYPH_MODEL_LIGHT, anchor, False, False))
                cells.append((' ', anchor, False, False))
                cells.append((' ', anchor, False, False))
                for ch in name:
                    cells.append((ch, anchor, False, False))
                cells.append((' ', anchor, False, False))
                pill_l  = pill_gradient_fg(0, 0, len(cells), anchor, shift, pct_bg) + PILL_LEFT
                pill_r  = pill_gradient_fg(len(cells), 0, len(cells), anchor, shift, pct_bg) + PILL_RIGHT
                painted = pill_l + paint_bg_span(cells, anchor, shift, pct_bg, self.pill_fg_dark, self.pill_fg_light) + pill_r + RESET
                return painted, _visible_width(painted)
            text = f'{model_clr}{GLYPH_MODEL_LIGHT}  {name}{self.R}'
            return text, _visible_width(text)

        right_text, right_w = _make_right(model_name)
        if right_w > max_right_width and max_right_width > 0:
            _, base_w = _make_right('')
            budget    = max(3, max_right_width - base_w - 1)
            right_text, right_w = _make_right(model_name[:budget] + '…')
        return rate_text, right_text, right_w

    def plugins_skills(self, skills_count: int, skills_names: str, plugin_names: str) -> str:
        step = rainbow_step()
        c_skills = rainbow_at(step, 3)
        c_plugins = rainbow_at(step, 6)
        extras = []
        if skills_count > 0:
            extras.append(f'{c_skills}{BOLD}{GLYPH_SKILLS}  {self.R}{self.SKILLS}{skills_names}{self.R}')
        if plugin_names:
            extras.append(f'{c_plugins}{BOLD}{GLYPH_PLUGINS}  {self.R}{self.SKILLS}{plugin_names}{self.R}')
        return f' {self.LABEL}|{self.R} '.join(extras)

    SUBAGENT_TOK_W = 6  # fmt_tok('999.9K') is 6 chars; reserve to avoid jitter

    def subagent_activity(
        self,
        last_activity: tuple[str, str, dict[str, object]],
        *,
        cap: int = 36,
    ) -> str:
        kind, name, inp = last_activity
        if kind == 'tool_use':
            key = TOOL_ARG_KEY.get(name)
            if key and key in inp:
                raw = str(inp[key])
                raw = raw.split('\n')[0]
                if key == 'file_path':
                    raw = Path(raw).name
            elif inp:
                raw = str(next(iter(inp.values())))
                raw = raw.split('\n')[0]
            else:
                raw = ''
            if _visible_width(raw) > cap:
                raw = raw[:cap] + '…'  # U+2026 HORIZONTAL ELLIPSIS
            return f'{GLYPH_TASKS} {name}[{raw}]'
        if kind == 'thinking':
            return f'{GLYPH_THINKING} (thinking)'
        if kind == 'text':
            raw = name
            if not raw:
                return f'{GLYPH_REPLYING} (replying)'
            if _visible_width(raw) > cap:
                raw = raw[:cap] + '…'  # U+2026 HORIZONTAL ELLIPSIS
            return f'{GLYPH_REPLYING} {raw}'
        return ''

    def subagent_row(
        self,
        sub: RunningSubagent,
        content_width: int,
        *,
        twoline: bool = False,
        session_inout: int = 0,
        stats_col: int | None = None,
    ) -> str:
        now     = time.time()
        is_done = sub.end_ts > 0
        if is_done:
            dur = max(0.0, sub.end_ts - sub.first_timestamp)
        else:
            dur = max(0.0, now - sub.first_timestamp) if sub.first_timestamp > 0 else 0.0
        dur_s   = fmt_dur(dur).rjust(5)

        short_model = model_key(sub.model)  # 'opus'/'sonnet'/'haiku'/'other'
        model_clr   = self.model_colour(sub.model)
        ctx_clr     = self.risk_zone_color(sub.total_input)

        step      = rainbow_step()
        c_marker  = rainbow_at(step, 12)
        type_text = sub.agent_type or '?'

        target_w = content_width  # explicit content width supplied by the builder

        if twoline:
            # --- line 1: duration-first identity + right-aligned cluster (D6) ---
            # No run-state marker: a Done agent dims every field and freezes its
            # duration; a running one keeps live colours and a ticking duration.
            # The right cluster is `· {share%}  {tok} · {model}`; under width
            # pressure the description truncates first, then the cluster sheds
            # share% and then tok. The model and the front duration always stay.
            front_w = 5 + 1 + _visible_width(type_text)  # dur(5) + ' ' + type

            share     = subagent_share(sub.total_input + sub.output, session_inout)
            share_str = f'{share * 100:.1f}%' if share is not None else ''
            tok_field = fmt_tok(sub.total_input).rjust(5)
            model_str = short_model.rjust(6)

            if is_done:
                front_c = f'{self.CTX_DIM}{dur_s}{self.R} {self.CTX_DIM}{type_text}{self.R}'
            else:
                front_c = f'{self.CTX}{dur_s}{self.R} {self.SKILLS}{type_text}{self.R}'

            def build_cluster(show_share: bool, show_tok: bool) -> str:
                if is_done:
                    d   = self.CTX_DIM
                    seg = f'{d}·{self.R} '
                    if show_share and share is not None:
                        seg += f'{d}{share_str}{self.R}  '
                    if show_tok:
                        seg += f'{d}{tok_field}{self.R} {d}·{self.R} '
                    return seg + f'{d}{model_str}{self.R}'
                share_clr = self.gradient.gradient_color(share) if share is not None else ''
                seg = f'{self.LABEL}·{self.R} '
                if show_share and share is not None:
                    seg += f'{share_clr}{share_str}{self.R}  '
                if show_tok:
                    seg += f'{ctx_clr}{tok_field}{self.R} {self.LABEL}·{self.R} '
                return seg + f'{model_clr}{model_str}{self.R}'

            # Decide whether the stats cluster anchors at a fixed content
            # column (wide layouts) or right-aligns to the content edge. The
            # anchor only applies when even the model-only fallback fits within
            # the slack to the right of `stats_col`; otherwise we fall through
            # to the right-aligned path so very narrow widths stay sane.
            model_only_w = _visible_width(build_cluster(False, False))
            anchored     = stats_col is not None and (target_w - stats_col) >= model_only_w

            if anchored:
                assert stats_col is not None  # narrowed by `anchored`
                avail = target_w - stats_col  # slack to the right of the anchor
                # Pick the richest cluster that fits within the anchored slack.
                cluster = build_cluster(False, False)  # model-only fallback
                for show_share, show_tok in ((True, True), (False, True)):
                    cand = build_cluster(show_share, show_tok)
                    if _visible_width(cand) <= avail:
                        cluster = cand
                        break
                cluster_w = _visible_width(cluster)

                # Truncate the description so it stops before the stats column
                # with at least a 1-col gap. ' · ' separator is 3 cols wide.
                desc_text  = sub.description or ''
                desc_max   = stats_col - front_w - 3 - 1
                sep_desc   = ''
                sep_desc_w = 0
                if desc_text and desc_max > 0:
                    if _visible_width(desc_text) > desc_max:
                        desc_text = desc_text[:desc_max - 1] + '…'  # U+2026 HORIZONTAL ELLIPSIS
                    desc_w = _visible_width(desc_text)
                    if is_done:
                        sep_desc = f' {self.CTX_DIM}·{self.R} {self.CTX_DIM}{desc_text}{self.R}'
                    else:
                        sep_desc = f' {self.LABEL}·{self.R} {self.CTX}{desc_text}{self.R}'
                    sep_desc_w = 3 + desc_w

                # Anchor the cluster's first `·` at content-offset stats_col.
                pad1  = max(1, stats_col - front_w - sep_desc_w)
                line1 = f'{front_c}{sep_desc}{" " * pad1}{cluster}'
                line1 += ' ' * max(0, target_w - _visible_width(line1))
            else:
                # Pick the richest cluster that fits alongside the front + a 1-col gap.
                cluster = build_cluster(False, False)  # model-only fallback
                for show_share, show_tok in ((True, True), (False, True)):
                    cand = build_cluster(show_share, show_tok)
                    if front_w + 1 + _visible_width(cand) <= target_w:
                        cluster = cand
                        break
                cluster_w = _visible_width(cluster)

                # Fill the description into the space left over (truncates first).
                desc_text  = sub.description or ''
                desc_max   = target_w - front_w - cluster_w - 1 - 3  # 1-col gap + ' · '
                sep_desc   = ''
                sep_desc_w = 0
                if desc_text and desc_max > 0:
                    if _visible_width(desc_text) > desc_max:
                        desc_text = desc_text[:desc_max - 1] + '…'  # U+2026 HORIZONTAL ELLIPSIS
                    desc_w = _visible_width(desc_text)
                    if is_done:
                        sep_desc = f' {self.CTX_DIM}·{self.R} {self.CTX_DIM}{desc_text}{self.R}'
                    else:
                        sep_desc = f' {self.LABEL}·{self.R} {self.CTX}{desc_text}{self.R}'
                    sep_desc_w = 3 + desc_w

                pad1  = max(1, target_w - front_w - sep_desc_w - cluster_w)
                line1 = f'{front_c}{sep_desc}{" " * pad1}{cluster}'

            # --- line 2: activity-only continuation, no right metrics (D6) ---
            # The snippet grows with the spare width line 2 has (no right
            # cluster lives here), but never past 100 cols before truncating.
            avail2       = max(0, target_w - 6)  # '   '(3) + └ + '  '(2)
            activity_cap = min(100, avail2)
            activity     = self.subagent_activity(sub.last_activity, cap=activity_cap)
            if _visible_width(activity) > avail2:
                activity = activity[:max(0, avail2 - 1)] + '…'
            left2   = (
                f'   {self.CTX_DIM}{GLYPH_CONTINUATION}{self.R}  '
                f'{self.CTX_DIM}{activity}{self.R}'
            )
            left2_w = 6 + _visible_width(activity)
            pad2    = max(0, target_w - left2_w)
            line2   = f'{left2}{" " * pad2}'

            return f'{line1}\n{line2}'

        # --- one-line collapse (D6): drops ↑output; marker/type/verb on the
        # left, model right-anchored into the metric column ---
        # Only show activity status for running agents; done agents freeze state.
        if is_done:
            tool_verb = ''
        else:
            kind = sub.last_activity[0]
            tool_verb = sub.last_activity[1] if kind == 'tool_use' else (
                '(thinking)' if kind == 'thinking' else
                '(replying)' if kind == 'text' else ''
            )

        # The model is a fixed-width, right-justified field at the head of the
        # right cluster so it forms a vertical column with the tokens and
        # duration (also right-justified) down stacked rows. Reading order:
        # `{model:>6}  {hourglass} {tok:>5}  {dur:>5}`. Model dims when Done.
        model_field = short_model.rjust(6)
        model_n_clr = self.CTX_DIM if is_done else model_clr
        tok_n       = fmt_tok(sub.total_input).rjust(6)
        right_n = (
            f'{model_n_clr}{model_field}{self.R}'
            f'  {ctx_clr}{GLYPH_HOURGLASS} {tok_n}{self.R}'
            f'  {self.CTX}{dur_s}{self.R}'
        )
        right_n_w = _visible_width(right_n)

        if is_done:
            left_n = (
                f'{self.CTX_DIM}{GLYPH_SUBAGENT_DONE}{self.R}  '
                f'{self.CTX_DIM}{type_text}{self.R}'
            )
        else:
            left_n = (
                f'{c_marker}{BOLD}{GLYPH_SUBAGENT_ROW}{self.R}  '
                f'{self.SKILLS}{type_text}{self.R}'
                f'  {self.CTX}{tool_verb}{self.R}'
            )
        left_n_w = _visible_width(left_n)
        # Budget the left segment so the row never overflows the right border:
        # the bounded right cluster (model + hourglass + tok + dur) stays
        # intact, and the marker/type/verb run truncates with a middle ellipsis
        # when it would otherwise push past target_w (reserving a 1-col gap).
        left_budget = target_w - right_n_w - 1
        if left_n_w > left_budget:
            left_n   = _middle_ellipsis(left_n, max(1, left_budget))
            left_n_w = _visible_width(left_n)
        # Right-anchor the metric cluster (model + hourglass + tok + dur) flush
        # to the closing border so the model, tokens and elapsed columns line
        # up down stacked rows; the slack between the left run and the cluster
        # is the gap.
        pad_n = max(1, target_w - left_n_w - right_n_w)
        return f'{left_n}{" " * pad_n}{right_n}'

    def workflow_header(self, run: RunningWorkflow, content_width: int) -> str:
        """Group header for a workflow run.

        With a known phase list the header renders the phases inline as a
        dot-separated trail — ``▸  <name>  P1 · ❯P2 · P3`` — where the phase
        matching ``run.phase`` is highlighted (SKILLS colour, ``❯`` prefix) and
        the rest dimmed; an empty ``run.phase`` (live run) dims all of them with
        no marker. Without a phase list it falls back to the ``[<phase>]``
        bracket form (omitted when no phase is known).

        The name keeps a minimum width: when the phase trail is wide the trail
        itself is truncated with ``…`` before the name shrinks below that floor.
        The whole line is clamped to ``content_width`` as a final safety net.
        """
        step  = rainbow_step()
        c_hdr = rainbow_at(step, 4)
        glyph_w = 3  # ▸ + two spaces

        if run.phases:
            phase_seg = self._workflow_phase_list(run)
            # Reserve a name floor so a long phase trail truncates first.
            name_floor = min(_visible_width(run.name), WF_NAME_MIN)
            trail_max  = content_width - glyph_w - name_floor - WF_PHASE_GAP
            if _visible_width(phase_seg) > max(0, trail_max):
                phase_seg = _middle_ellipsis(phase_seg, max(1, trail_max))
            phase_seg = f'  {phase_seg}'
        elif run.phase:
            phase_seg = f'  {self.LABEL}[{self.R}{self.CTX}{run.phase}{self.R}{self.LABEL}]{self.R}'
        else:
            phase_seg = ''

        name_max = max(1, content_width - glyph_w - _visible_width(phase_seg))
        name     = _middle_ellipsis(run.name, name_max)
        line     = f'{c_hdr}{BOLD}{GLYPH_WF_HEADER}{self.R}  {self.SKILLS}{name}{self.R}{phase_seg}'
        if _visible_width(line) > content_width:
            line = _middle_ellipsis(line, content_width)
        return line

    def _workflow_phase_list(self, run: RunningWorkflow) -> str:
        """Dot-separated phase trail: current phase highlighted, rest dimmed.

        The current phase (``run.phase``) gets the SKILLS colour and a ``❯``
        marker; every other phase — and all phases when ``run.phase`` is empty —
        renders in ``CTX_DIM``. Separator dots are dim throughout.
        """
        sep   = f' {self.CTX_DIM}{WF_PHASE_DOT}{self.R} '
        parts = []
        for title in run.phases:
            if run.phase and title == run.phase:
                parts.append(f'{self.SKILLS}{GLYPH_WF_CURRENT}{title}{self.R}')
            else:
                parts.append(f'{self.CTX_DIM}{title}{self.R}')
        return sep.join(parts)

    def workflow_summary(self, run: RunningWorkflow, content_width: int, *, hidden_agents: int = 0) -> str:
        """Summary footer for a workflow run: ``└  N agents · M done · <tok>``.

        ``hidden_agents`` (agents beyond the per-run cap) appends ``+K hidden``.
        Token total is the run's aggregate from the per-agent transcript parse.
        """
        step  = rainbow_step()
        c_sum = rainbow_at(step, 7)
        sep   = f' {self.LABEL}·{self.R} '
        parts = [
            f'{self.CTX}{run.agent_count}{self.R} {self.LABEL}agents{self.R}',
            f'{self.CTX}{run.done_count}{self.R} {self.LABEL}done{self.R}',
            f'{self.CTX}{fmt_tok(run.total_tokens)}{self.R}',
        ]
        if hidden_agents > 0:
            parts.append(f'{self.LABEL}+{hidden_agents} hidden{self.R}')
        line = f'{c_sum}{GLYPH_WF_SUMMARY}{self.R}  {sep.join(parts)}'
        if _visible_width(line) > content_width:
            line = _middle_ellipsis(line, content_width)
        return line

    def task_row(self, tasks: TaskList, content_width: int, *, compact: bool = False) -> list[str]:
        step    = rainbow_step()
        c_glyph = rainbow_at(step, 9)
        done    = tasks.completed
        total   = tasks.total
        count_s = f'{done}/{total}'
        now     = time.time()

        DIM = self.TOK_DIM  # dim grey for frozen timers + collapse lines
        BRT = self.CTX      # accent for the active task (stays lighter than white_brt on light themes)

        glyph_s = f'{c_glyph}{BOLD}{GLYPH_TASKS}{self.R}'
        count_p = f'{self.SKILLS}{count_s}{self.R}'

        # --- compact branch (narrow): glyph + done/total on the left, the active
        # task's live timer right-anchored to the content edge. The header is a
        # lone row (no per-task checklist below it to column-align against), so
        # the timer fills the otherwise-dead trailing space as a second anchor,
        # reading like the subagent rows. Falls back to the bare left cluster
        # when no task is actively timing.
        if compact:
            head   = f'{glyph_s}  {count_p}'
            active = tasks.active
            if active is None or active.started_at is None:
                return [head]
            live    = fmt_duration(now - active.started_at)
            right   = f'{BRT}{BOLD}{live}{self.R}'
            right_w = _visible_width(right)
            head_w  = _visible_width(head)
            # Reserve the floor gap; if left + gap + timer would overflow the
            # content width, truncate the left cluster with a middle ellipsis so
            # the timer stays flush right and the row never overruns the border.
            if head_w + TASK_HEADER_RIGHT_GAP_MIN + right_w > content_width:
                head   = _middle_ellipsis(head, max(1, content_width - TASK_HEADER_RIGHT_GAP_MIN - right_w))
                head_w = _visible_width(head)
            mid = max(TASK_HEADER_RIGHT_GAP_MIN, content_width - head_w - right_w)
            return [f'{head}{" " * mid}{right}']

        # --- full-list branch (wide/medium): header + windowed items ---
        elapsed   = total_elapsed(tasks, now)
        elapsed_s = fmt_duration(elapsed) if elapsed is not None else ''

        win = select_window(tasks)

        # Per-item timer strings (plain, for column-width maths), glyphs and
        # the 1-indexed task-number prefix. The number is kept separate from the
        # subject so it can be tinted like the glyph/timer (not the subject), and
        # it lets the window stay legible without `+N done` / `+N more` lines.
        rows: list[tuple[str, str, str, str]] = []  # (glyph, num, subject, timer_plain)
        for t in win.items:
            if t.status == 'completed':
                glyph = GLYPH_TASK_DONE
                subj  = t.subject
                timer = ''
                if t.started_at is not None and t.completed_at is not None:
                    timer = fmt_duration(t.completed_at - t.started_at)
            elif t.status == 'in_progress':
                glyph = GLYPH_TASK_ACTIVE
                subj  = t.active_form or t.subject
                timer = fmt_duration(now - t.started_at) if t.started_at is not None else ''
            else:
                glyph = GLYPH_TASK_PENDING
                subj  = t.subject
                timer = ''
            rows.append((glyph, f'{t.id}. ', subj, timer))

        # Fixed leading timer column = widest shown timer string, also covering
        # the header's Total Elapsed so the per-task timers right-align under it.
        timer_w = max(
            (_visible_width(tm) for *_, tm in rows if tm),
            default=0,
        )
        timer_w = max(timer_w, _visible_width(elapsed_s))

        # Header order: Total Elapsed first (right-aligned in the timer column so
        # it lines up with the per-task timers below), then glyph + done/total
        # count. The leading elapsed is omitted when never started.
        if elapsed_s:
            head_pad = ' ' * max(0, timer_w - _visible_width(elapsed_s))
            head     = f'{head_pad}{DIM}{elapsed_s}{self.R} {glyph_s}  {count_p}'
        else:
            head = f'{glyph_s}  {count_p}'

        # Inner content width supplied by the builder (the box's content area
        # at full width, or a narrower side-by-side left-column width). Item
        # rows are laid out to exactly this width so subjects truncate to fit.
        inner_w = content_width

        out: list[str] = [head]

        # Layout per item: [timer column] + gap + glyph(1) + '  ' + number + subject.
        # The timer column is a fixed leading width (`timer_w`), right-aligned
        # within itself so digits line up; a `gap` separates it from the glyph,
        # and two spaces separate the glyph from the task number. Pending/untimed
        # rows leave the timer column blank. The number+subject share a fixed
        # field width (the number always shown, the subject padded/truncated) so
        # all item rows share one total visible width.
        gap         = 1 if timer_w else 0
        field_w     = max(1, inner_w - 3 - gap - timer_w)  # col + gap + glyph + '  '

        for (glyph, num, subj, timer), t in zip(rows, win.items):
            if t.status == 'completed':
                g_clr  = DIM
                tm_clr = DIM
            elif t.status == 'in_progress':
                g_clr  = BRT + BOLD
                tm_clr = BRT + BOLD
            else:
                g_clr  = DIM
                tm_clr = ''

            avail = max(1, field_w - _visible_width(num))
            sw    = _visible_width(subj)
            if sw > avail:
                # Single-side ellipsis truncation by visible width.
                acc = ''
                for ch in subj:
                    if _visible_width(acc + ch) > avail - 1:
                        break
                    acc += ch
                subj = acc + '…'
                subj_pad = max(0, avail - _visible_width(subj))
            else:
                subj_pad = avail - sw

            line = ''
            if timer_w:
                tm_pad = max(0, timer_w - _visible_width(timer))
                line += ' ' * tm_pad
                line += f'{tm_clr}{timer}{self.R}' if timer else ' ' * _visible_width(timer)
                line += ' ' * gap
            # Glyph, two spaces, then the number tinted like the glyph/timer and
            # the subject in the standard content colour.
            line += f'{g_clr}{glyph}{self.R}  {g_clr}{num}{self.R}{self.CTX}{subj}{self.R}{" " * subj_pad}'
            out.append(line)

        return out

    RATE_W  = 6
    IN_W    = 6
    CACHE_W = 6
    OUT_W   = 6

    # Per-slot caps (in spaces) for the justify breathing room. Each slot fills
    # from its 1-space minimum toward the cap as slack allows; leftover slack
    # after every cap is met still feeds the rate/sparkline leader (as before).
    JUSTIFY_PAD_CAP = 4

    def tokens_cost(self, sess_in: int, sess_cache: int, sess_out: int, day_in: int, day_cache: int, day_out: int, sess_cost: float, day_cost: float, tok_rate: int, session_id: str = '', box_width: int = 80, fill: float = 1.0, show_day_stats: bool = True, justify: bool = False) -> tuple[list[str], tuple[int, int], int, int]:
        """One content line: tokens │ cost │ rate-and-sparkline.

        With ``show_day_stats`` (default), session and day figures merge per
        field as ``session/day`` with a paired cache parenthetical. When off,
        the row is session-only and keeps the original per-field justification.

        When ``justify`` is on (and day stats are shown), horizontal slack that
        would otherwise all flow to the sparkline leader is first spent as
        breathing room *inside* the sections — widening the two inter-group gaps
        in the tokens column and padding the cost/leader edges, each capped at
        ``JUSTIFY_PAD_CAP`` spaces. ``min_width`` is unchanged: the optional
        padding only consumes genuine slack, so at the tight floor the gaps
        collapse to 1 and the row fits exactly as with ``justify`` off.
        The tokens and cost columns are sized to the *measured* content (floored
        at a realistic-widest budget), so the two ``│`` dividers always land on
        the rendered content's divider column — they never detach from the
        ┬/┴ elbows above/below. Returns ``([line], (col1, col2), 0, min_width)``:
        the divider columns for the builder's elbow threading, the dead mark_col
        (the old 60s tick marker is gone, =0), and ``min_width`` — the smallest
        box width at which this row fits without overflow, so the builder can
        fall back to a compact form below it.
        """
        day_clr = self.day_cost_colour(day_cost)
        in_active, out_active = TokenRate.recently_active(session_id)
        in_icon  = '\U0001f847 ' if in_active  else '↓ '  # 🡇+space or ↓+space (both 2 cols)
        out_icon = '\U0001f845 ' if out_active else '↑ '  # 🡅+space or ↑+space (both 2 cols)

        # Inter-group gaps in the tokens column and the cost/leader edge pads.
        # They start at their minimums (gaps 1 space, edge pads 0) so the
        # measured widths and ``min_width`` below are the tight floor; ``justify``
        # widens them from genuine slack only (see the pad block after min_width).
        gap1 = gap2 = ' '   # ↓in/day | (cache) | ↑out/day inter-group gaps
        cost_lpad = cost_rpad = ''
        leader_lpad = ''

        if show_day_stats:
            # Merged session/day per field; variable width, no fixed rjust (D2).
            cache = (f'{self.TOK_DIM}({fmt_tok(sess_cache)}{self.R}'
                     f'{self.TOK_DAY_DIM}/{fmt_tok(day_cache)}{self.R}'
                     f'{self.TOK_DIM}){self.R}')

            def build_tokens() -> str:
                return (
                    f'{self.LABEL}{self.BOLDY}{in_icon}{self.R}'
                    f'{self.TOK}{fmt_tok(sess_in)}{self.R}{self.TOK_DAY_DIM}/{fmt_tok(day_in)}{self.R}{gap1}'
                    f'{cache}'
                    f'{self.LABEL}{gap2}{self.BOLDY}{out_icon}{self.R}'
                    f'{self.TOK}{fmt_tok(sess_out)}{self.R}{self.TOK_DAY_DIM}/{fmt_tok(day_out)}{self.R}'
                )

            def build_cost() -> str:
                return (f'{cost_lpad}{self.safe}{ICON_COST}{self.R}  {self.COST}${sess_cost:,.2f}{self.R}'
                        f'{self.LABEL} / {self.R}{day_clr}${day_cost:,.2f}{self.R}{cost_rpad}')

            tokens_col = build_tokens()
            cost_col   = build_cost()
        else:
            # Session-only: original per-field justification (D2).
            sess_in_s    = fmt_tok(sess_in).rjust(self.IN_W)
            sess_cache_s = fmt_tok(sess_cache).rjust(self.CACHE_W)
            sess_out_s   = fmt_tok(sess_out).rjust(self.OUT_W)
            tokens_col = (f'{self.LABEL}{self.BOLDY}{in_icon}{self.R}{self.TOK}{sess_in_s}{self.R} '
                          f'{self.TOK_DIM}({sess_cache_s}){self.R}{self.LABEL} '
                          f'{self.BOLDY}{out_icon}{self.R}{self.TOK}{sess_out_s}{self.R}')
            cost_col = f'{self.safe}{ICON_COST}{self.R}  {self.COST}${sess_cost:,.2f}{self.R}'

        vsep_w        = 4
        vsep_leader_w = 4
        label_w       = 15

        content_w = box_width - 3
        inner     = content_w - vsep_w - vsep_leader_w  # tokens + cost + leader budget

        # Section widths track the *measured* content so each column hugs its
        # content and the two │ dividers sit directly after it (only the vsep's
        # built-in 2-space lead remains as the gap). There is no inflated floor:
        # the budget IS the measured width. Measure with _visible_width (the
        # strings carry ANSI; never len()). The honest floor further down
        # (``w_middle = max(w_middle, tokens_w)`` etc.) still guarantees pad>=0,
        # so col1/col2 always land on the rendered │ and never detach from their
        # ┬/┴ elbows above/below. The intrinsic minimum box width this needs is
        # returned to the caller (see ``min_width`` below) so the builder can fall
        # back to a compact form rather than overflow the box.
        tokens_w = _visible_width(tokens_col)
        cost_w   = _visible_width(cost_col)
        # The rate/spark leader can never compress below its bare ``<rate> t/m``
        # label; measure it here so the budget split and min_width are exact (when
        # bar_w<=0 below, the leader is the bare label, which may exceed label_w+1).
        rate_label   = f'{self.TOK_ICON}{ICON_TOK_RATE}  {self.TOK}{fmt_tok(tok_rate)}{self.R}{self.LABEL} t/m{self.R}'
        rate_label_w = _visible_width(rate_label)
        leader_min   = max(label_w + 1, rate_label_w)

        # The smallest box that holds both columns at their measured size plus the
        # two vseps and the leader. Derived from the measured content, so it tracks
        # token/cost/rate magnitude rather than being hardcoded. The leader floor
        # here is the bare ``rate_label_w``, not ``leader_min``: at the tightest
        # box the sparkline is omitted (bar_w<10) and the leader collapses to the
        # bare ``<rate> t/m`` label, so the row genuinely fits at that narrower
        # width. The builder only emits this row when ``box_width >= min_width``.
        min_width = tokens_w + cost_w + vsep_w + vsep_leader_w + rate_label_w + 3

        # Justify breathing room: spend genuine slack as padding *inside* the
        # sections before it flows to the sparkline. ``free`` is the room beyond
        # the tight minimum (min-gap content + min leader); it is exactly the
        # slack that today all lands in the leader. We never touch ``min_width``,
        # so at the floor ``free`` is 0, the gaps stay at 1, and the row is
        # byte-for-byte the justify-off layout. Slots fill toward their caps via
        # an even round-robin; whatever is consumed shrinks the leader by the
        # same amount, and the remainder still feeds the sparkline.
        cap = self.JUSTIFY_PAD_CAP
        if justify and show_day_stats:
            free = max(0, inner - tokens_w - cost_w - leader_min)
            # (slot extra above its 1-space/0-space minimum, per-slot cap).
            #  gap1, gap2 sit at 1 already → extra cap is cap-1; the edge pads
            #  sit at 0 → extra cap is the full cap.
            slots = [cap - 1, cap - 1, cap, cap, cap]  # gap1, gap2, cost_l, cost_r, leader_l
            give  = [0, 0, 0, 0, 0]
            budget = min(free, sum(slots))
            while budget > 0 and any(give[i] < slots[i] for i in range(len(slots))):
                for i in range(len(slots)):
                    if budget <= 0:
                        break
                    if give[i] < slots[i]:
                        give[i] += 1
                        budget  -= 1
            gap1 = ' ' * (1 + give[0])
            gap2 = ' ' * (1 + give[1])
            cost_lpad = ' ' * give[2]
            cost_rpad = ' ' * give[3]
            leader_lpad = ' ' * give[4]
            # Rebuild the padded strings and grow the measured widths by the
            # injected pad so the budget split and col1/col2 follow the new
            # divider positions exactly (the leader pad is accounted separately
            # below). min_width above stays on the unpadded floor.
            tokens_col = build_tokens()
            cost_col   = build_cost()
            tokens_w  += give[0] + give[1]
            cost_w    += give[2] + give[3]

        # Budgets track the (possibly padded) measured widths, so the column
        # sizing and col1/col2 always land on the rendered │.
        TOKENS_BUDGET = tokens_w
        COST_BUDGET   = cost_w
        leader_lpad_w = len(leader_lpad)

        avail = inner - leader_min                 # room left after the leader minimum
        if TOKENS_BUDGET + COST_BUDGET <= avail:
            w_middle, w_end = TOKENS_BUDGET, COST_BUDGET
        else:
            # Over budget: give each column at least its measured content, then
            # share any slack proportionally. Clamping at content (not the inflated
            # proportional share) keeps the cell sum from spilling past col1/col2.
            w_middle = max(tokens_w, avail * TOKENS_BUDGET // (TOKENS_BUDGET + COST_BUDGET))
            w_end    = max(cost_w, avail - w_middle)

        # Honest floor: never allocate a cell narrower than its own content. This
        # keeps the trailing pad >= 0 so the │ lands exactly at col1/col2.
        w_middle = max(w_middle, tokens_w)
        w_end    = max(w_end, cost_w)

        # Left-justify each column to its (content-floored) width. The trailing pad
        # lands the │ at the divider column col1/col2 regardless of content.
        tokens_col += ' ' * max(0, w_middle - tokens_w)
        cost_col   += ' ' * max(0, w_end   - cost_w)

        leader_w = max(label_w + 1, inner - w_middle - w_end)

        col1 = w_middle + 5                   # 1-indexed position of vsep │
        col2 = w_middle + vsep_w + w_end + 5  # 1-indexed position of vsep_leader │
        vsep        = self.vsep_block(col1, box_width, fill=fill, leader=True)
        vsep_leader = self.vsep_block(col2, box_width, fill=fill, leader=True)

        # The justify leader pad sits between the vsep_leader │ and the rate
        # label; it eats from the leader budget so the sparkline shrinks by the
        # same amount it grew the breathing room.
        bar_w = leader_w - rate_label_w - leader_lpad_w

        if bar_w < 10:
            leader = f'{leader_lpad}{rate_label}'
        else:
            if session_id:
                # 1 second per char (D4): span the most recent bar_w seconds, one
                # char each (window == bar_w → 1s buckets). History is
                # oldest→newest, so reverse it to put the newest (live) bucket on
                # the LEFT, next to the t/m label — sparkline_1row dims that
                # now-leftmost cell.
                spark_history = TokenRate.history(session_id, bar_w, float(bar_w))[::-1]
                spark = self.sparkline_1row(spark_history, live=True)
            else:
                spark = ' ' * bar_w
            leader = f'{leader_lpad}{rate_label}{spark}'

        return [f'{tokens_col}{vsep}{cost_col}{vsep_leader}{leader}'], (col1, col2), 0, min_width

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

    def context_line(
        self,
        ctx: ContextWindow,
        available: int = 76,
        soft_limit: int = DEFAULT_SOFT_LIMIT,
        exceeds_200k: bool = False,
    ) -> str:
        fill_ratio, pct_soft = _ctx_fill_ratio(ctx, soft_limit)
        total_tokens         = _ctx_used_tokens(ctx)

        badge   = f'{CLR_WARN}!200K{self.R} ' if exceeds_200k else ''
        badge_w = 6 if exceeds_200k else 0

        if fill_ratio >= 1.0:
            a = BOLD + self.risk_zone_color(total_tokens)
            # Right-justify the visible text into fixed-width fields (applied to
            # the plain string before ANSI wrapping, since a colour-coded string
            # cannot be rjust-ed) so the token/window/soft columns hold a stable
            # right edge regardless of magnitude — `194.0K (97%) 100%` lines up
            # under `30.0K (3%) 20%` from the normal branch below.
            secondary = ''
            if ctx.context_window_size > 0:
                pct_model = total_tokens / ctx.context_window_size * 100
                secondary = f' {a}{f"({pct_model:.0f}%)":>5}{self.R}'
            prefix = f'{a}{fmt_tok(total_tokens):>6}{self.R}{secondary} {a}{BOLD}{f"{pct_soft:.0f}%":>4}{self.R} '
            bar_w  = max(0, max(4, available - _visible_width(prefix) - 3) - badge_w)
            filled = int(min(fill_ratio, 1.0) * bar_w)
            empty  = max(0, bar_w - filled - (1 if filled < bar_w else 0))
            bar    = f'{self.gradient_bar(filled, bar_w)}{self.R}{a}{BarChars.EMPTY * empty}{self.R}'
            return f'{badge}{a}{GLYPH_HOURGLASS}{self.R} {prefix}{bar}'

        bar_clr = self.risk_zone_color(total_tokens)
        # Fixed-width right-justified fields (rjust applied to the plain text
        # before ANSI wrapping) keep the token/window/soft columns aligned with
        # the over-limit branch above, so short and long magnitudes share a
        # stable right edge under the `context`/`fill`/`dumb` labels.
        secondary = ''
        if ctx.context_window_size > 0:
            pct_model = total_tokens / ctx.context_window_size * 100
            secondary = f' {self.DIM_GREEN}{f"({pct_model:.0f}%)":>5}{self.R}'
        prefix = f'{bar_clr}{self.R}{self.DIM_GREEN}{fmt_tok(total_tokens):>6}{self.R}{secondary} {bar_clr}{BOLD}{f"{pct_soft:.0f}%":>4}{self.R} '
        bar_w  = max(0, max(4, available - _visible_width(prefix) - 3) - badge_w)
        filled = int(fill_ratio * bar_w)
        empty  = max(0, bar_w - filled - (1 if filled < bar_w else 0))
        bar    = f'{self.gradient_bar(filled, bar_w)}{self.R}{self._empty_section(empty, blend=filled > 0)}{self.R}'
        return f'{badge}{bar_clr}{GLYPH_HOURGLASS}{self.R} {prefix}{bar}'

    def context_line_compact(
        self,
        ctx: ContextWindow,
        available: int,
        soft_limit: int = DEFAULT_SOFT_LIMIT,
        exceeds_200k: bool = False,
    ) -> str:
        fill_ratio, pct_soft = _ctx_fill_ratio(ctx, soft_limit)
        total_tokens         = _ctx_used_tokens(ctx)

        badge   = f'{CLR_WARN}!200K{self.R} ' if exceeds_200k else ''
        badge_w = 6 if exceeds_200k else 0

        if fill_ratio >= 1.0:
            a      = BOLD + self.risk_zone_color(total_tokens)
            prefix = f'{a}{pct_soft:.0f}%{self.R} '
            bar_w  = max(0, max(4, available - _visible_width(prefix) - 3) - badge_w)
            filled = int(min(fill_ratio, 1.0) * bar_w)
            empty  = max(0, bar_w - filled - (1 if filled < bar_w else 0))
            bar    = f'{self.gradient_bar(filled, bar_w)}{self.R}{a}{BarChars.EMPTY * empty}{self.R}'
            return f' {badge}{prefix}{bar}'

        bar_clr = self.risk_zone_color(total_tokens)
        prefix  = f'{bar_clr}{BOLD}{pct_soft:.0f}%{self.R} '
        bar_w   = max(0, max(4, available - _visible_width(prefix) - 3) - badge_w)
        filled  = int(fill_ratio * bar_w)
        empty   = max(0, bar_w - filled - (1 if filled < bar_w else 0))
        bar     = f'{self.gradient_bar(filled, bar_w)}{self.R}{self._empty_section(empty, blend=filled > 0)}{self.R}'
        return f' {badge}{prefix}{bar}'

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

    def openspec_bar(self, name: str, done: int, total: int, box_width: int = 80, title_w: int = 25) -> str:
        idx = zlib.crc32(name.encode()) % len(self.SPEC_GRADIENTS)
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
        glyph = GLYPH_BURN_FAST if delta > 0 else GLYPH_BURN_SLOW  # colour modulation carries over/under-burn direction
        sign  = '-' if delta < 0 else '+'
        return f'{colour}{glyph} {sign}{abs_delta:.1f}%{self.R}'

    def helper(self, five_hour: RateBucket, gap: int = 1) -> str:
        # ``gap`` is the inter-stat separator width (countdown↔pct, pct↔trend).
        # It widens to give the justified top row breathing room; the glyph→stat
        # spacing lives in the caller and is unaffected.
        sp      = ' ' * gap
        pct_clr = self.fill_colour(float(five_hour.used_percentage or 0))
        pct_str = f'{float(five_hour.used_percentage or 0):.1f}'
        try:
            if not five_hour.resets_at:
                if not five_hour.used_percentage:
                    return '∞'
                return f'{pct_clr}{pct_str}%{self.R}{sp}{self.COMMIT}∞'
            resets_at = datetime.fromtimestamp(five_hour.resets_at).astimezone()
            delta = resets_at - datetime.now().astimezone().replace(microsecond=0)
            if delta.total_seconds() <= 0:
                if not five_hour.used_percentage:
                    return '∞'
                return f'{pct_clr}{pct_str}%{self.R}{sp}{self.COMMIT}∞'
            total_s   = int(delta.total_seconds())
            h, rem    = divmod(total_s, 3600)
            m         = rem // 60
            countdown = f'(-{h}:{m:02d})'
            trend = self.burndown_trend(
                float(five_hour.used_percentage or 0),
                five_hour.resets_at,
                FIVE_HOUR_MINUTES,
                FIVE_HOUR_WARMUP_MINUTES,
            )
            trend_part = f'{sp}{trend}' if trend else ''
            return f'{self.COMMIT}{countdown}{self.R}{sp}{pct_clr}{pct_str}%{self.R}{trend_part}'
        except Exception as e:
            return f'{e.__class__.__name__}, {str(e)}'
