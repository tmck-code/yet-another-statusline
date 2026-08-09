"""Layout pipeline: RowSpec, LayoutSpec, build_narrow/medium/wide, render_layout."""

from __future__ import annotations

import time

from yas.config import Config
from yas.constants import (
    _ANSI_RE,
    BOX_V,
    CLR_WARN,
    DEFAULT_SOFT_LIMIT,
    ELLIPSIS,
    GLYPH_CONFIG_WARN,
    GLYPH_HOURGLASS,
    GLYPH_RENAMED,
    GLYPH_WF_DIVIDER,
    LINES_LABEL,
    RESET,
    SUBAGENT_DESC_FLOOR,
    SUBAGENT_NAME_MAX,
    SUBAGENT_RETENTION_SECONDS,
    SUBAGENT_STATS_ACTIVITY_GAP,
    subagent_is_terminal,
    subagent_status,
    SUBAGENT_TREE_PLAN_PAD,
    SUBAGENT_TREE_PLAN_WIDTH,
    TOKENS_COST_MIN_WIDTH,
    TOOL_COUNTS_LABEL,
    TWO_COL_WF_WIDTH,
    WORKFLOW_AGENT_CAP,
    WORKFLOW_RUN_CAP,
)
from yas.info import SessionView, _fmt_elapsed_clock
from yas.info.subagents import RunningSubagent, cap_tree_groups, read_last_prompt_ts, tree_order
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


class RowSpec:
    __slots__ = (
        'kind', 'content', 'bg_lead', 'bg_trail', 'pill_flush', 'ups', 'downs',
        'pill', 'pill_edge', 'right_pill', 'labels',
    )

    def __init__(
        self,
        kind:       str,  # 'top_border', 'bottom_border', 'separator', 'separator_dim', 'content'
        content:    str = '',
        bg_lead:    str = '',
        bg_trail:   str = '',
        pill_flush: bool = False,
        ups:        tuple[int, ...] = (),
        downs:      tuple[int, ...] = (),
        pill:       Pill | None = None,
        pill_edge:  str = 'bottom',
        right_pill: str = '',
        labels:     list[tuple[str, int]] | None = None,
    ) -> None:
        self.kind       = kind
        self.content    = content
        self.bg_lead    = bg_lead
        self.bg_trail   = bg_trail
        self.pill_flush = pill_flush
        self.ups        = ups
        self.downs      = downs
        self.pill       = pill
        self.pill_edge  = pill_edge
        self.right_pill = right_pill
        self.labels     = labels if labels is not None else []


class LayoutSpec:
    __slots__ = ('width', 'fill', 'session_id', 'rows')

    def __init__(
        self,
        width:      int,
        fill:       float,
        session_id: str,
        rows:       list[RowSpec] | None = None,
    ) -> None:
        self.width      = width
        self.fill       = fill
        self.session_id = session_id
        self.rows       = rows if rows is not None else []


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
        text = text[:avail - 1] + ELLIPSIS
    bottom = rows.pop()  # the bottom_border RowSpec
    rows.append(RowSpec('separator_dim', ups=bottom.ups))
    rows.append(RowSpec('content', content=f'{CLR_WARN}{text}{RESET}'))
    rows.append(RowSpec('bottom_border'))


def plan_content_width(lines: list[str]) -> int:
    """Intrinsic visible width of a rendered task checklist.

    ``Renderer.task_row`` lays its item rows out to exactly the width it is
    handed, so ``_visible_width`` of a rendered line always reports that width
    rather than the width the content actually needs. Strip the ANSI first (a
    trailing ``RESET`` sits after the padding, so a bare ``rstrip`` would miss
    it), then drop trailing blanks, and take the widest remaining line.
    """
    return max((_visible_width(_ANSI_RE.sub('', line).rstrip()) for line in lines), default=0)


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


def select_visible_cohort(
    visible_subs: list[RunningSubagent],
    cap: int,
    *,
    now: float | None = None,
) -> list[RunningSubagent]:
    """Apply retention, cascade-clear, then the display cap to a raw cohort.

    Retention: a terminal (non-running) row drops outright once
    ``SUBAGENT_RETENTION_SECONDS`` have passed since its ``end_ts`` — a
    maximum, not a guarantee; the cap below can still evict it sooner.

    Cascade clear: once a parent reaches any terminal status, every
    descendant still showing 'running' is forced to the parent's terminal
    status (and end_ts) too. This is sound by construction — a notification
    only fires once an agent has no live children, so a 'running' descendant
    at that point is a missed notification, not live work — and it prevents
    a stale child from pinning a finished parent's cohort open forever.

    Eviction: defers to ``cap_tree_groups`` (whole-group eviction,
    oldest-completion-first, never separating a live parent from a running
    child). This keeps every running row before evicting any terminal one,
    and terminal rows are always evicted oldest-``end_ts``-first regardless
    of which terminal state they ended in.
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
            pass  # `.status` isn't a slot on this build yet — nothing to cascade.

    # Cap by whole parent+descendant group so a still-running parent can't be
    # evicted while a finished child (later timestamp) lingers and fills the
    # cap's slice.
    return cap_tree_groups(visible_subs, cap)


def subagent_cells(
    visible_subs: list[RunningSubagent],
) -> list[tuple[RunningSubagent, str]]:
    """Pair each visible subagent with its tree-branch prefix.

    Reorders parent-first via ``tree_order`` and builds the branch prefix:
    depth-0 roots carry none; a child gets ``'├ '`` (``'└ '`` when it is its
    parent's last child), indented two spaces per extra nesting level.
    """
    cells: list[tuple[RunningSubagent, str]] = []
    for sub, depth, last in tree_order(visible_subs):
        if depth == 0:
            prefix = ''
        else:
            prefix = '  ' * (depth - 1) + ('└ ' if last else '├ ')
        cells.append((sub, prefix))
    return cells


def tree_desc_content_width(cells: list[tuple[RunningSubagent, str]]) -> int:
    """Widest `sub.description` string across a tree cohort's visible rows.

    Used by `tree_columns` to size the description column to what the cohort
    actually needs (content-measured) rather than a fixed guarantee/fraction
    of the terminal width — the same "measure, don't assume" pattern as
    `tree_model_width`/`tree_lines_width`. A subagent's
    `description` is set once at spawn and doesn't change frame-to-frame
    (unlike `last_activity`, which does), so measuring it here carries none
    of the jitter risk that measuring the activity snippet would.
    """
    return max((_visible_width(sub.description or '') for sub, _ in cells), default=0)


def tree_columns(
    cells: list[tuple[RunningSubagent, str]],
    width: int,
    *,
    cluster_full_w: int = 0,
    model_w: int = 0,
) -> tuple[int, int, int]:
    """Compute the (desc_col, stats_col, activity_col) anchors for tree-single rows.

    ``desc_col`` is the widest (prefix + duration + type + model) front-field
    across the cohort, plus the leading gap before ' · description' — so
    every row's description starts at the same absolute column regardless of
    its own prefix depth, type-name length, or model-label width (the
    renderer pads the shorter rows' type field to match). ``model_w`` is the
    cohort's `tree_model_width` — the model field now lives in the front
    cluster (`<time> <elbow> <name> <model>`), not the stats cluster, so it
    must be folded into this front-field measurement.

    Priority (inverted from the earlier design): the description/activity text
    is the ELASTIC side of the row and truncates first as the terminal
    narrows; the lines/share%/tok stats cluster is protected and sheds only
    once the description is already at its floor (`SUBAGENT_DESC_FLOOR`). So
    ``stats_col`` — where the cluster's leading '·' lands — is placed at
    ``desc_col + 3 + min(cohort's longest actual description, available room)``:
    it grows with the description's real content (never truncating on a wide
    terminal just because of a fixed cap) but never pads the column out past
    what the longest description needs (no dead gutter on a wide terminal
    with short descriptions either). ``cluster_full_w`` (the fully-populated
    cluster's measured width — see `render.metrics.subagent_cluster_width`)
    is what "available room" is computed against: room is only handed to the
    description once the full cluster plus a minimal activity gap are
    accounted for; past that, the description is held at its floor and the
    cluster starts shedding fields instead (see the "anchored" branch of
    `Renderer.subagent_row`).
    """
    now      = time.time()
    desc_col = 0
    desc_content_w = tree_desc_content_width(cells)
    for sub, prefix in cells:
        prefix_w = _visible_width(prefix)
        # dur_s is NOT fixed-width (fmt_dur grows an extra digit past 9
        # minutes/hours: '3m36s' is 5 chars, '40m23s' is 6) — measure the
        # actual string `subagent_row` will render, or a long-running parent
        # row silently claims one column less than it needs and every
        # shorter-duration child row drifts left of it. See subagent_dur_str.
        # The name is measured via `subagent_type_label` (the same string
        # `subagent_row` renders) capped at SUBAGENT_NAME_MAX
        # (the renderer truncates past that); +3 + model_w: the ' X <model>'
        # field after the name, where X is the run-state marker/separator
        # glyph (0 when model_w is 0, e.g. an empty cohort) — keep all of it
        # in lockstep with `subagent_row`'s own front_w formula.
        dur_w      = _visible_width(subagent_dur_str(sub, now))
        model_gap  = 3 if model_w else 0  # ' X ' marker/separator ahead of the model field
        name_w     = min(_visible_width(subagent_type_label(sub)), SUBAGENT_NAME_MAX)
        front_w    = dur_w + 1 + name_w + model_gap + model_w  # dur + ' ' + type + marker + model
        desc_col   = max(desc_col, prefix_w + front_w + 1)  # +1: leading space of ' · '

    # Everything after `desc_col + 3` (the ' · ' before the description) is up
    # for grabs between the description, the cluster, and the activity gap.
    # Reserve the full cluster plus a minimal activity gap (room for at least
    # the model-only fallback) first; whatever's left is what the description
    # is allowed to grow into, capped by what it actually needs so a short
    # cohort of descriptions never gets padded out into a gutter.
    activity_floor = 16  # model-only fallback + a breath of activity text
    room_after_desc_col = max(0, width - desc_col - 3)
    room_for_desc        = max(0, room_after_desc_col - cluster_full_w - activity_floor)
    desc_w = min(desc_content_w, max(SUBAGENT_DESC_FLOOR, room_for_desc))
    # Never grow past the row's own width (degenerate very-narrow case).
    desc_w = max(0, min(desc_w, room_after_desc_col))
    stats_col = desc_col + 3 + desc_w

    # The activity column starts after the cluster's full width plus the
    # constant stats/activity gap, so wider terminals — where the description
    # didn't need all its "room for full cluster" allotment — hand the extra
    # space straight to the activity column instead of leaving it as a dead
    # gutter between the description and the cluster. Floored at
    # `stats_col + activity_floor` (room for the model-only fallback) and
    # capped at the row's own width.
    activity_col = max(stats_col + activity_floor, stats_col + cluster_full_w + SUBAGENT_STATS_ACTIVITY_GAP)
    activity_col = min(activity_col, width)  # never past the row's target width
    # Degenerate very-narrow case: clamping activity_col down to `width` can
    # leave less than the activity-floor gap between it and stats_col (the
    # description was already squeezed to its floor and there still isn't
    # room). Pull stats_col back in step so the gap invariant callers rely on
    # (`activity_col >= stats_col + 16`) always holds — the description
    # degrades below its floor rather than the whole row producing
    # nonsensical overlapping columns.
    if activity_col < stats_col + activity_floor:
        stats_col = max(desc_col + 3, activity_col - activity_floor)
    return desc_col, stats_col, activity_col


def oneline_name_width(cells: list[tuple[RunningSubagent, str]]) -> int:
    """Widest branch-prefix + type-label run across a cohort's rows.

    Passed to `Renderer.subagent_row` as `oneline_name_w` so the one-line
    collapse form pads every row's name field to a common width — the
    ' · model' column then starts at the same offset down the cohort,
    mirroring the twoline form's `tree_desc_col` alignment.
    """
    return max(
        (_visible_width(prefix)
         + min(_visible_width(subagent_type_label(sub)), SUBAGENT_NAME_MAX)
         for sub, prefix in cells),
        default=0,
    )


def tree_model_width(cells: list[tuple[RunningSubagent, str]]) -> int:
    """Widest model label actually present in this tree cohort (measured,
    not fixed).

    The tree row embeds the model field directly in the front cluster
    (`<time> <elbow> <name> <model>`, ahead of the description), padded to
    this width so every row's model column starts and ends at the same
    offset down the cohort — but the column itself grows/shrinks with
    whichever models are actually running, rather than reserving a fixed
    width sized for a worst-case label like `'sonnet[1m]'` regardless of
    cohort content. `default=0` covers the empty-cohort case.
    """
    return max((_visible_width(model_display(sub.model)) for sub, _ in cells), default=0)


def tree_lines_width(cells: list[tuple[RunningSubagent, str]], per_agent: dict[str, tuple[int, int]]) -> int:
    """Widest `fmt_tok` string any cohort row's read/changed count needs.

    Passed to `Renderer.subagent_row` as `tree_lines_w` so the Lines Read/
    Changed field reserves only as much column width as this cohort's actual
    counts require, instead of always assuming `fmt_tok`'s full 6-char ceiling
    (`'999.9B'`) — the same "measure, don't assume" fix already applied to the
    duration field (`subagent_dur_str`), since `fmt_tok`'s output is equally
    NOT fixed-width. Falls back to 1 for an all-idle cohort (no lines data at
    all), so a idle row's blank-field width still matches a populated one.
    """
    widths = []
    for sub, _ in cells:
        pair = per_agent.get(sub.jsonl_path)
        if pair is None:
            continue
        read, changed = pair
        widths.append(len(fmt_tok_fixed(read)))
        widths.append(len(fmt_tok_fixed(changed)))
    return max(widths, default=1)


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
            # Pair agents column-major: left column is agents[:ceil(n/2)] (most
            # recent, chronological), right column is the rest, paired by row
            # index. An odd trailing agent renders in the left column with a
            # blank right half so it stays inside the L/R section and the
            # divider stays unbroken.
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
    visible_subs   = subagents.visible(time.time(), last_prompt_ts)
    visible_subs = select_visible_cohort(visible_subs, view.cfg.agent_tree_max_height)
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
        cells = subagent_cells(visible_subs)
        name_w = oneline_name_width(cells)
        model_w = tree_model_width(cells)
        for sub, prefix in cells:
            for line in r.subagent_row(sub, width - 4, twoline=width > 100, session_inout=0,
                                       stats_col=100 if width >= 125 else None,
                                       tree_prefix=prefix, oneline_name_w=name_w,
                                       oneline_model_w=model_w).split('\n'):
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
    visible_subs   = subagents.visible(time.time(), last_prompt_ts)
    visible_subs = select_visible_cohort(visible_subs, view.cfg.agent_tree_max_height)
    rows: list[RowSpec] = [top_row, content_row, sep_row]
    if tasks.is_visible():
        for line in r.task_row(tasks, width - 4):
            rows.append(RowSpec('content', content=line))
        rows.append(RowSpec('separator_dim'))
    if visible_subs:
        cells = subagent_cells(visible_subs)
        name_w = oneline_name_width(cells)
        model_w = tree_model_width(cells)
        for sub, prefix in cells:
            for line in r.subagent_row(sub, width - 4, twoline=width > 100, session_inout=0,
                                       stats_col=100 if width >= 125 else None,
                                       tree_prefix=prefix, oneline_name_w=name_w,
                                       oneline_model_w=model_w).split('\n'):
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
    # Reading `view.tool_counts` here forces its transcript scan on every wide
    # render (previously only when `cfg.show_tool_uses` was on, for the
    # per-tool row further down) — needed to feed the session-total lines
    # read/changed segment into `tokens_cost` below. Accepted +2.9ms cost per
    # design.md Decision 6.
    line_tokens, vsep_cols, _mark_col, tokens_min_w = r.tokens_cost(
        usage.billed_in, usage.cache_read, usage.out,
        token_log.day_in, token_log.day_cache_read, token_log.day_out,
        sess_cost, day_cost, tok_rate,
        session.session_id, width, fill, view.cfg.show_day_stats,
        view.cfg.justify,
        lines=(view.tool_counts.lines_read, view.tool_counts.lines_changed),
    )
    # The three-segment tokens │ cost │ rate row is fixed-content-width: at the
    # bottom of the wide band (box ~80-84) it cannot hold both columns plus the
    # rate/spark leader without overflowing the box and detaching its two │ from
    # the ┬/┴ elbows. ``tokens_min_w`` is the exact content-aware floor reported
    # by tokens_cost; below it (and below the worst-case constant) we drop the row
    # and fall back to the compact context line the medium layout uses.
    tokens_fits = width >= max(tokens_min_w, TOKENS_COST_MIN_WIDTH)

    plugins_line = r.plugins_skills(len(skills.names), skill_display, session.workspace.plugins)
    # border_line pads to width - 3 ('│ ' + content + '│') but never truncates;
    # a long plugin list would overflow the box, so clip it here.
    plugins_avail = width - 3
    if _visible_width(plugins_line) > plugins_avail:
        cut = _ansi_byte_offset(plugins_line, plugins_avail - 1)
        plugins_line = f'{plugins_line[:cut]}{ELLIPSIS}{RESET}'
    title_cap    = max(10, width - 45)
    title_w      = min(40, title_cap, max((len(n) for n, _, _ in changes), default=25))
    openspec_bars = [r.openspec_bar(name, d, t, width, title_w) for name, d, t in changes]

    state_labels = view.cfg.context_labels if view.cfg.context_state else None
    line_context = (
        r.context_line(ctx, width - 3, soft_limit, state_labels=state_labels, state_thresholds=view.cfg.context_thresholds)
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
        # Spend each helper section's slack first as inter-stat breathing room
        # (separators widen from 1 toward a 3-char cap, symmetric within the
        # section), then centre whatever remains as outer padding. The section's
        # total width is unchanged — inner growth is matched by outer shrink — so
        # the divider columns below are unaffected. The 5h section has two
        # separators (countdown↔pct, pct↔trend); 7d has one (pct↔trend).
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
            # RHS has 2 more built-in spaces than LHS (sep_rate trailing=1 vs
            # explicit-space+cache_vsep-lead=3), so bias the split left by 1.
            h7_left  = (h7_outer + 2) // 2
            h7_right = h7_outer - h7_left
        if gap_5h != 1 or gap_7d != 1:
            helper_5h, helper_7d = r._rate_helpers(session.rate_limits, gap_5h, gap_7d)
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

    # Section labels (cfg.labels): hand-tuned superscript captions overlaid onto
    # the top border above the path/model row. Each (text, start_col) anchor is
    # derived from the divider/width vars already computed above; the border
    # primitive truncates/drops them at any elbow, corner, session id, or pill so
    # a wrong column is cosmetic-only. Empty (and byte-identical to today) when
    # the knob is off.
    # Each anchor is measured from the *rendered* content below it (ANSI stripped,
    # value token offsets), so a label's first glyph sits over the value it names
    # regardless of that value's width. Labels are appended left-to-right; the
    # border primitive truncates/drops them at any elbow, corner, session id, or
    # pill so a wrong column is cosmetic-only.
    top_labels: list[tuple[str, int]] = []
    if view.cfg.labels:
        # `changes`: over the git dirty block. It is always ' ' + a dirty glyph
        # after the ∈ branch separator; the leading-space requirement keeps a '-'
        # inside a branch name from matching. The dirty block sits at the right
        # end of the path content (justify pads before it, so it always abuts the
        # path divider), leaving only a few fill columns to its right — too few
        # for the 7-glyph word. So RIGHT-align the label to the dirty block's
        # right edge (path content end, column `2 + path_w`); it extends left
        # over the branch fill and shows in full.
        _pp = _ANSI_RE.sub('', line_path)
        _ps = _pp.find(_BRANCH_SEP)
        if _ps != -1:
            for _ci in range(_ps + 1, len(_pp) - 1):
                if _pp[_ci] == ' ' and _pp[_ci + 1] in _DIRTY_CHARS:
                    top_labels.append(('changes', max(3, 2 + path_w - len('changes') + 1)))
                    break
        # Elapsed cell: measured from the rendered timers. With a clear timer the
        # cell is [glyph, clear, session] (the clear-only degradation tier drops
        # the trailing session token); with no clear timer it is just the session
        # clock. `clear` is emitted ONLY when the clear timer is displayed — never
        # over a value that isn't there.
        if elapsed_section_w:
            _pe   = _ANSI_RE.sub('', elapsed_content)
            _eo   = _token_offsets(_pe)
            _ebse = path_div_col + 2
            if clear_str:
                if len(_eo) >= 2:
                    top_labels.append(('clear', _ebse + _eo[1]))
                if len(_eo) >= 3:
                    top_labels.append(('session', _ebse + _eo[2]))
            elif _eo:
                top_labels.append(('session', _ebse + _eo[0]))
        # 5h helper cell: `5h` over the glyph, then one label per rendered
        # sub-value. padded_5h tokens are [glyph, …]: the full countdown form is
        # [glyph, (-h:mm), used%, burn-glyph, burn%] (distinguished by the
        # countdown's leading '('); the compact form is [glyph, used%, ∞] and
        # carries only `used`.
        _p5     = _ANSI_RE.sub('', padded_5h)
        _h5     = _token_offsets(_p5)
        _h5base = helper_anchor + 2
        if _h5:
            top_labels.append(('5h', _h5base + _h5[0]))
            if len(_h5) >= 2 and _p5[_h5[1]] == '(':
                top_labels.append(('remain', _h5base + _h5[1]))
                if len(_h5) >= 3:
                    top_labels.append(('used', _h5base + _h5[2]))
                if len(_h5) >= 4:
                    top_labels.append(('burn rate', _h5base + _h5[3]))
            elif len(_h5) >= 2 and _p5[_h5[1]] != '∞':
                top_labels.append(('used', _h5base + _h5[1]))
        # 7d cell, when present: `7d` over the glyph, `used` over the pct, and
        # `burn rate` over the burn glyph. tokens: [glyph, used%, burn-glyph, burn%].
        if has_7d and sep_rate_col is not None:
            _p7     = _ANSI_RE.sub('', padded_7d)
            _h7     = _token_offsets(_p7)
            _h7base = sep_rate_col + 2
            if _h7:
                top_labels.append(('7d', _h7base + _h7[0]))
                if len(_h7) >= 2:
                    top_labels.append(('used', _h7base + _h7[1]))
                if len(_h7) >= 3:
                    top_labels.append(('burn rate', _h7base + _h7[2]))
        # Cache countdown cell begins just after the cache │.
        if cache_section_w and cache_div_col is not None:
            top_labels.append(('cache', cache_div_col + 2))

    if pill_pct:
        rows += [
            RowSpec('top_border', downs=path_row_downs, pill=pill, labels=top_labels),
            RowSpec('content', content=f'{middle}{" " * last_extra}', right_pill=right_text),
        ]
    else:
        pad = max(1, (width - 3) - (path_w + vsep_w + elapsed_section_w + helper_w + cache_section_w + (1 if cache_section_w else 0) + right_w))
        content_full = f'{middle}{" " * pad}{right_text}'
        rows += [
            RowSpec('top_border', downs=path_row_downs, labels=top_labels),
            RowSpec('content', content=content_full),
        ]

    # Context separator labels: `context` over the absolute count, `fill` over
    # the (% of window) parenthetical, `dumb` over the soft-limit %. Only the
    # full context_line (tokens_fits) renders those three values; the compact
    # fallback shows a bare % and carries no labels. Each label is RIGHT-aligned
    # to its value's right edge (a stable column, since the values are
    # right-justified in fixed-width fields) so a label wider than its value —
    # `context` over `30.0K` — extends left into the gap rather than spilling
    # right into the next label.
    ctx_labels: list[tuple[str, int]] = []
    if view.cfg.labels and tokens_fits:
        _ctx_plain = _ANSI_RE.sub('', line_context)
        _ctx_off   = _token_offsets(_ctx_plain)
        _hg = next((k for k, o in enumerate(_ctx_off) if _ctx_plain[o] == GLYPH_HOURGLASS), None)
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

    # Two elbows: one per vsep │ in the single tokens line. The old 60s tick
    # marker (a third elbow) was removed once the bar became a flat 60s window.
    # The row is dropped at the bottom of the wide band (box < tokens_fits floor),
    # where it cannot fit without overflow; then there are no vseps to thread, so
    # the seam carries no `ups`.
    if tokens_fits:
        # Tokens/cost separator labels: input/cache/output measured over the
        # three token columns left of the first vsep │ (input at the ↓ icon,
        # cache at the '(' parenthetical, output at the ↑ icon after the ')'),
        # cost between the two vseps, and "tokens over time" over the rate
        # sparkline after the second. The `sess/day` suffix names the
        # session/day pair shown only when day stats are on.
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
                # Centre `cache` over the `(…)` parenthetical (anchor = section
                # midpoint − half the label width). When the column has room the
                # label sits centred over its value; but with the long ` sess/day`
                # suffix the centred label reaches back into the `input` columns,
                # so fall back to the original left-anchor at the '(' rather than
                # cannibalising `input` — centring is best-effort, applied only
                # when it fits.
                _cache_lbl = f'cache{_suf}'
                _cache_end = _close_i if _close_i != -1 else _cache_i
                _cache_mid = 3 + (_cache_i + _cache_end) // 2
                _cache_anchor = max(3, _cache_mid - len(_cache_lbl) // 2)
                if _cache_anchor < 3 + len(f'input{_suf}'):
                    _cache_anchor = 3 + _cache_i
                tok_labels.append((_cache_lbl, _cache_anchor))
            if _out_i != -1:
                tok_labels.append((f'output{_suf}', 3 + _out_i))
            # Centre `cost` within its cell (between the last two vseps) instead of
            # left-anchoring at the cell's start. The cost cell is its own section
            # (bounded by vseps), so this never conflicts with the token labels.
            # Index from the end: vsep_cols is a 2-tuple when the lines segment is
            # shed and a 3-tuple when it's included (design.md Decision 8), and the
            # cost cell is always the pair immediately preceding the sparkline.
            _cost_lbl = f'cost{_suf}'
            _cost_mid = (vsep_cols[-2] + vsep_cols[-1]) // 2
            tok_labels.append((_cost_lbl, max(vsep_cols[-2] + 1, _cost_mid - len(_cost_lbl) // 2)))
            tok_labels.append(('tokens over time', vsep_cols[-1] + 2))
            # `lines read/changed` caption, centred between the first two vseps —
            # only present when the segment itself is (len == 3; Decision 8).
            if len(vsep_cols) == 3:
                _lines_mid = (vsep_cols[0] + vsep_cols[1]) // 2
                tok_labels.append((LINES_LABEL, max(vsep_cols[0] + 1, _lines_mid - len(LINES_LABEL) // 2)))
        rows.append(RowSpec('separator_dim', downs=vsep_cols, labels=tok_labels))
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

    # Per-tool tool_use counts row (wide-only), directly under the tokens/cost
    # rows. Full-width content with no internal │, so it threads no ┬/┴ of its
    # own — the leading separator closes the tokens vseps via sep_kind/pending_ups.
    # Zero-state (no counted tool uses since /clear): omit both rows, leave
    # pending_ups intact so the next section inherits the tokens vseps' ┴.
    tc = view.tool_counts
    if view.cfg.show_tool_uses and tc.counts:
        tc_labels: list[tuple[str, int]] = [(TOOL_COUNTS_LABEL, 3)] if view.cfg.labels else []
        rows.append(RowSpec(sep_kind('separator_dim'), ups=pending_ups, labels=tc_labels))
        rows.append(RowSpec('content', content=r.tool_counts_row(tc.counts, width, fill=fill)))
        pending_ups = ()

    if plugins_line:
        # Single "skills + plugins" caption anchored at content start (col 3).
        plugins_labels: list[tuple[str, int]] = (
            [('skills + plugins', 3)] if view.cfg.labels else []
        )
        rows.append(RowSpec(sep_kind('separator_dim'), ups=pending_ups, labels=plugins_labels))
        rows.append(RowSpec('content', content=plugins_line))
        pending_ups = ()

    last_prompt_ts = read_last_prompt_ts(session.session_id)
    visible_subs   = subagents.visible(time.time(), last_prompt_ts)
    visible_subs = select_visible_cohort(visible_subs, view.cfg.agent_tree_max_height)

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
        # Size the plan column to its content — the longest rendered plan
        # line plus SUBAGENT_TREE_PLAN_PAD — so every reclaimed column goes
        # to the subagent tree instead of a band of trailing padding. `task_row`
        # right-pads its item rows to the width it is handed, so the content
        # width is measured off a probe render at the ceiling with trailing
        # padding stripped (ANSI first, since a trailing RESET follows the pad).
        # The ceiling is SUBAGENT_TREE_PLAN_WIDTH (a long plan never eats the
        # whole box) clamped by the 45%-of-inner cap, so a narrow box still
        # degrades gracefully.
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
            for sub, prefix in right_cells:
                right_lines.extend(
                    r.subagent_row(sub, right_w, twoline=True, session_inout=session_inout,
                                   stats_col=right_stats_col, tree_prefix=prefix,
                                   tree_single=True, tree_desc_col=right_desc_col,
                                   tree_activity_col=right_activity_col, tree_model_w=right_model_w,
                                   tree_lines_w=right_lines_w,
                                   lines=view.tool_counts.per_agent.get(sub.jsonl_path)).split('\n')
                )
            div_color = r.grad_at(divider_col - 1, width, fill=fill)
            divider   = f'{div_color}{BOX_V}{RESET}'
            # `plan` over the checklist column, `agent` over the cohort column.
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
            # Overlay column labels on the section header (the
            # `separator_dim` row just appended above): 'name' over the
            # desc column, 'model' over the front-embedded model
            # field, 'tokens' over the tok field, 'loc r/w' over the lines
            # column, 'log' over the activity column. Derived from the SAME
            # anchors and field-offset math the rows themselves use
            # (desc_col/stats_col_v/activity_col plus
            # `subagent_cluster_field_offsets`) — never a hardcoded guess, so
            # the header can't drift from the data it labels.
            if view.cfg.labels and rows and rows[-1].labels is not None:
                tok_off, lines_off = subagent_cluster_field_offsets(lines_w)
                # Model now lives at the tail of the front field
                # (`desc_col - 1` is where ' · description' starts;
                # the model field is the `model_w` cols immediately
                # before that, with a 2-col gap ahead of it).
                model_col = max(0, desc_col - 1 - model_w) if model_w else desc_col
                # The tok field is right-justified to width 5
                # (`fmt_tok_fixed(...).rjust(5)`) at `stats_col_v + tok_off`.
                # A label's anchor is where its OWN text starts (never a
                # right edge — `_overlay_labels` only ever shifts a label
                # LEFT of its anchor to make it fit, never right), so anchor
                # at the field's start, same as 'model' above.
                tok_col = 3 + stats_col_v + tok_off
                # The data row renders the lines field as
                # '<read> /<changed>' — `lines_w`-wide read, then a
                # space, then the '/'. Measured against the actual
                # rendered cluster (not re-derived from the field
                # widths alone — the tok field's own padding shifts
                # this by a column the naive arithmetic misses), the
                # '/' lands at `lines_off + lines_w` inside the stats
                # cluster. 'loc r/w' has its own '/' at index 5
                # ('l','o','c',' ','r','/'), so anchoring the label
                # there — rather than at the field's start like the
                # full-word form — keeps the two '/'s stacked
                # regardless of the cohort's measured `lines_w`.
                loc_slash_col = stats_col_v + lines_off + lines_w
                loc_col = 3 + loc_slash_col - 5
                rows[-1].labels.extend([
                    # +2: nudges 'name' off the desc column's exact
                    # start so it settles visually under the name
                    # values rather than flush against 'model'.
                    ('name', 3 + desc_col + 2),
                    ('model', 3 + model_col),
                    # 'tokens' (not the full word) — the tok field's 5-wide
                    # column sits close enough to 'loc r/w' that the full
                    # word collides with it and gets dropped by the label
                    # overlay's run-based fitting; the short form fits its
                    # own run without stealing 'loc r/w's.
                    ('tok', tok_col),
                    ('loc r/w', loc_col),
                    ('log', 3 + activity_col),
                ])
            name_w = oneline_name_width(sub_cells)
            oneline_model_w = tree_model_width(sub_cells)
            for sub, prefix in sub_cells:
                for line in r.subagent_row(sub, inner, twoline=width > 100, session_inout=session_inout,
                                           stats_col=stats_col_v,
                                           tree_prefix=prefix, tree_single=True,
                                           tree_desc_col=desc_col, tree_activity_col=activity_col,
                                           tree_model_w=model_w, tree_lines_w=lines_w,
                                           oneline_name_w=name_w, oneline_model_w=oneline_model_w,
                                           lines=view.tool_counts.per_agent.get(sub.jsonl_path)).split('\n'):
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
        elif row.kind == 'separator':
            lines.append(r.border_separator(spec.width, ups=row.ups, downs=row.downs, fill=spec.fill, labels=tuple(row.labels)))
        elif row.kind == 'separator_seam':
            # Static->dynamic split: a full-brightness solid rule (vs the dotted-dim
            # separators between dynamic sections). Renders via the solid separator.
            lines.append(r.border_separator(spec.width, ups=row.ups, downs=row.downs, fill=spec.fill, labels=tuple(row.labels)))
        elif row.kind == 'separator_dim':
            lines.append(r.border_separator_dim(spec.width, downs=row.downs, ups=row.ups, fill=spec.fill, pill=row.pill, pill_edge=row.pill_edge, labels=tuple(row.labels)))
        elif row.kind == 'content':
            lines.append(r.border_line(row.content, spec.width, fill=spec.fill, bg_lead=row.bg_lead, bg_trail=row.bg_trail, pill_flush=row.pill_flush, right_pill=row.right_pill))
    return lines
