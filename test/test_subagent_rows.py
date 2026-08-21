import json
import re
import time
from pathlib import Path

import pytest

import yas.layout as layout
import yas.renderer as renderer_mod
import yas.session as session_mod
import yas.info.subagents as subagents_mod
from yas.config import Config

import yas.constants as constants
from yas.constants import (
    BOLD,
    BOX_H,
    BOX_H_DASH4,
    CLR_GREY_DIM,
    CLR_WHITE_BRT,
    ELLIPSIS,
    GLYPH_REPLYING,
    ITALIC,
    RESET,
    STRIKE,
    SUBAGENT_DESC_FLOOR,
    SUBAGENT_STATS_ACTIVITY_GAP,
    TREE_PREFIX_BASE_W,
    TREE_PREFIX_STEP_W,
    UNSTRIKE,
)
from yas.info import SessionView
from yas.info.subagents import RunningSubagent
from yas.render.metrics import subagent_dur_str
from yas.render.text import _visible_width, fmt_tok, fmt_tok_fixed
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
    status: str | None = None,
    run_count: int = 0,
    resumed: bool = False,
    run_start_ts: float | None = None,
) -> RunningSubagent:
    now = time.time()
    if first_timestamp is None:
        first_timestamp = now - 47
    if mtime is None:
        mtime = now - 5
    if status is None:
        # Infer the pre-four-state default (end_ts > 0 => finished) so every
        # existing caller that only sets end_ts keeps behaving as before.
        status = 'completed' if end_ts > 0 else 'running'
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
        status          = status,
        run_count       = run_count,
        resumed         = resumed,
        # None -> RunningSubagent's own default (equals first_timestamp), so
        # every existing caller that doesn't pass this keeps exercising the
        # "no distinct resume boundary tracked" path unchanged.
        run_start_ts    = run_start_ts,
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


def _has_lines_field(plain: str) -> bool:
    """True if the lines-read/written field ('<read>/<written>', no icons) is
    present in an ANSI-stripped subagent row. The field is the only '/'-joined
    token the row ever emits, so a bare '/' is an unambiguous marker for it —
    see the field's composition in `Renderer.subagent_row`."""
    return '/' in plain


# A. Two-line form: duration-first identity + cluster ------------------------

def test_two_line_duration_at_front() -> None:
    sub = _make_sub(first_timestamp=time.time() - 47)
    line1, _ = _two(sub)
    plain = strip_ansi(line1)
    assert plain.lstrip().startswith('0:47')
    # duration precedes the agent type
    assert plain.index('0:47') < plain.index('general-purpose')


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


def test_two_line_cluster_tok_model_order() -> None:
    # Cluster order: lines · tok · model — the `(N.N%)` session-share suffix
    # has been removed from the tok field entirely.
    sub = _make_sub(total_input=12345, output=678, model='claude-sonnet-4-6')
    line1, _ = _two(sub, 136)
    plain = strip_ansi(line1)
    tok = fmt_tok_fixed(sub.total_input)
    assert '%' not in plain
    assert tok in plain
    assert 'sonnet' in plain
    # cluster order: tok, then model
    assert plain.index(tok) < plain.index('sonnet')


@pytest.mark.parametrize('model, word', [
    ('claude-fable-5', 'fable'),
    ('claude-mythos-5', 'mythos'),
])
def test_two_line_cluster_shows_new_model_family(model: str, word: str) -> None:
    sub = _make_sub(total_input=12345, output=678, model=model)
    line1, _ = _two(sub, 136)
    assert word in strip_ansi(line1)


def test_two_line_cluster_shows_bracketed_context_suffix() -> None:
    # Agent frontmatter model like 'sonnet[1m]' must keep the [1m] suffix
    # visible instead of being normalised down to just 'sonnet'.
    sub = _make_sub(total_input=12345, output=678, model='claude-sonnet-4-6[1m]')
    line1, _ = _two(sub, 136)
    plain = strip_ansi(line1)
    assert 'sonnet[1m]' in plain


def test_two_line_no_tpm_field() -> None:
    sub = _make_sub(first_timestamp=time.time() - 60, total_input=3000, output=600)
    line1, line2 = _two(sub, 160)
    assert 't/m' not in strip_ansi(line1)
    assert 't/m' not in strip_ansi(line2)


def test_two_line_no_output_field() -> None:
    sub = _make_sub()
    line1, line2 = _two(sub, 160)
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
    _, line2 = _two(sub, 136)
    plain = strip_ansi(line2)
    assert '%' not in plain
    assert 'sonnet' not in plain
    assert fmt_tok(sub.total_input) not in plain


# C. Equal widths via _visible_width -----------------------------------------

@pytest.mark.parametrize('content_width', [60, 96, 136])
def test_two_line_equal_visible_widths(content_width: int) -> None:
    sub = _make_sub()
    line1, line2 = _two(sub, content_width)
    assert _visible_width(line1) == content_width
    assert _visible_width(line2) == content_width


def test_two_line_long_description_elides() -> None:
    sub = _make_sub(description='x' * 200)
    line1, _ = _two(sub, 136, session_inout=999_999)
    assert '…' in strip_ansi(line1)
    assert _visible_width(line1) == 136


# D. Line-1 cluster shedding: lines first, then tok --------------------------

def test_shed_description_truncates_before_cluster_sheds() -> None:
    # Wide enough for the full cluster but not the full description: the
    # description elides while lines and tok are both retained.
    sub = _make_sub(description='x' * 120, total_input=12345, output=678)
    line1, _ = _two(sub, 70, lines=(5, 3))
    plain = strip_ansi(line1)
    assert '…' in plain                     # description truncated
    assert _has_lines_field(plain)          # lines field kept
    assert fmt_tok(sub.total_input) in plain  # tok kept


def test_shed_order_lines_then_tok_narrow_range() -> None:
    # Across narrowing widths the kept cluster is one of model-only,
    # tok+model, or lines+tok+model — never tok dropped while lines kept.
    sub = _make_sub(agent_type='general-purpose', description='x' * 80,
                    total_input=12345, output=678)
    tok = fmt_tok(sub.total_input)
    valid = {(True, True), (False, True), (False, False)}
    for w in range(30, 80):
        line1, _ = _two(sub, w, lines=(5, 3))
        plain = strip_ansi(line1)
        state = (_has_lines_field(plain), tok in plain)
        assert state in valid, f'width={w}: out-of-order shed {state}'


def test_shed_all_levels_reachable() -> None:
    # Decision 10 inverted: tok + loc are now the PROTECTED unit (never shed
    # independently or together) — model is the only field this cluster ever
    # drops. lines/tok therefore stay present at every width in this sweep.
    sub = _make_sub(agent_type='general-purpose', description='x' * 80,
                    total_input=12345, output=678)
    tok = fmt_tok(sub.total_input)
    seen = set()
    for w in range(30, 80):
        plain = strip_ansi(_two(sub, w, lines=(5, 3))[0])
        seen.add((_has_lines_field(plain), tok in plain))
    assert seen == {(True, True)}  # lines + tok never shed, at any width


def test_shed_model_and_duration_kept_duration_never_shed() -> None:
    # Duration is never shed. Model is now the field this cluster sheds under
    # width pressure (inverted Decision 10) -- it survives at generous widths
    # and is the first thing dropped as the row narrows.
    sub = _make_sub(agent_type='general-purpose', description='x' * 80,
                    first_timestamp=time.time() - 47, model='claude-sonnet-4-6',
                    total_input=12345, output=678)
    seen_model_present = seen_model_absent = False
    for w in range(30, 80):
        line1, _ = _two(sub, w)
        plain = strip_ansi(line1)
        assert '0:47' in plain, f'width={w} dropped duration'
        if 'sonnet' in plain:
            seen_model_present = True
        else:
            seen_model_absent = True
    assert seen_model_present  # kept at generous widths
    assert seen_model_absent   # shed under pressure (was never true pre-inversion)


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
    line1, _ = _two(sub, 156, stats_col=100)
    plain = strip_ansi(line1)
    assert plain[100] == '·'              # cluster dot anchored at stats_col
    assert _visible_width(line1) == 156   # still fills the content edge
    assert '…' in plain                   # description truncated before stats


def test_stats_col_none_keeps_right_alignment() -> None:
    # Default (no stats_col) is unchanged: the cluster right-aligns to the edge
    # so its leading `·` is well past stats_col=100 at this width.
    sub = _make_sub(description='short', total_input=12345, output=678)
    line1, _ = _two(sub, 156)
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
    line1_anchor, _ = _two(sub, 105, stats_col=100)
    line1_default, _ = _two(sub, 105)
    assert strip_ansi(line1_anchor) == strip_ansi(line1_default)
    assert strip_ansi(line1_anchor)[100] != '·'


def test_stats_col_richest_cluster_that_fits_at_anchor() -> None:
    # Slack to the right of the anchor governs which cluster is chosen. With
    # generous slack the full tok+model cluster anchors at stats_col.
    sub = _make_sub(total_input=12345, output=678, model='claude-sonnet-4-6')
    line1, _ = _two(sub, 156, stats_col=100)
    plain = strip_ansi(line1)
    tok   = fmt_tok(sub.total_input)
    assert plain[100] == '·'
    assert tok in plain and 'sonnet' in plain


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
    # end_ts - first_timestamp = 90s -> 1:30, shown at the front of line 1
    line1, _ = _two(_make_done_sub())
    assert '1:30' in strip_ansi(line1)


def test_done_two_line_duration_does_not_tick() -> None:
    sub = _make_done_sub()
    line1_a, _ = _two(sub)
    time.sleep(0.05)
    line1_b, _ = _two(sub)
    assert strip_ansi(line1_a) == strip_ansi(line1_b)


def test_done_two_line_duration_is_greyed() -> None:
    # A finished agent's timer is frozen, so it greys with the type/name text
    # rather than keeping the live/done accent colour. Only the ✓/✗ marker
    # keeps done_clr.
    sub   = _make_done_sub()
    dur_s = subagent_dur_str(sub, time.time())
    line1, _ = _two(sub)
    # dur_s is right-justified; `strike` keeps the pad space outside SGR 9.
    assert f'{_r.CTX_DIM}{dur_s.replace(dur_s.strip(), STRIKE + dur_s.strip() + UNSTRIKE)}' in line1
    assert f'{_r.safe}{dur_s}' not in line1


def test_running_two_line_duration_keeps_live_colour() -> None:
    sub   = _make_sub()
    dur_s = subagent_dur_str(sub, time.time())
    line1, _ = _two(sub)
    assert f'{_r.CTX}{dur_s}' in line1


def test_done_one_line_duration_is_greyed() -> None:
    sub   = _make_done_sub()
    dur_s = subagent_dur_str(sub, time.time())
    line  = _one(sub)
    assert f'{_r.CTX_DIM}{dur_s.replace(dur_s.strip(), STRIKE + dur_s.strip() + UNSTRIKE)}' in line
    assert f'{_r.safe}{dur_s}' not in line


def test_done_one_line_name_is_greyed() -> None:
    # The italic name/type field greys too, matching the twoline tree form.
    line = _one(_make_done_sub())
    assert f'{_r.CTX_DIM}{ITALIC}' in line
    assert f'{_r.safe}{ITALIC}' not in line


def test_running_one_line_name_keeps_live_styling() -> None:
    line = _one(_make_sub())
    assert f'{_r.SKILLS}{ITALIC}' in line


def test_done_two_line_no_marker() -> None:
    line1, _ = _two(_make_done_sub())
    plain = strip_ansi(line1)
    assert '▶' not in plain
    assert '✓' not in plain


# E2. Four-state lifecycle (completed/killed/stopped/failed) + resume --------

def _make_state_sub(status: str, **kw) -> RunningSubagent:
    now = time.time()
    defaults = dict(first_timestamp=now - 120.0, end_ts=now - 30.0, status=status)
    defaults.update(kw)
    return _make_sub(**defaults)


@pytest.mark.parametrize('status, glyph', [
    ('completed', '✓'),
    ('killed', '✗'),
    ('stopped', '✗'),
    ('failed', '!'),
])
def test_one_line_terminal_state_marker(status: str, glyph: str) -> None:
    sub = _make_state_sub(status)
    out = strip_ansi(_one(sub))
    assert glyph in out
    assert '▶' not in out


def test_one_line_killed_and_stopped_share_glyph() -> None:
    killed  = strip_ansi(_one(_make_state_sub('killed')))
    stopped = strip_ansi(_one(_make_state_sub('stopped')))
    # Same marker glyph for both — "ended early by intent".
    assert '✗' in killed and '✗' in stopped


def test_one_line_failed_marker_dim_styling() -> None:
    line = _one(_make_state_sub('failed'))
    assert _r.CTX_DIM in line


@pytest.mark.parametrize('status', ['completed', 'killed', 'stopped', 'failed'])
def test_two_line_terminal_marker_in_tree_column(status: str) -> None:
    # Tree mode renders the run-state glyph as the name/model separator
    # (`<name> <glyph> <model>`); every terminal state shows its glyph there
    # instead of the running '·'.
    sub = _make_state_sub(status)
    line = _r.subagent_row(sub, 136, twoline=True, tree_single=True,
                           tree_prefix='├ ', tree_desc_col=40)
    plain = strip_ansi(line)
    marker = {'completed': '✓', 'killed': '✗', 'stopped': '✗', 'failed': '!'}[status]
    assert marker in plain
    # The glyph sits between the name and the model label.
    assert plain.index('general-purpose') < plain.index(marker) < plain.index('sonnet')


def test_two_line_strikethrough_applies_to_all_terminal_states() -> None:
    for status in ('completed', 'killed', 'stopped', 'failed'):
        sub = _make_state_sub(status, description='finish the report')
        line1, _ = _two(sub, 136, stats_col=100)
        assert STRIKE in line1 and UNSTRIKE in line1, f'status={status} missing strikethrough'


def test_one_line_resumed_shows_resume_glyph_without_run_count() -> None:
    # The ×N run-count suffix was removed: run_count counts
    # <task-notification> records, which a stall watchdog inflates for
    # merely-slow agents. The ↺ glyph alone marks the resume.
    sub = _make_sub(status='running', run_count=1, resumed=True,
                    first_timestamp=time.time() - 47)
    out = strip_ansi(_one(sub))
    assert '↺' in out
    assert '▶' not in out
    assert '×' not in out


def test_one_line_resumed_keeps_live_styling_not_dim() -> None:
    sub = _make_sub(status='running', run_count=1, resumed=True)
    line = _one(sub)
    assert _r.SKILLS in line


def test_one_line_resumed_elapsed_uses_first_timestamp_when_run_start_unset() -> None:
    # RENAMED (was test_one_line_resumed_elapsed_continues_from_original_spawn):
    # `_make_sub` leaves `run_start_ts` unset, so it defaults to
    # `first_timestamp` (the "no resume boundary tracked" case) regardless of
    # the `resumed`/`run_count` flags passed here. Kept, renamed, to cover
    # exactly that default-anchor fallback rather than imply it exercises the
    # real resume-boundary math (see info/subagents.py's `run_start_ts`
    # computation in `from_session` for that).
    sub = _make_sub(status='running', run_count=1, resumed=True,
                    first_timestamp=time.time() - 90)
    out = strip_ansi(_one(sub))
    assert '1:30' in out


def test_one_line_resumed_elapsed_uses_run_start_ts_when_set() -> None:
    # The real resume-boundary case: run_start_ts distinct from
    # first_timestamp must win — this is the row-rendering-level regression
    # guard for the fix (info/subagents.py's from_session covers the actual
    # boundary computation; this only checks subagent_row wires run_start_ts
    # through subagent_dur_str correctly).
    now = time.time()
    sub = _make_sub(status='running', run_count=1, resumed=True,
                    first_timestamp=now - 65 * 60, run_start_ts=now - 90)
    out = strip_ansi(_one(sub))
    assert '1:30' in out
    assert '1:05:' not in out


def test_two_line_resumed_shows_resume_glyph_in_tree_column() -> None:
    sub = _make_sub(status='running', run_count=2, resumed=True)
    line = _r.subagent_row(sub, 136, twoline=True, tree_single=True,
                           tree_prefix='├ ', tree_desc_col=40)
    plain = strip_ansi(line)
    assert '↺' in plain
    assert '×' not in plain  # the run-count suffix is gone; the glyph remains


def test_one_line_not_resumed_without_resumed_flag_or_run_count() -> None:
    sub = _make_sub(status='running')
    out = strip_ansi(_one(sub))
    assert '↺' not in out


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
    assert '0:47' in out


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


def test_one_line_running_has_blank_marker() -> None:
    # Matches the tree twoline convention: running rows reserve a blank
    # marker column ('✓' when done, '↺' when resumed) — no '▶' glyph.
    out = strip_ansi(_one(_make_sub()))
    assert '▶' not in out
    assert '✓' not in out


def test_one_line_done_uses_checkmark() -> None:
    out = strip_ansi(_one(_make_done_sub()))
    assert '✓' in out
    assert '▶' not in out


def test_one_line_done_frozen_duration() -> None:
    sub = _make_done_sub()
    out = strip_ansi(_one(sub))
    assert '1:30' in out


# E3. LOC (opportunistic, oneline form) ---------------------------------------
#
# The oneline branch has no reserved LOC column (unlike twoline/tree_single,
# which always reserves it) — LOC only appears once there's genuine slack
# past the (already-safe) front field, using the same '<read> / <written>'
# format as the twoline form. Threshold determined empirically (see the
# renderer-precedence report addendum) for this fixture: a short
# ('grep-bot'/'haiku', oneline_name_w=8, oneline_model_w=5) cohort-aligned
# row first shows LOC cleanly at content_width=44; nothing below that width
# shows it, and no width in the sweep garbles (no doubled ellipsis).

def _make_loc_sub(**kw) -> RunningSubagent:
    defaults = dict(agent_type='grep-bot', model='claude-haiku-4-5',
                    last_activity=('tool_use', 'Bash', {'command': 'pytest -q'}))
    defaults.update(kw)
    return _make_sub(**defaults)


def test_one_line_loc_absent_below_threshold_no_garbling() -> None:
    sub = _make_loc_sub()
    for w in range(24, 44):
        out = strip_ansi(_r.subagent_row(
            sub, w, twoline=False, lines=(1234, 567),
            oneline_name_w=8, oneline_model_w=5,
        ))
        assert ' / ' not in out, f'width={w}: LOC shown below the measured threshold'
        # No doubled-ellipsis garbling: at most one '…' run in the front field.
        assert out.count(ELLIPSIS) <= 2, f'width={w}: garbled ({out!r})'


def test_one_line_loc_present_at_and_above_threshold() -> None:
    sub = _make_loc_sub()
    for w in range(44, 60):
        out = strip_ansi(_r.subagent_row(
            sub, w, twoline=False, lines=(1234, 567),
            oneline_name_w=8, oneline_model_w=5,
        ))
        assert ' / ' in out, f'width={w}: LOC missing at/above the measured threshold'
        assert '1.23K / 567' in out


def test_one_line_loc_absent_without_lines_data() -> None:
    # No `lines=` at all -- LOC never appears regardless of width, even well
    # past the threshold.
    sub = _make_loc_sub()
    out = strip_ansi(_r.subagent_row(sub, 60, twoline=False, oneline_name_w=8, oneline_model_w=5))
    assert ' / ' not in out


def test_one_line_loc_absent_when_lines_are_zero() -> None:
    # (0, 0) is treated the same as "no data" -- opportunistic, not forced.
    sub = _make_loc_sub()
    out = strip_ansi(_r.subagent_row(
        sub, 60, twoline=False, lines=(0, 0), oneline_name_w=8, oneline_model_w=5,
    ))
    assert ' / ' not in out


def test_one_line_loc_never_overflows_target_width() -> None:
    sub = _make_loc_sub()
    for w in range(24, 70):
        out = strip_ansi(_r.subagent_row(
            sub, w, twoline=False, lines=(1234, 567),
            oneline_name_w=8, oneline_model_w=5,
        ))
        assert _visible_width(out) == w, f'width={w}: row padding/width mismatch ({out!r})'


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
    # `<time> <name> · <model> · <tok> · <activity>` — the token count sits
    # in a fixed column straight after the model, and the activity/log is
    # the LAST column, right-padded out to exactly content_width.
    content_width = 90
    sub = _make_sub(agent_type='grep-bot',
                    last_activity=('tool_use', 'Grep', {}))
    out  = _one(sub, content_width)
    text = strip_ansi(out)
    assert _visible_width(out) == content_width
    assert text.index(fmt_tok(sub.total_input)) < text.index('Grep')


def test_one_line_model_follows_type_before_activity() -> None:
    # Mirrors the wide/tree reading order: `<time> <name> · <model> · <tok>
    # · <activity>` — the activity/log is the last column.
    sub = _make_sub(agent_type='general-purpose',
                    model='claude-sonnet-4-6',
                    last_activity=('tool_use', 'Bash', {}))
    text = strip_ansi(_one(sub))
    assert text.index('general-purpose') < text.index('sonnet')
    assert text.index('sonnet') < text.index(fmt_tok(sub.total_input)) < text.index('Bash')


def test_one_line_model_forms_aligned_column_with_cohort_widths() -> None:
    # Two stacked rows with differing name/model widths align their ' · model'
    # column when the caller supplies the cohort-measured `oneline_name_w` /
    # `oneline_model_w` (the layout builders pass these for every cohort).
    content_width = 90
    a = _make_sub(agent_type='synth', model='claude-3-5-haiku',
                  total_input=6800, first_timestamp=time.time() - 90,
                  last_activity=('tool_use', 'Edit', {}))
    b = _make_sub(agent_type='fetch-notebook-worker', model='claude-sonnet-4-6',
                  total_input=11500, first_timestamp=time.time() - 50,
                  last_activity=('tool_use', 'Read', {}))
    name_w  = max(len('synth'), len('fetch-notebook-worker'))
    model_w = max(len('haiku'), len('sonnet'))
    row_a = strip_ansi(_one(a, content_width, oneline_name_w=name_w, oneline_model_w=model_w))
    row_b = strip_ansi(_one(b, content_width, oneline_name_w=name_w, oneline_model_w=model_w))
    # The model column start lines up despite the differing name widths.
    assert row_a.index('haiku') == row_b.index('sonnet')
    # Both rows fill to exactly content_width, so the right-anchored token
    # column also lines up by construction.
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
    (4, '0:04'), (47, '0:47'), (83, '1:23'), (3700, '1:01:40'),
])
def test_one_line_duration_formats(elapsed: int, token: str) -> None:
    out = strip_ansi(_one(_make_sub(first_timestamp=time.time() - elapsed)))
    assert token in out


def test_subagent_dur_str_is_mmss_not_fmt_dur_style() -> None:
    # Change: elapsed time is M:SS (e.g. '1:29'), not fmt_dur's '1m29s' style.
    from yas.render.metrics import subagent_dur_str
    sub = _make_sub(first_timestamp=time.time() - 89)
    assert subagent_dur_str(sub, time.time()).strip() == '1:29'


def test_subagent_dur_str_rolls_to_hms() -> None:
    from yas.render.metrics import subagent_dur_str
    sub = _make_sub(first_timestamp=time.time() - 3700)  # 1:01:40
    assert subagent_dur_str(sub, time.time()).strip() == '1:01:40'


def test_two_line_duration_mmss_in_every_width_mode() -> None:
    # The M:SS format applies in the two-line, tree-single, and one-line
    # collapse forms alike — never the old '1m29s' style.
    sub = _make_sub(first_timestamp=time.time() - 89)
    line1_two, _ = _two(sub)
    line_one     = _one(sub)
    assert '1:29' in strip_ansi(line1_two)
    assert '1:29' in strip_ansi(line_one)
    assert '1m29s' not in strip_ansi(line1_two)
    assert '1m29s' not in strip_ansi(line_one)


def test_one_line_no_timestamp_fallback() -> None:
    out = strip_ansi(_one(_make_sub(first_timestamp=0)))
    assert '0:00' in out


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
        classmethod(lambda cls, sid, pdir, **kwargs: subagents_mod.RunningSubagents(subagents=subs)),
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
    monkeypatch.setattr(constants, 'CLAUDE_DIR', tmp_path)
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
    # root -> k1 (leaf, not last), k2 (last, has a child) -> gk (leaf, only
    # child of k2). Top-level agents branch off the implicit, never-rendered
    # main thread, so `root` itself gets an elbow too — here it's the only
    # top-level agent, so it's "last" (`└`) and has children (`┬`). Box-
    # drawing connectors: a node with children gets '┬' at its own
    # position, a leaf gets '─' (or '┈' when not active); ancestor columns
    # render '│'/'┊' only when that ancestor still has siblings following it
    # (root is last and k2 is last, so gk's two ancestor columns are both
    # blank, not '│'). Every raw connector is then padded with '─'/'┈' up to
    # the cohort's widest (gk's 4-char '  └─'), so every row's trailing
    # separator space — and the name after it — lands one column past that
    # shared width. All four agents default to still-running here, so every
    # segment paints active (solid '─'/'│') rather than dashed.
    root = _make_tree_sub('agent-a', agent_type='main')
    k1   = _make_tree_sub('agent-b', parent_id='a', ts_off=1)
    k2   = _make_tree_sub('agent-c', parent_id='a', ts_off=2)
    gk   = _make_tree_sub('agent-d', parent_id='c', ts_off=3)
    cells = layout.subagent_cells([root, k1, k2, gk])
    assert [strip_ansi(p) for _, p, _ in cells] == ['└┬─ ', ' ├─── ', ' └┬── ', '  └──── ']
    assert [d for _, _, d in cells] == [0, 1, 1, 2]


def test_subagent_cells_ancestor_column_continues_past_uncle() -> None:
    # root -> a (has a child, not last) -> b (leaf grandchild); root -> c
    # (last sibling of a, leaf "uncle"). The grandchild's ancestor column
    # must render '│' (not blank) because its parent `a` still has a
    # sibling (`c`) following below — the vertical line has to keep
    # running past the grandchild's row to reach it. `root` is the sole
    # top-level agent, so its own column (both a's and b's leftmost
    # column) stays blank — only `a`'s own not-last status feeds a '│'.
    # All four default to still-running, so the column `a` contributes for
    # b's row is active/solid '│': it ORs together "does `a` have a later
    # active CHILD past b" (no) with "does `a` itself have a later active
    # SIBLING" (yes — `c` is running) — the same OR that fixes the
    # spurious-dashed-spine bug (a live branch reached only via a parent's
    # later sibling must not paint its child's spine dashed).
    root = _make_tree_sub('agent-r', agent_type='root')
    a    = _make_tree_sub('agent-a', parent_id='r', ts_off=1)
    b    = _make_tree_sub('agent-b', parent_id='a', ts_off=2)
    c    = _make_tree_sub('agent-c', parent_id='r', ts_off=3)
    cells = layout.subagent_cells([root, a, b, c])
    prefixes = {sub.agent_id: strip_ansi(p) for sub, p, _ in cells}
    assert prefixes['agent-a'].startswith(' ├┬')   # not last, has a child
    assert prefixes['agent-b'].startswith(' │└')   # ancestor column stays active via `c`
    assert prefixes['agent-c'].startswith(' └─')   # last sibling, leaf, active


def test_subagent_cells_single_child_gets_last_leaf_elbow() -> None:
    root = _make_tree_sub('agent-a', agent_type='main')
    only = _make_tree_sub('agent-b', parent_id='a', ts_off=1)
    cells = layout.subagent_cells([root, only])
    assert [strip_ansi(p) for _, p, _ in cells] == ['└┬─ ', ' └─── ']


def test_subagent_cells_multiple_siblings_only_last_gets_corner() -> None:
    root = _make_tree_sub('agent-a', agent_type='main')
    k1   = _make_tree_sub('agent-b', parent_id='a', ts_off=1)
    k2   = _make_tree_sub('agent-c', parent_id='a', ts_off=2)
    k3   = _make_tree_sub('agent-d', parent_id='a', ts_off=3)
    cells = layout.subagent_cells([root, k1, k2, k3])
    prefixes = [strip_ansi(p) for _, p, _ in cells]
    assert prefixes == ['└┬─ ', ' ├─── ', ' ├─── ', ' └─── ']


def test_subagent_cells_multiple_top_level_agents_get_own_elbow() -> None:
    # Two unrelated top-level agents (no parent/child relation between
    # them): both branch directly off the implicit main thread and are
    # ordered as siblings — only the second (last) gets '└'.
    first  = _make_tree_sub('agent-a', agent_type='first')
    second = _make_tree_sub('agent-b', agent_type='second', ts_off=1)
    cells = layout.subagent_cells([first, second])
    assert [strip_ansi(p) for _, p, d in cells] == ['├── ', '└── ']
    assert [d for _, _, d in cells] == [0, 0]


def test_subagent_cells_prefix_staircases_by_depth() -> None:
    # Mixed-depth cohort (including the root): names STAIRCASE rather than
    # sharing one column — each row's prefix visible width is exactly
    # TREE_PREFIX_BASE_W + depth * TREE_PREFIX_STEP_W, so a deeper row's
    # name starts further right than a shallower one's, by a constant step
    # per level.
    root = _make_tree_sub('agent-r', agent_type='root')
    a    = _make_tree_sub('agent-a', parent_id='r', ts_off=1)
    b    = _make_tree_sub('agent-b', parent_id='a', ts_off=2)
    c    = _make_tree_sub('agent-c', parent_id='r', ts_off=3)
    cells = layout.subagent_cells([root, a, b, c])
    for _, prefix, depth in cells:
        assert _visible_width(prefix) == TREE_PREFIX_BASE_W + depth * TREE_PREFIX_STEP_W


def test_subagent_cells_finished_leaf_dashed_but_white() -> None:
    # A lone, finished top-level agent's whole connector — elbow, branch, and
    # fill — is DASHED (nothing downstream is running) but still renders
    # bright white: colour no longer differentiates finished from running,
    # only the dashed-vs-solid glyph does.
    root = _make_tree_sub('agent-a', agent_type='main', end_ts=100.0, status='completed')
    cells = layout.subagent_cells([root])
    prefix = [p for _, p, _ in cells][0]
    assert CLR_GREY_DIM not in prefix
    assert prefix.count(CLR_WHITE_BRT) == 3   # elbow + branch + 1-char fill
    assert strip_ansi(prefix) == '└┈┈ '


def test_subagent_cells_running_leaf_paints_bright_white_solid() -> None:
    # Same shape, but still running: solid glyphs, still bright white.
    root = _make_tree_sub('agent-a', agent_type='main', status='running')
    cells = layout.subagent_cells([root])
    prefix = [p for _, p, _ in cells][0]
    assert CLR_GREY_DIM not in prefix
    assert CLR_WHITE_BRT in prefix
    assert strip_ansi(prefix) == '└── '


def test_subagent_cells_active_wins_on_shared_ancestor_column() -> None:
    # root -> a (finished, not last) -> b (finished leaf); root -> c (last
    # sibling, still running). The trunk column shared by b's row (root's
    # own elbow/branch, drawn on root's row) must render SOLID because a
    # live descendant (`c`) is reachable through it, even though the
    # finished branch (`a`/`b`) itself renders dashed throughout. Colour is
    # bright white everywhere, regardless of activity — only the glyph
    # (solid vs dashed) follows activity now.
    root = _make_tree_sub('agent-r', agent_type='root', status='running')
    a    = _make_tree_sub('agent-a', parent_id='r', ts_off=1, status='completed', end_ts=1.0)
    b    = _make_tree_sub('agent-b', parent_id='a', ts_off=2, status='completed', end_ts=2.0)
    c    = _make_tree_sub('agent-c', parent_id='r', ts_off=3, status='running')
    cells = layout.subagent_cells([root, a, b, c])
    prefixes = {sub.agent_id: p for sub, p, _ in cells}
    # No row anywhere in this cohort uses CLR_GREY_DIM.
    for prefix in prefixes.values():
        assert CLR_GREY_DIM not in prefix
    assert f'{CLR_WHITE_BRT} {RESET}' in prefixes['agent-a']          # ancestor column, active wins
    assert f'{CLR_WHITE_BRT}├{RESET}' in prefixes['agent-a']          # a's own elbow, white
    assert f'{CLR_WHITE_BRT}┬{RESET}' in prefixes['agent-a']          # a's own branch, white
    assert f'{CLR_WHITE_BRT}└{RESET}' in prefixes['agent-b']          # b's own elbow, white
    assert f'{CLR_WHITE_BRT}{BOX_H_DASH4}{RESET}' in prefixes['agent-b']  # b's branch dashed, but white
    assert f'{CLR_WHITE_BRT}└{RESET}' in prefixes['agent-c']          # c's own elbow, white
    assert f'{CLR_WHITE_BRT}{BOX_H}{RESET}' in prefixes['agent-c']    # c's branch solid, white
    # Structure: a's ancestor column carries no glyph of its own (blank);
    # b's visible ancestor column (contributed by `a`) ALSO tracks whether
    # `a` itself has a later active SIBLING (`c`, running) — not just later
    # siblings of `b` under `a` (there are none) — so it renders active/solid
    # '│', the fix for the spurious-dashed-spine bug; c's own leaf branch is
    # active so it's solid '─', not dashed '┈'.
    assert strip_ansi(prefixes['agent-a']).startswith(' ├┬')
    assert strip_ansi(prefixes['agent-b']).startswith(' │└')


def test_subagent_cells_ancestor_column_active_via_parents_later_sibling() -> None:
    # root1 -> two finished children (last one, `n2`, is the deepest row of
    # its group); root2 -> a running child (`m1`). Because root1 has a
    # later ACTIVE sibling (root2), the vertical spine `root1` contributes
    # to `n2`'s row must render active/solid '│', not dashed '┊' — the
    # branch it belongs to still leads somewhere live, just not through
    # root1's own children.
    root1 = _make_tree_sub('agent-r1', agent_type='root1', ts_off=0, status='completed', end_ts=1.0)
    n1    = _make_tree_sub('agent-n1', parent_id='r1', ts_off=1, status='completed', end_ts=2.0)
    n2    = _make_tree_sub('agent-n2', parent_id='r1', ts_off=2, status='completed', end_ts=3.0)
    root2 = _make_tree_sub('agent-r2', agent_type='root2', ts_off=3, status='completed', end_ts=4.0)
    m1    = _make_tree_sub('agent-m1', parent_id='r2', ts_off=4, status='running')
    cells = layout.subagent_cells([root1, n1, n2, root2, m1])
    prefixes = {sub.agent_id: strip_ansi(p) for sub, p, _ in cells}
    assert prefixes['agent-n1'].startswith('│├')  # not last, spine active via root2
    assert prefixes['agent-n2'].startswith('│└')  # last child, spine STILL active via root2


def test_cap_tree_groups_keeps_active_parent_with_child() -> None:
    # Parent started first (ts_off=0) and is still running (end_ts=0). Its
    # child started later (ts_off=1) so a flat "last N" slice would keep the
    # child but drop the parent. Five unrelated finished singletons round out
    # the cohort past the cap.
    parent = _make_tree_sub('agent-a', ts_off=0, agent_type='parent', end_ts=0.0)
    child  = _make_tree_sub('agent-b', parent_id='a', ts_off=1, agent_type='child', end_ts=0.0)
    finished = [
        _make_tree_sub(f'agent-f{i}', ts_off=2 + i, agent_type=f'done{i}', end_ts=time.time())
        for i in range(5)
    ]
    subs = [parent, child, *finished]
    got = subagents_mod.cap_tree_groups(subs, 6)
    assert parent in got and child in got
    assert len(got) == 6
    # Finished singleton groups are evicted first, ahead of the still-active pair.
    assert sum(1 for s in got if s in finished) == 4


def test_cap_tree_groups_trims_within_the_last_surviving_group() -> None:
    # A single group can't be evicted whole -- that would return an empty
    # cohort. Once it's the only group left, cap_tree_groups trims *within*
    # it instead: keep the root, drop descendants down to cap - 1.
    parent = _make_tree_sub('agent-a', ts_off=0, agent_type='parent', end_ts=0.0)
    child  = _make_tree_sub('agent-b', parent_id='a', ts_off=1, agent_type='child', end_ts=0.0)
    got = subagents_mod.cap_tree_groups([parent, child], 1)
    assert got == [parent]  # root always kept; cap - 1 == 0 descendants


def test_cap_tree_groups_never_evicts_a_group_to_zero() -> None:
    # One parent + 10 active children, all one group, over cap: the group
    # must never be evicted wholesale down to nothing -- it gets trimmed to
    # the root plus its most-recently-active `cap - 1` descendants instead.
    root = _make_tree_sub('agent-root', ts_off=0, agent_type='spec-implementer', end_ts=0.0)
    children = [
        _make_tree_sub(f'agent-c{i}', parent_id='root', ts_off=1 + i,
                        agent_type=f'child{i}', end_ts=0.0, mtime=time.time() - 100 + i)
        for i in range(10)
    ]
    subs = [root, *children]
    got = subagents_mod.cap_tree_groups(subs, 6)
    assert len(got) == 6
    assert got[0] is root
    # The 5 kept descendants are the most-recently-active ones (highest mtime).
    kept_ids = {id(sub) for sub in got[1:]}
    most_recent_ids = {id(sub) for sub in sorted(children, key=lambda s: s.mtime, reverse=True)[:5]}
    assert kept_ids == most_recent_ids


def test_cap_tree_groups_noop_under_cap() -> None:
    parent = _make_tree_sub('agent-a', ts_off=0)
    child  = _make_tree_sub('agent-b', parent_id='a', ts_off=1)
    subs = [parent, child]
    assert subagents_mod.cap_tree_groups(subs, 6) == subs


def test_tree_prefix_two_line_widths_and_indent() -> None:
    sub = _make_sub()
    line1, line2 = _two(sub, 136, tree_prefix='├ ')
    p1, p2 = strip_ansi(line1), strip_ansi(line2)
    # Elbow sits to the RIGHT of the elapsed time, not to its left: 'M:SS
    # <elbow> <name>', never '<elbow> M:SS <name>'.
    assert '├ ' in p1
    assert p1.index('├ ') > p1.index(':')
    assert not p1.startswith('├ ')
    assert p2.startswith('  ')            # continuation indents under the branch
    assert _visible_width(line1) == 136   # prefix eats content width, not the box
    assert _visible_width(line2) == 136


def test_tree_prefix_one_line_width() -> None:
    # The elbow renders inline between the duration and the name — same
    # '<time> <elbow> <name>' order as the twoline tree form.
    sub  = _make_sub()
    line = _one(sub, 96, tree_prefix='└ ')
    p    = strip_ansi(line)
    assert '└ ' in p
    assert p.index(':') < p.index('└')  # time (M:SS) left of the elbow
    assert _visible_width(line) == 96


def test_tree_prefix_default_noop() -> None:
    sub = _make_sub()
    assert _r.subagent_row(sub, 136, twoline=True) == \
           _r.subagent_row(sub, 136, twoline=True, tree_prefix='')


def test_elbow_sits_right_of_elapsed_time_two_line() -> None:
    # '<time> <elbow> <name>', never '<elbow> <time> <name>' — in every glyph
    # mode (checked here for the raw unicode elbow the renderer emits;
    # ascii-mode folding is covered separately in test_ascii_render.py).
    sub = _make_sub()
    for elbow in ('├ ', '└ ', '  ├ '):  # sibling, last-child, nested
        line1, _ = _two(sub, 136, tree_prefix=elbow)
        p1 = strip_ansi(line1)
        time_idx  = p1.index(':') - 1  # the MM:SS field starts one col before ':'
        elbow_idx = p1.index(elbow.strip())
        assert elbow_idx > time_idx, f'elbow at {elbow_idx} not right of time at {time_idx}: {p1!r}'


def test_elbow_sits_right_of_elapsed_time_tree_single() -> None:
    sub = _make_sub()
    line = _r.subagent_row(sub, 136, twoline=True, tree_single=True, tree_prefix='├ ')
    p = strip_ansi(line)
    assert p.index('├') > p.index(':')


def test_elbow_sits_right_of_elapsed_time_ascii_mode() -> None:
    # After folding through apply_glyph_mode('ascii'), the elbow becomes a
    # bare 'L' — confirm it still lands after the time field, not before it.
    from yas.render.text import apply_glyph_mode
    sub = _make_sub()
    line1, _ = _two(sub, 136, tree_prefix='├ ')
    ascii_line = apply_glyph_mode(strip_ansi(line1), 'ascii')
    time_idx  = ascii_line.index(':') - 1
    l_idx     = ascii_line.index('L')
    assert l_idx > time_idx, f'ascii elbow at {l_idx} not right of time at {time_idx}: {ascii_line!r}'


def test_root_row_has_no_elbow_but_keeps_time_first() -> None:
    # The top-level/root row (no tree_prefix) has no elbow at all — just
    # '<time> <name>' — per the worked example ('1:29 spec-author').
    sub = _make_sub()
    line1, _ = _two(sub, 136, tree_prefix='')
    p1 = strip_ansi(line1)
    assert '├' not in p1 and '└' not in p1
    assert p1.lstrip().split(' ', 1)[0].count(':') == 1  # leading token is the MM:SS time


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
    # Elbow sits to the right of the elapsed time in tree-single rows too.
    kid_p = strip_ansi(kid)
    assert '├ ' in kid_p
    assert kid_p.index('├ ') > kid_p.index(':')
    assert not kid_p.startswith('├ ')


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


def test_tree_single_type_and_model_never_shed_by_width() -> None:
    # Full precedence (highest-retained first): (1) timer+tok+loc protected,
    # (2) type, (3) model, (4) log, (5) name(description). In tree_single
    # mode, type and model are baked into the front field (never width-shed
    # at all — only capped at a fixed SUBAGENT_NAME_MAX/tree_model_w), so
    # they must survive at every width the row is asked to render at, even
    # widths so narrow the log/description have nothing left to give.
    sub = _make_tree_sub('agent-a', agent_type='spec-author', model='claude-sonnet-4-6',
                         description='x' * 40,
                         last_activity=('tool_use', 'Bash', {'command': 'x'}))
    cells = [(sub, '', 0)]
    model_w = layout.tree_model_width(cells)
    for width in range(40, 140, 5):
        desc_col, stats_col, activity_col = layout.tree_columns(cells, width, model_w=model_w)
        line = strip_ansi(_r.subagent_row(
            sub, width, twoline=True, tree_single=True,
            stats_col=stats_col, tree_desc_col=desc_col,
            tree_activity_col=activity_col, tree_model_w=model_w,
        ))
        assert 'spec-author' in line, f'width={width}: type shed'
        assert 'sonnet' in line, f'width={width}: model shed'


def test_tree_columns_common_anchor_across_names_and_prefixes() -> None:
    # layout.tree_columns: desc_col is the widest (prefix + duration + type)
    # across the cohort, so the shortest names/prefixes get padded up to it.
    # stats_col grows with the cohort's actual (measured) description content
    # — the shed priority is now inverted from the description-cap design:
    # description is the elastic side, the stats cluster is protected — so
    # stats_col == desc_col + 3 + the cohort's longest description, as long
    # as that leaves room for the (here: zero-width, no cluster reserved)
    # cluster plus the activity floor.
    root = _make_tree_sub('agent-a', agent_type='spec-author', description='d' * 10)     # prefix '', long type
    kid  = _make_tree_sub('agent-b', parent_id='a', agent_type='api', description='d' * 3)  # prefix '├ ', short type
    cells = [(root, '', 0), (kid, '├ ', 1)]
    desc_col, stats_col, activity_col = layout.tree_columns(cells, 140)
    # desc_col matches the widest row: '' + 5 + 1 + len('spec-author') + 1
    # (no leading marker column — the run-state glyph rides in the
    # name/model separator, and model_w is 0 here so no model field either).
    assert desc_col == 0 + 5 + 1 + len('spec-author') + 1
    assert activity_col >= stats_col + 16
    assert activity_col <= 140
    # Longest description in the cohort is 10 chars, well past the floor and
    # well under the available room, so stats_col reflects it exactly.
    assert stats_col == desc_col + 3 + 10


def test_tree_columns_protects_cluster_before_shedding_description() -> None:
    # Inverted priority: when the cohort's cluster needs real room
    # (cluster_full_w > 0), stats_col reserves that room FIRST — the
    # description is squeezed toward its floor rather than the cluster
    # shedding fields. At a width where the naive "give description whatever
    # it wants" placement would leave no room for the cluster, stats_col must
    # still clear desc_col + 3 + SUBAGENT_DESC_FLOOR (never less).
    root  = _make_tree_sub('agent-a', agent_type='spec-author', description='x' * 200)
    cells = [(root, '', 0)]
    cluster_w = 40
    desc_col, stats_col, activity_col = layout.tree_columns(cells, 90, cluster_full_w=cluster_w)
    assert stats_col >= desc_col + 3 + SUBAGENT_DESC_FLOOR
    # The 200-char description is nowhere close to fitting — confirms the
    # cluster's reserved room took priority over the description's appetite.
    assert stats_col < desc_col + 3 + 200


def test_tree_single_description_aligned_across_depths_and_names() -> None:
    # Full pipeline: root (long type name, no prefix) and a deeper child
    # (short type name, indented prefix) still start ' · description' and the
    # activity column at the identical absolute offset.
    root = _make_tree_sub('agent-a', agent_type='spec-author', description='Fetch the artifact',
                          last_activity=('tool_use', 'Bash', {'command': 'openspec show'}))
    kid  = _make_tree_sub('agent-b', parent_id='a', agent_type='api', description='Make tmp dir',
                          last_activity=('tool_use', 'Bash', {'command': 'mkdir -p /tmp'}))
    cells = [(root, '', 0), (kid, '├ ', 1)]
    model_w = layout.tree_model_width(cells)
    desc_col, stats_col, activity_col = layout.tree_columns(cells, 140, model_w=model_w)
    lines = [
        strip_ansi(_r.subagent_row(sub, 140, twoline=True, tree_single=True, tree_prefix=prefix,
                                   stats_col=stats_col, tree_desc_col=desc_col,
                                   tree_activity_col=activity_col, tree_model_w=model_w))
        for sub, prefix, _ in cells
    ]
    # Locate each row's description text directly (rather than the first
    # ' · ' substring, which now belongs to the front-embedded model
    # separator, not the description one).
    desc_idx = [ln.index(desc) for ln, desc in zip(lines, ('Fetch the artifact', 'Make tmp dir'))]
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


def test_tree_columns_desc_grows_to_content_at_wide_width_no_hard_cap() -> None:
    # Inverted design: there is no fixed description-column cap any more. At
    # a wide enough terminal with room to spare, stats_col grows to fit the
    # cohort's ACTUAL longest description in full — even well past the old
    # SUBAGENT_DESC_MIN_WIDTH=70 cap — so a long title is never left
    # ellipsis-truncated just because the terminal is wide.
    long_desc = 'x' * 120
    root = _make_tree_sub('agent-a', agent_type='spec-implementer', description=long_desc)
    cells = [(root, '', 0)]
    desc_col, stats_col, activity_col = layout.tree_columns(cells, 260, cluster_full_w=40)
    assert stats_col == desc_col + 3 + len(long_desc)
    assert activity_col <= 260


def test_tree_columns_degrades_gracefully_at_narrow_width() -> None:
    # At a narrow terminal the description is squeezed toward (and, in an
    # extreme squeeze, even below) its floor rather than the cluster
    # shedding — but the row must still produce sane, positive, in-bounds,
    # non-overlapping column offsets: the activity-gap invariant always
    # holds, even if that means pulling stats_col back below the floor.
    root = _make_tree_sub('agent-a', agent_type='spec-implementer')
    cells = [(root, '', 0)]
    desc_col, stats_col, activity_col = layout.tree_columns(cells, 50)
    assert activity_col >= stats_col + 16
    assert activity_col <= 50
    assert stats_col > desc_col and activity_col > 0


def test_tree_columns_short_description_leaves_no_dead_gutter_at_wide_width() -> None:
    # Problem 2 regression: a cohort whose longest description is short must
    # NOT have its description column padded out toward some large
    # width-scaled figure just because the terminal is wide — stats_col
    # (and, downstream, activity_col) should track the cohort's actual
    # content width and stay put as the terminal widens, handing the freed
    # space to the activity column instead of leaving it as a gap.
    root = _make_tree_sub('agent-a', agent_type='spec-implementer', description='short')
    cells = [(root, '', 0)]
    desc_col_140, stats_col_140, activity_col_140 = layout.tree_columns(cells, 140, cluster_full_w=40)
    desc_col_300, stats_col_300, activity_col_300 = layout.tree_columns(cells, 300, cluster_full_w=40)
    assert desc_col_140 == desc_col_300
    assert stats_col_140 == stats_col_300 == desc_col_140 + 3 + len('short')
    assert activity_col_140 == activity_col_300  # no width-scaled growth either


def test_tree_model_width_measures_cohort_max() -> None:
    # tree_model_width measures the cohort's actual longest model label
    # (dynamic, per-cohort) — a cohort with only the short 'haiku' label
    # reserves exactly 5 columns; a cohort with a longer bracket-suffixed
    # label reserves exactly that label's width. It no longer pins to a
    # fixed constant regardless of content.
    short_only = [(_make_tree_sub('agent-a', model='claude-haiku-4-5-20251001'), '', 0)]
    long_only  = [(_make_tree_sub('agent-a', model='claude-sonnet-4-6[1m]'), '', 0)]
    assert layout.tree_model_width(short_only) == len('haiku')
    assert layout.tree_model_width(long_only) == len('sonnet[1m]')
    assert layout.tree_model_width([]) == 0


def test_tree_single_description_truncates_before_cluster_sheds() -> None:
    # End-to-end regression for the inverted shed priority: as the row
    # narrows, the description truncates (down to its floor) WHILE the
    # lines/tok cluster stays fully populated — the cluster is never
    # allowed to drop a field while the description still has room above its
    # floor to give up.
    from yas.render.metrics import subagent_cluster_width

    sub = _make_tree_sub('agent-a', agent_type='spec-implementer',
                         description='x' * 80, last_activity=('tool_use', 'Bash', {'command': 'x'}))
    cells = [(sub, '', 0)]
    model_w = layout.tree_model_width(cells)
    lines_w = layout.tree_lines_width(cells, {})
    si = 1000
    cluster_w = subagent_cluster_width(lines_w)

    saw_truncated_desc_with_full_cluster = False
    for width in range(70, 140):
        desc_col, stats_col, activity_col = layout.tree_columns(cells, width, cluster_full_w=cluster_w, model_w=model_w)
        line1 = _r.subagent_row(
            sub, width, twoline=True, session_inout=si, stats_col=stats_col,
            tree_single=True, tree_desc_col=desc_col, tree_activity_col=activity_col,
            tree_model_w=model_w, tree_lines_w=lines_w, lines=(5, 3),
        ).split('\n')[0]
        plain = strip_ansi(line1)
        desc_truncated = '…' in plain
        cluster_full = _has_lines_field(plain)
        # Never the inverse: a shed cluster while the description is intact.
        if desc_truncated and cluster_full:
            saw_truncated_desc_with_full_cluster = True
        assert not (cluster_full is False and not desc_truncated), (
            f'width={width}: cluster shed before description gave up any room'
        )
    assert saw_truncated_desc_with_full_cluster, 'never observed the truncate-before-shed rung'


def test_tree_columns_label_anchors_follow_elastic_desc_growth() -> None:
    # The SUBAGENTS header labels ('name', 'loc read / written', 'model',
    # 'current activity') are placed from desc_col/stats_col/activity_col —
    # verify those anchors still nest correctly (each label strictly to the
    # left of the next) at a narrow, medium, and very wide box now that
    # stats_col is content-elastic rather than a fixed guarantee.
    from yas.render.metrics import subagent_cluster_field_offsets, subagent_cluster_width

    root = _make_tree_sub('agent-a', agent_type='spec-implementer', description='Fetch things for the task')
    cells = [(root, '', 0)]
    model_w = layout.tree_model_width(cells)
    lines_w = layout.tree_lines_width(cells, {})
    cluster_w = subagent_cluster_width(lines_w)
    for width in (80, 140, 260):
        desc_col, stats_col, activity_col = layout.tree_columns(cells, width, cluster_full_w=cluster_w, model_w=model_w)
        _tok_off, lines_off = subagent_cluster_field_offsets(lines_w)
        # Model now anchors inside the front field (ahead of desc_col), not
        # the cluster — verify the remaining cluster fields (tok, lines) and
        # the activity column still nest correctly relative to desc_col.
        assert 3 + stats_col + _tok_off < 3 + stats_col + lines_off < 3 + activity_col


def test_tree_row_stats_cluster_aligns_across_long_and_short_duration_rows() -> None:
    # Regression: subagent_dur_str is NOT fixed-width -- '9:36' is 4 chars but
    # '40:23' (double-digit minutes) is 5. A long-running parent row and a
    # freshly-spawned prefixed child row used to disagree on the front-field
    # width because the layout math assumed a constant duration width, so
    # the whole stats cluster (read/written line-counts, tok, model) drifted
    # left by one column on the prefixed row. Assert both rows agree on the
    # absolute start column of the cluster, not a brittle full string.
    from yas.render.metrics import subagent_cluster_width

    parent = _make_tree_sub('agent-a', agent_type='spec-implementer', ts_off=-2360)  # ~40:23 elapsed
    child  = _make_tree_sub('agent-b', parent_id='a', agent_type='ui', ts_off=0)      # ~1:40 elapsed
    cells  = [(parent, '', 0), (child, '└ ', 1)]
    width  = 290
    model_w   = layout.tree_model_width(cells)
    lines_w   = layout.tree_lines_width(cells, {})
    cluster_w = subagent_cluster_width(lines_w)
    desc_col, stats_col, activity_col = layout.tree_columns(cells, width, cluster_full_w=cluster_w, model_w=model_w)

    def cluster_start_col(sub: RunningSubagent, prefix: str) -> int:
        line1 = _r.subagent_row(
            sub, width, twoline=True, session_inout=200_000, stats_col=stats_col,
            tree_prefix=prefix, tree_single=True, tree_desc_col=desc_col,
            tree_activity_col=activity_col, tree_model_w=model_w,
            tree_lines_w=lines_w, lines=(5, 3),
        ).split('\n')[0]
        stripped = strip_ansi(line1)
        idx = stripped.find('/')
        assert idx != -1
        return idx

    parent_col = cluster_start_col(parent, '')
    child_col  = cluster_start_col(child, '└ ')
    assert parent_col == child_col


def test_tree_single_constant_gap_with_model_padded_to_cohort_width() -> None:
    # TASK B: pad every row's model label to the cohort's own widest label
    # (via tree_model_w, now dynamically measured — see
    # test_tree_model_width_measures_cohort_max), then a CONSTANT
    # SUBAGENT_STATS_ACTIVITY_GAP-col gap separates the cluster from the
    # activity snippet, regardless of model label length or which models are
    # actually present in the cohort.
    short = _make_tree_sub('agent-a', agent_type='api', model='claude-haiku-4-5-20251001',
                           last_activity=('tool_use', 'Bash', {'command': 'x'}))
    long  = _make_tree_sub('agent-b', agent_type='api', model='claude-sonnet-4-6',
                           last_activity=('tool_use', 'Read', {'file_path': 'y.py'}))
    cells = [(short, '', 0), (long, '', 0)]
    model_w = layout.tree_model_width(cells)
    assert model_w == len('sonnet')
    l_short = strip_ansi(_r.subagent_row(short, 136, twoline=True, tree_single=True, tree_model_w=model_w))
    l_long  = strip_ansi(_r.subagent_row(long, 136, twoline=True, tree_single=True, tree_model_w=model_w))
    # The gap measured from the END OF THE PADDED MODEL FIELD (not from the
    # end of the visible label text) is identical for both rows — the model
    # pad-to-cohort-width absorbs the label-length difference, so what's left
    # is the constant activity gap (plus the activity glyph/space that always
    # leads the snippet).
    gap_short = l_short.index('Bash[') - (l_short.index('haiku') + len('haiku'))
    gap_long  = l_long.index('Read[') - (l_long.index('sonnet') + len('sonnet'))
    assert gap_short - (model_w - len('haiku')) == gap_long - (model_w - len('sonnet'))
    assert gap_short - (model_w - len('haiku')) >= SUBAGENT_STATS_ACTIVITY_GAP


def test_tree_single_off_keeps_two_line_with_tree_model_w() -> None:
    # Flat (twoline, tree_single=False) rendering stays byte-identical even
    # when a caller passes tree_model_w — the param is a no-op outside
    # tree_single mode.
    sub = _make_sub()
    assert _r.subagent_row(sub, 136, twoline=True) == \
           _r.subagent_row(sub, 136, twoline=True, tree_model_w=12)


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
        classmethod(lambda cls, sid, pdir, **kwargs: subagents_mod.RunningSubagents(subagents=[root, kid1, kid2])),
    )
    session = session_mod.SessionInfo.from_dict(json.loads(SESSION.read_text()))
    view    = SessionView(session, Config())
    tick    = TickRecord(token_log=TokenLog(), day_cost=0.0, tok_rate=0)
    spec    = layout.build_wide(view, tick, 140, _r)
    out     = [strip_ansi(ln) for ln in layout.render_layout(spec, _r)]
    kid_lines = [ln for ln in out if 'kid-one' in ln or 'kid-two' in ln]
    assert len(kid_lines) == 2                     # one line per subagent
    # All three default to still-running, so every connector segment is
    # active (solid '─'/'│'), not dashed.
    assert ' ├─── ' in kid_lines[0] and 'kid-one' in kid_lines[0] and 'Bash[' in kid_lines[0]
    assert ' └─── ' in kid_lines[1] and 'kid-two' in kid_lines[1] and 'Read[' in kid_lines[1]
    # tree mode stacks single-column even above TWO_COL_SUBAGENT_WIDTH; the root
    # is a single line carrying its own activity, no separate continuation row.
    # The root branches off the implicit main thread and — as the sole
    # top-level agent with two children — gets its own '└┬' elbow.
    root_lines = [ln for ln in out if 'root-agent' in ln]
    assert len(root_lines) == 1 and '└┬─ ' in root_lines[0] and 'Task[' in root_lines[0]
    # Description and activity columns line up across depths: root (its own
    # elbow, longer type name) vs the indented children (shorter names).
    all_rows  = root_lines + kid_lines
    desc_cols = [ln.index(' · ') for ln in all_rows]
    assert len(set(desc_cols)) == 1, f'description column drifted: {desc_cols}'


# I. select_visible_cohort: retention, cascade-clear, eviction ---------------

def _rs(agent_id: str, status: str = 'running', end_ts: float = 0.0,
        parent_id: str = '', mtime: float | None = None) -> RunningSubagent:
    now = time.time()
    return RunningSubagent(
        agent_type='general-purpose', description='x', billed_in=1, output=1,
        first_timestamp=now - 60, model='claude-sonnet-4-6', end_ts=end_ts,
        mtime=mtime if mtime is not None else now, agent_id=agent_id,
        parent_id=parent_id, status=status,
    )


def test_retention_drops_terminal_row_past_120s() -> None:
    now = time.time()
    fresh_done = _rs('a', status='completed', end_ts=now - 10)
    stale_done = _rs('b', status='completed', end_ts=now - 200)
    out = layout.select_visible_cohort([fresh_done, stale_done], cap=6, now=now)
    assert fresh_done in out
    assert stale_done not in out


def test_retention_never_drops_running_row() -> None:
    now = time.time()
    running = _rs('a', status='running')
    out = layout.select_visible_cohort([running], cap=6, now=now)
    assert running in out


def test_cascade_clear_forces_running_descendant_terminal() -> None:
    now = time.time()
    parent = _rs('p', status='completed', end_ts=now - 5)
    child  = _rs('c', status='running', parent_id='p')
    out = layout.select_visible_cohort([parent, child], cap=6, now=now)
    child_out = next(s for s in out if s.agent_id == 'c')
    assert child_out.status == 'completed'
    assert child_out.end_ts == parent.end_ts


def test_cascade_clear_walks_multiple_ancestor_levels() -> None:
    now = time.time()
    grandparent = _rs('gp', status='killed', end_ts=now - 5)
    parent      = _rs('p', status='running', parent_id='gp')
    child       = _rs('c', status='running', parent_id='p')
    out = layout.select_visible_cohort([grandparent, parent, child], cap=6, now=now)
    for sub in out:
        if sub.agent_id in ('p', 'c'):
            assert sub.status == 'killed'


def test_cap_evicts_finished_group_before_live_one() -> None:
    # Capacity pressure: a lingering finished root must yield its slot to a
    # still-running one even though its retention window has not expired.
    now  = time.time()
    done = _rs('done', status='completed', end_ts=now - 10, mtime=now - 10)
    live = _rs('live', status='running', mtime=now - 1)

    out = layout.select_visible_cohort([done, live], cap=1, now=now)

    assert out == [live]


def test_cap_evicts_oldest_finished_group_first() -> None:
    now    = time.time()
    older  = _rs('older',  status='completed', end_ts=now - 90, mtime=now - 90)
    newer  = _rs('newer',  status='completed', end_ts=now - 10, mtime=now - 10)

    out = layout.select_visible_cohort([older, newer], cap=1, now=now)

    assert out == [newer]


def test_cap_within_one_group_keeps_live_child_over_finished_one() -> None:
    # Single-group trim path: the finished child has the more recent mtime,
    # but a live sibling still outranks it.
    now      = time.time()
    root     = _rs('root', status='running', mtime=now - 1)
    finished = _rs('fin',  status='completed', end_ts=now - 2, mtime=now - 1,
                   parent_id='root')
    live     = _rs('live', status='running', mtime=now - 30, parent_id='root')

    out = layout.select_visible_cohort([root, finished, live], cap=2, now=now)

    assert out == [root, live]


# K. Per-subagent lines read/changed field (Decision 10) -----------------------

def test_lines_field_shows_humanised_values() -> None:
    # 1234 -> '1.23K', 567 -> '567' via fmt_tok_fixed (subagent-row-only,
    # 3-significant-figure formatting); rendered as '<read> / <written>' (a
    # space on both sides of the slash), no icons.
    sub = _make_sub(total_input=12345, output=678)
    line1, _ = _two(sub, 136, lines=(1234, 567))
    plain = strip_ansi(line1)
    assert fmt_tok_fixed(1234) in plain
    assert fmt_tok_fixed(567) in plain
    assert _has_lines_field(plain)
    assert f'{fmt_tok_fixed(1234)} / {fmt_tok_fixed(567)}' in plain


def test_lines_field_blank_when_both_zero() -> None:
    # Non-tree (flat/twoline) rows OMIT the field entirely when there's no
    # data — the width-reservation behaviour is tree_single-only. `lines`
    # supplied but both sides zero counts as "no data" here.
    sub = _make_sub(total_input=12345, output=678)
    line1, _ = _two(sub, 136, lines=(0, 0))
    plain = strip_ansi(line1)
    assert not _has_lines_field(plain)


def test_lines_field_blank_when_both_zero_tree_single() -> None:
    # tree_single DOES reserve the field's width even with no data, so
    # cohort rows without data stay aligned under sibling rows that do.
    sub = _make_sub(total_input=12345, output=678)
    line1 = _r.subagent_row(
        sub, 136, twoline=True, tree_single=True, lines=(0, 0),
    ).split('\n')[0]
    plain = strip_ansi(line1)
    assert _has_lines_field(plain)
    # Both sides immediately touching the '/' are blank (space), not '0'.
    idx = plain.index('/')
    assert plain[idx - 1] == ' ' and plain[idx + 1] == ' '


def test_lines_field_blank_when_none() -> None:
    # lines=None (idle/default) also renders blank, same as (0, 0).
    sub = _make_sub(total_input=12345, output=678)
    line1_none, _ = _two(sub, 136, lines=None)
    line1_zero, _ = _two(sub, 136, lines=(0, 0))
    assert strip_ansi(line1_none) == strip_ansi(line1_zero)


def test_lines_field_omitted_not_blank_dot_when_no_data() -> None:
    # Non-tree (flat/twoline) rows: a caller that never supplies `lines`
    # (narrow/medium rows, workflow-agent rows) OMITS the field entirely
    # (and its leading '· ' separator), rather than reserving blank-padded
    # width — that reservation behaviour is scoped to tree_single only.
    sub = _make_sub(total_input=12345, output=678)
    line1_no_lines,   _ = _two(sub, 136)             # lines=None
    line1_with_lines, _ = _two(sub, 136, lines=(5, 3))
    plain_no_lines   = strip_ansi(line1_no_lines)
    plain_with_lines = strip_ansi(line1_with_lines)
    assert not _has_lines_field(plain_no_lines)
    assert _has_lines_field(plain_with_lines)


def test_lines_field_reserves_width_not_omitted_when_no_data_tree_single() -> None:
    # tree_single: reserves the field's full column width — blank-padded on
    # both sides — rather than omitting the field and its leading '· '
    # separator, so cohort rows without data stay aligned under sibling
    # rows that do have data. The field (and its dot-separator) is present
    # in BOTH cases now; only the shed ladder (width pressure) drops it.
    sub = _make_sub(total_input=12345, output=678)
    line1_no_lines = _r.subagent_row(
        sub, 136, twoline=True, tree_single=True,
    ).split('\n')[0]                                                   # lines=None
    line1_with_lines = _r.subagent_row(
        sub, 136, twoline=True, tree_single=True, lines=(5, 3),
    ).split('\n')[0]
    plain_no_lines   = strip_ansi(line1_no_lines)
    plain_with_lines = strip_ansi(line1_with_lines)
    assert _has_lines_field(plain_no_lines)
    assert _has_lines_field(plain_with_lines)
    # Same number of dot-separated cluster segments either way — the field
    # is blank-padded, not dropped, so the segment count doesn't change.
    dots_no_lines   = plain_no_lines[plain_no_lines.index('·'):].count('· ')
    dots_with_lines = plain_with_lines[plain_with_lines.index('·'):].count('· ')
    assert dots_no_lines == dots_with_lines
    # And the row's total visible width is identical either way.
    assert _visible_width(line1_no_lines) == _visible_width(line1_with_lines)


def test_lines_field_cluster_width_identical_idle_vs_populated() -> None:
    # The cluster's fixed-width blank keeps total rendered width identical
    # between an idle row (lines=None) and a populated one (lines=(1234, 567))
    # at the same box width.
    sub = _make_sub(total_input=12345, output=678)
    line1_idle, _ = _two(sub, 136, lines=None)
    line1_full, _ = _two(sub, 136, lines=(1234, 567))
    assert _visible_width(line1_idle) == _visible_width(line1_full) == 136


def test_shed_order_lines_and_tok_protected_together() -> None:
    # Inverted Decision 10: lines + tok form one protected unit and are
    # never shed, together or independently, at any width in this sweep.
    sub = _make_sub(agent_type='general-purpose', description='x' * 80,
                    total_input=12345, output=678)
    tok = fmt_tok(sub.total_input)
    seen = set()
    for w in range(30, 90):
        line1, _ = _two(sub, w, lines=(1234, 567))
        plain = strip_ansi(line1)
        state = (_has_lines_field(plain), tok in plain)
        assert state == (True, True), f'width={w}: protected lines/tok shed {state}'
        seen.add(state)
    assert seen == {(True, True)}


def test_tok_field_has_no_percent_suffix() -> None:
    # The `(N.N%)` session-share suffix has been removed from the subagent
    # row's token field in every rendering mode (Change: "Remove the (N.N%)
    # percentage-of-session-tokens suffix").
    big   = _make_sub(agent_type='big', total_input=750_000, output=0, model='sonnet')
    small = _make_sub(agent_type='small', total_input=350_000, output=0, model='haiku')
    si    = 1_500_000
    line_big   = _r.subagent_row(big, 160, twoline=True, session_inout=si, tree_single=True,
                                  tree_desc_col=30)
    line_small = _r.subagent_row(small, 160, twoline=True, session_inout=si, tree_single=True,
                                  tree_desc_col=30)
    plain_big   = strip_ansi(line_big)
    plain_small = strip_ansi(line_small)
    assert '%' not in plain_big and '(' not in plain_big
    assert '%' not in plain_small and '(' not in plain_small
    assert fmt_tok_fixed(big.total_input) in plain_big
    assert fmt_tok_fixed(small.total_input) in plain_small


def test_fmt_tok_fixed_three_sig_figs() -> None:
    # Change 2: fmt_tok_fixed always renders 3 significant figures, so a
    # single-digit mantissa gets 2 decimals ('7.52M') and a 2-digit mantissa
    # gets 1 ('56.8K') — both 5 chars wide once the unit suffix lands.
    assert fmt_tok_fixed(7_520_000) == '7.52M'
    assert fmt_tok_fixed(3_500_000) == '3.50M'
    assert fmt_tok_fixed(56_800) == '56.8K'
    assert fmt_tok_fixed(121) == '121'
    assert _visible_width(fmt_tok_fixed(7_520_000)) == _visible_width(fmt_tok_fixed(3_500_000))


def test_fmt_tok_fixed_not_used_by_session_level_row() -> None:
    # The session-level input/cache/output row and day totals keep `fmt_tok`'s
    # original 1-decimal behaviour — `fmt_tok_fixed` is subagent-row-only.
    assert fmt_tok(7_520_000) == '7.5M'
    assert fmt_tok(7_520_000) != fmt_tok_fixed(7_520_000)


def test_lines_field_sheds_read_and_changed_independently() -> None:
    # Change 3: a subagent that only wrote (read == 0) blanks just the read
    # side, not the whole field — and vice versa for a read-only subagent.
    sub = _make_sub(total_input=12345, output=678)
    line_read_only, _    = _two(sub, 136, lines=(1234, 0))
    line_changed_only, _ = _two(sub, 136, lines=(0, 567))
    plain_read    = strip_ansi(line_read_only)
    plain_changed = strip_ansi(line_changed_only)
    assert fmt_tok_fixed(1234) in plain_read and fmt_tok_fixed(567) not in plain_read
    assert fmt_tok_fixed(567) in plain_changed and fmt_tok_fixed(1234) not in plain_changed
    # Blanking one side must not shift the row's total width.
    line_both, _ = _two(sub, 136, lines=(1234, 567))
    assert _visible_width(line_read_only) == _visible_width(line_changed_only) == _visible_width(line_both)


def test_header_labels_anchor_over_measured_columns() -> None:
    # Change 5: the SUBAGENTS section header's 'name'/'loc read / written'/
    # 'model'/'current activity' labels are derived from the SAME anchors
    # (desc_col/stats_col/activity_col + subagent_cluster_field_offsets) the
    # data rows use — never a hardcoded guess.
    from yas.render.metrics import subagent_cluster_field_offsets, subagent_cluster_width
    root = _make_tree_sub('agent-a', agent_type='spec-implementer')
    cells = [(root, '', 0)]
    model_w  = layout.tree_model_width(cells)
    lines_w  = layout.tree_lines_width(cells, {})
    cluster_w = subagent_cluster_width(lines_w)
    desc_col, stats_col, activity_col = layout.tree_columns(cells, 200, cluster_full_w=cluster_w, model_w=model_w)
    _tok_off, lines_off = subagent_cluster_field_offsets(lines_w)
    # The label anchors layout.py computes must land inside the row's own
    # measured columns, not past the activity column. Model now anchors in
    # the front field (ahead of desc_col), so it's checked separately below.
    assert 3 + desc_col < 3 + stats_col + _tok_off < 3 + stats_col + lines_off < 3 + activity_col
    model_col = max(0, desc_col - 1 - model_w) if model_w else desc_col
    assert 0 <= 3 + model_col < 3 + desc_col


def test_tree_lines_width_measures_cohort_max() -> None:
    # layout.tree_lines_width returns the widest fmt_tok string any cohort
    # row's read/changed count actually needs, not a hardcoded ceiling — a
    # cohort of small counts should measure narrow.
    a = _make_tree_sub('agent-a')
    a.jsonl_path = 'a.jsonl'
    b = _make_tree_sub('agent-b', parent_id='a')
    b.jsonl_path = 'b.jsonl'
    cells = [(a, '', 0), (b, '', 0)]
    per_agent = {a.jsonl_path: (50, 194), b.jsonl_path: (3, 0)}
    assert layout.tree_lines_width(cells, per_agent) == len(fmt_tok(194))  # '194' -> 3
    # A cohort with no lines data at all falls back to 1 (matches the blank
    # field's own minimum), not 0 or an error.
    assert layout.tree_lines_width(cells, {}) == 1


def test_tree_lines_w_tightens_gap_vs_hardcoded_five() -> None:
    # Passing the cohort's measured width (narrower than fmt_tok_fixed's
    # 5-char ceiling) shrinks the rjust padding reserved before the read
    # digits; the default (no tree_lines_w) still falls back to the safe
    # 5-char reservation. Compare the read segment's own rjust'd text
    # (immediately before the '/' separator) directly, rather than its
    # absolute column, since the cluster's overall row position can itself
    # shift with the cluster's total width (right-alignment fallback) —
    # not what this test is about.
    from yas.render.metrics import fmt_lines_pair

    sub = _make_tree_sub('agent-a')
    sub.jsonl_path = 'a.jsonl'
    line_default = strip_ansi(_r.subagent_row(
        sub, 140, twoline=True, tree_single=True, lines=(50, 194),
    ).split('\n')[0])
    measured_w = layout.tree_lines_width([(sub, '', 0)], {sub.jsonl_path: (50, 194)})
    line_measured = strip_ansi(_r.subagent_row(
        sub, 140, twoline=True, tree_single=True, lines=(50, 194),
        tree_lines_w=measured_w,
    ).split('\n')[0])
    read_s_default,  _ = fmt_lines_pair(50, 194, width=5, fixed=True)
    read_s_measured, _ = fmt_lines_pair(50, 194, width=measured_w, fixed=True)
    assert f'{read_s_default} /' in line_default
    assert f'{read_s_measured} /' in line_measured
    # measured_w is 3 (the wider of '50' and '194'), narrower than the
    # unmeasured default's 5-char fallback reservation.
    assert len(read_s_measured) < len(read_s_default)
    assert measured_w == 3


def test_tree_lines_w_alignment_holds_across_mixed_digit_widths() -> None:
    # The whole point of measuring the cohort width instead of hardcoding it:
    # a row with a 1-digit count and a row with a 3-digit count still start
    # their numbers at the SAME absolute column when given the same
    # cohort-measured tree_lines_w.
    short = _make_tree_sub('agent-a')
    short.jsonl_path = 'short.jsonl'
    long  = _make_tree_sub('agent-b', parent_id='a')
    long.jsonl_path = 'long.jsonl'
    cells = [(short, '', 0), (long, '', 0)]
    per_agent = {short.jsonl_path: (5, 0), long.jsonl_path: (500, 12)}
    w = layout.tree_lines_width(cells, per_agent)
    si = 1_000_000

    def read_col(sub: RunningSubagent, lines: tuple) -> int:
        line1 = strip_ansi(_r.subagent_row(
            sub, 140, twoline=True, session_inout=si, tree_single=True,
            lines=lines, tree_lines_w=w,
        ).split('\n')[0])
        # The read segment has fixed width `w` (rjust), ending right before
        # the '/' separator — subtracting `w` from the separator's column
        # gives the segment's (digit-count-invariant) start column.
        return line1.index('/') - w

    assert read_col(short, (5, 0)) == read_col(long, (500, 12))


def test_narrow_width_no_lines_matches_pre_change_output() -> None:
    # A narrow width that already sheds fields today renders byte-identically
    # to the pre-change output for callers that don't pass `lines` (zero
    # regression for existing callers).
    sub = _make_sub(agent_type='general-purpose', description='x' * 80,
                    total_input=12345, output=678)
    for w in (30, 45, 60):
        line1_default, _ = _two(sub, w)
        line1_explicit_none, _ = _two(sub, w, lines=None)
        assert line1_default == line1_explicit_none


def test_lines_field_uses_the_log_column_grey() -> None:
    # The loc read/changed values render in the same grey as the activity/log
    # column at the end of the row (CTX_DIM), not bright white.
    sub  = _make_sub(last_activity=('text', 'ran the gates', {}))
    line = _r.subagent_row(sub, 156, twoline=True, tree_single=True,
                           tree_prefix='├ ', tree_desc_col=40,
                           tree_activity_col=110, lines=(1200, 34)).split('\n')[0]

    assert f'{_r.CTX_DIM}1.20K' in line
    assert _r.white_brt not in line
    # Same constant the log column paints with.
    assert f'{_r.CTX_DIM}{GLYPH_REPLYING} ran the gates' in line


def test_lines_field_grey_composes_with_the_finished_strikethrough() -> None:
    # The lines field is CTX_DIM in BOTH run states — that alone predates the
    # strikethrough feature and asserting it on the done row only wouldn't
    # detect a regression (the finished path was already CTX_DIM before
    # strikethrough existed). What's new is that strike layers on top of the
    # SAME colour rather than the field going conditionally-coloured again;
    # asserting both branches together is what makes a regression back to
    # `d if is_done else white_brt`-style conditional colouring fail here.
    done = _make_done_sub()
    live = _make_sub()
    kw   = dict(twoline=True, tree_single=True, tree_prefix='├ ',
                tree_desc_col=40, lines=(1200, 34))

    done_line = _r.subagent_row(done, 156, **kw).split('\n')[0]
    live_line = _r.subagent_row(live, 156, **kw).split('\n')[0]

    # Colour opens, strike opens and closes inside it, then the row's reset —
    # no bleed — and the colour codes are zero-width either way.
    assert f'{_r.CTX_DIM}{STRIKE}1.20K{UNSTRIKE}' in done_line
    # The live row carries the SAME grey with no strike at all — if the
    # colour ever regressed to being conditional on run state again, this
    # branch would go back to white_brt and this assertion would catch it.
    assert f'{_r.CTX_DIM}1.20K' in live_line
    assert STRIKE not in live_line and UNSTRIKE not in live_line
    assert _r.white_brt not in live_line
    assert _visible_width(done_line) == _visible_width(live_line) == 156


# L. Self-scoping: no rollup across the tree ----------------------------------

def test_self_scoped_lines_no_rollup_between_parent_and_child() -> None:
    # Parent and child rows each render their OWN (read, changed) figures —
    # subagent_row never sums across the tree.
    parent = _make_sub(agent_type='parent-agent', total_input=12345, output=678)
    child  = _make_sub(agent_type='child-agent', total_input=12345, output=678)
    parent_line, _ = _two(parent, 136, lines=(100, 20))
    child_line, _  = _two(child, 136, lines=(500, 300))
    p_plain = strip_ansi(parent_line)
    c_plain = strip_ansi(child_line)
    assert fmt_tok(100) in p_plain and fmt_tok(20) in p_plain
    assert fmt_tok(500) in c_plain and fmt_tok(300) in c_plain
    # parent's row must not carry the child's figures (no accidental rollup)
    assert fmt_tok(500) not in p_plain
    assert fmt_tok(300) not in p_plain
    # ...and vice versa
    assert fmt_tok(100) not in c_plain
    assert fmt_tok(20) not in c_plain


def test_eviction_drops_oldest_completion_first_across_states() -> None:
    now = time.time()
    subs = [
        _rs('old-fail',   status='failed',    end_ts=now - 90),
        _rs('mid-killed', status='killed',    end_ts=now - 60),
        _rs('new-done',   status='completed', end_ts=now - 10),
        _rs('run-1',      status='running'),
        _rs('run-2',      status='running'),
    ]
    out = layout.select_visible_cohort(subs, cap=4, now=now)
    ids = {s.agent_id for s in out}
    assert 'old-fail' not in ids           # oldest completion evicted first
    assert 'run-1' in ids and 'run-2' in ids  # running rows never displaced


def test_flat_row_name_and_description_are_italic() -> None:
    # Flat (non-tree) twoline row: both the agent name (type_text) and the
    # description are wrapped in ITALIC ... RESET.
    sub = _make_sub(agent_type='general-purpose', description='Draft claude-light Theme literal')
    line1, _ = _two(sub, 136)
    assert f'{ITALIC}general-purpose' in line1
    assert f'{ITALIC}Draft claude-light Theme literal' in line1


def test_tree_single_name_and_description_are_italic() -> None:
    # tree_single row: same italic wrap on name and description.
    sub = _make_sub(agent_type='spec-implementer', description='Implement task 4')
    line1 = _r.subagent_row(sub, 136, twoline=True, tree_single=True).split('\n')[0]
    assert f'{ITALIC}spec-implementer' in line1
    assert f'{ITALIC}Implement task 4' in line1


def test_tree_single_depth0_name_is_bold_not_italic() -> None:
    # Top-level agents (tree_depth 0 — direct children of the implicit main
    # thread) render the agent name BOLD instead of ITALIC.
    sub = _make_sub(agent_type='spec-implementer', description='Sidechain work')
    line1 = _r.subagent_row(
        sub, 156, twoline=True, tree_single=True, tree_prefix='├── ', tree_depth=0,
    ).split('\n')[0]
    assert f'{BOLD}spec-implementer' in line1
    assert f'{ITALIC}spec-implementer' not in line1


def test_tree_single_depth1_plus_name_is_regular() -> None:
    # Descendants of a top-level agent (tree_depth 1+) render REGULAR — no
    # BOLD, no ITALIC — but the same colour (self.SKILLS) as depth 0, so
    # bold-vs-regular is the only remaining visual distinction by depth.
    sub = _make_sub(agent_type='general-purpose', description='Sidechain section')
    line1 = _r.subagent_row(
        sub, 156, twoline=True, tree_single=True, tree_prefix='├── ', tree_depth=1,
    ).split('\n')[0]
    assert f'{ITALIC}general-purpose' not in line1
    assert f'{BOLD}general-purpose' not in line1
    assert f'{_r.SKILLS}general-purpose' in line1


def test_tree_single_depth0_and_depth1_share_colour_only_bold_differs() -> None:
    # depth 0 and depth 1+ names share the exact same colour (self.SKILLS
    # while running) — bold-vs-regular is the ONLY visual distinction left
    # between a top-level agent's name and its descendants'.
    root = _make_sub(agent_type='spec-implementer', description='top-level work')
    kid  = _make_sub(agent_type='general-purpose', description='child work')
    line_root = _r.subagent_row(
        root, 156, twoline=True, tree_single=True, tree_prefix='├── ', tree_depth=0,
    ).split('\n')[0]
    line_kid = _r.subagent_row(
        kid, 156, twoline=True, tree_single=True, tree_prefix='├── ', tree_depth=1,
    ).split('\n')[0]
    assert f'{_r.SKILLS}{BOLD}spec-implementer' in line_root
    assert f'{_r.SKILLS}general-purpose' in line_kid
    assert f'{_r.SKILLS}{ITALIC}general-purpose' not in line_kid
    assert f'{_r.SKILLS}{BOLD}general-purpose' not in line_kid


def test_tree_single_no_tree_depth_stays_italic() -> None:
    # A tree row rendered without an explicit tree_depth (the default,
    # None) falls back to ITALIC rather than being mistaken for depth 0.
    sub = _make_sub(agent_type='fork', description='grandchild work')
    line1 = _r.subagent_row(
        sub, 156, twoline=True, tree_single=True, tree_prefix=' └─ ',
    ).split('\n')[0]
    assert f'{ITALIC}fork' in line1
    assert f'{BOLD}fork' not in line1


def test_one_line_collapse_name_is_italic() -> None:
    # One-line collapse form: only the name (type_text) is present (no
    # separate description field), so only it needs the italic wrap.
    sub = _make_sub(agent_type='general-purpose')
    line = _one(sub, 96)
    assert f'{ITALIC}general-purpose' in line


# M. Finished rows: strikethrough across every text field ---------------------

_STRIKE_SPAN_RE = re.compile(re.escape(STRIKE) + '(.*?)' + re.escape(UNSTRIKE), re.DOTALL)

# Nerd Font PUA, box drawing/elbows, and the marker/separator glyphs — none of
# these may ever fall inside an SGR 9 span (a rule drawn through a glyph or a
# border renders as a mangled cell).
_NEVER_STRUCK = '│┬┴├└─·✓✗↺'


def _struck_spans(line: str) -> list[str]:
    return _STRIKE_SPAN_RE.findall(line)


def _is_pua(ch: str) -> bool:
    cp = ord(ch)
    return 0xE000 <= cp <= 0xF8FF or 0xF0000 <= cp <= 0xFFFFD


def _done_tree_row(**kw) -> str:
    sub = _make_done_sub(
        agent_type    = 'verifier',
        description   = 'run the gates',
        last_activity = ('text', 'wrote the report', {}),
        total_input   = 12345,
        **kw,
    )
    out = _r.subagent_row(sub, 156, twoline=True, tree_single=True,
                          tree_prefix='├ ', tree_desc_col=40,
                          tree_activity_col=110, lines=(1200, 34))
    return out.split('\n')[0]


def test_done_tree_row_strikes_every_text_field() -> None:
    line1 = _done_tree_row()

    struck = ''.join(_struck_spans(line1))

    for field in ('1:30', 'verifier', 'sonnet', fmt_tok_fixed(12345),
                  '1.20K', '34', 'run the gates', 'wrote the report'):
        assert field in struck, f'{field!r} not struck through'


def test_done_tree_row_leaves_glyphs_borders_and_padding_unstruck() -> None:
    line1 = _done_tree_row()

    spans = _struck_spans(line1)

    assert spans
    for span in spans:
        assert span, 'empty strikethrough span'
        assert span == span.strip(' '), f'padding struck through: {span!r}'
        assert not any(_is_pua(ch) for ch in span), f'PUA glyph struck: {span!r}'
        assert not any(ch in _NEVER_STRUCK for ch in span), f'glyph/border struck: {span!r}'


def test_done_row_strikethrough_is_always_terminated() -> None:
    line1 = _done_tree_row()

    assert line1.count(STRIKE) == line1.count(UNSTRIKE)
    # No dangling SGR 9 past the last terminator — nothing can bleed into the
    # next cell or the row below.
    assert line1.rindex(UNSTRIKE) > line1.rindex(STRIKE)


def test_strike_activity_never_strikes_a_leading_pua_glyph_without_a_space() -> None:
    # `_strike_activity` normally splits on the glyph's trailing space, but a
    # no-space activity (e.g. the glyph alone, or a glyph glued straight to
    # text with no separator) must still leave the leading PUA glyph plain —
    # falling back to striking the WHOLE string would rule through the icon.
    glyph = GLYPH_REPLYING
    struck = renderer_mod._strike_activity(f'{glyph}nospace')

    assert struck.startswith(glyph)
    assert not struck.startswith(f'{STRIKE}{glyph}')
    assert f'{STRIKE}nospace{UNSTRIKE}' in struck

    # Plain text with no glyph at all still gets struck in full.
    assert renderer_mod._strike_activity('plaintext') == renderer_mod.strike('plaintext')


def test_strikethrough_is_absent_from_a_running_row() -> None:
    sub  = _make_sub()
    line = _r.subagent_row(sub, 156, twoline=True, tree_single=True,
                           tree_prefix='├ ', tree_desc_col=40)

    assert STRIKE not in line


@pytest.mark.parametrize('content_width', (96, 136, 156))
def test_done_and_running_rows_have_identical_display_width(content_width: int) -> None:
    kw   = dict(agent_type='verifier', description='run the gates', total_input=12345)
    done = _make_done_sub(**kw)
    live = _make_sub(**kw)

    tree_done = _r.subagent_row(done, content_width, twoline=True, tree_single=True,
                                tree_prefix='├ ', tree_desc_col=40).split('\n')[0]
    tree_live = _r.subagent_row(live, content_width, twoline=True, tree_single=True,
                                tree_prefix='├ ', tree_desc_col=40).split('\n')[0]
    one_done  = _one(done, content_width)
    one_live  = _one(live, content_width)

    # SGR 9/29 are zero-width: a finished row occupies exactly the same
    # columns as a running one, and the escapes leave no trace in plain text.
    assert _visible_width(tree_done) == _visible_width(tree_live) == content_width
    assert _visible_width(one_done) == _visible_width(one_live) == content_width
    assert STRIKE not in strip_ansi(tree_done) and UNSTRIKE not in strip_ansi(tree_done)
