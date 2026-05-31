"""Renderer and all section-helper methods for the statusline."""

from __future__ import annotations

import re
import time
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from statusline.borders import BorderRenderer
from statusline.constants import (
    BOLD,
    ITALIC,
    RESET,
    BarChars,
    CLR_ALERT,
    CLR_BORDER_OFF,
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
    GLYPH_CONFIG_WARN,
    GLYPH_CONTINUATION,
    GLYPH_FOLDER,
    GLYPH_HELPER,
    GLYPH_HOURGLASS,
    GLYPH_MODEL,
    GLYPH_PIE,
    GLYPH_PLUGINS,
    GLYPH_RENAMED,
    GLYPH_REPLYING,
    GLYPH_SKILLS,
    GLYPH_SUBAGENT,
    GLYPH_SUBAGENT_ROW,
    GLYPH_TASKS,
    GLYPH_THINKING,
    GLYPH_TRASH,
    ICON_COST,
    ICON_TOK_RATE,
    PILL_LEFT,
    PILL_RIGHT,
    SEVEN_DAY_MINUTES,
    SEVEN_DAY_WARMUP_MINUTES,
)
from statusline.gradient import (
    GradientEngine,
    model_key,
    paint_bg_span,
    pill_gradient_fg,
    rainbow_at,
    rainbow_step,
    _scale,
)
from statusline.git import GitInfo
from statusline.metrics import burndown_delta, subagent_avg_tpm, subagent_share
from statusline.openspec import OpenSpec
from statusline.pill import Pill
from statusline.session import ContextWindow, RateBucket, RateLimits, SessionInfo
from statusline.skills import LoadedSkills
from statusline.subagents import RunningSubagent, RunningSubagents
from statusline.tasks import Task, TaskList
from statusline.text import _middle_ellipsis, _visible_width, fmt_dur, fmt_tok
from statusline.tokens import TokenAccounting, TokenRate
from statusline.transcript import TranscriptUsage

if TYPE_CHECKING:
    from statusline.themes import ModelColors, Theme

# Runtime import of themes (the package module is always available when running
# as a package; no importlib shim needed).
from statusline.themes import CLAUDE_DARK, THEMES, ModelColors, Theme  # type: ignore[assignment]


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
            f' {self.LABEL}{self.ARROW}{BOLD}∈{self.R}'
            f' {self.BRANCH}{git.branch}{self.R}'
            f'{commit_part}{dirty}{tail}'
        )

    def path_git_compact(self, short_pwd: str, git: GitInfo) -> str:
        return (
            f'{self.ICON_PATH}  {self.PWD}{short_pwd}{self.R}'
            f' {self.LABEL}{self.ARROW}{BOLD}∈{self.R}'
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
        in_icon  = '\U0001f847 ' if in_active  else '↓ '  # 🡇+space or ↓+space (both 2 cols)
        out_icon = '\U0001f845 ' if out_active else '↑ '  # 🡅+space or ↑+space (both 2 cols)

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

    def context_line(self, ctx: ContextWindow, available: int = 76, soft_limit: int = DEFAULT_SOFT_LIMIT) -> str:
        total_tokens = ctx.total_input_tokens + ctx.total_output_tokens
        fill_ratio   = min(total_tokens / soft_limit, 1.0)
        pct_soft     = total_tokens / soft_limit * 100

        if total_tokens >= soft_limit:
            a = BOLD + self.risk_zone_color(total_tokens)
            secondary = ''
            if ctx.context_window_size > 0:
                pct_model = total_tokens / ctx.context_window_size * 100
                secondary = f' {a}({pct_model:.0f}%){self.R}'
            prefix = f'{secondary} {a}{fmt_tok(total_tokens)}{self.R} {a}{BOLD}{pct_soft:.0f}%{self.R} '
            bar_w  = max(4, available - _visible_width(prefix) - 3)
            filled = int(min(fill_ratio, 1.0) * bar_w)
            empty  = max(0, bar_w - filled - (1 if filled < bar_w else 0))
            bar    = f'{self.gradient_bar(filled, bar_w)}{self.R}{a}{BarChars.EMPTY * empty}{self.R}'
            return f'{a}{GLYPH_HOURGLASS}{self.R} {prefix}{bar}'

        bar_clr = self.risk_zone_color(total_tokens)
        secondary = ''
        if ctx.context_window_size > 0:
            pct_model = total_tokens / ctx.context_window_size * 100
            secondary = f' {self.DIM_GREEN}({pct_model:.0f}%){self.R}'
        prefix = f'{bar_clr}{self.R}{self.DIM_GREEN}{fmt_tok(total_tokens)}{self.R}{secondary} {bar_clr}{BOLD}{pct_soft:.0f}% '
        bar_w  = max(4, available - _visible_width(prefix) - 3)
        filled = int(fill_ratio * bar_w)
        empty  = max(0, bar_w - filled - (1 if filled < bar_w else 0))
        bar    = f'{self.gradient_bar(filled, bar_w)}{self.R}{self._empty_section(empty, blend=filled > 0)}{self.R}'
        return f'{bar_clr}{GLYPH_HOURGLASS}{self.R} {prefix}{bar}'

    def context_line_compact(self, ctx: ContextWindow, available: int, soft_limit: int = DEFAULT_SOFT_LIMIT) -> str:
        total_tokens = ctx.total_input_tokens + ctx.total_output_tokens
        fill_ratio   = min(total_tokens / soft_limit, 1.0)
        pct_soft     = total_tokens / soft_limit * 100

        if total_tokens >= soft_limit:
            a      = BOLD + self.risk_zone_color(total_tokens)
            prefix = f'{a}{pct_soft:.0f}%{self.R} '
            bar_w  = max(4, available - _visible_width(prefix) - 3)
            filled = int(min(fill_ratio, 1.0) * bar_w)
            empty  = max(0, bar_w - filled - (1 if filled < bar_w else 0))
            bar    = f'{self.gradient_bar(filled, bar_w)}{self.R}{a}{BarChars.EMPTY * empty}{self.R}'
            return f' {prefix}{bar}'

        bar_clr = self.risk_zone_color(total_tokens)
        prefix  = f'{bar_clr}{BOLD}{pct_soft:.0f}%{self.R} '
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
        glyph = GLYPH_BURN_FAST if delta > 0 else GLYPH_BURN_SLOW  # colour modulation carries over/under-burn direction
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
            delta = resets_at - datetime.now().astimezone().replace(microsecond=0)
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
