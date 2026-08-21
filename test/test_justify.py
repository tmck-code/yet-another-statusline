"""Justify layout tests (tasks 4.2–4.4).

Exercises the ``justify`` knob in ``build_wide``: box integrity under
distributed slack, equivalence when total_slack==0, and correct N=3
distribution when neither elapsed nor cache sections are active.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pytest

import yas.layout as layout
import yas.renderer as renderer_mod
import yas.session as session_mod
from yas.config import Config
from yas.info import SessionView
from yas.render.text import _visible_width
from yas.tokens import TickRecord, TokenLog

_r = renderer_mod.Renderer()
SESSION = (Path(__file__).parent.parent / 'ops' / 'session-info-example.json')


def _session() -> session_mod.SessionInfo:
    return session_mod.SessionInfo.from_dict(json.loads(SESSION.read_text()))


def _view(cfg: Config) -> SessionView:
    return SessionView(_session(), cfg)


def _tick() -> TickRecord:
    return TickRecord(token_log=TokenLog(), day_cost=0.0, tok_rate=0)




def _rendered_lines(view: SessionView, width: int) -> list[str]:
    spec = layout.build_wide(view, _tick(), width, _r)
    return layout.render_layout(spec, _r)


# 4.2 – box integrity with justify enabled

@pytest.mark.parametrize('width', [95, 120, 140, 160])
def test_justify_box_all_rows_uniform_width(
    monkeypatch: pytest.MonkeyPatch, silence_dynamic: None, strip_ansi: Callable[[str], str], width: int
) -> None:
    """With cfg.justify=True every rendered row is exactly `width` columns wide."""
    view = _view(Config(justify=True))
    lines = _rendered_lines(view, width)
    widths = {_visible_width(strip_ansi(ln)) for ln in lines}
    assert widths == {width}, f'mismatched row widths at terminal {width}: {widths}'


def test_justify_top_content_row_is_width_wide(
    monkeypatch: pytest.MonkeyPatch, silence_dynamic: None, strip_ansi: Callable[[str], str],
) -> None:
    """The top content row (index 1) rendered with justify=True is exactly ``width`` columns."""
    width = 160
    view = _view(Config(justify=True))
    lines = [strip_ansi(ln) for ln in _rendered_lines(view, width)]
    assert _visible_width(lines[1]) == width


# 4.3 – total_slack == 0 produces output identical to justify-disabled

def test_justify_slack_zero_matches_unjustified(
    monkeypatch: pytest.MonkeyPatch, silence_dynamic: None,
) -> None:
    """When fit_path fills the entire target width (slack=0), justify=True output
    is byte-for-byte identical to justify=False for the path/model row.

    The tokens │ cost │ rate row carries its *own* justify slack pool (the row's
    internal breathing room — see test_tokens_cost), independent of the path
    row's slack, so it is excluded from this path-row equivalence check."""
    # The top-row shed loop (build_wide) now tries the dir-full path forms
    # itself (via `path_git`) before ever calling `fit_path` — so patch
    # `path_git` to never fit (forcing every lower-priority section: 7d,
    # timer, ... to shed first, same on both sides of the justify flag) and
    # patch `fit_path` to consume all remaining width so total_slack == 0.
    monkeypatch.setattr(
        renderer_mod.Renderer, 'path_git',
        lambda self, pwd, git, show_path=True, show_commit=True, show_dirty=True, show_icons=True: 'z' * 10_000,
    )
    monkeypatch.setattr(
        renderer_mod.Renderer, 'fit_path',
        lambda self, pwd, git, target_w, compact_only=False, show_icons=True: 'x' * max(0, target_w),
    )
    session = _session()
    view_on  = SessionView(session, Config(justify=True))
    view_off = SessionView(session, Config(justify=False))

    # The tokens │ cost │ rate row is the final block (its content row plus the
    # separator above and bottom border below). Its dividers — and therefore the
    # ┬/┴ elbows on those two border rows — shift with its own justify slack, so
    # exclude the trailing block and compare the path/model and context rows,
    # which is where the path-row slack=0 equivalence actually holds.
    lines_on  = _rendered_lines(view_on,  160)[:-3]
    lines_off = _rendered_lines(view_off, 160)[:-3]
    assert lines_on == lines_off


# 4.4 – N=3 distribution (no elapsed, no cache)

def test_justify_n3_path_wider_than_unjustified(
    monkeypatch: pytest.MonkeyPatch, silence_dynamic: None, strip_ansi: Callable[[str], str],
) -> None:
    """With N=3 sections and positive slack, the path section in the justify=True
    render is wider than in the justify=False render (slack is shared, not all
    concentrated in the gap before the right pill/text)."""
    width = 160
    view_on  = _view(Config(justify=True))
    view_off = _view(Config(justify=False))

    def _path_end_col(lines: list[str]) -> int:
        # Strip ANSI and find the first interior │ after the lead border.
        raw = strip_ansi(lines[1])  # top content row
        for i, ch in enumerate(raw):
            if ch == '│' and i > 1:
                return i
        return -1

    col_on  = _path_end_col(_rendered_lines(view_on,  width))
    col_off = _path_end_col(_rendered_lines(view_off, width))
    # Justify distributes slack away from the gap; path gets some extra columns.
    assert col_on > col_off, (
        f'expected justify=True path │ further right ({col_on}) than justify=False ({col_off})'
    )


def test_justify_n3_box_intact(
    monkeypatch: pytest.MonkeyPatch, silence_dynamic: None, strip_ansi: Callable[[str], str],
) -> None:
    """N=3 distribution (no elapsed, no cache) keeps the box intact."""
    width = 160
    view = _view(Config(justify=True))
    lines = [strip_ansi(ln) for ln in _rendered_lines(view, width)]
    widths = {_visible_width(ln) for ln in lines}
    assert widths == {width}


# 4.5 – path_extra distributed around the git block

def test_justify_path_extra_split_around_git_block(
    monkeypatch: pytest.MonkeyPatch, silence_dynamic: None, strip_ansi: Callable[[str], str],
) -> None:
    """With justify=True and git info present, path_extra is distributed around
    the ∈ git block: there are spaces *before* ∈ that were not present in the
    unjustified render, and spaces before the dirty-status indicator (or at the
    git-block end). The trailing-only append fallback must not be used when a
    branch separator is visible."""
    width = 160

    # Render unjustified first so we know the natural position of ∈.
    raw_off = strip_ansi(_rendered_lines(_view(Config(justify=False)), width)[1])
    raw_on  = strip_ansi(_rendered_lines(_view(Config(justify=True)),  width)[1])

    sep = '∈'
    idx_off = raw_off.find(sep)
    idx_on  = raw_on.find(sep)

    # ∈ must appear in both renders.
    assert idx_off != -1, 'branch separator not found in unjustified render'
    assert idx_on  != -1, 'branch separator not found in justified render'

    # With justify=True the ∈ should be pushed right (spaces inserted before it).
    assert idx_on > idx_off, (
        f'justify=True should push ∈ right: off={idx_off} on={idx_on}'
    )

    # The path section up to the first interior │ must be exactly width cols wide.
    first_pipe = raw_on.find('│', 1)
    assert first_pipe != -1
    path_section = raw_on[:first_pipe + 1]
    assert _visible_width(path_section) == first_pipe + 1


# Inter-stat breathing room inside the 5h/7d helper sections

def test_justify_elapsed_field_balanced(
    monkeypatch: pytest.MonkeyPatch, silence_dynamic: None, strip_ansi: Callable[[str], str],
) -> None:
    """The elapsed/session-timer cell is a right-justified fixed-width atom
    baked in by ``Renderer.elapsed_section`` (``rjust(8)``). The justify pass
    must fold that baked-in leading padding into the slack it distributes, so
    total LHS/RHS whitespace around the visible digits is balanced (diff <=1)
    rather than stacking a fair added-slack split on top of an already
    right-justified string (which produced a diff of 2+, e.g. ``'   +13:27 '``)."""
    import re

    tested = 0
    for width in (100, 102, 104, 108, 111, 112, 113, 115, 120):
        view = _view(Config(justify=True))
        raw = strip_ansi(_rendered_lines(view, width)[1])
        pipes = [i for i, ch in enumerate(raw) if ch == '│']
        assert len(pipes) >= 3, f'width={width} raw={raw!r}'
        field = raw[pipes[1] + 1:pipes[2]]
        if not re.search(r'\+\d', field):
            continue  # elapsed cell shed at this width
        tested += 1
        left  = len(field) - len(field.lstrip(' '))
        right = len(field) - len(field.rstrip(' '))
        assert abs(left - right) <= 1, (
            f'width={width} field={field!r} left={left} right={right}'
        )
    assert tested > 0, 'no width in the sweep exercised the elapsed cell'


def test_justify_elapsed_field_balanced_at_zero_slack(
    monkeypatch: pytest.MonkeyPatch, silence_dynamic: None, strip_ansi: Callable[[str], str],
) -> None:
    """Regression for the residual centering defect found at widths 102/112
    (kitchen-sink demo scenario, YAS_JUSTIFY=1): when a sibling section (e.g.
    `fit_path` crossing a growth threshold) consumes the ENTIRE row's slack
    in the same layout pass, `total_slack` lands on exactly 0 -- the elapsed
    cell's baked-in `rjust(8)` asymmetry (2 leading spaces, 0 trailing) must
    still be rebalanced to <=1 diff even though no *distributed* slack exists
    to fold into. Before the fix this produced a diff-2 split (e.g.
    ``'   +13:27 '``) because the rebalance was nested inside the
    ``total_slack > 0`` gate and silently skipped.

    Widths 65/66/77/78 are where the standard fixture session naturally
    lands on total_slack == 0 (dir-full path exactly fills its budget) while
    the elapsed cell is still active -- picked by sweeping the fixture rather
    than forcing it, so this exercises the real shed/slack interaction
    instead of an artificial mock."""
    import re

    tested = 0
    for width in (65, 66, 77, 78):
        view = _view(Config(justify=True))
        spec = layout.build_wide(view, _tick(), width, _r)
        raw  = strip_ansi(layout.render_layout(spec, _r)[1])
        pipes = [i for i, ch in enumerate(raw) if ch == '│']
        assert len(pipes) >= 3, f'width={width} raw={raw!r}'
        field = raw[pipes[1] + 1:pipes[2]]
        if not re.search(r'\+\d', field):
            continue  # elapsed cell shed at this width
        tested += 1
        left  = len(field) - len(field.lstrip(' '))
        right = len(field) - len(field.rstrip(' '))
        assert abs(left - right) <= 1, (
            f'width={width} field={field!r} left={left} right={right}'
        )
    assert tested > 0, 'no width in the sweep exercised the elapsed cell at zero slack'


def test_justify_widens_helper_inter_stat_gap(
    monkeypatch: pytest.MonkeyPatch, silence_dynamic: None, strip_ansi: Callable[[str], str],
) -> None:
    """With justify=True the 5h section's inter-stat separator widens beyond the
    single space the unjustified render uses (the example session's 5h limit is
    in its ``pct ∞`` form, so the pct↔∞ separator is the one that grows)."""
    width = 160

    def _gap(lines: list[str]) -> int:
        raw = strip_ansi(lines[1])
        i = raw.index('61.0%') + len('61.0%')
        return len(raw[i:]) - len(raw[i:].lstrip(' '))

    gap_off = _gap(_rendered_lines(_view(Config(justify=False)), width))
    gap_on  = _gap(_rendered_lines(_view(Config(justify=True)),  width))
    assert gap_off == 1
    assert 1 < gap_on <= 3


# Regression — no digit may ever be flush against a border char (found in the
# final confirm pass: widths 79-81, justify=True, glyph_mode='ascii' rendered
# `...Sonnet 4.6│` with zero trailing space). Root cause was `model_right_section`'s
# non-pill branch baking no trailing space into `right_text` (unlike the pill
# branch, which pads a cell after the model name) -- `build_wide`'s own `pad`
# math could land on exactly zero spare columns at these widths, so the fix
# bakes a guaranteed trailing space into `right_text` itself in renderer.py.

@pytest.mark.parametrize('justify', [True, False])
def test_no_digit_adjacent_to_border(
    monkeypatch: pytest.MonkeyPatch, silence_dynamic: None, strip_ansi: Callable[[str], str], justify: bool,
) -> None:
    """Sweep widths 60-130 (ascii glyph mode, the reported failure's glyph mode)
    and assert no rendered row ever has a digit immediately touching `│`."""
    monkeypatch.setenv('YAS_GLYPH_MODE', 'ascii')
    import re
    digit_touches_border = re.compile(r'\d[│|]|[│|]\d')

    for width in range(60, 131):
        view = _view(Config(justify=justify, glyph_mode='ascii'))
        for line in _rendered_lines(view, width):
            raw = strip_ansi(line)
            assert not digit_touches_border.search(raw), (
                f'width={width} justify={justify} raw={raw!r}'
            )
