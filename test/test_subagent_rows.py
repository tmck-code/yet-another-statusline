import json
import time
from pathlib import Path

import pytest

import yas.layout as layout
import yas.renderer as renderer_mod
import yas.session as session_mod
import yas.info.subagents as subagents_mod
from yas.config import Config

from yas.constants import (
    GLYPH_REPLYING,
)
from yas.info import SessionView
from yas.info.subagents import RunningSubagent
from yas.render.text import _visible_width, fmt_tok
from yas.tokens import TickRecord, TokenLog
from helper import strip_ansi


_r = renderer_mod.Renderer()

SESSION = (Path(__file__).parent.parent / 'ops'
           / 'session-info-example.json')


def _make_sub(
    agent_type: str = 'general-purpose',
    description: str = 'Draft claude-light Theme literal',
    billed_in: int = 12345,
    output: int = 678,
    first_timestamp: float | None = None,
    model: str = 'claude-sonnet-4-6',
    cache_read_in: int = 0,
    total_input: int = 12345,
    last_activity: tuple = ('tool_use', 'Bash', {'command': 'pytest -q'}),
    mtime: float | None = None,
    end_ts: float = 0.0,
) -> RunningSubagent:
    now = time.time()
    if first_timestamp is None:
        first_timestamp = now - 47
    if mtime is None:
        mtime = now - 5
    return RunningSubagent(
        agent_type      = agent_type,
        description     = description,
        billed_in       = billed_in,
        output          = output,
        first_timestamp = first_timestamp,
        mtime           = mtime,
        model           = model,
        cache_read_in   = cache_read_in,
        total_input     = total_input,
        last_activity   = last_activity,
        end_ts          = end_ts,
    )


# Helpers ---------------------------------------------------------------------

def _two(sub: RunningSubagent, content_width: int = 136, **kw):
    """Render the two-line form and return (line1, line2)."""
    out = _r.subagent_row(sub, content_width, twoline=True, **kw)
    line1, line2 = out.split('\n')
    return line1, line2


def _one(sub: RunningSubagent, content_width: int = 96, **kw) -> str:
    """Render the one-line collapse form."""
    return _r.subagent_row(sub, content_width, twoline=False, **kw)


# A. Two-line form: duration-first identity + cluster ------------------------

def test_two_line_duration_at_front() -> None:
    sub = _make_sub(first_timestamp=time.time() - 47)
    line1, _ = _two(sub)
    plain = strip_ansi(line1)
    assert plain.lstrip().startswith('47s')
    # duration precedes the agent type
    assert plain.index('47s') < plain.index('general-purpose')


def test_two_line_has_type_then_description() -> None:
    sub = _make_sub(description='hello world')
    line1, _ = _two(sub)
    plain = strip_ansi(line1)
    assert plain.index('general-purpose') < plain.index('hello world')


def test_two_line_no_run_state_marker() -> None:
    line1, line2 = _two(_make_sub())
    assert '▶' not in strip_ansi(line1)
    assert '✓' not in strip_ansi(line1)
    assert '▶' not in strip_ansi(line2)
    assert '✓' not in strip_ansi(line2)


def test_two_line_cluster_share_tok_model_order() -> None:
    sub = _make_sub(total_input=12345, output=678, model='claude-sonnet-4-6')
    si  = (sub.total_input + sub.output) * 2  # ~50% share
    line1, _ = _two(sub, 136, session_inout=si)
    plain = strip_ansi(line1)
    tok = fmt_tok(sub.total_input)
    assert '%' in plain
    assert tok in plain
    assert 'sonnet' in plain
    # cluster order: share% then tok then model
    assert plain.index('%') < plain.index(tok) < plain.index('sonnet')


def test_two_line_no_tpm_field() -> None:
    sub = _make_sub(first_timestamp=time.time() - 60, total_input=3000, output=600)
    si  = (sub.total_input + sub.output) * 2
    line1, line2 = _two(sub, 160, session_inout=si)
    assert 't/m' not in strip_ansi(line1)
    assert 't/m' not in strip_ansi(line2)


def test_two_line_no_output_field() -> None:
    sub = _make_sub()
    si  = (sub.total_input + sub.output) * 2
    line1, line2 = _two(sub, 160, session_inout=si)
    assert '↑' not in strip_ansi(line1)
    assert '↑' not in strip_ansi(line2)


def test_two_line_no_cost() -> None:
    line1, line2 = _two(_make_sub(), 160, session_inout=999_999)
    assert '$' not in strip_ansi(line1)
    assert '$' not in strip_ansi(line2)


# B. Two-line line 2: activity-only ------------------------------------------

def test_two_line_continuation_starts_with_elbow() -> None:
    _, line2 = _two(_make_sub())
    assert strip_ansi(line2).lstrip().startswith('└')


def test_two_line_continuation_shows_activity() -> None:
    sub = _make_sub(last_activity=('tool_use', 'Bash', {'command': 'pytest -q'}))
    _, line2 = _two(sub)
    assert 'Bash[pytest -q]' in strip_ansi(line2)


def test_two_line_continuation_tool_arg_strips_newlines() -> None:
    sub = _make_sub(last_activity=('tool_use', 'Bash', {'command': 'echo hi\nrm -rf /\necho bye'}))
    _, line2 = _two(sub)
    plain = strip_ansi(line2)
    assert 'Bash[echo hi]' in plain
    assert '\n' not in plain
    assert 'rm -rf' not in plain


def test_two_line_continuation_has_no_metrics() -> None:
    sub = _make_sub(model='claude-sonnet-4-6')
    si  = (sub.total_input + sub.output) * 2
    _, line2 = _two(sub, 136, session_inout=si)
    plain = strip_ansi(line2)
    assert '%' not in plain
    assert 'sonnet' not in plain
    assert fmt_tok(sub.total_input) not in plain


# C. Equal widths via _visible_width -----------------------------------------

@pytest.mark.parametrize('content_width', [60, 96, 136])
def test_two_line_equal_visible_widths(content_width: int) -> None:
    sub = _make_sub()
    si  = (sub.total_input + sub.output) * 2
    line1, line2 = _two(sub, content_width, session_inout=si)
    assert _visible_width(line1) == content_width
    assert _visible_width(line2) == content_width


def test_two_line_long_description_elides() -> None:
    sub = _make_sub(description='x' * 200)
    line1, _ = _two(sub, 136, session_inout=999_999)
    assert '…' in strip_ansi(line1)
    assert _visible_width(line1) == 136


# D. Line-1 cluster shedding: share% first, then tok -------------------------

def _cluster_state(line1: str, tok: str) -> tuple[bool, bool]:
    """(share% present, tok present) on a line-1 cluster."""
    p = strip_ansi(line1)
    return ('%' in p, tok in p)


def test_shed_description_truncates_before_cluster_sheds() -> None:
    # Wide enough for the full cluster but not the full description: the
    # description elides while share% and tok are both retained.
    sub = _make_sub(description='x' * 120, total_input=12345, output=678)
    si  = (sub.total_input + sub.output) * 2
    line1, _ = _two(sub, 70, session_inout=si)
    plain = strip_ansi(line1)
    assert '…' in plain                     # description truncated
    assert '%' in plain                     # share% kept
    assert fmt_tok(sub.total_input) in plain  # tok kept


def test_shed_order_share_then_tok() -> None:
    # Across narrowing widths the kept cluster is one of model-only,
    # tok+model, or share+tok+model — never tok dropped while share kept.
    sub = _make_sub(agent_type='general-purpose', description='x' * 80,
                    total_input=12345, output=678)
    si  = (sub.total_input + sub.output) * 2
    tok = fmt_tok(sub.total_input)
    valid = {(True, True), (False, True), (False, False)}
    for w in range(30, 80):
        line1, _ = _two(sub, w, session_inout=si)
        state = _cluster_state(line1, tok)
        assert state in valid, f'width={w}: out-of-order shed {state}'


def test_shed_all_levels_reachable() -> None:
    sub = _make_sub(agent_type='general-purpose', description='x' * 80,
                    total_input=12345, output=678)
    si  = (sub.total_input + sub.output) * 2
    tok = fmt_tok(sub.total_input)
    seen = {_cluster_state(_two(sub, w, session_inout=si)[0], tok)
            for w in range(30, 80)}
    assert (True, True) in seen    # nothing shed
    assert (False, True) in seen   # share% shed, tok kept
    assert (False, False) in seen  # share% and tok shed


def test_shed_model_and_duration_always_kept() -> None:
    sub = _make_sub(agent_type='general-purpose', description='x' * 80,
                    first_timestamp=time.time() - 47, model='claude-sonnet-4-6',
                    total_input=12345, output=678)
    si  = (sub.total_input + sub.output) * 2
    for w in range(30, 80):
        line1, _ = _two(sub, w, session_inout=si)
        plain = strip_ansi(line1)
        assert 'sonnet' in plain, f'width={w} dropped model'
        assert '47s' in plain, f'width={w} dropped duration'


# E. Done vs running treatment -----------------------------------------------

def _make_done_sub(**kw) -> RunningSubagent:
    now = time.time()
    defaults = dict(first_timestamp=now - 120.0, end_ts=now - 30.0)
    defaults.update(kw)
    return _make_sub(**defaults)


def test_done_two_line_uses_dim_styling() -> None:
    line1, _ = _two(_make_done_sub())
    assert _r.CTX_DIM in line1


def test_running_two_line_uses_live_styling() -> None:
    line1, _ = _two(_make_sub())
    # running line1 styles the type with SKILLS and never uses the dim colour
    assert _r.SKILLS in line1
    assert _r.CTX_DIM not in line1


def test_done_two_line_frozen_duration_value() -> None:
    # end_ts - first_timestamp = 90s -> 1m30s, shown at the front of line 1
    line1, _ = _two(_make_done_sub())
    assert '1m30s' in strip_ansi(line1)


def test_done_two_line_duration_does_not_tick() -> None:
    sub = _make_done_sub()
    line1_a, _ = _two(sub)
    time.sleep(0.05)
    line1_b, _ = _two(sub)
    assert strip_ansi(line1_a) == strip_ansi(line1_b)


def test_done_two_line_no_marker() -> None:
    line1, _ = _two(_make_done_sub())
    plain = strip_ansi(line1)
    assert '▶' not in plain
    assert '✓' not in plain


# F. One-line collapse form ---------------------------------------------------

def test_one_line_single_line() -> None:
    assert '\n' not in _one(_make_sub())


def test_one_line_drops_output() -> None:
    out = _one(_make_sub())
    assert '↑' not in strip_ansi(out)


def test_one_line_keeps_token_and_duration() -> None:
    sub = _make_sub(first_timestamp=time.time() - 47)
    out = strip_ansi(_one(sub))
    assert fmt_tok(sub.total_input) in out
    assert '47s' in out


def test_one_line_keeps_type_model_verb() -> None:
    sub = _make_sub(model='claude-sonnet-4-6',
                    last_activity=('tool_use', 'Bash', {}))
    out = strip_ansi(_one(sub))
    assert 'general-purpose' in out
    assert 'sonnet' in out
    assert 'Bash' in out


def test_one_line_running_keeps_marker() -> None:
    out = strip_ansi(_one(_make_sub()))
    assert '▶' in out
    assert '✓' not in out


def test_one_line_done_uses_checkmark() -> None:
    out = strip_ansi(_one(_make_done_sub()))
    assert '✓' in out
    assert '▶' not in out


def test_one_line_done_frozen_duration() -> None:
    sub = _make_done_sub()
    out = strip_ansi(_one(sub))
    assert '1m30s' in out


def test_one_line_done_no_activity_verb() -> None:
    # Done agents should not show their last activity (no "Bash", "Edit", etc.)
    sub = _make_done_sub(last_activity=('tool_use', 'Bash', {}))
    out = strip_ansi(_one(sub))
    # Check the marker, type, and model are shown
    assert '✓' in out
    assert 'general-purpose' in out
    assert 'sonnet' in out
    # But the activity verb (Bash) should NOT be shown
    assert 'Bash' not in out


@pytest.mark.parametrize('content_width', [60, 96])
def test_one_line_fits_content_width(content_width: int) -> None:
    out = _one(_make_sub(), content_width)
    assert _visible_width(out) <= content_width


@pytest.mark.parametrize('content_width', [33, 37, 41])
def test_one_line_long_name_padded_flush_to_width(content_width: int) -> None:
    # A long-named agent (general-purpose + Edit verb) would push the left
    # segment past the right border at narrow widths. The left run truncates so
    # the row is padded/truncated to exactly content_width (border stays flush).
    sub = _make_sub(agent_type='general-purpose',
                    last_activity=('tool_use', 'Edit', {}))
    out = _one(sub, content_width)
    assert _visible_width(out) == content_width


def test_one_line_metrics_right_anchored_at_wide_width() -> None:
    # The right metric cluster (hourglass + tok + dur) is flush to the closing
    # border so the tokens/elapsed columns line up down stacked rows; the slack
    # between the left run and the cluster is the interior gap (no trailing
    # space after the duration). The row fills exactly to content_width.
    content_width = 90
    sub = _make_sub(agent_type='grep-bot',
                    last_activity=('tool_use', 'Grep', {}))
    out  = _one(sub, content_width)
    text = strip_ansi(out)
    assert _visible_width(out) == content_width
    # No trailing space: the duration is the last visible glyph on the row.
    assert text == text.rstrip()


# G. Duration formatting ------------------------------------------------------

@pytest.mark.parametrize('elapsed, token', [
    (4, '4s'), (47, '47s'), (83, '1m23s'), (3700, '1h01m'),
])
def test_one_line_duration_formats(elapsed: int, token: str) -> None:
    out = strip_ansi(_one(_make_sub(first_timestamp=time.time() - elapsed)))
    assert token in out


def test_one_line_no_timestamp_fallback() -> None:
    out = strip_ansi(_one(_make_sub(first_timestamp=0)))
    assert '0s' in out


# H. subagent_activity formatter (unchanged) ---------------------------------

def test_subagent_activity_bash_extracts_command() -> None:
    act = ('tool_use', 'Bash', {'command': 'pytest -q tests/'})
    out = strip_ansi(_r.subagent_activity(act))
    assert 'Bash[pytest -q tests/]' in out


def test_subagent_activity_read_extracts_basename() -> None:
    act = ('tool_use', 'Read', {'file_path': '/home/x/very/deep/path/file.py'})
    out = strip_ansi(_r.subagent_activity(act))
    assert 'Read[file.py]' in out


def test_subagent_activity_unknown_tool_first_value() -> None:
    act = ('tool_use', 'NovelTool', {'foo': 'bar', 'baz': 'qux'})
    out = strip_ansi(_r.subagent_activity(act))
    assert 'NovelTool[bar]' in out


def test_subagent_activity_long_arg_truncated() -> None:
    act = ('tool_use', 'Bash', {'command': 'x' * 100})
    out = strip_ansi(_r.subagent_activity(act))
    arg = out.split('[', 1)[1].rstrip(']')
    assert _visible_width(arg) == 37  # 36 chars + ellipsis


def test_subagent_activity_thinking() -> None:
    out = strip_ansi(_r.subagent_activity(('thinking', '', {})))
    assert '(thinking)' in out


def test_subagent_activity_replying() -> None:
    out = strip_ansi(_r.subagent_activity(('text', '', {})))
    assert '(replying)' in out


def test_subagent_activity_empty() -> None:
    assert _r.subagent_activity(('', '', {})) == ''


# H2. Activity selection: text snippet vs tool_use precedence ----------------

def _parse_activity(content: list, tmp_path: Path) -> tuple:
    """Write a one-message transcript and return its parsed last_activity tuple.

    Exercises RunningSubagents._parse_transcript end-to-end so the snippet /
    precedence selection is tested, not just the renderer.
    """
    line = json.dumps({
        'type': 'assistant',
        'message': {
            'id': 'm1',
            'usage': {'input_tokens': 1, 'output_tokens': 1},
            'content': content,
        },
    }) + '\n'
    jsonl = tmp_path / 'agent.jsonl'
    jsonl.write_text(line)
    return subagents_mod.RunningSubagents._parse_transcript(jsonl)[5]


def test_text_only_message_renders_replying_snippet(tmp_path: Path) -> None:
    # Text-only latest message (no tool_use) -> first non-empty stripped line.
    act = _parse_activity(
        [{'type': 'text', 'text': '\n   Investigating the failing test\nmore'}],
        tmp_path,
    )
    assert act[0] == 'text'
    assert act[1] == 'Investigating the failing test'
    out = strip_ansi(_r.subagent_activity(act))
    assert out == f'{GLYPH_REPLYING} Investigating the failing test'


def test_interleaved_tool_use_beats_trailing_text(tmp_path: Path) -> None:
    # [text, tool_use, text]: the tool call must win over the trailing narration.
    act = _parse_activity(
        [
            {'type': 'text', 'text': 'Let me run the tests'},
            {'type': 'tool_use', 'name': 'Bash', 'input': {'command': 'pytest -q'}},
            {'type': 'text', 'text': 'running now'},
        ],
        tmp_path,
    )
    assert act[0] == 'tool_use'
    out = strip_ansi(_r.subagent_activity(act))
    assert 'Bash[pytest -q]' in out      # tool verb wins
    assert 'running now' not in out      # trailing text snippet suppressed
    assert GLYPH_REPLYING not in out     # not the replying glyph


def test_text_snippet_truncates_and_empty_falls_back() -> None:
    # A snippet wider than 36 visible columns is capped to 36 + ellipsis.
    out = strip_ansi(_r.subagent_activity(('text', 'y' * 80, {})))
    snippet = out[len(f'{GLYPH_REPLYING} '):]
    assert snippet.endswith('…')
    assert _visible_width(snippet) == 37  # 36 cols + ellipsis
    # Empty/absent text content falls back to the (replying) placeholder.
    empty = strip_ansi(_r.subagent_activity(('text', '', {})))
    assert empty == f'{GLYPH_REPLYING} (replying)'


# H3. Line-2 activity snippet widens with available width --------------------

def test_two_line_activity_widens_beyond_36_when_room() -> None:
    # A text snippet 60 cols wide (>36, <=100) renders in full on a wide row,
    # rather than being capped to the old 36+ellipsis cap.
    sub = _make_sub(last_activity=('text', 'y' * 60, {}))
    _, line2 = _two(sub, 136)
    plain   = strip_ansi(line2)
    snippet = plain.split(f'{GLYPH_REPLYING} ', 1)[1].rstrip()
    assert '…' not in snippet                  # not truncated
    assert _visible_width(snippet) == 60       # full 60 cols, not 37


def test_two_line_activity_caps_at_100_when_huge() -> None:
    # A snippet far wider than 100 caps at 100 cols + ellipsis even on a very
    # wide row, instead of expanding unbounded.
    sub = _make_sub(last_activity=('text', 'y' * 150, {}))
    _, line2 = _two(sub, 160)
    plain   = strip_ansi(line2)
    snippet = plain.split(f'{GLYPH_REPLYING} ', 1)[1].rstrip()
    assert snippet.endswith('…')
    assert _visible_width(snippet) == 101       # 100 cols + ellipsis


# I. build_wide integration --------------------------------------------------

def _render_wide(monkeypatch: pytest.MonkeyPatch, subs: list[RunningSubagent]) -> str:
    monkeypatch.setattr(
        subagents_mod.RunningSubagents, 'from_session',
        classmethod(lambda cls, sid, pdir: subagents_mod.RunningSubagents(subagents=subs)),
    )
    session = session_mod.SessionInfo.from_dict(json.loads(SESSION.read_text()))
    view    = SessionView(session, Config())
    tick    = TickRecord(token_log=TokenLog(), day_cost=0.0, tok_rate=0)
    spec    = layout.build_wide(view, tick, 120, _r)
    return '\n'.join(layout.render_layout(spec, _r))


def test_build_wide_no_subagents(monkeypatch: pytest.MonkeyPatch) -> None:
    out = strip_ansi(_render_wide(monkeypatch, []))
    assert 'alpha-agent' not in out
    assert 'beta-agent' not in out


def test_build_wide_two_subagents_render(monkeypatch: pytest.MonkeyPatch) -> None:
    sub_a = _make_sub(agent_type='alpha-agent', description='do alpha thing')
    sub_b = _make_sub(agent_type='beta-agent', description='do beta thing')
    out   = strip_ansi(_render_wide(monkeypatch, [sub_a, sub_b]))
    assert 'alpha-agent' in out
    assert 'beta-agent' in out
    # wide is two-line: subagent rows carry no run-state marker
    assert '▶' not in out
    # the subagent identity lines drop the t/m and ↑output fields
    sub_lines = [ln for ln in strip_ansi(_render_wide(monkeypatch, [sub_a, sub_b])).split('\n')
                 if 'alpha-agent' in ln or 'beta-agent' in ln]
    assert sub_lines
    for ln in sub_lines:
        assert 't/m' not in ln
        assert '↑' not in ln
