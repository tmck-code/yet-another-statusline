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


@pytest.mark.parametrize('model, word', [
    ('claude-fable-5', 'fable'),
    ('claude-mythos-5', 'mythos'),
])
def test_two_line_cluster_shows_new_model_family(model: str, word: str) -> None:
    sub = _make_sub(total_input=12345, output=678, model=model)
    si  = (sub.total_input + sub.output) * 2
    line1, _ = _two(sub, 136, session_inout=si)
    assert word in strip_ansi(line1)


def test_two_line_cluster_shows_bracketed_context_suffix() -> None:
    # Agent frontmatter model like 'sonnet[1m]' must keep the [1m] suffix
    # visible instead of being normalised down to just 'sonnet'.
    sub = _make_sub(total_input=12345, output=678, model='claude-sonnet-4-6[1m]')
    si  = (sub.total_input + sub.output) * 2
    line1, _ = _two(sub, 136, session_inout=si)
    plain = strip_ansi(line1)
    assert 'sonnet[1m]' in plain


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


# D2. Line-1 stats anchoring (stats_col) -------------------------------------

def _cluster_dot_offset(line1: str) -> int:
    """Content-offset of the stats cluster's leading `·`.

    The line may carry a leading ` · ` *description* separator; the cluster's
    own `·` is the last `·`-led group, so we find the rightmost one that begins
    a `· ` token at/after a high column.
    """
    plain = strip_ansi(line1)
    return plain.rfind('· ', plain.find('%') - 4 if '%' in plain else 0)


def test_stats_col_anchors_cluster_dot_at_column() -> None:
    # At a wide content width the cluster's leading `·` sits at exactly
    # stats_col, with the description truncated before it.
    sub = _make_sub(description='x' * 200, total_input=12345, output=678)
    si  = (sub.total_input + sub.output) * 2
    line1, _ = _two(sub, 156, session_inout=si, stats_col=100)
    plain = strip_ansi(line1)
    assert plain[100] == '·'              # cluster dot anchored at stats_col
    assert _visible_width(line1) == 156   # still fills the content edge
    assert '…' in plain                   # description truncated before stats


def test_stats_col_none_keeps_right_alignment() -> None:
    # Default (no stats_col) is unchanged: the cluster right-aligns to the edge
    # so its leading `·` is well past stats_col=100 at this width.
    sub = _make_sub(description='short', total_input=12345, output=678)
    si  = (sub.total_input + sub.output) * 2
    line1, _ = _two(sub, 156, session_inout=si)
    plain = strip_ansi(line1)
    assert plain[100] != '·'              # not anchored at 100
    assert _cluster_dot_offset(line1) > 100  # cluster pushed to the right edge
    assert _visible_width(line1) == 156


def test_stats_col_narrow_falls_back_to_right_align() -> None:
    # When even the model-only cluster cannot fit to the right of stats_col
    # (model-only is `· <model>` = 8 cols, so content width 105 leaves only 5
    # cols of slack), the row falls back to right-alignment exactly as if
    # stats_col were None. This is the defensive guard for narrow rows.
    sub = _make_sub(description='short', total_input=12345, output=678)
    si  = (sub.total_input + sub.output) * 2
    line1_anchor, _ = _two(sub, 105, session_inout=si, stats_col=100)
    line1_default, _ = _two(sub, 105, session_inout=si)
    assert strip_ansi(line1_anchor) == strip_ansi(line1_default)
    assert strip_ansi(line1_anchor)[100] != '·'


def test_stats_col_richest_cluster_that_fits_at_anchor() -> None:
    # Slack to the right of the anchor governs which cluster is chosen. With
    # generous slack the full share%+tok+model cluster anchors at stats_col.
    sub = _make_sub(total_input=12345, output=678, model='claude-sonnet-4-6')
    si  = (sub.total_input + sub.output) * 2
    line1, _ = _two(sub, 156, session_inout=si, stats_col=100)
    plain = strip_ansi(line1)
    tok   = fmt_tok(sub.total_input)
    assert plain[100] == '·'
    assert '%' in plain and tok in plain and 'sonnet' in plain


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


@pytest.mark.parametrize('model, word', [
    ('claude-fable-5', 'fable'),
    ('claude-mythos-5', 'mythos'),
])
def test_one_line_shows_new_model_family(model: str, word: str) -> None:
    sub = _make_sub(model=model, last_activity=('tool_use', 'Bash', {}))
    out = strip_ansi(_one(sub))
    assert word in out


def test_one_line_shows_bracketed_context_suffix() -> None:
    sub = _make_sub(model='claude-sonnet-4-6[1m]', last_activity=('tool_use', 'Bash', {}))
    out = strip_ansi(_one(sub))
    assert 'sonnet[1m]' in out


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
    # The right metric cluster (model + hourglass + tok + dur) is flush to the
    # closing border so the model/tokens/elapsed columns line up down stacked
    # rows; the slack between the left run and the cluster is the interior gap
    # (no trailing space after the duration). Fills exactly to content_width.
    content_width = 90
    sub = _make_sub(agent_type='grep-bot',
                    last_activity=('tool_use', 'Grep', {}))
    out  = _one(sub, content_width)
    text = strip_ansi(out)
    assert _visible_width(out) == content_width
    # No trailing space: the duration is the last visible glyph on the row.
    assert text == text.rstrip()


def test_one_line_model_in_right_cluster_not_after_type() -> None:
    # The model moved out of the left run into the right-anchored cluster: it
    # now sits between the agent type and the token figure, not directly abutting
    # the type. The verb (left run) precedes the model (right cluster).
    sub = _make_sub(agent_type='general-purpose',
                    model='claude-sonnet-4-6',
                    last_activity=('tool_use', 'Bash', {}))
    text = strip_ansi(_one(sub))
    # type, then verb (left), then model (right cluster), then token count.
    assert text.index('general-purpose') < text.index('Bash') < text.index('sonnet')
    assert text.index('sonnet') < text.index(fmt_tok(sub.total_input))


def test_one_line_model_forms_right_aligned_column() -> None:
    # Two stacked rows with differing left widths and token widths must align
    # their model, token, and duration fields into vertical columns because the
    # whole cluster is fixed-width (model rjust 6, tok rjust 6, dur rjust 5) and
    # right-anchored to the border.
    content_width = 90
    a = _make_sub(agent_type='synth', model='claude-3-5-haiku',
                  total_input=6800, first_timestamp=time.time() - 90,
                  last_activity=('tool_use', 'Edit', {}))
    b = _make_sub(agent_type='fetch-notebook-worker', model='claude-sonnet-4-6',
                  total_input=11500, first_timestamp=time.time() - 50,
                  last_activity=('tool_use', 'Read', {}))
    row_a = strip_ansi(_one(a, content_width))
    row_b = strip_ansi(_one(b, content_width))
    # The model column start (left edge of the rjust-6 field) lines up.
    assert row_a.index('haiku') - 1 == row_b.index('sonnet')
    # Both rows fill to exactly content_width, so the duration column also lines
    # up by construction.
    assert _visible_width(row_a) == content_width == _visible_width(row_b)


def test_one_line_six_char_token_keeps_model_aligned() -> None:
    # A workflow agent routinely exceeds 100K tokens, so fmt_tok yields a 6-char
    # figure ('115.0K'). The one-line token field is rjust(6), so a 6-char value
    # fills the column without widening the right cluster — the model column stays
    # right-edge aligned with a row carrying a smaller (4-char) token value.
    content_width = 90
    big   = _make_sub(agent_type='synth', model='claude-sonnet-4-6',
                      total_input=115000, first_timestamp=time.time() - 90,
                      last_activity=('tool_use', 'Edit', {}))
    small = _make_sub(agent_type='synth', model='claude-sonnet-4-6',
                      total_input=6800, first_timestamp=time.time() - 90,
                      last_activity=('tool_use', 'Edit', {}))
    # The 6-char value really is wider than the 4-char one (the bug's premise).
    assert len(fmt_tok(big.total_input)) == 6
    assert len(fmt_tok(small.total_input)) == 4
    row_big   = strip_ansi(_one(big, content_width))
    row_small = strip_ansi(_one(small, content_width))
    # Same model glyph column despite the differing token widths.
    assert row_big.index('sonnet') == row_small.index('sonnet')
    # Both rows fill flush to the border, so the right cluster did not widen.
    assert _visible_width(row_big) == content_width == _visible_width(row_small)


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

def _render_wide(monkeypatch: pytest.MonkeyPatch, subs: list[RunningSubagent], width: int = 120) -> str:
    monkeypatch.setattr(
        subagents_mod.RunningSubagents, 'from_session',
        classmethod(lambda cls, sid, pdir: subagents_mod.RunningSubagents(subagents=subs)),
    )
    session = session_mod.SessionInfo.from_dict(json.loads(SESSION.read_text()))
    view    = SessionView(session, Config())
    tick    = TickRecord(token_log=TokenLog(), day_cost=0.0, tok_rate=0)
    spec    = layout.build_wide(view, tick, width, _r)
    return '\n'.join(layout.render_layout(spec, _r))


def test_build_wide_no_subagents(monkeypatch: pytest.MonkeyPatch) -> None:
    out = strip_ansi(_render_wide(monkeypatch, []))
    assert 'alpha-agent' not in out
    assert 'beta-agent' not in out


def test_build_wide_two_subagents_render(monkeypatch: pytest.MonkeyPatch) -> None:
    # width 119 stays below TWO_COL_SUBAGENT_WIDTH (120), so this still
    # exercises the single-column twoline=True stacked rendering; see
    # test_layout_subagent_rows.py for the width>=120 paired-column layout.
    sub_a = _make_sub(agent_type='alpha-agent', description='do alpha thing')
    sub_b = _make_sub(agent_type='beta-agent', description='do beta thing')
    out   = strip_ansi(_render_wide(monkeypatch, [sub_a, sub_b], width=119))
    assert 'alpha-agent' in out
    assert 'beta-agent' in out
    # wide is two-line: subagent rows carry no run-state marker
    assert '▶' not in out
    # the subagent identity lines drop the t/m and ↑output fields
    sub_lines = [ln for ln in strip_ansi(_render_wide(monkeypatch, [sub_a, sub_b], width=119)).split('\n')
                 if 'alpha-agent' in ln or 'beta-agent' in ln]
    assert sub_lines
    for ln in sub_lines:
        assert 't/m' not in ln
        assert '↑' not in ln


# J. Tree view ----------------------------------------------------------------

def _make_tree_sub(agent_id: str, parent_id: str = '', ts_off: float = 0.0, **kw) -> RunningSubagent:
    sub = _make_sub(first_timestamp=time.time() - 100 + ts_off, **kw)
    sub.agent_id  = agent_id
    sub.parent_id = parent_id
    return sub


def test_meta_parent_extraction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # parentAgentId/spawnDepth in the meta.json land on the parsed subagent;
    # a meta without them falls back to top-level ('' / 0).
    monkeypatch.setattr(subagents_mod, 'CLAUDE_DIR', tmp_path)
    sub_dir = tmp_path / 'projects' / '-proj' / 'sess-1' / 'subagents'
    sub_dir.mkdir(parents=True)
    line = json.dumps({'type': 'assistant', 'timestamp': '2026-01-01T00:00:00Z',
                       'message': {'id': 'm1', 'usage': {'input_tokens': 1}}}) + '\n'
    (sub_dir / 'agent-parent.meta.json').write_text(json.dumps({'agentType': 'root', 'description': 'd'}))
    (sub_dir / 'agent-parent.jsonl').write_text(line)
    (sub_dir / 'agent-child.meta.json').write_text(json.dumps(
        {'agentType': 'kid', 'description': 'd', 'parentAgentId': 'parent', 'spawnDepth': 2}))
    (sub_dir / 'agent-child.jsonl').write_text(line)
    got = {s.agent_type: s for s in
           subagents_mod.RunningSubagents.from_session('sess-1', '/proj').subagents}
    assert got['root'].parent_id == '' and got['root'].spawn_depth == 0
    assert got['root'].agent_id == 'agent-parent'
    assert got['kid'].parent_id == 'parent' and got['kid'].spawn_depth == 2


def test_tree_order_groups_children_under_parent() -> None:
    root  = _make_tree_sub('agent-a', ts_off=0, agent_type='main')
    other = _make_tree_sub('agent-b', ts_off=1, agent_type='other')
    kid1  = _make_tree_sub('agent-c', parent_id='a', ts_off=2, agent_type='k1')
    kid2  = _make_tree_sub('agent-d', parent_id='agent-a', ts_off=3, agent_type='k2')
    # Interleaved input: children regroup directly under their parent, siblings
    # keep order, `a`-prefixed and bare parent ids both match.
    out = subagents_mod.tree_order([root, kid1, other, kid2])
    assert [(s.agent_type, d, last) for s, d, last in out] == [
        ('main', 0, False), ('k1', 1, False), ('k2', 1, True), ('other', 0, False),
    ]


def test_tree_order_unknown_parent_is_top_level() -> None:
    orphan = _make_tree_sub('agent-x', parent_id='nope', agent_type='orphan')
    out = subagents_mod.tree_order([orphan])
    assert out == [(orphan, 0, False)]


def test_subagent_cells_prefixes_branch_glyphs() -> None:
    root = _make_tree_sub('agent-a', agent_type='main')
    k1   = _make_tree_sub('agent-b', parent_id='a', ts_off=1)
    k2   = _make_tree_sub('agent-c', parent_id='a', ts_off=2)
    gk   = _make_tree_sub('agent-d', parent_id='c', ts_off=3)
    cells = layout.subagent_cells([root, k1, k2, gk], True)
    assert [p for _, p in cells] == ['', '├ ', '└ ', '  └ ']


def test_subagent_cells_flat_mode_unchanged() -> None:
    subs = [_make_tree_sub('agent-b', parent_id='a'), _make_tree_sub('agent-a', ts_off=1)]
    # Default (flat) mode: original order, no prefixes, no reordering.
    assert layout.subagent_cells(subs, False) == [(subs[0], ''), (subs[1], '')]


def test_tree_prefix_two_line_widths_and_indent() -> None:
    sub = _make_sub()
    line1, line2 = _two(sub, 136, tree_prefix='├ ')
    p1, p2 = strip_ansi(line1), strip_ansi(line2)
    assert p1.startswith('├ ')
    assert p2.startswith('  ')            # continuation indents under the branch
    assert _visible_width(line1) == 136   # prefix eats content width, not the box
    assert _visible_width(line2) == 136


def test_tree_prefix_one_line_width() -> None:
    sub  = _make_sub()
    line = _one(sub, 96, tree_prefix='└ ')
    assert strip_ansi(line).startswith('└ ')
    assert _visible_width(line) == 96


def test_tree_prefix_default_noop() -> None:
    sub = _make_sub()
    assert _r.subagent_row(sub, 136, twoline=True) == \
           _r.subagent_row(sub, 136, twoline=True, tree_prefix='')


def test_tree_single_puts_activity_on_line_one() -> None:
    # Tree single-line: the current-activity continuation moves onto line 1 as
    # a right-hand column after the stats/model cluster — one line, no └ marker.
    sub  = _make_sub(last_activity=('tool_use', 'Bash', {'command': 'openspec show'}))
    out  = _r.subagent_row(sub, 136, twoline=True, tree_single=True)
    assert '\n' not in out                       # exactly one line
    plain = strip_ansi(out)
    assert 'Bash[openspec show]' in plain         # activity on the same line
    assert 'sonnet' in plain                      # after the model cluster
    assert plain.index('sonnet') < plain.index('Bash[')  # activity is to the right
    assert '└' not in plain and '├' not in plain  # no continuation/branch glyph here


def test_tree_single_width_preserved_and_prefixed() -> None:
    sub  = _make_sub()
    root = _r.subagent_row(sub, 136, twoline=True, tree_single=True)
    kid  = _r.subagent_row(sub, 136, twoline=True, tree_single=True, tree_prefix='├ ')
    assert '\n' not in root and '\n' not in kid
    assert _visible_width(root) == 136
    assert _visible_width(kid) == 136             # prefix eats content, not the box
    assert strip_ansi(kid).startswith('├ ')


def test_tree_single_activity_column_aligned_across_rows() -> None:
    # The activity column starts at a consistent offset regardless of the model
    # width, because the cluster right-aligns to the reserved stats width.
    a = _make_sub(model='claude-sonnet-4-6',       last_activity=('tool_use', 'Bash', {'command': 'x'}))
    b = _make_sub(model='claude-haiku-4-5-2025',   last_activity=('tool_use', 'Read', {'file_path': 'y.py'}))
    la = strip_ansi(_r.subagent_row(a, 136, twoline=True, tree_single=True))
    lb = strip_ansi(_r.subagent_row(b, 136, twoline=True, tree_single=True))
    assert la.index('Bash[') == lb.index('Read[')


def test_tree_single_activity_truncates_when_tight() -> None:
    long = 'y' * 200
    sub  = _make_sub(last_activity=('text', long, {}))
    out  = strip_ansi(_r.subagent_row(sub, 136, twoline=True, tree_single=True))
    assert out.rstrip().endswith('…')
    assert _visible_width(out) == 136


def test_tree_single_activity_column_aligned_across_prefix_depths() -> None:
    # Regression: activity_reserve must be sized off the PRE-prefix width, not
    # the already-shrunk content_width, so the glyph's absolute column (prefix
    # included) doesn't drift as deeper branches eat more front width.
    sub = _make_sub(last_activity=('tool_use', 'Bash', {'command': 'x'}))
    cols = []
    for prefix in ('', '├ ', '  └ '):
        line = strip_ansi(_r.subagent_row(sub, 136, twoline=True, tree_single=True, tree_prefix=prefix))
        cols.append(line.index('Bash['))
        assert _visible_width(line) == 136
    assert len(set(cols)) == 1, f'activity column drifted across prefixes: {cols}'


def test_tree_columns_common_anchor_across_names_and_prefixes() -> None:
    # layout.tree_columns: desc_col is the widest (prefix + duration + type)
    # across the cohort, so the shortest names/prefixes get padded up to it;
    # stats_col/activity_col target ~30%/~50% of the row width, never left of
    # where the preceding field ends.
    root = _make_tree_sub('agent-a', agent_type='spec-author')     # prefix '', long type
    kid  = _make_tree_sub('agent-b', parent_id='a', agent_type='api')  # prefix '├ ', short type
    cells = [(root, ''), (kid, '├ ')]
    desc_col, stats_col, activity_col = layout.tree_columns(cells, 140)
    # desc_col matches the widest row: '' + 5 + 1 + len('spec-author') + 1
    assert desc_col == 0 + 5 + 1 + len('spec-author') + 1
    assert stats_col >= desc_col + 8
    assert activity_col >= stats_col + 16
    assert stats_col == round(140 * 0.30) or stats_col == desc_col + 8
    assert activity_col == round(140 * 0.50) or activity_col == stats_col + 16


def test_tree_single_description_aligned_across_depths_and_names() -> None:
    # Full pipeline: root (long type name, no prefix) and a deeper child
    # (short type name, indented prefix) still start ' · description' and the
    # activity column at the identical absolute offset.
    root = _make_tree_sub('agent-a', agent_type='spec-author', description='Fetch the artifact',
                          last_activity=('tool_use', 'Bash', {'command': 'openspec show'}))
    kid  = _make_tree_sub('agent-b', parent_id='a', agent_type='api', description='Make tmp dir',
                          last_activity=('tool_use', 'Bash', {'command': 'mkdir -p /tmp'}))
    cells = [(root, ''), (kid, '├ ')]
    desc_col, stats_col, activity_col = layout.tree_columns(cells, 140)
    lines = [
        strip_ansi(_r.subagent_row(sub, 140, twoline=True, tree_single=True, tree_prefix=prefix,
                                   stats_col=stats_col, tree_desc_col=desc_col,
                                   tree_activity_col=activity_col))
        for sub, prefix in cells
    ]
    desc_idx = [ln.index(' · ') for ln in lines]
    act_idx  = [ln.index('Bash[') for ln in lines]
    assert len(set(desc_idx)) == 1, f'description column drifted: {desc_idx}'
    assert len(set(act_idx)) == 1, f'activity column drifted: {act_idx}'
    for ln in lines:
        assert _visible_width(ln) == 140


def test_tree_single_model_left_aligned_no_padding() -> None:
    # Per the design mock, the model is plain (no right-justify padding to a
    # fixed width) in tree_single mode — alignment across rows comes from the
    # cluster area padding to stats_w as a whole, not from the model field.
    sub  = _make_sub(model='claude-haiku-4-5-20251001')
    line = strip_ansi(_r.subagent_row(sub, 136, twoline=True, tree_single=True))
    # 'haiku' immediately followed by two spaces (the activity gap) or the
    # activity text — never padded out to the old 6-char rjust field width.
    assert '· haiku' in line
    assert 'haiku ' + ' ' * 5 not in line  # no leftover rjust-style padding run


def test_tree_single_off_keeps_two_line() -> None:
    # Without tree_single the two-line form is unchanged (flat-mode invariant).
    sub = _make_sub()
    assert _r.subagent_row(sub, 136, twoline=True) == \
           _r.subagent_row(sub, 136, twoline=True, tree_single=False)


def test_build_wide_tree_mode_renders_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    root = _make_tree_sub('agent-a', agent_type='root-agent', description='spawn things',
                          last_activity=('tool_use', 'Task', {'description': 'spawn'}))
    kid1 = _make_tree_sub('agent-b', parent_id='a', ts_off=1, agent_type='kid-one',
                          last_activity=('tool_use', 'Bash', {'command': 'ls'}))
    kid2 = _make_tree_sub('agent-c', parent_id='a', ts_off=2, agent_type='kid-two',
                          last_activity=('tool_use', 'Read', {'file_path': 'z.py'}))
    monkeypatch.setattr(
        subagents_mod.RunningSubagents, 'from_session',
        classmethod(lambda cls, sid, pdir: subagents_mod.RunningSubagents(subagents=[root, kid1, kid2])),
    )
    session = session_mod.SessionInfo.from_dict(json.loads(SESSION.read_text()))
    view    = SessionView(session, Config(subagent_tree=True))
    tick    = TickRecord(token_log=TokenLog(), day_cost=0.0, tok_rate=0)
    spec    = layout.build_wide(view, tick, 140, _r)
    out     = [strip_ansi(ln) for ln in layout.render_layout(spec, _r)]
    kid_lines = [ln for ln in out if 'kid-one' in ln or 'kid-two' in ln]
    assert len(kid_lines) == 2                     # one line per subagent
    assert '├ ' in kid_lines[0] and 'kid-one' in kid_lines[0] and 'Bash[' in kid_lines[0]
    assert '└ ' in kid_lines[1] and 'kid-two' in kid_lines[1] and 'Read[' in kid_lines[1]
    # tree mode stacks single-column even above TWO_COL_SUBAGENT_WIDTH; the root
    # is a single line carrying its own activity, no separate continuation row.
    root_lines = [ln for ln in out if 'root-agent' in ln]
    assert len(root_lines) == 1 and '├ ' not in root_lines[0] and 'Task[' in root_lines[0]
    # Description and activity columns line up across depths: root (no
    # prefix, longer type name) vs the indented children (shorter names).
    all_rows  = root_lines + kid_lines
    desc_cols = [ln.index(' · ') for ln in all_rows]
    assert len(set(desc_cols)) == 1, f'description column drifted: {desc_cols}'
