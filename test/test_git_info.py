"""Tests for GitInfo._find_repo, _read_head, and from_cwd."""
import shutil
import subprocess

import pytest

import statusline_command as sl


# ---------------------------------------------------------------------------
# 6.2  Helpers to build a synthetic .git directory (no shell-out)
# ---------------------------------------------------------------------------

def _make_git_dir(base, branch='main', commit='abcdef1234567890'):
    """Create a minimal .git directory structure in base."""
    gitdir = base / '.git'
    gitdir.mkdir(parents=True, exist_ok=True)
    (gitdir / 'HEAD').write_text(f'ref: refs/heads/{branch}\n')
    refs_heads = gitdir / 'refs' / 'heads'
    refs_heads.mkdir(parents=True, exist_ok=True)
    (refs_heads / branch).write_text(commit + '\n')
    return gitdir


# ---------------------------------------------------------------------------
# 6.3  _find_repo walks upward to find .git
# ---------------------------------------------------------------------------

def test_find_repo_walks_upward(tmp_path):
    """_find_repo walks from a deep subdirectory up to where .git lives."""
    (tmp_path / '.git').mkdir()
    deep = tmp_path / 'a' / 'b' / 'c'
    deep.mkdir(parents=True)

    repo, gitdir = sl.GitInfo._find_repo(str(deep))
    assert repo == str(tmp_path)
    assert gitdir == str(tmp_path / '.git')


def test_find_repo_no_git_returns_empty(tmp_path):
    """_find_repo returns ('', '') when no .git is found."""
    deep = tmp_path / 'x' / 'y'
    deep.mkdir(parents=True)
    repo, gitdir = sl.GitInfo._find_repo(str(deep))
    assert repo == ''
    assert gitdir == ''


# ---------------------------------------------------------------------------
# 6.4  _read_head: ref HEAD with branch + commit truncated to 9 chars
# ---------------------------------------------------------------------------

def test_read_head_ref_branch(tmp_path):
    """_read_head parses ref: HEAD and returns branch + 9-char commit."""
    gitdir = _make_git_dir(tmp_path, branch='main', commit='abcdef1234567890')
    branch, commit = sl.GitInfo._read_head(str(gitdir))
    assert branch == 'main'
    assert commit == 'abcdef123'  # first 9 chars


# ---------------------------------------------------------------------------
# 6.5  _read_head: detached HEAD
# ---------------------------------------------------------------------------

def test_read_head_detached(tmp_path):
    """_read_head returns ('d:<sha[:7]>', '') for a detached HEAD."""
    sha = 'abcdef1234567890abcdef1234567890abcdef12'
    gitdir = tmp_path / '.git'
    gitdir.mkdir()
    (gitdir / 'HEAD').write_text(sha + '\n')

    branch, commit = sl.GitInfo._read_head(str(gitdir))
    assert branch == f'd:{sha[:7]}'
    assert commit == ''


# ---------------------------------------------------------------------------
# 6.6  GitInfo.from_cwd returns empty GitInfo for non-repo path
# ---------------------------------------------------------------------------

def test_from_cwd_non_repo(tmp_path):
    """from_cwd returns an empty GitInfo when no .git exists."""
    result = sl.GitInfo.from_cwd(str(tmp_path))
    assert result == sl.GitInfo(branch='', commit='', modified=0, untracked=0)


# ---------------------------------------------------------------------------
# 6.7  Integration test: real git repo (skipped if git not installed)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
def test_from_cwd_real_repo(tmp_path):
    """from_cwd populates modified and untracked counts from a real repo."""
    subprocess.run(['git', 'init', str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ['git', '-C', str(tmp_path), 'config', 'user.email', 'test@test.com'],
        check=True, capture_output=True,
    )
    subprocess.run(
        ['git', '-C', str(tmp_path), 'config', 'user.name', 'Test'],
        check=True, capture_output=True,
    )

    # Create and commit a tracked file
    tracked = tmp_path / 'tracked.txt'
    tracked.write_text('initial\n')
    subprocess.run(['git', '-C', str(tmp_path), 'add', 'tracked.txt'], check=True, capture_output=True)
    subprocess.run(
        ['git', '-C', str(tmp_path), 'commit', '-m', 'init'],
        check=True, capture_output=True,
    )

    # Modify the tracked file (modified count = 1)
    tracked.write_text('changed\n')

    # Create an untracked file (untracked count = 1)
    (tmp_path / 'untracked.txt').write_text('new\n')

    result = sl.GitInfo.from_cwd(str(tmp_path))
    assert result.modified == 1
    assert result.untracked == 1
