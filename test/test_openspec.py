"""Tests for OpenSpec._find_root and OpenSpec.from_cwd."""
from pathlib import Path

import yas.info.openspec as openspec_mod


def test_find_root_walks_upward(tmp_path: Path) -> None:
    """_find_root walks up from a subdirectory to find openspec/."""
    openspec_dir = tmp_path / 'openspec' / 'specs'
    openspec_dir.mkdir(parents=True)
    sub = tmp_path / 'sub'
    sub.mkdir()

    result = openspec_mod.OpenSpec._find_root(str(sub))
    assert result == str(tmp_path / 'openspec')


def test_find_root_no_openspec_returns_empty(tmp_path: Path) -> None:
    """_find_root returns '' when no openspec/ directory is found."""
    result = openspec_mod.OpenSpec._find_root(str(tmp_path))
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

    result = openspec_mod.OpenSpec.from_cwd(str(tmp_path))
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

    result = openspec_mod.OpenSpec.from_cwd(str(tmp_path))
    assert result.changes == []


def test_empty_tasks_excluded(tmp_path: Path) -> None:
    """A tasks.md with no checkbox lines is excluded from results."""
    changes_dir = tmp_path / 'openspec' / 'changes' / 'empty-change'
    changes_dir.mkdir(parents=True)
    (changes_dir / 'tasks.md').write_text('# No tasks here\nJust prose.\n')

    result = openspec_mod.OpenSpec.from_cwd(str(tmp_path))
    assert result.changes == []
