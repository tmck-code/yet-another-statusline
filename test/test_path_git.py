import statusline_command as sl
from conftest import strip_ansi

_visible_width = sl._visible_width
Renderer = sl.Renderer
GitInfo = sl.GitInfo


def test_path_git_clean_no_elapsed():
    r = Renderer()
    git = GitInfo(branch='main', commit='abc1234')
    out = r.path_git('~/proj', git, '')
    stripped = strip_ansi(out)
    assert '~/proj' in stripped
    assert 'main' in stripped
    assert 'abc1234' in stripped
    assert '✹' not in stripped
    assert '✭' not in stripped
    assert '[' not in stripped


def test_path_git_dirty_with_elapsed():
    r = Renderer()
    git = GitInfo(branch='main', commit='abc1234', modified=3, untracked=1)
    out = r.path_git('~/proj', git, '12m')
    stripped = strip_ansi(out)
    assert '✹ 3' in stripped
    assert '✭ 1' in stripped
    assert '[12m]' in stripped


def test_path_git_zero_elapsed_suppressed():
    r = Renderer()
    git = GitInfo(branch='main', commit='abc1234')
    out = r.path_git('~/proj', git, '0m')
    stripped = strip_ansi(out)
    assert '[0m]' not in stripped


def test_path_git_compact_no_commit_no_dirty():
    r = Renderer()
    git = GitInfo(branch='main', commit='abc1234', modified=3, untracked=1)
    out = r.path_git_compact('~/proj', git)
    stripped = strip_ansi(out)
    assert '~/proj' in stripped
    assert 'main' in stripped
    assert 'abc1234' not in stripped
    assert '✹' not in stripped
    assert '✭' not in stripped
