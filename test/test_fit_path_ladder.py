"""fit_path include/omit ladder (change tasks 3.1-3.4).

The path is a whole unit: shown in full or omitted entirely, never
middle-ellipsized. The branch always outlives the path, and the glyph-only
floor is the overflow-safe terminal state. No `…` (U+2026) may ever appear in
any fit_path output, at any width.
"""

import yas.renderer as renderer
from yas.info.git import GitInfo
from yas.render.text import _visible_width
from helper import strip_ansi

Renderer = renderer.Renderer

ELLIPSIS = '…'  # U+2026 HORIZONTAL ELLIPSIS — must never appear in fit_path output


def _git(branch: str = 'main', commit: str = 'abc1234',
         modified: int = 2, untracked: int = 1) -> GitInfo:
    return GitInfo(branch=branch, commit=commit,
                   modified=modified, untracked=untracked)


# --- 3.1: include/omit ladder drops commit first, then dirty ----------------

def test_wide_target_returns_full_form() -> None:
    r = Renderer()
    git = _git()
    pwd = '~/proj'
    full = r.path_git(pwd, git)
    result = r.fit_path(pwd, git, _visible_width(full) + 10)
    assert result == full


def test_drops_commit_first() -> None:
    r = Renderer()
    git = _git()
    pwd = '~/proj'
    no_commit = r.path_git(pwd, git, show_commit=False)
    # A width that fits no-commit but not the full form.
    target_w = _visible_width(no_commit)
    result = r.fit_path(pwd, git, target_w)
    stripped = strip_ansi(result)
    assert result == no_commit
    assert git.commit not in stripped       # commit hash dropped
    assert git.branch in stripped           # branch still present
    assert ELLIPSIS not in stripped


def test_drops_dirty_after_commit() -> None:
    r = Renderer()
    git = _git()
    pwd = '~/proj'
    no_dirty = r.path_git(pwd, git, show_commit=False, show_dirty=False)
    target_w = _visible_width(no_dirty)
    result = r.fit_path(pwd, git, target_w)
    stripped = strip_ansi(result)
    assert result == no_dirty
    assert git.commit not in stripped
    assert git.branch in stripped
    # dirty markers gone: no untracked/modified counts.
    assert '•' not in stripped
    assert '*' not in stripped
    assert ELLIPSIS not in stripped


# --- 3.2: path omitted whole, branch retained ------------------------------

def test_branch_only_omits_path_whole() -> None:
    r = Renderer()
    git = _git(branch='qa')                      # short branch
    pwd = '~/some-distinctive-long-path'         # long, distinctive pwd
    compact = r.path_git_compact(pwd, git)
    branch_only = r.path_git(
        pwd, git, show_path=False, show_commit=False, show_dirty=False,
    )
    # A width below compact path+branch but at/above branch-only.
    target_w = _visible_width(branch_only)
    assert target_w < _visible_width(compact)    # clean window exists
    result = r.fit_path(pwd, git, target_w)
    stripped = strip_ansi(result)
    assert result == branch_only
    assert pwd not in stripped                   # path omitted whole
    assert git.branch in stripped                # branch retained
    assert ELLIPSIS not in stripped              # never middle-ellipsized


# --- 3.3: glyph-only floor --------------------------------------------------

def test_glyph_only_floor_below_branch_width() -> None:
    r = Renderer()
    git = _git(branch='main')
    pwd = '~/proj'
    for target_w in (1, 2):
        result = r.fit_path(pwd, git, target_w)
        assert result == r.path_glyph_only()
        assert _visible_width(result) <= target_w   # overflow-safe floor


def test_floor_never_overflows_across_small_widths() -> None:
    r = Renderer()
    git = _git(branch='feature/some-long-branch-name')
    pwd = '~/another-distinctive-long-path'
    floor_w = _visible_width(r.path_glyph_only())
    assert floor_w == 1
    for target_w in range(0, 6):
        result = r.fit_path(pwd, git, target_w)
        # Below the branch-only rung the floor is returned; it never overflows
        # a target at/above its own width, and never emits an ellipsis.
        assert ELLIPSIS not in strip_ansi(result)
        if target_w >= floor_w:
            assert _visible_width(result) <= target_w


# --- 3.4: no middle-ellipsis ever, across a wide width sweep ---------------

def test_no_ellipsis_at_any_width() -> None:
    r = Renderer()
    combos = [
        ('~/proj', _git()),
        ('~/some-distinctive-long-path', _git(branch='qa')),
        ('~/a/much/longer/nested/project/path/here',
         _git(branch='feature/extremely-long-branch-name', modified=5, untracked=3)),
        ('~', _git(branch='m', commit='deadbee', modified=0, untracked=0)),
    ]
    for pwd, git in combos:
        for target_w in range(0, 120):
            result = r.fit_path(pwd, git, target_w)
            assert ELLIPSIS not in strip_ansi(result), (
                f'ellipsis at width {target_w} for pwd={pwd!r} branch={git.branch!r}'
            )


# --- compact_only ladder ----------------------------------------------------

def test_compact_only_skips_full_path_git_stages() -> None:
    r = Renderer()
    git = _git()
    pwd = '~/proj'
    full = r.path_git(pwd, git)
    # Even at a very wide target, compact_only never returns the full path_git
    # stages (commit hash absent).
    result = r.fit_path(pwd, git, _visible_width(full) + 50, compact_only=True)
    stripped = strip_ansi(result)
    assert result == r.path_git_compact(pwd, git)
    assert git.commit not in stripped
    assert ELLIPSIS not in stripped


def test_compact_only_ladder_terminates_at_branch_then_glyph() -> None:
    r = Renderer()
    git = _git(branch='qa')
    pwd = '~/some-distinctive-long-path'
    branch_only = r.path_git(
        pwd, git, show_path=False, show_commit=False, show_dirty=False,
    )

    # Branch-only rung still reachable under compact_only.
    result = r.fit_path(pwd, git, _visible_width(branch_only), compact_only=True)
    assert result == branch_only
    assert pwd not in strip_ansi(result)
    assert ELLIPSIS not in strip_ansi(result)

    # Glyph-only floor under compact_only at a tiny width.
    floor = r.fit_path(pwd, git, 1, compact_only=True)
    assert floor == r.path_glyph_only()
    assert _visible_width(floor) <= 1
