"""Tests for the tool-counts row: the Renderer helper and build_wide wiring."""

import json
from pathlib import Path

import pytest

import yas.layout as layout
import yas.renderer as renderer_mod
import yas.session as session_mod
import yas.info.subagents as subagents_mod
import yas.info.tasks as tasks_mod
import yas.info.skills as skills_mod
import yas.info.openspec as openspec_mod
from helper import strip_ansi
from yas.config import Config
from yas.constants import FAINT, TOOL_COUNTS_LABEL
from yas.info import SessionView
from yas.info.toolcounts import ToolCounts
from yas.render.text import _visible_width, superscript
from yas.tokens import TickRecord, TokenLog

_r = renderer_mod.Renderer()
SESSION = Path(__file__).parent.parent / 'ops' / 'session-info-example.json'


def _session() -> session_mod.SessionInfo:
    return session_mod.SessionInfo.from_dict(json.loads(SESSION.read_text()))


def _view(cfg: Config | None = None) -> SessionView:
    return SessionView(_session(), cfg if cfg is not None else Config())


def _tick() -> TickRecord:
    return TickRecord(token_log=TokenLog(), day_cost=0.0, tok_rate=0)


def _silence_dynamic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subagents_mod.RunningSubagents, 'from_session',
                        classmethod(lambda cls, sid, pdir: subagents_mod.RunningSubagents(subagents=[])))
    monkeypatch.setattr(tasks_mod.TaskList, 'from_session',
                        classmethod(lambda cls, path: tasks_mod.TaskList(tasks=[], last_event_ts=0.0)))
    monkeypatch.setattr(skills_mod.LoadedSkills, 'from_transcript',
                        classmethod(lambda cls, path: skills_mod.LoadedSkills(names=[])))
    monkeypatch.setattr(openspec_mod.OpenSpec, 'from_cwd',
                        classmethod(lambda cls, cwd: openspec_mod.OpenSpec(changes=[])))
    monkeypatch.setattr(session_mod.Workspace, 'plugins', property(lambda self: ''))


def _content_texts(spec: layout.LayoutSpec) -> str:
    return ' '.join(strip_ansi(r.content) for r in spec.rows if r.kind == 'content')


# ---------------------------------------------------------------------------
# Renderer.tool_counts_row helper
# ---------------------------------------------------------------------------

def test_helper_format_and_faint_on_sub() -> None:
    out = _r.tool_counts_row({'Bash': (5, 12)}, 100)
    assert 'Bash 5/12' in strip_ansi(out)
    assert FAINT in out, 'sub value must be SGR-faint'


def test_helper_zero_sub_renders_both_sides() -> None:
    assert 'Edit 3/0' in strip_ansi(_r.tool_counts_row({'Edit': (3, 0)}, 100))


def test_helper_orders_by_combined_total_descending() -> None:
    plain = strip_ansi(_r.tool_counts_row(
        {'Bash': (5, 12), 'Read': (40, 8), 'Edit': (3, 0)}, 120))
    assert plain.index('Read') < plain.index('Bash') < plain.index('Edit')


def test_helper_alphabetical_tie_break() -> None:
    plain = strip_ansi(_r.tool_counts_row({'Glob': (2, 0), 'Edit': (2, 0)}, 120))
    assert plain.index('Edit') < plain.index('Glob')


def test_helper_respects_width() -> None:
    counts = {f'tool{i}': (i, i) for i in range(12)}
    out = _r.tool_counts_row(counts, 60)
    assert _visible_width(out) <= 60 - 4


def test_helper_overflow_counts_types_not_calls() -> None:
    # 10 tools, all uniform-width entries (3-char name, single-digit counts);
    # combined total = 9-i so order is to0..to9. At width 30 only the first two
    # entries fit; the +k marker must report unshown TYPES (8), not the summed
    # calls of the unshown tools (7+6+...+0 = 28).
    counts = {f'to{i}': (9 - i, 0) for i in range(10)}
    out    = strip_ansi(_r.tool_counts_row(counts, 30))
    shown  = sum(1 for i in range(10) if f'to{i} ' in out)
    assert shown == 2
    assert out.rstrip().endswith('+8')
    unshown_calls = sum(9 - i for i in range(shown, 10))
    assert unshown_calls != 8  # marker is a type count, not a call sum


# ---------------------------------------------------------------------------
# build_wide wiring
# ---------------------------------------------------------------------------

def test_row_present_in_wide(monkeypatch: pytest.MonkeyPatch) -> None:
    _silence_dynamic(monkeypatch)
    view = _view(Config(show_tool_uses=True))
    view.__dict__['tool_counts'] = ToolCounts({'Zbash': (5, 2), 'Aread': (8, 1)})
    spec = layout.build_wide(view, _tick(), 160, _r)
    texts = _content_texts(spec)
    assert 'Zbash' in texts and 'Aread' in texts
    # The tool row is the first dynamic section: its separator becomes the seam.
    assert [r.kind for r in spec.rows].count('separator_seam') == 1


def test_row_label_when_captions_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _silence_dynamic(monkeypatch)
    view = _view(Config(labels=True, show_tool_uses=True))
    view.__dict__['tool_counts'] = ToolCounts({'Zbash': (5, 2)})
    spec = layout.build_wide(view, _tick(), 160, _r)
    # The separator above the tool content row carries the plain caption.
    tool_idx = next(i for i, r in enumerate(spec.rows)
                    if r.kind == 'content' and 'Zbash' in strip_ansi(r.content))
    sep = spec.rows[tool_idx - 1]
    assert sep.kind in ('separator_seam', 'separator_dim')
    assert any(text == TOOL_COUNTS_LABEL for text, _ in sep.labels)
    # The rendered separator shows the superscript form of the caption.
    line = strip_ansi(layout.render_layout(spec, _r)[tool_idx - 1])
    assert superscript(TOOL_COUNTS_LABEL) in line


def test_zero_state_omits_row_and_separator(monkeypatch: pytest.MonkeyPatch) -> None:
    _silence_dynamic(monkeypatch)
    view = _view()
    view.__dict__['tool_counts'] = ToolCounts({})
    spec = layout.build_wide(view, _tick(), 140, _r)
    kinds = [r.kind for r in spec.rows]
    # No dynamic section at all -> no seam, box closes with the bottom border.
    assert 'separator_seam' not in kinds
    assert kinds[-1] == 'bottom_border'


def test_row_hidden_when_show_tool_uses_false(monkeypatch: pytest.MonkeyPatch) -> None:
    _silence_dynamic(monkeypatch)
    view = _view(Config(show_tool_uses=False))
    view.__dict__['tool_counts'] = ToolCounts({'Zbash': (5, 2), 'Aread': (8, 1)})
    spec = layout.build_wide(view, _tick(), 160, _r)
    kinds = [r.kind for r in spec.rows]
    assert 'Zbash' not in _content_texts(spec)
    # No dynamic section precedes it -> no seam, box closes with the bottom border.
    assert 'separator_seam' not in kinds
    assert kinds[-1] == 'bottom_border'


def test_row_absent_in_narrow_and_medium(monkeypatch: pytest.MonkeyPatch) -> None:
    _silence_dynamic(monkeypatch)
    counts = ToolCounts({'Zbash': (5, 2)})

    view_n = _view()
    view_n.__dict__['tool_counts'] = counts
    spec_n = layout.build_narrow(view_n, 50, _r)
    assert 'Zbash' not in _content_texts(spec_n)

    view_m = _view()
    view_m.__dict__['tool_counts'] = counts
    spec_m = layout.build_medium(view_m, 70, _r)
    assert 'Zbash' not in _content_texts(spec_m)


def test_row_directly_under_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tool row sits immediately after the tokens/cost content rows."""
    _silence_dynamic(monkeypatch)
    view = _view(Config(show_tool_uses=True))
    view.__dict__['tool_counts'] = ToolCounts({'Zbash': (5, 2)})
    spec = layout.build_wide(view, _tick(), 160, _r)
    tok_idx = max(i for i, r in enumerate(spec.rows)
                  if r.kind == 'content' and 't/m' in strip_ansi(r.content))
    tool_idx = next(i for i, r in enumerate(spec.rows)
                    if r.kind == 'content' and 'Zbash' in strip_ansi(r.content))
    # tokens content, then the seam separator, then the tool content row.
    assert tool_idx == tok_idx + 2
    assert spec.rows[tok_idx + 1].kind == 'separator_seam'
