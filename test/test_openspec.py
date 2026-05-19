"""Tests for OpenSpec._find_root and OpenSpec.from_cwd."""
import statusline_command as sl


# ---------------------------------------------------------------------------
# 7.2  _find_root walks upward to find an openspec/ directory
# ---------------------------------------------------------------------------

def test_find_root_walks_upward(tmp_path):
    """_find_root walks up from a subdirectory to find openspec/."""
    openspec_dir = tmp_path / 'openspec' / 'specs'
    openspec_dir.mkdir(parents=True)
    sub = tmp_path / 'sub'
    sub.mkdir()

    result = sl.OpenSpec._find_root(str(sub))
    assert result == str(tmp_path / 'openspec')


def test_find_root_no_openspec_returns_empty(tmp_path):
    """_find_root returns '' when no openspec/ directory is found."""
    result = sl.OpenSpec._find_root(str(tmp_path))
    assert result == ''


# ---------------------------------------------------------------------------
# 7.3  Counts - [ ] vs - [x] lines in tasks.md
# ---------------------------------------------------------------------------

def test_counts_open_and_done_tasks(tmp_path):
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


# ---------------------------------------------------------------------------
# 7.4  Archived changes are excluded
# ---------------------------------------------------------------------------

def test_archived_changes_excluded(tmp_path):
    """Changes under /archive/ are excluded from results."""
    archive_dir = tmp_path / 'openspec' / 'changes' / 'archive' / 'old-change'
    archive_dir.mkdir(parents=True)
    (archive_dir / 'tasks.md').write_text('- [ ] task\n')

    result = sl.OpenSpec.from_cwd(str(tmp_path))
    assert result.changes == []


# ---------------------------------------------------------------------------
# 7.5  tasks.md with zero checkboxes is excluded
# ---------------------------------------------------------------------------

def test_empty_tasks_excluded(tmp_path):
    """A tasks.md with no checkbox lines is excluded from results."""
    changes_dir = tmp_path / 'openspec' / 'changes' / 'empty-change'
    changes_dir.mkdir(parents=True)
    (changes_dir / 'tasks.md').write_text('# No tasks here\nJust prose.\n')

    result = sl.OpenSpec.from_cwd(str(tmp_path))
    assert result.changes == []
