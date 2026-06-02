import json
import time
from pathlib import Path

import pytest

import yas.layout as layout
import yas.renderer as renderer_mod
import yas.session as session_mod
import yas.info.subagents as subagents_mod
import yas.info.tasks as tasks_mod
import yas.info.skills as skills_mod
import yas.info.openspec as openspec_mod
from yas.config import Config
from yas.info import SessionView
from yas.tokens import TickRecord, TokenLog

_r = renderer_mod.Renderer()
SESSION = (Path(__file__).parent.parent / 'ops'
           / 'session-info-example.json')


def _session() -> session_mod.SessionInfo:
    return session_mod.SessionInfo.from_dict(json.loads(SESSION.read_text()))


def _view(session=None) -> SessionView:
    if session is None:
        session = _session()
    return SessionView(session, Config())


def _tick() -> TickRecord:
    return TickRecord(token_log=TokenLog(), day_cost=0.0, tok_rate=0)


def _make_sub() -> subagents_mod.RunningSubagent:
    now = time.time()
    return subagents_mod.RunningSubagent(
        agent_type      = 'Explore',
        description     = 'test desc',
        billed_in       = 1000,
        output          = 100,
        first_timestamp = now - 10,
        model           = 'claude-sonnet-4-6',
        cache_read_in   = 0,
        total_input     = 1000,
        last_activity   = ('tool_use', 'Bash', {'command': 'pytest'}),
        mtime           = now - 5,
    )


def _silence_dynamic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every conditional (dynamic) section so token stats are last.

    Each dynamic section below the token stats reads the real machine (the
    transcript, ~/.claude/settings.json, the cwd's openspec dir, ...). Left
    alone, the host's own plugins/skills/tasks leak in and synthesise a
    dynamic row + seam, so neutralise every source — including
    Workspace.plugins, which reads CLAUDE_DIR/settings.json directly.
    """
    monkeypatch.setattr(subagents_mod.RunningSubagents, 'from_session',
                        classmethod(lambda cls, sid, pdir: subagents_mod.RunningSubagents(subagents=[])))
    monkeypatch.setattr(tasks_mod.TaskList, 'from_session',
                        classmethod(lambda cls, path: tasks_mod.TaskList(tasks=[], last_event_ts=0.0)))
    monkeypatch.setattr(skills_mod.LoadedSkills, 'from_transcript',
                        classmethod(lambda cls, path: skills_mod.LoadedSkills(names=[])))
    monkeypatch.setattr(openspec_mod.OpenSpec, 'from_cwd',
                        classmethod(lambda cls, cwd: openspec_mod.OpenSpec(changes=[])))
    monkeypatch.setattr(session_mod.Workspace, 'plugins', property(lambda self: ''))


def _kinds(spec: layout.LayoutSpec) -> list[str]:
    return [row.kind for row in spec.rows]


def test_seam_present_with_dynamic_section(monkeypatch: pytest.MonkeyPatch) -> None:
    _silence_dynamic(monkeypatch)
    monkeypatch.setattr(subagents_mod.RunningSubagents, 'from_session',
                        classmethod(lambda cls, sid, pdir: subagents_mod.RunningSubagents(subagents=[_make_sub()])))
    spec = layout.build_wide(_view(), _tick(), 140, _r)
    assert _kinds(spec).count('separator_seam') == 1


def test_no_seam_without_dynamic_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    _silence_dynamic(monkeypatch)
    spec = layout.build_wide(_view(), _tick(), 140, _r)
    assert 'separator_seam' not in _kinds(spec)
    assert _kinds(spec)[-1] == 'bottom_border'


def test_seam_is_first_separator_below_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    _silence_dynamic(monkeypatch)
    monkeypatch.setattr(subagents_mod.RunningSubagents, 'from_session',
                        classmethod(lambda cls, sid, pdir: subagents_mod.RunningSubagents(subagents=[_make_sub()])))
    spec = layout.build_wide(_view(), _tick(), 140, _r)
    seam_idx = next(i for i, row in enumerate(spec.rows) if row.kind == 'separator_seam')
    # Seam threads up-elbows into the token-stat vsep columns.
    assert spec.rows[seam_idx].ups
    # The very next row is the dynamic content the seam introduces.
    assert spec.rows[seam_idx + 1].kind == 'content'


def test_seam_renders_solid_not_heavy(monkeypatch: pytest.MonkeyPatch) -> None:
    from helper import strip_ansi
    _silence_dynamic(monkeypatch)
    monkeypatch.setattr(subagents_mod.RunningSubagents, 'from_session',
                        classmethod(lambda cls, sid, pdir: subagents_mod.RunningSubagents(subagents=[_make_sub()])))
    spec = layout.build_wide(_view(), _tick(), 140, _r)
    seam_idx = next(i for i, row in enumerate(spec.rows) if row.kind == 'separator_seam')
    seam = strip_ansi(layout.render_layout(spec, _r)[seam_idx])
    assert seam[0] == '├' and seam[-1] == '┤'   # single-line box ends
    assert '─' in seam and '┴' in seam          # solid rule, up-elbows into token vseps
    assert '━' not in seam and '┷' not in seam  # not the heavy variant


def test_cache_countdown_none_single_elbow(monkeypatch: pytest.MonkeyPatch) -> None:
    """When cache_countdown is None the top border and separator_dim each carry only one elbow."""
    _silence_dynamic(monkeypatch)
    view = _view()
    view.__dict__['cache_countdown'] = None
    spec = layout.build_wide(view, _tick(), 160, _r)
    top_border    = spec.rows[0]
    separator_dim = spec.rows[2]
    assert top_border.kind == 'top_border'
    assert separator_dim.kind == 'separator_dim'
    assert len(top_border.downs) == 1,  f'expected 1 down, got {top_border.downs}'
    assert len(separator_dim.ups) == 1, f'expected 1 up, got {separator_dim.ups}'


def test_cache_countdown_width_shed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cache section sheds at the exact threshold without extra path truncation.

    The shed condition is: (width-4) - vsep_w - helper_w - cache_section_w - right_w < 5.
    At min_keep width the path budget is exactly 5 (cache kept); one col narrower it sheds.
    """
    from yas.constants import GLYPH_CACHE
    from yas.render.text import _visible_width
    _silence_dynamic(monkeypatch)

    countdown = (187.0, 38)
    vsep_w    = 5
    sess      = _session()

    # Measure renderer geometry so threshold is exact rather than hand-coded.
    helper_text, _, right_w = _r.model_right_section(
        sess.model_name,
        sess.model_thinking,
        sess.rate_limits,
        '',
        fast_mode=sess.fast_mode,
    )
    helper_w        = _visible_width(helper_text)
    _, cache_w      = _r.cache_section(*countdown)
    cache_section_w = vsep_w + cache_w
    # Minimum width where the cache section is NOT shed (path budget == 5).
    min_keep = 5 + vsep_w + helper_w + cache_section_w + right_w + 4

    # At the shed boundary: cache absent, single elbow.
    view_shed = _view()
    view_shed.__dict__['cache_countdown'] = countdown
    spec_shed  = layout.build_wide(view_shed, _tick(), min_keep - 1, _r)
    lines_shed = layout.render_layout(spec_shed, _r)
    assert not any(GLYPH_CACHE in ln for ln in lines_shed), \
        f'cache glyph present at width={min_keep - 1} (should be shed)'
    assert len(spec_shed.rows[0].downs) == 1, \
        f'expected 1 top_border down at shed width, got {spec_shed.rows[0].downs}'

    # 20 cols wider: cache present, two elbows.
    view_keep = _view()
    view_keep.__dict__['cache_countdown'] = countdown
    spec_keep  = layout.build_wide(view_keep, _tick(), min_keep + 20, _r)
    lines_keep = layout.render_layout(spec_keep, _r)
    assert any(GLYPH_CACHE in ln for ln in lines_keep), \
        f'cache glyph absent at width={min_keep + 20} (should be kept)'
    assert len(spec_keep.rows[0].downs) == 2, \
        f'expected 2 top_border downs at keep width, got {spec_keep.rows[0].downs}'


def test_narrow_and_medium_no_cache_countdown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neither narrow nor medium layouts ever render the cache countdown glyph."""
    from yas.constants import GLYPH_CACHE
    _silence_dynamic(monkeypatch)

    view_n = _view()
    view_n.__dict__['cache_countdown'] = (187.0, 38)
    spec_narrow = layout.build_narrow(view_n, 50, _r)
    for ln in layout.render_layout(spec_narrow, _r):
        assert GLYPH_CACHE not in ln, f'cache glyph found in narrow render: {ln!r}'

    view_m = _view()
    view_m.__dict__['cache_countdown'] = (187.0, 38)
    spec_medium = layout.build_medium(view_m, 70, _r)
    for ln in layout.render_layout(spec_medium, _r):
        assert GLYPH_CACHE not in ln, f'cache glyph found in medium render: {ln!r}'


def test_only_first_dynamic_separator_is_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    # Two dynamic sections (skills + subagents): first separator is the seam,
    # the separator between them stays a normal dotted-dim separator.
    _silence_dynamic(monkeypatch)
    monkeypatch.setattr(skills_mod.LoadedSkills, 'from_transcript',
                        classmethod(lambda cls, path: skills_mod.LoadedSkills(names=['x:demo'])))
    monkeypatch.setattr(subagents_mod.RunningSubagents, 'from_session',
                        classmethod(lambda cls, sid, pdir: subagents_mod.RunningSubagents(subagents=[_make_sub()])))
    spec = layout.build_wide(_view(), _tick(), 140, _r)
    kinds = _kinds(spec)
    assert kinds.count('separator_seam') == 1
    seam_idx = kinds.index('separator_seam')
    # A later separator (between skills and subagents) is normal, not a seam.
    assert 'separator_dim' in kinds[seam_idx + 1:]


# ---------------------------------------------------------------------------
# Cache countdown section tests (6.4)
# ---------------------------------------------------------------------------

def test_cache_countdown_content_row_contains_glyph_and_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from helper import strip_ansi
    from yas.constants import GLYPH_CACHE
    _silence_dynamic(monkeypatch)
    view = _view()
    # Inject a known cache_countdown bypassing the cached_property.
    view.__dict__['cache_countdown'] = (187.0, 38)
    spec = layout.build_wide(view, _tick(), 160, _r)
    # The path/model row is the first content row (index 1 after top_border).
    top_border_idx = next(i for i, row in enumerate(spec.rows) if row.kind == 'top_border')
    path_row = spec.rows[top_border_idx + 1]
    assert path_row.kind == 'content'
    visible = strip_ansi(path_row.content)
    assert GLYPH_CACHE in visible
    assert '3m07s' in visible


def test_cache_countdown_divider_threaded_into_borders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _silence_dynamic(monkeypatch)
    view = _view()
    view.__dict__['cache_countdown'] = (187.0, 38)
    spec = layout.build_wide(view, _tick(), 160, _r)

    top_border_idx    = next(i for i, row in enumerate(spec.rows) if row.kind == 'top_border')
    sep_dim_idx       = next(
        i for i, row in enumerate(spec.rows)
        if row.kind == 'separator_dim' and i > top_border_idx
    )
    top_row  = spec.rows[top_border_idx]
    sep_row  = spec.rows[sep_dim_idx]

    # Both the top_border downs and the separator_dim ups must carry at least
    # two elbow columns — path_div_col and cache_div_col.
    assert len(top_row.downs) >= 2, 'top_border should have >= 2 downs when cache shown'
    assert len(sep_row.ups)   >= 2, 'separator_dim should have >= 2 ups when cache shown'

    # cache_div_col must appear in both tuples (it's the second entry).
    cache_div_col = top_row.downs[-1]
    assert cache_div_col in sep_row.ups
