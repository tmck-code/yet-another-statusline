import json
import re
import time
from pathlib import Path

import pytest

import yas.layout as layout
import yas.renderer as renderer_mod
import yas.session as session_mod
import yas.info.subagents as subagents_mod
from helper import strip_ansi
from yas.config import Config
from yas.constants import ICON_TERMINAL
from yas.info import SessionView
from yas.info.main_activity import MainActivity
from yas.info.shell_commands import MAIN_AGENT_ID, AgentUsage
from yas.info.toolcounts import ToolCounts
from yas.tokens import TickRecord, TokenLog

_r = renderer_mod.Renderer()
SESSION = (Path(__file__).parent.parent / 'ops'
           / 'session-info-example.json')


def _make_sub(agent_type: str = 'Explore', first_timestamp: float | None = None) -> subagents_mod.RunningSubagent:
    now = time.time()
    if first_timestamp is None:
        first_timestamp = now - 10
    return subagents_mod.RunningSubagent(
        agent_type      = agent_type,
        description     = 'test desc',
        billed_in       = 1000,
        output          = 100,
        first_timestamp = first_timestamp,
        model           = 'claude-sonnet-4-6',
        cache_read_in   = 0,
        total_input     = 1000,
        last_activity   = ('tool_use', 'Bash', {'command': 'pytest'}),
        mtime           = now - 5,
    )


def _inject(monkeypatch: pytest.MonkeyPatch, subs: list[subagents_mod.RunningSubagent]) -> None:
    monkeypatch.setattr(
        subagents_mod.RunningSubagents, 'from_session',
        classmethod(lambda cls, sid, pdir, **kwargs: subagents_mod.RunningSubagents(subagents=subs)),
    )


def _session() -> session_mod.SessionInfo:
    return session_mod.SessionInfo.from_dict(json.loads(SESSION.read_text()))


def _view(session=None) -> SessionView:
    if session is None:
        session = _session()
    return SessionView(session, Config())


def _tick() -> TickRecord:
    return TickRecord(token_log=TokenLog(), day_cost=0.0, tok_rate=0)


def _content_lines(spec: layout.LayoutSpec) -> list[str]:
    return [strip_ansi(row.content) for row in spec.rows if row.kind == 'content']


def _specs(view: SessionView) -> list[layout.LayoutSpec]:
    return [
        layout.build_narrow(view, 80, _r),
        layout.build_medium(view, 120, _r),
        layout.build_wide(view, _tick(), 140, _r),
    ]


def _content_rows_starting_with(spec: layout.LayoutSpec, *prefixes: str) -> list[layout.RowSpec]:
    return [
        row for row in spec.rows
        if row.kind == 'content' and any(strip_ansi(row.content).startswith(p) for p in prefixes)
    ]


def _subagent_block_rows(spec: layout.LayoutSpec, types: tuple[str, ...]) -> list[layout.RowSpec]:
    """Content rows for a markerless two-line cohort: identity rows carry the
    agent type, continuation rows start with the `└` elbow."""
    return [
        row for row in spec.rows
        if row.kind == 'content' and (
            any(t in strip_ansi(row.content) for t in types)
            or strip_ansi(row.content).lstrip().startswith('└')
        )
    ]


# 4.4.1 — three subagents at wide -> one row per subagent
# NOTE: width is 110 (> 100 for twoline, but < TWO_COL_WF_WIDTH=120). The wide
# plain (non-workflow) subagent cohort always renders as tree-single rows —
# one line per agent, with the current-activity snippet embedded as a
# trailing column rather than a separate continuation line — so the count is
# 3, not 6 (the pre-tree-only flat form's two-lines-per-agent count).
def test_three_subagents_wide_produces_three_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    subs = [_make_sub('alpha'), _make_sub('beta'), _make_sub('gamma')]
    _inject(monkeypatch, subs)
    spec = layout.build_wide(_view(), _tick(), 110, _r)
    sub_rows = _subagent_block_rows(spec, ('alpha', 'beta', 'gamma'))
    assert len(sub_rows) == 3


# 4.4.2 — three subagents at narrow → 3 content rows
def test_three_subagents_narrow_produces_three_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    subs = [_make_sub('alpha'), _make_sub('beta'), _make_sub('gamma')]
    _inject(monkeypatch, subs)
    spec = layout.build_narrow(_view(), 80, _r)
    sub_rows = _subagent_block_rows(spec, ('alpha', 'beta', 'gamma'))
    assert len(sub_rows) == 3


# 4.4.3 — ordering follows first_timestamp ascending (from_session sorts; inject mirrors that)
# NOTE: width is 110 (> 100 for twoline) to exercise the wide (tree-single)
# subagent-cohort rendering this test targets.
def test_ordering_preserved_wide(monkeypatch: pytest.MonkeyPatch) -> None:
    now = time.time()
    subs_unsorted = [
        _make_sub('late',  first_timestamp=now - 5),
        _make_sub('early', first_timestamp=now - 15),
        _make_sub('mid',   first_timestamp=now - 10),
    ]
    # from_session returns subagents sorted by first_timestamp; mirror that in the mock
    subs_sorted = sorted(subs_unsorted, key=lambda s: s.first_timestamp)
    monkeypatch.setattr(
        subagents_mod.RunningSubagents, 'from_session',
        classmethod(lambda cls, sid, pdir, **kwargs: subagents_mod.RunningSubagents(subagents=subs_sorted)),
    )
    spec = layout.build_wide(_view(), _tick(), 110, _r)
    # markerless two-line identity rows carry the agent type (continuation rows
    # start with the `└` elbow and are excluded here)
    identity_rows = [
        row for row in spec.rows
        if row.kind == 'content'
        and not strip_ansi(row.content).lstrip().startswith('└')
        and any(s.agent_type in strip_ansi(row.content) for s in subs_sorted)
    ]
    for i, expected_sub in enumerate(subs_sorted):
        assert expected_sub.agent_type in strip_ansi(identity_rows[i].content)


# 4.4.4 — narrow: subagent_row at ≤100 width produces no \n (single line)
def test_subagent_row_narrow_no_newline() -> None:
    sub = _make_sub()
    out = _r.subagent_row(sub, 80)
    assert '\n' not in out


# 4.4.5 — medium also emits two rows per subagent at width > 100
def test_three_subagents_medium_produces_six_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    subs = [_make_sub('alpha'), _make_sub('beta'), _make_sub('gamma')]
    _inject(monkeypatch, subs)
    spec = layout.build_medium(_view(), 120, _r)
    sub_rows = _subagent_block_rows(spec, ('alpha', 'beta', 'gamma'))
    # Six subagent lines plus the main row's continuation line (its identity
    # line carries 'main' rather than a subagent type, so the helper does not
    # count it).
    assert len(sub_rows) == 7


# The two-column plain subagent cohort (old TWO_COL_SUBAGENT_WIDTH threshold)
# has been removed: the wide plain subagent cohort now always renders tree-
# single, single-column (a column-major pairing would tear parent/child
# branches apart across the two columns) — see
# test_two_col_workflow_column_major_ordering in test_workflow_cohort.py for
# the still-live workflow-cohort two-column equivalent.


def test_hour_long_duration_does_not_shift_the_front_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A timer that has rolled to H:MM:SS is two columns wider than a fresh
    # M:SS one. The cohort must right-justify every row's duration to the
    # measured max, or the long row's elbow/name/description drift right of
    # its siblings (the ragged tree this regression guards).
    now = time.time()
    short = _make_sub('short', first_timestamp=now - 64)
    long = _make_sub('long', first_timestamp=now - (6 * 3600 + 28 * 60 + 32))
    long.description = 'long desc'
    _inject(monkeypatch, [short, long])
    for spec in (layout.build_wide(_view(), _tick(), 160, _r), layout.build_narrow(_view(), 80, _r)):
        rows = [strip_ansi(row.content) for row in spec.rows if row.kind == 'content']
        short_row = next(r for r in rows if 'short' in r)
        long_row = next(r for r in rows if 'long' in r)
        assert short_row.index('short') == long_row.index('long')


def _content_blocks(spec: layout.LayoutSpec) -> list[list[str]]:
    'Runs of consecutive content rows, ANSI-stripped.'
    blocks: list[list[str]] = []
    block: list[str] = []
    for row in spec.rows:
        if row.kind == 'content':
            block.append(strip_ansi(row.content))
        elif block:
            blocks.append(block)
            block = []
    if block:
        blocks.append(block)
    return blocks


def _main_block(spec: layout.LayoutSpec) -> list[str]:
    'The content block that starts with the synthetic main row (name `main`).'
    return next(
        block for block in _content_blocks(spec)
        if re.search(r'\d+:\d\d\s+main\b', block[0])
    )


def test_main_row_is_first_in_narrow_medium_and_wide(monkeypatch: pytest.MonkeyPatch) -> None:
    _inject(monkeypatch, [_make_sub('alpha')])
    view = _view()
    for spec in _specs(view):
        block = _main_block(spec)
        alpha_i = next(i for i, line in enumerate(block) if 'alpha' in line)
        assert alpha_i > 0
        assert 'main' in block[0]


def test_main_row_drawn_when_no_subagents(monkeypatch: pytest.MonkeyPatch) -> None:
    _inject(monkeypatch, [])
    view = _view()
    for spec in _specs(view):
        block = _main_block(spec)
        assert block
        assert any('sonnet' in line for line in block)
        assert any('main' in line for line in block)
        assert not any(ICON_TERMINAL in line or 'shell commands' in line for line in block)


def test_main_row_name_is_main(monkeypatch: pytest.MonkeyPatch) -> None:
    _inject(monkeypatch, [])
    spec = layout.build_wide(_view(), _tick(), 140, _r)
    main_line = _main_block(spec)[0]
    assert 'main' in main_line
    assert 'sonnet' in main_line


def _activity_view(monkeypatch: pytest.MonkeyPatch, activity: MainActivity,
                   usage: AgentUsage | None = None) -> SessionView:
    _inject(monkeypatch, [])
    view = _view()
    view.__dict__['main_activity'] = activity
    view.__dict__['agent_usage'] = {} if usage is None else {MAIN_AGENT_ID: usage}
    return view


def test_main_row_shows_thinking(monkeypatch: pytest.MonkeyPatch) -> None:
    now = time.time()
    view = _activity_view(monkeypatch, MainActivity(
        first_ts=now - 30, kind='thinking', since=now - 30,
        activity=('thinking', '', {}),
    ))
    main = layout.regular_agent_cells(view, [])[0][0]
    assert main.agent_type == 'main'
    assert main.description == ''
    assert 'Thinking' in main.log_text
    assert main.last_activity == ('', '', {})
    lines = _content_lines(layout.build_narrow(view, 80, _r))
    assert any('Thinking' in line for line in lines)


def test_main_row_shows_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    usage = AgentUsage(cpu_percent=0.0, rss_kb=0, elapsed_s=120, waiting=True)
    view = _activity_view(monkeypatch, MainActivity(), usage)
    main = layout.regular_agent_cells(view, [])[0][0]
    assert main.agent_type == 'main'
    assert main.description == ''
    assert 'Waiting' in main.log_text
    lines = _content_lines(layout.build_narrow(view, 80, _r))
    assert any('Waiting' in line for line in lines)


def test_main_row_shows_bash_command_and_plus_n(monkeypatch: pytest.MonkeyPatch) -> None:
    usage = AgentUsage(cpu_percent=5.0, rss_kb=0, elapsed_s=20,
                       command='pytest -q', command_count=2)
    activity = MainActivity(kind='tool_use', activity=('tool_use', 'Bash', {'command': 'pytest -q'}))
    view = _activity_view(monkeypatch, activity, usage)
    main = layout.regular_agent_cells(view, [])[0][0]
    assert main.agent_type == 'main'
    assert main.description == ''
    assert main.last_activity == ('', '', {})
    assert main.log_text == 'Bash[pytest -q] +1'
    lines = _content_lines(layout.build_narrow(view, 80, _r))
    assert any('Bash[pytest -q] +1' in line for line in lines)


def test_main_row_shows_non_bash_tool_call(monkeypatch: pytest.MonkeyPatch) -> None:
    usage = AgentUsage(cpu_percent=5.0, rss_kb=0, elapsed_s=20, command='make demo')
    activity = MainActivity(kind='tool_use', activity=('tool_use', 'Read', {'file_path': 'x'}))
    view = _activity_view(monkeypatch, activity, usage)
    main = layout.regular_agent_cells(view, [])[0][0]
    assert main.agent_type == 'main'
    assert main.description == ''
    assert main.log_text == ''
    assert main.last_activity[1] == 'Read'
    lines = _content_lines(layout.build_narrow(view, 80, _r))
    assert any('Read' in line for line in lines)


def test_main_row_shows_text_message(monkeypatch: pytest.MonkeyPatch) -> None:
    message = "ok, I'll re-upload it"
    activity = MainActivity(kind='text', activity=('text', message, {}))
    view = _activity_view(monkeypatch, activity)
    main = layout.regular_agent_cells(view, [])[0][0]
    assert main.agent_type == 'main'
    assert main.log_text == ''
    assert main.last_activity == ('text', message, {})
    narrow = _content_lines(layout.build_narrow(view, 80, _r))
    wide = _content_lines(layout.build_wide(view, _tick(), 140, _r))
    assert any(message in line for line in narrow)
    assert any(message in line for line in wide)


def test_main_row_waiting_while_showing_text_message(monkeypatch: pytest.MonkeyPatch) -> None:
    message = "I'll wait here"
    activity = MainActivity(kind='text', activity=('text', message, {}))
    usage = AgentUsage(cpu_percent=0.0, rss_kb=0, elapsed_s=120, waiting=True)
    view = _activity_view(monkeypatch, activity, usage)
    main = layout.regular_agent_cells(view, [])[0][0]
    assert 'Waiting' in main.log_text
    assert main.last_activity == ('', '', {})
    lines = _content_lines(layout.build_narrow(view, 80, _r))
    assert any('Waiting' in line for line in lines)


def test_main_row_shows_stale_bash_call_without_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    activity = MainActivity(
        kind='tool_use', activity=('tool_use', 'Bash', {'command': 'pytest -q'}),
    )
    view = _activity_view(monkeypatch, activity)
    main = layout.regular_agent_cells(view, [])[0][0]
    assert main.log_text == ''
    assert main.last_activity[1] == 'Bash'
    lines = _content_lines(layout.build_narrow(view, 80, _r))
    assert any('Bash[pytest -q]' in line for line in lines)


def test_main_row_shows_its_own_loc_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    _inject(monkeypatch, [])
    view = _view()
    view.__dict__['tool_counts'] = ToolCounts(main_lines=(1234, 56))
    for spec in _specs(view):
        main_line = _main_block(spec)[0]
        assert '1.23K' in main_line and '56' in main_line
