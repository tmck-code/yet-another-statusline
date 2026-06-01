"""Tests for TaskList.from_session and visibility logic."""
import json
import time
from pathlib import Path

import yas.info.tasks as tasks


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
    # D5: the freshness cap only applies when nothing is in_progress, so this
    # case uses two pending tasks (no in_progress to pin it visible).
    now = time.time()
    old = now - tasks.TaskList.FRESHNESS_CAP - 5
    path = _write_transcript(tmp_path, [
        _create_line('A', 'Doing A', old),
        _create_line('B', 'Doing B', old),
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


# --- D1: Per-task timestamps -------------------------------------------------

def test_in_progress_sets_started_at_and_clears_completed_at(tmp_path: Path) -> None:
    now = time.time()
    path = _write_transcript(tmp_path, [
        _create_line('A', 'Doing A', now - 30),
        _update_line(1, 'in_progress', now - 20),
    ])

    result = tasks.TaskList.from_session(str(path))

    assert result.tasks[0].started_at == pytest_approx(now - 20)
    assert result.tasks[0].completed_at is None


def test_completed_sets_completed_at(tmp_path: Path) -> None:
    now = time.time()
    path = _write_transcript(tmp_path, [
        _create_line('A', 'Doing A', now - 30),
        _update_line(1, 'in_progress', now - 25),
        _update_line(1, 'completed', now - 10),
    ])

    result = tasks.TaskList.from_session(str(path))

    assert result.tasks[0].started_at == pytest_approx(now - 25)
    assert result.tasks[0].completed_at == pytest_approx(now - 10)


def test_reopen_overwrites_started_at_and_clears_completed_at(tmp_path: Path) -> None:
    now = time.time()
    path = _write_transcript(tmp_path, [
        _create_line('A', 'Doing A', now - 60),
        _update_line(1, 'in_progress', now - 50),
        _update_line(1, 'completed', now - 40),
        _update_line(1, 'in_progress', now - 10),
    ])

    result = tasks.TaskList.from_session(str(path))

    assert result.tasks[0].status == 'in_progress'
    assert result.tasks[0].started_at == pytest_approx(now - 10)
    assert result.tasks[0].completed_at is None


def test_pending_to_completed_leaves_started_at_none(tmp_path: Path) -> None:
    now = time.time()
    path = _write_transcript(tmp_path, [
        _create_line('A', 'Doing A', now - 30),
        _update_line(1, 'completed', now - 10),
    ])

    result = tasks.TaskList.from_session(str(path))

    assert result.tasks[0].started_at is None
    assert result.tasks[0].completed_at == pytest_approx(now - 10)


# --- D2: Plan Generation scoping --------------------------------------------

def test_create_while_all_completed_starts_fresh_generation(tmp_path: Path) -> None:
    now = time.time()
    path = _write_transcript(tmp_path, [
        _create_line('Old A', 'Old A', now - 60),
        _create_line('Old B', 'Old B', now - 59),
        _update_line(1, 'completed', now - 50),
        _update_line(2, 'completed', now - 45),
        _create_line('New A', 'New A', now - 20),
    ])

    result = tasks.TaskList.from_session(str(path))

    assert [t.id for t in result.tasks] == [1]
    assert [t.subject for t in result.tasks] == ['New A']
    assert result.total == 1
    assert result.completed == 0


def test_create_while_work_open_appends(tmp_path: Path) -> None:
    now = time.time()
    path = _write_transcript(tmp_path, [
        _create_line('A', 'A', now - 60),
        _update_line(1, 'in_progress', now - 50),
        _create_line('B', 'B', now - 40),
    ])

    result = tasks.TaskList.from_session(str(path))

    assert [t.id for t in result.tasks] == [1, 2]
    assert [t.subject for t in result.tasks] == ['A', 'B']


def test_count_reflects_only_latest_generation(tmp_path: Path) -> None:
    now = time.time()
    path = _write_transcript(tmp_path, [
        # Generation 1: two tasks, both completed
        _create_line('G1 A', 'G1 A', now - 90),
        _create_line('G1 B', 'G1 B', now - 89),
        _update_line(1, 'completed', now - 80),
        _update_line(2, 'completed', now - 75),
        # Generation 2 starts here
        _create_line('G2 A', 'G2 A', now - 60),
        _create_line('G2 B', 'G2 B', now - 59),
        _create_line('G2 C', 'G2 C', now - 58),
        _update_line(1, 'completed', now - 40),
    ])

    result = tasks.TaskList.from_session(str(path))

    assert result.total == 3
    assert result.completed == 1
    assert [t.subject for t in result.tasks] == ['G2 A', 'G2 B', 'G2 C']


def test_update_after_reset_resolves_against_new_ids(tmp_path: Path) -> None:
    now = time.time()
    path = _write_transcript(tmp_path, [
        _create_line('Old', 'Old', now - 60),
        _update_line(1, 'completed', now - 50),
        _create_line('New', 'New', now - 30),
        _update_line(1, 'in_progress', now - 10),
    ])

    result = tasks.TaskList.from_session(str(path))

    assert result.tasks[0].subject == 'New'
    assert result.tasks[0].status == 'in_progress'


# --- D5: Pinned visibility while active -------------------------------------

def test_is_visible_pinned_past_freshness_cap_when_in_progress(tmp_path: Path) -> None:
    now = time.time()
    old = now - tasks.TaskList.FRESHNESS_CAP - 60
    path = _write_transcript(tmp_path, [
        _create_line('A', 'Doing A', old),
        _update_line(1, 'in_progress', old),
    ])

    result = tasks.TaskList.from_session(str(path))

    assert result.is_visible(now=now) is True


def test_is_visible_cap_applies_when_nothing_in_progress(tmp_path: Path) -> None:
    now = time.time()
    old = now - tasks.TaskList.FRESHNESS_CAP - 5
    path = _write_transcript(tmp_path, [
        _create_line('A', 'A', old),
        _create_line('B', 'B', old),
        _update_line(1, 'completed', old),
    ])

    result = tasks.TaskList.from_session(str(path))

    # B is still pending (not all completed), but past the 120s cap -> hidden
    assert result.is_visible(now=now) is False


def test_is_visible_grace_applies_when_nothing_in_progress(tmp_path: Path) -> None:
    now = time.time()
    done_ts = now - tasks.TaskList.GRACE_SECONDS - 5
    path = _write_transcript(tmp_path, [
        _create_line('A', 'A', done_ts - 5),
        _update_line(1, 'completed', done_ts),
    ])

    result = tasks.TaskList.from_session(str(path))

    assert result.is_visible(now=now) is False


def pytest_approx(value: float, tol: float = 1.0) -> object:
    import pytest
    return pytest.approx(value, abs=tol)
