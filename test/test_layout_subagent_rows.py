import json
import time
from pathlib import Path

import pytest

import yas.layout as layout
import yas.renderer as renderer_mod
import yas.session as session_mod
import yas.info.subagents as subagents_mod
from helper import strip_ansi
from yas.config import Config
from yas.constants import GLYPH_WF_DIVIDER, MIDDLE_DOT
from yas.info import SessionView
from yas.tokens import TickRecord, TokenLog

_r = renderer_mod.Renderer()
SESSION = (Path(__file__).parent.parent / 'ops'
           / 'session-info-example.json')


def _make_sub(agent_type: str = 'Explore', first_timestamp: float | None = None,
              model: str = 'claude-sonnet-4-6') -> subagents_mod.RunningSubagent:
    now = time.time()
    if first_timestamp is None:
        first_timestamp = now - 10
    return subagents_mod.RunningSubagent(
        agent_type      = agent_type,
        description     = 'test desc',
        billed_in       = 1000,
        output          = 100,
        first_timestamp = first_timestamp,
        model           = model,
        cache_read_in   = 0,
        total_input     = 1000,
        last_activity   = ('tool_use', 'Bash', {'command': 'pytest'}),
        mtime           = now - 5,
    )


def _inject(monkeypatch: pytest.MonkeyPatch, subs: list[subagents_mod.RunningSubagent]) -> None:
    monkeypatch.setattr(
        subagents_mod.RunningSubagents, 'from_session',
        classmethod(lambda cls, sid, pdir: subagents_mod.RunningSubagents(subagents=subs)),
    )


def _session() -> session_mod.SessionInfo:
    return session_mod.SessionInfo.from_dict(json.loads(SESSION.read_text()))


def _view(session=None) -> SessionView:
    if session is None:
        session = _session()
    return SessionView(session, Config())


def _tick() -> TickRecord:
    return TickRecord(token_log=TokenLog(), day_cost=0.0, tok_rate=0)


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


# 4.4.1 — three subagents at wide → 6 content rows
# NOTE: width is 110 (> 100 for twoline, but < TWO_COL_SUBAGENT_WIDTH=120), not
# 140, so this exercises the plain single-column stacked rendering rather than
# the paired two-column layout added for width >= 120 (see
# test_two_col_subagent_threshold below).
def test_three_subagents_wide_produces_six_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    subs = [_make_sub('alpha'), _make_sub('beta'), _make_sub('gamma')]
    _inject(monkeypatch, subs)
    spec = layout.build_wide(_view(), _tick(), 110, _r)
    sub_rows = _subagent_block_rows(spec, ('alpha', 'beta', 'gamma'))
    assert len(sub_rows) == 6


# 4.4.2 — three subagents at narrow → 3 content rows
def test_three_subagents_narrow_produces_three_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    subs = [_make_sub('alpha'), _make_sub('beta'), _make_sub('gamma')]
    _inject(monkeypatch, subs)
    spec = layout.build_narrow(_view(), 80, _r)
    sub_rows = _content_rows_starting_with(spec, '▶')
    assert len(sub_rows) == 3


# 4.4.3 — ordering follows first_timestamp ascending (from_session sorts; inject mirrors that)
# NOTE: width is 110 (> 100 for twoline, but < TWO_COL_SUBAGENT_WIDTH=120) to
# stay in the single-column stacked rendering this test targets; see
# test_two_col_subagent_column_major_ordering below for ordering within the
# paired two-column layout.
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
        classmethod(lambda cls, sid, pdir: subagents_mod.RunningSubagents(subagents=subs_sorted)),
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
    assert len(sub_rows) == 6


# 4.4.6 — the 1M context-window variant marker surfaces through build_wide
def test_1m_variant_suffix_renders_in_wide_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    # A subagent on the 1M-token context variant surfaces an `[1m]` suffix after
    # its model bucket in the full layout; a plain subagent shows no suffix.
    variant = _make_sub('opus-worker',   model='claude-opus-4-8[1m]')
    plain   = _make_sub('sonnet-worker', model='claude-sonnet-4-6')
    _inject(monkeypatch, [variant, plain])
    spec = layout.build_wide(_view(), _tick(), 110, _r)
    text = '\n'.join(
        strip_ansi(row.content) for row in spec.rows if row.kind == 'content'
    )
    assert 'opus[1m]' in text     # variant subagent carries the suffix
    assert 'sonnet[1m]' not in text  # plain subagent does not


# 4.4.7 — a MIXED cohort ('opus[1m]' beside plain 'sonnet') shares one model
# column: every row rjusts its model label to the cohort-wide max width, so the
# model field's LEFT edge lines up across rows (the whole point of threading
# `model_field_w` through the cohort). Without the shared width the 8-col
# 'opus[1m]' field and the 6-col 'sonnet' field start 2 columns apart.
def test_mixed_cohort_model_field_shares_left_edge(monkeypatch: pytest.MonkeyPatch) -> None:
    variant = _make_sub('opus-worker',   model='claude-opus-4-8[1m]')
    plain   = _make_sub('sonnet-worker', model='claude-sonnet-4-6')
    _inject(monkeypatch, [variant, plain])
    # width 110 → twoline identity rows; the model field is the rightmost cluster
    # segment, flush to the content edge and preceded by a MIDDLE_DOT separator.
    spec = layout.build_wide(_view(), _tick(), 110, _r)

    # The two line-1 identity rows (continuation rows start with the `└` elbow).
    identity = [
        strip_ansi(row.content) for row in spec.rows
        if row.kind == 'content'
        and not strip_ansi(row.content).lstrip().startswith('└')
        and ('opus-worker' in strip_ansi(row.content) or 'sonnet-worker' in strip_ansi(row.content))
    ]
    assert len(identity) == 2

    # The model field begins one column after the final MIDDLE_DOT separator
    # (`· ` + rjust'd label). A shared field width puts that left edge at the
    # same column for both rows.
    field_lefts = [line.rfind(MIDDLE_DOT) + 2 for line in identity]
    assert field_lefts[0] == field_lefts[1]

    # And both fields end flush at the same content edge, so equal left edge ⇒
    # equal field width (the field of the longer 'opus[1m]' label = 8 cols).
    field_widths = {len(line) - fl for line, fl in zip(identity, field_lefts)}
    assert field_widths == {8}


# ---------------------------------------------------------------------------
# Two-column plain subagent cohort (TWO_COL_SUBAGENT_WIDTH threshold, D-series
# precedent shared with the workflow two-column layout).
# ---------------------------------------------------------------------------

def _sub_rows(spec: layout.LayoutSpec, subs: list[subagents_mod.RunningSubagent]) -> list[layout.RowSpec]:
    """Content rows that mention at least one of the given subagents' types."""
    return [
        row for row in spec.rows
        if row.kind == 'content' and any(s.agent_type in strip_ansi(row.content) for s in subs)
    ]


def test_two_col_subagent_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """At width >= TWO_COL_SUBAGENT_WIDTH (120) with >= 2 visible subagents, the
    plain (non-workflow) subagent cohort collapses into paired rows (roughly
    ceil(n/2) instead of n), with the dashed ``┊`` divider embedded at
    ``workflow_divider_col(width)`` in every paired row. Just below the
    threshold it stays single-column."""
    subs = [_make_sub(f'agent{i}') for i in range(1, 5)]  # 4 agents
    _inject(monkeypatch, subs)

    spec = layout.build_wide(_view(), _tick(), 120, _r)
    paired_rows = _sub_rows(spec, subs)
    assert len(paired_rows) == 2  # ceil(4/2)
    div_col = layout.workflow_divider_col(120)
    for row in paired_rows:
        line = strip_ansi(row.content)
        assert len(line) > div_col - 1
        assert line[div_col - 3] == GLYPH_WF_DIVIDER

    # Just below the threshold: single-column stacked rows, no row pairs two
    # agents together, and every agent is still present somewhere.
    stacked_spec = layout.build_wide(_view(), _tick(), 119, _r)
    stacked_rows = _sub_rows(stacked_spec, subs)
    assert not any(
        sum(s.agent_type in strip_ansi(row.content) for s in subs) >= 2
        for row in stacked_rows
    )
    for s in subs:
        assert any(s.agent_type in strip_ansi(row.content) for row in stacked_rows)


def test_two_col_subagent_column_major_ordering(monkeypatch: pytest.MonkeyPatch) -> None:
    """5 visible subagents at width 120 fill column-major: left column top-to-
    bottom is agents 1,2,3 and right column top-to-bottom is agents 4,5 — the
    first row pairs agent1(left)/agent4(right), NOT agent1(left)/agent2(right).
    The workflow cohort's two-column block fills the same way (see
    test_two_col_workflow_column_major_ordering in test_workflow_cohort.py).
    The trailing odd agent (agent3) renders left-only with a trailing
    divider and a blank right cell."""
    subs = [_make_sub(f'agent{i}') for i in range(1, 6)]  # 5 agents, distinct types
    _inject(monkeypatch, subs)

    spec = layout.build_wide(_view(), _tick(), 120, _r)
    rows = [strip_ansi(row.content) for row in _sub_rows(spec, subs)]
    assert len(rows) == 3  # ceil(5/2): 2 full pairs + 1 odd trailing row

    row0, row1, row2 = rows

    # Column-major: row0 = agent1|agent4, NOT agent1|agent2 (row-major would).
    assert 'agent1' in row0 and 'agent4' in row0
    assert 'agent2' not in row0 and 'agent5' not in row0

    assert 'agent2' in row1 and 'agent5' in row1
    assert 'agent1' not in row1 and 'agent4' not in row1

    # Odd trailing row: left-only agent3, no right agent, trailing divider.
    assert 'agent3' in row2
    for other in ('agent1', 'agent2', 'agent4', 'agent5'):
        assert other not in row2
    div_col = layout.workflow_divider_col(120)
    assert len(row2) >= div_col - 2
    assert row2[div_col - 3] == GLYPH_WF_DIVIDER
