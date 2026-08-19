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
from yas.render.text import _ansi_byte_offset, _middle_ellipsis, _visible_width, fmt_tok, fmt_tok_fixed, strike
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


def _best_fit_cluster(
    build_cluster: Callable[[bool, bool, bool], str],
    fits: Callable[[str], bool],
) -> str:
    """Pick the richest subagent stats cluster that satisfies `fits`.

    Shared shed ladder (Decision 10, inverted) for `Renderer.subagent_row`'s
    anchored and right-aligned branches: timer + tok + loc is now the
    PROTECTED unit — start from the richest form (lines+tok+model), and the
    only rung this cluster ever sheds down to is dropping model (lines+tok
    survive). There is no model-only or empty fallback any more; loc/tok are
    never shed from here. The two call sites differ only in what "fits"
    means (slack past a fixed anchor column vs. slack alongside the front
    field), which is why `fits` is a caller-supplied predicate.
    """
    cluster = build_cluster(True, True, False)  # protected floor: tok + loc, no model
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
    """Strike an activity segment's text, leaving its leading PUA glyph plain.

    `subagent_activity` emits '<glyph> <text>'; a rule drawn across a Nerd
    Font icon renders as a mangled box, so only the part past the glyph's
    trailing space is wrapped. Call this AFTER any ellipsis truncation — the
    callers slice the raw string, and slicing an escape-bearing one would cut
    a sequence in half and let the strike bleed into the next column.

    If there's no space (e.g. the glyph got truncated down to nothing but
    itself), still never strike a leading PUA glyph — strike everything
    after it instead of falling back to striking the whole string.
    """
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
        # The cwd path is a whole unit: shown in full or omitted entirely (no
        # middle-ellipsis). show_path=False yields the branch-only rung (glyph +
        # arrow + branch) used as a width-degradation step below the path forms.
        path_part = f'{self.PWD}{short_pwd}{self.R} ' if show_path else ''
        # With icons off there is no glyph to reserve the row's usual 2-col
        # left margin -- fall back to a single literal space so the path row
        # lines up with rows that reserve their margin via a fixed-width
        # rjust instead of an icon (e.g. context_line's `fmt_tok(...):>6`).
        glyph_part = f'{GLYPH_FOLDER}  ' if show_icons else ' '

        return (
            f'{self.ICON_PATH}{glyph_part}{path_part}'
            f'{self.LABEL}{self.ARROW}{BOLD}{GLYPH_IN}{self.R}'
            f' {self.BRANCH}{git.branch}{self.R}'
            f'{commit_part}{dirty}'
        )

    def path_glyph_only(self, show_icons: bool = True) -> str:
        """Presence-glyph floor: the folder glyph alone (1 visible column).

        The overflow-safe terminal state of the path ladder — it can never
        exceed the available width or disturb the box border math.
        ``show_icons`` (default on) gates the folder glyph itself; with icons
        hidden there is nothing left to present, so the floor degrades to an
        empty string (0 visible columns).
        """
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

        # Whole-unit include/omit ladder; first candidate that fits wins.
        # full → drop commit → drop commit+dirty → compact path+branch →
        # branch-only (path omitted) → glyph-only floor. The path is never
        # middle-ellipsized: it is shown in full or dropped whole, and the
        # branch outlives the path. compact_only enters at the compact rung.
        # show_icons gates the leading folder glyph (path_git / glyph-only
        # floor); path_git_compact never carried the glyph, so it is
        # unaffected either way.
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

        # Path omitted whole, branch retained (glyph + arrow + branch).
        branch_only = self.path_git(
            short_pwd, git, show_path=False, show_commit=False, show_dirty=False,
            show_icons=show_icons,
        )
        if fits(branch_only):
            return branch_only

        # Glyph-only presence floor — 1 visible column, always within target.
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
        """Compose the elapsed-cell content and its visible width.

        When *clear_str* is non-empty (session has been /clear-ed), the cell
        shows the clear timer first — ``[GLYPH_CLEAR  ]<accent>+<clear_str>`` —
        followed by the grey right-justified session timer when *elapsed* is
        also non-empty. Passing ``elapsed=''`` with a non-empty *clear_str*
        gives the clear-only degradation tier (no session timer). ``show_icons``
        gates the leading ``GLYPH_CLEAR`` glyph (matching every other
        number-adjacent icon); the clear/session digits themselves always show,
        signed ``+`` since both are count-up clocks.

        When both *clear_str* and *elapsed* follow their defaults (empty), the
        result is byte-identical to the pre-change single-timer form:
        ``<grey><elapsed rjust 8>``.
        """
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
        """Build the 5h and (optional) 7d limit sub-sections.

        ``gap_5h`` / ``gap_7d`` set the inter-stat separator width within each
        section (default 1). The justified top row widens them toward 3 to spend
        section slack as breathing room rather than only outer padding.

        ``show_icons`` (default on) gates the 5h clock and 7d calendar glyphs
        (and their trailing gap) beside the two rate-limit percentages. Widths
        are always measured from the built strings, so callers threading
        ``helper_5h``/``helper_7d`` widths downstream adapt automatically.
        """
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
        # model_form == 'short': abbreviate to e.g. 'O5-1m (l)' via the pure
        # helpers in render/gradient.py -- keep this a display-only swap so
        # everything below (pill painting, width) is unaffected by the form.
        if model_form == 'short':
            model_name     = model_form_short(model_name)
            model_thinking = thinking_form_short(model_thinking)
        model_clr  = self.model_colour(model_name)
        pct        = self._model_bg_pct(effort_level)
        lead_glyph = GLYPH_BURN_FAST if fast_mode else GLYPH_MODEL_LIGHT

        if pct:
            anchor, shift = self._model_anchor_pair(model_name)
            cells: list[tuple[str, tuple[int, int, int] | None, bool, bool]] = []
            cells.append((' ',          anchor, False, False))   # extra left padding
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
            # Trailing space above is deliberate, matching the `pct` pill
            # branch's baked-in trailing padding cell above: without it, this
            # is the rightmost content in the row and its own budget math
            # (build_wide's `pad`) can land on exactly 0 spare columns at
            # certain widths (e.g. justify+ascii at 79-81), landing a digit
            # flush against the closing border. Baking the space in here
            # makes the no-digit-adjacent-to-border invariant hold by
            # construction rather than by relying on `pad` always having
            # slack left over.

        right_w = _visible_width(right_text)

        helper_5h, helper_7d = self._rate_helpers(rate_limits, show_icons=show_icons)
        if not include_7d:
            # Content-driven has_7d gate in _rate_helpers still applies first;
            # this just lets a caller under width pressure force it off too.
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
        # With icons off, no glyph reserves the row's usual 2-col left
        # margin -- add the same single literal space the path/tokens rows
        # fall back to, so this row's leading value lines up with them.
        return f' {line}' if (line and not show_icons) else line

    def tool_counts_row(self, counts: dict[str, tuple[int, int]], width: int, *, fill: float = 1.0) -> str:
        """Greedy-filled per-tool ``Name main/sub`` counts as a full-width line.

        Entries are ordered by combined ``(main + sub)`` total descending with an
        alphabetical tie-break, painted ``main`` bright / ``/`` dim / ``sub`` faint,
        and filled into the inner content width (``width - 4``) with a 3-space gap.
        When tool TYPES remain unshown an overflow ``+k`` is appended (k = unshown
        type count, never the call sum); the last fitted entry is dropped if needed
        so the marker is never clipped. Returns a single line with no internal ``│``.
        """
        content_w = max(1, width - 4)
        gap       = 3
        items     = sorted(counts.items(), key=lambda kv: (-(kv[1][0] + kv[1][1]), kv[0]))
        total     = len(items)
        shown: list[tuple[str, int]] = []  # (colored, plain_width)
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
            # Make room for the +k marker, dropping trailing entries as needed.
            # Each drop turns a shown type into an unshown one, so k recomputes.
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
        """Truncate + colour-tint a subagent row's description field.

        Shared by `subagent_row`'s anchored and right-aligned branches, which
        differ only in how `desc_max` (the column budget for the description)
        is derived. Returns `(sep_desc, sep_desc_w)`: the rendered
        ' · <description>' segment (empty if there's no room) and its visible
        width (0 when empty).
        """
        if not desc_text or desc_max <= 0:
            return '', 0
        if _visible_width(desc_text) > desc_max:
            desc_text = desc_text[:desc_max - 1] + '…'  # U+2026 HORIZONTAL ELLIPSIS
        desc_w = _visible_width(desc_text)
        if is_done:
            # Strikethrough the description (not the type/model/token fields)
            # to mark the task itself as finished; SGR-only, applied after
            # truncation so it never perturbs the width math above.
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
        # Tree view: a plain branch prefix ('├ ', '└ ', indented deeper) eats
        # visible columns out of the front-field budget (between the duration
        # and the agent name — see below), so the stats/activity anchors
        # shift left by the same amount to keep those columns straight across
        # mixed depths.
        # The branch elbow now renders INLINE between the duration and the
        # agent name (`<time> <elbow> <name>`, not `<elbow> <time> <name>`),
        # so it occupies columns inside `content_width`/`front_w` rather than
        # being prepended ahead of it. `content_width` therefore stays the
        # full row width — no coordinate shift here — and `stats_col`/
        # `tree_desc_col`/`tree_activity_col` (already absolute, row-start-
        # relative offsets per `layout.tree_columns`) are used as-is.
        prefix_w = _visible_width(tree_prefix)
        # Top-level agents (tree_depth 0 — direct children of the implicit,
        # never-rendered main thread) render their name BOLD; depth-1+ rows
        # (their descendants) render REGULAR — no BOLD, no ITALIC. Both
        # depths share the exact same colour (self.SKILLS while running,
        # self.CTX_DIM once finished — set where `name_style` is used below);
        # bold-vs-regular is the ONLY remaining visual distinction between a
        # top-level agent and its descendants. `tree_depth` is threaded
        # through explicitly from `layout.subagent_cells` (`tree_order_full`'s
        # own depth) rather than re-derived from the prefix string — every
        # tree row's prefix now starts with an elbow glyph regardless of
        # depth, so the glyph alone can't disambiguate. A flat (non-tree) row
        # passes NO `tree_depth` at all (``None``) and keeps its pre-existing
        # ITALIC look — that code path is untouched, only the tree view's
        # depth-1+ style changed from ITALIC to regular.
        if tree_depth == 0:
            name_style = BOLD
        elif tree_depth is None:
            name_style = ITALIC
        else:
            name_style = ''
        now         = time.time()
        status      = subagent_status(sub)
        is_done     = subagent_is_terminal(status)
        # Terminal tint for the duration/name/marker fields: green for a
        # successful finish, red for any other ending (failed, killed,
        # stopped). Only meaningful when is_done.
        done_clr    = self.safe if status == 'completed' else self.alert
        # A finished row strikes through every TEXT field (duration, name,
        # model, token/lines counts, description, activity) on top of the
        # existing grey. `str` is the identity for the running case — SGR 9
        # is zero-width either way, so none of the width math below shifts;
        # `mark` is only ever applied at paint time, never to a measured
        # string. Glyphs, elbows and padding cells are excluded: the ✓/✗
        # marker keeps its unstruck done_clr so pass-vs-fail stays readable,
        # and `strike` leaves a field's own pad spaces outside the escape.
        mark        = strike if is_done else str
        run_count   = getattr(sub, 'run_count', 0)
        is_resumed  = (not is_done) and (getattr(sub, 'resumed', False) or run_count >= 1)
        dur_s   = subagent_dur_str(sub, now)

        # Display form keeps any bracketed context-size suffix (e.g. 'sonnet[1m]')
        # from agent frontmatter; colour lookup still keys off the bare family.
        short_model = model_display(sub.model)
        model_clr   = self.model_colour(sub.model)
        ctx_clr     = self.risk_zone_color(sub.total_input)

        step      = rainbow_step()
        c_marker  = rainbow_at(step, 12)
        # Shared with layout's column-width measurement (see
        # metrics.subagent_type_label). Capped at
        # SUBAGENT_NAME_MAX so one pathological agent type can't push the
        # model/description columns off the row (the layout's cohort
        # measurements apply the same cap).
        type_text = subagent_type_label(sub)
        if _visible_width(type_text) > SUBAGENT_NAME_MAX:
            type_text = type_text[:SUBAGENT_NAME_MAX - 1] + ELLIPSIS

        target_w = content_width  # explicit content width supplied by the builder

        if twoline:
            # --- line 1: duration-first identity + right-aligned cluster (D6) ---
            # Outside tree mode there's no run-state marker here: a Done
            # agent dims every field and freezes its duration; a running one
            # keeps live colours and a ticking duration. In tree mode the
            # run-state glyph rides in the name/model separator (see
            # `mid_marker` below) rather than a leading marker column.
            # The right cluster is `· {share%}  {tok} · {model}`; under width
            # pressure the description truncates first, then the cluster sheds
            # share% and then tok. The model and the front duration always stay.
            # Tree-single mode embeds the model label directly in the front
            # field — `<time> <elbow> <name> <marker> <model>` — immediately
            # after the name, ahead of the ' · description' separator, padded
            # to the cohort's widest label (tree_model_w) when a cohort-wide
            # width is supplied, else shown unpadded (a lone row rendered
            # outside a cohort anchor). The separator between name and model
            # doubles as the run-state marker: '✓'/'✗' when finished, '↺' on
            # a resumed run, a plain '·' while running — saving the leading
            # marker column the row used to reserve. Gated on `tree_single`
            # itself (not on `tree_desc_col` being set) so a standalone
            # tree_single row still gets its model field. Outside tree_single
            # the model stays in the stats cluster (see `model_str` below).
            front_model_gap = 3 if tree_single else 0  # ' X ' marker/separator before the model field
            front_model_str = ''
            if tree_single:
                front_model_str = short_model.ljust(tree_model_w) if tree_model_w else short_model
            front_model_w = _visible_width(front_model_str)
            # dur_s is NOT fixed-width: fmt_dur grows an extra digit past 9
            # minutes/hours ('3m36s' is 5 chars, '40m23s' is 6), so measure
            # the actual string rather than assuming 5 — see subagent_dur_str.
            dur_w    = _visible_width(dur_s)
            # dur + ' ' + elbow + type + model; the elbow sits between the
            # duration and the name (`<time> <elbow> <name>`), so it's part
            # of the front-field budget rather than a separate leading
            # segment.
            front_w  = (dur_w + 1 + prefix_w + _visible_width(type_text)
                        + front_model_gap + front_model_w)

            # Tree view: pad the type field so the front (duration + elbow +
            # type + model) reaches a caller-supplied common width across the
            # whole cohort — every row's ' · description' then starts at the
            # same absolute column regardless of prefix depth or type-name
            # length.
            if tree_desc_col is not None:
                front_w = max(front_w, tree_desc_col - 1)  # -1: leading space of ' · '
                type_text = type_text.ljust(max(
                    0, front_w - dur_w - 1 - prefix_w - front_model_gap - front_model_w,
                ))

            # Tree single-line: the current-activity continuation moves onto
            # line 1 as a right-hand column. The stats/model cluster right-
            # aligns to a fixed `stats_w` (leaving a reserved activity column to
            # its right) instead of flushing to the full content width, so the
            # activity column starts at a consistent offset down the cohort.
            stats_w = target_w
            if tree_single:
                if tree_activity_col is not None:
                    # Caller-anchored: the cluster right-aligns so the ' · '
                    # separator (SUBAGENT_STATS_ACTIVITY_GAP cols) lands the
                    # activity text exactly at tree_activity_col.
                    stats_w = max(front_w + 1, min(target_w, tree_activity_col - SUBAGENT_STATS_ACTIVITY_GAP))
                else:
                    # Legacy fallback (no cohort-wide anchor supplied): reserve
                    # sized off the pre-prefix width so its absolute position
                    # is identical at every tree depth.
                    activity_reserve = min(48, content_width // 3)
                    stats_w          = max(front_w + 1, target_w - activity_reserve)

            # `fmt_tok_fixed` (3 significant figures) instead of `fmt_tok`: a
            # subagent-row-only formatter so every row's tok reading lands at
            # the SAME width regardless of mantissa digit count ('7.52M' /
            # '3.50M' / '56.8K' are all 5 chars) — never applied to the
            # session-level input/cache/output row or day totals, which keep
            # `fmt_tok`'s original 1-decimal behaviour. `rjust(5)`:
            # `fmt_tok_fixed`'s own docstring caps its output at 5 visible
            # chars ("7.52M"); below 1000 it's an unsuffixed int of at most 3
            # digits, so 5 is the guaranteed ceiling — same "measure the
            # ceiling" reasoning the old `fmt_tok().rjust(6)` relied on.
            # (The `(N.N%)` session-share suffix that used to follow this
            # field has been removed — just the bare token count now.)
            tok_field = fmt_tok_fixed(sub.total_input).rjust(5)
            # Self-scoped lines read/changed (Decision 10): each of read/
            # changed sheds independently — a subagent that read but didn't
            # write (or vice versa) shows a blank for the zero side rather
            # than a literal '0', while the OTHER side still renders. Every
            # blank occupies exactly the width the populated field would have
            # (the value's own width — no glyph any more, see below), so the
            # cluster's total width — and therefore the constant activity gap
            # after it in tree_single mode — stays deterministic regardless of
            # which fields are populated.
            # A subagent with no lines data at all (lines is None or (0, 0))
            # still reserves the field's full column width — both sides
            # blank-padded, same as the existing per-side blanking below —
            # rather than omitting the field, so cohort rows without data
            # stay aligned under sibling rows that do have data. Only the
            # width-pressure shed ladder (`build_cluster`'s `show_lines`)
            # drops the field entirely now.
            read_lc, changed_lc = lines if lines is not None else (0, 0)
            if tree_single:
                # `tree_lines_w`: the cohort's own MEASURED max fmt_tok_fixed
                # width (`layout.tree_lines_width`), not a hardcoded guess —
                # sized to what this cohort's read/changed counts actually
                # need. Falls back to 5 (fmt_tok_fixed's guaranteed max width)
                # for callers that don't supply a cohort measurement.
                lines_w = tree_lines_w if tree_lines_w is not None else 5
                read_s, changed_s = fmt_lines_pair(read_lc, changed_lc, width=lines_w, fixed=True)
            else:
                lines_w = 0
                read_s, changed_s = fmt_lines_pair(read_lc, changed_lc, fixed=True)
            # No icons here (unlike the session-level tokens/cost row's
            # GLYPH_LINES_READ/GLYPH_LINES_CHANGED pair) — a tight
            # '<read> /<written>' ratio notation instead, since this field
            # repeats once per cohort row and the icons added noise without
            # adding information the '/' doesn't already convey. A space on
            # both sides of the '/' keeps the two right-justified figures
            # visually distinct.
            read_blank_w    = _visible_width(read_s)
            changed_blank_w = _visible_width(changed_s)
            read_part    = read_s if (lines is not None and read_lc) else ' ' * read_blank_w
            changed_part = changed_s if (lines is not None and changed_lc) else ' ' * changed_blank_w
            lines_field  = f'{mark(read_part)} / {mark(changed_part)}'
            # Whether this row has ANY lines data at all — gates whether the
            # non-tree cluster reserves the field's width when there's
            # nothing to show. tree_single always reserves it (see
            # `build_cluster` below) regardless of `has_lines`.
            has_lines = lines is not None and bool(read_lc or changed_lc)
            if not tree_single:
                # Tree-single mode moves the model field into the front
                # cluster (see `front_model_str` above); the flat two-line
                # form keeps it in the stats cluster, unchanged.
                model_str = short_model.rjust(6)

            # Elbow sits between the duration and the name — '<time> <elbow>
            # <name>'. `tree_prefix` (built by `layout.subagent_cells`)
            # already carries its own per-segment bright-white/grey colour
            # codes and RESETs — active ancestry paints white, finished paths
            # grey — so it's used as-is, not force-tinted with CTX_DIM.
            elbow = tree_prefix if prefix_w else ''
            # Agent name (type_text) renders BOLD at depth 0, regular at
            # depth 1+ (`name_style`, computed above) — the style code is
            # opened right before the text and self.R (RESET) closes it
            # along with the colour (open code, then a bare RESET at the
            # end).
            # The type/name text greys via CTX_DIM when finished, same as the
            # model field below — only the ✓/✗ status marker keeps done_clr
            # (green/alert) so pass-vs-fail stays visually distinguishable.
            # The duration/elapsed field greys with the text: a finished
            # agent's timer is frozen, so keeping it in a live colour read as
            # if it were still ticking.
            if is_done:
                front_c = f'{self.CTX_DIM}{mark(dur_s)}{self.R} {elbow}{self.CTX_DIM}{name_style}{mark(type_text)}{self.R}'
            else:
                front_c = f'{self.CTX}{dur_s}{self.R} {elbow}{self.SKILLS}{name_style}{type_text}{self.R}'
            if tree_single:
                # Model sits in the front field now (see `front_model_str`
                # above), immediately after the name/type. The single-glyph
                # separator ahead of it doubles as the run-state marker —
                # '✓'/'✗' when finished, '↺' on a resumed run, a plain '·'
                # while running — always exactly one column, so the model/
                # description columns never shift with run state.
                model_field_clr = self.CTX_DIM if is_done else model_clr
                if is_done:
                    mid_marker = f'{done_clr}{subagent_marker_glyph(status)}{self.R}'
                elif is_resumed:
                    mid_marker = f'{c_marker}{BOLD}{GLYPH_SUBAGENT_RESUME}{self.R}'
                else:
                    mid_marker = f'{self.LABEL}{MIDDLE_DOT}{self.R}'
                front_c += f' {mid_marker} {model_field_clr}{mark(front_model_str)}{self.R}'

            # Cluster order (tree_single mode): '· tok · lines'. The model
            # field has already moved into the front (see above) and is no
            # longer part of this cluster. A dot-separated field precedes
            # every field after the first — see
            # `render.metrics.subagent_cluster_field_offsets`, the single
            # source of truth this mirrors for the header-label anchors.
            # Outside tree_single, the cluster still carries the model field
            # (unchanged legacy '· lines · tok · model' order).
            dot = f'{MIDDLE_DOT} '

            def build_cluster(show_lines: bool, show_tok: bool, show_model: bool = True) -> str:
                d = self.CTX_DIM if is_done else self.LABEL
                # The loc read/changed field renders in the SAME grey as the
                # activity/log column at the end of the row (`self.CTX_DIM`,
                # theme `ctx_dim`) in both run states — it used to be the only
                # white text on the row and drew the eye away from the tok
                # reading beside it. Deliberately not `tok_clr`: tok keeps its
                # risk-zone tint.
                lines_clr = self.CTX_DIM
                fields: list[str] = []
                if tree_single:
                    if show_tok:
                        tok_clr = d if is_done else ctx_clr
                        fields.append(f'{tok_clr}{mark(tok_field)}{self.R}')
                    # tree_single ALWAYS reserves the lines field's width
                    # when show_lines (width-pressure hasn't shed it) — even
                    # with no data — so sibling rows in the cohort stay
                    # column-aligned. The non-tree path below omits the
                    # field entirely when there's no data (`has_lines`).
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

            # Decide whether the stats cluster anchors at a fixed content
            # column (wide layouts) or right-aligns to the content edge. The
            # anchor only applies when even the protected floor fits within
            # the slack to the right of `stats_col`; otherwise we fall
            # through to the right-aligned path so very narrow widths stay
            # sane. In tree_single mode the model field already lives in the
            # front (not this cluster), so its own floor is unchanged (``''``,
            # same as before); in flat mode this cluster's floor is now
            # tok + loc with model dropped (see Decision 10 below).
            floor_w  = _visible_width(build_cluster(False, False, False) if tree_single
                                       else build_cluster(True, True, False))
            anchored = stats_col is not None and (stats_w - stats_col) >= floor_w

            if anchored:
                assert stats_col is not None  # narrowed by `anchored`
                avail = stats_w - stats_col  # slack to the right of the anchor
                # Pick the richest cluster that fits within the anchored slack.
                # Shed ladder (Decision 10, inverted from the original):
                # timer + tok + loc is now a PROTECTED unit that is never
                # shed — model is the only field this cluster ever drops
                # under width pressure. (type/name and the activity/log
                # column shed even earlier, ahead of model — see
                # `subagent_row`'s front-field and activity handling above/
                # below; they are not part of this cluster.)
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
                # Pick the richest cluster that fits alongside the front + a 1-col gap.
                # Same shed ladder as the anchored branch above: model is the
                # only field ever dropped from this cluster (tok + loc are
                # protected — see Decision 10 above).
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
                # Full row precedence (highest-retained first): (1) timer +
                # tokens + loc — the protected cluster, never shed; (2) type
                # (`type_text`, baked into the front field below and only
                # ever hard-capped at SUBAGENT_NAME_MAX, never width-shed);
                # (3) model (also baked into the front field in tree_single
                # mode via `front_model_str` — never width-shed here either;
                # only the FLAT/non-tree_single cluster in `build_cluster`
                # above sheds model, per Decision 10); (4) log — this
                # activity column, appended below only when `avail_act`
                # allows; (5) name (`sub.description`, rendered above as
                # `sep_desc`) — the row's genuinely elastic field, truncated
                # via `desc_max`/`stats_col` before anything else gives way.
                # `layout.tree_columns` reserves this activity column's floor
                # (`activity_floor`) ahead of the description's extra growth,
                # so (4) already outranks (5) by construction; (2)/(3) never
                # varying with width in tree_single mode trivially outranks
                # everything that does.
                # Append the current-activity column after the stats cluster.
                # The model label (and, when tree_single, the share field) is
                # now padded to a fixed width, so the cluster's own width is
                # deterministic across rows and a CONSTANT
                # SUBAGENT_STATS_ACTIVITY_GAP-col gap — rather than a variable
                # fill-to-column pad — is enough to keep the activity column
                # aligned down the cohort. The activity (tool glyph + verb, no
                # `└` continuation marker) truncates with the usual ellipsis
                # when tight. Dimmed like the old line 2.
                # The gap now carries a '·' separator (' · ' plus trailing pad
                # to the constant width) rather than bare spaces, matching the
                # design mock's 'sonnet ·   <activity>'.
                gap     = SUBAGENT_STATS_ACTIVITY_GAP  # ' · ' separator, no extra padding
                dot_clr = self.CTX_DIM if is_done else self.LABEL
                # Only append the separator + activity when the row actually
                # has room past the stats cluster — a tight side-by-side
                # column can leave less slack than the separator itself, and
                # appending unconditionally used to push the row past the
                # border. The '·' renders even when the activity itself is
                # blank (a finished row), keeping the column separator
                # continuous down the cohort.
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

            # --- line 2: activity-only continuation, no right metrics (D6) ---
            # The snippet grows with the spare width line 2 has (no right
            # cluster lives here), but never past 100 cols before truncating.
            # `target_w2`: line 2 is indented by `prefix_w` spaces below (to
            # sit under line 1's front field), so its OWN content budget is
            # `target_w` minus that indent — otherwise the indented row would
            # run `prefix_w` columns past the box.
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
                # Line 1 already carries the elbow inline (between duration
                # and name); line 2 has no elbow of its own, but indents by
                # the same width so its continuation glyph lines up under
                # line 1's front field rather than under column 0.
                return f'{line1}\n{" " * prefix_w}{line2}'
            return f'{line1}\n{line2}'

        # --- one-line collapse (narrow/medium widths): mirrors the wide/tree
        # reading order — `<time> <elbow> <name> <marker> <model> · <tok>
        # [· <activity>]` — duration on the LEFT like the tree rows, the
        # token count in a fixed column straight after the model, and the
        # activity/log as the LAST (elastic) column, filling whatever slack
        # remains when there is meaningful room (medium) and dropped
        # entirely when there isn't (narrow). No hourglass glyph ahead of
        # the token count and no trailing duration column. The run-state
        # marker rides in the name/model separator, matching the tree
        # twoline form: '✓'/'✗' when finished, '↺' on a resumed run, a
        # plain '·' while running.
        # `tree_prefix` self-colours (see the twoline branch above) — used as-is.
        elbow_n   = tree_prefix if prefix_w else ''
        dot_n_clr = self.CTX_DIM if is_done else self.LABEL
        tok_n_clr = self.CTX_DIM if is_done else ctx_clr
        tok_n     = fmt_tok_fixed(sub.total_input).rjust(5)
        tok_n_w   = 3 + 5  # ' · ' + fixed 5-wide tok field

        # Cohort alignment (the one-line counterpart of the twoline form's
        # tree_desc_col / tree_model_w columns): the name and model render as
        # fixed-width, left-justified fields sized to the cohort's widest
        # (`oneline_name_w` / `oneline_model_w`), so the marker/model/tok
        # separators land in the same column down every row. Under width
        # pressure the FIELD widths shrink — name first (down to a small
        # floor), then model — identically for every row in the cohort (the
        # arithmetic uses only cohort-wide inputs), so rows stay
        # column-aligned and individual names truncate with an ellipsis
        # rather than one long row drifting its separators.
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
            # Frozen timer and name/type both grey, same as the twoline tree
            # form above; the ✓/✗ marker below is the only field that keeps
            # done_clr, so pass-vs-fail stays readable.
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

        # Never overflow the right border: when even the tok-terminated front
        # is too wide, it truncates with a middle ellipsis before the
        # activity is considered.
        if front_n_w > target_w:
            front_n   = _middle_ellipsis(front_n, target_w)
            front_n_w = _visible_width(front_n)

        # LOC (read/write lines): opportunistic, not forced. The oneline form
        # has no reserved LOC column — unlike the twoline/tree_single form,
        # which always reserves it — so it only appears past the front
        # (already safely fitted above) when there's genuine slack, using the
        # SAME read/write pair format as the twoline form
        # (`fmt_lines_pair(..., fixed=True)`) for visual consistency. Once it
        # DOES fit, it's part of the row's rank-1 protected cluster
        # (timer + tokens + loc) — it's placed and measured BEFORE the
        # activity/log segment below, so activity (rank 4, sheds first) is
        # the one that loses out to LOC for the row's remaining slack, never
        # the other way around.
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

        # Activity/log segment: last column, running agents only, and only
        # when at least 12 columns of slack remain past the token field — so
        # narrow rows never show it and medium rows get the full leftover.
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

    def workflow_summary(
        self, run: RunningWorkflow, content_width: int, *, hidden_agents: int = 0, show_icons: bool = True,
    ) -> str:
        """Summary footer for a workflow run: ``└  N agents · M done · <tok>``.

        ``hidden_agents`` (agents beyond the per-run cap) appends ``+K hidden``.
        Token total is the run's aggregate from the per-agent transcript parse.
        ``show_icons`` (default on) gates the leading corner glyph beside the
        ``N agents`` count; the rest of the line (all number-bearing) is
        unaffected since it carries no other glyphs.
        """
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

    def tokens_cost(self, sess_in: int, sess_cache: int, sess_out: int, day_in: int, day_cache: int, day_out: int, sess_cost: float, day_cost: float, trailing_content: str = '', session_id: str = '', box_width: int = 80, fill: float = 1.0, show_day_stats: bool = True, justify: bool = False, lines: tuple[int, int] | None = None, show_icons: bool = True) -> tuple[list[str], tuple[int, ...], int, int, bool]:
        """One content line: tokens │ [lines │] cost │ [trailing_content].

        With ``show_day_stats`` (default), session and day figures merge per
        field as ``session/day`` with a paired cache parenthetical. When off,
        the row is session-only and keeps the original per-field justification.

        When ``justify`` is on (and day stats are shown), horizontal slack is
        spent as breathing room *inside* the sections — widening the two
        inter-group gaps in the tokens column and padding the cost edges, each
        capped at ``JUSTIFY_PAD_CAP`` spaces. ``min_width`` is unchanged: the
        optional padding only consumes genuine slack, so at the tight floor the
        gaps collapse to 1 and the row fits exactly as with ``justify`` off.
        The tokens and cost columns are sized to the *measured* content (floored
        at a realistic-widest budget), so the two ``│`` dividers always land on
        the rendered content's divider column — they never detach from the
        ┬/┴ elbows above/below.

        ``show_icons`` (default on) gates every per-number glyph in this row —
        the in/out token arrows, the cost icon, and the lines read/changed
        icons. When off, each icon (and its trailing gap) is simply omitted
        from the builder closures below; every width (``tokens_w``, ``cost_w``,
        ``lines_w``) is measured from the *built* string via ``_visible_width``,
        so the column/vsep math downstream adapts automatically — no separate
        width branch needed.

        ``lines``, when given, is a ``(read, changed)`` session-total pair
        rendered as a third segment between tokens and cost — but only when
        the box is wide enough (``box_width >= max(min_width_with_lines,
        LINES_SEGMENT_MIN_WIDTH)``); otherwise the segment and its ``│``
        divider are shed entirely and this method returns exactly today's
        shape. ``TOKENS_COST_MIN_WIDTH`` (the row's own existence gate,
        checked by the caller) is unaffected by this shed rule — it is
        computed from the without-segment ``min_width`` only.

        ``trailing_content`` is pre-rendered content (e.g. "skills + plugins")
        appended as a fourth, content-measured segment after cost — included
        whenever the box has room for it, *even when empty*: this segment's
        divider/border must not disappear just because there's nothing to
        show (blank-padded to the leader column's width in that case). This
        replaces the old in-row rate/sparkline leader, which is now its own
        standalone row (see ``tokens_over_time``).

        Shed ladder (highest-retained first): tokens sess/day, then loc r/w,
        then cost, then the trailing content. The richest form (everything the
        box has room for, per the existing gates above) is tried first; if IT
        overflows ``box_width``, the row falls through progressively leaner
        rungs that each drop exactly one segment in shed order (trailing
        content first, then cost, then loc) until only tokens sess/day
        remains — the protected segment that is never shed. ``vsep_cols``
        shrinks by one column per rung dropped.

        Returns ``([line], vsep_cols, 0, min_width, has_lines)``: ``vsep_cols``
        has 0-3 entries depending on which rung was used — the divider
        columns for the builder's elbow threading — the dead mark_col (the
        old 60s tick marker is gone, =0), ``min_width`` — the smallest box
        width at which this row fits without overflow, i.e. the floor of the
        surviving-minimum form (tokens sess/day alone), independent of
        whether ``lines``/cost/the trailing content end up shown at a given
        width — and ``has_lines`` — whether the loc r/w segment survived into
        the returned ``line`` (both the initial width gate AND the shed
        ladder), so the caller can anchor labels to it without re-deriving
        the same decision by sniffing the rendered content for a glyph that
        ``show_icons=False`` would hide.
        """
        day_clr = self.day_cost_colour(day_cost)
        in_active, out_active = TokenRate.recently_active(session_id)
        if show_icons:
            in_icon  = f'{ARROW_IN_ACTIVE} '  if in_active  else f'{ARROW_IN_IDLE} '   # both 2 cols
            out_icon = f'{ARROW_OUT_ACTIVE} ' if out_active else f'{ARROW_OUT_IDLE} '  # both 2 cols
        else:
            # show_icons=False: number-only, no arrow glyph. The row's left
            # margin is reserved by `sess_in`'s own rjust (below) instead of
            # an icon-shaped space -- mirrors context_line, which has no
            # icon-reservation either and relies solely on its rjust'd
            # number for the margin. Reserving *both* here would double up
            # and misalign the two rows again.
            in_icon = out_icon = ''

        # Inter-group gaps in the tokens column and the cost/leader edge pads.
        # They start at their minimums (gaps 1 space, edge pads 0) so the
        # measured widths and ``min_width`` below are the tight floor; ``justify``
        # widens them from genuine slack only (see the pad block after min_width).
        gap1 = gap2 = ' '   # ↓in/day | (cache) | ↑out/day inter-group gaps
        cost_lpad = cost_rpad = ''

        if show_day_stats:
            # Merged session/day per field; variable width, no fixed rjust (D2)
            # -- except the row's LEADING number (`sess_in`), which is
            # right-justified to `IN_W` (the same fixed width the
            # session-only rung below uses) so it shares a stable right
            # edge with row 2's context-fill number (also rjust'd, in
            # `context_line`) and has headroom to grow (e.g. 25.9K ->
            # 123.0K) without shifting every column after it or ending up
            # flush against the row's left border.
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
            # Session-only: original per-field justification (D2).
            sess_in_s    = fmt_tok(sess_in).rjust(self.IN_W)
            sess_cache_s = fmt_tok(sess_cache).rjust(self.CACHE_W)
            sess_out_s   = fmt_tok(sess_out).rjust(self.OUT_W)
            tokens_col = (f'{self.LABEL}{self.BOLDY}{in_icon}{self.R}{self.TOK}{sess_in_s}{self.R} '
                          f'{self.TOK_DIM}({sess_cache_s}){self.R}{self.LABEL} '
                          f'{self.BOLDY}{out_icon}{self.R}{self.TOK}{sess_out_s}{self.R}')
            cost_icon = f'{self.safe}{ICON_COST}{self.R}  ' if show_icons else ''
            cost_col = f'{cost_icon}{self.COST}${sess_cost:,.2f}{self.R}'

        def build_lines() -> str:
            # Mirrors the tokens column's own glyph-pair convention (icon,
            # bold value, a plain double-space gap before the next glyph
            # pair) rather than the cost column's " / " separator, since
            # read/changed are two independent counters (like in/out), not
            # a session/day pair of the same counter.
            # ``build_lines`` is only ever invoked where ``lines is not None``
            # (guarded by the caller), but mypy can't narrow a captured
            # outer-scope variable across a closure boundary — assert it here
            # so the tuple-unpack below type-checks honestly.
            assert lines is not None
            read, changed = lines
            # width=0: this is a single, non-cohort row (no cross-row
            # alignment needed) — see fmt_lines_pair for why the subagent
            # tree row can't reuse this width policy wholesale.
            read_s, changed_s = fmt_lines_pair(read, changed)
            if show_icons:
                read_icon    = f'{self.LABEL}{GLYPH_LINES_READ}  {self.R}'
                changed_icon = f'{self.LABEL}  {GLYPH_LINES_CHANGED}  {self.R}'
            else:
                # No glyphs: keep the same single inter-group gap the tokens
                # column uses (gap1's minimum) so the two counters stay
                # visually separated without a bare icon slot.
                read_icon, changed_icon = '', '  '
            return (f'{read_icon}{self.TOK}{read_s}{self.R}'
                    f'{changed_icon}{self.TOK}{changed_s}{self.R}')

        vsep_w        = 4
        vsep_leader_w = 4
        vsep_lines_w  = 4

        content_w = box_width - 3
        inner     = content_w - vsep_w  # tokens + cost budget (lines/trailing subtracted below when included)

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
        # Unpadded (pre-justify) tokens width -- this is the row's true floor:
        # tokens sess/day is the protected survivor of the shed ladder below,
        # so `min_width` is derived from THIS, not from the richest form.
        tokens_base_w = tokens_w

        # The trailing column is content-measured only, with no minimum reserve
        # of its own (unlike the old rate/spark leader) -- it either fits at its
        # full measured width or is shed entirely (see include_leader below).
        trailing_w = _visible_width(trailing_content)

        # The smallest box that holds both columns at their measured size plus
        # the tokens│cost vsep. Derived from the measured content, so it tracks
        # token/cost magnitude rather than being hardcoded.
        min_width = tokens_w + cost_w + vsep_w + 3

        # The lines segment's own measured width and the with-segment floor.
        # Included only when the box clears both this floor and the fixed
        # LINES_SEGMENT_MIN_WIDTH — never at a width where it would overflow,
        # so ``tokens_fits`` in build_wide (gated on the WITHOUT-segment
        # min_width, below) is unaffected either way.
        lines_w = _visible_width(build_lines()) if lines is not None else 0
        min_width_with_lines = min_width + lines_w + vsep_lines_w
        include_lines = lines is not None and box_width >= max(min_width_with_lines, LINES_SEGMENT_MIN_WIDTH)
        if include_lines:
            inner -= vsep_lines_w  # the lines segment's own vsep

        # The trailing segment's own gate, mirroring include_lines: only shown
        # when the box has genuine room for it at its full measured width.
        min_width_with_leader = min_width + trailing_w + vsep_leader_w
        # Included whenever the box has room -- unlike `include_lines`, this
        # is NOT gated on `trailing_content` being non-empty: the "skills +
        # plugins" section is always shown, blank-padded when there is
        # nothing to display, so its border (divider + ┬/┴ elbows + label)
        # never disappears just because no skills/plugins are loaded.
        include_leader = box_width >= min_width_with_leader
        if include_leader:
            inner -= vsep_leader_w  # the trailing segment's own vsep

        # Justify breathing room: spend genuine slack as padding *inside* the
        # sections. ``free`` is the room beyond the tight minimum (min-gap
        # content only -- the trailing segment never competes for this slack,
        # see the NOTE below). We never touch ``min_width``, so at the floor
        # ``free`` is 0, the gaps stay at 1, and the row is byte-for-byte the
        # justify-off layout. Slots fill toward their caps via an even
        # round-robin.
        # NOTE: neither the lines segment nor the trailing segment gets a slot
        # here — both are content-measured only (see w_lines/leader_w below),
        # same as tokens_col/cost_col before padding. This is deliberate, not
        # an oversight: giving them justify breathing room would make their
        # width (and therefore the divider columns) depend on `justify`, which
        # no other content-measured segment in this row does.
        cap = self.JUSTIFY_PAD_CAP
        if justify and show_day_stats:
            free = max(0, inner - tokens_w - cost_w)
            # (slot extra above its 1-space/0-space minimum, per-slot cap).
            #  gap1, gap2 sit at 1 already → extra cap is cap-1; the edge pads
            #  sit at 0 → extra cap is the full cap.
            slots = [cap - 1, cap - 1, cap, cap]  # gap1, gap2, cost_l, cost_r
            give  = [0, 0, 0, 0]
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
            # Rebuild the padded strings and grow the measured widths by the
            # injected pad so the budget split and col1/col2 follow the new
            # divider positions exactly. min_width above stays on the unpadded
            # floor.
            tokens_col = build_tokens()
            cost_col   = build_cost()
            tokens_w  += give[0] + give[1]
            cost_w    += give[2] + give[3]

        # Budgets track the (possibly padded) measured widths, so the column
        # sizing and col1/col2 always land on the rendered │.
        TOKENS_BUDGET = tokens_w
        COST_BUDGET   = cost_w

        if TOKENS_BUDGET + COST_BUDGET <= inner:
            w_middle, w_end = TOKENS_BUDGET, COST_BUDGET
        else:
            # Over budget: give each column at least its measured content, then
            # share any slack proportionally. Clamping at content (not the inflated
            # proportional share) keeps the cell sum from spilling past col1/col2.
            w_middle = max(tokens_w, inner * TOKENS_BUDGET // (TOKENS_BUDGET + COST_BUDGET))
            w_end    = max(cost_w, inner - w_middle)

        # Honest floor: never allocate a cell narrower than its own content. This
        # keeps the trailing pad >= 0 so the │ lands exactly at col1/col2.
        w_middle = max(w_middle, tokens_w)
        w_end    = max(w_end, cost_w)

        # The lines segment (when included) is content-measured only, floored
        # at its own rendered width — same "honest floor" pattern as
        # w_middle/w_end above, but it never competes for slack: it always
        # gets exactly its measured width.
        w_lines = lines_w if include_lines else 0

        # Left-justify each column to its (content-floored) width. The trailing pad
        # lands the │ at the divider column col1/col2 regardless of content.
        tokens_col += ' ' * max(0, w_middle - tokens_w)
        cost_col   += ' ' * max(0, w_end   - cost_w)

        col1 = w_middle + 5                                          # 1-indexed position of the tokens│ vsep
        if include_lines:
            col2 = col1 + vsep_w + w_lines                           # 1-indexed position of the lines│ vsep
            col_after_lines = col2 + vsep_lines_w + w_end            # 1-indexed position of the vsep_leader │
        else:
            col_after_lines = w_middle + vsep_w + w_end + 5          # 1-indexed position of the vsep_leader │ (today's shape)
        vsep = self.vsep_block(col1, box_width, fill=fill, leader=True)
        if include_lines:
            lines_col  = build_lines()
            vsep_lines = self.vsep_block(col2, box_width, fill=fill, leader=True)

        if include_leader:
            vsep_leader = self.vsep_block(col_after_lines, box_width, fill=fill, leader=True)
            leader_w    = max(0, inner - w_middle - w_lines - w_end)
            if trailing_w <= leader_w:
                leader = trailing_content + ' ' * (leader_w - trailing_w)
            elif leader_w > 0:
                cut    = _ansi_byte_offset(trailing_content, max(0, leader_w - 1))
                leader = f'{trailing_content[:cut]}{ELLIPSIS}{RESET}'
            else:
                leader = ''

        vsep_cols: tuple[int, ...]
        if include_leader:
            if include_lines:
                line = f'{tokens_col}{vsep}{lines_col}{vsep_lines}{cost_col}{vsep_leader}{leader}'
                vsep_cols = (col1, col2, col_after_lines)
            else:
                line = f'{tokens_col}{vsep}{cost_col}{vsep_leader}{leader}'
                vsep_cols = (col1, col_after_lines)
        elif include_lines:
            line = f'{tokens_col}{vsep}{lines_col}{vsep_lines}{cost_col}'
            vsep_cols = (col1, col2)
        else:
            line = f'{tokens_col}{vsep}{cost_col}'
            vsep_cols = (col1,)

        # Shed ladder (highest-retained first): tokens sess/day -> loc r/w ->
        # cost -> trailing content. The richest form built above is tried
        # first; if it overflows the box, fall through progressively leaner
        # rungs that each drop exactly one segment, in the order trailing
        # content -> cost -> loc, until we land on tokens sess/day alone,
        # which is the protected survivor and is never shed. `min_width`
        # (below) reflects THIS floor, not the richest form's.
        content_w = box_width - 3
        # Tracks whether the lines segment survives into the FINAL rung
        # actually used below -- the caller needs this to anchor the 'loc r/w'
        # and 'cost sess/day' labels correctly, and can't reliably re-derive
        # it by sniffing the rendered content for the read-glyph, since
        # `show_icons=False` omits that glyph even when the segment is
        # present (see layout.py's tok_labels build).
        has_lines_final = include_lines
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
                has_lines_final = False

        min_width = tokens_base_w + 3

        return [line], vsep_cols, 0, min_width, has_lines_final

    def tokens_over_time(self, tok_rate: int, session_id: str, box_width: int, fill: float = 1.0, show_icons: bool = True) -> str:
        """Full-width content line: rate label + live sparkline leader.

        Formerly the trailing segment of ``tokens_cost`` ("tokens over time");
        now its own standalone row so ``tokens_cost``'s trailing column is free
        for other content (e.g. "skills + plugins"). ``session_id`` empty (no
        history available) renders a blank span instead of a sparkline.
        """
        rate_icon    = f'{self.TOK_ICON}{ICON_TOK_RATE}  ' if show_icons else ''
        rate_label   = f'{rate_icon}{self.TOK}{fmt_tok(tok_rate)}{self.R}{self.LABEL} t/m{self.R}'
        rate_label_w = _visible_width(rate_label)

        bar_w = (box_width - 3) - rate_label_w
        if bar_w < 10:
            return rate_label
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
        return f'{rate_label}{spark}'

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
        # 3-step ramp going from a dim shade up to BAR_EMPTY, so the fill→empty
        # seam blends instead of butting a coloured glyph against flat grey.
        # "Dim" is nearer the terminal background, which is darker only on a dark
        # theme: darkening a pale track walks away from the background instead
        # and lands as a dark smudge against the fill. Which side the track is on
        # is BG_LUM_THRESHOLD's question, the same one the pill foreground flip in
        # render/gradient.py asks.
        m = self._EMPTY_FADE_256.search(self.BAR_EMPTY)
        if m:
            n = int(m.group(1))
            # A grey's level *is* its luma, so converting the xterm greyscale
            # index (232..255 → level 8..238) puts this branch on that same scale.
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

    # Minimum bar cells that must survive after the optional context-state word
    # is added; below this the word sheds so the bar stays legible.
    _CTX_WORD_MIN_BAR = 8

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
        """Build the optional context-state word segment (ported from Dumbometer).

        Returns ``(segment, visible_width)``. The label (Smart..Dumb) is padded
        to the widest configured label for a jitter-free left edge, tinted with
        the bar's threshold ``color``, and followed by one space. Returns
        ``('', 0)`` when disabled or when rendering it would leave fewer than
        ``_CTX_WORD_MIN_BAR`` cells for the bar (shed-first behaviour).
        """
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
            prefix_w = _visible_width(prefix)
            word_seg, word_w = self._ctx_state_word(pct_soft, available, prefix_w, badge_w, a, state_labels, state_thresholds)
            bar_w  = max(0, max(4, available - prefix_w - word_w - 3) - badge_w)
            filled = int(min(fill_ratio, 1.0) * bar_w)
            empty  = max(0, bar_w - filled - (1 if filled < bar_w else 0))
            bar    = f'{self.gradient_bar(filled, bar_w)}{self.R}{a}{BarChars.EMPTY * empty}{self.R}'
            icon = f'{a}{GLYPH_HOURGLASS}{self.R} ' if show_icons else ''
            return f'{badge}{icon}{prefix}{word_seg}{bar}'

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
