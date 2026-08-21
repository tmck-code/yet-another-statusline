"""Layout pipeline: RowSpec, LayoutSpec, build_narrow/medium/wide, render_layout."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import NamedTuple, TYPE_CHECKING

if TYPE_CHECKING:
    from yas.session import ContextWindow, SessionInfo

from yas.config import Config
from yas.constants import (
    _ANSI_RE,
    BOX_H,
    BOX_H_DASH4,
    BOX_V,
    BOX_V_DASH4,
    CLR_WARN,
    CLR_WHITE_BRT,
    DEFAULT_SOFT_LIMIT,
    ELLIPSIS,
    GLYPH_CONFIG_WARN,
    GLYPH_HOURGLASS,
    GLYPH_RENAMED,
    GLYPH_WF_DIVIDER,
    LINES_LABEL,
    NARROW_SIDE_BY_SIDE_MIN_WIDTH,
    PLAN_ONELINE_MIN_W,
    RESET,
    SUBAGENT_DESC_FLOOR,
    SUBAGENT_DISPLAY_CAP,
    SUBAGENT_NAME_MAX,
    SUBAGENT_ONELINE_MIN_W,
    SUBAGENT_RETENTION_SECONDS,
    SUBAGENT_STATS_ACTIVITY_GAP,
    subagent_is_terminal,
    subagent_status,
    SUBAGENT_TREE_PLAN_PAD,
    SUBAGENT_TREE_PLAN_WIDTH,
    TOKENS_COST_MIN_WIDTH,
    TOPROW_JUSTIFY_OUTER_CAP,
    TOOL_COUNTS_LABEL,
    TREE_PREFIX_BASE_W,
    TREE_PREFIX_STEP_W,
    TWO_COL_WF_WIDTH,
    WORKFLOW_AGENT_CAP,
    WORKFLOW_RUN_CAP,
)
from yas.info import SessionView, _fmt_elapsed_clock
from yas.info.subagents import (
    RunningSubagent,
    cap_tree_groups,
    read_last_prompt_ts,
    tree_order_full,
)
from yas.render.metrics import (
    subagent_cluster_field_offsets,
    subagent_cluster_width,
    subagent_dur_str,
    subagent_type_label,
)
from yas.render.pill import Pill
from yas.render.gradient import model_display
from yas.renderer import Renderer
from yas.render.text import _visible_width, _token_offsets, fmt_tok_fixed
from yas.tokens import TickRecord

# Dirty-status block in the plain-text path string is a space + one of these:
# untracked (•), modified (*), deleted (-), renamed (GLYPH_RENAMED).
_DIRTY_CHARS = frozenset('•*-' + GLYPH_RENAMED)

_BRANCH_SEP = '∈'   # U+2208 ELEMENT OF; branch-separator glyph in path_git


class _TopRowShed(NamedTuple):
    """Winning state from `build_wide`'s top-row shed ladder."""
    line_path:         str
    target_w:          int
    right_w:           int
    right_text:        str
    helper_5h:         str
    helper_7d:         str
    has_7d:            bool
    cache_content:     str
    cache_section_w:   int
    elapsed_content:   str
    elapsed_section_w: int


class _CtxFillPill(NamedTuple):
    """Shared preamble computed by every `build_*` tier: context fill + model pill state."""
    ctx:           'ContextWindow'
    fill:          float
    effort_for_bg: str
    pill_pct:      int
    pill_anchor:   tuple[int, int, int]
    pill_shift:    tuple[int, int, int]


def _ctx_fill_pill(session: 'SessionInfo', r: Renderer, soft_limit: int) -> _CtxFillPill:
    """Context-window fill ratio plus the model-pill anchor/shift/pct, identical across tiers."""
    ctx           = session.context_window
    total_tokens  = ctx.total_input_tokens + ctx.total_output_tokens
    fill          = min(total_tokens / soft_limit, 1.0)
    effort_for_bg = session.effort.level if session.thinking.enabled else ''
    pill_pct      = r._model_bg_pct(effort_for_bg)
    pill_anchor, pill_shift = r._model_anchor_pair(session.model_name) if pill_pct else ((0, 0, 0), (0, 0, 0))
    return _CtxFillPill(ctx, fill, effort_for_bg, pill_pct, pill_anchor, pill_shift)


def _ansi_byte_offset(ansi: str, plain_idx: int) -> int:
    """Str index in *ansi* corresponding to visible-text position *plain_idx*."""
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


@dataclass(slots=True)
class RowSpec:
    kind:       str  # 'top_border', 'bottom_border', 'separator', 'separator_dim', 'content'
    content:    str = ''
    bg_lead:    str = ''
    bg_trail:   str = ''
    pill_flush: bool = False
    ups:        tuple[int, ...] = ()
    downs:      tuple[int, ...] = ()
    pill:       Pill | None = None
    pill_edge:  str = 'bottom'
    right_pill: str = ''
    labels:     list[tuple[str, int]] = field(default_factory=list)


@dataclass(slots=True)
class LayoutSpec:
    width:      int
    fill:       float
    session_id: str
    rows:       list[RowSpec] = field(default_factory=list)


def append_error_row(rows: list[RowSpec], cfg: Config, width: int, r: Renderer) -> None:
    """Append a compact yas.toml config-error row above the bottom border. No-op if no errors."""
    if not cfg.errors:
        return
    names = ', '.join(cfg.errors)
    text  = f'{GLYPH_CONFIG_WARN} yas.toml: {len(cfg.errors)} values ignored ({names})'
    avail = max(1, width - 4)  # inner content area between "│ " and " │"
    if _visible_width(text) > avail:
        text = text[:avail - 1] + ELLIPSIS
    bottom = rows.pop()  # the bottom_border RowSpec
    rows.append(RowSpec('separator_dim', ups=bottom.ups))
    rows.append(RowSpec('content', content=f'{CLR_WARN}{text}{RESET}'))
    rows.append(RowSpec('bottom_border'))


def plan_content_width(lines: list[str]) -> int:
    """Intrinsic visible width of a rendered task checklist (ANSI-stripped, trailing blanks dropped)."""
    return max((_visible_width(_ANSI_RE.sub('', line).rstrip()) for line in lines), default=0)


def _fit_column(line: str, col_w: int) -> str:
    """Pad or truncate *line* to exactly ``col_w`` visible columns.

    A renderer's own per-field floor (e.g. task_row's numbered-prefix) can render
    1 column over col_w; left untruncated that desyncs the shared column width and
    shifts the interior divider │ for just the affected rows.
    """
    vis = _visible_width(line)
    if vis > col_w:
        cut = _ansi_byte_offset(line, col_w)
        return f'{line[:cut]}{RESET}'
    if vis < col_w:
        return f'{line}{" " * (col_w - vis)}'
    return line


def zip_columns(
    left_lines: list[str],
    right_lines: list[str],
    left_w: int,
    right_w: int,
    divider: str,
) -> list[str]:
    """Zip two independently-rendered columns into `{left} {divider} {right}` rows,
    top-aligned and padded to `max(len(left), len(right))`. Widths enforced via
    `_fit_column` so left_w/right_w are a hard contract every row agrees on.
    """
    height = max(len(left_lines), len(right_lines))
    rows: list[str] = []
    for i in range(height):
        left  = left_lines[i]  if i < len(left_lines)  else ''
        right = right_lines[i] if i < len(right_lines) else ''
        left  = _fit_column(left, left_w)
        right = _fit_column(right, right_w)
        rows.append(f'{left} {divider} {right}')
    return rows


def select_visible_cohort(
    visible_subs: list[RunningSubagent],
    cap: int,
    *,
    now: float | None = None,
) -> list[RunningSubagent]:
    """Apply retention, cascade-clear, then the display cap to a raw cohort.

    Retention: a terminal row drops once SUBAGENT_RETENTION_SECONDS have passed
    since its end_ts (a maximum, not a guarantee — the cap can evict sooner).
    Cascade clear: once a parent reaches a terminal status, every still-'running'
    descendant is forced to that status/end_ts too, so a stale child can't pin a
    finished parent's cohort open.
    Eviction: `cap_tree_groups` (whole-group, oldest-completion-first, never
    separating a live parent from a running child).
    """
    if now is None:
        now = time.time()

    visible_subs = [
        sub for sub in visible_subs
        if not subagent_is_terminal(subagent_status(sub))
        or now - sub.end_ts <= SUBAGENT_RETENTION_SECONDS
    ]

    by_id: dict[str, RunningSubagent] = {}
    for sub in visible_subs:
        if sub.agent_id:
            by_id[sub.agent_id] = sub
            by_id[sub.agent_id.removeprefix('agent-')] = sub

    def terminal_ancestor(sub: RunningSubagent) -> RunningSubagent | None:
        seen: set[int] = set()
        parent = by_id.get(sub.parent_id) if sub.parent_id else None
        while parent is not None and id(parent) not in seen:
            if subagent_is_terminal(subagent_status(parent)):
                return parent
            seen.add(id(parent))
            parent = by_id.get(parent.parent_id) if parent.parent_id else None
        return None

    for sub in visible_subs:
        if subagent_is_terminal(subagent_status(sub)):
            continue
        ancestor = terminal_ancestor(sub)
        if ancestor is None:
            continue
        try:
            sub.status  = subagent_status(ancestor)
            sub.end_ts  = ancestor.end_ts
        except AttributeError:
            pass  # `.status` isn't a slot on this build — nothing to cascade.

    return cap_tree_groups(visible_subs, cap)


def subagent_cells(
    visible_subs: list[RunningSubagent],
) -> list[tuple[RunningSubagent, str, int]]:
    """Pair each visible subagent with its box-drawing tree prefix and depth.

    Reorders parent-first via `tree_order_full` and draws a connector per node
    (including depth-0 top-level agents, branching off an implicit main-thread
    parent): one │/┊/' ' column per ancestor with following siblings, then the
    node's own elbow (└/├) and branch glyph (┬ for children, ─/┈ for a leaf).

    All runs render CLR_WHITE_BRT; only the glyph follows activity — solid
    (─/│) toward a running subagent, dashed (┈/┊) toward only-finished ones.
    Corners/junctions always stay solid. A shared column serving both an
    active and finished branch draws solid.

    Names staircase rather than sharing one column: each row is padded with ┈
    to `TREE_PREFIX_BASE_W + depth * TREE_PREFIX_STEP_W` (own depth), giving
    the classic indented-tree look. The trailing int is the node's
    `tree_order_full` depth, threaded to `Renderer.subagent_row` as
    `tree_depth` (BOLD at depth 0, ITALIC deeper) and to `tree_columns` to
    anchor description/model/stats columns despite the staircase.
    """
    cells: list[tuple[RunningSubagent, str, int]] = []
    for sub, depth, last, has_children, ancestor_continues, ancestor_active, own_active in tree_order_full(
        visible_subs,
    ):
        own_h = BOX_H if own_active else BOX_H_DASH4
        cols = ''.join(
            f'{CLR_WHITE_BRT}{(BOX_V if active else BOX_V_DASH4) if cont else " "}{RESET}'
            for cont, active in zip(ancestor_continues, ancestor_active)
        )
        elbow  = f'{CLR_WHITE_BRT}{"└" if last else "├"}{RESET}'
        branch = f'{CLR_WHITE_BRT}{"┬" if has_children else own_h}{RESET}'
        raw    = cols + elbow + branch
        # +1 reserves the trailing separator space ahead of the name.
        target_w = TREE_PREFIX_BASE_W + depth * TREE_PREFIX_STEP_W
        fill_n   = max(0, target_w - _visible_width(raw) - 1)
        fill     = f'{CLR_WHITE_BRT}{own_h * fill_n}{RESET}' if fill_n else ''
        cells.append((sub, f'{raw}{fill} ', depth))
    return cells


def tree_desc_content_width(cells: list[tuple[RunningSubagent, str, int]]) -> int:
    """Widest `sub.description` string across a tree cohort's visible rows.

    Used by `tree_columns` to size the description column to actual content
    rather than a fixed fraction of terminal width.
    """
    return max((_visible_width(sub.description or '') for sub, _, _ in cells), default=0)


def tree_columns(
    cells: list[tuple[RunningSubagent, str, int]],
    width: int,
    *,
    cluster_full_w: int = 0,
    model_w: int = 0,
) -> tuple[int, int, int]:
    """Compute the (desc_col, stats_col, activity_col) anchors for tree-single rows.

    desc_col: widest (prefix + duration + type + model) front-field across the
    cohort + gap before ' · description', so every row's description starts at
    the same column regardless of its own prefix depth/type/model width.

    Priority: description/activity is elastic and truncates first as the
    terminal narrows; the lines/share%/tok stats cluster is protected, shedding
    only once description is at its floor (SUBAGENT_DESC_FLOOR). stats_col sits
    at desc_col + 3 + min(longest actual description, available room), where
    room is computed against cluster_full_w plus a minimal activity gap.
    """
    now      = time.time()
    desc_col = 0
    desc_content_w = tree_desc_content_width(cells)
    for sub, prefix, _ in cells:
        prefix_w = _visible_width(prefix)
        # dur_s is NOT fixed-width (fmt_dur grows a digit past 9 min/hr) — measure
        # the actual rendered string, mirroring `subagent_row`'s front_w formula.
        dur_w      = _visible_width(subagent_dur_str(sub, now))
        model_gap  = 3 if model_w else 0  # ' X ' marker/separator ahead of the model field
        name_w     = min(_visible_width(subagent_type_label(sub)), SUBAGENT_NAME_MAX)
        front_w    = dur_w + 1 + name_w + model_gap + model_w  # dur + ' ' + type + marker + model
        desc_col   = max(desc_col, prefix_w + front_w + 1)  # +1: leading space of ' · '

    # Room after desc_col+3 splits between description, cluster, activity gap;
    # description gets whatever's left after the cluster + activity floor,
    # capped by its own content width.
    activity_floor = 16  # bare activity glyph + a few characters of text
    room_after_desc_col = max(0, width - desc_col - 3)
    room_for_desc        = max(0, room_after_desc_col - cluster_full_w - activity_floor)
    desc_w = min(desc_content_w, max(SUBAGENT_DESC_FLOOR, room_for_desc))
    desc_w = max(0, min(desc_w, room_after_desc_col))  # never past the row's own width
    stats_col = desc_col + 3 + desc_w

    activity_col = max(stats_col + activity_floor, stats_col + cluster_full_w + SUBAGENT_STATS_ACTIVITY_GAP)
    activity_col = min(activity_col, width)  # never past the row's target width
    # Invariant callers rely on: activity_col >= stats_col + activity_floor.
    # Pull stats_col back rather than let columns overlap in the narrow case.
    if activity_col < stats_col + activity_floor:
        stats_col = max(desc_col + 3, activity_col - activity_floor)
    return desc_col, stats_col, activity_col


def oneline_name_width(cells: list[tuple[RunningSubagent, str, int]]) -> int:
    """Widest branch-prefix + type-label run across a cohort's rows.

    Passed to `Renderer.subagent_row` as `oneline_name_w` so the one-line form
    pads every row's name field to a common width, aligning the ' · model' column.
    """
    return max(
        (_visible_width(prefix)
         + min(_visible_width(subagent_type_label(sub)), SUBAGENT_NAME_MAX)
         for sub, prefix, _ in cells),
        default=0,
    )


def tree_model_width(cells: list[tuple[RunningSubagent, str, int]]) -> int:
    """Widest model label actually present in this tree cohort (measured, not fixed).

    Padded to this width in the front cluster (`<time> <elbow> <name> <model>`)
    so every row's model column starts/ends at the same offset.
    """
    return max((_visible_width(model_display(sub.model)) for sub, _, _ in cells), default=0)


def tree_lines_width(cells: list[tuple[RunningSubagent, str, int]], per_agent: dict[str, tuple[int, int]]) -> int:
    """Widest `fmt_tok` string any cohort row's read/changed count needs.

    Sizes the Lines Read/Changed field to actual counts (fmt_tok isn't
    fixed-width) rather than its 6-char ceiling. Falls back to 1 for an all-idle
    cohort.
    """
    widths = []
    for sub, _, _ in cells:
        pair = per_agent.get(sub.jsonl_path)
        if pair is None:
            continue
        read, changed = pair
        widths.append(len(fmt_tok_fixed(read)))
        widths.append(len(fmt_tok_fixed(changed)))
    return max(widths, default=1)


def oneline_right_floor(cells: list[tuple[RunningSubagent, str, int]], now: float | None = None) -> int:
    """Untruncated content width for the narrow-tier oneline subagent column.

    Mirrors `Renderer.subagent_row`'s oneline formula
    (`<dur> <elbow> <name> <marker> <model> · <tok>`). Used by
    `build_narrow`'s plan/subagent split to give the subagent column priority
    over the plan column's item name.
    """
    if not cells:
        return 0
    if now is None:
        now = time.time()
    dur_w   = max(_visible_width(subagent_dur_str(sub, now)) for sub, _, _ in cells)
    name_w  = oneline_name_width(cells)
    model_w = tree_model_width(cells)
    # +1 dur-name space, +3 ' <marker> ', +8 ' · ' + fixed 5-wide tok field.
    return dur_w + 1 + name_w + 3 + model_w + 8


def workflow_divider_col(width: int) -> int:
    """1-indexed visual column of the two-column workflow divider ┊.

    Content begins at col 3 (border │ at 1, lead space at 2); divider sits at
    `half_w + 2`. Used by `build_workflow_rows` to colour the bar from the
    border gradient at this column; it floats free with no ┬/┴ elbows.
    """
    half_w = ((width - 4) - 5) // 2
    return 3 + half_w + 2


def _append_subagent_cohort_rows(
    rows:  list[RowSpec],
    r:     Renderer,
    visible_subs: list[RunningSubagent],
    width: int,
) -> None:
    """Oneline subagent cohort stack shared by `build_narrow`'s fallback branch and `build_medium`."""
    cells   = subagent_cells(visible_subs)
    name_w  = oneline_name_width(cells)
    model_w = tree_model_width(cells)
    for sub, prefix, depth in cells:
        for line in r.subagent_row(sub, width - 4, twoline=width > 100, session_inout=0,
                                   stats_col=100 if width >= 125 else None,
                                   tree_prefix=prefix, tree_depth=depth, oneline_name_w=name_w,
                                   oneline_model_w=model_w).split('\n'):
            rows.append(RowSpec('content', content=line))
    rows.append(RowSpec('separator_dim'))


def build_workflow_rows(
    view: SessionView,
    width: int,
    r: Renderer,
    *,
    per_agent: bool,
    fill: float = 1.0,
) -> list[RowSpec]:
    """Content RowSpecs for the visible workflow runs (no leading separator).

    Returns [] when no run is visible. Each run contributes a header row,
    optionally up to WORKFLOW_AGENT_CAP per-agent rows (per_agent — wide
    layouts only), and a summary footer. Agents beyond the cap fold into the
    footer's `+K hidden`; runs beyond WORKFLOW_RUN_CAP fold into one
    `+N more workflows` row.

    In two-column mode (per_agent and width >= TWO_COL_WF_WIDTH) the dashed
    divider ┊ is embedded in every row so the bar runs unbroken; it floats
    free of the frame with no ┬/┴ elbow.
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
            # Pad left-half content to the divider column; right half left blank.
            return f'{text}{" " * max(0, half_w - _visible_width(text))}{divider}'

        for run in shown:
            out.append(RowSpec('content', content=left_only(r.workflow_header(run, half_w))))
            agents        = run.agents[-WORKFLOW_AGENT_CAP:]  # most recent, chronological
            hidden_agents = run.agent_count - len(agents)
            # Pair agents column-major: left = agents[:ceil(n/2)], right = rest.
            # An odd trailing agent renders in the left column, right half blank.
            left_count   = (len(agents) + 1) // 2  # ceil: left column gets the extra agent
            left_agents  = agents[:left_count]
            right_agents = agents[left_count:]
            for i in range(len(left_agents)):
                left_raw = r.subagent_row(left_agents[i], half_w, twoline=True, session_inout=0)
                left_lines = [f'{ln}{" " * max(0, half_w - _visible_width(ln))}' for ln in left_raw.split('\n')]
                if i < len(right_agents):
                    right_raw = r.subagent_row(right_agents[i], half_w, twoline=True, session_inout=0)
                    right_lines = [f'{ln}{" " * max(0, half_w - _visible_width(ln))}' for ln in right_raw.split('\n')]
                else:
                    right_lines = [' ' * half_w] * len(left_lines)
                for j in range(len(left_lines)):
                    out.append(RowSpec('content', content=f'{left_lines[j]}{divider}{right_lines[j]}'))
            out.append(RowSpec('content', content=left_only(r.workflow_summary(run, half_w, hidden_agents=hidden_agents, show_icons=view.cfg.show_icons))))
        if hidden_runs > 0:
            out.append(RowSpec('content', content=left_only(f'{r.LABEL}+{hidden_runs} more workflows{r.R}')))
        return out

    for run in shown:
        out.append(RowSpec('content', content=r.workflow_header(run, inner)))
        hidden_agents = 0
        if per_agent:
            agents        = run.agents[-WORKFLOW_AGENT_CAP:]  # most recent, chronological
            hidden_agents = run.agent_count - len(agents)
            for sub in agents:
                for line in r.subagent_row(sub, inner, twoline=width > 100, session_inout=0).split('\n'):
                    out.append(RowSpec('content', content=line))
        out.append(RowSpec('content', content=r.workflow_summary(run, inner, hidden_agents=hidden_agents, show_icons=view.cfg.show_icons)))
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
    ctx, fill, effort_for_bg, pill_pct, pill_anchor, pill_shift = _ctx_fill_pill(session, r, soft_limit)

    max_right    = max(8, width // 2)
    rate_text, right_text, right_w = r.model_right_section_compact(
        session.model_name, session.rate_limits, max_right, effort_for_bg,
        show_icons=view.cfg.show_icons,
    )
    line_context = r.context_line_compact(ctx, width - 3, soft_limit)

    pill: Pill | None = None
    if pill_pct:
        pill = Pill(start=width - right_w + 1, end=width, anchor=pill_anchor, shift=pill_shift, pct=pill_pct)

    tasks     = view.tasks
    subagents = view.subagents
    last_prompt_ts = read_last_prompt_ts(session.session_id)
    visible_subs   = subagents.visible(time.time(), last_prompt_ts)
    visible_subs = select_visible_cohort(visible_subs, SUBAGENT_DISPLAY_CAP)
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
    # Plan + subagent side-by-side (narrow tier). Cross-column shed order:
    # subagent column gets its untruncated floor first, so the plan column's
    # item name is what shrinks under pressure.
    side_by_side = False
    tail_ups: tuple[int, ...] = ()
    if tasks.is_visible() and visible_subs:
        inner = width - 4
        avail = inner - 3  # minus the '  │  '-style one-space-each-side divider
        cells = subagent_cells(visible_subs)
        right_floor = oneline_right_floor(cells)
        if width >= NARROW_SIDE_BY_SIDE_MIN_WIDTH:
            side_by_side = True
            right_w = min(right_floor, avail - PLAN_ONELINE_MIN_W)
            right_w = max(right_w, SUBAGENT_ONELINE_MIN_W)
            left_w  = avail - right_w
            divider_col = 3 + left_w + 1  # 1-indexed visual column of the │
            left_lines  = r.task_row(tasks, left_w)
            name_w  = oneline_name_width(cells)
            model_w = tree_model_width(cells)
            right_lines = [
                r.subagent_row(sub, right_w, twoline=False, session_inout=0,
                                tree_prefix=prefix, tree_depth=depth, oneline_name_w=name_w,
                                oneline_model_w=model_w)
                for sub, prefix, depth in cells
            ]
            div_color = r.grad_at(divider_col - 1, width, fill=fill)
            divider   = f'{div_color}{BOX_V}{RESET}'
            rows.append(RowSpec('separator_dim', downs=(divider_col,)))
            for line in zip_columns(left_lines, right_lines, left_w, right_w, divider):
                rows.append(RowSpec('content', content=line))
            tail_ups = (divider_col,)

    if not side_by_side:
        if tasks.is_visible():
            for line in r.task_row(tasks, width - 4, compact=True):
                rows.append(RowSpec('content', content=line))
            rows.append(RowSpec('separator_dim'))
        if visible_subs:
            _append_subagent_cohort_rows(rows, r, visible_subs, width)
    wf_rows = build_workflow_rows(view, width, r, per_agent=False)
    if wf_rows:
        rows.extend(wf_rows)
        rows.append(RowSpec('separator_dim', ups=tail_ups))
        tail_ups = ()
    if tail_ups:
        # No workflow rows to close the divider's elbow: fold the closing ┴
        # in via a bare separator_dim (mirrors build_wide's pending_ups).
        rows.append(RowSpec('separator_dim', ups=tail_ups))
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
    ctx, fill, effort_for_bg, pill_pct, pill_anchor, pill_shift = _ctx_fill_pill(session, r, soft_limit)

    git          = view.git
    line_context = r.context_line_compact(ctx, width - 3, soft_limit)

    max_right    = max(8, width // 2)
    rate_text, right_text, right_w = r.model_right_section_compact(
        session.model_name, session.rate_limits, max_right, effort_for_bg,
        show_icons=view.cfg.show_icons,
    )

    spec = LayoutSpec(width=width, fill=fill, session_id=session.session_id)

    vsep_w   = 5
    rate_w   = _visible_width(rate_text)
    target_w = (width - 4) - vsep_w - rate_w - right_w
    line_path = r.fit_path(
        session.short_pwd, git, target_w, compact_only=True,
        show_icons=view.cfg.show_icons,
    )
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
    visible_subs = select_visible_cohort(visible_subs, SUBAGENT_DISPLAY_CAP)
    rows: list[RowSpec] = [top_row, content_row, sep_row]
    if tasks.is_visible():
        for line in r.task_row(tasks, width - 4):
            rows.append(RowSpec('content', content=line))
        rows.append(RowSpec('separator_dim'))
    if visible_subs:
        _append_subagent_cohort_rows(rows, r, visible_subs, width)
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

    ctx, fill, effort_for_bg, pill_pct, pill_anchor, pill_shift = _ctx_fill_pill(session, r, soft_limit)

    skill_display = ','.join(s.split(':', 1)[-1] for s in skills.names)
    session_inout = view.session_inout

    # `view.tool_counts` forces a transcript scan on every wide render (feeds
    # the session-total lines read/changed segment into tokens_cost below).
    line_tokens, vsep_cols, _mark_col, tokens_min_w = r.tokens_cost(
        usage.billed_in, usage.cache_read, usage.out,
        token_log.day_in, token_log.day_cache_read, token_log.day_out,
        sess_cost, day_cost, tok_rate,
        session.session_id, width, fill, view.cfg.show_day_stats,
        view.cfg.justify,
        lines=(view.tool_counts.lines_read, view.tool_counts.lines_changed),
        show_icons=view.cfg.show_icons,
    )
    # Floor for full-width display of `tokens │ cost │ rate` row; below it,
    # drop the row and fall back to the compact context line.
    tokens_fits = width >= max(tokens_min_w, TOKENS_COST_MIN_WIDTH)

    plugins_line = r.plugins_skills(len(skills.names), skill_display, session.workspace.plugins, show_icons=view.cfg.show_icons)
    # border_line pads to width - 3 but never truncates; clip a long plugin list here.
    plugins_avail = width - 3
    if _visible_width(plugins_line) > plugins_avail:
        cut = _ansi_byte_offset(plugins_line, plugins_avail - 1)
        plugins_line = f'{plugins_line[:cut]}{ELLIPSIS}{RESET}'
    title_cap    = max(10, width - 45)
    title_w      = min(40, title_cap, max((len(n) for n, _, _ in changes), default=25))
    openspec_bars = [r.openspec_bar(name, d, t, width, title_w) for name, d, t in changes]

    state_labels = view.cfg.context_labels if view.cfg.context_state else None
    line_context = (
        r.context_line(
            ctx, width - 3, soft_limit, state_labels=state_labels,
            state_thresholds=view.cfg.context_thresholds, show_icons=view.cfg.show_icons,
        )
        if tokens_fits else
        r.context_line_compact(ctx, width - 3, soft_limit)
    )

    spec = LayoutSpec(width=width, fill=fill, session_id=session.session_id)
    rows: list[RowSpec] = []

    vsep_w = 5

    # Top-row shed order as width shrinks: commit -> changes -> 7d -> timer ->
    # dir -> branch -> cache -> 5h. Branch/dir/changes/commit live inside
    # `Renderer.fit_path`'s own include/omit ladder; driven here in two phases
    # so 7d/timer shed before the path shrinks past dir-full (phase 1), then
    # the path's own compact -> branch-only -> glyph-only rungs (phase 2).
    # Cache and the model pill are the last resorts.
    cache_cd    = view.cache_countdown
    clear_epoch = view.clear_epoch
    clear_str   = ''
    if clear_epoch is not None:
        clear_ms  = max(0.0, view.now - clear_epoch) * 1000
        clear_str = _fmt_elapsed_clock(int(clear_ms))

    include_7d = True          # priority 6 — shed before the path shrinks
    timer_mode = 'full' if (elapsed or clear_str) else 'none'  # priority 5
    cache_on   = cache_cd is not None                          # priority 2
    model_form = 'full'                                        # priority 1

    def _resolve_toprow_shed() -> _TopRowShed:
        # Closes over the enclosing build_wide scope; include_7d_/timer_mode_/
        # cache_on_/model_form_ are the mutable shed state, local to this call.
        include_7d_ = include_7d
        timer_mode_ = timer_mode
        cache_on_   = cache_on
        model_form_ = model_form

        while True:
            helper_5h, helper_7d, right_text, right_w = r.model_right_section(
                session.model_name, session.model_thinking, session.rate_limits,
                session.effort.level if session.thinking.enabled else '',
                fast_mode=session.fast_mode, show_icons=view.cfg.show_icons,
                include_7d=include_7d_, model_form=model_form_,
            )
            helper_5h_w = _visible_width(helper_5h)
            has_7d      = bool(helper_7d)
            helper_7d_w = _visible_width(helper_7d) if has_7d else 0
            helper_w    = helper_5h_w + (4 + helper_7d_w if has_7d else 0)

            cache_content   = ''
            cache_section_w = 0
            if cache_on_ and cache_cd is not None:
                _cache_txt, _cache_w = r.cache_section(*cache_cd, show_icons=view.cfg.show_icons)
                cache_content   = _cache_txt
                cache_section_w = vsep_w + _cache_w

            if timer_mode_ == 'full':
                elapsed_content, _elapsed_cw = r.elapsed_section(elapsed, clear_str, show_icons=view.cfg.show_icons)
            elif timer_mode_ == 'clearonly':
                elapsed_content, _elapsed_cw = r.elapsed_section('', clear_str, show_icons=view.cfg.show_icons)
            else:
                elapsed_content, _elapsed_cw = '', 0
            elapsed_section_w = (_elapsed_cw + 3) if timer_mode_ != 'none' else 0

            target_w = (width - 4) - vsep_w - elapsed_section_w - helper_w - cache_section_w - right_w

            # Phase 1: try the path with dir still at full width (commit, then
            # commit+changes shed within this phase; dir itself untouched).
            _dirfull_candidates = (
                r.path_git(session.short_pwd, git, show_icons=view.cfg.show_icons),
                r.path_git(session.short_pwd, git, show_commit=False, show_icons=view.cfg.show_icons),
                r.path_git(session.short_pwd, git, show_commit=False, show_dirty=False, show_icons=view.cfg.show_icons),
            )
            _dirfull_fit = next((c for c in _dirfull_candidates if _visible_width(c) <= target_w), None)
            if _dirfull_fit is not None:
                return _TopRowShed(
                    _dirfull_fit, target_w, right_w, right_text, helper_5h, helper_7d,
                    has_7d, cache_content, cache_section_w, elapsed_content, elapsed_section_w,
                )

            # Doesn't fit even with commit+changes dropped: shed 7d, then the
            # timer, before letting the path itself shrink.
            if include_7d_:
                include_7d_ = False
                continue
            if timer_mode_ == 'full':
                timer_mode_ = 'clearonly' if clear_str else 'none'
                continue
            if timer_mode_ == 'clearonly':
                timer_mode_ = 'none'
                continue

            # 7d and the timer are both gone; the path now degrades through its
            # own compact -> branch-only -> glyph-only ladder.
            _compact_path = r.fit_path(
                session.short_pwd, git, target_w, compact_only=True,
                show_icons=view.cfg.show_icons,
            )
            if _visible_width(_compact_path) <= target_w:
                return _TopRowShed(
                    _compact_path, target_w, right_w, right_text, helper_5h, helper_7d,
                    has_7d, cache_content, cache_section_w, elapsed_content, elapsed_section_w,
                )

            # Even the glyph-only floor overflows: shed cache, then narrow the
            # model pill. The five-hour stats themselves are never dropped.
            if cache_on_:
                cache_on_ = False
                continue
            if model_form_ == 'full':
                model_form_ = 'short'
                continue
            # Nothing left to shed: accept the glyph-only-floor overflow.
            return _TopRowShed(
                _compact_path, target_w, right_w, right_text, helper_5h, helper_7d,
                has_7d, cache_content, cache_section_w, elapsed_content, elapsed_section_w,
            )

    _shed = _resolve_toprow_shed()
    line_path         = _shed.line_path
    target_w          = _shed.target_w
    right_w           = _shed.right_w
    right_text        = _shed.right_text
    helper_5h         = _shed.helper_5h
    helper_7d         = _shed.helper_7d
    has_7d            = _shed.has_7d
    cache_content     = _shed.cache_content
    cache_section_w   = _shed.cache_section_w
    elapsed_content   = _shed.elapsed_content
    elapsed_section_w = _shed.elapsed_section_w

    path_w = _visible_width(line_path)

    # Justify: distribute horizontal slack evenly across active top-row sections
    # (path, [elapsed], 5h, [7d], [cache], last-slot). No-op when total_slack == 0.
    total_slack = target_w - path_w
    path_extra = elapsed_extra = h5_left = h5_right = h7_left = h7_right = cache_extra = last_extra = 0
    # Computed unconditionally: also needed below for the baked-in-padding
    # rebalance, which must run even when total_slack <= 0.
    _has_elapsed = elapsed_section_w > 0
    if view.cfg.justify and total_slack > 0:
        _has_cache   = cache_section_w > 0
        _N           = 3 + (1 if _has_elapsed else 0) + (1 if has_7d else 0) + (1 if _has_cache else 0)
        _extra_per   = total_slack // _N
        _remainder   = total_slack % _N
        # Cap every slot but the last at TOPROW_JUSTIFY_OUTER_CAP (see its
        # docstring); overflow rolls forward into the last slot (`last_extra`)
        # so at most one uncapped blank run appears in this row.
        _extras      = []
        _rollover    = 0
        for i in range(_N):
            _share = _extra_per + (1 if i < _remainder else 0) + _rollover
            if i < _N - 1:
                _capped   = min(TOPROW_JUSTIFY_OUTER_CAP, _share)
                _rollover = _share - _capped
                _extras.append(_capped)
            else:
                _extras.append(_share)  # last slot: uncapped, absorbs all rollover
        _idx         = 0
        path_extra   = _extras[_idx]
        _idx += 1
        if _has_elapsed:
            elapsed_extra = _extras[_idx]
            _idx += 1
        # Spend each helper section's slack as inter-stat breathing room first
        # (separators widen from 1 toward a 3-char cap), then centre the rest
        # as outer padding; section total width is unchanged, so divider
        # columns below are unaffected. 5h has two separators, 7d has one.
        h5_extra = _extras[_idx]
        _idx += 1
        gap_5h   = 1 + min(2, h5_extra // 2)   # ≤3; both 5h separators at this width
        h5_inner = 2 * (gap_5h - 1)
        h5_outer = h5_extra - h5_inner
        h5_left  = h5_outer // 2
        h5_right = h5_outer - h5_left
        gap_7d   = 1
        if has_7d:
            h7_extra = _extras[_idx]
            _idx += 1
            gap_7d   = 1 + min(2, h7_extra)    # ≤3; the single 7d separator
            h7_inner = gap_7d - 1
            h7_outer = h7_extra - h7_inner
            # RHS has 2 more built-in spaces than LHS, so bias the split left by 1.
            h7_left  = (h7_outer + 2) // 2
            h7_right = h7_outer - h7_left
        if gap_5h != 1 or gap_7d != 1:
            # `_rate_helpers` computes both helpers regardless of `include_7d`;
            # only accept the widened helper_7d when 7d is still active, else a
            # dropped 7d section would leak back in un-padded.
            new_helper_5h, new_helper_7d = r._rate_helpers(
                session.rate_limits, gap_5h, gap_7d, show_icons=view.cfg.show_icons,
            )
            helper_5h = new_helper_5h
            if has_7d:
                helper_7d = new_helper_7d
        if _has_cache:
            cache_extra = _extras[_idx]
            _idx += 1
        last_extra = _extras[_idx]
        if path_extra:
            # Distribute path_extra around the git block: half before ∈, half
            # before the dirty indicator (or at the end). Simple append if no git block.
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
    if view.cfg.justify and _has_elapsed:
        # elapsed_content may carry asymmetric leading padding baked in by
        # elapsed_section's fixed-width rjust. Strip it and fold it back into
        # the slack pool before splitting so total whitespace balances.
        # Runs independent of total_slack > 0: a sibling section can consume
        # all slack while this cell's baked-in asymmetry still needs correcting.
        _plain_e    = _ANSI_RE.sub('', elapsed_content)
        _baked_left = len(_plain_e) - len(_plain_e.lstrip(' '))
        if _baked_left:
            _b_end          = _ansi_byte_offset(elapsed_content, _baked_left)
            elapsed_content = elapsed_content[:_b_end].rstrip(' ') + elapsed_content[_b_end:]
        _total_pad = _baked_left + elapsed_extra
        if _total_pad:
            _e_left           = _total_pad // 2
            _e_right          = _total_pad - _e_left
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

    # Helper section: 5h + optional 7d, joined by a vsep │ (elbowed) when 7d
    # is active. Content starts at helper_anchor + 2.
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
        # last_extra lands entirely on RHS; cache vsep trailing gives 2 LHS
        # built-in spaces. Shift split so visible LHS ≈ visible RHS.
        _c_left         = min(cache_extra, max(0, (cache_extra + last_extra - 2) // 2))
        _c_right        = cache_extra - _c_left
        cache_content   = f'{" " * _c_left}{cache_content}{" " * _c_right}'
        cache_section_w += cache_extra

    cache_div_col = helper_anchor + helper_w + vsep_w if cache_section_w else None
    cache_vsep    = r.vsep_block(cache_div_col, width, fill=fill, leader=False) if cache_div_col else ''

    # middle section: path | [elapsed |] helper [| cache].
    middle = f'{line_path}{vsep}'
    if elapsed_section_w:
        middle = f'{middle}{elapsed_content}{elapsed_vsep}'
    middle = f'{middle}{helper_text}'
    if cache_section_w:
        middle = f'{middle} {cache_vsep}{cache_content}'

    # Every │ in the content row needs a matching ┬/┴ on the borders above/below.
    path_row_cols: list[int] = [path_div_col]
    if elapsed_section_w:
        path_row_cols.append(elapsed_div_col)  # type: ignore[arg-type]
    if sep_rate_col is not None:
        path_row_cols.append(sep_rate_col)
    if cache_section_w:
        path_row_cols.append(cache_div_col)    # type: ignore[arg-type]
    path_row_downs = tuple(path_row_cols)
    path_row_ups   = path_row_downs

    # Section labels (cfg.labels): captions overlaid on the top border, anchored
    # from the rendered content's token offsets below them. The border primitive
    # truncates/drops them at any elbow, corner, session id, or pill, so a wrong
    # column is cosmetic-only. Empty when the knob is off.
    top_labels: list[tuple[str, int]] = []
    if view.cfg.labels:
        # `changes`: over the git dirty block (' ' + dirty glyph after ∈).
        # Right-align to the dirty block's right edge (path content end,
        # `2 + path_w`) since there's rarely room to the right for the word.
        _pp = _ANSI_RE.sub('', line_path)
        _ps = _pp.find(_BRANCH_SEP)
        if _ps != -1:
            for _ci in range(_ps + 1, len(_pp) - 1):
                if _pp[_ci] == ' ' and _pp[_ci + 1] in _DIRTY_CHARS:
                    top_labels.append(('changes', max(3, 2 + path_w - len('changes') + 1)))
                    break
        # Elapsed cell: [glyph, clear, session] with a clear timer, else just
        # the session clock. `clear` only emitted when actually displayed.
        if elapsed_section_w:
            _pe   = _ANSI_RE.sub('', elapsed_content)
            _eo   = _token_offsets(_pe)
            _ebse = path_div_col + 2
            # Hidden icons shift the token walk left by one (mirrors `_h5_shift`).
            _el_shift = 0 if view.cfg.show_icons else -1
            if clear_str:
                if len(_eo) >= 2 + _el_shift:
                    top_labels.append(('clear', _ebse + _eo[1 + _el_shift]))
                if len(_eo) >= 3 + _el_shift:
                    top_labels.append(('session', _ebse + _eo[2 + _el_shift]))
            elif _eo:
                top_labels.append(('session', _ebse + _eo[0]))
        # 5h helper cell: `5h` over the glyph, one label per rendered sub-value.
        # Full countdown form: [glyph, (-h:mm), used%, burn-glyph, burn%]
        # (leading '(' distinguishes it); compact form: [glyph, used%, ∞].
        # Hidden icons shift the label sequence left by one (`_h5_shift`).
        _h5_shift = 0 if view.cfg.show_icons else -1
        _p5     = _ANSI_RE.sub('', padded_5h)
        _h5     = _token_offsets(_p5)
        _h5base = helper_anchor + 2
        if _h5:
            if view.cfg.show_icons:
                top_labels.append(('5h', _h5base + _h5[0]))
            if len(_h5) >= 2 + _h5_shift and _p5[_h5[1 + _h5_shift]] == '(':
                top_labels.append(('remain', _h5base + _h5[1 + _h5_shift]))
                if len(_h5) >= 3 + _h5_shift:
                    top_labels.append(('used', _h5base + _h5[2 + _h5_shift]))
                if len(_h5) >= 4 + _h5_shift:
                    top_labels.append(('burn rate', _h5base + _h5[3 + _h5_shift]))
            elif len(_h5) >= 2 + _h5_shift and _p5[_h5[1 + _h5_shift]] != '∞':
                top_labels.append(('used', _h5base + _h5[1 + _h5_shift]))
        # 7d cell, when present: `7d` over the glyph, `used` over the pct, and
        # `burn rate` over the burn glyph. tokens: [glyph, used%, burn-glyph, burn%].
        if has_7d and sep_rate_col is not None:
            _h7_shift = 0 if view.cfg.show_icons else -1
            _p7     = _ANSI_RE.sub('', padded_7d)
            _h7     = _token_offsets(_p7)
            _h7base = sep_rate_col + 2
            if _h7:
                if view.cfg.show_icons:
                    top_labels.append(('7d', _h7base + _h7[0]))
                if len(_h7) >= 2 + _h7_shift:
                    top_labels.append(('used', _h7base + _h7[1 + _h7_shift]))
                if len(_h7) >= 3 + _h7_shift:
                    top_labels.append(('burn rate', _h7base + _h7[2 + _h7_shift]))
        # Cache countdown cell begins just after the cache │.
        if cache_section_w and cache_div_col is not None:
            top_labels.append(('cache', cache_div_col + 2))

    if pill_pct:
        rows += [
            RowSpec('top_border', downs=path_row_downs, pill=pill, labels=top_labels),
            RowSpec('content', content=f'{middle}{" " * last_extra}', right_pill=right_text),
        ]
    else:
        # elapsed_section_w already accounts for its vsep's lead=1 (4 visible
        # cols, not vsep_w=5) — don't double-count vsep_w for it here.
        pad = max(1, (width - 3) - (path_w + vsep_w + elapsed_section_w + helper_w + cache_section_w + (1 if cache_section_w else 0) + right_w))
        content_full = f'{middle}{" " * pad}{right_text}'

        rows += [
            RowSpec('top_border', downs=path_row_downs, labels=top_labels),
            RowSpec('content', content=content_full),
        ]

    # Context separator labels: `context` over the absolute count, `fill` over
    # the (% of window) parenthetical, `dumb` over the soft-limit %. Only the
    # full context_line (tokens_fits) renders these; the compact fallback shows
    # a bare % and carries no labels. Each label right-aligns to its value's
    # right edge so a label wider than its value extends left, not right.
    ctx_labels: list[tuple[str, int]] = []
    if view.cfg.labels and tokens_fits:
        _ctx_plain = _ANSI_RE.sub('', line_context)
        _ctx_off   = _token_offsets(_ctx_plain)
        _hg = next((k for k, o in enumerate(_ctx_off) if _ctx_plain[o] == GLYPH_HOURGLASS), None)
        # When show_icons hides the hourglass, there is no glyph token to anchor
        # on — the first token offset is directly the `context` value instead,
        # so anchor one position earlier (-1) to keep the same relative walk.
        if _hg is None and not view.cfg.show_icons:
            _hg = -1
        if _hg is not None:
            for _name, _k in zip(('context', 'fill', 'dumb'),
                                 range(_hg + 1, _hg + 4)):
                if _k < len(_ctx_off):
                    _ctx_end = _ctx_off[_k]
                    while _ctx_end + 1 < len(_ctx_plain) and _ctx_plain[_ctx_end + 1] != ' ':
                        _ctx_end += 1
                    ctx_labels.append((_name, max(3, 3 + _ctx_end - len(_name) + 1)))
    rows.append(RowSpec('separator_dim', ups=path_row_ups, pill=pill, labels=ctx_labels))
    rows.append(RowSpec('content', content=line_context))

    # One elbow per vsep │ in the tokens line; dropped entirely (no `ups`)
    # when the row itself doesn't fit (below the tokens_fits floor).
    if tokens_fits:
        # Tokens/cost separator labels: input/cache/output over the three
        # token columns left of the first vsep │, cost between the two vseps,
        # "tokens over time" over the sparkline after the second. `sess/day`
        # suffix names the pair shown only when day stats are on.
        tok_labels: list[tuple[str, int]] = []
        if view.cfg.labels:
            _tp      = _ANSI_RE.sub('', line_tokens[0])
            _cache_i = _tp.find('(')
            _close_i = _tp.find(')', _cache_i + 1) if _cache_i != -1 else -1
            _out_i   = -1
            if _close_i != -1:
                _j = _close_i + 1
                while _j < len(_tp) and _tp[_j] == ' ':
                    _j += 1
                if _j < len(_tp):
                    _out_i = _j
            _suf = ' sess/day' if view.cfg.show_day_stats else ''
            tok_labels.append((f'input{_suf}', 3))
            if _cache_i != -1:
                # Centre `cache` over the `(…)` parenthetical when it fits;
                # fall back to a left-anchor at '(' rather than cannibalising
                # `input` when the ` sess/day` suffix makes it too wide.
                _cache_lbl = f'cache{_suf}'
                _cache_end = _close_i if _close_i != -1 else _cache_i
                _cache_mid = 3 + (_cache_i + _cache_end) // 2
                _cache_anchor = max(3, _cache_mid - len(_cache_lbl) // 2)
                if _cache_anchor < 3 + len(f'input{_suf}'):
                    _cache_anchor = 3 + _cache_i
                tok_labels.append((_cache_lbl, _cache_anchor))
            if _out_i != -1:
                tok_labels.append((f'output{_suf}', 3 + _out_i))
            # Centre `cost` within its cell (between the last two vseps).
            # vsep_cols is a 2-tuple with the lines segment shed, 3-tuple with
            # it included; the cost cell is always the last pair before the sparkline.
            _cost_lbl = f'cost{_suf}'
            _cost_mid = (vsep_cols[-2] + vsep_cols[-1]) // 2
            tok_labels.append((_cost_lbl, max(vsep_cols[-2] + 1, _cost_mid - len(_cost_lbl) // 2)))
            tok_labels.append(('tokens over time', vsep_cols[-1] + 2))
            # `lines read/changed` caption, centred between the first two vseps,
            # only when that segment is present (len == 3).
            if len(vsep_cols) == 3:
                _lines_mid = (vsep_cols[0] + vsep_cols[1]) // 2
                tok_labels.append((LINES_LABEL, max(vsep_cols[0] + 1, _lines_mid - len(LINES_LABEL) // 2)))
        rows.append(RowSpec('separator_dim', downs=vsep_cols, labels=tok_labels))
        for lt in line_tokens:
            rows.append(RowSpec('content', content=lt))

    # First post-tokens separator draws as the heavy "seam" marking the
    # static->dynamic split; later separators keep their normal style.
    pending_ups: tuple[int, ...] = vsep_cols if tokens_fits else ()
    seam_pending = True

    def sep_kind(normal: str) -> str:
        nonlocal seam_pending
        if seam_pending:
            seam_pending = False
            return 'separator_seam'
        return normal

    # Per-tool tool_use counts row (wide-only). Full-width, no internal │, so
    # it threads no ┬/┴ of its own. Zero-state: omit, leave pending_ups intact.
    tc = view.tool_counts
    if view.cfg.show_tool_uses and tc.counts:
        tc_labels: list[tuple[str, int]] = [(TOOL_COUNTS_LABEL, 3)] if view.cfg.labels else []
        rows.append(RowSpec(sep_kind('separator_dim'), ups=pending_ups, labels=tc_labels))
        rows.append(RowSpec('content', content=r.tool_counts_row(tc.counts, width, fill=fill)))
        pending_ups = ()

    if plugins_line:
        plugins_labels: list[tuple[str, int]] = (
            [('skills + plugins', 3)] if view.cfg.labels else []
        )
        rows.append(RowSpec(sep_kind('separator_dim'), ups=pending_ups, labels=plugins_labels))
        rows.append(RowSpec('content', content=plugins_line))
        pending_ups = ()

    last_prompt_ts = read_last_prompt_ts(session.session_id)
    visible_subs   = subagents.visible(time.time(), last_prompt_ts)
    visible_subs = select_visible_cohort(visible_subs, SUBAGENT_DISPLAY_CAP)

    # Side-by-side: when there's both a visible checklist and >=1 visible
    # subagent, lay them out as two columns in one bordered block. Left column
    # capped at 45% of inner width; falls back to stacking if right < 40 cols.
    # `tail_ups` carries the divider's ┴ onto the separator/border below.
    tail_ups: tuple[int, ...] = ()
    side_by_side = False
    if tasks.is_visible() and visible_subs:
        inner             = width - 4
        # Size the plan column to its content (probe-rendered at the ceiling,
        # trailing pad stripped) so reclaimed columns go to the subagent tree.
        plan_ceiling  = min(SUBAGENT_TREE_PLAN_WIDTH, inner * 45 // 100)
        plan_content  = plan_content_width(r.task_row(tasks, plan_ceiling))
        left_w        = min(plan_content + SUBAGENT_TREE_PLAN_PAD, plan_ceiling)
        right_w           = inner - 3 - left_w
        if right_w >= 40:
            side_by_side = True
            divider_col  = 3 + left_w + 1  # 1-indexed visual column of the │
            left_lines   = r.task_row(tasks, left_w)
            right_cells  = subagent_cells(visible_subs)
            right_model_w = tree_model_width(right_cells)
            right_lines_w = tree_lines_width(right_cells, view.tool_counts.per_agent)
            right_cluster_w = subagent_cluster_width(right_lines_w)
            right_desc_col, right_stats_col, right_activity_col = tree_columns(
                right_cells, right_w, cluster_full_w=right_cluster_w, model_w=right_model_w,
            )
            right_lines: list[str] = []
            for sub, prefix, depth in right_cells:
                right_lines.extend(
                    r.subagent_row(sub, right_w, twoline=True, session_inout=session_inout,
                                   stats_col=right_stats_col, tree_prefix=prefix, tree_depth=depth,
                                   tree_single=True, tree_desc_col=right_desc_col,
                                   tree_activity_col=right_activity_col, tree_model_w=right_model_w,
                                   tree_lines_w=right_lines_w,
                                   lines=view.tool_counts.per_agent.get(sub.jsonl_path)).split('\n')
                )
            div_color = r.grad_at(divider_col - 1, width, fill=fill)
            divider   = f'{div_color}{BOX_V}{RESET}'
            sbs_labels: list[tuple[str, int]] = (
                [('plan', 3), ('agent', divider_col + 10)] if view.cfg.labels else []
            )
            rows.append(RowSpec(sep_kind('separator_dim'), ups=pending_ups, downs=(divider_col,), labels=sbs_labels))
            for line in zip_columns(left_lines, right_lines, left_w, right_w, divider):
                rows.append(RowSpec('content', content=line))
            pending_ups = ()
            tail_ups    = (divider_col,)

    if not side_by_side:
        if tasks.is_visible():
            plan_labels: list[tuple[str, int]] = [('plan', 3)] if view.cfg.labels else []
            rows.append(RowSpec(sep_kind('separator_dim'), ups=pending_ups, labels=plan_labels))
            for line in r.task_row(tasks, width - 4):
                rows.append(RowSpec('content', content=line))
            pending_ups = ()

        if visible_subs:
            sub_labels: list[tuple[str, int]] = [('agent', 11)] if view.cfg.labels else []
            rows.append(RowSpec(sep_kind('separator_dim'), ups=pending_ups, labels=sub_labels))
            sub_cells = subagent_cells(visible_subs)
            inner = width - 4
            model_w = tree_model_width(sub_cells)
            lines_w = tree_lines_width(sub_cells, view.tool_counts.per_agent)
            cluster_w = subagent_cluster_width(lines_w)
            desc_col, stats_col_v, activity_col = tree_columns(
                sub_cells, inner, cluster_full_w=cluster_w, model_w=model_w,
            )
            # Overlay column labels on the section header: 'name'/'model'/'tok'/
            # 'loc r/w'/'log', derived from the same anchors and field-offset
            # math the rows themselves use, so the header can't drift.
            if view.cfg.labels and rows and rows[-1].labels is not None:
                tok_off, lines_off = subagent_cluster_field_offsets(lines_w)
                # Model sits at the tail of the front field, model_w cols
                # before ' · description' with a 2-col gap ahead of it.
                model_col = max(0, desc_col - 1 - model_w) if model_w else desc_col
                # tok field is right-justified to width 5 at stats_col_v + tok_off.
                tok_col = 3 + stats_col_v + tok_off
                # Lines field renders '<read> /<changed>'; anchor 'loc r/w' at
                # its own '/' (index 5) so the two '/'s stay stacked.
                loc_slash_col = stats_col_v + lines_off + lines_w
                loc_col = 3 + loc_slash_col - 5
                rows[-1].labels.extend([
                    ('name', 3 + desc_col + 2),  # +2 nudges off desc column's exact start
                    ('model', 3 + model_col),
                    ('tok', tok_col),
                    ('loc r/w', loc_col),
                    ('log', 3 + activity_col),
                ])
            name_w = oneline_name_width(sub_cells)
            oneline_model_w = tree_model_width(sub_cells)
            for sub, prefix, depth in sub_cells:
                for line in r.subagent_row(sub, inner, twoline=width > 100, session_inout=session_inout,
                                           stats_col=stats_col_v,
                                           tree_prefix=prefix, tree_depth=depth, tree_single=True,
                                           tree_desc_col=desc_col, tree_activity_col=activity_col,
                                           tree_model_w=model_w, tree_lines_w=lines_w,
                                           oneline_name_w=name_w, oneline_model_w=oneline_model_w,
                                           lines=view.tool_counts.per_agent.get(sub.jsonl_path)).split('\n'):
                    rows.append(RowSpec('content', content=line))
            pending_ups = ()

    # Workflow cohort: header / per-agent rows / summary block per visible run,
    # after the subagent cohort and task row. Leading separator closes off any
    # still-pending dividers so the plain content rows below carry no elbows.
    wf_rows = build_workflow_rows(view, width, r, per_agent=True, fill=fill)
    if wf_rows:
        wf_labels: list[tuple[str, int]] = [('workflow', 3)] if view.cfg.labels else []
        rows.append(RowSpec(sep_kind('separator_dim'), ups=pending_ups + tail_ups, labels=wf_labels))
        rows.extend(wf_rows)
        pending_ups = ()
        tail_ups    = ()

    if openspec_bars:
        spec_labels: list[tuple[str, int]] = [('specs', 3)] if view.cfg.labels else []
        rows.append(RowSpec(sep_kind('separator'), ups=pending_ups + tail_ups, labels=spec_labels))
        for bar in openspec_bars:
            rows.append(RowSpec('content', content=bar))
        rows.append(RowSpec('bottom_border'))
    else:
        rows.append(RowSpec('bottom_border', ups=pending_ups + tail_ups))

    append_error_row(rows, view.cfg, width, r)
    spec.rows = rows
    return spec


def render_layout(spec: LayoutSpec, r: Renderer, timing: str = '', version: str = '') -> list[str]:
    lines: list[str] = []
    for row in spec.rows:
        if row.kind == 'top_border':
            lines.append(r.border_top(spec.width, spec.session_id, downs=row.downs, fill=spec.fill, pill=row.pill, labels=tuple(row.labels)))
        elif row.kind == 'bottom_border':
            lines.append(r.border_bottom(spec.width, ups=row.ups, fill=spec.fill, timing=timing, version=version))
        elif row.kind in ('separator', 'separator_seam'):
            # 'separator_seam' (static->dynamic split) is a full-brightness solid rule,
            # not dotted-dim, but renders identically to a plain 'separator' otherwise.
            lines.append(r.border_separator(spec.width, ups=row.ups, downs=row.downs, fill=spec.fill, labels=tuple(row.labels)))
        elif row.kind == 'separator_dim':
            lines.append(r.border_separator_dim(spec.width, downs=row.downs, ups=row.ups, fill=spec.fill, pill=row.pill, pill_edge=row.pill_edge, labels=tuple(row.labels)))
        elif row.kind == 'content':
            lines.append(r.border_line(row.content, spec.width, fill=spec.fill, bg_lead=row.bg_lead, bg_trail=row.bg_trail, pill_flush=row.pill_flush, right_pill=row.right_pill))
    return lines
