"""Tests for OpenSpec._find_root and OpenSpec.from_cwd."""
from pathlib import Path

import statusline_command as sl



def test_find_root_walks_upward(tmp_path: Path) -> None:
    """_find_root walks up from a subdirectory to find openspec/."""
    openspec_dir = tmp_path / 'openspec' / 'specs'
    openspec_dir.mkdir(parents=True)
    sub = tmp_path / 'sub'
    sub.mkdir()

    result = sl.OpenSpec._find_root(str(sub))
    assert result == str(tmp_path / 'openspec')


def test_find_root_no_openspec_returns_empty(tmp_path: Path) -> None:
    """_find_root returns '' when no openspec/ directory is found."""
    result = sl.OpenSpec._find_root(str(tmp_path))
    assert result == ''



def test_counts_open_and_done_tasks(tmp_path: Path) -> None:
    """from_cwd counts - [ ] and - [x] lines per tasks.md."""
    changes_dir = tmp_path / 'openspec' / 'changes' / 'my-change'
    changes_dir.mkdir(parents=True)
    (changes_dir / 'tasks.md').write_text(
        '- [ ] one\n'
        '- [x] two\n'
        '- [x] three\n'
    )

    result = sl.OpenSpec.from_cwd(str(tmp_path))
    assert len(result.changes) == 1
    name, done, total = result.changes[0]
    assert name == 'my-change'
    assert done == 2
    assert total == 3



def test_archived_changes_excluded(tmp_path: Path) -> None:
    """Changes under /archive/ are excluded from results."""
    archive_dir = tmp_path / 'openspec' / 'changes' / 'archive' / 'old-change'
    archive_dir.mkdir(parents=True)
    (archive_dir / 'tasks.md').write_text('- [ ] task\n')

    result = sl.OpenSpec.from_cwd(str(tmp_path))
    assert result.changes == []


def test_project_under_archive_ancestor_still_detected(tmp_path: Path) -> None:
    """Audit OS-ARCHIVE: the old '/archive/' substring filter wrongly excluded an
    ENTIRE project that merely lived under a dir named 'archive'. The anchored
    relative_to(root).parts check only skips archive/ INSIDE the openspec root."""
    changes_dir = tmp_path / 'archive' / 'myproject' / 'openspec' / 'changes' / 'add-foo'
    changes_dir.mkdir(parents=True)
    (changes_dir / 'tasks.md').write_text('- [x] a\n- [ ] b\n')

    result = sl.OpenSpec.from_cwd(str(tmp_path / 'archive' / 'myproject'))
    assert result.changes == [('add-foo', 1, 2)]


def test_active_and_archived_mixed(tmp_path: Path) -> None:
    """An active change and an archived one under the same root: only the active."""
    active = tmp_path / 'openspec' / 'changes' / 'add-foo'
    active.mkdir(parents=True)
    (active / 'tasks.md').write_text('- [x] a\n- [ ] b\n')
    archived = tmp_path / 'openspec' / 'changes' / 'archive' / 'old'
    archived.mkdir(parents=True)
    (archived / 'tasks.md').write_text('- [x] a\n- [x] b\n')

    result = sl.OpenSpec.from_cwd(str(tmp_path))
    assert result.changes == [('add-foo', 1, 2)]



def test_empty_tasks_excluded(tmp_path: Path) -> None:
    """A tasks.md with no checkbox lines is excluded from results."""
    changes_dir = tmp_path / 'openspec' / 'changes' / 'empty-change'
    changes_dir.mkdir(parents=True)
    (changes_dir / 'tasks.md').write_text('# No tasks here\nJust prose.\n')

    result = sl.OpenSpec.from_cwd(str(tmp_path))
    assert result.changes == []
