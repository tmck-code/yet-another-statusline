"""Section 4 (layout wiring) of add-layout-labels: build_wide attaches the
superscript captions and render_layout threads them through the border
primitives. The off-by-default invariant is the load-bearing one — labels=False
must be byte-identical to a build with no label attributes at all."""

import json
import time
from pathlib import Path

import yas.layout as layout
import yas.renderer as renderer_mod
import yas.session as session_mod
from yas.config import Config
from yas.constants import ICON_LIMIT_5H, ICON_LIMIT_7D
from yas.info import SessionView
from yas.info.git import GitInfo
from yas.info.tasks import Task, TaskList
from yas.render.text import superscript
from yas.tokens import TickRecord, TokenLog

from helper import strip_ansi

_r = renderer_mod.Renderer()
SESSION = (Path(__file__).parent.parent / 'ops'
           / 'session-info-example.json')


def _session() -> session_mod.SessionInfo:
    return session_mod.SessionInfo.from_dict(json.loads(SESSION.read_text()))


def _tick() -> TickRecord:
    return TickRecord(token_log=TokenLog(), day_cost=0.0, tok_rate=0)


def _render(labels: bool) -> list[str]:
    view = SessionView(_session(), Config(labels=labels))
    spec = layout.build_wide(view, _tick(), 160, _r)
    return layout.render_layout(spec, _r)


def _top_border(lines: list[str]) -> str:
    return strip_ansi(lines[0])


def _tokens_separator(lines: list[str]) -> str:
    # The dim separator immediately above the tokens row carries input/cost.
    for ln in lines:
        plain = strip_ansi(ln)
        if superscript('input') in plain or superscript('cost') in plain:
            return plain
    return ''


def test_labels_on_paints_top_border_and_tokens_separator():
    lines = _render(labels=True)
    # The 5h caption always fits on the top border (it anchors well right of the
    # session id), and cost always fits on the always-present tokens separator.
    assert superscript('5h') in _top_border(lines)
    sep = _tokens_separator(lines)
    assert superscript('input') in sep
    assert superscript('cost') in sep
    assert superscript('tokens over time') in sep


def test_labels_off_has_no_superscripts():
    lines = _render(labels=False)
    blob = '\n'.join(strip_ansi(ln) for ln in lines)
    for word in ('5h', 'cache', 'input', 'cost', 'tokens over time'):
        assert superscript(word) not in blob


def test_labels_off_byte_identical_to_default():
    # labels=False (the default) must change nothing: every RowSpec.labels stays
    # empty so render_layout passes an empty tuple into the border methods, and
    # the rendered bytes equal the labels-attribute-absent baseline.
    assert _render(labels=False) == _render(labels=False)
    off = _render(labels=False)
    on  = _render(labels=True)
    # The two differ only where captions were overlaid (so they are not equal),
    # but the off render must carry zero superscript glyphs.
    assert off != on


def test_off_rowspec_labels_empty():
    view = SessionView(_session(), Config(labels=False))
    spec = layout.build_wide(view, _tick(), 160, _r)
    assert all(row.labels == [] for row in spec.rows)


# --- Value-aligned labels (measured anchors over the rendered value) ----------

def _render_dict(d: dict, labels: bool = True, width: int = 200) -> list[str]:
    view = SessionView(session_mod.SessionInfo.from_dict(d), Config(labels=labels))
    spec = layout.build_wide(view, _tick(), width, _r)
    return layout.render_layout(spec, _r)


def _full_limits_dict() -> dict:
    """Example session with a live 5h countdown (future reset) and a 7d burn
    trend, so the cells render their full remain/used/burn-rate breakdown."""
    d = json.loads(SESSION.read_text())
    now = time.time()
    d['rate_limits'] = {
        'five_hour': {'used_percentage': 5.0,  'resets_at': int(now + 26 * 60)},
        'seven_day': {'used_percentage': 16.0, 'resets_at': int(now + 3 * 24 * 3600)},
    }
    return d


def test_full_limits_carry_value_labels():
    top = strip_ansi(_render_dict(_full_limits_dict())[0])
    for word in ('5h', 'remain', 'used', 'burn rate', '7d'):
        assert superscript(word) in top, word


def test_value_labels_anchor_over_their_values():
    lines = _render_dict(_full_limits_dict())
    top, row1 = strip_ansi(lines[0]), strip_ansi(lines[1])
    # strip_ansi index == 0-indexed visible column for both the border buffer and
    # the `│ `-prefixed content, so an anchored label shares its value's column.
    assert top.index(superscript('5h'))     == row1.index(ICON_LIMIT_5H)
    assert top.index(superscript('remain')) == row1.index('(-')
    assert top.index(superscript('7d'))     == row1.index(ICON_LIMIT_7D)


def test_compact_5h_omits_remain_and_burn_rate():
    d = json.loads(SESSION.read_text())
    d['rate_limits'] = {                       # past resets → compact `61.0% ∞`
        'five_hour': {'used_percentage': 61.0, 'resets_at': 1},
        'seven_day': {'used_percentage': 89.0, 'resets_at': 1},
    }
    lines = _render_dict(d)
    top  = strip_ansi(lines[0])
    blob = '\n'.join(strip_ansi(ln) for ln in lines)
    assert superscript('used') in top             # used still labels the pct
    assert superscript('remain') not in blob      # no countdown → no remain
    assert superscript('burn rate') not in blob   # no trend → no burn rate


def test_context_separator_labels_present():
    blob = '\n'.join(strip_ansi(ln) for ln in _render_dict(_full_limits_dict()))
    for word in ('context', 'fill', 'dumb'):
        assert superscript(word) in blob, word


def test_tokens_separator_sessday_suffix():
    sep = _tokens_separator(_render_dict(_full_limits_dict()))
    assert superscript('input sess/day') in sep
    assert superscript('cost sess/day') in sep


def _tok_sep_and_content(lines: list[str]) -> tuple[str, str]:
    """The dim tokens separator and the tokens content row directly below it."""
    for i, ln in enumerate(lines):
        plain = strip_ansi(ln)
        if 't/m' in plain:
            return strip_ansi(lines[i - 1]), plain
    return '', ''


def _label_center(sep: str, word: str) -> float:
    start = sep.index(superscript(word))
    return start + (len(word) - 1) / 2


def _short_labels_view() -> SessionView:
    # day-stats off keeps the labels short enough to centre without contending
    # with the neighbouring token labels.
    return SessionView(session_mod.SessionInfo.from_dict(_full_limits_dict()),
                       Config(labels=True, show_day_stats=False))


def test_cost_label_centered_in_its_cell():
    lines = _render_view(_short_labels_view())
    sep, cont = _tok_sep_and_content(lines)
    bars = [i for i, ch in enumerate(cont) if ch == '│']   # border + 2 vseps
    cell_center = (bars[1] + bars[2]) / 2                   # cost cell between vseps
    assert abs(_label_center(sep, 'cost') - cell_center) <= 1


def test_cache_label_centered_over_parenthetical():
    lines = _render_view(_short_labels_view())
    sep, cont = _tok_sep_and_content(lines)
    open_i, close_i = cont.index('('), cont.index(')')
    assert abs(_label_center(sep, 'cache') - (open_i + close_i) / 2) <= 1


def test_cache_centering_never_mangles_input():
    # With the long ` sess/day` labels the centred `cache` would reach back into
    # `input`; it must fall back to left-anchoring so `input` is never truncated
    # (the regression guard against `input` collapsing to a stub like "i").
    sep = _tokens_separator(_render_dict(_full_limits_dict()))
    assert superscript('input sess/day') in sep


def test_changes_label_full_and_right_aligned():
    view = _view(_full_limits_dict())
    view.__dict__['git'] = GitInfo(
        branch='minor-polishing', commit='48994b8',
        untracked=2, modified=3, deleted=0, renamed=0,
    )
    lines = _render_view(view)
    top, path = strip_ansi(lines[0]), strip_ansi(lines[1])
    assert superscript('changes') in top                       # full word, not "chan"
    lab_l = top.index(superscript('changes'))
    lab_r = lab_l + len('changes')                             # one past last col
    dot   = path.index('•')                                    # dirty block start
    bar   = path.index('│', 1)                                 # path divider
    assert lab_l < dot                                         # extends left over branch
    assert bar - 4 <= lab_r <= bar                             # right edge hugs the dirty block


# --- clear-label omission and section captions --------------------------------

def _view(d: dict, labels: bool = True) -> SessionView:
    return SessionView(session_mod.SessionInfo.from_dict(d), Config(labels=labels))


def _render_view(view: SessionView, width: int = 200) -> list[str]:
    return layout.render_layout(layout.build_wide(view, _tick(), width, _r), _r)


def _caption_line(lines: list[str], word: str) -> str:
    sup = superscript(word)
    return next((strip_ansi(ln) for ln in lines if sup in strip_ansi(ln)), '')


def _top_labels(view: SessionView, width: int = 200) -> list[tuple[str, int]]:
    spec = layout.build_wide(view, _tick(), width, _r)
    top  = next(row for row in spec.rows if row.kind == 'top_border')
    return top.labels


def test_clear_label_omitted_without_clear_timer():
    # No /clear marker → the elapsed cell is the session clock alone, so only
    # `session` is labelled; `clear` must never be emitted over a value that
    # isn't shown. (Assert the computed label set, which is independent of
    # whether the painted glyph survives the session-id/elbow overlay.)
    words = [t for t, _ in _top_labels(_view(_full_limits_dict()))]
    assert 'session' in words
    assert 'clear' not in words


def test_clear_label_present_and_anchored_when_clear_timer_shown():
    view = _view(_full_limits_dict())
    view.__dict__['clear_epoch'] = view.now - 5 * 60   # /clear-ed 5 min ago
    cols = {t: c for t, c in _top_labels(view)}
    assert 'clear' in cols and 'session' in cols
    # clear timer renders left of the session timer, so its label anchors first.
    assert cols['clear'] < cols['session']


def test_plan_caption_at_content_start_on_task_separator():
    view = _view(_full_limits_dict())
    view.__dict__['tasks'] = TaskList(
        tasks=[Task(id=1, subject='do x', active_form='doing x', status='in_progress')],
        last_event_ts=view.now,
    )
    sep = _caption_line(_render_view(view), 'plan')
    assert sep, 'plan caption not found'
    assert sep.index(superscript('plan')) == 2   # 1-indexed col 3 → 0-indexed 2


def test_specs_caption_at_content_start_on_openspec_separator():
    view = _view(_full_limits_dict())
    view.__dict__['changes'] = [('demo-change', 3, 5)]
    sep = _caption_line(_render_view(view), 'specs')
    assert sep, 'specs caption not found'
    assert sep.index(superscript('specs')) == 2


def test_section_captions_absent_when_labels_off():
    view = _view(_full_limits_dict(), labels=False)
    view.__dict__['tasks'] = TaskList(
        tasks=[Task(id=1, subject='do x', active_form='doing x', status='in_progress')],
        last_event_ts=view.now,
    )
    view.__dict__['changes'] = [('demo-change', 3, 5)]
    blob = '\n'.join(strip_ansi(ln) for ln in _render_view(view))
    for word in ('plan', 'specs', 'subagents', 'workflow'):
        assert superscript(word) not in blob, word
