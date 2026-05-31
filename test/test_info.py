"""Tests for statusline.info — SessionView gather module."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from statusline.git import GitInfo
from statusline.openspec import OpenSpec
from statusline.subagents import RunningSubagent, RunningSubagents
from statusline.transcript import TranscriptUsage

SESSION_FILE = Path(__file__).parent.parent / 'claude' / 'statusline' / 'session-info-example.json'


def _session():
    from statusline.session import SessionInfo
    return SessionInfo.from_dict(json.loads(SESSION_FILE.read_text()))


def _cfg():
    from statusline.config import Config
    return Config()


# ---------------------------------------------------------------------------
# Task 2.1 — session_inout arithmetic
# ---------------------------------------------------------------------------

def test_session_inout_sums_usage_and_subagents(monkeypatch):
    """session_inout = (billed_in + cache_read + out) + Σ(subagent total_input + output)."""
    from statusline.info import SessionView

    usage = TranscriptUsage(
        input_tokens                = 100,
        cache_creation_input_tokens = 50,
        cache_read_input_tokens     = 200,
        output_tokens               = 75,
    )
    # billed_in = 100 + 50 = 150; cache_read = 200; out = 75  → 425
    # subagents: (300 + 80) + (120 + 40) = 380 + 160 = 540
    # total: 425 + 540 = 965

    sub_a = RunningSubagent(
        agent_type      = 'Explore',
        description     = 'find X',
        billed_in       = 300,
        output          = 80,
        first_timestamp = time.time(),
        total_input     = 300,
    )
    sub_b = RunningSubagent(
        agent_type      = 'Write',
        description     = 'write Y',
        billed_in       = 120,
        output          = 40,
        first_timestamp = time.time(),
        total_input     = 120,
    )
    running = RunningSubagents(subagents=[sub_a, sub_b])

    monkeypatch.setattr(TranscriptUsage, 'from_transcript', classmethod(lambda cls, p: usage))
    monkeypatch.setattr(RunningSubagents, 'from_session',   classmethod(lambda cls, sid, pd: running))
    monkeypatch.setattr(GitInfo,          'from_cwd',       classmethod(lambda cls, cwd: GitInfo()))
    monkeypatch.setattr(OpenSpec,         'from_cwd',       classmethod(lambda cls, cwd: OpenSpec()))

    session = _session()
    view = SessionView(session=session, cfg=_cfg())

    # expected: 425 (transcript) + 540 (subagents) = 965
    assert view.session_inout == 965


def test_session_inout_no_subagents(monkeypatch):
    """With no running subagents, session_inout equals transcript usage only."""
    from statusline.info import SessionView

    usage   = TranscriptUsage(
        input_tokens                = 400,
        cache_creation_input_tokens = 0,
        cache_read_input_tokens     = 100,
        output_tokens               = 50,
    )
    running = RunningSubagents(subagents=[])

    monkeypatch.setattr(TranscriptUsage, 'from_transcript', classmethod(lambda cls, p: usage))
    monkeypatch.setattr(RunningSubagents, 'from_session',   classmethod(lambda cls, sid, pd: running))
    monkeypatch.setattr(GitInfo,          'from_cwd',       classmethod(lambda cls, cwd: GitInfo()))
    monkeypatch.setattr(OpenSpec,         'from_cwd',       classmethod(lambda cls, cwd: OpenSpec()))

    view = SessionView(session=_session(), cfg=_cfg())
    # billed_in=400, cache_read=100, out=50 → 550
    assert view.session_inout == 550


# ---------------------------------------------------------------------------
# Task 2.2 — _fmt_elapsed pure function
# ---------------------------------------------------------------------------

def test_fmt_elapsed_none_returns_empty():
    """None mtime returns empty string."""
    from statusline.info import _fmt_elapsed
    assert _fmt_elapsed(None, time.time()) == ''


def test_fmt_elapsed_sub_hour():
    """mtime 5 minutes ago returns '5m'."""
    from statusline.info import _fmt_elapsed
    now   = time.time()
    mtime = now - 300  # 5 minutes ago
    result = _fmt_elapsed(mtime, now)
    assert result == '5m'


def test_fmt_elapsed_multi_hour():
    """mtime 1h30m ago returns '1h30m'."""
    from statusline.info import _fmt_elapsed
    now   = time.time()
    mtime = now - (90 * 60)  # 1h 30m ago
    result = _fmt_elapsed(mtime, now)
    assert result == '1h30m'


def test_fmt_elapsed_exact_one_hour():
    """mtime exactly 1h ago returns '1h0m'."""
    from statusline.info import _fmt_elapsed
    now   = time.time()
    mtime = now - 3600
    result = _fmt_elapsed(mtime, now)
    assert result == '1h0m'


def test_fmt_elapsed_zero_minutes():
    """mtime 30 seconds ago (< 1m) returns '0m'."""
    from statusline.info import _fmt_elapsed
    now   = time.time()
    mtime = now - 30
    result = _fmt_elapsed(mtime, now)
    assert result == '0m'


# ---------------------------------------------------------------------------
# Task 2.3 — laziness: accessing view.subagents must NOT trigger git / transcript / openspec
# ---------------------------------------------------------------------------

def test_accessing_subagents_does_not_trigger_other_readers(monkeypatch):
    """Accessing only view.subagents must not call GitInfo.from_cwd,
    TranscriptUsage.from_transcript, or OpenSpec.from_cwd."""
    from statusline.info import SessionView

    git_call_count        = {'n': 0}
    transcript_call_count = {'n': 0}
    openspec_call_count   = {'n': 0}

    def counting_git(cls, cwd):
        git_call_count['n'] += 1
        return GitInfo()

    def counting_transcript(cls, path):
        transcript_call_count['n'] += 1
        return TranscriptUsage()

    def counting_openspec(cls, cwd):
        openspec_call_count['n'] += 1
        return OpenSpec()

    running = RunningSubagents(subagents=[])

    monkeypatch.setattr(GitInfo,          'from_cwd',       classmethod(counting_git))
    monkeypatch.setattr(TranscriptUsage,  'from_transcript', classmethod(counting_transcript))
    monkeypatch.setattr(OpenSpec,         'from_cwd',       classmethod(counting_openspec))
    monkeypatch.setattr(RunningSubagents, 'from_session',   classmethod(lambda cls, sid, pd: running))

    view = SessionView(session=_session(), cfg=_cfg())
    _ = view.subagents  # access only this one cached property

    assert git_call_count['n']        == 0, 'GitInfo.from_cwd should not have been called'
    assert transcript_call_count['n'] == 0, 'TranscriptUsage.from_transcript should not have been called'
    assert openspec_call_count['n']   == 0, 'OpenSpec.from_cwd should not have been called'
