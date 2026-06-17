"""Layout pipeline: RowSpec, LayoutSpec, build_narrow/medium/wide, render_layout."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from yas.config import Config
from yas.constants import (
    _ANSI_RE,
    CLR_WARN,
    DEFAULT_SOFT_LIMIT,
    GLYPH_CONFIG_WARN,
    GLYPH_RENAMED,
    GLYPH_WF_DIVIDER,
    RESET,
    SUBAGENT_DISPLAY_CAP,
    TOKENS_COST_MIN_WIDTH,
    TWO_COL_WF_WIDTH,
    WORKFLOW_AGENT_CAP,
    WORKFLOW_RUN_CAP,
)
from yas.info import SessionView, _fmt_elapsed_clock
from yas.info.subagents import read_last_prompt_ts
from yas.render.pill import Pill
from yas.renderer import Renderer
from yas.render.text import _visible_width
from yas.tokens import TickRecord

# Characters that can start a dirty-status block in the plain-text path string.
# The block is always preceded by a single space so we search for ' ' + one of
# these. Untracked (•), modified (*), deleted (-), and renamed (GLYPH_RENAMED).
_DIRTY_CHARS = frozenset('•*-' + GLYPH_RENAMED)

# The branch-separator glyph used in path_git / path_git_compact.
_BRANCH_SEP = '∈'   # U+2208 ELEMENT OF (plain Unicode, not PUA)


def _ansi_byte_offset(ansi: str, plain_idx: int) -> int:
    """Return the byte (str index) in *ansi* that corresponds to plain-text
    position *plain_idx* (0-indexed visible character count, ANSI escapes
    excluded). Returns ``len(ansi)`` when *plain_idx* >= visible width."""
    pos = 0   # current byte position in `ansi`
    vis = 0   # visible characters counted so far
    while pos < len(ansi) and vis < plain_idx:
        m = _ANSI_RE.match(ansi, pos)
        if m:
            pos = m.end()
            continue
        pos += 1
        vis += 1
    return pos


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


def append_error_row(rows: list[RowSpec], cfg: Config, width: int, r: Renderer) -> None:
    """Append a compact yas.toml config-error row above the bottom border.

    No-op when ``cfg`` has no errors. The row is plain content (no elbows or
    dividers); the closing border's elbows shift up onto a dim separator placed
    above the row, so the box math is unchanged. Truncated to the render width
    via ``_visible_width`` so a long list of rejected knobs never breaks the box.
    """
    if not cfg.errors:
        return
    names = ', '.join(cfg.errors)
    text  = f'{GLYPH_CONFIG_WARN} yas.toml: {len(cfg.errors)} values ignored ({names})'
    avail = max(1, width - 4)  # inner content area between "│ " and " │"
    if _visible_width(text) > avail:
        text = text[:avail - 1] + '…'
    bottom = rows.pop()  # the bottom_border RowSpec
    rows.append(RowSpec('separator_dim', ups=bottom.ups))
    rows.append(RowSpec('content', content=f'{CLR_WARN}{text}{RESET}'))
    rows.append(RowSpec('bottom_border'))


def zip_columns(
    left_lines: list[str],
    right_lines: list[str],
    left_w: int,
    right_w: int,
    divider: str,
) -> list[str]:
    """Combine two rendered columns into side-by-side content rows (D3).

    Each column is rendered independently to its own content width; this zips
    them top-aligned to ``max(len(left), len(right))`` rows, padding the shorter
    column with blank rows of its own width so the divider and the right edge
    stay straight. Every combined row is ``{left} {divider} {right}`` — one pad
    space on each side of the gradient ``│`` — and spans the full inner width.
    Padding uses ``_visible_width`` so ANSI/glyph runs don't skew the columns.
    """
    height = max(len(left_lines), len(right_lines))
    rows: list[str] = []
    for i in range(height):
        left  = left_lines[i]  if i < len(left_lines)  else ''
        right = right_lines[i] if i < len(right_lines) else ''
        left  = f'{left}{" " * max(0, left_w - _visible_width(left))}'
        right = f'{right}{" " * max(0, right_w - _visible_width(right))}'
        rows.append(f'{left} {divider} {right}')
    return rows


def workflow_divider_col(width: int) -> int:
    """1-indexed visual column of the two-column workflow divider ``┊``.

    ``border_line`` draws the box ``│`` at col 1 and a lead space at col 2, so
    content begins at col 3; within the content the divider sits at index
    ``half_w + 2`` (a ``  │  `` block after the left half). Used by
    ``build_workflow_rows`` to embed the dashed bar in every row of the block
    and to colour it from the border gradient at this column. The bar floats
    free — no ``┬``/``┴`` elbows bracket it.
    """
    half_w = ((width - 4) - 5) // 2
    return 3 + half_w + 2


def build_workflow_rows(
    view: SessionView,
    width: int,
    r: Renderer,
    *,
    per_agent: bool,
    fill: float = 1.0,
) -> list[RowSpec]:
    """Content RowSpecs for the visible workflow runs (no leading separator).

    Returns [] when no run is visible. Each visible run contributes a header
    row, optionally up to ``WORKFLOW_AGENT_CAP`` per-agent rows (when
    ``per_agent`` — wide layouts only; narrow/medium collapse to header+summary),
    and a summary footer. Agents beyond the cap fold into the footer's
    ``+K hidden``; runs beyond ``WORKFLOW_RUN_CAP`` fold into a single
    ``+N more workflows`` content row.

    In two-column mode (``per_agent`` and ``width >= TWO_COL_WF_WIDTH``) the
    column divider ``┊`` (a dashed vertical, softer than the solid box ``│``)
    is embedded in *every* row of the block — header,
    paired/odd agent rows, summary and overflow — so the bar runs unbroken from
    the header down to the summary. The rows carry no internal separators, and
    the dashed bar floats free of the frame: ``build_wide`` threads no
    ``┬``/``┴`` elbow onto the separator above or the border below it.
    """
    last_prompt_ts = read_last_prompt_ts(view.session.session_id)
    runs = view.workflows.visible(time.time(), last_prompt_ts)
    if not runs:
        return []
    shown       = runs[:WORKFLOW_RUN_CAP]
    hidden_runs = len(runs) - len(shown)
    inner       = width - 4
    two_col     = per_agent and width >= TWO_COL_WF_WIDTH
    out: list[RowSpec] = []

    if two_col:
        half_w    = (inner - 5) // 2
        div_color = r.grad_at(workflow_divider_col(width) - 1, width, fill=fill)
        divider   = f'  {div_color}{GLYPH_WF_DIVIDER}{RESET}  '

        def left_only(text: str) -> str:
            # Left-half content padded to the divider, then the bar; the right
            # half is left blank for border_line to pad. Keeps the divider column
            # straight under the header, summary and overflow rows.
            return f'{text}{" " * max(0, half_w - _visible_width(text))}{divider}'

        for run in shown:
            out.append(RowSpec('content', content=left_only(r.workflow_header(run, half_w))))
            agents        = run.agents[-WORKFLOW_AGENT_CAP:]  # most recent, chronological (first_timestamp asc)
            hidden_agents = run.agent_count - len(agents)
            # Pair agents sequentially in first_timestamp order. An odd trailing
            # agent renders in the left column with a blank right half so it
            # stays inside the L/R section and the divider stays unbroken.
            for i in range(0, len(agents), 2):
                left = r.subagent_row(agents[i], half_w, twoline=False, session_inout=0)
                left = f'{left}{" " * max(0, half_w - _visible_width(left))}'
                if i + 1 < len(agents):
                    right = r.subagent_row(agents[i + 1], half_w, twoline=False, session_inout=0)
                    right = f'{right}{" " * max(0, half_w - _visible_width(right))}'
                    out.append(RowSpec('content', content=f'{left}{divider}{right}'))
                else:
                    out.append(RowSpec('content', content=f'{left}{divider}'))
            out.append(RowSpec('content', content=left_only(r.workflow_summary(run, half_w, hidden_agents=hidden_agents))))
        if hidden_runs > 0:
            out.append(RowSpec('content', content=left_only(f'{r.LABEL}+{hidden_runs} more workflows{r.R}')))
        return out

    for run in shown:
        out.append(RowSpec('content', content=r.workflow_header(run, inner)))
        hidden_agents = 0
        if per_agent:
            agents        = run.agents[-WORKFLOW_AGENT_CAP:]  # most recent, chronological (first_timestamp asc)
            hidden_agents = run.agent_count - len(agents)
            for sub in agents:
                for line in r.subagent_row(sub, inner, twoline=width > 100, session_inout=0).split('\n'):
                    out.append(RowSpec('content', content=line))
        out.append(RowSpec('content', content=r.workflow_summary(run, inner, hidden_agents=hidden_agents)))
    if hidden_runs > 0:
        out.append(RowSpec('content', content=f'{r.LABEL}+{hidden_runs} more workflows{r.R}'))
    return out


def build_narrow(
    view: SessionView,
    width: int,
    r: Renderer,
    soft_limit: int = DEFAULT_SOFT_LIMIT,
) -> LayoutSpec:
    session = view.session

    ctx          = session.context_window
    total_tokens = ctx.total_input_tokens + ctx.total_output_tokens
    fill         = min(total_tokens / soft_limit, 1.0)

    effort_for_bg = session.effort.level if session.thinking.enabled else ''
    pill_pct      = r._model_bg_pct(effort_for_bg)
    pill_anchor, pill_shift = r._model_anchor_pair(session.model_name) if pill_pct else ((0, 0, 0), (0, 0, 0))

    max_right    = max(8, width // 2)
    rate_text, right_text, right_w = r.model_right_section_compact(
        session.model_name, session.rate_limits, max_right, effort_for_bg,
    )
    line_context = r.context_line_compact(ctx, width - 3, soft_limit)

    pill: Pill | None = None
    if pill_pct:
        pill = Pill(start=width - right_w + 1, end=width, anchor=pill_anchor, shift=pill_shift, pct=pill_pct)

    tasks     = view.tasks
    subagents = view.subagents
    last_prompt_ts = read_last_prompt_ts(session.session_id)
    visible_subs   = subagents.visible(time.time(), last_prompt_ts)[-SUBAGENT_DISPLAY_CAP:]
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
    if tasks.is_visible():
        for line in r.task_row(tasks, width - 4, compact=True):
            rows.append(RowSpec('content', content=line))
        rows.append(RowSpec('separator_dim'))
    if visible_subs:
        for sub in visible_subs:
            for line in r.subagent_row(sub, width - 4, twoline=width > 100, session_inout=0).split('\n'):
                rows.append(RowSpec('content', content=line))
        rows.append(RowSpec('separator_dim'))
    wf_rows = build_workflow_rows(view, width, r, per_agent=False)
    if wf_rows:
        rows.extend(wf_rows)
        rows.append(RowSpec('separator_dim'))
    rows.append(RowSpec('content', content=line_context))
    rows.append(RowSpec('bottom_border'))
    append_error_row(rows, view.cfg, width, r)
    spec.rows = rows
    return spec


def build_medium(
    view: SessionView,
    width: int,
    r: Renderer,
    soft_limit: int = DEFAULT_SOFT_LIMIT,
) -> LayoutSpec:
    session = view.session

    ctx          = session.context_window
    total_tokens = ctx.total_input_tokens + ctx.total_output_tokens
    fill         = min(total_tokens / soft_limit, 1.0)

    effort_for_bg = session.effort.level if session.thinking.enabled else ''
    pill_pct      = r._model_bg_pct(effort_for_bg)
    pill_anchor, pill_shift = r._model_anchor_pair(session.model_name) if pill_pct else ((0,0,0), (0,0,0))

    git          = view.git
    line_context = r.context_line_compact(ctx, width - 3, soft_limit)

    max_right    = max(8, width // 2)
    rate_text, right_text, right_w = r.model_right_section_compact(
        session.model_name, session.rate_limits, max_right, effort_for_bg,
    )

    spec = LayoutSpec(width=width, fill=fill, session_id=session.session_id)

    vsep_w   = 5
    rate_w   = _visible_width(rate_text)
    target_w = (width - 4) - vsep_w - rate_w - right_w
    line_path = r.fit_path(session.short_pwd, git, target_w, compact_only=True)
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
    tasks     = view.tasks
    subagents = view.subagents
    last_prompt_ts = read_last_prompt_ts(session.session_id)
    visible_subs   = subagents.visible(time.time(), last_prompt_ts)[-SUBAGENT_DISPLAY_CAP:]
    rows: list[RowSpec] = [top_row, content_row, sep_row]
    if tasks.is_visible():
        for line in r.task_row(tasks, width - 4):
            rows.append(RowSpec('content', content=line))
        rows.append(RowSpec('separator_dim'))
    if visible_subs:
        for sub in visible_subs:
            for line in r.subagent_row(sub, width - 4, twoline=width > 100, session_inout=0).split('\n'):
                rows.append(RowSpec('content', content=line))
        rows.append(RowSpec('separator_dim'))
    wf_rows = build_workflow_rows(view, width, r, per_agent=False)
    if wf_rows:
        rows.extend(wf_rows)
        rows.append(RowSpec('separator_dim'))
    rows.append(RowSpec('content', content=line_context))
    rows.append(RowSpec('bottom_border'))
    append_error_row(rows, view.cfg, width, r)
    spec.rows = rows
    return spec


def build_wide(
    view: SessionView,
    tick: TickRecord,
    width: int,
    r: Renderer,
    soft_limit: int = DEFAULT_SOFT_LIMIT,
) -> LayoutSpec:
    session   = view.session
    usage     = view.transcript_usage
    token_log = tick.token_log
    tok_rate  = tick.tok_rate
    day_cost  = tick.day_cost
    sess_cost = view.session_cost
    subagents = view.subagents
    tasks     = view.tasks
    skills    = view.skills
    changes   = view.changes
    elapsed   = view.elapsed
    git       = view.git

    ctx          = session.context_window
    total_tokens = ctx.total_input_tokens + ctx.total_output_tokens
    fill         = min(total_tokens / soft_limit, 1.0)

    effort_for_bg = session.effort.level if session.thinking.enabled else ''
    pill_pct      = r._model_bg_pct(effort_for_bg)
    pill_anchor, pill_shift = r._model_anchor_pair(session.model_name) if pill_pct else ((0,0,0), (0,0,0))

    skill_display = ','.join(s.split(':', 1)[-1] for s in skills.names)
    session_inout = view.session_inout

    helper_5h, helper_7d, right_text, right_w = r.model_right_section(
        session.model_name, session.model_thinking, session.rate_limits,
        session.effort.level if session.thinking.enabled else '',
        fast_mode=session.fast_mode,
    )
    line_tokens, vsep_cols, _mark_col, tokens_min_w = r.tokens_cost(
        usage.billed_in, usage.cache_read, usage.out,
        token_log.day_in, token_log.day_cache_read, token_log.day_out,
        sess_cost, day_cost, tok_rate,
        session.session_id, width, fill, view.cfg.show_day_stats,
        view.cfg.justify,
    )
    # The three-segment tokens │ cost │ rate row is fixed-content-width: at the
    # bottom of the wide band (box ~80-84) it cannot hold both columns plus the
    # rate/spark leader without overflowing the box and detaching its two │ from
    # the ┬/┴ elbows. ``tokens_min_w`` is the exact content-aware floor reported
    # by tokens_cost; below it (and below the worst-case constant) we drop the row
    # and fall back to the compact context line the medium layout uses.
    tokens_fits = width >= max(tokens_min_w, TOKENS_COST_MIN_WIDTH)

    plugins_line = r.plugins_skills(len(skills.names), skill_display, session.workspace.plugins)
    title_cap    = max(10, width - 45)
    title_w      = min(40, title_cap, max((len(n) for n, _, _ in changes), default=25))
    openspec_bars = [r.openspec_bar(name, d, t, width, title_w) for name, d, t in changes]

    line_context = (
        r.context_line(ctx, width - 3, soft_limit)
        if tokens_fits else
        r.context_line_compact(ctx, width - 3, soft_limit)
    )

    spec = LayoutSpec(width=width, fill=fill, session_id=session.session_id)
    rows: list[RowSpec] = []

    vsep_w     = 5
    helper_5h_w = _visible_width(helper_5h)
    has_7d      = bool(helper_7d)
    helper_7d_w = _visible_width(helper_7d) if has_7d else 0
    helper_w    = helper_5h_w + (4 + helper_7d_w if has_7d else 0)

    # Cache countdown section: glyph + time, vsep-delimited, sheds before path truncates.
    cache_cd = view.cache_countdown
    cache_section_w = 0      # vsep_w + glyph+space+time width; 0 when shed/hidden
    cache_content   = ''     # rendered text (no vsep); empty when not shown
    if cache_cd is not None:
        _cache_txt, _cache_w = r.cache_section(*cache_cd)
        _cache_section_w = vsep_w + _cache_w
        # Width-shed: drop if path would get fewer than 5 visible chars.
        if (width - 4) - vsep_w - helper_w - _cache_section_w - right_w >= 5:
            cache_section_w = _cache_section_w
            cache_content   = _cache_txt

    # Elapsed section: session clock + optional since-/clear timer.
    # Degradation: both timers → clear-only → shed entirely (path protection outermost).
    clear_epoch = view.clear_epoch
    clear_str   = ''
    if clear_epoch is not None:
        clear_ms  = max(0.0, view.now - clear_epoch) * 1000
        clear_str = _fmt_elapsed_clock(int(clear_ms))

    elapsed_content, _elapsed_cw = r.elapsed_section(elapsed, clear_str)
    elapsed_section_w = 0
    if elapsed or clear_str:
        _sw = _elapsed_cw + 3
        if (width - 4) - vsep_w - _sw - helper_w - cache_section_w - right_w >= 5:
            elapsed_section_w = _sw
        elif clear_str:
            # Try clear-only (drop session timer)
            _co, _cw = r.elapsed_section('', clear_str)
            _sw_c = _cw + 3
            if (width - 4) - vsep_w - _sw_c - helper_w - cache_section_w - right_w >= 5:
                elapsed_content, _elapsed_cw = _co, _cw
                elapsed_section_w = _sw_c

    target_w = (width - 4) - vsep_w - elapsed_section_w - helper_w - cache_section_w - right_w
    line_path = r.fit_path(session.short_pwd, git, target_w, compact_only=False)
    path_w   = _visible_width(line_path)

    # Justify: distribute horizontal slack evenly across active top-row sections
    # (path, [elapsed], 5h, [7d], [cache], last-slot). Gate on cfg.justify and
    # total_slack > 0; fall through silently when total_slack == 0 (D3).
    total_slack = target_w - path_w
    path_extra = elapsed_extra = h5_left = h5_right = h7_left = h7_right = cache_extra = last_extra = 0
    if view.cfg.justify and total_slack > 0:
        _has_elapsed = elapsed_section_w > 0
        _has_cache   = cache_section_w > 0
        _N           = 3 + (1 if _has_elapsed else 0) + (1 if has_7d else 0) + (1 if _has_cache else 0)
        _extra_per   = total_slack // _N
        _remainder   = total_slack % _N
        _extras      = [_extra_per + (1 if i < _remainder else 0) for i in range(_N)]
        _idx         = 0
        path_extra   = _extras[_idx]
        _idx += 1
        if _has_elapsed:
            elapsed_extra = _extras[_idx]
            _idx += 1
        h5_extra = _extras[_idx]
        _idx += 1
        h5_left  = h5_extra // 2
        h5_right = h5_extra - h5_left
        if has_7d:
            h7_extra = _extras[_idx]
            _idx += 1
            # RHS has 2 more built-in spaces than LHS (sep_rate trailing=1 vs
            # explicit-space+cache_vsep-lead=3), so bias the split left by 1.
            h7_left  = (h7_extra + 2) // 2
            h7_right = h7_extra - h7_left
        if _has_cache:
            cache_extra = _extras[_idx]
            _idx += 1
        last_extra = _extras[_idx]
        if path_extra:
            # Distribute path_extra around the git block when one is present:
            # half before the ∈ separator, half after the branch/commit and
            # before the dirty-status indicator (or at the end when absent).
            # Fall back to simple append when there is no git block.
            _plain = _ANSI_RE.sub('', line_path)
            _sep_i = _plain.find(_BRANCH_SEP)
            if _sep_i != -1:
                # Locate the dirty block: ' ' + a dirty char after the sep.
                _dirty_i = -1
                for _ci in range(_sep_i + 1, len(_plain) - 1):
                    if _plain[_ci] == ' ' and _plain[_ci + 1] in _DIRTY_CHARS:
                        _dirty_i = _ci
                        break
                # Split: half before ∈, half before dirty (or at end).
                _p_left  = path_extra // 2
                _p_right = path_extra - _p_left
                # Byte offsets in the ANSI string for the two insertion points.
                _b_sep   = _ansi_byte_offset(line_path, _sep_i)
                if _dirty_i != -1:
                    # Offset of dirty section shifts by _p_left spaces we inserted.
                    _b_dirt = _ansi_byte_offset(line_path, _dirty_i)
                    line_path = (
                        line_path[:_b_sep]
                        + ' ' * _p_left
                        + line_path[_b_sep:_b_dirt]
                        + ' ' * _p_right
                        + line_path[_b_dirt:]
                    )
                else:
                    line_path = (
                        line_path[:_b_sep]
                        + ' ' * _p_left
                        + line_path[_b_sep:]
                        + ' ' * _p_right
                    )
            else:
                line_path = f'{line_path}{" " * path_extra}'
            path_w += path_extra
        if elapsed_extra:
            _e_left           = elapsed_extra // 2
            _e_right          = elapsed_extra - _e_left
            elapsed_content   = f'{" " * _e_left}{elapsed_content}{" " * _e_right}'
            elapsed_section_w += elapsed_extra

    pill: Pill | None = None
    if pill_pct:
        pill = Pill(start=width - right_w + 1, end=width, anchor=pill_anchor, shift=pill_shift, pct=pill_pct)

    path_div_col = 3 + path_w + 2
    vsep         = r.vsep_block(path_div_col, width, fill=fill, leader=True)

    if elapsed_section_w:
        elapsed_div_col = path_div_col + elapsed_section_w
        elapsed_vsep    = r.vsep_block(elapsed_div_col, width, fill=fill, leader=True, lead=1)
    else:
        elapsed_div_col = None
        elapsed_vsep    = ''

    helper_anchor = elapsed_div_col if elapsed_div_col is not None else path_div_col

    # Build the helper section from the 5h and (optional) 7d sub-sections.
    # When 7d is active, join them with a proper vsep │ that receives ┬/┴ elbows.
    # helper content starts at absolute col helper_anchor + 2 (one col for trailing
    # space of the preceding vsep block; then content at +2 after that │ col).
    padded_5h = f'{" " * h5_left}{helper_5h}{" " * h5_right}' if (h5_left or h5_right) else helper_5h
    sep_rate_col: int | None = None
    sep_rate_vsep = ''
    if has_7d:
        sep_rate_col  = helper_anchor + 2 + _visible_width(padded_5h) + 2
        sep_rate_vsep = r.vsep_block(sep_rate_col, width, fill=fill, leader=True)
    padded_7d = f'{" " * h7_left}{helper_7d}{" " * h7_right}' if (h7_left or h7_right) else helper_7d
    helper_text = f'{padded_5h}{sep_rate_vsep}{padded_7d}'
    helper_w    = _visible_width(helper_text)

    if cache_extra:
        # last_extra (= pad) lands entirely on RHS; cache vsep trailing gives 2 LHS
        # built-in spaces. Shift split so visible LHS ≈ visible RHS.
        _c_left         = min(cache_extra, max(0, (cache_extra + last_extra - 2) // 2))
        _c_right        = cache_extra - _c_left
        cache_content   = f'{" " * _c_left}{cache_content}{" " * _c_right}'
        cache_section_w += cache_extra

    cache_div_col = helper_anchor + helper_w + vsep_w if cache_section_w else None
    cache_vsep    = r.vsep_block(cache_div_col, width, fill=fill, leader=False) if cache_div_col else ''

    # Build the middle section: path | [elapsed |] helper [| cache].
    # The leading space before cache_vsep is the +1 in cache_div_col accounting.
    middle = f'{line_path}{vsep}'
    if elapsed_section_w:
        middle = f'{middle}{elapsed_content}{elapsed_vsep}'
    middle = f'{middle}{helper_text}'
    if cache_section_w:
        middle = f'{middle} {cache_vsep}{cache_content}'

    # Collect divider columns for elbow math — every │ in the content row
    # must have a matching ┬/┴ on the borders above and below.
    path_row_cols: list[int] = [path_div_col]
    if elapsed_section_w:
        path_row_cols.append(elapsed_div_col)  # type: ignore[arg-type]
    if sep_rate_col is not None:
        path_row_cols.append(sep_rate_col)
    if cache_section_w:
        path_row_cols.append(cache_div_col)    # type: ignore[arg-type]
    path_row_downs = tuple(path_row_cols)
    path_row_ups   = path_row_downs

    if pill_pct:
        rows += [
            RowSpec('top_border', downs=path_row_downs, pill=pill),
            RowSpec('content', content=f'{middle}{" " * last_extra}', right_pill=right_text),
        ]
    else:
        pad = max(1, (width - 3) - (path_w + vsep_w + elapsed_section_w + helper_w + cache_section_w + (1 if cache_section_w else 0) + right_w))
        content_full = f'{middle}{" " * pad}{right_text}'
        rows += [
            RowSpec('top_border', downs=path_row_downs),
            RowSpec('content', content=content_full),
        ]

    rows.append(RowSpec('separator_dim', ups=path_row_ups, pill=pill))
    rows.append(RowSpec('content', content=line_context))

    # Two elbows: one per vsep │ in the single tokens line. The old 60s tick
    # marker (a third elbow) was removed once the bar became a flat 60s window.
    # The row is dropped at the bottom of the wide band (box < tokens_fits floor),
    # where it cannot fit without overflow; then there are no vseps to thread, so
    # the seam carries no `ups`.
    if tokens_fits:
        rows.append(RowSpec('separator_dim', downs=vsep_cols))
        for lt in line_tokens:
            rows.append(RowSpec('content', content=lt))

    # First post-tokens separator threads `ups` back into the tokens vseps and
    # is drawn as the heavy "seam" marking the static->dynamic split. Only the
    # first one — later inter-section separators keep their normal style. When
    # nothing dynamic follows, no seam is drawn (the bottom border closes off).
    pending_ups: tuple[int, ...] = vsep_cols if tokens_fits else ()
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

    last_prompt_ts = read_last_prompt_ts(session.session_id)
    visible_subs   = subagents.visible(time.time(), last_prompt_ts)[-SUBAGENT_DISPLAY_CAP:]

    # Side-by-side composition (D2/D3/D5/D7): when the wide layout has BOTH a
    # visible checklist AND >=1 visible subagent, lay the checklist (left) and
    # the subagent cohort (right) as two columns in one bordered block. The
    # left column is capped at 45% of the inner width; the right takes the rest.
    # If the right column would be narrower than 40 cols, fall back to stacking.
    # `tail_ups` carries the divider's `┴` onto the separator/border below.
    tail_ups: tuple[int, ...] = ()
    side_by_side = False
    if tasks.is_visible() and visible_subs:
        inner             = width - 4
        task_lines_full   = r.task_row(tasks, inner)
        longest_task_line = max((_visible_width(line) for line in task_lines_full), default=0)
        left_w            = min(longest_task_line, inner * 45 // 100)
        right_w           = inner - 3 - left_w
        if right_w >= 40:
            side_by_side = True
            divider_col  = 3 + left_w + 1  # 1-indexed visual column of the │
            left_lines   = r.task_row(tasks, left_w)
            right_lines: list[str] = []
            for sub in visible_subs:
                right_lines.extend(
                    r.subagent_row(sub, right_w, twoline=True, session_inout=session_inout).split('\n')
                )
            div_color = r.grad_at(divider_col - 1, width, fill=fill)
            divider   = f'{div_color}│{RESET}'
            rows.append(RowSpec(sep_kind('separator_dim'), ups=pending_ups, downs=(divider_col,)))
            for line in zip_columns(left_lines, right_lines, left_w, right_w, divider):
                rows.append(RowSpec('content', content=line))
            pending_ups = ()
            tail_ups    = (divider_col,)

    if not side_by_side:
        if tasks.is_visible():
            rows.append(RowSpec(sep_kind('separator_dim'), ups=pending_ups))
            for line in r.task_row(tasks, width - 4):
                rows.append(RowSpec('content', content=line))
            pending_ups = ()

        if visible_subs:
            rows.append(RowSpec(sep_kind('separator_dim'), ups=pending_ups))
            for sub in visible_subs:
                for line in r.subagent_row(sub, width - 4, twoline=width > 100, session_inout=session_inout).split('\n'):
                    rows.append(RowSpec('content', content=line))
            pending_ups = ()

    # Workflow cohort: each visible run as a header / per-agent rows / summary
    # block, after the subagent cohort and task row. The leading separator
    # closes off any still-pending dividers (tokens vseps, side-by-side divider)
    # so the plain content rows below carry no elbows.
    wf_rows = build_workflow_rows(view, width, r, per_agent=True, fill=fill)
    if wf_rows:
        # Two-column workflow blocks embed a dashed column divider in every row,
        # but it floats free of the frame — no ┬/┴ elbows thread it into the
        # separator above the header or the border below the summary. The dashed
        # bar reads as an internal hint rather than splitting the box in two.
        rows.append(RowSpec(sep_kind('separator_dim'), ups=pending_ups + tail_ups))
        rows.extend(wf_rows)
        pending_ups = ()
        tail_ups    = ()

    if openspec_bars:
        rows.append(RowSpec(sep_kind('separator'), ups=pending_ups + tail_ups))
        for bar in openspec_bars:
            rows.append(RowSpec('content', content=bar))
        rows.append(RowSpec('bottom_border'))
    else:
        rows.append(RowSpec('bottom_border', ups=pending_ups + tail_ups))

    append_error_row(rows, view.cfg, width, r)
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
            lines.append(r.border_separator(spec.width, ups=row.ups, downs=row.downs, fill=spec.fill))
        elif row.kind == 'separator_seam':
            # Static->dynamic split: a full-brightness solid rule (vs the dotted-dim
            # separators between dynamic sections). Renders via the solid separator.
            lines.append(r.border_separator(spec.width, ups=row.ups, downs=row.downs, fill=spec.fill))
        elif row.kind == 'separator_dim':
            lines.append(r.border_separator_dim(spec.width, downs=row.downs, ups=row.ups, fill=spec.fill, pill=row.pill, pill_edge=row.pill_edge))
        elif row.kind == 'content':
            lines.append(r.border_line(row.content, spec.width, fill=spec.fill, bg_lead=row.bg_lead, bg_trail=row.bg_trail, pill_flush=row.pill_flush, right_pill=row.right_pill))
    return lines
