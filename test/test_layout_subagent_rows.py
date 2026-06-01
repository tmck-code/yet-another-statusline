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
from yas.info import SessionView
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


# 4.4.1 — three subagents at wide → 6 content rows
def test_three_subagents_wide_produces_six_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    subs = [_make_sub('alpha'), _make_sub('beta'), _make_sub('gamma')]
    _inject(monkeypatch, subs)
    spec = layout.build_wide(_view(), _tick(), 140, _r)
    sub_rows = _content_rows_starting_with(spec, '▶', '   └')
    assert len(sub_rows) == 6


# 4.4.2 — three subagents at narrow → 3 content rows
def test_three_subagents_narrow_produces_three_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    subs = [_make_sub('alpha'), _make_sub('beta'), _make_sub('gamma')]
    _inject(monkeypatch, subs)
    spec = layout.build_narrow(_view(), 80, _r)
    sub_rows = _content_rows_starting_with(spec, '▶')
    assert len(sub_rows) == 3


# 4.4.3 — ordering follows first_timestamp ascending (from_session sorts; inject mirrors that)
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
    spec = layout.build_wide(_view(), _tick(), 140, _r)
    identity_rows = [row for row in spec.rows if row.kind == 'content' and '▶' in strip_ansi(row.content)]
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
    sub_rows = _content_rows_starting_with(spec, '▶', '   └')
    assert len(sub_rows) == 6
