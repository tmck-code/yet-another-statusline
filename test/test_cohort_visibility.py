'''Tests for RunningSubagents.visible() — cohort membership & retirement logic.

These tests build RunningSubagent objects directly (no disk I/O) so they are
fast and deterministic.  The mtime and end_ts fields are set explicitly to
simulate various age/done combinations.
'''
from yas.info.subagents import RunningSubagent, RunningSubagents


NOW = 1_000_000.0  # arbitrary fixed epoch

LIVENESS  = RunningSubagents.LIVENESS_WINDOW_SECONDS   # 30
GRACE     = RunningSubagents.COHORT_GRACE_SECONDS       # 20
JANITOR   = RunningSubagents.JANITOR_HORIZON_SECONDS    # 60


def _sub(
    *,
    first_timestamp: float = NOW - 10.0,
    mtime: float           = NOW - 5.0,
    end_ts: float          = 0.0,
    description: str       = 'test-agent',
) -> RunningSubagent:
    return RunningSubagent(
        agent_type      = 'Explore',
        description     = description,
        billed_in       = 0,
        output          = 0,
        first_timestamp = first_timestamp,
        mtime           = mtime,
        end_ts          = end_ts,
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


# ---------------------------------------------------------------------------
# Cohort retirement
# ---------------------------------------------------------------------------

def test_all_done_within_grace_returns_candidates() -> None:
    '''All-Done cohort within the grace window is still visible.'''
    last_prompt_ts = NOW - 30.0
    sub = _sub(first_timestamp=NOW - 25.0, mtime=NOW - 25.0, end_ts=NOW - (GRACE - 5))
    result = _cohort(sub).visible(NOW, last_prompt_ts)
    assert sub in result


def test_clean_retire_at_20s() -> None:
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


def test_janitor_sweep_at_60s() -> None:
    '''Dirty cohort (still-running agent) is swept when all transcripts silent for 60 s.'''
    last_prompt_ts = NOW - 5.0
    # Agent started this turn so it's a candidate, but hasn't written in 61 s
    sub = _sub(first_timestamp=NOW - 3.0, mtime=NOW - (JANITOR + 1), end_ts=0.0)
    result = _cohort(sub).visible(NOW, last_prompt_ts)
    assert result == []


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
