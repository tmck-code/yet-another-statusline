import json
import time
from pathlib import Path

import pytest

from helper import strip_ansi
import yas.layout as layout
import yas.renderer as renderer_mod
import yas.session as session_mod
import yas.info.subagents as subagents_mod
import yas.info.tasks as tasks_mod
import yas.info.skills as skills_mod
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




def _kinds(spec: layout.LayoutSpec) -> list[str]:
    return [row.kind for row in spec.rows]


def _tokens_row_indices(spec: layout.LayoutSpec) -> list[int]:
    """Content rows that carry the tokens/cost/rate line (the rate label 't/m')."""
    return [i for i, row in enumerate(spec.rows)
            if row.kind == 'content' and 't/m' in strip_ansi(row.content)]


def test_tokens_row_is_single_content_line(monkeypatch: pytest.MonkeyPatch, silence_dynamic: None) -> None:
    spec = layout.build_wide(_view(), _tick(), 160, _r)
    assert len(_tokens_row_indices(spec)) == 1


def test_tokens_row_session_only_single_line(monkeypatch: pytest.MonkeyPatch, silence_dynamic: None) -> None:
    view = SessionView(_session(), Config(show_day_stats=False))
    spec = layout.build_wide(view, _tick(), 160, _r)
    assert len(_tokens_row_indices(spec)) == 1


def test_tokens_row_dividers_align_with_separators(monkeypatch: pytest.MonkeyPatch, silence_dynamic: None) -> None:
    """Every interior │ in the single tokens line has a matching ┬ on the
    separator above and ┴ on the separator below at the same visual column.

    At width=160 (>= LINES_SEGMENT_MIN_WIDTH=103) the lines read/changed
    segment (design.md Decision 8) is included, so there are 3 interior │
    (lines | cost | rate) instead of the pre-Decision-8 2."""
    # A dynamic section below ensures the row below tokens is a (seam) separator,
    # not the bottom border — so we can check ┴ elbows both sides.
    monkeypatch.setattr(subagents_mod.RunningSubagents, 'from_session',
                        classmethod(lambda cls, sid, pdir, now=None, **kwargs: subagents_mod.RunningSubagents(subagents=[_make_sub()])))
    spec  = layout.build_wide(_view(), _tick(), 160, _r)
    lines = [strip_ansi(ln) for ln in layout.render_layout(spec, _r)]
    t_idx = _tokens_row_indices(spec)[0]

    last = len(lines[t_idx]) - 1
    interior_bars = [i for i, ch in enumerate(lines[t_idx]) if ch == '│' and 0 < i < last]
    assert len(interior_bars) == 3, f'expected 3 interior │, got {interior_bars}'

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


def test_subagent_cohort_caps_at_six_most_recent(monkeypatch: pytest.MonkeyPatch, silence_dynamic: None) -> None:
    """Eight live subagents collapse to the six most recently started, shown
    in chronological (first_timestamp ascending) order."""
    from yas.constants import SUBAGENT_DISPLAY_CAP
    now  = time.time()
    subs = [_make_sub_labelled(f'sub-{i}', now - (8 - i)) for i in range(8)]
    monkeypatch.setattr(subagents_mod.RunningSubagents, 'from_session',
                        classmethod(lambda cls, sid, pdir, now=None, **kwargs: subagents_mod.RunningSubagents(subagents=subs)))
    spec = layout.build_wide(_view(), _tick(), 160, _r)
    texts = ' '.join(strip_ansi(row.content) for row in spec.rows if row.kind == 'content')
    shown = [i for i in range(8) if f'sub-{i}' in texts]
    assert len(shown) == SUBAGENT_DISPLAY_CAP
    assert shown == [2, 3, 4, 5, 6, 7]  # oldest two (0, 1) dropped, chronological


def test_seam_present_with_dynamic_section(monkeypatch: pytest.MonkeyPatch, silence_dynamic: None) -> None:
    monkeypatch.setattr(subagents_mod.RunningSubagents, 'from_session',
                        classmethod(lambda cls, sid, pdir, now=None, **kwargs: subagents_mod.RunningSubagents(subagents=[_make_sub()])))
    spec = layout.build_wide(_view(), _tick(), 140, _r)
    assert _kinds(spec).count('separator_seam') == 1


def test_no_seam_without_dynamic_rows(monkeypatch: pytest.MonkeyPatch, silence_dynamic: None) -> None:
    spec = layout.build_wide(_view(), _tick(), 140, _r)
    assert 'separator_seam' not in _kinds(spec)
    assert _kinds(spec)[-1] == 'bottom_border'


def test_seam_is_first_separator_below_tokens(monkeypatch: pytest.MonkeyPatch, silence_dynamic: None) -> None:
    monkeypatch.setattr(subagents_mod.RunningSubagents, 'from_session',
                        classmethod(lambda cls, sid, pdir, now=None, **kwargs: subagents_mod.RunningSubagents(subagents=[_make_sub()])))
    spec = layout.build_wide(_view(), _tick(), 140, _r)
    seam_idx = next(i for i, row in enumerate(spec.rows) if row.kind == 'separator_seam')
    # Seam threads up-elbows into the token-stat vsep columns.
    assert spec.rows[seam_idx].ups
    # The very next row is the dynamic content the seam introduces.
    assert spec.rows[seam_idx + 1].kind == 'content'


def test_seam_renders_solid_not_heavy(monkeypatch: pytest.MonkeyPatch, silence_dynamic: None) -> None:
    monkeypatch.setattr(subagents_mod.RunningSubagents, 'from_session',
                        classmethod(lambda cls, sid, pdir, now=None, **kwargs: subagents_mod.RunningSubagents(subagents=[_make_sub()])))
    spec = layout.build_wide(_view(), _tick(), 140, _r)
    seam_idx = next(i for i, row in enumerate(spec.rows) if row.kind == 'separator_seam')
    seam = strip_ansi(layout.render_layout(spec, _r)[seam_idx])
    assert seam[0] == '├' and seam[-1] == '┤'   # single-line box ends
    assert '─' in seam and '┴' in seam          # solid rule, up-elbows into token vseps
    assert '━' not in seam and '┷' not in seam  # not the heavy variant


def test_cache_countdown_none_single_elbow(monkeypatch: pytest.MonkeyPatch, silence_dynamic: None) -> None:
    """When cache_countdown is None the top border and separator_dim carry elbows for
    path + elapsed + sep_rate (the ┆ between 5h and 7d rate-limit segments) but NOT cache."""
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


def test_cache_countdown_outranks_branch_dir_and_timer(monkeypatch: pytest.MonkeyPatch, silence_dynamic: None) -> None:
    """Cache countdown is priority 2 in the declarative top-row precedence —
    higher than branch (3), dir (4), the session timer (5), 7d (6), changes
    (7), and commit (8). So even with a pathologically long branch name that
    forces the path all the way down to its glyph-only floor, the cache
    section is still retained across the whole wide tier (width >= 80)."""
    from yas.constants import GLYPH_CACHE, MEDIUM_WIDTH
    from yas.info.git import GitInfo

    countdown = (187.0, 38)
    long_git  = GitInfo(branch='x' * 200, commit='abcdef1', modified=3)

    for width in (MEDIUM_WIDTH, MEDIUM_WIDTH + 1, MEDIUM_WIDTH + 20, MEDIUM_WIDTH + 80):
        view = _view()
        view.__dict__['cache_countdown'] = countdown
        view.__dict__['git']             = long_git
        spec  = layout.build_wide(view, _tick(), width, _r)
        lines = layout.render_layout(spec, _r)
        assert any(GLYPH_CACHE in ln for ln in lines), \
            f'cache glyph absent at width={width} (priority 2 should outlast branch/dir/timer)'

    # A normal (short) branch name keeps the elbow count and cache glyph
    # present too — the shed loop only exercises the extreme-narrow rungs
    # (7d/timer/dir/branch) when the path itself demands it.
    view_normal = _view()
    view_normal.__dict__['cache_countdown'] = countdown
    spec_normal  = layout.build_wide(view_normal, _tick(), MEDIUM_WIDTH, _r)
    lines_normal = layout.render_layout(spec_normal, _r)
    assert any(GLYPH_CACHE in ln for ln in lines_normal), \
        f'cache glyph absent at width={MEDIUM_WIDTH} with a normal-length branch name'


def test_narrow_and_medium_no_cache_countdown(monkeypatch: pytest.MonkeyPatch, silence_dynamic: None) -> None:
    """Neither narrow nor medium layouts ever render the cache countdown glyph."""
    from yas.constants import GLYPH_CACHE

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


def test_only_first_dynamic_separator_is_seam(monkeypatch: pytest.MonkeyPatch, silence_dynamic: None) -> None:
    # Two dynamic sections (skills + subagents): first separator is the seam,
    # the separator between them stays a normal dotted-dim separator.
    monkeypatch.setattr(skills_mod.LoadedSkills, 'from_transcript',
                        classmethod(lambda cls, path: skills_mod.LoadedSkills(names=['x:demo'])))
    monkeypatch.setattr(subagents_mod.RunningSubagents, 'from_session',
                        classmethod(lambda cls, sid, pdir, now=None, **kwargs: subagents_mod.RunningSubagents(subagents=[_make_sub()])))
    spec = layout.build_wide(_view(), _tick(), 140, _r)
    kinds = _kinds(spec)
    assert kinds.count('separator_seam') == 1
    seam_idx = kinds.index('separator_seam')
    # A later separator (between skills and subagents) is normal, not a seam.
    assert 'separator_dim' in kinds[seam_idx + 1:]


def test_cache_countdown_content_row_contains_glyph_and_time(
    monkeypatch: pytest.MonkeyPatch, silence_dynamic: None,
) -> None:
    from yas.constants import GLYPH_CACHE
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
    monkeypatch: pytest.MonkeyPatch, silence_dynamic: None,
) -> None:
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


def test_sep_rate_elbow_threaded_into_borders(monkeypatch: pytest.MonkeyPatch, silence_dynamic: None) -> None:
    """The │ separator between 5h and 7d rate-limit segments in the wide path/model
    row must have matching ┬/┴ elbows in the top border and separator_dim at the
    same visual column.

    Uses the default example session (seven_day.used_percentage=89) so the 7d vsep
    is present in the content row. Uses render_layout to verify glyphs land at the
    correct column position after border painting.
    """
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


def test_sep_rate_no_elbow_when_seven_day_absent(monkeypatch: pytest.MonkeyPatch, silence_dynamic: None) -> None:
    """When the 7-day bucket is absent (used_percentage=0, resets_at=0), the 7d vsep
    does not appear in the content row and no stray ┬/┴ elbows are added for it."""
    from yas.session import RateBucket, RateLimits, SessionInfo

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


def _make_tasklist(long_subject: bool = False) -> tasks_mod.TaskList:
    """A visible checklist (one task in_progress pins it visible).

    With ``long_subject`` the widest task line easily exceeds 45% of the inner
    width at any realistic terminal, so the left column is always capped — which
    lets the width-driven fallback be exercised deterministically. The active
    task's ``active_form`` is lengthened alongside its subject, since that is
    what the in-progress row actually renders.
    """
    now  = time.time()
    long = long_subject
    subj = ('a fairly long task subject line wide enough to cap the left column'
            if long else 'second task here')
    act  = ('doing a fairly long task wide enough to cap the left column too'
            if long else 'doing second')
    return tasks_mod.TaskList(
        tasks=[
            tasks_mod.Task(id=1, subject='first task subject', active_form='doing first',
                           status='completed', completed_at=now - 30),
            tasks_mod.Task(id=2, subject=subj, active_form=act,
                           status='in_progress', started_at=now - 10),
            tasks_mod.Task(id=3, subject='third pending task', active_form='third',
                           status='pending'),
        ],
        last_event_ts=now - 5,
    )


def _make_tasklist_narrow_stress() -> tasks_mod.TaskList:
    """A checklist shaped to stress `task_row`'s narrow (left_w ~12) per-item
    field math: >=4 completed tasks (pushes the visible id past a single
    digit: '5.', '6.', ...) plus a Total Elapsed timer WIDER than any
    individual item's duration ('11:07' vs '1:11'/'1:07') — so `timer_w` (the
    shared leading column) is sized off the header's elapsed string, not any
    item's own timer, exactly like the demo fixture that exposed the
    interior-divider off-by-one (task_row's own
    ``avail = max(1, field_w - _visible_width(num))`` floor renders 1 column
    past ``field_w`` once the numbered prefix alone already fills it, which a
    3-task/single-digit/matched-timer-width fixture never triggers)."""
    now = time.time()
    return tasks_mod.TaskList(
        tasks=[
            tasks_mod.Task(id=i, subject=f't{i}', active_form=f'a{i}', status='completed',
                           started_at=now - (900 - i * 100), completed_at=now - (800 - i * 100))
            for i in range(1, 5)
        ] + [
            tasks_mod.Task(id=5, subject='task five subject text', active_form='doing five',
                           status='in_progress', started_at=now - 71),
            tasks_mod.Task(id=6, subject='task six subject text', active_form='doing six',
                           status='in_progress', started_at=now - 67),
            tasks_mod.Task(id=7, subject='task seven subject', active_form='doing seven',
                           status='pending'),
            tasks_mod.Task(id=8, subject='task eight subject', active_form='doing eight',
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
    tl = _make_tasklist(long_subject=long_subject)
    monkeypatch.setattr(tasks_mod.TaskList, 'from_session',
                        classmethod(lambda cls, path: tl))
    monkeypatch.setattr(subagents_mod.RunningSubagents, 'from_session',
                        classmethod(lambda cls, sid, pdir, now=None, **kwargs: subagents_mod.RunningSubagents(subagents=[_make_sub()])))


def _both_sections_narrow_stress(monkeypatch: pytest.MonkeyPatch) -> None:
    """Like `_both_sections`, but with `_make_tasklist_narrow_stress` — the
    fixture that actually exercises `task_row`'s narrow field-width floor
    (see its docstring). Use this for any narrow-tier side-by-side assertion
    that needs to catch the interior-divider-drift class of bug; the plain
    `_make_tasklist()` fixture does not stress that code path."""
    tl = _make_tasklist_narrow_stress()
    monkeypatch.setattr(tasks_mod.TaskList, 'from_session',
                        classmethod(lambda cls, path: tl))
    monkeypatch.setattr(subagents_mod.RunningSubagents, 'from_session',
                        classmethod(lambda cls, sid, pdir, now=None, **kwargs: subagents_mod.RunningSubagents(subagents=[_make_sub()])))


def test_side_by_side_continuous_divider_when_both_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wide + both sections + room → one block with a divider column that runs
    ┬ (separator above) → │ (every combined row) → ┴ (separator/border below).
    Column positions asserted via _visible_width."""
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
    has_sub  = any(row.kind == 'content' and 'Explore' in strip_ansi(row.content) for row in spec.rows)
    assert has_task and has_sub, 'both sections should render in the stacked fallback'


def test_side_by_side_plan_column_capped_in_tree_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tree mode + wide box + a plan longer than the cap: the plan column stops
    at SUBAGENT_TREE_PLAN_WIDTH (not the old 45%-of-inner even split), so the
    subagent tree gets the rest."""
    from yas.constants import SUBAGENT_TREE_PLAN_WIDTH
    _both_sections(monkeypatch, long_subject=True)

    width = 300
    view  = SessionView(_session(), Config())
    spec  = layout.build_wide(view, _tick(), width, _r)

    combined_idx = _divider_content_idx(spec)
    assert combined_idx, 'expected a side-by-side block with a divider column'
    div_cols = {3 + strip_ansi(spec.rows[i].content).index('│') for i in combined_idx}
    assert len(div_cols) == 1
    divider_col = div_cols.pop()
    left_w = divider_col - 4
    assert left_w == SUBAGENT_TREE_PLAN_WIDTH, f'left_w={left_w}, expected {SUBAGENT_TREE_PLAN_WIDTH}'


def test_side_by_side_plan_column_sized_to_content_in_tree_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tree mode + a plan shorter than the cap: the plan column is sized to the
    longest rendered plan line plus SUBAGENT_TREE_PLAN_PAD — no trailing band of
    padding before the divider — and every reclaimed column goes to the tree."""
    from yas.constants import SUBAGENT_TREE_PLAN_PAD, SUBAGENT_TREE_PLAN_WIDTH
    _both_sections(monkeypatch, long_subject=False)

    width = 300
    view  = SessionView(_session(), Config())
    spec  = layout.build_wide(view, _tick(), width, _r)

    combined_idx = _divider_content_idx(spec)
    assert combined_idx, 'expected a side-by-side block with a divider column'
    div_cols = {3 + strip_ansi(spec.rows[i].content).index('│') for i in combined_idx}
    assert len(div_cols) == 1, f'divider column drifts across rows: {div_cols}'
    left_w = div_cols.pop() - 4

    longest = layout.plan_content_width(_r.task_row(view.tasks, SUBAGENT_TREE_PLAN_WIDTH))
    assert longest + SUBAGENT_TREE_PLAN_PAD < SUBAGENT_TREE_PLAN_WIDTH, \
        'precondition: this plan must be shorter than the cap'
    assert left_w == longest + SUBAGENT_TREE_PLAN_PAD, \
        f'left_w={left_w}, expected content width {longest} + {SUBAGENT_TREE_PLAN_PAD}'


def test_subagent_tree_plan_width_cap_value() -> None:
    """The tree-mode plan-column cap is a modest ~13% reduction from its
    previous 78-col value (78 -> 68), so the subagent side gets more room
    without truncating the plan column into uselessness."""
    from yas.constants import SUBAGENT_TREE_PLAN_WIDTH
    assert SUBAGENT_TREE_PLAN_WIDTH == 68


def test_side_by_side_plan_column_degrades_at_narrow_width(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tree mode on with a plan longer than the ceiling, but the box is too
    narrow for a SUBAGENT_TREE_PLAN_WIDTH-col plan column: the ceiling falls
    back to the old 45%-of-inner cap (still side-by-side)."""
    from yas.constants import SUBAGENT_TREE_PLAN_WIDTH
    _both_sections(monkeypatch, long_subject=True)

    width = 140  # inner=136, 45%-cap=61 < SUBAGENT_TREE_PLAN_WIDTH=68
    inner = width - 4
    assert inner * 45 // 100 < SUBAGENT_TREE_PLAN_WIDTH, 'precondition: 45% cap must undercut the fixed width here'

    view = SessionView(_session(), Config())
    spec = layout.build_wide(view, _tick(), width, _r)
    combined_idx = _divider_content_idx(spec)
    assert combined_idx, 'expected side-by-side (still enough room at width 140)'
    div_cols = {3 + strip_ansi(spec.rows[i].content).index('│') for i in combined_idx}
    divider_col = div_cols.pop()
    left_w = divider_col - 4
    assert left_w == inner * 45 // 100, 'must degrade to the 45%-of-inner cap, not the fixed width'


def test_tasks_only_renders_full_width_stacked(monkeypatch: pytest.MonkeyPatch, silence_dynamic: None) -> None:
    """Single-section: checklist present, no subagents → full-width, no divider."""
    from yas.constants import GLYPH_TASKS
    tl = _make_tasklist(long_subject=True)
    monkeypatch.setattr(tasks_mod.TaskList, 'from_session',
                        classmethod(lambda cls, path: tl))

    spec = layout.build_wide(_view(), _tick(), 140, _r)
    assert _divider_content_idx(spec) == [], 'tasks-only must not compose a divider column'
    assert any(row.kind == 'content' and GLYPH_TASKS in strip_ansi(row.content) for row in spec.rows), \
        'task checklist should render'


def test_subagents_only_renders_full_width_stacked(monkeypatch: pytest.MonkeyPatch, silence_dynamic: None) -> None:
    """Single-section: subagents present, no checklist → full-width, no divider."""
    monkeypatch.setattr(subagents_mod.RunningSubagents, 'from_session',
                        classmethod(lambda cls, sid, pdir, now=None, **kwargs: subagents_mod.RunningSubagents(subagents=[_make_sub()])))

    spec = layout.build_wide(_view(), _tick(), 140, _r)
    assert _divider_content_idx(spec) == [], 'subagents-only must not compose a divider column'
    # twoline cohort at wide: an identity row carries the agent type.
    assert any(row.kind == 'content' and 'Explore' in strip_ansi(row.content) for row in spec.rows), \
        'subagent cohort should render'


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
    monkeypatch: pytest.MonkeyPatch, silence_dynamic: None, width: int,
) -> None:
    """At the bottom of the wide band (box 80-84) the three-segment tokens row
    used to overflow the box and detach its two │ from the ┬/┴ elbows. The
    fit floor (TOKENS_COST_MIN_WIDTH) is now pinned to MEDIUM_WIDTH == 80, i.e.
    the wide layout's own entry point, so the row is present across this whole
    band; regardless, at EVERY width: no rendered row is wider than the box,
    and every ┬/┴ is backed by a │ in the adjacent row."""
    from yas.render.text import _visible_width
    spec  = layout.build_wide(_view(), _tick(), width, _r)
    lines = [strip_ansi(ln) for ln in layout.render_layout(spec, _r)]
    for ln in lines:
        assert _visible_width(ln) == width, f'row not full width at box {width}: {_visible_width(ln)} != {width}'
    assert _elbow_gaps(lines) == 0, f'detached ┬/┴ elbow at box {width}'


def test_wide_bottom_band_drops_three_segment_tokens_row(
    monkeypatch: pytest.MonkeyPatch, silence_dynamic: None,
) -> None:
    """Below the fit floor (TOKENS_COST_MIN_WIDTH == MEDIUM_WIDTH == 80) the
    three-segment tokens │ cost │ rate row is dropped (no 't/m' content row);
    at/above it the row is present. TOKENS_COST_MIN_WIDTH is now pinned to
    MEDIUM_WIDTH, so the floor sits below build_wide's own box >= 80 entry
    point — passing a sub-80 width directly to build_wide (as this seam test
    does) is the only way left to observe the dropped row."""

    def has_tokens_row(spec: layout.LayoutSpec) -> bool:
        return any(row.kind == 'content' and 't/m' in strip_ansi(row.content)
                   for row in spec.rows)

    assert not has_tokens_row(layout.build_wide(_view(), _tick(), 75, _r))
    assert has_tokens_row(layout.build_wide(_view(), _tick(), 80, _r))
    assert has_tokens_row(layout.build_wide(_view(), _tick(), 100, _r))


def test_workflow_two_column_pairing_threshold() -> None:
    """Section 6: at width >= TWO_COL_WF_WIDTH (120) workflow agents pair
    two-per-row; just below it each agent gets its own row. Two agents -> one
    paired row vs two stacked rows."""
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


def test_long_plugins_row_clipped_to_box_width(monkeypatch: pytest.MonkeyPatch, silence_dynamic: None) -> None:
    """A plugin list far wider than the box is clipped to the inner content
    width with a trailing ellipsis instead of overflowing past the right
    border — every rendered row stays exactly box-wide."""
    from yas.constants import ELLIPSIS
    from yas.render.text import _visible_width
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


def test_short_plugins_row_not_truncated(monkeypatch: pytest.MonkeyPatch, silence_dynamic: None) -> None:
    """A plugin list that fits the box renders in full, with no ellipsis."""
    from yas.constants import ELLIPSIS
    monkeypatch.setattr(session_mod.Workspace, 'plugins', property(lambda self: 'foo,bar'))

    spec = layout.build_wide(_view(), _tick(), 140, _r)
    plugins_lines = [strip_ansi(ln) for ln in layout.render_layout(spec, _r) if 'foo,bar' in strip_ansi(ln)]
    assert plugins_lines, 'plugins row should render'
    assert ELLIPSIS not in plugins_lines[0]


def test_cache_section_sub_hour_format() -> None:
    text, _w = _r.cache_section(187.0, 38)
    stripped = strip_ansi(text)
    assert '03:07' in stripped


def test_cache_section_over_hour_format() -> None:
    text, _w = _r.cache_section(3905.0, 38)
    stripped = strip_ansi(text)
    assert '1:05:05' in stripped


def _inject_clear_epoch(view: SessionView, epoch: float | None) -> SessionView:
    """Inject a clear_epoch value into a SessionView's __dict__ cache."""
    view.__dict__['clear_epoch'] = epoch
    return view


def test_clear_timer_both_shown_at_ample_width(monkeypatch: pytest.MonkeyPatch, silence_dynamic: None) -> None:
    """At a wide terminal both clear and session timers appear in the content row."""
    from yas.constants import GLYPH_CLEAR
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


def test_clear_timer_clear_first_in_cell(monkeypatch: pytest.MonkeyPatch, silence_dynamic: None) -> None:
    """The clear timer is leftmost (lower index) in the content row plain text."""
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


def test_clear_timer_fresh_session_byte_identical(
    monkeypatch: pytest.MonkeyPatch, silence_dynamic: None, frozen_clock: float,
) -> None:
    """Fresh session (clear_epoch=None): top content row is byte-identical to the pre-change render."""
    # frozen_clock pins the rainbow palette, which rolls once a second and would
    # otherwise colour the two builds differently.
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
    monkeypatch: pytest.MonkeyPatch, silence_dynamic: None,
) -> None:
    """When width is too narrow for both timers but fits clear-only, only the
    clear timer renders. Under the declarative precedence, the session timer
    is priority 5 — it degrades (both -> clear-only -> none) well before the
    path/branch/dir (priorities 3/4) are touched, so this transition happens
    at a width where the path is still rendered in full."""
    from yas.constants import GLYPH_CLEAR

    now         = 1_750_000_000.0
    clear_epoch = now - 18 * 60 - 33

    def _render(width: int) -> str:
        view = _view()
        view.__dict__['now']     = now
        view.__dict__['elapsed'] = '13:27'
        _inject_clear_epoch(view, clear_epoch)
        spec = layout.build_wide(view, _tick(), width, _r)
        content_rows = [row for row in spec.rows if row.kind == 'content']
        return content_rows[0].content

    # Wide enough for both timers. (Threshold is 77, not 76: `right_text`'s
    # model-name cell now bakes in a guaranteed trailing space -- see the
    # no-digit-adjacent-to-border fix in renderer.py's `model_right_section`
    # -- which costs the row's shed budget 1 column across the board.)
    plain_both = strip_ansi(_render(77))
    assert '18:33' in plain_both and '13:27' in plain_both

    # Narrower: clear timer present, session timer shed.
    content_clear_only = _render(70)
    plain_clear_only    = strip_ansi(content_clear_only)
    assert GLYPH_CLEAR in content_clear_only, 'clear glyph should be present'
    assert '18:33' in plain_clear_only, 'clear timer should be shown'
    assert '13:27' not in plain_clear_only, 'session timer should be shed'


def test_clear_timer_sheds_entire_cell_on_path_protection(
    monkeypatch: pytest.MonkeyPatch, silence_dynamic: None,
) -> None:
    """When even clear-only doesn't protect the path (< 5 cols), the whole cell sheds."""
    from yas.constants import GLYPH_CLEAR
    from yas.render.text import _visible_width

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


def test_tokens_row_three_elbows_at_wide_width(monkeypatch: pytest.MonkeyPatch, silence_dynamic: None) -> None:
    """At width=140 (>= LINES_SEGMENT_MIN_WIDTH=103) the lines read/changed
    segment is included, so the tokens/cost separator row threads 3 elbows
    (3-tuple downs/ups) instead of the pre-change 2."""
    spec = layout.build_wide(_view(), _tick(), 140, _r)
    # The tokens/cost separator is the separator_dim row immediately above the
    # first tokens content row (the one carrying the 't/m' rate label).
    t_idx = _tokens_row_indices(spec)[0]
    tokens_sep = spec.rows[t_idx - 1]
    assert tokens_sep.kind == 'separator_dim'
    assert len(tokens_sep.downs) == 3, f'expected 3 downs at width=140, got {tokens_sep.downs}'

    # And the render itself shows three interior │/┬/┴ triples aligned.
    lines = [strip_ansi(ln) for ln in layout.render_layout(spec, _r)]
    content_line = lines[t_idx]
    above, below = lines[t_idx - 1], lines[t_idx + 1]
    last = len(content_line) - 1
    interior_bars = [i for i, ch in enumerate(content_line) if ch == '│' and 0 < i < last]
    assert len(interior_bars) == 3, f'expected 3 interior │ at width=140, got {interior_bars}'
    for col in interior_bars:
        assert above[col] in ('┬', '┼'), f'no ┬ above at col {col}: {above[col]!r}'
        assert below[col] in ('┴', '┼'), f'no ┴ below at col {col}: {below[col]!r}'


def test_tokens_row_two_elbows_in_85_102_band(monkeypatch: pytest.MonkeyPatch, silence_dynamic: None) -> None:
    """At width=95 (85 <= width < 103) the lines segment is shed: the
    tokens/cost separator row threads only 2 elbows, identical to before this
    change."""
    spec = layout.build_wide(_view(), _tick(), 95, _r)
    t_idx = _tokens_row_indices(spec)[0]
    tokens_sep = spec.rows[t_idx - 1]
    assert tokens_sep.kind == 'separator_dim'
    assert len(tokens_sep.downs) == 2, f'expected 2 downs at width=95, got {tokens_sep.downs}'


@pytest.mark.parametrize('width', [80, 85, 90, 100, 103, 140])
def test_tokens_row_present_across_lines_segment_threshold(
    monkeypatch: pytest.MonkeyPatch, silence_dynamic: None, width: int,
) -> None:
    """TOKENS_COST_MIN_WIDTH (== MEDIUM_WIDTH == 80) gating is unaffected by the
    new lines segment: the tokens/cost content row (and hence the full, not
    compact, context line) is present at every width from 80 (build_wide's own
    floor) up through and past the 103 lines-segment threshold."""
    spec = layout.build_wide(_view(), _tick(), width, _r)
    assert _tokens_row_indices(spec), f'tokens/cost row missing at width={width}'


def test_context_row_upgrades_at_wide_layout_floor(monkeypatch: pytest.MonkeyPatch, silence_dynamic: None) -> None:
    """Task threshold-alignment: TOKENS_COST_MIN_WIDTH is pinned to
    MEDIUM_WIDTH, so the rich context line (token total + fraction, e.g.
    '150.0K (75%) 100%') and the tokens/cost row's dividers both appear from
    box 80 -- the same box width build_wide itself starts at -- eliminating
    the old 80-84 band where the plugin row showed but the context row was
    still degraded to the compact '75%'-only form."""

    spec = layout.build_wide(_view(), _tick(), 80, _r)
    lines = [strip_ansi(ln) for ln in layout.render_layout(spec, _r)]
    assert _tokens_row_indices(spec), 'tokens/cost row missing at the wide-layout floor (box 80)'
    assert any('%' in ln and '(' in ln for ln in lines), \
        'expected the rich context line (fraction form) at box 80, not the compact one'


def test_plugin_row_and_rich_context_row_copresent_at_wide_layout_floor(
        monkeypatch: pytest.MonkeyPatch, silence_dynamic: None) -> None:
    """Empirical pin for the fixed inconsistency: at box 80 (terminal 86),
    with plugin data present, the plugin row and the rich context row (token
    total + fraction, e.g. '16.0K (8%) 11%') must both render together --
    there must be no band where the plugin row shows while the context row
    is still degraded to the compact percent-only form. Before
    TOKENS_COST_MIN_WIDTH was aligned to MEDIUM_WIDTH, the plugin row (gated
    only by MEDIUM_WIDTH=80) could appear up to 5 box-columns ahead of the
    rich context row (previously gated at 85)."""
    monkeypatch.setattr(session_mod.Workspace, 'plugins', property(lambda self: 'foo,bar'))

    spec  = layout.build_wide(_view(), _tick(), 80, _r)
    lines = [strip_ansi(ln) for ln in layout.render_layout(spec, _r)]

    plugin_lines = [ln for ln in lines if 'foo,bar' in ln]
    assert plugin_lines, 'plugins row should render at box 80'

    assert _tokens_row_indices(spec), 'tokens/cost row missing at box 80 alongside the plugin row'
    assert any('%' in ln and '(' in ln for ln in lines), \
        'expected the rich context line (fraction form) co-present with the plugin row at box 80'


def test_clear_timer_no_additional_elbow(monkeypatch: pytest.MonkeyPatch, silence_dynamic: None) -> None:
    """Adding a clear timer does NOT add a new border elbow (single divider unchanged)."""
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


# --- Subagent Tree View column labels ('loc r/w' anchoring, 'name' offset) ---

def test_tree_labels_loc_slash_stacks_over_data_slash(monkeypatch: pytest.MonkeyPatch, silence_dynamic: None) -> None:
    """The 'loc r/w' header's own '/' must land in the SAME printed column as
    the '/' in a tree row's '<read> /<changed>' data — not at the field's
    start like the (session-level) full-word 'loc read/write' label does."""
    sub = _make_sub()
    sub.jsonl_path = '/fake/ui.jsonl'
    monkeypatch.setattr(
        subagents_mod.RunningSubagents, 'from_session',
        classmethod(lambda cls, sid, pdir, now=None, **kwargs: subagents_mod.RunningSubagents(subagents=[sub])),
    )

    view = SessionView(_session(), Config(labels=True))
    view.__dict__['tool_counts'] = type(
        'FakeTC', (), {
            'counts': {}, 'per_agent': {'/fake/ui.jsonl': (381, 239)},
            'lines_read': 381, 'lines_changed': 239,
        },
    )()

    spec = layout.build_wide(view, _tick(), 200, _r)
    out  = layout.render_layout(spec, _r)

    label_line = next(ln for ln in out if 'ʳᐟʷ' in strip_ansi(ln))
    data_line  = next(ln for ln in out if 'Explore' in strip_ansi(ln) or 'test desc' in strip_ansi(ln))
    label_plain = strip_ansi(label_line)
    data_plain  = strip_ansi(data_line)
    assert label_plain.index('ᐟ') == data_plain.index('/'), (
        f"label '/' at {label_plain.index('ᐟ')} != data '/' at {data_plain.index('/')}"
    )


def test_tree_labels_name_shifted_right_of_desc_col_start(monkeypatch: pytest.MonkeyPatch, silence_dynamic: None) -> None:
    """The 'name' header no longer sits flush against the desc column's exact
    start — it's nudged right so it settles under the actual name text rather
    than crowding the 'model' label to its left."""
    sub = _make_sub()
    monkeypatch.setattr(
        subagents_mod.RunningSubagents, 'from_session',
        classmethod(lambda cls, sid, pdir, now=None, **kwargs: subagents_mod.RunningSubagents(subagents=[sub])),
    )

    view = SessionView(_session(), Config(labels=True))
    spec = layout.build_wide(view, _tick(), 200, _r)

    header_row = next(row for row in spec.rows if row.labels and any(lbl == 'name' for lbl, _ in row.labels))
    name_col  = next(col for lbl, col in header_row.labels if lbl == 'name')
    desc_col, _, _ = tree_columns_for(view)
    assert name_col == 3 + desc_col + 2


def test_context_labels_survive_show_icons_false(monkeypatch: pytest.MonkeyPatch, silence_dynamic: None) -> None:
    """The `context`/`fill`/`dumb` separator labels are anchored off the
    hourglass glyph in `context_line`. With show_icons=False the glyph is
    gone, so the anchor must fall back to the first token instead of
    silently dropping the whole label row."""
    view = SessionView(_session(), Config(labels=True, show_icons=False))
    spec = layout.build_wide(view, _tick(), 200, _r)

    ctx_row = next(
        (row for row in spec.rows if row.labels and any(lbl == 'context' for lbl, _ in row.labels)),
        None,
    )
    assert ctx_row is not None, 'expected a `context` label even with show_icons=False'


def test_helper_row_show_icons_false_drops_5h7d_and_flame_when_gaps_widen(
    monkeypatch: pytest.MonkeyPatch, silence_dynamic: None,
) -> None:
    """`build_wide` re-derives ``helper_5h``/``helper_7d`` a second time once it
    widens the inter-stat gaps to spend justification slack (``gap_5h``/
    ``gap_7d`` != 1) — that second `_rate_helpers` call must also thread
    ``show_icons``, or the 5h/7d clock/calendar glyphs and the burndown flame
    reappear in the top row regardless of the config. Sweeps widths since the
    widen-gaps branch only fires once enough slack accumulates."""
    from yas.constants import ICON_LIMIT_5H, ICON_LIMIT_7D, GLYPH_BURN_FAST, GLYPH_BURN_SLOW

    view = SessionView(_session(), Config(show_icons=False))
    for width in (140, 160, 180, 200, 220):
        spec = layout.build_wide(view, _tick(), width, _r)
        out  = layout.render_layout(spec, _r)
        plain = '\n'.join(strip_ansi(ln) for ln in out)
        for glyph in (ICON_LIMIT_5H, ICON_LIMIT_7D, GLYPH_BURN_FAST, GLYPH_BURN_SLOW):
            assert glyph not in plain, f'{glyph!r} leaked at width={width} with show_icons=False'


def test_path_row_show_icons_false_drops_folder_glyph(monkeypatch: pytest.MonkeyPatch, silence_dynamic: None) -> None:
    """The leading folder glyph in the top-left path row is gated by
    show_icons like every other number-adjacent icon. With icons off the
    glyph must not leak into build_medium or build_wide, and the row must
    still render (box stays square — widths are always _visible_width-derived,
    so no separate shift bookkeeping is needed here)."""
    from yas.constants import GLYPH_FOLDER

    view = SessionView(_session(), Config(show_icons=False))
    for width in (90, 120, 160, 200):
        specs = [
            ('build_medium', layout.build_medium(view, width, _r)),
            ('build_wide', layout.build_wide(view, _tick(), width, _r)),
        ]
        for name, spec in specs:
            out  = layout.render_layout(spec, _r)
            plain = '\n'.join(strip_ansi(ln) for ln in out)
            assert GLYPH_FOLDER not in plain, (
                f'{GLYPH_FOLDER!r} leaked from {name} at width={width} '
                'with show_icons=False'
            )
            for ln in out:
                assert len(strip_ansi(ln)) > 0


def tree_columns_for(view: SessionView) -> tuple[int, int, int]:
    """Recompute the same desc/stats/activity anchors `build_wide` used, so
    the test can assert the label's offset relative to them without
    hardcoding a width-specific magic number."""
    from yas.layout import tree_columns, tree_model_width, tree_lines_width, subagent_cluster_width
    sub_cells = layout.subagent_cells(view.subagents.visible(0, None))
    inner = 200 - 4
    model_w = tree_model_width(sub_cells)
    lines_w = tree_lines_width(sub_cells, view.tool_counts.per_agent)
    cluster_w = subagent_cluster_width(lines_w)
    return tree_columns(sub_cells, inner, cluster_full_w=cluster_w, model_w=model_w)


def _narrow_divider_content_idx(spec: layout.LayoutSpec) -> list[int]:
    """Indices of content rows carrying the narrow-tier side-by-side divider │.

    `build_narrow` has no `separator_seam` marker (that's a `build_wide`-only
    dynamic-section concept), so — unlike `_divider_content_idx` — this scans
    every content row's `downs`/`ups`-adjacent block directly: a row is part
    of the side-by-side block only if a `│` appears at the SAME visible
    column across a contiguous run bracketed by `separator_dim` rows whose
    `downs`/`ups` name that column. Simpler in practice: just take content
    rows containing a bare `│` (ANSI-stripped) — narrow's other content rows
    (rate/model header, compact plan summary, context line) never contain one.
    """
    return [
        i for i, row in enumerate(spec.rows)
        if row.kind == 'content' and '│' in strip_ansi(row.content)
    ]

def test_narrow_side_by_side_below_floor_falls_back_to_stacking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Below NARROW_SIDE_BY_SIDE_MIN_WIDTH (45), build_narrow keeps stacking
    plan above subagents (the old compact single-line plan header) rather
    than forcing an unreadable two-column split."""
    from yas.constants import NARROW_SIDE_BY_SIDE_MIN_WIDTH
    _both_sections(monkeypatch)

    width = NARROW_SIDE_BY_SIDE_MIN_WIDTH - 1
    spec  = layout.build_narrow(_view(), width, _r)
    assert not _narrow_divider_content_idx(spec), (
        'no interior column divider expected below the side-by-side floor'
    )
    lines = [strip_ansi(ln) for ln in layout.render_layout(spec, _r)]
    plain = '\n'.join(lines)
    # The old compact plan header (glyph + done/total) is still present.
    assert '1/3' in plain


def test_narrow_side_by_side_at_and_above_floor_has_continuous_divider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """At/above NARROW_SIDE_BY_SIDE_MIN_WIDTH, build_narrow lays the plan
    checklist and subagent cohort out side-by-side with a continuous divider
    column — same ┬/│/┴ threading invariant as the wide-tier split.

    Uses `_both_sections_narrow_stress` (>=4 completed tasks + a Total
    Elapsed timer wider than any item's own duration) rather than the plain
    3-task `_both_sections` fixture: that plain fixture never pushes
    `task_row`'s narrow field-width math into its own internal floor
    (`avail = max(1, ...)`), so a header/item divider-column drift regression
    there sailed through this test's every-sampled-width check silently —
    exactly what happened with the off-by-one this test is now written to
    catch. Checks EVERY width 45-54 (not a 3-point sample) and every row's
    divider column against the FIRST row of the block (the top border, not
    just the header/item content rows), so a border-vs-content drift and a
    header-vs-item drift are both caught the same way.
    """
    from yas.render.text import _visible_width
    from yas.constants import NARROW_SIDE_BY_SIDE_MIN_WIDTH
    _both_sections_narrow_stress(monkeypatch)

    for width in range(NARROW_SIDE_BY_SIDE_MIN_WIDTH, 55):
        spec = layout.build_narrow(_view(), width, _r)
        combined_idx = _narrow_divider_content_idx(spec)
        assert combined_idx, f'expected a side-by-side block with a divider at width={width}'
        div_cols = {3 + strip_ansi(spec.rows[i].content).index('│') for i in combined_idx}
        assert len(div_cols) == 1, f'divider column drifts across rows at width={width}: {div_cols}'
        divider_col = div_cols.pop()

        first, last = combined_idx[0], combined_idx[-1]
        assert combined_idx == list(range(first, last + 1)), 'combined block is not contiguous'
        above = spec.rows[first - 1]
        below = spec.rows[last + 1]
        assert divider_col in above.downs, f'separator above missing ┬ at {divider_col}: {above.downs}'
        assert divider_col in below.ups,   f'separator/border below missing ┴ at {divider_col}: {below.ups}'

        # Check EVERY rendered line's actual glyph at the divider column —
        # the top border (┬), every combined content row (│, header AND
        # items alike), and the bottom separator/border (┴) — not just a
        # subset of the combined rows. This is what actually caught the
        # header-vs-item drift: the header row alone matched the border's
        # column, but the item rows (below it, past the false floor a
        # smaller fixture never exercised) did not.
        lines = [strip_ansi(ln) for ln in layout.render_layout(spec, _r)]
        for ln in lines:
            assert _visible_width(ln) == width, f'row not full width: {_visible_width(ln)} != {width}'
        col = divider_col - 1
        assert lines[first - 1][col] in ('┬', '┼'), f'no ┬ above at width={width}: {lines[first - 1][col]!r}'
        for i in combined_idx:
            assert lines[i][col] == '│', (
                f'no │ at the shared divider column in row {i} (content: {lines[i]!r}) at width={width}'
            )
        assert lines[last + 1][col] in ('┴', '┼'), f'no ┴ below at width={width}: {lines[last + 1][col]!r}'


def test_narrow_side_by_side_plan_name_sheds_before_subagent_type_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cross-column precedence: at the side-by-side floor, the plan column is
    pinned to PLAN_ONELINE_MIN_W (its item name truncated hard) while the
    subagent column still gets its full untruncated type+model text, if
    there is enough total room for the subagent column's untruncated floor
    at all — i.e. plan item name (priority 4) sheds before subagent
    type/model (priority 3), never the other way around."""
    from yas.constants import ELLIPSIS, PLAN_ONELINE_MIN_W
    _both_sections(monkeypatch)

    view = _view()
    cells = layout.subagent_cells(view.subagents.visible(0, None))
    right_floor = layout.oneline_right_floor(cells)

    # A width where the subagent column's untruncated floor is reachable
    # (avail - PLAN_ONELINE_MIN_W >= right_floor) but the plan column has no
    # slack left over — i.e. plan is at its floor and subagent is at its
    # natural (untruncated) width simultaneously.
    width = right_floor + PLAN_ONELINE_MIN_W + 7
    spec  = layout.build_narrow(view, width, _r)
    combined_idx = _narrow_divider_content_idx(spec)
    assert combined_idx, 'expected a side-by-side block at this width'
    divider_col = 3 + strip_ansi(spec.rows[combined_idx[0]].content).index('│')
    left_w = divider_col - 3 - 1  # content starts at col 3; divider sits 1 col after left_w
    assert left_w == PLAN_ONELINE_MIN_W, (
        f'plan column should be pinned to its floor ({PLAN_ONELINE_MIN_W}) '
        f'once the subagent column claims its untruncated width, got {left_w}'
    )
    # The subagent side shows the model name in full (no mid-word ellipsis)
    # at this width, confirming type/model (priority 3) survived intact.
    plain = strip_ansi(spec.rows[combined_idx[0]].content)
    assert 'sonnet' in plain and ELLIPSIS not in plain.split('│', 1)[1], (
        f'expected an untruncated model name on the subagent side: {plain!r}'
    )


def test_top_row_justify_padding_capped_at_wide_widths(monkeypatch: pytest.MonkeyPatch, silence_dynamic: None) -> None:
    """Finding C (width-gap audit): without a cap, `total_slack` (path/
    elapsed/5h/7d/cache justify breathing room) scales linearly with `width`
    once nothing is being shed, so an equal N-way split turned into several
    individually growing, uncapped blank runs scattered across the top row.
    Every "extra" slot but the last is now capped at
    `TOPROW_JUSTIFY_OUTER_CAP`; the last slot (ahead of the model pill)
    absorbs whatever slack the others couldn't. So at any width there should
    be AT MOST ONE blank run wider than the cap — everything else stays
    small regardless of how wide the box gets."""
    import re
    from yas.constants import TOPROW_JUSTIFY_OUTER_CAP
    session = _session()

    for width in (150, 200, 250, 300, 350):
        view = SessionView(session, Config(justify=True))
        spec = layout.build_wide(view, _tick(), width, _r)
        content_rows = [row for row in spec.rows if row.kind == 'content']
        plain = strip_ansi(content_rows[0].content)
        gaps  = [len(m.group()) for m in re.finditer(r' {2,}', plain)]
        oversized = [g for g in gaps if g > TOPROW_JUSTIFY_OUTER_CAP]
        assert len(oversized) <= 1, (
            f'width={width}: expected at most one uncapped gap run '
            f'(the trailing slot), got {len(oversized)}: {gaps}'
        )


def test_top_row_justify_never_overflows_the_box_with_short_model_form(
    monkeypatch: pytest.MonkeyPatch, silence_dynamic: None,
) -> None:
    """Regression for the `model_form='short'` shed-rung justify bug: at the
    last-resort rung (`build_wide` narrows the model pill instead of dropping
    5h), widening the 5h helper's inner separators (`gap_5h`) unconditionally
    reassigned `helper_7d` from a fresh `Renderer._rate_helpers` call, even
    when 7d had already been shed for width (`has_7d=False`) -- resurrecting
    the dropped 7d text un-padded into `helper_text`. That silently overflowed
    the top row past its own border by exactly the 7d section's width, at
    every width in the `model_form='short'` band except the (coincidentally
    zero-total_slack) 82-86 sub-band. Sweep the whole band and assert every
    rendered line is exactly `width` -- never over, matching border_line's
    own "pad, never truncate" contract."""
    from yas.render.text import _visible_width
    session = _session()
    long_model = session_mod.Model(
        id='claude-opus-5[1m]',
        display_name='Opus 5 Extended Thinking Reasoning Deep Research Preview 1M',
    )
    session.__dict__.update(
        model=long_model,
        rate_limits=session_mod.RateLimits(
            session_mod.RateBucket(35.0, 0), session_mod.RateBucket(24.0, 0),
        ),
    )

    for width in range(78, 111):
        view = SessionView(session, Config(justify=True))
        spec = layout.build_wide(view, _tick(), width, _r)
        lines = layout.render_layout(spec, _r)
        for ln in lines:
            assert _visible_width(ln) <= width, (
                f'width={width}: row overflows the box: '
                f'{_visible_width(ln)} > {width}: {ln!r}'
            )


def test_top_row_justify_matches_unjustified_when_slack_absorbed_by_cap(
    monkeypatch: pytest.MonkeyPatch, silence_dynamic: None,
) -> None:
    """The cap only bounds each slot's OWN growth; it must not change how
    much total width the row consumes (still exactly `width`, via
    `border_line`'s pad) or which sections are present."""
    from yas.render.text import _visible_width
    session = _session()

    for width in (150, 250, 350):
        view = SessionView(session, Config(justify=True))
        spec = layout.build_wide(view, _tick(), width, _r)
        lines = layout.render_layout(spec, _r)
        for ln in lines:
            assert _visible_width(ln) == width, (
                f'width={width}: row overflows/underfills the box: '
                f'{_visible_width(ln)} != {width}'
            )


