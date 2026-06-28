"""Tests for the per-tool tool_use counting aggregator (yas.info.toolcounts)."""

import json
from pathlib import Path

from yas.info.subagents import RunningSubagent, _parse_iso_to_epoch
from yas.info.toolcounts import ToolCounts, count_transcript

TS_EARLY = '2026-01-01T00:00:00Z'
TS_LATE  = '2026-01-01T12:00:00Z'


def _line(mid: str, tools: list[str], ts: str = TS_LATE) -> str:
    """One assistant JSONL line with the given message id and tool_use names."""
    return json.dumps({
        'timestamp': ts,
        'type':      'assistant',
        'message':   {
            'id':      mid,
            'content': [{'type': 'tool_use', 'name': t, 'input': {}} for t in tools],
        },
    })


def _write(tmp_path: Path, name: str, lines: list[str]) -> str:
    p = tmp_path / name
    p.write_text('\n'.join(lines) + '\n')
    return str(p)


def test_per_tool_counting(tmp_path: Path) -> None:
    path = _write(tmp_path, 'main.jsonl', [
        _line('m1', ['Bash']),
        _line('m2', ['Read', 'Read']),
        _line('m3', ['Edit']),
    ])
    assert count_transcript(path, None) == {'Bash': 1, 'Read': 2, 'Edit': 1}


def test_dedup_keeps_last_write(tmp_path: Path) -> None:
    """A later, fuller write for the same message.id supersedes the partial."""
    path = _write(tmp_path, 'main.jsonl', [
        _line('m1', ['Bash']),            # early partial: 1 block
        _line('m1', ['Bash', 'Read']),    # final write: 2 blocks
    ])
    assert count_transcript(path, None) == {'Bash': 1, 'Read': 1}


def test_repeated_identical_final_write_not_double_counted(tmp_path: Path) -> None:
    path = _write(tmp_path, 'main.jsonl', [
        _line('m1', ['Bash', 'Read']),
        _line('m1', ['Bash', 'Read']),
    ])
    assert count_transcript(path, None) == {'Bash': 1, 'Read': 1}


def test_clear_epoch_excludes_before_and_none_counts_all(tmp_path: Path) -> None:
    path = _write(tmp_path, 'main.jsonl', [
        _line('m1', ['Bash'], ts=TS_EARLY),
        _line('m2', ['Read'], ts=TS_LATE),
    ])
    # None counts the whole transcript.
    assert count_transcript(path, None) == {'Bash': 1, 'Read': 1}
    # A clear epoch between the two excludes the early Bash line.
    boundary = (_parse_iso_to_epoch(TS_EARLY) + _parse_iso_to_epoch(TS_LATE)) / 2
    assert count_transcript(path, boundary) == {'Read': 1}


def test_meta_excluded_task_kept(tmp_path: Path) -> None:
    path = _write(tmp_path, 'main.jsonl', [
        _line('m1', ['TodoWrite']),
        _line('m2', ['ExitPlanMode']),
        _line('m3', ['AskUserQuestion']),
        _line('m4', ['Task']),
        _line('m5', ['Bash', 'TodoWrite']),
    ])
    counts = count_transcript(path, None)
    assert 'TodoWrite' not in counts
    assert 'ExitPlanMode' not in counts
    assert 'AskUserQuestion' not in counts
    assert counts['Task'] == 1
    assert counts['Bash'] == 1


def test_mcp_name_normalized_to_last_segment(tmp_path: Path) -> None:
    path = _write(tmp_path, 'main.jsonl', [
        _line('m1', ['mcp__github__create_issue']),
        _line('m2', ['mcp__github__create_issue']),
    ])
    assert count_transcript(path, None) == {'create_issue': 2}


def test_missing_message_id_skipped(tmp_path: Path) -> None:
    """A tool_use line with no message.id contributes nothing."""
    line = json.dumps({
        'timestamp': TS_LATE,
        'message':   {'content': [{'type': 'tool_use', 'name': 'Bash', 'input': {}}]},
    })
    path = _write(tmp_path, 'main.jsonl', [line, _line('m1', ['Read'])])
    assert count_transcript(path, None) == {'Read': 1}


def test_unreadable_path_returns_empty() -> None:
    assert count_transcript('', None) == {}
    assert count_transcript('/no/such/file.jsonl', None) == {}


def _sub(jsonl_path: str) -> RunningSubagent:
    return RunningSubagent(
        agent_type      = 'Explore',
        description     = '',
        billed_in       = 0,
        output          = 0,
        first_timestamp = 0.0,
        jsonl_path      = jsonl_path,
    )


def test_gather_main_vs_sub_summed_across_subagents(tmp_path: Path) -> None:
    main = _write(tmp_path, 'main.jsonl', [
        _line('m1', ['Edit', 'Edit', 'Edit']),
    ])
    sub1 = _write(tmp_path, 'a1.jsonl', [_line('s1', ['Grep'] * 6)])
    sub2 = _write(tmp_path, 'a2.jsonl', [_line('s2', ['Grep'] * 9)])

    tc = ToolCounts.gather(main, [_sub(sub1), _sub(sub2)], None)
    assert tc.counts['Edit'] == (3, 0)
    assert tc.counts['Grep'] == (0, 15)
    assert tc.total_types == 2


def test_gather_zero_fills_both_columns(tmp_path: Path) -> None:
    main = _write(tmp_path, 'main.jsonl', [_line('m1', ['Bash'])])
    sub1 = _write(tmp_path, 'a1.jsonl', [_line('s1', ['Bash', 'Read'])])
    tc = ToolCounts.gather(main, [_sub(sub1)], None)
    assert tc.counts['Bash'] == (1, 1)
    assert tc.counts['Read'] == (0, 1)


def test_gather_empty_when_nothing_counted(tmp_path: Path) -> None:
    main = _write(tmp_path, 'main.jsonl', [_line('m1', ['TodoWrite'])])
    tc = ToolCounts.gather(main, [], None)
    assert tc.counts == {}
    assert tc.total_types == 0
