"""Renderer and all section-helper methods for the statusline."""

from __future__ import annotations

import re
import time
import zlib
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Callable, TYPE_CHECKING

from yas.render.borders import BorderRenderer
from yas.constants import (
    BOLD,
    ITALIC,
    MIDDLE_DOT,
    RESET,
    ARROW_IN_ACTIVE,
    ARROW_IN_IDLE,
    ARROW_OUT_ACTIVE,
    ARROW_OUT_IDLE,
    BarChars,
    BG_LUM_THRESHOLD,
    BOX_V,
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
    CLR_ROSE,
    CLR_SKY_BLUE,
    CLR_TEAL_VIOLET,
    CLR_WARN,
    CLR_WHITE_BRT,
    CLR_YELLOW,
    CLR_YELLOW_BRT,
    DEFAULT_SOFT_LIMIT,
    ELLIPSIS,
    FAINT,
    FIVE_HOUR_MINUTES,
    FIVE_HOUR_WARMUP_MINUTES,
    GLYPH_BURN_FAST,
    GLYPH_BURN_SLOW,
    GLYPH_CONTINUATION,
    GLYPH_FOLDER,
    GLYPH_CACHE,
    GLYPH_CLEAR,
    GLYPH_HOURGLASS,
    GLYPH_IN,
    GLYPH_LINES_READ,
    GLYPH_LINES_CHANGED,
    LINES_SEGMENT_MIN_WIDTH,
    GLYPH_MODEL_LIGHT,
    GLYPH_PLUGINS,
    GLYPH_RENAMED,
    GLYPH_REPLYING,
    GLYPH_SKILLS,
    GLYPH_SUBAGENT_RESUME,
    subagent_is_terminal,
    subagent_marker_glyph,
    subagent_status,
    GLYPH_TASKS,
    GLYPH_TASK_ACTIVE,
    GLYPH_TASK_DONE,
    GLYPH_TASK_PENDING,
    GLYPH_THINKING,
    GLYPH_UNLIMITED,
    GLYPH_UNTRACKED,
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
    STRIKE,
    UNSTRIKE,
    SUBAGENT_NAME_MAX,
    SUBAGENT_STATS_ACTIVITY_GAP,
    TASK_HEADER_RIGHT_GAP_MIN,
    WF_NAME_MIN,
    WF_PHASE_DOT,
    WF_PHASE_GAP,
)
from yas.render.gradient import (
    GradientEngine,
    model_display,
    model_form_short,
    model_key,
    paint_bg_span,
    pill_gradient_fg,
    rainbow_at,
    rainbow_step,
    thinking_form_short,
    _scale,
)
from yas.context_state import context_state
from yas.info.git import GitInfo
from yas.render.metrics import burndown_delta, fmt_lines_pair, subagent_dur_str, subagent_type_label
from yas.render.pill import Pill
from yas.render.tasks_view import fmt_duration, select_window, total_elapsed
from yas.session import ContextWindow, RateBucket, RateLimits
from yas.info.subagents import RunningSubagent
from yas.info.workflows import RunningWorkflow
from yas.info.tasks import TaskList
from yas.render.text import _middle_ellipsis, _visible_width, fmt_tok, fmt_tok_fixed, strike
from yas.tokens import TokenRate

if TYPE_CHECKING:
    from yas.themes import Theme

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
    """Effective context-token count driving the bar/label/colour; single source of truth
    shared by `_ctx_fill_ratio` and `context_line` so they never disagree."""
    if ctx.used_percentage is not None and ctx.context_window_size > 0:
        return max(0, round(ctx.used_percentage / 100.0 * ctx.context_window_size))
    return max(0, ctx.total_input_tokens)


def _ctx_fill_ratio(ctx: ContextWindow, soft_limit: int) -> tuple[float, float]:
    """Return (fill_ratio, pct_soft) for the context bar, scaled to `soft_limit` (not the full window)."""
    if soft_limit <= 0:
        return 0.0, 0.0
    fill_ratio = min(_ctx_used_tokens(ctx) / soft_limit, 1.0)
    pct_soft   = fill_ratio * 100.0
    return fill_ratio, pct_soft


def _best_fit_cluster(
    build_cluster: Callable[[bool, bool, bool], str],
    fits: Callable[[str], bool],
) -> str:
    """Pick the richest subagent stats cluster that satisfies `fits`; tok+loc are never shed, only model."""
    cluster = build_cluster(True, True, False)  # floor: tok + loc, no model
    for show_lines, show_tok, show_model in ((True, True, True),):
        cand = build_cluster(show_lines, show_tok, show_model)
        if fits(cand):
            cluster = cand
            break
    return cluster


def _is_pua(ch: str) -> bool:
    """True if `ch` is a Nerd Font Private Use Area codepoint."""
    cp = ord(ch)
    return 0xE000 <= cp <= 0xF8FF or 0xF0000 <= cp <= 0xFFFFD


def _strike_activity(activity: str) -> str:
    """Strike an activity segment's text, leaving its leading PUA glyph plain (call after ellipsis truncation)."""
    if not activity:
        return ''
    glyph, sep, text = activity.partition(' ')
    if sep:
        return f'{glyph}{sep}{strike(text)}'
    if _is_pua(activity[0]):
        return f'{activity[0]}{strike(activity[1:])}'
    return strike(activity)


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
        self.FABLE       = t.models['fable'].label
        self.MYTHOS      = t.models['mythos'].label
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
    FABLE     = CLR_ROSE
    MYTHOS    = CLR_TEAL_VIOLET

    # --- Gradient delegations (theme-driven; see r.gradient for GRAD_STOPS etc.) ---
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
        return f'{" " * lead}{color}{BOX_V}{self.R}{trailing}'

    def sparkline_1row(self, history: list[int], live: bool = False) -> str:
        return self.gradient.sparkline_1row(history, live)

    def spark_rgb(self, t: float, dim: float = 1.0) -> tuple[int, int, int]:
        return self.gradient.spark_rgb(t, dim)

    def spark_color(self, t: float, dim: float = 1.0) -> str:
        return self.gradient.spark_color(t, dim)

    # --- Border delegations (backward compat) ---
    def border_top(self, width: int, session_id: str = '', downs: tuple[int, ...] = (), fill: float = 1.0, pill: Pill | None = None, labels: tuple[tuple[str, int], ...] = ()) -> str:
        return self.border.border_top(width, session_id, downs, fill, pill, labels)

    def border_bottom(self, width: int, ups: tuple[int, ...] = (), fill: float = 1.0, timing: str = '', version: str = '') -> str:
        return self.border.border_bottom(width, ups, fill, timing, version)

    def border_separator(self, width: int, ups: tuple[int, ...] = (), downs: tuple[int, ...] = (), fill: float = 1.0, labels: tuple[tuple[str, int], ...] = ()) -> str:
        return self.border.border_separator(width, ups, downs, fill, labels)

    def border_separator_dim(self, width: int, downs: tuple[int, ...] = (), ups: tuple[int, ...] = (), fill: float = 1.0, pill: Pill | None = None, pill_edge: str = 'bottom', labels: tuple[tuple[str, int], ...] = ()) -> str:
        return self.border.border_separator_dim(width, downs, ups, fill, pill, pill_edge, labels)

    def border_line(self, content: str, width: int, fill: float = 1.0, bg_lead: str = '', bg_trail: str = '', pill_flush: bool = False, right_pill: str = '') -> str:
        return self.border.border_line(content, width, fill, bg_lead, bg_trail, pill_flush, right_pill)

    def path_git(
        self, short_pwd: str, git: GitInfo,
        *, show_path: bool = True, show_commit: bool = True, show_dirty: bool = True,
        show_icons: bool = True,
    ) -> str:
        dirty = ''
        if show_dirty:
            if git.untracked > 0:
                dirty += f'{self.DIRTY}{GLYPH_UNTRACKED}{git.untracked}{RESET}'
            if git.modified > 0:
                dirty += f'{self.DIRTY}*{git.modified}{RESET}'
            if git.deleted > 0:
                dirty += f'{self.DIRTY}-{git.deleted}{RESET}'
            if git.renamed > 0:
                dirty += f'{self.DIRTY}{GLYPH_RENAMED} {git.renamed}{RESET}'
            if dirty:
                dirty = ' ' + dirty
        commit_part = f'{self.LABEL}/{self.R}{self.COMMIT}{git.commit}{self.R}' if show_commit else ''
        # cwd path is whole-unit: shown in full or omitted (no middle-ellipsis).
        path_part = f'{self.PWD}{short_pwd}{self.R} ' if show_path else ''
        # icons-off still reserves the row's 2-col left margin via a literal space.
        glyph_part = f'{GLYPH_FOLDER}  ' if show_icons else ' '

        return (
            f'{self.ICON_PATH}{glyph_part}{path_part}'
            f'{self.LABEL}{self.ARROW}{BOLD}{GLYPH_IN}{self.R}'
            f' {self.BRANCH}{git.branch}{self.R}'
            f'{commit_part}{dirty}'
        )

    def path_glyph_only(self, show_icons: bool = True) -> str:
        """Presence-glyph floor: folder glyph alone (1 visible col), or empty when icons are off."""
        if not show_icons:
            return ''
        return f'{self.ICON_PATH}{GLYPH_FOLDER}{self.R}'

    def path_git_compact(self, short_pwd: str, git: GitInfo) -> str:
        return (
            f'{self.ICON_PATH}  {self.PWD}{short_pwd}{self.R}'
            f' {self.LABEL}{self.ARROW}{BOLD}{GLYPH_IN}{self.R}'
            f' {self.BRANCH}{git.branch}{self.R}'
        )

    def fit_path(
        self, short_pwd: str, git: GitInfo, target_w: int,
        *, compact_only: bool = False, show_icons: bool = True,
    ) -> str:
        def fits(s: str) -> bool:
            return _visible_width(s) <= target_w

        # Whole-unit ladder (never middle-ellipsized): full -> drop commit ->
        # drop commit+dirty -> compact -> branch-only -> glyph-only floor.
        if not compact_only:
            for kwargs in (
                {},
                {'show_commit': False},
                {'show_commit': False, 'show_dirty': False},
            ):
                candidate = self.path_git(short_pwd, git, show_icons=show_icons, **kwargs)
                if fits(candidate):
                    return candidate

        compact = self.path_git_compact(short_pwd, git)
        if fits(compact):
            return compact

        branch_only = self.path_git(
            short_pwd, git, show_path=False, show_commit=False, show_dirty=False,
            show_icons=show_icons,
        )
        if fits(branch_only):
            return branch_only

        return self.path_glyph_only(show_icons=show_icons)

    def model_colour(self, model_name: str) -> str:
        return self.theme.models[model_key(model_name)].label

    def fill_colour(self, pct: float) -> str:
        if pct >= 90:
            return self.alert
        if pct >= 70:
            return self.warn
        return self.safe

    def elapsed_section(self, elapsed: str, clear_str: str = '', show_icons: bool = True) -> tuple[str, int]:
        """Compose the elapsed-cell content and its visible width; clear timer (if any) leads, session timer trails."""
        if clear_str:
            sess_part = (
                f'  {self.SESSION}{("+" + elapsed).rjust(8)}{self.R}'
                if elapsed else ''
            )
            glyph_part = f'{GLYPH_CLEAR}  ' if show_icons else ''
            text = f'{glyph_part}{CLR_CYAN}+{clear_str}{RESET}{sess_part}'
            return text, _visible_width(text)
        padded = ('+' + elapsed).rjust(8) if elapsed else elapsed.rjust(8)
        text   = f'{self.SESSION}{padded}{self.R}'
        return text, _visible_width(text)

    def cache_section(self, remaining: float, elapsed_pct: int, show_icons: bool = True) -> tuple[str, int]:
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
        glyph_part = f'{GLYPH_CACHE}  ' if show_icons else ''
        text   = f'{glyph_part}{colour}-{dur}{RESET}'
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

    def model_section_compact(
        self, model_name: str, rate_limits: RateLimits, max_width: int,
        effort_level: str = '', show_icons: bool = True,
    ) -> tuple[str, int]:
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
            rate_icon = f'{c_helper}{BOLD}{ICON_LIMIT_5H}{self.R} ' if show_icons else ''
            if pct_bg:
                cells: list[tuple[str, tuple[int, int, int] | None, bool, bool]] = []
                if show_icons:
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
                    f' {rate_icon}{rate}'
                ), pw
            glyph_part = f'{GLYPH_MODEL_LIGHT}  ' if show_icons else ''
            return (
                f'{model_clr}{glyph_part}{name}{self.R}'
                f' {self.LABEL}|{self.R}'
                f' {rate_icon}{rate}'
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
        return _build(model_name[:name_budget] + ELLIPSIS, rate_pct)

    def _rate_helpers(self, rate_limits: RateLimits, gap_5h: int = 1, gap_7d: int = 1, show_icons: bool = True) -> tuple[str, str]:
        """Build the 5h and (optional) 7d limit sub-sections; gap_5h/gap_7d set inter-stat spacing."""
        c_helper  = rainbow_at(rainbow_step(), 9)
        icon_5h   = f'{c_helper}{BOLD}{ICON_LIMIT_5H}{self.R}  ' if show_icons else ''
        helper_5h = f'{icon_5h}{self.white_brt}{BOLD}{self.helper(rate_limits.five_hour, gap_5h, show_icons=show_icons)}{self.R}'
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
                show_icons=show_icons,
            )
            seven_trend_part = f'{" " * gap_7d}{seven_trend}' if seven_trend else ''
            icon_7d   = f'{c_helper}{BOLD}{ICON_LIMIT_7D}{self.R}  ' if show_icons else ''
            helper_7d = f'{icon_7d}{seven_clr}{seven_pct_str}%{self.R}{seven_trend_part}'
        return helper_5h, helper_7d

    def model_right_section(
        self, model_name: str, model_thinking: str, rate_limits: RateLimits,
        effort_level: str = '', fast_mode: bool = False, show_icons: bool = True,
        *, include_7d: bool = True, model_form: str = 'full',
    ) -> tuple[str, str, str, int]:
        # model_form == 'short': display-only abbreviation, e.g. 'O5-1m (l)'.
        if model_form == 'short':
            model_name     = model_form_short(model_name)
            model_thinking = thinking_form_short(model_thinking)
        model_clr  = self.model_colour(model_name)
        pct        = self._model_bg_pct(effort_level)
        lead_glyph = GLYPH_BURN_FAST if fast_mode else GLYPH_MODEL_LIGHT

        if pct:
            anchor, shift = self._model_anchor_pair(model_name)
            cells: list[tuple[str, tuple[int, int, int] | None, bool, bool]] = []
            cells.append((' ',          anchor, False, False))   # left padding
            if show_icons:
                cells.append((lead_glyph, anchor, False, False))
                cells.append((' ',        anchor, False, False))
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
        else:
            glyph_part = f' {lead_glyph}  ' if show_icons else '  '
            if model_thinking:
                right_text = f'{model_clr}{glyph_part}{model_name}{self.R} {model_clr}({model_thinking}){RESET} '
            else:
                right_text = f'{model_clr}{glyph_part}{model_name}{self.R} '
            # Trailing space is deliberate: keeps a digit from landing flush
            # against the closing border at tight widths (build_wide's `pad`).

        right_w = _visible_width(right_text)

        helper_5h, helper_7d = self._rate_helpers(rate_limits, show_icons=show_icons)
        if not include_7d:
            helper_7d = ''

        return helper_5h, helper_7d, right_text, right_w

    def model_right_section_compact(
        self, model_name: str, rate_limits: RateLimits, max_right_width: int,
        effort_level: str = '', show_icons: bool = True,
    ) -> tuple[str, str, int]:
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
                        show_icons=show_icons,
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
                if show_icons:
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
            glyph_part = f'{GLYPH_MODEL_LIGHT}  ' if show_icons else ''
            text = f'{model_clr}{glyph_part}{name}{self.R}'
            return text, _visible_width(text)

        right_text, right_w = _make_right(model_name)
        if right_w > max_right_width and max_right_width > 0:
            _, base_w = _make_right('')
            budget    = max(3, max_right_width - base_w - 1)
            right_text, right_w = _make_right(model_name[:budget] + ELLIPSIS)
        return rate_text, right_text, right_w

    def plugins_skills(self, skills_count: int, skills_names: str, plugin_names: str, show_icons: bool = True) -> str:
        step = rainbow_step()
        c_skills = rainbow_at(step, 3)
        c_plugins = rainbow_at(step, 6)
        extras = []
        if skills_count > 0:
            skills_glyph = f'{c_skills}{BOLD}{GLYPH_SKILLS}  {self.R}' if show_icons else ''
            extras.append(f'{skills_glyph}{self.SKILLS}{skills_names}{self.R}')
        if plugin_names:
            plugins_glyph = f'{c_plugins}{BOLD}{GLYPH_PLUGINS}  {self.R}' if show_icons else ''
            extras.append(f'{plugins_glyph}{self.SKILLS}{plugin_names}{self.R}')
        line = f' {self.LABEL}|{self.R} '.join(extras)
        # icons-off: add the same fallback margin space as path/tokens rows.
        return f' {line}' if (line and not show_icons) else line

    def tool_counts_row(self, counts: dict[str, tuple[int, int]], width: int, *, fill: float = 1.0) -> str:
        """Greedy-filled per-tool ``Name main/sub`` counts as a full-width line, ordered by total desc; overflow shows ``+k`` unshown types."""
        content_w = max(1, width - 4)
        gap       = 3
        items     = sorted(counts.items(), key=lambda kv: (-(kv[1][0] + kv[1][1]), kv[0]))
        total     = len(items)
        shown: list[tuple[str, int]] = []  # (colored, width)
        used = 0
        for name, (main, sub) in items:
            plain = f'{name} {main}/{sub}'
            w     = _visible_width(plain)
            add   = w + (gap if shown else 0)
            if used + add > content_w:
                break
            colored = (
                f'{self.white_brt}{name}{self.R} '
                f'{self.TOK}{main}{self.R}'
                f'{self.LABEL}/{self.R}'
                f'{FAINT}{sub}{self.R}'
            )
            shown.append((colored, w))
            used += add
        parts = [c for c, _ in shown]
        if len(shown) < total:
            # Drop trailing entries as needed to make room for the +k marker.
            while True:
                k     = total - len(shown)
                mw    = _visible_width(f'+{k}')
                extra = (gap + mw) if shown else mw
                if used + extra <= content_w or not shown:
                    break
                _, w = shown.pop()
                used -= w + (gap if shown else 0)
            k     = total - len(shown)
            parts = [c for c, _ in shown]
            parts.append(f'{self.LABEL}+{k}{self.R}')
        return (' ' * gap).join(parts)

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
                raw = raw[:cap] + ELLIPSIS
            return f'{GLYPH_TASKS} {name}[{raw}]'
        if kind == 'thinking':
            return f'{GLYPH_THINKING} (thinking)'
        if kind == 'text':
            raw = name
            if not raw:
                return f'{GLYPH_REPLYING} (replying)'
            if _visible_width(raw) > cap:
                raw = raw[:cap] + ELLIPSIS
            return f'{GLYPH_REPLYING} {raw}'
        return ''

    def _subagent_desc_tint(
        self, desc_text: str, desc_max: int, is_done: bool,
    ) -> tuple[str, int]:
        """Truncate + colour-tint a subagent row's description; returns `(sep_desc, sep_desc_w)`."""
        if not desc_text or desc_max <= 0:
            return '', 0
        if _visible_width(desc_text) > desc_max:
            desc_text = desc_text[:desc_max - 1] + '…'  # U+2026 HORIZONTAL ELLIPSIS
        desc_w = _visible_width(desc_text)
        if is_done:
            # Strike only the description field to mark the task finished.
            sep_desc = (
                f' {self.CTX_DIM}·{self.R} '
                f'{self.CTX_DIM}{STRIKE}{ITALIC}{desc_text}{UNSTRIKE}{self.R}'
            )
        else:
            sep_desc = f' {self.LABEL}·{self.R} {self.CTX}{ITALIC}{desc_text}{self.R}'
        return sep_desc, 3 + desc_w

    def subagent_row(
        self,
        sub: RunningSubagent,
        content_width: int,
        *,
        twoline: bool = False,
        session_inout: int = 0,
        stats_col: int | None = None,
        tree_prefix: str = '',
        tree_depth: int | None = None,
        tree_single: bool = False,
        tree_desc_col: int | None = None,
        tree_activity_col: int | None = None,
        tree_model_w: int | None = None,
        tree_lines_w: int | None = None,
        lines: tuple[int, int] | None = None,
        oneline_name_w: int | None = None,
        oneline_model_w: int | None = None,
        oneline_lines_w: int | None = None,
    ) -> str:
        # Tree branch prefix ('├ '/'└ ', indented per depth) renders inline
        # between duration and name (`<time> <elbow> <name>`), inside
        # content_width/front_w; stats_col/tree_desc_col/tree_activity_col
        # are already absolute row-relative offsets, used as-is.
        prefix_w = _visible_width(tree_prefix)
        # tree_depth 0 (top-level agents) render name BOLD; depth-1+ REGULAR.
        # Flat (non-tree) rows pass tree_depth=None and stay ITALIC.
        if tree_depth == 0:
            name_style = BOLD
        elif tree_depth is None:
            name_style = ITALIC
        else:
            name_style = ''
        now         = time.time()
        status      = subagent_status(sub)
        is_done     = subagent_is_terminal(status)
        # Terminal tint: green for a successful finish, red otherwise (only meaningful when is_done).
        done_clr    = self.safe if status == 'completed' else self.alert
        # `mark` strikes every text field on a finished row (zero-width SGR, applied at paint time only).
        mark        = strike if is_done else str
        run_count   = getattr(sub, 'run_count', 0)
        is_resumed  = (not is_done) and (getattr(sub, 'resumed', False) or run_count >= 1)
        dur_s   = subagent_dur_str(sub, now)

        # Display form keeps a bracketed context-size suffix (e.g. 'sonnet[1m]'); colour keys off the bare family.
        short_model = model_display(sub.model)
        model_clr   = self.model_colour(sub.model)
        ctx_clr     = self.risk_zone_color(sub.total_input)

        step      = rainbow_step()
        c_marker  = rainbow_at(step, 12)
        # Capped at SUBAGENT_NAME_MAX (matches layout's cohort measurement) so
        # one pathological agent type can't push the model/description columns off the row.
        type_text = subagent_type_label(sub)
        if _visible_width(type_text) > SUBAGENT_NAME_MAX:
            type_text = type_text[:SUBAGENT_NAME_MAX - 1] + ELLIPSIS

        target_w = content_width

        if twoline:
            # line 1: duration-first identity + right-aligned cluster.
            # Tree-single mode embeds the model label in the front field
            # (`<time> <elbow> <name> <marker> <model>`); the name/model
            # separator doubles as the run-state marker ('✓'/'✗'/'↺'/'·').
            front_model_gap = 3 if tree_single else 0  # ' X ' marker/separator before the model field
            front_model_str = ''
            if tree_single:
                front_model_str = short_model.ljust(tree_model_w) if tree_model_w else short_model
            front_model_w = _visible_width(front_model_str)
            # dur_s is not fixed-width (grows a digit past 9m/9h) — measure it.
            dur_w    = _visible_width(dur_s)
            front_w  = (dur_w + 1 + prefix_w + _visible_width(type_text)
                        + front_model_gap + front_model_w)

            # Pad type field so the front reaches a cohort-common width,
            # keeping ' · description' at the same column across the cohort.
            if tree_desc_col is not None:
                front_w = max(front_w, tree_desc_col - 1)  # -1: leading space of ' · '
                type_text = type_text.ljust(max(
                    0, front_w - dur_w - 1 - prefix_w - front_model_gap - front_model_w,
                ))

            # Stats/model cluster right-aligns to stats_w so the activity
            # column starts at a consistent offset down the cohort.
            stats_w = target_w
            if tree_single:
                if tree_activity_col is not None:
                    stats_w = max(front_w + 1, min(target_w, tree_activity_col - SUBAGENT_STATS_ACTIVITY_GAP))
                else:
                    activity_reserve = min(48, content_width // 3)
                    stats_w          = max(front_w + 1, target_w - activity_reserve)

            # fmt_tok_fixed pins every row's tok reading to the same 5-char width regardless of mantissa digits.
            tok_field = fmt_tok_fixed(sub.total_input).rjust(5)
            # Self-scoped read/changed each shed independently: a zero side
            # blank-pads to the populated side's width rather than showing '0',
            # keeping cluster width (and the activity gap after it) deterministic.
            read_lc, changed_lc = lines if lines is not None else (0, 0)
            if tree_single:
                lines_w = tree_lines_w if tree_lines_w is not None else 5
                read_s, changed_s = fmt_lines_pair(read_lc, changed_lc, width=lines_w, fixed=True)
            else:
                lines_w = 0
                read_s, changed_s = fmt_lines_pair(read_lc, changed_lc, fixed=True)
            read_blank_w    = _visible_width(read_s)
            changed_blank_w = _visible_width(changed_s)
            read_part    = read_s if (lines is not None and read_lc) else ' ' * read_blank_w
            changed_part = changed_s if (lines is not None and changed_lc) else ' ' * changed_blank_w
            lines_field  = f'{mark(read_part)} / {mark(changed_part)}'
            # tree_single always reserves the field's width (see `build_cluster` below) regardless of `has_lines`.
            has_lines = lines is not None and bool(read_lc or changed_lc)
            if not tree_single:
                model_str = short_model.rjust(6)  # tree_single moves the model field into the front cluster instead

            # Elbow between duration and name; tree_prefix already carries its own colour codes, used as-is.
            elbow = tree_prefix if prefix_w else ''
            # Finished row greys duration/name via CTX_DIM; only the ✓/✗ marker keeps done_clr.
            if is_done:
                front_c = f'{self.CTX_DIM}{mark(dur_s)}{self.R} {elbow}{self.CTX_DIM}{name_style}{mark(type_text)}{self.R}'
            else:
                front_c = f'{self.CTX}{dur_s}{self.R} {elbow}{self.SKILLS}{name_style}{type_text}{self.R}'
            if tree_single:
                # Model sits in the front field (front_model_str); separator doubles as the run-state marker.
                model_field_clr = self.CTX_DIM if is_done else model_clr
                if is_done:
                    mid_marker = f'{done_clr}{subagent_marker_glyph(status)}{self.R}'
                elif is_resumed:
                    mid_marker = f'{c_marker}{BOLD}{GLYPH_SUBAGENT_RESUME}{self.R}'
                else:
                    mid_marker = f'{self.LABEL}{MIDDLE_DOT}{self.R}'
                front_c += f' {mid_marker} {model_field_clr}{mark(front_model_str)}{self.R}'

            # Cluster order (tree_single): '· tok · lines' (model already moved to front).
            # Flat mode: legacy '· lines · tok · model' order. Field offsets mirror
            # `render.metrics.subagent_cluster_field_offsets`.
            dot = f'{MIDDLE_DOT} '

            def build_cluster(show_lines: bool, show_tok: bool, show_model: bool = True) -> str:
                d = self.CTX_DIM if is_done else self.LABEL
                lines_clr = self.CTX_DIM  # matches the activity column's grey, not tok's risk-zone tint
                fields: list[str] = []
                if tree_single:
                    if show_tok:
                        tok_clr = d if is_done else ctx_clr
                        fields.append(f'{tok_clr}{mark(tok_field)}{self.R}')
                    # tree_single always reserves this width when show_lines, even with no data.
                    if show_lines:
                        fields.append(f'{lines_clr}{lines_field}{self.R}')
                else:
                    if show_lines and has_lines:
                        fields.append(f'{lines_clr}{lines_field}{self.R}')
                    if show_tok:
                        tok_clr = d if is_done else ctx_clr
                        fields.append(f'{tok_clr}{mark(tok_field)}{self.R}')
                    if show_model:
                        model_clr_use = d if is_done else model_clr
                        fields.append(f'{model_clr_use}{mark(model_str)}{self.R}')
                if not fields:
                    return ''
                sep = f' {d}{dot}{self.R}'
                return f'{d}{dot}{self.R}' + sep.join(fields)

            # Stats cluster anchors at a fixed content column (wide) when
            # even the protected floor fits in the slack right of stats_col;
            # otherwise falls through to right-aligned for narrow widths.
            floor_w  = _visible_width(build_cluster(False, False, False) if tree_single
                                       else build_cluster(True, True, False))
            anchored = stats_col is not None and (stats_w - stats_col) >= floor_w

            if anchored:
                assert stats_col is not None  # narrowed by `anchored`
                avail = stats_w - stats_col  # slack to the right of the anchor
                # Richest cluster fitting the anchored slack; model is the only field ever dropped (tok+loc protected).
                cluster = _best_fit_cluster(
                    build_cluster, lambda cand: _visible_width(cand) <= avail,
                )
                cluster_w = _visible_width(cluster)

                # Truncate the description so it stops before the stats column
                # with at least a 1-col gap. ' · ' separator is 3 cols wide.
                desc_text  = sub.description or ''
                desc_max   = stats_col - front_w - 3 - 1
                sep_desc, sep_desc_w = self._subagent_desc_tint(desc_text, desc_max, is_done)

                # Anchor the cluster's first `·` at content-offset stats_col.
                pad1  = max(1, stats_col - front_w - sep_desc_w)
                line1 = f'{front_c}{sep_desc}{" " * pad1}{cluster}'
                line1 += ' ' * max(0, stats_w - _visible_width(line1))
            else:
                # Richest cluster fitting alongside front + 1-col gap; same shed ladder as anchored branch above.
                cluster = _best_fit_cluster(
                    build_cluster,
                    lambda cand: front_w + 1 + _visible_width(cand) <= stats_w,
                )
                cluster_w = _visible_width(cluster)

                # Fill the description into the space left over (truncates first).
                desc_text  = sub.description or ''
                desc_max   = stats_w - front_w - cluster_w - 1 - 3  # 1-col gap + ' · '
                sep_desc, sep_desc_w = self._subagent_desc_tint(desc_text, desc_max, is_done)

                pad1  = max(1, stats_w - front_w - sep_desc_w - cluster_w)
                line1 = f'{front_c}{sep_desc}{" " * pad1}{cluster}'

            if tree_single:
                # Precedence (highest-retained first): timer+tok+loc (protected)
                # > type > model (both baked into the front field, never shed)
                # > activity/log (appended below, gap allowing) > name/description
                # (the elastic field, truncated first via desc_max/stats_col).
                # Activity column stays aligned via a constant
                # SUBAGENT_STATS_ACTIVITY_GAP-col '·' separator, since the
                # cluster fields are fixed-width. Only appended when room remains.
                gap     = SUBAGENT_STATS_ACTIVITY_GAP
                dot_clr = self.CTX_DIM if is_done else self.LABEL
                avail_act = target_w - _visible_width(line1)
                if avail_act >= gap:
                    act_w    = avail_act - gap
                    activity = self.subagent_activity(sub.last_activity, cap=max(0, act_w - 3))
                    if _visible_width(activity) > act_w:
                        activity = activity[:max(0, act_w - 1)] + ELLIPSIS
                    if is_done:
                        activity = _strike_activity(activity)  # after truncation
                    line1 = f'{line1} {dot_clr}{MIDDLE_DOT}{self.R} {self.CTX_DIM}{activity}{self.R}'
                line1 += ' ' * max(0, target_w - _visible_width(line1))
                # Elbow is already embedded in front_c (between the duration
                # and the name), so line1 needs no further prefixing here.
                return line1

            # line 2: activity-only continuation, indented by prefix_w to sit under line 1's front field.
            target_w2    = max(1, target_w - prefix_w)
            avail2       = max(0, target_w2 - 6)  # '   '(3) + └ + '  '(2)
            activity_cap = min(100, avail2)
            activity     = self.subagent_activity(sub.last_activity, cap=activity_cap)
            if _visible_width(activity) > avail2:
                activity = activity[:max(0, avail2 - 1)] + ELLIPSIS
            left2_w = 6 + _visible_width(activity)  # measured before the strike
            if is_done:
                activity = _strike_activity(activity)  # after truncation
            left2   = (
                f'   {self.CTX_DIM}{GLYPH_CONTINUATION}{self.R}  '
                f'{self.CTX_DIM}{activity}{self.R}'
            )
            pad2    = max(0, target_w2 - left2_w)
            line2   = f'{left2}{" " * pad2}'

            if prefix_w:
                return f'{line1}\n{" " * prefix_w}{line2}'
            return f'{line1}\n{line2}'

        # one-line collapse (narrow/medium): `<time> <elbow> <name> <marker>
        # <model> · <tok> [· <activity>]`; marker rides in the name/model
        # separator ('✓'/'✗'/'↺'/'·'), activity is the last elastic column.
        elbow_n   = tree_prefix if prefix_w else ''
        dot_n_clr = self.CTX_DIM if is_done else self.LABEL
        tok_n_clr = self.CTX_DIM if is_done else ctx_clr
        tok_n     = fmt_tok_fixed(sub.total_input).rjust(5)
        tok_n_w   = 3 + 5  # ' · ' + fixed 5-wide tok field

        # Cohort alignment: name/model render fixed-width (sized to the
        # cohort's widest), shrinking name then model under width pressure so
        # separators stay column-aligned down every row.
        name_field_w  = oneline_name_w or (prefix_w + _visible_width(type_text))
        model_field_w = oneline_model_w or _visible_width(short_model)
        over = (_visible_width(dur_s) + 1 + name_field_w + 3 + model_field_w
                + tok_n_w - target_w)
        if over > 0:
            shrink        = min(over, max(0, name_field_w - 8))  # 8: name floor
            name_field_w -= shrink
            over         -= shrink
        if over > 0:
            model_field_w = max(1, model_field_w - over)
        avail_type = max(1, name_field_w - prefix_w)
        if _visible_width(type_text) > avail_type:
            type_text = type_text[:avail_type - 1] + ELLIPSIS
        type_text = type_text.ljust(avail_type)
        if _visible_width(short_model) > model_field_w:
            model_field = short_model[:max(1, model_field_w - 1)] + ELLIPSIS
        else:
            model_field = short_model.ljust(model_field_w)

        if is_done:
            front_n = f'{self.CTX_DIM}{mark(dur_s)}{self.R} {elbow_n}{self.CTX_DIM}{name_style}{mark(type_text)}{self.R}'
        else:
            front_n = f'{self.CTX}{dur_s}{self.R} {elbow_n}{self.SKILLS}{name_style}{type_text}{self.R}'
        model_n_clr = self.CTX_DIM if is_done else model_clr
        if is_done:
            mid_n = f'{done_clr}{subagent_marker_glyph(status)}{self.R}'
        elif is_resumed:
            mid_n = f'{c_marker}{BOLD}{GLYPH_SUBAGENT_RESUME}{self.R}'
        else:
            mid_n = f'{dot_n_clr}{MIDDLE_DOT}{self.R}'
        front_n += (f' {mid_n} {model_n_clr}{mark(model_field)}{self.R}'
                    f' {dot_n_clr}{MIDDLE_DOT}{self.R} {tok_n_clr}{mark(tok_n)}{self.R}')
        front_n_w = _visible_width(front_n)

        # Never overflow the right border.
        if front_n_w > target_w:
            front_n   = _middle_ellipsis(front_n, target_w)
            front_n_w = _visible_width(front_n)

        # LOC: opportunistic (no reserved column, unlike twoline/tree_single);
        # placed before activity so activity sheds first when slack is tight.
        read_lc_n, changed_lc_n = lines if lines is not None else (0, 0)
        has_lines_n = lines is not None and bool(read_lc_n or changed_lc_n)
        if has_lines_n:
            lines_w_n = oneline_lines_w if oneline_lines_w is not None else 0
            read_s_n, changed_s_n = fmt_lines_pair(read_lc_n, changed_lc_n, width=lines_w_n, fixed=True)
            loc_field_n = f'{mark(read_s_n)} / {mark(changed_s_n)}'
            loc_field_w = _visible_width(loc_field_n)
            avail_loc   = target_w - front_n_w - 3  # ' · '
            if avail_loc >= loc_field_w:
                front_n   += f' {dot_n_clr}{MIDDLE_DOT}{self.R} {self.CTX_DIM}{loc_field_n}{self.R}'
                front_n_w += 3 + loc_field_w

        # Activity/log segment: last column, running agents only, needs >=12 cols of slack.
        act_seg   = ''
        act_seg_w = 0
        if not is_done:
            avail_n = target_w - front_n_w - 3  # ' · '
            if avail_n >= 12:
                activity = self.subagent_activity(sub.last_activity, cap=avail_n)
                if _visible_width(activity) > avail_n:
                    activity = activity[:max(0, avail_n - 1)] + ELLIPSIS
                if activity:
                    act_seg   = f' {dot_n_clr}{MIDDLE_DOT}{self.R} {self.CTX_DIM}{activity}{self.R}'
                    act_seg_w = 3 + _visible_width(activity)
        pad_n = max(0, target_w - front_n_w - act_seg_w)
        return f'{front_n}{act_seg}{" " * pad_n}'

    def workflow_header(self, run: RunningWorkflow, content_width: int) -> str:
        """Group header for a workflow run: phase trail if `run.phases` known, else `[<phase>]` bracket form."""
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
        """Dot-separated phase trail: current phase highlighted (SKILLS + ❯), rest dimmed."""
        sep   = f' {self.CTX_DIM}{WF_PHASE_DOT}{self.R} '
        parts = []
        for title in run.phases:
            if run.phase and title == run.phase:
                parts.append(f'{self.SKILLS}{GLYPH_WF_CURRENT}{title}{self.R}')
            else:
                parts.append(f'{self.CTX_DIM}{title}{self.R}')
        return sep.join(parts)

    def workflow_summary(
        self, run: RunningWorkflow, content_width: int, *, hidden_agents: int = 0, show_icons: bool = True,
    ) -> str:
        """Summary footer for a workflow run: ``└  N agents · M done · <tok>``, appends ``+K hidden`` when capped."""
        step  = rainbow_step()
        c_sum = rainbow_at(step, 7)
        sep   = f' {self.LABEL}{MIDDLE_DOT}{self.R} '
        parts = [
            f'{self.CTX}{run.agent_count}{self.R} {self.LABEL}agents{self.R}',
            f'{self.CTX}{run.done_count}{self.R} {self.LABEL}done{self.R}',
            f'{self.CTX}{fmt_tok(run.total_tokens)}{self.R}',
        ]
        if hidden_agents > 0:
            parts.append(f'{self.LABEL}+{hidden_agents} hidden{self.R}')
        lead = f'{c_sum}{GLYPH_WF_SUMMARY}{self.R}  ' if show_icons else ''
        line = f'{lead}{sep.join(parts)}'
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

        # compact (narrow): glyph + done/total left, active task's live timer right-anchored.
        if compact:
            head   = f'{glyph_s}  {count_p}'
            active = tasks.active
            if active is None or active.started_at is None:
                return [head]
            live    = fmt_duration(now - active.started_at)
            right   = f'{BRT}{BOLD}{live}{self.R}'
            right_w = _visible_width(right)
            head_w  = _visible_width(head)
            if head_w + TASK_HEADER_RIGHT_GAP_MIN + right_w > content_width:
                head   = _middle_ellipsis(head, max(1, content_width - TASK_HEADER_RIGHT_GAP_MIN - right_w))
                head_w = _visible_width(head)
            mid = max(TASK_HEADER_RIGHT_GAP_MIN, content_width - head_w - right_w)
            return [f'{head}{" " * mid}{right}']

        # full-list (wide/medium): header + windowed items.
        elapsed   = total_elapsed(tasks, now)
        elapsed_s = fmt_duration(elapsed) if elapsed is not None else ''

        win = select_window(tasks)

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

        # Fixed leading timer column = widest shown timer, covers header's Total Elapsed too.
        timer_w = max(
            (_visible_width(tm) for *_, tm in rows if tm),
            default=0,
        )
        timer_w = max(timer_w, _visible_width(elapsed_s))

        # Header: Total Elapsed (rjust to timer_w) first, then glyph + done/total; omitted when never started.
        if elapsed_s:
            head_pad = ' ' * max(0, timer_w - _visible_width(elapsed_s))
            head     = f'{head_pad}{DIM}{elapsed_s}{self.R} {glyph_s}  {count_p}'
        else:
            head = f'{glyph_s}  {count_p}'

        inner_w = content_width
        out: list[str] = [head]

        # Per item: [timer col, rjust] + gap + glyph + '  ' + number + subject (padded/truncated to field_w).
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
                acc = ''
                for ch in subj:
                    if _visible_width(acc + ch) > avail - 1:
                        break
                    acc += ch
                subj = acc + ELLIPSIS
                subj_pad = max(0, avail - _visible_width(subj))
            else:
                subj_pad = avail - sw

            line = ''
            if timer_w:
                tm_pad = max(0, timer_w - _visible_width(timer))
                line += ' ' * tm_pad
                line += f'{tm_clr}{timer}{self.R}' if timer else ' ' * _visible_width(timer)
                line += ' ' * gap
            line += f'{g_clr}{glyph}{self.R}  {g_clr}{num}{self.R}{self.CTX}{subj}{self.R}{" " * subj_pad}'
            out.append(line)

        return out

    RATE_W  = 6
    IN_W    = 6
    CACHE_W = 6
    OUT_W   = 6

    JUSTIFY_PAD_CAP = 4  # per-slot cap (spaces) for justify breathing room

    def tokens_cost(self, sess_in: int, sess_cache: int, sess_out: int, day_in: int, day_cache: int, day_out: int, sess_cost: float, day_cost: float, tok_rate: int, session_id: str = '', box_width: int = 80, fill: float = 1.0, show_day_stats: bool = True, justify: bool = False, lines: tuple[int, int] | None = None, show_icons: bool = True) -> tuple[list[str], tuple[int, ...], int, int]:
        """One content line: tokens │ [lines │] cost │ rate-and-sparkline.

        Shed ladder (highest-retained first, one segment dropped per rung):
        tokens-over-time (rate label + sparkline) -> cost -> lines r/w ->
        tokens sess/day (protected, never shed). ``vsep_cols`` shrinks by one
        column per rung dropped. Tokens/cost column widths are measured from
        built content so the ``│`` dividers always land on the rendered
        divider column and stay attached to the ┬/┴ elbows above/below.

        Returns ``([line], vsep_cols, 0, min_width)`` — ``min_width`` is the
        floor of the surviving-minimum form (tokens sess/day alone).
        """
        day_clr = self.day_cost_colour(day_cost)
        in_active, out_active = TokenRate.recently_active(session_id)
        if show_icons:
            in_icon  = f'{ARROW_IN_ACTIVE} '  if in_active  else f'{ARROW_IN_IDLE} '   # both 2 cols
            out_icon = f'{ARROW_OUT_ACTIVE} ' if out_active else f'{ARROW_OUT_IDLE} '  # both 2 cols
        else:
            # icons off: left margin reserved by sess_in's own rjust, matching context_line.
            in_icon = out_icon = ''

        # Gaps/pads start at their minimums (tight floor); `justify` widens them from genuine slack only.
        gap1 = gap2 = ' '   # ↓in/day | (cache) | ↑out/day inter-group gaps
        cost_lpad = cost_rpad = ''
        leader_lpad = ''

        if show_day_stats:
            # Merged session/day per field, variable width -- except the
            # leading `sess_in`, rjust'd to IN_W to share a stable right edge
            # with row 2's context-fill number.
            cache = (f'{self.TOK_DIM}({fmt_tok(sess_cache)}{self.R}'
                     f'{self.TOK_DAY_DIM}/{fmt_tok(day_cache)}{self.R}'
                     f'{self.TOK_DIM}){self.R}')

            def build_tokens() -> str:
                return (
                    f'{self.LABEL}{self.BOLDY}{in_icon}{self.R}'
                    f'{self.TOK}{fmt_tok(sess_in).rjust(self.IN_W)}{self.R}{self.TOK_DAY_DIM}/{fmt_tok(day_in)}{self.R}{gap1}'
                    f'{cache}'
                    f'{self.LABEL}{gap2}{self.BOLDY}{out_icon}{self.R}'
                    f'{self.TOK}{fmt_tok(sess_out)}{self.R}{self.TOK_DAY_DIM}/{fmt_tok(day_out)}{self.R}'
                )

            def build_cost() -> str:
                cost_icon = f'{self.safe}{ICON_COST}{self.R}  ' if show_icons else ''
                return (f'{cost_lpad}{cost_icon}{self.COST}${sess_cost:,.2f}{self.R}'
                        f'{self.LABEL} / {self.R}{day_clr}${day_cost:,.2f}{self.R}{cost_rpad}')

            tokens_col = build_tokens()
            cost_col   = build_cost()
        else:
            # Session-only: per-field justification.
            sess_in_s    = fmt_tok(sess_in).rjust(self.IN_W)
            sess_cache_s = fmt_tok(sess_cache).rjust(self.CACHE_W)
            sess_out_s   = fmt_tok(sess_out).rjust(self.OUT_W)
            tokens_col = (f'{self.LABEL}{self.BOLDY}{in_icon}{self.R}{self.TOK}{sess_in_s}{self.R} '
                          f'{self.TOK_DIM}({sess_cache_s}){self.R}{self.LABEL} '
                          f'{self.BOLDY}{out_icon}{self.R}{self.TOK}{sess_out_s}{self.R}')
            cost_icon = f'{self.safe}{ICON_COST}{self.R}  ' if show_icons else ''
            cost_col = f'{cost_icon}{self.COST}${sess_cost:,.2f}{self.R}'

        def build_lines() -> str:
            # Mirrors the tokens column's glyph-pair convention (read/changed are independent, not a session/day pair).
            assert lines is not None  # guarded by caller; narrows the closure capture for mypy
            read, changed = lines
            read_s, changed_s = fmt_lines_pair(read, changed)  # width=0: single non-cohort row
            if show_icons:
                read_icon    = f'{self.LABEL}{GLYPH_LINES_READ}  {self.R}'
                changed_icon = f'{self.LABEL}  {GLYPH_LINES_CHANGED}  {self.R}'
            else:
                # icons off: two-space gap keeps the counters separated without a bare icon slot.
                read_icon, changed_icon = '', '  '
            return (f'{read_icon}{self.TOK}{read_s}{self.R}'
                    f'{changed_icon}{self.TOK}{changed_s}{self.R}')

        vsep_w        = 4
        vsep_leader_w = 4
        vsep_lines_w  = 4
        label_w       = 15

        content_w = box_width - 3
        inner     = content_w - vsep_w - vsep_leader_w  # tokens + cost + leader budget

        # Column widths track measured content (_visible_width, never len())
        # so the │ dividers sit directly after content; honest floors below
        # (`w_middle = max(w_middle, tokens_w)`) guarantee pad>=0, keeping
        # col1/col2 attached to their ┬/┴ elbows above/below.
        tokens_w = _visible_width(tokens_col)
        cost_w   = _visible_width(cost_col)
        tokens_base_w = tokens_w  # pre-justify floor: tokens sess/day is the protected shed-ladder survivor
        rate_icon    = f'{self.TOK_ICON}{ICON_TOK_RATE}  ' if show_icons else ''
        rate_label   = f'{rate_icon}{self.TOK}{fmt_tok(tok_rate)}{self.R}{self.LABEL} t/m{self.R}'
        rate_label_w = _visible_width(rate_label)
        leader_min   = max(label_w + 1, rate_label_w)

        # Smallest box holding both columns + vseps + leader; builder only emits this row when box_width >= min_width.
        min_width = tokens_w + cost_w + vsep_w + vsep_leader_w + rate_label_w + 3

        # Lines segment included only when the box clears its own with-segment floor and LINES_SEGMENT_MIN_WIDTH.
        lines_w = _visible_width(build_lines()) if lines is not None else 0
        min_width_with_lines = min_width + lines_w + vsep_lines_w
        include_lines = lines is not None and box_width >= max(min_width_with_lines, LINES_SEGMENT_MIN_WIDTH)
        if include_lines:
            inner -= vsep_lines_w

        # Justify: spend genuine slack past the tight minimum as in-section
        # padding before it flows to the sparkline leader; at the floor free=0
        # so the row is byte-identical to justify-off. Lines segment gets no
        # slot deliberately -- it stays content-measured only, so col2/col3
        # never depend on `justify`.
        cap = self.JUSTIFY_PAD_CAP
        if justify and show_day_stats:
            free = max(0, inner - tokens_w - cost_w - leader_min)
            slots = [cap - 1, cap - 1, cap, cap, cap]  # gap1, gap2, cost_l, cost_r, leader_l (gaps start at 1, pads at 0)
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
            # Rebuild padded strings; min_width above stays on the unpadded floor.
            tokens_col = build_tokens()
            cost_col   = build_cost()
            tokens_w  += give[0] + give[1]
            cost_w    += give[2] + give[3]

        TOKENS_BUDGET = tokens_w
        COST_BUDGET   = cost_w
        leader_lpad_w = len(leader_lpad)

        avail = inner - leader_min                 # room left after the leader minimum
        if TOKENS_BUDGET + COST_BUDGET <= avail:
            w_middle, w_end = TOKENS_BUDGET, COST_BUDGET
        else:
            # Over budget: give each column its measured content, share slack proportionally, clamp at content.
            w_middle = max(tokens_w, avail * TOKENS_BUDGET // (TOKENS_BUDGET + COST_BUDGET))
            w_end    = max(cost_w, avail - w_middle)

        # Honest floor: never allocate a cell narrower than its content, so trailing pad >= 0 and │ lands exactly.
        w_middle = max(w_middle, tokens_w)
        w_end    = max(w_end, cost_w)
        w_lines = lines_w if include_lines else 0  # content-measured only, never competes for slack

        tokens_col += ' ' * max(0, w_middle - tokens_w)
        cost_col   += ' ' * max(0, w_end   - cost_w)

        leader_w = max(label_w + 1, inner - w_middle - w_lines - w_end)

        col1 = w_middle + 5                                          # 1-indexed position of the tokens│ vsep
        if include_lines:
            col2 = col1 + vsep_w + w_lines                           # 1-indexed position of the lines│ vsep
            col3 = col2 + vsep_lines_w + w_end                       # 1-indexed position of the vsep_leader │
        else:
            col2 = w_middle + vsep_w + w_end + 5                     # 1-indexed position of the vsep_leader │ (today's shape)
        vsep        = self.vsep_block(col1, box_width, fill=fill, leader=True)
        vsep_leader = self.vsep_block(col3 if include_lines else col2, box_width, fill=fill, leader=True)
        if include_lines:
            lines_col   = build_lines()
            vsep_lines  = self.vsep_block(col2, box_width, fill=fill, leader=True)

        # justify leader pad eats from the leader budget, so the sparkline shrinks by the same amount.
        bar_w = leader_w - rate_label_w - leader_lpad_w

        if bar_w < 10:
            leader = f'{leader_lpad}{rate_label}'
        else:
            if session_id:
                # 1s per char, most recent bar_w seconds; reversed so the newest bucket sits leftmost next to the label.
                spark_history = TokenRate.history(session_id, bar_w, float(bar_w))[::-1]
                spark = self.sparkline_1row(spark_history, live=True)
            else:
                spark = ' ' * bar_w
            leader = f'{leader_lpad}{rate_label}{spark}'

        vsep_cols: tuple[int, ...]
        if include_lines:
            line = f'{tokens_col}{vsep}{lines_col}{vsep_lines}{cost_col}{vsep_leader}{leader}'
            vsep_cols = (col1, col2, col3)
        else:
            line = f'{tokens_col}{vsep}{cost_col}{vsep_leader}{leader}'
            vsep_cols = (col1, col2)

        # Shed ladder fallback: drop tokens-over-time, then cost, then loc, landing on tokens sess/day (never shed).
        content_w = box_width - 3
        if _visible_width(line) > content_w:
            if include_lines:
                rung_b = f'{tokens_col}{vsep}{lines_col}{vsep_lines}{cost_col}'
                rung_b_cols: tuple[int, ...] = (col1, col2)
            else:
                rung_b = f'{tokens_col}{vsep}{cost_col}'
                rung_b_cols = (col1,)
            if _visible_width(rung_b) <= content_w:
                line, vsep_cols = rung_b, rung_b_cols
            elif include_lines and _visible_width(f'{tokens_col}{vsep}{lines_col}') <= content_w:
                line, vsep_cols = f'{tokens_col}{vsep}{lines_col}', (col1,)
            else:
                line, vsep_cols = tokens_col, ()

        min_width = tokens_base_w + 3

        return [line], vsep_cols, 0, min_width

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
        # 3-step ramp from a dim shade up to BAR_EMPTY, so fill->empty blends
        # rather than butting colour against flat grey. Which side is "dim"
        # (toward vs away from bg) depends on BG_LUM_THRESHOLD, same test as
        # the pill foreground flip in render/gradient.py.
        m = self._EMPTY_FADE_256.search(self.BAR_EMPTY)
        if m:
            n = int(m.group(1))
            # xterm greyscale index (232..255) -> luma level (8..238).
            if 8 + (n - 232) * 10 >= BG_LUM_THRESHOLD:
                return [f'\033[38;5;{min(255, n + k)}m' for k in (6, 4, 2)]
            return [f'\033[38;5;{max(232, n - k)}m' for k in (6, 4, 2)]
        m = self._EMPTY_FADE_RGB.search(self.BAR_EMPTY)
        if m:
            r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
            lum = (r * 299 + g * 587 + b * 114) // 1000
            a = 255 if lum >= BG_LUM_THRESHOLD else 0
            return [
                f'\033[38;2;{int(a + (r - a) * k)};{int(a + (g - a) * k)};'
                f'{int(a + (b - a) * k)}m'
                for k in (0.3, 0.5, 0.7)
            ]
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

    _CTX_WORD_MIN_BAR = 8  # min bar cells that must survive after the optional context-state word

    def _ctx_state_word(
        self,
        pct_soft: float,
        available: int,
        prefix_w: int,
        badge_w: int,
        color: str,
        state_labels: Sequence[str] | None,
        state_thresholds: Sequence[int],
    ) -> tuple[str, int]:
        """Build the optional context-state word segment; sheds first, returning ('', 0), when the bar would drop below `_CTX_WORD_MIN_BAR`."""
        if not state_labels:
            return '', 0
        label = context_state(pct_soft, state_labels, state_thresholds)
        label = label.ljust(max(len(s) for s in state_labels))
        word_w = len(label) + 1  # trailing space
        if available - prefix_w - word_w - 3 - badge_w < self._CTX_WORD_MIN_BAR:
            return '', 0
        return f'{color}{label}{self.R} ', word_w

    def context_line(
        self,
        ctx: ContextWindow,
        available: int = 76,
        soft_limit: int = DEFAULT_SOFT_LIMIT,
        exceeds_200k: bool = False,
        state_labels: Sequence[str] | None = None,
        state_thresholds: Sequence[int] = (),
        show_icons: bool = True,
    ) -> str:
        fill_ratio, pct_soft = _ctx_fill_ratio(ctx, soft_limit)
        total_tokens         = _ctx_used_tokens(ctx)

        badge   = f'{CLR_WARN}!200K{self.R} ' if exceeds_200k else ''
        badge_w = 6 if exceeds_200k else 0

        if fill_ratio >= 1.0:
            a = BOLD + self.risk_zone_color(total_tokens)
            # rjust each field on the plain string (pre-ANSI) so token/window/soft columns hold a stable right edge.
            secondary = ''
            if ctx.context_window_size > 0:
                pct_model = total_tokens / ctx.context_window_size * 100
                secondary = f' {a}{f"({pct_model:.0f}%)":>5}{self.R}'
            prefix = f'{a}{fmt_tok(total_tokens):>6}{self.R}{secondary} {a}{BOLD}{f"{pct_soft:.0f}%":>4}{self.R} '
            prefix_w = _visible_width(prefix)
            word_seg, word_w = self._ctx_state_word(pct_soft, available, prefix_w, badge_w, a, state_labels, state_thresholds)
            bar_w  = max(0, max(4, available - prefix_w - word_w - 3) - badge_w)
            filled = int(min(fill_ratio, 1.0) * bar_w)
            empty  = max(0, bar_w - filled - (1 if filled < bar_w else 0))
            bar    = f'{self.gradient_bar(filled, bar_w)}{self.R}{a}{BarChars.EMPTY * empty}{self.R}'
            icon = f'{a}{GLYPH_HOURGLASS}{self.R} ' if show_icons else ''
            return f'{badge}{icon}{prefix}{word_seg}{bar}'

        bar_clr = self.risk_zone_color(total_tokens)
        # rjust on plain text (pre-ANSI) keeps token/window/soft columns aligned with the over-limit branch above.
        secondary = ''
        if ctx.context_window_size > 0:
            pct_model = total_tokens / ctx.context_window_size * 100
            secondary = f' {self.DIM_GREEN}{f"({pct_model:.0f}%)":>5}{self.R}'
        prefix = f'{bar_clr}{self.R}{self.DIM_GREEN}{fmt_tok(total_tokens):>6}{self.R}{secondary} {bar_clr}{BOLD}{f"{pct_soft:.0f}%":>4}{self.R} '
        prefix_w = _visible_width(prefix)
        word_seg, word_w = self._ctx_state_word(pct_soft, available, prefix_w, badge_w, bar_clr, state_labels, state_thresholds)
        bar_w  = max(0, max(4, available - prefix_w - word_w - 3) - badge_w)
        filled = int(fill_ratio * bar_w)
        empty  = max(0, bar_w - filled - (1 if filled < bar_w else 0))
        bar    = f'{self.gradient_bar(filled, bar_w)}{self.R}{self._empty_section(empty, blend=filled > 0)}{self.R}'
        icon = f'{bar_clr}{GLYPH_HOURGLASS}{self.R} ' if show_icons else ''
        return f'{badge}{icon}{prefix}{word_seg}{bar}'

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

    def burndown_trend(
        self, used_pct: float, resets_at: int, window_minutes: int, warmup_minutes: int,
        now: float | None = None, show_icons: bool = True,
    ) -> str:
        delta = burndown_delta(used_pct, resets_at, window_minutes, warmup_minutes, now=now)
        if delta is None:
            return ''
        abs_delta = abs(delta)
        # Map delta onto the fill gradient: t=0 (green) at max under-burn,
        # t=0.5 (yellow-orange midpoint) at neutral, t=1 (red/purple) at max over-burn.
        t = max(0.0, min(1.0, 0.5 + delta / 50.0))
        colour = self.gradient.gradient_color(t)
        glyph = GLYPH_BURN_FAST if delta > 0 else GLYPH_BURN_SLOW  # colour modulation carries over/under-burn direction
        glyph_part = f'{glyph} ' if show_icons else ''
        sign  = '-' if delta < 0 else '+'
        return f'{colour}{glyph_part}{sign}{abs_delta:.1f}%{self.R}'

    def helper(self, five_hour: RateBucket, gap: int = 1, show_icons: bool = True) -> str:
        # ``gap`` is the inter-stat separator width (countdown↔pct, pct↔trend).
        # It widens to give the justified top row breathing room; the glyph→stat
        # spacing lives in the caller and is unaffected.
        sp      = ' ' * gap
        pct_clr = self.fill_colour(float(five_hour.used_percentage or 0))
        pct_str = f'{float(five_hour.used_percentage or 0):.1f}'
        try:
            if not five_hour.resets_at:
                if not five_hour.used_percentage:
                    return GLYPH_UNLIMITED
                return f'{pct_clr}{pct_str}%{self.R}{sp}{self.COMMIT}{GLYPH_UNLIMITED}'
            resets_at = datetime.fromtimestamp(five_hour.resets_at).astimezone()
            delta = resets_at - datetime.now().astimezone().replace(microsecond=0)
            if delta.total_seconds() <= 0:
                if not five_hour.used_percentage:
                    return GLYPH_UNLIMITED
                return f'{pct_clr}{pct_str}%{self.R}{sp}{self.COMMIT}{GLYPH_UNLIMITED}'
            total_s   = int(delta.total_seconds())
            h, rem    = divmod(total_s, 3600)
            m         = rem // 60
            countdown = f'(-{h}:{m:02d})'
            trend = self.burndown_trend(
                float(five_hour.used_percentage or 0),
                five_hour.resets_at,
                FIVE_HOUR_MINUTES,
                FIVE_HOUR_WARMUP_MINUTES,
                show_icons=show_icons,
            )
            trend_part = f'{sp}{trend}' if trend else ''
            return f'{self.COMMIT}{countdown}{self.R}{sp}{pct_clr}{pct_str}%{self.R}{trend_part}'
        except Exception as e:
            return f'{e.__class__.__name__}, {str(e)}'
