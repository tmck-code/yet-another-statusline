import yas.renderer as renderer
from yas.info.git import GitInfo
from yas.render.text import _visible_width
from helper import strip_ansi

Renderer = renderer.Renderer


def test_path_git_clean_no_elapsed() -> None:
    r = Renderer()
    git = GitInfo(branch='main', commit='abc1234')
    out = r.path_git('~/proj', git, '')
    stripped = strip_ansi(out)
    assert '~/proj' in stripped
    assert 'main' in stripped
    assert 'abc1234' in stripped
    assert '●' not in stripped
    assert '*' not in stripped
    assert '[' not in stripped


def test_path_git_dirty_with_elapsed() -> None:
    r = Renderer()
    git = GitInfo(branch='main', commit='abc1234', modified=3, untracked=1)
    out = r.path_git('~/proj', git, '12m')
    stripped = strip_ansi(out)
    assert '*3' in stripped   # modified
    assert '•1' in stripped   # untracked
    assert '[12m]' in stripped


def test_path_git_zero_elapsed_suppressed() -> None:
    r = Renderer()
    git = GitInfo(branch='main', commit='abc1234')
    out = r.path_git('~/proj', git, '0m')
    stripped = strip_ansi(out)
    assert '[0m]' not in stripped


def test_path_git_compact_no_commit_no_dirty() -> None:
    r = Renderer()
    git = GitInfo(branch='main', commit='abc1234', modified=3, untracked=1)
    out = r.path_git_compact('~/proj', git)
    stripped = strip_ansi(out)
    assert '~/proj' in stripped
    assert 'main' in stripped
    assert 'abc1234' not in stripped
    assert '●' not in stripped
    assert '*' not in stripped


# path_git keyword-flag regression (task 4.3)

class TestPathGitFlags:
    def test_defaults_byte_identical(self) -> None:
        r = Renderer()
        git = GitInfo(branch='feat/login', commit='abc1234', modified=2, untracked=1)
        explicit = r.path_git('~/proj', git, '5m',
                              show_commit=True, show_dirty=True, show_elapsed=True)
        default  = r.path_git('~/proj', git, '5m')
        assert explicit == default

    def test_show_commit_false_omits_hash(self) -> None:
        r = Renderer()
        git = GitInfo(branch='main', commit='abc1234', modified=1)
        out = r.path_git('~/proj', git, '3m', show_commit=False)
        stripped = strip_ansi(out)
        assert 'abc1234' not in stripped
        assert '/' not in stripped.split('main')[1]
        assert '*1' in stripped   # modified
        assert '[3m]' in stripped

    def test_show_elapsed_false_omits_tail(self) -> None:
        r = Renderer()
        git = GitInfo(branch='main', commit='abc1234')
        out = r.path_git('~/proj', git, '5m', show_elapsed=False)
        stripped = strip_ansi(out)
        assert '[5m]' not in stripped
        assert 'abc1234' in stripped

    def test_show_dirty_false_omits_markers(self) -> None:
        r = Renderer()
        git = GitInfo(branch='main', commit='abc1234', modified=3, untracked=2)
        out = r.path_git('~/proj', git, '5m', show_dirty=False)
        stripped = strip_ansi(out)
        assert '●' not in stripped
        assert '*' not in stripped
        assert 'abc1234' in stripped
        assert '[5m]' in stripped


# fit_path ladder (task 4.2)

class TestFitPath:
    def _git(self, branch: str = 'main', commit: str = 'abc1234',
             modified: int = 2, untracked: int = 1) -> GitInfo:
        return GitInfo(branch=branch, commit=commit,
                       modified=modified, untracked=untracked)

    def test_full_fits_returns_full(self) -> None:
        r = Renderer()
        git = self._git()
        full = r.path_git('~/p', git, '2m')
        result = r.fit_path('~/p', git, '2m', _visible_width(full) + 10)
        assert result == full

    def test_no_commit_when_full_overflows(self) -> None:
        r = Renderer()
        git = self._git()
        no_commit = r.path_git('~/p', git, '2m', show_commit=False)
        target_w = _visible_width(no_commit)
        result = r.fit_path('~/p', git, '2m', target_w)
        assert strip_ansi(result) == strip_ansi(no_commit)
        assert _visible_width(result) <= target_w
        assert 'abc1234' not in strip_ansi(result)

    def test_no_elapsed_when_no_commit_still_overflows(self) -> None:
        r = Renderer()
        git = self._git()
        no_elapsed = r.path_git('~/p', git, '2m',
                                show_commit=False, show_elapsed=False)
        target_w = _visible_width(no_elapsed)
        result = r.fit_path('~/p', git, '2m', target_w)
        assert _visible_width(result) <= target_w
        assert '[2m]' not in strip_ansi(result)
        assert 'abc1234' not in strip_ansi(result)

    def test_no_dirty_when_still_overflows(self) -> None:
        r = Renderer()
        git = self._git()
        clean = r.path_git('~/p', git, '2m',
                           show_commit=False, show_elapsed=False, show_dirty=False)
        target_w = _visible_width(clean)
        result = r.fit_path('~/p', git, '2m', target_w)
        assert _visible_width(result) <= target_w
        assert '●' not in strip_ansi(result)

    def test_compact_when_all_path_git_overflow(self) -> None:
        r = Renderer()
        git = self._git()
        compact = r.path_git_compact('~/p', git)
        target_w = _visible_width(compact)
        result = r.fit_path('~/p', git, '2m', target_w)
        assert strip_ansi(result) == strip_ansi(compact)

    def test_ellipsis_pwd_when_compact_overflows(self) -> None:
        r = Renderer()
        git = self._git(branch='x')
        compact = r.path_git_compact('~/very-long-path-name', git)
        target_w = _visible_width(compact) - 4
        result = r.fit_path('~/very-long-path-name', git, '', target_w)
        assert _visible_width(result) <= target_w
        assert '…' in strip_ansi(result)
        assert 'x' in strip_ansi(result)

    def test_ellipsis_branch_as_last_resort(self) -> None:
        r = Renderer()
        git = self._git(branch='feature/very-long-branch-name')
        pwd = '~/also-very-long-path'
        compact = r.path_git_compact(pwd, git)
        target_w = max(5, _visible_width(compact) - 20)
        result = r.fit_path(pwd, git, '', target_w)
        assert _visible_width(result) <= target_w + 2  # small tolerance for wide chars

    def test_compact_only_skips_path_git_variants(self) -> None:
        r = Renderer()
        git = self._git()
        compact = r.path_git_compact('~/p', git)
        # target_w fits compact but not full
        target_w = _visible_width(compact)
        result = r.fit_path('~/p', git, '2m', target_w, compact_only=True)
        assert strip_ansi(result) == strip_ansi(compact)

    def test_compact_only_never_returns_full_path_git(self) -> None:
        r = Renderer()
        git = self._git()
        # Very wide target_w — compact_only should still not return full path_git
        result = r.fit_path('~/p', git, '2m', 999, compact_only=True)
        assert 'abc1234' not in strip_ansi(result)
