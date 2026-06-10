import yas.renderer as renderer
from yas.info.git import GitInfo
from yas.render.text import _visible_width
from helper import strip_ansi

Renderer = renderer.Renderer


def test_path_git_clean() -> None:
    r = Renderer()
    git = GitInfo(branch='main', commit='abc1234')
    out = r.path_git('~/proj', git)
    stripped = strip_ansi(out)
    assert '~/proj' in stripped
    assert 'main' in stripped
    assert 'abc1234' in stripped
    assert '●' not in stripped
    assert '*' not in stripped
    assert '[' not in stripped


def test_path_git_dirty() -> None:
    r = Renderer()
    git = GitInfo(branch='main', commit='abc1234', modified=3, untracked=1)
    out = r.path_git('~/proj', git)
    stripped = strip_ansi(out)
    assert '*3' in stripped   # modified
    assert '•1' in stripped   # untracked


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


def test_elapsed_section_shows_clock_time() -> None:
    r = Renderer()
    text, w = r.elapsed_section('0:12:34')
    stripped = strip_ansi(text)
    assert '0:12:34' in stripped
    assert w == _visible_width(text)


def test_elapsed_section_empty_string_still_renders() -> None:
    r = Renderer()
    text, w = r.elapsed_section('')
    assert w >= 0


# path_git keyword-flag regression (task 4.3)

class TestPathGitFlags:
    def test_defaults_byte_identical(self) -> None:
        r = Renderer()
        git = GitInfo(branch='feat/login', commit='abc1234', modified=2, untracked=1)
        explicit = r.path_git('~/proj', git, show_commit=True, show_dirty=True)
        default  = r.path_git('~/proj', git)
        assert explicit == default

    def test_show_commit_false_omits_hash(self) -> None:
        r = Renderer()
        git = GitInfo(branch='main', commit='abc1234', modified=1)
        out = r.path_git('~/proj', git, show_commit=False)
        stripped = strip_ansi(out)
        assert 'abc1234' not in stripped
        assert '/' not in stripped.split('main')[1]
        assert '*1' in stripped   # modified

    def test_show_dirty_false_omits_markers(self) -> None:
        r = Renderer()
        git = GitInfo(branch='main', commit='abc1234', modified=3, untracked=2)
        out = r.path_git('~/proj', git, show_dirty=False)
        stripped = strip_ansi(out)
        assert '●' not in stripped
        assert '*' not in stripped
        assert 'abc1234' in stripped


# fit_path ladder (task 4.2)

class TestFitPath:
    def _git(self, branch: str = 'main', commit: str = 'abc1234',
             modified: int = 2, untracked: int = 1) -> GitInfo:
        return GitInfo(branch=branch, commit=commit,
                       modified=modified, untracked=untracked)

    def test_full_fits_returns_full(self) -> None:
        r = Renderer()
        git = self._git()
        full = r.path_git('~/p', git)
        result = r.fit_path('~/p', git, _visible_width(full) + 10)
        assert result == full

    def test_no_commit_when_full_overflows(self) -> None:
        r = Renderer()
        git = self._git()
        no_commit = r.path_git('~/p', git, show_commit=False)
        target_w = _visible_width(no_commit)
        result = r.fit_path('~/p', git, target_w)
        assert strip_ansi(result) == strip_ansi(no_commit)
        assert _visible_width(result) <= target_w
        assert 'abc1234' not in strip_ansi(result)

    def test_no_dirty_when_still_overflows(self) -> None:
        r = Renderer()
        git = self._git()
        clean = r.path_git('~/p', git, show_commit=False, show_dirty=False)
        target_w = _visible_width(clean)
        result = r.fit_path('~/p', git, target_w)
        assert _visible_width(result) <= target_w
        assert '●' not in strip_ansi(result)

    def test_compact_when_all_path_git_overflow(self) -> None:
        r = Renderer()
        git = self._git()
        compact = r.path_git_compact('~/p', git)
        target_w = _visible_width(compact)
        result = r.fit_path('~/p', git, target_w)
        assert strip_ansi(result) == strip_ansi(compact)

    def test_omits_pwd_whole_when_compact_overflows(self) -> None:
        # Below compact path+branch the path is dropped whole (no middle
        # ellipsis): the branch survives and the distinctive pwd is gone.
        r = Renderer()
        git = self._git(branch='x')
        pwd = '~/very-long-path-name'
        branch_only = r.path_git(
            pwd, git, show_path=False, show_commit=False, show_dirty=False,
        )
        target_w = _visible_width(branch_only)
        result = r.fit_path(pwd, git, target_w)
        stripped = strip_ansi(result)
        assert _visible_width(result) <= target_w
        assert pwd not in stripped       # path omitted whole
        assert 'x' in stripped           # branch retained
        assert '…' not in stripped       # never middle-ellipsized

    def test_floor_when_branch_does_not_fit(self) -> None:
        # When not even the branch fits, fit_path falls back to the glyph-only
        # floor — within target, no ellipsis (no ellipsis-fallback any more).
        r = Renderer()
        git = self._git(branch='feature/very-long-branch-name')
        pwd = '~/also-very-long-path'
        result = r.fit_path(pwd, git, 2)
        assert result == r.path_glyph_only()
        assert _visible_width(result) <= 2
        assert '…' not in strip_ansi(result)

    def test_compact_only_skips_path_git_variants(self) -> None:
        r = Renderer()
        git = self._git()
        compact = r.path_git_compact('~/p', git)
        # target_w fits compact but not full
        target_w = _visible_width(compact)
        result = r.fit_path('~/p', git, target_w, compact_only=True)
        assert strip_ansi(result) == strip_ansi(compact)

    def test_compact_only_never_returns_full_path_git(self) -> None:
        r = Renderer()
        git = self._git()
        # Very wide target_w — compact_only should still not return full path_git
        result = r.fit_path('~/p', git, 999, compact_only=True)
        assert 'abc1234' not in strip_ansi(result)
