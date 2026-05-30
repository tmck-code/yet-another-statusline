"""Tests for GitInfo._find_repo, _read_head, and from_cwd."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import statusline_command as sl



def _make_git_dir(base: Path, branch: str = 'main', commit: str = 'abcdef1234567890') -> Path:
    """Create a minimal .git directory structure in base."""
    gitdir = base / '.git'
    gitdir.mkdir(parents=True, exist_ok=True)
    (gitdir / 'HEAD').write_text(f'ref: refs/heads/{branch}\n')
    refs_heads = gitdir / 'refs' / 'heads'
    refs_heads.mkdir(parents=True, exist_ok=True)
    (refs_heads / branch).write_text(commit + '\n')
    return gitdir



def test_find_repo_walks_upward(tmp_path: Path) -> None:
    """_find_repo walks from a deep subdirectory up to where .git lives."""
    (tmp_path / '.git').mkdir()
    deep = tmp_path / 'a' / 'b' / 'c'
    deep.mkdir(parents=True)

    repo, gitdir = sl.GitInfo._find_repo(str(deep))
    assert repo == str(tmp_path)
    assert gitdir == str(tmp_path / '.git')


def test_find_repo_no_git_returns_empty(tmp_path: Path) -> None:
    """_find_repo returns ('', '') when no .git is found."""
    deep = tmp_path / 'x' / 'y'
    deep.mkdir(parents=True)
    repo, gitdir = sl.GitInfo._find_repo(str(deep))
    assert repo == ''
    assert gitdir == ''



def test_read_head_ref_branch(tmp_path: Path) -> None:
    """_read_head parses ref: HEAD and returns branch + 9-char commit."""
    gitdir = _make_git_dir(tmp_path, branch='main', commit='abcdef1234567890')
    branch, commit = sl.GitInfo._read_head(str(gitdir))
    assert branch == 'main'
    assert commit == 'abcdef123'  # first 9 chars



def test_read_head_detached(tmp_path: Path) -> None:
    """_read_head returns ('d:<sha[:7]>', '') for a detached HEAD."""
    sha = 'abcdef1234567890abcdef1234567890abcdef12'
    gitdir = tmp_path / '.git'
    gitdir.mkdir()
    (gitdir / 'HEAD').write_text(sha + '\n')

    branch, commit = sl.GitInfo._read_head(str(gitdir))
    assert branch == f'd:{sha[:7]}'
    assert commit == ''



def test_from_cwd_non_repo(tmp_path: Path) -> None:
    """from_cwd returns an empty GitInfo when no .git exists."""
    result = sl.GitInfo.from_cwd(str(tmp_path))
    assert result == sl.GitInfo(branch='', commit='', modified=0, untracked=0)



@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
def test_from_cwd_real_repo(tmp_path: Path) -> None:
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


# --- G2: branch namespace preserved ------------------------------------------

def test_read_head_preserves_branch_namespace(tmp_path: Path) -> None:
    """A 'feature/foo' branch keeps its namespace instead of collapsing to 'foo'."""
    gitdir = tmp_path / '.git'
    (gitdir / 'refs' / 'heads' / 'feature').mkdir(parents=True)
    (gitdir / 'HEAD').write_text('ref: refs/heads/feature/foo\n')
    (gitdir / 'refs' / 'heads' / 'feature' / 'foo').write_text('deadbeef0000\n')

    branch, commit = sl.GitInfo._read_head(str(gitdir))
    assert branch == 'feature/foo'
    assert commit == 'deadbeef0'


# --- G1: packed-refs commit lookup -------------------------------------------

def test_read_head_packed_refs_commit(tmp_path: Path) -> None:
    """Commit is resolved from packed-refs when there is no loose ref file."""
    gitdir = tmp_path / '.git'
    gitdir.mkdir()
    (gitdir / 'HEAD').write_text('ref: refs/heads/main\n')
    (gitdir / 'packed-refs').write_text(
        '# pack-refs with: peeled fully-peeled sorted\n'
        'cafebabe1234567890 refs/heads/main\n'
    )

    branch, commit = sl.GitInfo._read_head(str(gitdir))
    assert branch == 'main'
    assert commit == 'cafebabe1'


# --- G1: linked worktree (.git is a FILE pointing at the worktree gitdir) -----

def test_find_repo_and_head_resolve_worktree(tmp_path: Path) -> None:
    """A worktree's `.git` file resolves to its gitdir; HEAD + commit (via the
    common dir) populate instead of going blank."""
    main_gitdir = tmp_path / 'main' / '.git'
    (main_gitdir / 'refs' / 'heads').mkdir(parents=True)
    (main_gitdir / 'refs' / 'heads' / 'wtbranch').write_text('abc123def456\n')

    wt_gitdir = main_gitdir / 'worktrees' / 'wt'
    wt_gitdir.mkdir(parents=True)
    (wt_gitdir / 'HEAD').write_text('ref: refs/heads/wtbranch\n')
    (wt_gitdir / 'commondir').write_text('../..\n')  # -> main/.git

    wt = tmp_path / 'wt'
    wt.mkdir()
    (wt / '.git').write_text(f'gitdir: {wt_gitdir}\n')

    repo, gd = sl.GitInfo._find_repo(str(wt))
    assert repo == str(wt)
    assert gd == str(wt_gitdir.resolve())

    branch, commit = sl.GitInfo._read_head(gd)
    assert branch == 'wtbranch'
    assert commit == 'abc123def'


def test_resolve_gitdir_malformed_file_returns_empty(tmp_path: Path) -> None:
    """A `.git` file without a gitdir: pointer resolves to '' (graceful)."""
    (tmp_path / '.git').write_text('garbage\n')
    repo, gd = sl.GitInfo._find_repo(str(tmp_path))
    assert repo == str(tmp_path)
    assert gd == ''
    # _read_head('') is empty, so from_cwd stays blank rather than crashing.
    assert sl.GitInfo._read_head(gd) == ('', '')


# --- P5: per-session git-status (dirty) cache --------------------------------

def _dirty_spy(calls: dict) -> object:
    def _dirty(repo: str) -> tuple[int, int, int, int]:
        calls['n'] += 1
        return (1, 2, 3, 4)
    return _dirty


def test_dirty_cache_hit_then_ttl_expiry(tmp_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {'n': 0}
    monkeypatch.setattr(sl.GitInfo, '_dirty', staticmethod(_dirty_spy(calls)))
    monkeypatch.setattr(sl.time, 'time', lambda: 1000.0)

    assert sl.GitInfo._dirty_cached('/repo', '/repo', 's1') == (1, 2, 3, 4)
    assert calls['n'] == 1                       # miss -> ran git, cached
    assert sl.GitInfo._dirty_cached('/repo', '/repo', 's1') == (1, 2, 3, 4)
    assert calls['n'] == 1                       # hit -> no git

    monkeypatch.setattr(sl.time, 'time', lambda: 1000.0 + sl.GIT_CACHE_TTL + 1)
    assert sl.GitInfo._dirty_cached('/repo', '/repo', 's1') == (1, 2, 3, 4)
    assert calls['n'] == 2                       # expired -> ran git again


def test_dirty_cache_cwd_mismatch_recomputes(tmp_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {'n': 0}
    monkeypatch.setattr(sl.GitInfo, '_dirty', staticmethod(_dirty_spy(calls)))
    monkeypatch.setattr(sl.time, 'time', lambda: 1000.0)
    sl.GitInfo._dirty_cached('/repo', '/repo', 's1')
    sl.GitInfo._dirty_cached('/repo', '/elsewhere', 's1')   # same session, different cwd
    assert calls['n'] == 2


def test_dirty_cache_disabled_without_session(tmp_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {'n': 0}
    monkeypatch.setattr(sl.GitInfo, '_dirty', staticmethod(_dirty_spy(calls)))
    sl.GitInfo._dirty_cached('/repo', '/repo', '')
    sl.GitInfo._dirty_cached('/repo', '/repo', '')
    assert calls['n'] == 2                       # no caching without a session id
    assert not (tmp_home / '.claude' / 'statusline-git').exists()


def test_from_cwd_branch_live_dirty_cached(tmp_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = tmp_home / 'repo'
    gitdir = _make_git_dir(base, branch='main')
    monkeypatch.setattr(sl.time, 'time', lambda: 1000.0)
    cache = tmp_home / '.claude' / 'statusline-git' / 's1.json'
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({'v': 1, 'cwd': str(base), 'ts': 1000.0,
                                 'modified': 5, 'untracked': 0, 'deleted': 0, 'renamed': 0}))

    def _no_git(*a: object, **k: object) -> None:
        raise AssertionError('git spawned despite a fresh dirty cache')
    monkeypatch.setattr(sl.subprocess, 'run', _no_git)

    g = sl.GitInfo.from_cwd(str(base), 's1')
    assert g.branch == 'main' and g.modified == 5

    # Switch branch in HEAD: branch must update immediately; dirty stays cached.
    (gitdir / 'refs' / 'heads' / 'feature').mkdir(parents=True, exist_ok=True)
    (gitdir / 'refs' / 'heads' / 'feature' / 'x').write_text('abc1234\n')
    (gitdir / 'HEAD').write_text('ref: refs/heads/feature/x\n')
    g2 = sl.GitInfo.from_cwd(str(base), 's1')
    assert g2.branch == 'feature/x'   # live
    assert g2.modified == 5            # cached
