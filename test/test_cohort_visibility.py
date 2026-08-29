'''Tests for RunningSubagents.visible() — cohort membership & retirement logic.

These tests build RunningSubagent objects directly (no disk I/O) so they are
fast and deterministic.  The mtime and end_ts fields are set explicitly to
simulate various age/done combinations.

One test (test_streaming_duplicate_id_end_turn_reaches_done_state) is an
end-to-end exception: it parses a real fixture transcript (plus a session-level
<task-notification> record — the only authoritative completion signal now
that the terminal-text/StructuredOutput heuristics are deleted) through
from_session so the Done-state (end_ts > 0) it asserts is produced by the
production notification-scanning path, not hand-set.

Another end-to-end exception (test_tree_states_scenario_shows_four_states)
renders ops/demo.py's 'subagent-tree-wide-states' scenario through the real
statusline subprocess. That scenario carries exactly 4 flat subagents, one per
lifecycle state (completed/killed/stopped/resumed) — this guard exists so a
future edit that trims/reorders those rows (or changes the cap/trim logic)
fails loudly instead of silently dropping a marker.
'''
import datetime
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

from yas.constants import (
    GLYPH_SUBAGENT_DONE,
    GLYPH_SUBAGENT_ENDED,
    GLYPH_SUBAGENT_RESUME,
    SUBAGENT_DISPLAY_CAP,
    SUBAGENT_RETENTION_SECONDS,
    subagent_marker_glyph,
)
from yas.info.subagents import RunningSubagent, RunningSubagents

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'ops'))


NOW = 1_000_000.0  # arbitrary fixed epoch

LIVENESS  = RunningSubagents.LIVENESS_WINDOW_SECONDS     # 30
GRACE     = RunningSubagents.COHORT_GRACE_SECONDS         # 120
JANITOR   = RunningSubagents.JANITOR_HORIZON_SECONDS      # 60
ABANDONED = RunningSubagents.ABANDONED_HORIZON_SECONDS    # 1800
LINGER    = RunningSubagents.FINISHED_LINGER_SECONDS      # 120


def _sub(
    *,
    first_timestamp: float = NOW - 10.0,
    mtime: float           = NOW - 5.0,
    end_ts: float          = 0.0,
    description: str       = 'test-agent',
    agent_id: str          = '',
    parent_id: str         = '',
) -> RunningSubagent:
    return RunningSubagent(
        agent_type      = 'Explore',
        description     = description,
        billed_in       = 0,
        output          = 0,
        first_timestamp = first_timestamp,
        mtime           = mtime,
        end_ts          = end_ts,
        agent_id        = agent_id,
        parent_id       = parent_id,
    )


def _cohort(*subs: RunningSubagent) -> RunningSubagents:
    return RunningSubagents(subagents=list(subs))


# ---------------------------------------------------------------------------
# Turn-scoped membership (last_prompt_ts provided)
# ---------------------------------------------------------------------------

def test_agent_this_turn_included() -> None:
    '''Agent started after last_prompt_ts is in the cohort.'''
    last_prompt_ts = NOW - 30.0
    # Agent started 10 s ago (after the prompt), wrote 5 s ago — still active
    sub = _sub(first_timestamp=NOW - 10.0, mtime=NOW - 5.0)
    result = _cohort(sub).visible(NOW, last_prompt_ts)
    assert sub in result


def test_pre_turn_still_writing_kept() -> None:
    '''Agent started before the prompt but still writing (within liveness window) is kept.'''
    last_prompt_ts = NOW - 10.0
    sub = _sub(first_timestamp=NOW - 60.0, mtime=NOW - (LIVENESS - 5))
    result = _cohort(sub).visible(NOW, last_prompt_ts)
    assert sub in result


def test_old_finished_agent_excluded() -> None:
    '''Agent started before the prompt and not writing recently is excluded.'''
    last_prompt_ts = NOW - 10.0
    sub = _sub(first_timestamp=NOW - 60.0, mtime=NOW - (LIVENESS + 5), end_ts=NOW - 50.0)
    result = _cohort(sub).visible(NOW, last_prompt_ts)
    assert sub not in result


def test_running_agent_always_shown() -> None:
    '''A still-running agent (end_ts == 0) actively writing is kept regardless.'''
    last_prompt_ts = NOW - 5.0
    sub = _sub(first_timestamp=NOW - 3.0, mtime=NOW - 2.0, end_ts=0.0)
    result = _cohort(sub).visible(NOW, last_prompt_ts)
    assert sub in result


class TestSupervisingParentVisibility:
    '''A parent blocked waiting on children writes nothing but is still alive.'''

    def test_silent_parent_with_live_descendant_stays_visible(self) -> None:
        # setup: parent last wrote well outside the liveness window, its child 2 s ago
        last_prompt_ts = NOW - 10.0
        parent = _sub(
            first_timestamp = NOW - 600.0,
            mtime           = NOW - (LIVENESS + 120),
            agent_id        = 'agent-parent',
        )
        child = _sub(
            first_timestamp = NOW - 300.0,
            mtime           = NOW - 2.0,
            agent_id        = 'agent-child',
            parent_id       = 'parent',
        )

        # run
        result = _cohort(parent, child).visible(NOW, last_prompt_ts)

        # expected
        expected = [parent, child]

        # assert
        assert result == expected

    def test_silent_grandparent_kept_through_the_whole_chain(self) -> None:
        # setup
        last_prompt_ts = NOW - 10.0
        silent_mtime = NOW - (LIVENESS + 120)
        gran = _sub(first_timestamp=NOW - 900.0, mtime=silent_mtime, agent_id='agent-gran')
        parent = _sub(
            first_timestamp = NOW - 600.0,
            mtime           = silent_mtime,
            agent_id        = 'agent-parent',
            parent_id       = 'gran',
        )
        child = _sub(
            first_timestamp = NOW - 300.0,
            mtime           = NOW - 2.0,
            agent_id        = 'agent-child',
            parent_id       = 'parent',
        )

        # run
        result = _cohort(gran, parent, child).visible(NOW, last_prompt_ts)

        # expected
        expected = [gran, parent, child]

        # assert
        assert result == expected

    def test_silent_parent_dropped_when_descendant_also_silent(self) -> None:
        # setup: nothing in the branch is writing, so the normal windows apply
        last_prompt_ts = NOW - 10.0
        silent_mtime = NOW - (LIVENESS + 120)
        parent = _sub(
            first_timestamp = NOW - 600.0,
            mtime           = silent_mtime,
            end_ts          = NOW - 300.0,
            agent_id        = 'agent-parent',
        )
        child = _sub(
            first_timestamp = NOW - 300.0,
            mtime           = silent_mtime,
            end_ts          = NOW - 200.0,
            agent_id        = 'agent-child',
            parent_id       = 'parent',
        )

        # run
        result = _cohort(parent, child).visible(NOW, last_prompt_ts)

        # expected
        expected: list[RunningSubagent] = []

        # assert
        assert result == expected


# ---------------------------------------------------------------------------
# Cohort retirement
# ---------------------------------------------------------------------------

def test_all_done_within_grace_returns_candidates() -> None:
    '''All-Done cohort within the grace window is still visible.'''
    last_prompt_ts = NOW - 30.0
    sub = _sub(first_timestamp=NOW - 25.0, mtime=NOW - 25.0, end_ts=NOW - (GRACE - 5))
    result = _cohort(sub).visible(NOW, last_prompt_ts)
    assert sub in result


def test_clean_retire_past_grace() -> None:
    '''All-Done cohort retires once the last end_ts exceeds the grace window.'''
    last_prompt_ts = NOW - 30.0
    sub = _sub(first_timestamp=NOW - 25.0, mtime=NOW - 25.0, end_ts=NOW - (GRACE + 1))
    result = _cohort(sub).visible(NOW, last_prompt_ts)
    assert result == []


def test_mixed_cohort_not_retired_by_grace() -> None:
    '''A cohort with at least one running agent is not subject to the grace-window retire.'''
    last_prompt_ts = NOW - 30.0
    done    = _sub(first_timestamp=NOW - 25.0, mtime=NOW - 25.0, end_ts=NOW - (GRACE + 5), description='done-agent')
    running = _sub(first_timestamp=NOW - 20.0, mtime=NOW - 2.0,  end_ts=0.0,               description='running-agent')
    result  = _cohort(done, running).visible(NOW, last_prompt_ts)
    assert running in result


def test_running_agent_not_swept_at_60s() -> None:
    '''Regression: a still-running agent (end_ts == 0) that has simply gone
    transcript-silent for JANITOR_HORIZON_SECONDS (e.g. mid long tool call or
    extended thinking) must NOT be swept -- silence alone is not evidence of
    abandonment when there is no terminal status yet. This was the confirmed
    false-negative: a genuinely alive subagent vanished from the tree after
    60-75 s of quiet, then reappeared on its next transcript write.
    '''
    last_prompt_ts = NOW - 5.0
    # Agent started this turn (first_timestamp >= last_prompt_ts) -- unambiguously
    # spawned this turn, not a stale candidate -- but silent for 75 s.
    sub = _sub(first_timestamp=NOW - 3.0, mtime=NOW - 75.0, end_ts=0.0)
    assert JANITOR < 75.0 < ABANDONED
    result = _cohort(sub).visible(NOW, last_prompt_ts)
    assert sub in result


def test_running_agent_eventually_swept_when_truly_abandoned() -> None:
    '''A still-running agent (end_ts == 0) whose transcript has been silent far
    past any reasonable liveness window (e.g. the session crashed) is still
    eventually swept -- the janitor cleanup for orphaned agent-*.jsonl entries
    is not removed, only its threshold for still-running members is widened.
    '''
    last_prompt_ts = NOW - 5.0
    sub = _sub(first_timestamp=NOW - 3.0, mtime=NOW - (ABANDONED + 1), end_ts=0.0)
    result = _cohort(sub).visible(NOW, last_prompt_ts)
    assert result == []


def test_dirty_cohort_mixed_horizons() -> None:
    '''A dirty cohort with one Done-but-not-terminal member silent past
    JANITOR_HORIZON_SECONDS and one still-running member silent past
    ABANDONED_HORIZON_SECONDS is swept only once BOTH thresholds are crossed.
    '''
    last_prompt_ts = NOW - 5.0
    done_ish = _sub(
        first_timestamp=NOW - 4.0, mtime=NOW - (JANITOR + 1), end_ts=NOW - (JANITOR + 1),
        description='done-ish',
    )
    running = _sub(
        first_timestamp=NOW - 3.0, mtime=NOW - (JANITOR + 5), end_ts=0.0,
        description='running',
    )
    # done_ish is past its own horizon but running is not past ABANDONED yet.
    result = _cohort(done_ish, running).visible(NOW, last_prompt_ts)
    assert running in result


def test_per_member_retirement_drops_only_long_dead_sibling() -> None:
    '''Regression: one still-live sibling must not keep a long-dead,
    never-notified cohort member visible forever. Each candidate retires
    independently once IT crosses its own horizon, not the cohort's `all()`.
    '''
    last_prompt_ts = NOW - 5.0
    long_dead = _sub(
        first_timestamp=NOW - 3.0, mtime=NOW - (ABANDONED + 1), end_ts=0.0,
        description='long-dead-no-notification',
    )
    live = _sub(
        first_timestamp=NOW - 3.0, mtime=NOW - 2.0, end_ts=0.0,
        description='live',
    )
    result = _cohort(long_dead, live).visible(NOW, last_prompt_ts)
    assert live in result
    assert long_dead not in result


def test_finished_member_still_visible_at_119s() -> None:
    """A finished member of a dirty cohort lingers for the full 2 minutes."""
    last_prompt_ts = NOW - 5.0
    finished = _sub(first_timestamp=NOW - 4.0, mtime=NOW - 119.0, end_ts=NOW - 119.0,
                    description='finished')
    live     = _sub(first_timestamp=NOW - 3.0, mtime=NOW - 2.0, end_ts=0.0,
                    description='live')

    result = _cohort(finished, live).visible(NOW, last_prompt_ts)

    assert finished in result


def test_finished_member_retired_at_121s() -> None:
    """One second past the linger window the finished member drops out."""
    last_prompt_ts = NOW - 5.0
    finished = _sub(first_timestamp=NOW - 4.0, mtime=NOW - 121.0, end_ts=NOW - 121.0,
                    description='finished')
    live     = _sub(first_timestamp=NOW - 3.0, mtime=NOW - 2.0, end_ts=0.0,
                    description='live')

    result = _cohort(finished, live).visible(NOW, last_prompt_ts)

    assert finished not in result
    assert live in result


def test_finished_linger_matches_layout_retention() -> None:
    """The info-layer linger must not retire a row before the layout's own
    retention horizon would — they are deliberately the same 120 s."""
    assert LINGER == SUBAGENT_RETENTION_SECONDS


def test_cohort_grace_matches_finished_linger() -> None:
    """COHORT_GRACE_SECONDS and FINISHED_LINGER_SECONDS are deliberately the
    same 120 s window. _retired() picks exactly one of the two per candidate
    (never both), so raising one does not compound with the other into a
    longer effective visibility window."""
    assert GRACE == LINGER


def test_all_done_cohort_visible_at_120s_not_240s() -> None:
    """Regression: an all-Done cohort must retire at COHORT_GRACE_SECONDS
    (120 s), not at COHORT_GRACE_SECONDS + FINISHED_LINGER_SECONDS (240 s).
    The two horizons are a select (all_done ? GRACE : LINGER), not a sum."""
    last_prompt_ts = NOW - 130.0
    sub = _sub(first_timestamp=NOW - 125.0, mtime=NOW - 125.0, end_ts=NOW - (GRACE - 1))
    assert _cohort(sub).visible(NOW, last_prompt_ts) == [sub]

    long_gone = _sub(first_timestamp=NOW - 125.0, mtime=NOW - 125.0, end_ts=NOW - (GRACE + LINGER - 1))
    assert _cohort(long_gone).visible(NOW, last_prompt_ts) == []


def test_janitor_not_triggered_if_one_member_wrote_recently() -> None:
    '''Dirty cohort is kept if at least one transcript was recently updated.'''
    last_prompt_ts = NOW - 30.0
    silent  = _sub(first_timestamp=NOW - 25.0, mtime=NOW - (JANITOR + 5), end_ts=0.0, description='silent')
    active  = _sub(first_timestamp=NOW - 20.0, mtime=NOW - 2.0,           end_ts=0.0, description='active')
    result  = _cohort(silent, active).visible(NOW, last_prompt_ts)
    assert active in result
    assert silent in result


# ---------------------------------------------------------------------------
# No-marker fallback (last_prompt_ts is None)
# ---------------------------------------------------------------------------

def test_recency_fallback_includes_recent_agent() -> None:
    '''When no marker, an agent written within JANITOR_HORIZON_SECONDS is included.'''
    sub = _sub(mtime=NOW - (JANITOR - 5), end_ts=NOW - 10.0)
    result = _cohort(sub).visible(NOW, None)
    assert sub in result


def test_recency_fallback_excludes_old_done_agent() -> None:
    '''When no marker, an agent written more than 60 s ago and Done is excluded.'''
    sub = _sub(mtime=NOW - (JANITOR + 5), end_ts=NOW - (JANITOR + 5))
    result = _cohort(sub).visible(NOW, None)
    assert sub not in result


def test_recency_fallback_keeps_running_agent() -> None:
    '''When no marker, a still-running agent (end_ts == 0) with recent writes is included.'''
    # Still running, wrote within the janitor window
    sub = _sub(mtime=NOW - (JANITOR - 10), end_ts=0.0)
    result = _cohort(sub).visible(NOW, None)
    assert sub in result


def test_empty_subagents_returns_empty() -> None:
    '''An empty RunningSubagents always returns an empty list.'''
    assert _cohort().visible(NOW, NOW - 5.0) == []
    assert _cohort().visible(NOW, None) == []


# ---------------------------------------------------------------------------
# End-to-end: streaming duplicate-id end_turn must still reach Done state
# ---------------------------------------------------------------------------
#
# Regression for the hardened _parse_transcript: streaming writes the same
# assistant message.id several times — an early partial with stop_reason: null,
# then a final write with stop_reason: "end_turn".  The end_turn/end_ts capture
# must run BEFORE the message-id dedup guard, otherwise the final end_turn write
# on an already-seen id is skipped, end_ts stays 0, and the agent lingers
# looking ACTIVE instead of reaching the Done state.  A Done agent (end_ts > 0)
# is eligible for the dimmed Done treatment + 20 s clean-retire grace; an
# active one is not.

_SESSION_ID = 'sess-dup'
_PROJECT_DIR = '/home/user/myproject'
_PROJECT_SLUG = 'home-user-myproject'


def _streaming_partial_line(msg_id: str, *, timestamp: str) -> str:
    '''An early streaming partial: same id, stop_reason null, not yet done.'''
    d: dict = {
        'type': 'assistant',
        'timestamp': timestamp,
        'message': {
            'id': msg_id,
            'role': 'assistant',
            'model': 'claude-sonnet-4-6',
            'stop_reason': None,
            'usage': {
                'input_tokens': 10,
                'cache_creation_input_tokens': 0,
                'cache_read_input_tokens': 0,
                'output_tokens': 2,
            },
            'content': [{'type': 'text', 'text': 'partial'}],
        },
    }
    return json.dumps(d) + '\n'


def _end_turn_line(msg_id: str, *, timestamp: str) -> str:
    '''Final streaming write: SAME id as the partial, now stop_reason end_turn.'''
    d: dict = {
        'type': 'assistant',
        'timestamp': timestamp,
        'message': {
            'id': msg_id,
            'role': 'assistant',
            'model': 'claude-sonnet-4-6',
            'stop_reason': 'end_turn',
            'usage': {
                'input_tokens': 10,
                'cache_creation_input_tokens': 0,
                'cache_read_input_tokens': 0,
                'output_tokens': 5,
            },
            'content': [{'type': 'text', 'text': 'done'}],
        },
    }
    return json.dumps(d) + '\n'


def test_streaming_duplicate_id_end_turn_reaches_done_state(tmp_home: Path) -> None:
    '''A transcript whose final end_turn reuses an earlier streaming partial's
    message.id still reaches the Done state (end_ts > 0) and is therefore
    subject to the 20 s grace retire (dimmed Done), not treated as active.
    '''
    # Build a real fixture transcript with a duplicated message.id: a streaming
    # partial (stop_reason null) followed by the final end_turn (same id).
    sdir = (
        tmp_home / '.claude' / 'projects' / f'-{_PROJECT_SLUG}'
        / _SESSION_ID / 'subagents'
    )
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / 'agent-dup.meta.json').write_text(
        json.dumps({'agentType': 'Explore', 'description': 'find X'}),
    )
    jsonl = sdir / 'agent-dup.jsonl'
    jsonl.write_text(
        _streaming_partial_line('msg_same', timestamp='2026-05-22T17:50:00.000Z')
        + _end_turn_line('msg_same', timestamp='2026-05-22T17:50:30.000Z'),
    )
    # Authoritative completion signal: a <task-notification> in the top-level
    # session .jsonl, keyed by task-id == the agent-*.jsonl filename stem
    # (minus the "agent-" prefix).
    session_dir = tmp_home / '.claude' / 'projects' / f'-{_PROJECT_SLUG}'
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / f'{_SESSION_ID}.jsonl').write_text(json.dumps({
        'type': 'queue-operation',
        'operation': 'enqueue',
        'timestamp': '2026-05-22T17:50:30.000Z',
        'content': (
            '<task-notification>\n'
            '<task-id>dup</task-id>\n'
            '<tool-use-id>toolu_dup</tool-use-id>\n'
            '<status>completed</status>\n'
            '<summary>done</summary>\n'
            '</task-notification>'
        ),
    }) + '\n')

    # Keep the transcript's mtime at/behind the notification: a later write
    # would (correctly) invalidate the terminal signal as stale.
    notif_epoch = datetime.datetime(
        2026, 5, 22, 17, 50, 30, tzinfo=datetime.timezone.utc,
    ).timestamp()
    os.utime(jsonl, (notif_epoch, notif_epoch))

    parsed = RunningSubagents.from_session(_SESSION_ID, _PROJECT_DIR)
    assert len(parsed.subagents) == 1
    sub = parsed.subagents[0]

    # The end_turn on the already-seen id must NOT have been suppressed by dedup.
    assert sub.end_ts > 0, 'duplicate-id end_turn must still set end_ts (Done)'
    end_ts = sub.end_ts

    # Drive that real Done agent through visible(): because it IS Done, it is
    # governed by the COHORT_GRACE_SECONDS clean-retire window, not the
    # janitor sweep / abandoned-horizon that applies to active agents.

    # Within grace (just retired this turn): still visible (eligible for the
    # dimmed Done treatment).
    now_in_grace = end_ts + (GRACE - 1)
    cohort = RunningSubagents(
        subagents=[RunningSubagent(
            agent_type='Explore', description='find X', billed_in=sub.billed_in,
            output=sub.output, first_timestamp=sub.first_timestamp,
            mtime=now_in_grace, end_ts=end_ts,
        )],
    )
    last_prompt_ts = sub.first_timestamp - 1.0  # agent started this turn
    assert cohort.subagents[0] in cohort.visible(now_in_grace, last_prompt_ts)

    # Past the grace window: the all-Done cohort clean-retires (governed by
    # COHORT_GRACE_SECONDS, not the ABANDONED_HORIZON_SECONDS that would
    # apply to a still-running/end_ts==0 candidate).
    now_past_grace = end_ts + (GRACE + 1)
    assert cohort.visible(now_past_grace, last_prompt_ts) == []
    # Sanity: it retired strictly before the abandoned-horizon, proving it
    # was treated as Done (fast grace-window retire) rather than as an
    # active/still-running agent (which would survive far longer).
    assert (GRACE + 1) < ABANDONED


# ---------------------------------------------------------------------------
# Regression guard: the six-state tree-mode demo scenario must render every
# lifecycle marker. The scenario is pinned at exactly SUBAGENT_DISPLAY_CAP
# (root + 5 children); a stray extra row silently trims the oldest-mtime row
# off the bottom instead of raising, which is exactly the failure this test
# exists to catch.
# ---------------------------------------------------------------------------

def _find_tree_states_scenario():
    '''Locate the 'subagent-tree-wide-states' ScenarioConfig from ops/demo.py.'''
    import demo as ops_demo  # ops/demo.py, reached via the sys.path.insert above
    for cfg in ops_demo.SCENARIOS:
        if cfg.name == 'subagent-tree-wide-states':
            return ops_demo, cfg
    raise AssertionError("'subagent-tree-wide-states' scenario not found in ops/demo.py SCENARIOS")


def _render_tree_states_scenario(tmp_path: Path, cfg_override=None) -> str:
    '''Render the tree-states scenario (or an override copy of it) to plain text
    via the same hermetic path make demo/img uses, and return the raw output.'''
    import dataclasses
    import os

    ops_demo, cfg = _find_tree_states_scenario()
    if cfg_override is not None:
        cfg = dataclasses.replace(cfg, subagents=cfg_override)

    fixture = json.loads(ops_demo.FIXTURE_PATH.read_text())
    out_dir = tmp_path / 'out'
    out_dir.mkdir()
    session_id = fixture['session_id']
    with tempfile.TemporaryDirectory() as raw_tmp:
        home = Path(raw_tmp)
        ops_demo.build_synthetic_env(home, session_id)
        env = os.environ.copy()
        env['HOME'] = str(home)
        env['CLAUDE_CONFIG_DIR'] = str(home / '.claude')
        ops_demo.render_scenario(env, fixture, home, session_id, cfg, out_dir)
    return (out_dir / f'{cfg.name}.txt').read_text()


_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


# ============================================================================
# 6.6: Retirement tests — totals_only caching and the mispredict re-parse path
# ============================================================================

def test_conclusively_retired_agent_totals_only_feeds_inout(tmp_home: Path) -> None:
    """Task 6.6(a): A conclusively-retired agent built totals_only still contributes
    total_input/output correctly to session aggregates."""
    from test_running_subagents import (
        _subagents_dir,
        _write_agent,
    )
    from yas.info.parsecache import TranscriptCache

    session_id = 'sess-retire-a'
    subagents_dir = _subagents_dir(tmp_home)
    _, agent_jsonl = _write_agent(subagents_dir, 'agent-retire-a')

    # Build a transcript that will parse to known token counts
    lines = [
        json.dumps({
            'type': 'assistant',
            'timestamp': '2025-01-01T12:00:00.000Z',
            'message': {
                'id': 'msg-001',
                'model': 'claude-3.5-sonnet',
                'stop_reason': 'end_turn',
                'usage': {
                    'input_tokens': 100,
                    'cache_creation_input_tokens': 10,
                    'cache_read_input_tokens': 20,
                    'output_tokens': 50,
                },
                'content': [{'type': 'text', 'text': 'response'}]
            }
        }) + '\n',
    ]
    agent_jsonl.write_text(''.join(lines))

    # Set up a cache with old file mtime
    mtime = 1_900_000.0
    os.utime(agent_jsonl, (mtime, mtime))
    st = agent_jsonl.stat()

    cache = TranscriptCache(session_id)

    # Parse and cache
    from yas.info.subagents import parse_transcript
    parsed = parse_transcript(agent_jsonl, resume_after=0.0, totals_only=False)
    cache.put_parse(str(agent_jsonl), st, 0.0, parsed)

    # Verify the parse has the expected totals
    assert parsed[0] == 110, f"Expected billed_in=110, got {parsed[0]}"
    assert parsed[1] == 20, f"Expected cache_read_in=20, got {parsed[1]}"
    assert parsed[2] == 50, f"Expected output=50, got {parsed[2]}"

    # Mark as terminal
    cache.mark_terminal(str(agent_jsonl))
    cache.save()

    # Verify the cache reports terminal
    loaded_cache = TranscriptCache.load(session_id)
    assert loaded_cache.is_terminal(str(agent_jsonl), st)


def test_terminal_but_recent_agent_not_reduced(tmp_home: Path) -> None:
    """Task 6.6(b): An agent that is terminal but recent (end_ts too close to now)
    is NOT marked as conclusively-retired and gets full parse, not totals_only."""
    from yas.info.subagents import _conclusively_retired

    # Set up a recent end_ts
    now = 3_000_000.0
    # Agent ended only 10 seconds ago (within grace period)
    end_ts = now - 10.0
    mtime = now - 5.0
    status = 'completed'

    # Should NOT be conclusively retired (too recent)
    is_retired = _conclusively_retired(now, status, end_ts, mtime)
    assert not is_retired, "Recent terminal agent should not be conclusively retired"


def test_conclusively_retired_predicate_old_agent_old_mtime(tmp_home: Path) -> None:
    """An old agent with old mtime is conclusively retired."""
    from yas.info.subagents import _conclusively_retired, RunningSubagents

    now = 3_000_000.0
    # Agent ended very long ago
    end_ts = now - (RunningSubagents.FINISHED_LINGER_SECONDS + RunningSubagents.TERMINAL_SKEW_SECONDS + 1000)
    # Mtime very old too
    mtime = now - (RunningSubagents.ABANDONED_HORIZON_SECONDS + RunningSubagents.TERMINAL_SKEW_SECONDS + 1000)
    status = 'completed'

    is_retired = _conclusively_retired(now, status, end_ts, mtime)
    assert is_retired, "Old terminal agent with old mtime should be conclusively retired"


def test_conclusively_retired_agent_marked_totals_only_for_real(tmp_home: Path) -> None:
    """Task 6.6(c), part 1: a genuinely old, notification-completed agent trips
    the real _conclusively_retired predicate (no stub) and from_session parses
    it totals_only — blank model/last_activity, but real totals."""
    from yas.info.parsecache import TranscriptCache

    session_id = 'sess-mispredict'
    project_dir = _PROJECT_DIR
    sdir = (
        tmp_home / '.claude' / 'projects' / f'-{_PROJECT_SLUG}'
        / session_id / 'subagents'
    )
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / 'agent-mispredict.meta.json').write_text(
        json.dumps({'agentType': 'Explore', 'description': 'find X'}),
    )
    jsonl = sdir / 'agent-mispredict.jsonl'
    jsonl.write_text(json.dumps({
        'type': 'assistant',
        'timestamp': '2025-01-01T12:00:00.000Z',
        'message': {
            'id': 'msg-001',
            'model': 'claude-3.5-sonnet',
            'stop_reason': 'end_turn',
            'usage': {
                'input_tokens': 100,
                'cache_creation_input_tokens': 10,
                'cache_read_input_tokens': 20,
                'output_tokens': 50,
            },
            'content': [
                {'type': 'tool_use', 'name': 'TestTool', 'id': 'tooluse-1', 'input': {'arg': 'value'}}
            ]
        }
    }) + '\n')

    session_dir = tmp_home / '.claude' / 'projects' / f'-{_PROJECT_SLUG}'
    (session_dir / f'{session_id}.jsonl').write_text(json.dumps({
        'type': 'queue-operation',
        'operation': 'enqueue',
        'timestamp': '2025-01-01T12:00:30.000Z',
        'content': (
            '<task-notification>\n'
            '<task-id>mispredict</task-id>\n'
            '<tool-use-id>toolu_mispredict</tool-use-id>\n'
            '<status>completed</status>\n'
            '<summary>done</summary>\n'
            '</task-notification>'
        ),
    }) + '\n')

    # Keep the transcript's mtime at/behind the notification, same as the
    # notification-scanning fixture above, so the terminal signal isn't
    # invalidated as stale.
    notif_epoch = datetime.datetime(
        2025, 1, 1, 12, 0, 30, tzinfo=datetime.timezone.utc,
    ).timestamp()
    os.utime(jsonl, (notif_epoch, notif_epoch))

    # now is past both staleness thresholds _conclusively_retired requires
    # (real predicate — no stub).
    now = (
        notif_epoch
        + RunningSubagents.ABANDONED_HORIZON_SECONDS
        + RunningSubagents.TERMINAL_SKEW_SECONDS
        + 10.0
    )

    cache = TranscriptCache(session_id)
    cache.save()

    running = RunningSubagents.from_session(session_id, project_dir, now=now, cache=cache)

    assert len(running.subagents) == 1
    sub = running.subagents[0]
    assert sub.agent_id in running.totals_only_ids, (
        'a genuinely old, notification-completed agent should trip the real '
        '_conclusively_retired predicate and be parsed totals_only'
    )
    assert sub.model == ''
    assert sub.last_activity == ('', '', {})
    assert sub.billed_in == 110
    assert sub.cache_read_in == 20
    assert sub.output == 50


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Production bug (claude/yas/info/subagents.py): _conclusively_retired's "
        "end_ts staleness requirement is max(FINISHED_LINGER_SECONDS, "
        "COHORT_GRACE_SECONDS) + TERMINAL_SKEW_SECONDS = 125s, which is always "
        "*stricter* than visible()'s own retirement horizon for the same "
        "end_ts>0 branch (120s). So any agent for which _conclusively_retired "
        "is genuinely True is already excluded by visible()'s own _retired() "
        "check on the same 'now' — the totals_only mispredict re-parse code in "
        "visible() (lines ~1081-1122) can never fire in production; it is only "
        "reachable via the test's previous constant-True stub. See "
        ".scratch/refactor-reduce-loc/editor-phase3-defects.md for the full "
        "diagnosis; not fixed here per instructions to not edit claude/**."
    ),
)
def test_mispredict_path_re_parse_restores_real_values(tmp_home: Path) -> None:
    """Task 6.6(c), part 2: a totals_only-marked agent that is still visible()
    should get re-parsed to restore real model/last_activity. Marked xfail
    (strict) — see the reason above: unreachable given current thresholds."""
    from yas.info.parsecache import TranscriptCache

    session_id = 'sess-mispredict-2'
    project_dir = _PROJECT_DIR
    sdir = (
        tmp_home / '.claude' / 'projects' / f'-{_PROJECT_SLUG}'
        / session_id / 'subagents'
    )
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / 'agent-mispredict2.meta.json').write_text(
        json.dumps({'agentType': 'Explore', 'description': 'find X'}),
    )
    jsonl = sdir / 'agent-mispredict2.jsonl'
    jsonl.write_text(json.dumps({
        'type': 'assistant',
        'timestamp': '2025-01-01T12:00:00.000Z',
        'message': {
            'id': 'msg-001',
            'model': 'claude-3.5-sonnet',
            'stop_reason': 'end_turn',
            'usage': {
                'input_tokens': 100,
                'cache_creation_input_tokens': 10,
                'cache_read_input_tokens': 20,
                'output_tokens': 50,
            },
            'content': [
                {'type': 'tool_use', 'name': 'TestTool', 'id': 'tooluse-1', 'input': {'arg': 'value'}}
            ]
        }
    }) + '\n')

    session_dir = tmp_home / '.claude' / 'projects' / f'-{_PROJECT_SLUG}'
    (session_dir / f'{session_id}.jsonl').write_text(json.dumps({
        'type': 'queue-operation',
        'operation': 'enqueue',
        'timestamp': '2025-01-01T12:00:30.000Z',
        'content': (
            '<task-notification>\n'
            '<task-id>mispredict2</task-id>\n'
            '<tool-use-id>toolu_mispredict2</tool-use-id>\n'
            '<status>completed</status>\n'
            '<summary>done</summary>\n'
            '</task-notification>'
        ),
    }) + '\n')

    notif_epoch = datetime.datetime(
        2025, 1, 1, 12, 0, 30, tzinfo=datetime.timezone.utc,
    ).timestamp()
    os.utime(jsonl, (notif_epoch, notif_epoch))

    now = (
        notif_epoch
        + RunningSubagents.ABANDONED_HORIZON_SECONDS
        + RunningSubagents.TERMINAL_SKEW_SECONDS
        + 10.0
    )

    cache = TranscriptCache(session_id)
    cache.save()

    running = RunningSubagents.from_session(session_id, project_dir, now=now, cache=cache)
    sub = running.subagents[0]
    assert sub.agent_id in running.totals_only_ids

    visible_list = running.visible(now, last_prompt_ts=None)

    assert len(visible_list) == 1
    restored_sub = visible_list[0]
    assert restored_sub.model == 'claude-3.5-sonnet', \
        f"Expected real model after re-parse, got {restored_sub.model}"
    assert restored_sub.last_activity[0] == 'tool_use', \
        f"Expected tool_use activity type, got {restored_sub.last_activity[0]}"
    assert restored_sub.last_activity[1] == 'TestTool', \
        f"Expected TestTool name, got {restored_sub.last_activity[1]}"
    assert len(running.totals_only_ids) == 0, "totals_only_ids should be cleared after re-parse"

    visible_list2 = running.visible(now, last_prompt_ts=None)
    assert len(visible_list2) == 1
    assert visible_list2[0].model == 'claude-3.5-sonnet', "Model should persist after second visible() call"
    assert len(running.totals_only_ids) == 0, "totals_only_ids should remain empty"


def test_tree_states_scenario_shows_four_states(tmp_path: Path) -> None:
    '''All four subagent lifecycle markers carried by the scenario must be
    present in the rendered output: ✓ completed, ✗ killed, ✗ stopped, and
    ↺ resumed (the scenario has no plain-running root — it
    is 4 flat subagents, one per state).
    '''
    with tempfile.TemporaryDirectory() as td:
        out = _render_tree_states_scenario(Path(td))
    plain = _ANSI_RE.sub('', out)

    checks = {
        'completed marker (✓)':      subagent_marker_glyph('completed') == GLYPH_SUBAGENT_DONE and GLYPH_SUBAGENT_DONE in plain,
        'killed marker (✗)':         subagent_marker_glyph('killed') == GLYPH_SUBAGENT_ENDED and GLYPH_SUBAGENT_ENDED in plain,
        'stopped marker (✗)':        subagent_marker_glyph('stopped') == GLYPH_SUBAGENT_ENDED and plain.count(GLYPH_SUBAGENT_ENDED) >= 2,
        'resumed marker (↺)':        GLYPH_SUBAGENT_RESUME in plain,
    }
    missing = [name for name, present in checks.items() if not present]
    assert not missing, (
        f'subagent-tree-wide-states scenario is missing: {missing}. '
        f'This scenario carries exactly SUBAGENT_DISPLAY_CAP={SUBAGENT_DISPLAY_CAP - 2} '
        f'flat subagent rows well under the display cap; if a marker went missing '
        f'here without a test failure elsewhere, check for a change to the cap/trim '
        f'logic or the scenario\'s subagents list in ops/demo.py.\n'
        f'--- rendered output ---\n{plain}'
    )
