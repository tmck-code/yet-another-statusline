'''Test that the wide layout's session-elapsed comes from the host's authoritative
cost.total_duration_ms (Audit DATA-5), not the transcript file's mtime.'''
import re

import statusline_command as sl


def _plain(s: str) -> str:
    return re.sub(r'\x1b\[[0-9;]*m', '', s)


def _render(total_duration_ms, width=130):
    return _plain(sl.render({
        'session_id': 's', 'model': {'display_name': 'Opus 4.1'},
        'workspace': {'current_dir': '/tmp/p'},
        'cost': {'total_duration_ms': total_duration_ms},
        'context_window': {'total_input_tokens': 40000, 'context_window_size': 200000},
    }, width, theme=sl.CLAUDE_DARK))


def test_elapsed_from_total_duration_ms():
    # 807557 ms -> 13m27s (fmt_dur granularity). The value is wall-clock since
    # session start, taken straight from stdin — no transcript stat().
    assert '13m27s' in _render(807557)


def test_elapsed_hours():
    # 3661000 ms = 1h 01m 01s -> '1h01m' (fmt_dur drops seconds past the hour).
    assert '1h01m' in _render(3661000)


def test_elapsed_zero_duration_hidden():
    # Before the first API response total_duration_ms is 0 -> no elapsed tail.
    out = _render(0)
    assert not re.search(r'\[\d+[hm]\d', out)  # no [13m27s] / [1h01m]-style tail


def test_elapsed_does_not_stat_transcript():
    # The displayed elapsed must NOT depend on transcript_path mtime. A bogus
    # path with a real total_duration_ms still shows the duration.
    out = _plain(sl.render({
        'session_id': 's', 'model': {'display_name': 'Opus 4.1'},
        'workspace': {'current_dir': '/tmp/p'},
        'transcript_path': '/nonexistent/does-not-exist.jsonl',
        'cost': {'total_duration_ms': 807557},
        'context_window': {'total_input_tokens': 40000, 'context_window_size': 200000},
    }, 130, theme=sl.CLAUDE_DARK))
    assert '13m27s' in out
