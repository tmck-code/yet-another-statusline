"""Tests for TaskList.from_session and visibility logic."""
import json
import time
from pathlib import Path

import statusline_command as sl
import statusline.tasks as tasks


def _iso(epoch: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')


def _create_line(subject: str, active_form: str, ts: float) -> str:
    return json.dumps({
        'timestamp': _iso(ts),
        'type': 'assistant',
        'message': {'content': [{
            'type': 'tool_use',
            'name': 'TaskCreate',
            'input': {'subject': subject, 'activeForm': active_form, 'description': ''},
        }]},
    }) + '\n'


def _update_line(task_id: int, status: str, ts: float, **extra: str) -> str:
    inp: dict[str, object] = {'taskId': str(task_id), 'status': status}
    inp.update(extra)
    return json.dumps({
        'timestamp': _iso(ts),
        'type': 'assistant',
        'message': {'content': [{
            'type': 'tool_use',
            'name': 'TaskUpdate',
            'input': inp,
        }]},
    }) + '\n'


def _write_transcript(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / 'transcript.jsonl'
    path.write_text(''.join(lines))
    return path


def test_missing_path_returns_empty() -> None:
    result = tasks.TaskList.from_session('')
    assert result == tasks.TaskList()


def test_nonexistent_path_returns_empty(tmp_path: Path) -> None:
    result = tasks.TaskList.from_session(str(tmp_path / 'nope.jsonl'))
    assert result == tasks.TaskList()


def test_ids_assigned_sequentially(tmp_path: Path) -> None:
    now = time.time()
    path = _write_transcript(tmp_path, [
        _create_line('First', 'Doing first', now - 30),
        _create_line('Second', 'Doing second', now - 25),
        _create_line('Third', 'Doing third', now - 20),
    ])

    result = tasks.TaskList.from_session(str(path))

    assert [t.id for t in result.tasks] == [1, 2, 3]
    assert [t.subject for t in result.tasks] == ['First', 'Second', 'Third']


def test_status_folded_from_updates(tmp_path: Path) -> None:
    now = time.time()
    path = _write_transcript(tmp_path, [
        _create_line('A', 'Doing A', now - 30),
        _create_line('B', 'Doing B', now - 29),
        _update_line(1, 'in_progress', now - 25),
        _update_line(1, 'completed', now - 20),
        _update_line(2, 'in_progress', now - 10),
    ])

    result = tasks.TaskList.from_session(str(path))

    assert result.tasks[0].status == 'completed'
    assert result.tasks[1].status == 'in_progress'


def test_completed_and_total(tmp_path: Path) -> None:
    now = time.time()
    path = _write_transcript(tmp_path, [
        _create_line('A', 'A', now - 30),
        _create_line('B', 'B', now - 29),
        _create_line('C', 'C', now - 28),
        _update_line(1, 'completed', now - 20),
        _update_line(2, 'completed', now - 15),
    ])

    result = tasks.TaskList.from_session(str(path))

    assert result.total == 3
    assert result.completed == 2


def test_active_returns_in_progress(tmp_path: Path) -> None:
    now = time.time()
    path = _write_transcript(tmp_path, [
        _create_line('A', 'Doing A', now - 30),
        _update_line(1, 'in_progress', now - 25),
    ])

    result = tasks.TaskList.from_session(str(path))

    assert result.active is not None
    assert result.active.id == 1


def test_next_pending_returns_first(tmp_path: Path) -> None:
    now = time.time()
    path = _write_transcript(tmp_path, [
        _create_line('A', 'A', now - 30),
        _create_line('B', 'B', now - 29),
        _update_line(1, 'completed', now - 20),
    ])

    result = tasks.TaskList.from_session(str(path))

    assert result.next_pending is not None
    assert result.next_pending.id == 2


def test_taskupdate_can_revise_active_form(tmp_path: Path) -> None:
    now = time.time()
    path = _write_transcript(tmp_path, [
        _create_line('A', 'Doing A', now - 30),
        _update_line(1, 'in_progress', now - 20, activeForm='Doing A revised'),
    ])

    result = tasks.TaskList.from_session(str(path))

    assert result.tasks[0].active_form == 'Doing A revised'


def test_is_visible_true_with_in_progress(tmp_path: Path) -> None:
    now = time.time()
    path = _write_transcript(tmp_path, [
        _create_line('A', 'Doing A', now - 30),
        _update_line(1, 'in_progress', now - 10),
    ])

    result = tasks.TaskList.from_session(str(path))

    assert result.is_visible(now=now) is True


def test_is_visible_false_past_freshness_cap(tmp_path: Path) -> None:
    now = time.time()
    old = now - tasks.TaskList.FRESHNESS_CAP - 5
    path = _write_transcript(tmp_path, [
        _create_line('A', 'Doing A', old),
        _update_line(1, 'in_progress', old),
    ])

    result = tasks.TaskList.from_session(str(path))

    assert result.is_visible(now=now) is False


def test_is_visible_grace_after_all_completed(tmp_path: Path) -> None:
    now = time.time()
    path = _write_transcript(tmp_path, [
        _create_line('A', 'A', now - 30),
        _update_line(1, 'completed', now - 10),
    ])

    result = tasks.TaskList.from_session(str(path))

    assert result.is_visible(now=now) is True


def test_is_visible_false_after_grace_when_all_completed(tmp_path: Path) -> None:
    now = time.time()
    done_ts = now - tasks.TaskList.GRACE_SECONDS - 5
    path = _write_transcript(tmp_path, [
        _create_line('A', 'A', done_ts - 5),
        _update_line(1, 'completed', done_ts),
    ])

    result = tasks.TaskList.from_session(str(path))

    assert result.is_visible(now=now) is False


def test_is_visible_false_when_empty() -> None:
    result = tasks.TaskList()
    assert result.is_visible(now=time.time()) is False


def test_taskupdate_referencing_missing_id_ignored(tmp_path: Path) -> None:
    now = time.time()
    path = _write_transcript(tmp_path, [
        _create_line('A', 'A', now - 30),
        _update_line(99, 'completed', now - 10),
    ])

    result = tasks.TaskList.from_session(str(path))

    assert result.tasks[0].status == 'pending'
    assert result.total == 1
