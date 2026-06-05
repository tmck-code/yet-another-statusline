"""Tests for yas.info — SessionView gather module."""
from __future__ import annotations

import json
import time
from pathlib import Path


from yas.info import SessionView
from yas.info.git import GitInfo
from yas.info.openspec import OpenSpec
from yas.info.subagents import RunningSubagent, RunningSubagents
from yas.info.transcript import TranscriptUsage

SESSION_FILE = Path(__file__).parent.parent / 'ops' / 'session-info-example.json'


def _session():
    from yas.session import SessionInfo
    return SessionInfo.from_dict(json.loads(SESSION_FILE.read_text()))


def _cfg():
    from yas.config import Config
    return Config()


# ---------------------------------------------------------------------------
# Task 2.1 — session_inout arithmetic
# ---------------------------------------------------------------------------

def test_session_inout_sums_usage_and_subagents(monkeypatch):
    """session_inout = (billed_in + cache_read + out) + Σ(subagent total_input + output)."""

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
    from yas.info import _fmt_elapsed
    assert _fmt_elapsed(None, time.time()) == ''


def test_fmt_elapsed_sub_hour():
    """mtime 5 minutes ago returns '5m'."""
    from yas.info import _fmt_elapsed
    now   = time.time()
    mtime = now - 300  # 5 minutes ago
    result = _fmt_elapsed(mtime, now)
    assert result == '5m'


def test_fmt_elapsed_multi_hour():
    """mtime 1h30m ago returns '1h30m'."""
    from yas.info import _fmt_elapsed
    now   = time.time()
    mtime = now - (90 * 60)  # 1h 30m ago
    result = _fmt_elapsed(mtime, now)
    assert result == '1h30m'


def test_fmt_elapsed_exact_one_hour():
    """mtime exactly 1h ago returns '1h0m'."""
    from yas.info import _fmt_elapsed
    now   = time.time()
    mtime = now - 3600
    result = _fmt_elapsed(mtime, now)
    assert result == '1h0m'


def test_fmt_elapsed_zero_minutes():
    """mtime 30 seconds ago (< 1m) returns '0m'."""
    from yas.info import _fmt_elapsed
    now   = time.time()
    mtime = now - 30
    result = _fmt_elapsed(mtime, now)
    assert result == '0m'


# ---------------------------------------------------------------------------
# session-elapsed-accuracy — elapsed derived from total_duration_ms
# ---------------------------------------------------------------------------

def test_elapsed_duration_under_one_hour():
    """total_duration_ms=807000 (13m27s) → elapsed == '13m'."""
    from yas.info import _fmt_duration_ms
    assert _fmt_duration_ms(807_000) == '13m'


def test_elapsed_duration_one_hour_or_more():
    """total_duration_ms=5580000 (1h33m) → elapsed == '1h33m'."""
    from yas.info import _fmt_duration_ms
    assert _fmt_duration_ms(5_580_000) == '1h33m'


def test_elapsed_duration_zero():
    """total_duration_ms=0 → elapsed == '' (empty string)."""
    from yas.info import _fmt_duration_ms
    assert _fmt_duration_ms(0) == ''


def test_elapsed_does_not_trigger_file_stat(monkeypatch):
    """Accessing view.elapsed alone does NOT trigger a Path.stat call."""
    from unittest.mock import patch

    session = _session()
    view = SessionView(session=session, cfg=_cfg())

    # Patch Path.stat to detect any stat call.
    with patch('pathlib.Path.stat', side_effect=AssertionError('unexpected Path.stat call')):
        result = view.elapsed

    # Result should be the formatted duration from the payload (807557ms → 13m).
    assert result == '13m'


# ---------------------------------------------------------------------------
# Task 2.3 — laziness: accessing view.subagents must NOT trigger git / transcript / openspec
# ---------------------------------------------------------------------------

def test_accessing_subagents_does_not_trigger_other_readers(monkeypatch):
    """Accessing only view.subagents must not call GitInfo.from_cwd,
    TranscriptUsage.from_transcript, or OpenSpec.from_cwd."""

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


# ---------------------------------------------------------------------------
# Task 6.2 — TranscriptUsage cache anchor / TTL logic
# ---------------------------------------------------------------------------

def _write_transcript(tmp_path: Path, lines: list[dict]) -> Path:
    """Write a JSONL transcript file and return its path."""
    p = tmp_path / 'transcript.jsonl'
    p.write_text('\n'.join(json.dumps(ln) for ln in lines) + '\n')
    return p


def _assistant_line(
    mid: str,
    timestamp: str,
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
    cache_creation: dict | None = None,
) -> dict:
    """Build a minimal assistant JSONL line."""
    usage: dict = {
        'input_tokens':                 input_tokens,
        'output_tokens':                output_tokens,
        'cache_creation_input_tokens':  cache_creation_input_tokens,
        'cache_read_input_tokens':      cache_read_input_tokens,
    }
    if cache_creation is not None:
        usage['cache_creation'] = cache_creation
    return {
        'type':      'assistant',
        'timestamp': timestamp,
        'message': {
            'role': 'assistant',
            'id':   mid,
            'usage': usage,
        },
    }


def test_cache_latest_anchor_wins(tmp_path):
    """When multiple cache-bearing lines exist the LAST one sets cache_anchor_epoch."""
    lines = [
        _assistant_line('msg-1', '2024-01-01T10:00:00.000Z', cache_read_input_tokens=100),
        _assistant_line('msg-2', '2024-01-01T11:00:00.000Z', cache_read_input_tokens=200),
        _assistant_line('msg-3', '2024-01-01T12:00:00.000Z', cache_read_input_tokens=300),
    ]
    p = _write_transcript(tmp_path, lines)
    usage = TranscriptUsage.from_transcript(str(p))

    from datetime import datetime
    expected = datetime.fromisoformat('2024-01-01T12:00:00+00:00').timestamp()
    assert usage.cache_anchor_epoch == expected


def test_cache_no_cache_activity_zero_anchor(tmp_path):
    """Transcript with no cache tokens → cache_anchor_epoch == 0.0 and cache_ttl == 0."""
    lines = [
        _assistant_line('msg-1', '2024-01-01T10:00:00.000Z'),
        _assistant_line('msg-2', '2024-01-01T11:00:00.000Z'),
    ]
    p = _write_transcript(tmp_path, lines)
    usage = TranscriptUsage.from_transcript(str(p))

    assert usage.cache_anchor_epoch == 0.0
    assert usage.cache_ttl == 0


def test_cache_1h_tier_sets_ttl_3600(tmp_path):
    """A line with cache_creation.ephemeral_1h_input_tokens > 0 → cache_ttl == 3600."""
    lines = [
        _assistant_line(
            'msg-1', '2024-01-01T10:00:00.000Z',
            cache_creation_input_tokens=100,
            cache_creation={'ephemeral_1h_input_tokens': 50},
        ),
    ]
    p = _write_transcript(tmp_path, lines)
    usage = TranscriptUsage.from_transcript(str(p))

    assert usage.cache_ttl == 3600


def test_cache_default_tier_sets_ttl_300(tmp_path):
    """A line with cache_read_input_tokens > 0 and no 1h flag → cache_ttl == 300."""
    lines = [
        _assistant_line('msg-1', '2024-01-01T10:00:00.000Z', cache_read_input_tokens=50),
    ]
    p = _write_transcript(tmp_path, lines)
    usage = TranscriptUsage.from_transcript(str(p))

    assert usage.cache_ttl == 300


def test_cache_malformed_timestamp_yields_zero_anchor(tmp_path):
    """Anchor line exists but timestamp is malformed → cache_anchor_epoch == 0.0."""
    line = _assistant_line('msg-1', 'not-a-timestamp', cache_read_input_tokens=100)
    p = _write_transcript(tmp_path, [line])
    usage = TranscriptUsage.from_transcript(str(p))

    assert usage.cache_anchor_epoch == 0.0


def test_cache_missing_timestamp_yields_zero_anchor(tmp_path):
    """Anchor line exists but timestamp key is absent → cache_anchor_epoch == 0.0."""
    line = _assistant_line('msg-1', '', cache_read_input_tokens=100)
    # Remove the timestamp key entirely
    line.pop('timestamp')
    p = _write_transcript(tmp_path, [line])
    usage = TranscriptUsage.from_transcript(str(p))

    assert usage.cache_anchor_epoch == 0.0


# ---------------------------------------------------------------------------
# Task 6.3 — scan-once: transcript_usage and cache_countdown share one read
# ---------------------------------------------------------------------------

def test_transcript_scanned_once_for_usage_and_cache_countdown(tmp_path, monkeypatch):
    """Accessing both transcript_usage and cache_countdown triggers exactly one
    file scan — cache_countdown must reuse the already-cached transcript_usage
    rather than calling from_transcript a second time."""
    from unittest.mock import patch

    lines = [
        _assistant_line('msg-1', '2024-06-01T10:00:00.000Z', cache_read_input_tokens=100),
    ]
    p = _write_transcript(tmp_path, lines)

    # Monkeypatch all the other readers so only transcript I/O is live.
    monkeypatch.setattr(GitInfo,          'from_cwd',     classmethod(lambda cls, cwd: GitInfo()))
    monkeypatch.setattr(RunningSubagents, 'from_session', classmethod(lambda cls, sid, pd: RunningSubagents(subagents=[])))
    monkeypatch.setattr(OpenSpec,         'from_cwd',     classmethod(lambda cls, cwd: OpenSpec()))

    # Build a session whose transcript_path points at the temp file.
    session = _session()
    object.__setattr__(session, 'transcript_path', str(p))

    from datetime import datetime
    anchor_ts   = datetime.fromisoformat('2024-06-01T10:00:00+00:00').timestamp()
    # Freeze 'now' to 60 s after the anchor so the cache is still live.
    frozen_now  = anchor_ts + 60.0

    with patch.object(
        TranscriptUsage,
        'from_transcript',
        wraps=TranscriptUsage.from_transcript,
    ) as mock_scan:
        view = SessionView(session=session, cfg=_cfg(), now=frozen_now)

        # First access: transcript_usage should trigger exactly one scan.
        tu = view.transcript_usage
        assert mock_scan.call_count == 1, (
            f'expected 1 scan after transcript_usage, got {mock_scan.call_count}'
        )

        # Second access via cache_countdown must NOT trigger a second scan.
        cc = view.cache_countdown
        assert mock_scan.call_count == 1, (
            f'expected still 1 scan after cache_countdown, got {mock_scan.call_count}'
        )

    # @cached_property stores the result in instance __dict__ after first access.
    assert 'transcript_usage' in view.__dict__, (
        'transcript_usage not found in view.__dict__; @cached_property may not have fired'
    )

    # Data-consistency: both views derive from the same single scan result.
    assert tu.cache_anchor_epoch == anchor_ts
    assert cc is not None, 'cache_countdown should be non-None for a live cache'
    remaining, elapsed_pct = cc
    assert 0 < remaining <= 300, f'unexpected remaining seconds: {remaining}'
    assert 0 <= elapsed_pct <= 100


# ---------------------------------------------------------------------------
# Task 6.1 — cache_countdown math on SessionView
# ---------------------------------------------------------------------------

def _make_view(fake_usage: 'TranscriptUsage', fixed_now: float) -> SessionView:
    """Construct a SessionView with a pre-populated transcript_usage and frozen now."""
    session = _session()
    # Minimise I/O: pre-populate every cached_property that might otherwise hit
    # the filesystem, then inject the fake transcript_usage.
    view = SessionView(session=session, cfg=_cfg(), now=fixed_now)
    view.__dict__['transcript_usage'] = fake_usage
    view.__dict__['git']       = GitInfo()
    view.__dict__['subagents'] = RunningSubagents(subagents=[])
    view.__dict__['changes']   = []
    return view


def test_cache_countdown_fresh():
    """90s elapsed out of 300s TTL → remaining 210, elapsed_pct 30."""
    now   = 1_700_000_000.0
    usage = TranscriptUsage(
        cache_anchor_epoch = now - 90,
        cache_ttl          = 300,
    )
    result = _make_view(usage, now).cache_countdown

    assert result is not None
    remaining, elapsed_pct = result
    assert remaining   == 210.0
    assert elapsed_pct == 30


def test_cache_countdown_near_expiry():
    """280s elapsed out of 300s → elapsed_pct in alert band (>= 85)."""
    now   = 1_700_000_000.0
    usage = TranscriptUsage(
        cache_anchor_epoch = now - 280,
        cache_ttl          = 300,
    )
    result = _make_view(usage, now).cache_countdown

    assert result is not None
    _remaining, elapsed_pct = result
    # 100 - round(20 * 100 / 300) = 100 - 7 = 93
    assert elapsed_pct == 93
    assert elapsed_pct >= 85


def test_cache_countdown_expired():
    """Cache expired (400s elapsed, 300s TTL) → None."""
    now   = 1_700_000_000.0
    usage = TranscriptUsage(
        cache_anchor_epoch = now - 400,
        cache_ttl          = 300,
    )
    result = _make_view(usage, now).cache_countdown

    assert result is None


def test_cache_countdown_no_anchor():
    """No cache event (anchor == 0.0 default) → None."""
    now   = 1_700_000_000.0
    usage = TranscriptUsage()  # cache_anchor_epoch=0.0, cache_ttl=0 by default

    result = _make_view(usage, now).cache_countdown

    assert result is None


def test_cache_countdown_1h_tier():
    """90s elapsed out of 3600s (1h tier) → remaining 3510, elapsed_pct 3."""
    now   = 1_700_000_000.0
    usage = TranscriptUsage(
        cache_anchor_epoch = now - 90,
        cache_ttl          = 3600,
    )
    result = _make_view(usage, now).cache_countdown

    assert result is not None
    remaining, elapsed_pct = result
    assert remaining   == 3510.0
    # 100 - round(3510 * 100 / 3600) = 100 - round(97.5) = 100 - 98 = 2
    # (Python rounds half-to-even: round(97.5) == 98)
    assert elapsed_pct == 2


def test_cache_countdown_uses_frozen_now():
    """cache_countdown must use the frozen now passed at construction, not a live clock."""
    frozen_now = 1_700_000_000.0
    usage      = TranscriptUsage(
        cache_anchor_epoch = frozen_now - 90,
        cache_ttl          = 300,
    )
    view = _make_view(usage, frozen_now)

    result = view.cache_countdown

    assert result is not None
    remaining, elapsed_pct = result
    # With frozen_now the math is deterministic: 300 - 90 = 210 remaining
    assert remaining   == 210.0
    assert elapsed_pct == 30
