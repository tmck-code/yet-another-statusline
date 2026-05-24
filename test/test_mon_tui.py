"""Tests for claude/mon/tui.py — covering tasks 5.2–5.5."""

import io
import os
import signal
import sys
import threading
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from claude.mon.tui import (
    RefreshClock,
    enter_alt_screen,
    exit_alt_screen,
    install_sigwinch_handler,
    parse_args,
)
from claude.mon.lifecycle import validate_thresholds


# ---------------------------------------------------------------------------
# parse_args — defaults
# ---------------------------------------------------------------------------

def test_parse_args_defaults():
    ns = parse_args([])
    assert ns.include_after == timedelta(minutes=10)
    assert ns.idle_after == timedelta(minutes=2)
    assert ns.remove_after == timedelta(minutes=15)
    assert ns.refresh == timedelta(seconds=2)
    assert ns.bg_shift == 'warm'
    assert ns.theme is None


# ---------------------------------------------------------------------------
# parse_args — individual flags
# ---------------------------------------------------------------------------

def test_parse_args_include_after():
    ns = parse_args(['--include-after=5m'])
    assert ns.include_after == timedelta(minutes=5)


def test_parse_args_idle_after():
    ns = parse_args(['--idle-after=30s'])
    assert ns.idle_after == timedelta(seconds=30)


def test_parse_args_remove_after():
    ns = parse_args(['--remove-after=1h'])
    assert ns.remove_after == timedelta(hours=1)


def test_parse_args_refresh():
    ns = parse_args(['--refresh=5s'])
    assert ns.refresh == timedelta(seconds=5)


def test_parse_args_bg_shift_cool():
    ns = parse_args(['--bg-shift=cool'])
    assert ns.bg_shift == 'cool'


def test_parse_args_bg_shift_warm():
    ns = parse_args(['--bg-shift=warm'])
    assert ns.bg_shift == 'warm'


def test_parse_args_theme():
    ns = parse_args(['--theme=dark'])
    assert ns.theme == 'dark'


# ---------------------------------------------------------------------------
# parse_args — all duration suffixes
# ---------------------------------------------------------------------------

def test_parse_args_duration_suffix_s():
    ns = parse_args(['--refresh=10s'])
    assert ns.refresh == timedelta(seconds=10)


def test_parse_args_duration_suffix_m():
    ns = parse_args(['--refresh=3m'])
    assert ns.refresh == timedelta(minutes=3)


def test_parse_args_duration_suffix_h():
    ns = parse_args(['--include-after=2h'])
    assert ns.include_after == timedelta(hours=2)


def test_parse_args_duration_fractional_seconds():
    ns = parse_args(['--refresh=0.5s'])
    assert ns.refresh == timedelta(seconds=0.5)


# ---------------------------------------------------------------------------
# parse_args — invalid duration raises SystemExit
# ---------------------------------------------------------------------------

def test_parse_args_invalid_duration_no_suffix():
    with pytest.raises(SystemExit):
        parse_args(['--refresh=10'])


def test_parse_args_invalid_duration_bad_number():
    with pytest.raises(SystemExit):
        parse_args(['--refresh=abcs'])


def test_parse_args_invalid_bg_shift():
    with pytest.raises(SystemExit):
        parse_args(['--bg-shift=blazing'])


# ---------------------------------------------------------------------------
# validate_thresholds — threshold ordering
# ---------------------------------------------------------------------------

def test_validate_thresholds_ok():
    # should not raise
    validate_thresholds(
        include=timedelta(minutes=10),
        idle=timedelta(minutes=2),
        remove=timedelta(minutes=15),
    )


def test_validate_thresholds_remove_less_than_idle():
    with pytest.raises(ValueError, match='remove_after'):
        validate_thresholds(
            include=timedelta(minutes=10),
            idle=timedelta(minutes=5),
            remove=timedelta(minutes=1),
        )


def test_validate_thresholds_remove_equal_idle_ok():
    # equal is fine — only strict less-than triggers
    validate_thresholds(
        include=timedelta(minutes=10),
        idle=timedelta(minutes=5),
        remove=timedelta(minutes=5),
    )


# ---------------------------------------------------------------------------
# enter_alt_screen / exit_alt_screen — escape sequences
# ---------------------------------------------------------------------------

def test_enter_alt_screen_writes_correct_sequence(monkeypatch):
    buf = io.StringIO()
    monkeypatch.setattr(sys, 'stdout', buf)
    enter_alt_screen()
    assert buf.getvalue() == '\x1b[?1049h'


def test_exit_alt_screen_writes_correct_sequence(monkeypatch):
    buf = io.StringIO()
    monkeypatch.setattr(sys, 'stdout', buf)
    exit_alt_screen()
    assert buf.getvalue() == '\x1b[?1049l'


def test_enter_exit_alt_screen_combined(monkeypatch):
    buf = io.StringIO()
    monkeypatch.setattr(sys, 'stdout', buf)
    enter_alt_screen()
    exit_alt_screen()
    assert buf.getvalue() == '\x1b[?1049h\x1b[?1049l'


# ---------------------------------------------------------------------------
# RefreshClock
# ---------------------------------------------------------------------------

def test_refresh_clock_wait_returns_within_timeout():
    clock = RefreshClock()
    # wait with a very short timeout — must not hang
    clock.wait(0.01)  # 10 ms


def test_refresh_clock_wake_causes_early_return():
    clock = RefreshClock()
    results = []

    def _waiter():
        clock.wait(5.0)  # would block for 5 s without wake
        results.append('done')

    t = threading.Thread(target=_waiter, daemon=True)
    t.start()
    clock.wake()
    t.join(timeout=1.0)

    assert not t.is_alive(), 'wait() did not return after wake()'
    assert results == ['done']


def test_refresh_clock_wake_before_wait_returns_immediately():
    clock = RefreshClock()
    clock.wake()  # pre-signal

    done = threading.Event()

    def _waiter():
        clock.wait(5.0)
        done.set()

    t = threading.Thread(target=_waiter, daemon=True)
    t.start()
    t.join(timeout=1.0)

    assert done.is_set(), 'wait() did not return immediately after pre-wake'


def test_refresh_clock_second_wait_blocks_after_first_consumed():
    """After wait() consumes the event, a subsequent wait() blocks again."""
    clock = RefreshClock()
    clock.wake()
    clock.wait(0.01)   # consume the event

    done = threading.Event()

    def _waiter():
        clock.wait(5.0)   # no pending event — would block without external wake
        done.set()

    t = threading.Thread(target=_waiter, daemon=True)
    t.start()
    t.join(timeout=0.05)  # very short: expect it is still blocking

    assert not done.is_set(), 'second wait() returned without a wake()'
    clock.wake()          # clean up the thread
    t.join(timeout=1.0)


# ---------------------------------------------------------------------------
# install_sigwinch_handler
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not hasattr(signal, 'SIGWINCH'),
    reason='SIGWINCH not available on this platform',
)
def test_install_sigwinch_handler_calls_on_resize():
    clock = RefreshClock()
    resize_calls = []

    def on_resize(cols: int, rows: int) -> None:
        resize_calls.append((cols, rows))

    install_sigwinch_handler(clock, on_resize)
    os.kill(os.getpid(), signal.SIGWINCH)

    # Give the signal handler a moment to fire (it runs synchronously
    # on the main thread when the signal is delivered)
    assert len(resize_calls) == 1
    cols, rows = resize_calls[0]
    assert isinstance(cols, int) and cols > 0
    assert isinstance(rows, int) and rows > 0


@pytest.mark.skipif(
    not hasattr(signal, 'SIGWINCH'),
    reason='SIGWINCH not available on this platform',
)
def test_install_sigwinch_handler_wakes_clock():
    clock = RefreshClock()
    woken = threading.Event()

    def on_resize(cols: int, rows: int) -> None:
        pass

    def _waiter():
        clock.wait(5.0)
        woken.set()

    install_sigwinch_handler(clock, on_resize)

    t = threading.Thread(target=_waiter, daemon=True)
    t.start()
    os.kill(os.getpid(), signal.SIGWINCH)
    t.join(timeout=1.0)

    assert woken.is_set(), 'SIGWINCH did not wake the RefreshClock'
