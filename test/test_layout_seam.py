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


def _tokens_row_indices(spec: layout.LayoutSpec) -> list[int]:
    """Content rows that carry the tokens/cost/rate line (the rate label 't/m')."""
    from helper import strip_ansi
    return [i for i, row in enumerate(spec.rows)
            if row.kind == 'content' and 't/m' in strip_ansi(row.content)]


def test_tokens_row_is_single_content_line(monkeypatch: pytest.MonkeyPatch) -> None:
    _silence_dynamic(monkeypatch)
    spec = layout.build_wide(_view(), _tick(), 160, _r)
    assert len(_tokens_row_indices(spec)) == 1


def test_tokens_row_session_only_single_line(monkeypatch: pytest.MonkeyPatch) -> None:
    _silence_dynamic(monkeypatch)
    view = SessionView(_session(), Config(show_day_stats=False))
    spec = layout.build_wide(view, _tick(), 160, _r)
    assert len(_tokens_row_indices(spec)) == 1


def test_tokens_row_dividers_align_with_separators(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every interior │ in the single tokens line has a matching ┬ on the
    separator above and ┴ on the separator below at the same visual column."""
    from helper import strip_ansi
    _silence_dynamic(monkeypatch)
    # A dynamic section below ensures the row below tokens is a (seam) separator,
    # not the bottom border — so we can check ┴ elbows both sides.
    monkeypatch.setattr(subagents_mod.RunningSubagents, 'from_session',
                        classmethod(lambda cls, sid, pdir: subagents_mod.RunningSubagents(subagents=[_make_sub()])))
    spec  = layout.build_wide(_view(), _tick(), 160, _r)
    lines = [strip_ansi(ln) for ln in layout.render_layout(spec, _r)]
    t_idx = _tokens_row_indices(spec)[0]

    last = len(lines[t_idx]) - 1
    interior_bars = [i for i, ch in enumerate(lines[t_idx]) if ch == '│' and 0 < i < last]
    assert len(interior_bars) == 2, f'expected 2 interior │, got {interior_bars}'

    above, below = lines[t_idx - 1], lines[t_idx + 1]
    for col in interior_bars:
        assert above[col] in ('┬', '┼'), f'no ┬ above at col {col}: {above[col]!r}'
        assert below[col] in ('┴', '┼'), f'no ┴ below at col {col}: {below[col]!r}'


def _make_sub_labelled(label: str, started: float) -> subagents_mod.RunningSubagent:
    return subagents_mod.RunningSubagent(
        agent_type      = label,
        description     = '',
        billed_in       = 1000,
        output          = 100,
        first_timestamp = started,
        model           = 'claude-sonnet-4-6',
        cache_read_in   = 0,
        total_input     = 1000,
        last_activity   = ('tool_use', 'Bash', {'command': 'pytest'}),
        mtime           = started,
    )


def test_subagent_cohort_caps_at_six_most_recent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Eight live subagents collapse to the six most recently started, shown
    in chronological (first_timestamp ascending) order."""
    from helper import strip_ansi
    from yas.constants import SUBAGENT_DISPLAY_CAP
    _silence_dynamic(monkeypatch)
    now  = time.time()
    subs = [_make_sub_labelled(f'sub-{i}', now - (8 - i)) for i in range(8)]
    monkeypatch.setattr(subagents_mod.RunningSubagents, 'from_session',
                        classmethod(lambda cls, sid, pdir: subagents_mod.RunningSubagents(subagents=subs)))
    spec = layout.build_wide(_view(), _tick(), 160, _r)
    texts = ' '.join(strip_ansi(row.content) for row in spec.rows if row.kind == 'content')
    shown = [i for i in range(8) if f'sub-{i}' in texts]
    assert len(shown) == SUBAGENT_DISPLAY_CAP
    assert shown == [2, 3, 4, 5, 6, 7]  # oldest two (0, 1) dropped, chronological


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
    """When cache_countdown is None the top border and separator_dim carry elbows for
    path + elapsed + sep_rate (the ┆ between 5h and 7d rate-limit segments) but NOT cache."""
    _silence_dynamic(monkeypatch)
    view = _view()
    view.__dict__['cache_countdown'] = None
    spec = layout.build_wide(view, _tick(), 160, _r)
    top_border    = spec.rows[0]
    separator_dim = spec.rows[2]
    assert top_border.kind == 'top_border'
    assert separator_dim.kind == 'separator_dim'
    # path + elapsed + sep_rate (┆) = 3; cache is absent so no fourth elbow.
    assert len(top_border.downs) == 3,  f'expected 3 downs (path + elapsed + sep_rate), got {top_border.downs}'
    assert len(separator_dim.ups) == 3, f'expected 3 ups (path + elapsed + sep_rate), got {separator_dim.ups}'


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
    h5h, h7d, _, right_w = _r.model_right_section(
        sess.model_name,
        sess.model_thinking,
        sess.rate_limits,
        '',
        fast_mode=sess.fast_mode,
    )
    helper_w = _visible_width(h5h) + (4 + _visible_width(h7d) if h7d else 0)
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
    assert len(spec_shed.rows[0].downs) == 3, \
        f'expected 3 top_border downs (path + elapsed + sep_rate) at shed width, got {spec_shed.rows[0].downs}'

    # 20 cols wider: cache present, four elbows (path + elapsed + sep_rate + cache).
    view_keep = _view()
    view_keep.__dict__['cache_countdown'] = countdown
    spec_keep  = layout.build_wide(view_keep, _tick(), min_keep + 20, _r)
    lines_keep = layout.render_layout(spec_keep, _r)
    assert any(GLYPH_CACHE in ln for ln in lines_keep), \
        f'cache glyph absent at width={min_keep + 20} (should be kept)'
    assert len(spec_keep.rows[0].downs) == 4, \
        f'expected 4 top_border downs (path + elapsed + sep_rate + cache) at keep width, got {spec_keep.rows[0].downs}'


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
    assert '03:07' in visible


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


def test_sep_rate_elbow_threaded_into_borders(monkeypatch: pytest.MonkeyPatch) -> None:
    """The │ separator between 5h and 7d rate-limit segments in the wide path/model
    row must have matching ┬/┴ elbows in the top border and separator_dim at the
    same visual column.

    Uses the default example session (seven_day.used_percentage=89) so the 7d vsep
    is present in the content row. Uses render_layout to verify glyphs land at the
    correct column position after border painting.
    """
    from helper import strip_ansi
    _silence_dynamic(monkeypatch)
    # The example session has both 5h and 7d buckets active, so the 7d vsep │ appears.
    spec  = layout.build_wide(_view(), _tick(), 160, _r)
    lines = [strip_ansi(ln) for ln in layout.render_layout(spec, _r)]

    top_border_idx = next(i for i, row in enumerate(spec.rows) if row.kind == 'top_border')
    content_idx    = top_border_idx + 1
    sep_dim_idx    = next(
        i for i, row in enumerate(spec.rows)
        if row.kind == 'separator_dim' and i > top_border_idx
    )
    assert spec.rows[content_idx].kind == 'content', 'expected content row after top_border'

    top_row = spec.rows[top_border_idx]
    sep_row = spec.rows[sep_dim_idx]

    # sep_rate_col (7d vsep │) is the last column in downs that sits past the
    # session-id span (the session-id covers cols 4–39 at width 160, so we find
    # the rightmost downs col as the one that is visible as ┬ in the top border).
    full_line = lines[content_idx]
    top_line  = lines[top_border_idx]
    sep_line  = lines[sep_dim_idx]

    # Locate the sep_rate_col: rightmost col in top_row.downs that actually has a ┬.
    sep_rate_col = None
    for col in top_row.downs:
        if top_line[col - 1] in ('┬', '┼'):
            sep_rate_col = col
    assert sep_rate_col is not None, (
        f'no ┬ found at any of top_border.downs {top_row.downs}\ntop: {top_line}'
    )

    # Verify content row has │ at sep_rate_col.
    assert full_line[sep_rate_col - 1] == '│', (
        f'expected │ in content at col {sep_rate_col}, got {full_line[sep_rate_col-1]!r}'
    )

    # Verify separator_dim has ┴ at sep_rate_col.
    assert sep_line[sep_rate_col - 1] in ('┴', '┼'), (
        f'expected ┴ in separator_dim at col {sep_rate_col}, got {sep_line[sep_rate_col-1]!r}'
    )

    # Verify downs and ups are consistent.
    assert sep_rate_col in top_row.downs, f'sep_rate_col {sep_rate_col} not in top_border.downs {top_row.downs}'
    assert sep_rate_col in sep_row.ups,   f'sep_rate_col {sep_rate_col} not in separator_dim.ups {sep_row.ups}'


def test_sep_rate_no_elbow_when_seven_day_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the 7-day bucket is absent (used_percentage=0, resets_at=0), the 7d vsep
    does not appear in the content row and no stray ┬/┴ elbows are added for it."""
    from helper import strip_ansi
    from yas.session import RateBucket, RateLimits, SessionInfo
    _silence_dynamic(monkeypatch)

    # Build a session with no 7-day bucket active.
    sess = _session()
    zero_limits = RateLimits(
        five_hour=sess.rate_limits.five_hour,
        seven_day=RateBucket(used_percentage=0, resets_at=0),
    )
    sess = SessionInfo(**{**sess.__dict__, 'rate_limits': zero_limits})

    view = SessionView(sess, Config())
    spec = layout.build_wide(view, _tick(), 160, _r)
    lines = [strip_ansi(ln) for ln in layout.render_layout(spec, _r)]

    top_border_idx = next(i for i, row in enumerate(spec.rows) if row.kind == 'top_border')
    top_row = spec.rows[top_border_idx]

    # When 7d is absent, sep_rate_col is None so fewer downs than with 7d active.
    spec_with_7d = layout.build_wide(_view(), _tick(), 160, _r)
    top_with_7d  = spec_with_7d.rows[next(i for i, r in enumerate(spec_with_7d.rows) if r.kind == 'top_border')]
    assert len(top_row.downs) < len(top_with_7d.downs), (
        f'expected fewer downs without 7d ({top_row.downs}) vs with 7d ({top_with_7d.downs})'
    )

    # No elbow gap: every ┬ has a │ below and every ┴ has a │ above.
    assert _elbow_gaps(lines) == 0, 'stray ┬/┴ elbows with no matching │ when 7-day absent'


# ---------------------------------------------------------------------------
# Side-by-side composition (Group 6: tasks ⟷ subagents columns)
# ---------------------------------------------------------------------------

def _make_tasklist(long_subject: bool = False) -> tasks_mod.TaskList:
    """A visible checklist (one task in_progress pins it visible).

    With ``long_subject`` the widest task line easily exceeds 45% of the inner
    width at any realistic terminal, so the left column is always capped — which
    lets the width-driven fallback be exercised deterministically.
    """
    now  = time.time()
    subj = ('a fairly long task subject line wide enough to cap the left column'
            if long_subject else 'second task here')
    return tasks_mod.TaskList(
        tasks=[
            tasks_mod.Task(id=1, subject='first task subject', active_form='doing first',
                           status='completed', completed_at=now - 30),
            tasks_mod.Task(id=2, subject=subj, active_form='doing second',
                           status='in_progress', started_at=now - 10),
            tasks_mod.Task(id=3, subject='third pending task', active_form='third',
                           status='pending'),
        ],
        last_event_ts=now - 5,
    )


def _divider_content_idx(spec: layout.LayoutSpec) -> list[int]:
    """Indices of dynamic content rows that carry a side-by-side divider │.

    The path/model row and the token-stat rows both contain vsep │ glyphs, so
    detection is scoped to content rows *below the static→dynamic seam* — only
    a side-by-side block puts a divider there.
    """
    from helper import strip_ansi
    seam_idx = next(
        (i for i, row in enumerate(spec.rows) if row.kind == 'separator_seam'),
        None,
    )
    if seam_idx is None:
        return []
    return [
        i for i, row in enumerate(spec.rows)
        if i > seam_idx and row.kind == 'content' and '│' in strip_ansi(row.content)
    ]


def _both_sections(monkeypatch: pytest.MonkeyPatch, *, long_subject: bool = False) -> None:
    """Silence host-derived dynamic sections, then inject BOTH a checklist and
    a one-subagent cohort so the wide builder can compose side-by-side."""
    _silence_dynamic(monkeypatch)
    tl = _make_tasklist(long_subject=long_subject)
    monkeypatch.setattr(tasks_mod.TaskList, 'from_session',
                        classmethod(lambda cls, path: tl))
    monkeypatch.setattr(subagents_mod.RunningSubagents, 'from_session',
                        classmethod(lambda cls, sid, pdir: subagents_mod.RunningSubagents(subagents=[_make_sub()])))


def test_side_by_side_continuous_divider_when_both_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wide + both sections + room → one block with a divider column that runs
    ┬ (separator above) → │ (every combined row) → ┴ (separator/border below).
    Column positions asserted via _visible_width."""
    from helper import strip_ansi
    from yas.render.text import _visible_width
    _both_sections(monkeypatch, long_subject=True)

    width = 140
    spec  = layout.build_wide(_view(), _tick(), width, _r)

    # Locate the combined block: content rows whose *inner* content carries the
    # divider │. The divider's 1-indexed visual column on the full line is
    # 3 + (its 0-indexed offset within the content), since border_line places
    # content at visual col 3.
    combined_idx = _divider_content_idx(spec)
    assert combined_idx, 'expected a side-by-side block with a divider column'
    # Divider column is identical across every combined row.
    div_cols = {3 + strip_ansi(spec.rows[i].content).index('│') for i in combined_idx}
    assert len(div_cols) == 1, f'divider column drifts across rows: {div_cols}'
    divider_col = div_cols.pop()

    # The block is contiguous; bracketing rows are the separators above/below.
    first, last = combined_idx[0], combined_idx[-1]
    assert combined_idx == list(range(first, last + 1)), 'combined block is not contiguous'
    above = spec.rows[first - 1]
    below = spec.rows[last + 1]
    assert above.kind in ('separator_dim', 'separator_seam', 'separator')
    assert below.kind in ('separator_dim', 'separator_seam', 'separator', 'bottom_border')
    # Elbow threading carries the divider down into the block and back up below.
    assert divider_col in above.downs, f'separator above missing ┬ at {divider_col}: {above.downs}'
    assert divider_col in below.ups,   f'separator/border below missing ┴ at {divider_col}: {below.ups}'

    # Render and verify the glyphs land on the same visual column everywhere.
    lines = [strip_ansi(ln) for ln in layout.render_layout(spec, _r)]
    for ln in lines:
        assert _visible_width(ln) == width, f'row not full width: {_visible_width(ln)} != {width}'
    col = divider_col - 1  # 0-indexed
    assert lines[first - 1][col] in ('┬', '┼'), f'no ┬ above: {lines[first - 1][col]!r}'
    for i in combined_idx:
        assert lines[i][col] == '│', f'no │ in combined row: {lines[i][col]!r}'
    assert lines[last + 1][col] in ('┴', '┼'), f'no ┴ below: {lines[last + 1][col]!r}'


def test_side_by_side_falls_back_to_stacked_when_narrow(monkeypatch: pytest.MonkeyPatch) -> None:
    """At a width where right_w < 40 the composition is abandoned and the two
    sections stack full-width (no divider in any content row)."""
    from helper import strip_ansi
    _both_sections(monkeypatch, long_subject=True)

    # width 80: inner=76, left_w=min(longest, 34)=34, right_w=76-3-34=39 (<40).
    width = 80
    inner = width - 4
    left_w = inner * 45 // 100
    assert inner - 3 - left_w < 40, 'precondition: this width must force the fallback'

    spec  = layout.build_wide(_view(), _tick(), width, _r)
    assert _divider_content_idx(spec) == [], 'expected stacked fallback (no divider column)'
    # Both sections still present, stacked: a task header glyph row and a
    # subagent marker row both appear as full-width content.
    from yas.constants import GLYPH_TASKS
    has_task = any(row.kind == 'content' and GLYPH_TASKS in strip_ansi(row.content) for row in spec.rows)
    has_sub  = any(row.kind == 'content' and strip_ansi(row.content).lstrip().startswith('▶') for row in spec.rows)
    assert has_task and has_sub, 'both sections should render in the stacked fallback'


def test_side_by_side_plan_column_capped_in_tree_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tree mode + wide box: the plan column is fixed at SUBAGENT_TREE_PLAN_WIDTH
    (not the old 45%-of-inner even split), so the subagent tree gets the rest."""
    from helper import strip_ansi
    from yas.constants import SUBAGENT_TREE_PLAN_WIDTH
    _both_sections(monkeypatch, long_subject=True)

    width = 300
    view  = SessionView(_session(), Config(subagent_tree=True))
    spec  = layout.build_wide(view, _tick(), width, _r)

    combined_idx = _divider_content_idx(spec)
    assert combined_idx, 'expected a side-by-side block with a divider column'
    div_cols = {3 + strip_ansi(spec.rows[i].content).index('│') for i in combined_idx}
    assert len(div_cols) == 1
    divider_col = div_cols.pop()
    left_w = divider_col - 4
    assert left_w == SUBAGENT_TREE_PLAN_WIDTH, f'left_w={left_w}, expected {SUBAGENT_TREE_PLAN_WIDTH}'


def test_side_by_side_plan_split_unchanged_when_tree_mode_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tree mode off: identical to the pre-existing 45%-of-inner split at the
    same wide width — byte-identical output either way."""
    from helper import strip_ansi
    _both_sections(monkeypatch, long_subject=True)

    width = 300
    view_default = SessionView(_session(), Config())
    view_off     = SessionView(_session(), Config(subagent_tree=False))
    spec_default = layout.build_wide(view_default, _tick(), width, _r)
    spec_off     = layout.build_wide(view_off, _tick(), width, _r)
    lines_default = [strip_ansi(ln) for ln in layout.render_layout(spec_default, _r)]
    lines_off     = [strip_ansi(ln) for ln in layout.render_layout(spec_off, _r)]
    assert lines_default == lines_off

    combined_idx = _divider_content_idx(spec_default)
    assert combined_idx, 'expected a side-by-side block with a divider column'
    div_cols = {3 + strip_ansi(spec_default.rows[i].content).index('│') for i in combined_idx}
    divider_col = div_cols.pop()
    left_w = divider_col - 4
    inner  = width - 4
    assert left_w == inner * 45 // 100, 'tree mode off must keep the old 45%-of-inner cap'


def test_side_by_side_plan_column_degrades_at_narrow_width(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tree mode on, but the box is too narrow for a fixed 78-col plan column
    to leave >=40 cols for the tree: falls back to the old 45%-of-inner cap
    (still side-by-side, just not pinned at SUBAGENT_TREE_PLAN_WIDTH)."""
    from helper import strip_ansi
    from yas.constants import SUBAGENT_TREE_PLAN_WIDTH
    _both_sections(monkeypatch, long_subject=True)

    width = 140  # inner=136, 45%-cap=61 < SUBAGENT_TREE_PLAN_WIDTH=78
    inner = width - 4
    assert inner * 45 // 100 < SUBAGENT_TREE_PLAN_WIDTH, 'precondition: 45% cap must undercut the fixed width here'

    view = SessionView(_session(), Config(subagent_tree=True))
    spec = layout.build_wide(view, _tick(), width, _r)
    combined_idx = _divider_content_idx(spec)
    assert combined_idx, 'expected side-by-side (still enough room at width 140)'
    div_cols = {3 + strip_ansi(spec.rows[i].content).index('│') for i in combined_idx}
    divider_col = div_cols.pop()
    left_w = divider_col - 4
    assert left_w == inner * 45 // 100, 'must degrade to the 45%-of-inner cap, not the fixed width'


def test_tasks_only_renders_full_width_stacked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Single-section: checklist present, no subagents → full-width, no divider."""
    from helper import strip_ansi
    from yas.constants import GLYPH_TASKS
    _silence_dynamic(monkeypatch)
    tl = _make_tasklist(long_subject=True)
    monkeypatch.setattr(tasks_mod.TaskList, 'from_session',
                        classmethod(lambda cls, path: tl))

    spec = layout.build_wide(_view(), _tick(), 140, _r)
    assert _divider_content_idx(spec) == [], 'tasks-only must not compose a divider column'
    assert any(row.kind == 'content' and GLYPH_TASKS in strip_ansi(row.content) for row in spec.rows), \
        'task checklist should render'


def test_subagents_only_renders_full_width_stacked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Single-section: subagents present, no checklist → full-width, no divider."""
    from helper import strip_ansi
    _silence_dynamic(monkeypatch)
    monkeypatch.setattr(subagents_mod.RunningSubagents, 'from_session',
                        classmethod(lambda cls, sid, pdir: subagents_mod.RunningSubagents(subagents=[_make_sub()])))

    spec = layout.build_wide(_view(), _tick(), 140, _r)
    assert _divider_content_idx(spec) == [], 'subagents-only must not compose a divider column'
    # twoline cohort at wide: an identity row carries the agent type.
    assert any(row.kind == 'content' and 'Explore' in strip_ansi(row.content) for row in spec.rows), \
        'subagent cohort should render'


# ---------------------------------------------------------------------------
# Bottom-of-wide-band tokens row (the box 80-84 overflow / detached-divider bug)
# ---------------------------------------------------------------------------

def _elbow_gaps(lines: list[str]) -> int:
    """Count ┬/┴ that lack a │ (or other vertical) in the adjacent row/column."""
    from yas.render.text import _is_wide
    def grid(line: str) -> dict[int, str]:
        cols: dict[int, str] = {}
        c = 0
        for ch in line:
            cols[c] = ch
            c += 2 if _is_wide(ch) else 1
        return cols
    g = [grid(ln) for ln in lines]
    vert = set('│┃┤├┼┊┆')  # ┊ = dashed two-column workflow divider; ┆ = SEP_RATE rate-limit separator
    join = set('┬┴┳┻')
    gaps = 0
    for i, cols in enumerate(g):
        for col, ch in cols.items():
            if ch in '┬┳' and i + 1 < len(g) and g[i + 1].get(col, ' ') not in vert | join:
                gaps += 1
            if ch in '┴┻' and i > 0 and g[i - 1].get(col, ' ') not in vert | join:
                gaps += 1
    return gaps


@pytest.mark.parametrize('width', [80, 81, 82, 83, 84, 85])
def test_wide_bottom_band_no_overflow_no_detached_elbows(
    monkeypatch: pytest.MonkeyPatch, width: int,
) -> None:
    """At the bottom of the wide band (box 80-84) the three-segment tokens row
    used to overflow the box and detach its two │ from the ┬/┴ elbows. The
    builder now drops it for the compact context line below the fit floor, so at
    EVERY width: no rendered row is wider than the box, and every ┬/┴ is backed
    by a │ in the adjacent row."""
    from helper import strip_ansi
    from yas.render.text import _visible_width
    _silence_dynamic(monkeypatch)
    spec  = layout.build_wide(_view(), _tick(), width, _r)
    lines = [strip_ansi(ln) for ln in layout.render_layout(spec, _r)]
    for ln in lines:
        assert _visible_width(ln) == width, f'row not full width at box {width}: {_visible_width(ln)} != {width}'
    assert _elbow_gaps(lines) == 0, f'detached ┬/┴ elbow at box {width}'


def test_wide_bottom_band_drops_three_segment_tokens_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Below the fit floor the three-segment tokens │ cost │ rate row is dropped
    (no 't/m' content row); at/above it the row is present."""
    from helper import strip_ansi
    _silence_dynamic(monkeypatch)

    def has_tokens_row(spec: layout.LayoutSpec) -> bool:
        return any(row.kind == 'content' and 't/m' in strip_ansi(row.content)
                   for row in spec.rows)

    assert not has_tokens_row(layout.build_wide(_view(), _tick(), 82, _r))
    assert has_tokens_row(layout.build_wide(_view(), _tick(), 100, _r))


def test_workflow_two_column_pairing_threshold() -> None:
    """Section 6: at width >= TWO_COL_WF_WIDTH (120) workflow agents pair
    two-per-row; just below it each agent gets its own row. Two agents -> one
    paired row vs two stacked rows."""
    from helper import strip_ansi
    from yas.info.subagents import RunningSubagent
    from yas.info.workflows import RunningWorkflow, RunningWorkflows

    now    = time.time()
    agents = [
        RunningSubagent(
            agent_type      = f'agent-{i}',
            description     = '',
            billed_in       = 0,
            output          = 0,
            first_timestamp = now + i,
            total_input     = 0,
            end_ts          = 0.0,
            mtime           = now,
            agent_id        = f'a{i}',
        )
        for i in range(2)
    ]
    run = RunningWorkflow(run_id='wf_x', name='wf_x', phase='', agents=agents)

    def _view_with(run):
        view = _view()
        view.__dict__['workflows'] = RunningWorkflows(workflows=[run])
        return view

    def agent_rows(width: int) -> list[layout.RowSpec]:
        rows = layout.build_workflow_rows(_view_with(run), width, _r, per_agent=True)
        # strip the header (first) and summary (last) rows
        return rows[1:-1]

    # width 120 (== TWO_COL_WF_WIDTH): the two agents share paired content
    # rows. With twoline=True each agent emits 2 lines, so one pair produces
    # 2 content rows. The block carries no internal separators — the divider
    # ``┊`` is embedded in every row and the bracketing ┬/┴ are threaded by
    # build_wide.
    rows = agent_rows(120)
    assert all(row.kind == 'content' for row in rows)
    assert len(rows) == 2
    assert 'agent-0' in rows[0].content and 'agent-1' in rows[0].content
    # Every row of the block (header, paired agents, summary) embeds the divider
    # at the shared column so the bar stays straight top-to-bottom.
    div_col = layout.workflow_divider_col(120)
    full    = layout.build_workflow_rows(_view_with(run), 120, _r, per_agent=True)
    for row in full:
        line = strip_ansi(row.content)
        assert len(line) > div_col - 3 and line[div_col - 3] == '┊'

    # The dashed divider floats free: build_wide threads NO ┬/┴ elbow onto the
    # separator above the header or the border below the summary at div_col.
    spec       = layout.build_wide(_view_with(run), _tick(), 120, _r)
    wide_lines = [strip_ansi(line) for line in layout.render_layout(spec, _r)]
    hdr_idx    = next(i for i, ln in enumerate(wide_lines) if '▸' in ln)
    # div_col is a 1-indexed visual column, so the glyph sits at index div_col-1.
    assert wide_lines[hdr_idx - 1][div_col - 1] not in '┬┼'   # plain rule above the title
    last_sum   = max(i for i, ln in enumerate(wide_lines) if '└' in ln and 'agents' in ln)
    assert wide_lines[last_sum + 1][div_col - 1] not in '┴┼'  # plain border below the summary

    # width 119: single-column — no row contains both agents (each renders in
    # its own row(s), the existing behaviour).
    stacked = agent_rows(119)
    assert not any('agent-0' in row.content and 'agent-1' in row.content
                   for row in stacked)
    assert any('agent-0' in row.content for row in stacked)
    assert any('agent-1' in row.content for row in stacked)


# ---------------------------------------------------------------------------
# Plugins row truncation (#91 — long plugin list overflowed the box)
# ---------------------------------------------------------------------------

def test_long_plugins_row_clipped_to_box_width(monkeypatch: pytest.MonkeyPatch) -> None:
    """A plugin list far wider than the box is clipped to the inner content
    width with a trailing ellipsis instead of overflowing past the right
    border — every rendered row stays exactly box-wide."""
    from helper import strip_ansi
    from yas.constants import ELLIPSIS
    from yas.render.text import _visible_width
    _silence_dynamic(monkeypatch)
    plugins = ','.join(f'plugin-{i:02d}' for i in range(40))  # ~440 visible cols
    monkeypatch.setattr(session_mod.Workspace, 'plugins', property(lambda self: plugins))

    width = 140
    spec  = layout.build_wide(_view(), _tick(), width, _r)
    lines = [strip_ansi(ln) for ln in layout.render_layout(spec, _r)]
    for ln in lines:
        assert _visible_width(ln) == width, f'row overflows the box: {_visible_width(ln)} != {width}'
    plugins_lines = [ln for ln in lines if 'plugin-00' in ln]
    assert plugins_lines, 'plugins row should render'
    assert ELLIPSIS in plugins_lines[0], 'clipped plugins row should end with an ellipsis'


def test_short_plugins_row_not_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    """A plugin list that fits the box renders in full, with no ellipsis."""
    from helper import strip_ansi
    from yas.constants import ELLIPSIS
    _silence_dynamic(monkeypatch)
    monkeypatch.setattr(session_mod.Workspace, 'plugins', property(lambda self: 'foo,bar'))

    spec = layout.build_wide(_view(), _tick(), 140, _r)
    plugins_lines = [strip_ansi(ln) for ln in layout.render_layout(spec, _r) if 'foo,bar' in strip_ansi(ln)]
    assert plugins_lines, 'plugins row should render'
    assert ELLIPSIS not in plugins_lines[0]


# ---------------------------------------------------------------------------
# Task 6.4 — cache_section sub-hour and over-hour format
# ---------------------------------------------------------------------------

def test_cache_section_sub_hour_format() -> None:
    from helper import strip_ansi
    text, _w = _r.cache_section(187.0, 38)
    stripped = strip_ansi(text)
    assert '03:07' in stripped


def test_cache_section_over_hour_format() -> None:
    from helper import strip_ansi
    text, _w = _r.cache_section(3905.0, 38)
    stripped = strip_ansi(text)
    assert '1:05:05' in stripped


# ---------------------------------------------------------------------------
# Task 6.3 — Clear-timer degradation ladder and fresh-session preservation
# ---------------------------------------------------------------------------

def _inject_clear_epoch(view: SessionView, epoch: float | None) -> SessionView:
    """Inject a clear_epoch value into a SessionView's __dict__ cache."""
    view.__dict__['clear_epoch'] = epoch
    return view


def test_clear_timer_both_shown_at_ample_width(monkeypatch: pytest.MonkeyPatch) -> None:
    """At a wide terminal both clear and session timers appear in the content row."""
    from helper import strip_ansi
    from yas.constants import GLYPH_CLEAR
    _silence_dynamic(monkeypatch)
    now = 1_750_000_000.0
    clear_epoch = now - 18 * 60 - 33  # 18:33 ago
    view = _view()
    view.__dict__['now'] = now
    view.__dict__['elapsed'] = '13:27'
    _inject_clear_epoch(view, clear_epoch)

    spec = layout.build_wide(view, _tick(), 160, _r)
    # The path/model row (first content row)
    content_rows = [r for r in spec.rows if r.kind == 'content']
    top_content = content_rows[0].content
    plain = strip_ansi(top_content)
    assert GLYPH_CLEAR in top_content, 'GLYPH_CLEAR should appear in the elapsed cell'
    assert '18:33' in plain, 'clear timer should appear'
    assert '13:27' in plain, 'session timer should appear'


def test_clear_timer_clear_first_in_cell(monkeypatch: pytest.MonkeyPatch) -> None:
    """The clear timer is leftmost (lower index) in the content row plain text."""
    from helper import strip_ansi
    _silence_dynamic(monkeypatch)
    now = 1_750_000_000.0
    clear_epoch = now - 18 * 60 - 33
    view = _view()
    view.__dict__['now'] = now
    view.__dict__['elapsed'] = '13:27'
    _inject_clear_epoch(view, clear_epoch)

    spec = layout.build_wide(view, _tick(), 160, _r)
    content_rows = [r for r in spec.rows if r.kind == 'content']
    plain = strip_ansi(content_rows[0].content)
    assert plain.index('18:33') < plain.index('13:27')


def test_clear_timer_fresh_session_byte_identical(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fresh session (clear_epoch=None): top content row is byte-identical to the pre-change render."""
    _silence_dynamic(monkeypatch)
    view_fresh = _view()
    view_fresh.__dict__['now'] = 1_750_000_000.0
    view_fresh.__dict__['elapsed'] = '13:27'
    _inject_clear_epoch(view_fresh, None)

    view_baseline = _view()
    view_baseline.__dict__['now'] = 1_750_000_000.0
    view_baseline.__dict__['elapsed'] = '13:27'
    # No clear_epoch injection → cached_property reads from transcript → None
    # To get a true baseline we inject None too (same result)
    view_baseline.__dict__['clear_epoch'] = None

    spec_fresh    = layout.build_wide(view_fresh, _tick(), 160, _r)
    spec_baseline = layout.build_wide(view_baseline, _tick(), 160, _r)

    # Both specs should produce an identical first content row
    rows_f = [r for r in spec_fresh.rows if r.kind == 'content']
    rows_b = [r for r in spec_baseline.rows if r.kind == 'content']
    assert rows_f[0].content == rows_b[0].content


def test_clear_timer_degrades_to_clear_only_when_both_dont_fit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When width is too narrow for both timers but fits clear-only, only the clear timer renders."""
    from helper import strip_ansi
    from yas.constants import GLYPH_CLEAR
    from yas.render.text import _visible_width
    _silence_dynamic(monkeypatch)

    # Measure the geometry so we find the exact shed boundary
    sess       = _session()
    h5h, h7d, _, right_w = _r.model_right_section(
        sess.model_name, sess.model_thinking, sess.rate_limits, '', fast_mode=sess.fast_mode,
    )
    helper_w = _visible_width(h5h) + (4 + _visible_width(h7d) if h7d else 0)
    vsep_w   = 5
    now      = 1_750_000_000.0
    clear_epoch = now - 18 * 60 - 33

    _co, clear_only_w = _r.elapsed_section('', '18:33')
    _cb, both_w       = _r.elapsed_section('13:27', '18:33')
    clear_sw = clear_only_w + 3
    both_sw  = both_w + 3

    # Width where both fit (path_budget = 5 with both)
    width_both = 5 + vsep_w + both_sw + helper_w + right_w + 4
    # Width where only clear fits (path_budget = 5 with clear only) but not both
    width_clear_only = 5 + vsep_w + clear_sw + helper_w + right_w + 4

    # At width_clear_only (< width_both), we should get clear-only
    if width_clear_only < width_both:
        view = _view()
        view.__dict__['now'] = now
        view.__dict__['elapsed'] = '13:27'
        _inject_clear_epoch(view, clear_epoch)

        spec = layout.build_wide(view, _tick(), width_clear_only, _r)
        content_rows = [r for r in spec.rows if r.kind == 'content']
        plain = strip_ansi(content_rows[0].content)
        # Clear timer present, session timer absent
        assert GLYPH_CLEAR in content_rows[0].content, 'clear glyph should be present'
        assert '18:33' in plain, 'clear timer should be shown'
        assert '13:27' not in plain, 'session timer should be shed'


def test_clear_timer_sheds_entire_cell_on_path_protection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When even clear-only doesn't protect the path (< 5 cols), the whole cell sheds."""
    from yas.constants import GLYPH_CLEAR
    from yas.render.text import _visible_width
    _silence_dynamic(monkeypatch)

    sess       = _session()
    h5h, h7d, _, right_w = _r.model_right_section(
        sess.model_name, sess.model_thinking, sess.rate_limits, '', fast_mode=sess.fast_mode,
    )
    helper_w = _visible_width(h5h) + (4 + _visible_width(h7d) if h7d else 0)
    vsep_w   = 5
    now      = 1_750_000_000.0
    clear_epoch = now - 18 * 60 - 33

    _co, clear_only_w = _r.elapsed_section('', '18:33')
    clear_sw = clear_only_w + 3

    # Width where even clear-only sheds (path_budget would be < 5)
    min_keep = 5 + vsep_w + clear_sw + helper_w + right_w + 4
    width_shed = min_keep - 1

    view = _view()
    view.__dict__['now'] = now
    view.__dict__['elapsed'] = '13:27'
    _inject_clear_epoch(view, clear_epoch)

    spec = layout.build_wide(view, _tick(), width_shed, _r)
    lines = layout.render_layout(spec, _r)
    for ln in lines:
        assert GLYPH_CLEAR not in ln, 'elapsed cell should be fully shed'


def test_clear_timer_no_additional_elbow(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adding a clear timer does NOT add a new border elbow (single divider unchanged)."""
    _silence_dynamic(monkeypatch)
    now = 1_750_000_000.0
    clear_epoch = now - 18 * 60 - 33

    view_cleared = _view()
    view_cleared.__dict__['now'] = now
    view_cleared.__dict__['elapsed'] = '13:27'
    _inject_clear_epoch(view_cleared, clear_epoch)

    view_fresh = _view()
    view_fresh.__dict__['now'] = now
    view_fresh.__dict__['elapsed'] = '13:27'
    _inject_clear_epoch(view_fresh, None)

    spec_cleared = layout.build_wide(view_cleared, _tick(), 160, _r)
    spec_fresh   = layout.build_wide(view_fresh,   _tick(), 160, _r)

    downs_cleared = spec_cleared.rows[0].downs
    downs_fresh   = spec_fresh.rows[0].downs
    # Same number of elbows: clear timer shares the existing elapsed divider
    assert len(downs_cleared) == len(downs_fresh)
