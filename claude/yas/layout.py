"""Layout pipeline: RowSpec, LayoutSpec, build_narrow/medium/wide, render_layout."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from yas.config import Config
from yas.constants import (
    CLR_WARN,
    DEFAULT_SOFT_LIMIT,
    GLYPH_CONFIG_WARN,
    RESET,
)
from yas.info import SessionView
from yas.info.subagents import read_last_prompt_ts
from yas.render.pill import Pill
from yas.renderer import Renderer
from yas.render.text import _visible_width
from yas.tokens import TickRecord


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
    visible_subs   = subagents.visible(time.time(), last_prompt_ts)
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
    visible_subs   = subagents.visible(time.time(), last_prompt_ts)
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
    plugins_line = r.plugins_skills(len(skills.names), skill_display, session.workspace.plugins)
    title_cap    = max(10, width - 45)
    title_w      = min(40, title_cap, max((len(n) for n, _, _ in changes), default=25))
    openspec_bars = [r.openspec_bar(name, d, t, width, title_w) for name, d, t in changes]

    line_context = r.context_line(ctx, width - 3, soft_limit)

    spec = LayoutSpec(width=width, fill=fill, session_id=session.session_id)
    rows: list[RowSpec] = []

    vsep_w   = 5
    helper_w = _visible_width(helper_text)

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

    # Elapsed section: session clock (H:MM:SS), vsep-delimited, sheds before path truncates.
    # elapsed_section_w = elapsed_content_w + 3 (1-lead vsep: ' │ ' = 3 visible).
    elapsed_content, _elapsed_cw = r.elapsed_section(elapsed)
    elapsed_section_w = 0
    if elapsed:
        _elapsed_sw = _elapsed_cw + 3
        if (width - 4) - vsep_w - _elapsed_sw - helper_w - cache_section_w - right_w >= 5:
            elapsed_section_w = _elapsed_sw

    target_w = (width - 4) - vsep_w - elapsed_section_w - helper_w - cache_section_w - right_w
    line_path = r.fit_path(session.short_pwd, git, target_w, compact_only=False)
    path_w   = _visible_width(line_path)

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
    if cache_section_w:
        path_row_cols.append(cache_div_col)    # type: ignore[arg-type]
    path_row_downs = tuple(path_row_cols)
    path_row_ups   = path_row_downs

    if pill_pct:
        rows += [
            RowSpec('top_border', downs=path_row_downs, pill=pill),
            RowSpec('content', content=middle, right_pill=right_text),
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

    tokens_downs = vsep_cols + ((spark_mark_col,) if spark_mark_col else ())
    rows.append(RowSpec('separator_dim', downs=tokens_downs))
    for lt in line_tokens:
        rows.append(RowSpec('content', content=lt))

    # First post-tokens separator threads `ups` back into the tokens vseps and
    # is drawn as the heavy "seam" marking the static->dynamic split. Only the
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

    last_prompt_ts = read_last_prompt_ts(session.session_id)
    visible_subs   = subagents.visible(time.time(), last_prompt_ts)

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
