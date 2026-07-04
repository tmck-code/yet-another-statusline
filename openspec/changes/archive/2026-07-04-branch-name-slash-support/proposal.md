## Why

Git branch names that contain `/` — the near-universal convention for prefixed
branches like `feat/123` or `release/2.0` — are displayed truncated to only their
last path segment. A branch checked out as `feat/123` renders as `123` in the
statusline, hiding the prefix that carries the branch's meaning. The root cause is
that `_read_head` derives the branch label by taking the basename of the ref path
(`head.rsplit('/', 1)[-1]`) instead of stripping the `refs/heads/` prefix.

## What Changes

- Fix branch-name derivation in `GitInfo._read_head` (`claude/yas/info/git.py`) to
  strip the `refs/heads/` **prefix** from a symbolic ref rather than taking the last
  `/`-delimited segment, so `refs/heads/feat/123` yields `feat/123` and
  `refs/heads/a/b/c` yields `a/b/c`.
- Preserve the current basename behaviour (`rsplit('/', 1)[-1]`) as a fallback only
  when the `refs/heads/` marker is absent (unusual / non-branch refs).
- Leave the detached-HEAD path (`d:<sha[:7]>`), control-char sanitisation, commit
  lookup, and dirty-count logic untouched.
- Add regression tests to `test/test_git_info.py` covering single-slash, multi-slash,
  and unchanged no-slash branch names.

Not breaking: no config keys, layout contracts, or public APIs change. The output
for a slashed branch simply becomes correct (fuller) rather than truncated.

## Capabilities

### New Capabilities

- `git-branch-display`: The statusline SHALL display a git branch name in full,
  including any `/` path separators, deriving the label by stripping the
  `refs/heads/` prefix from the symbolic ref in `.git/HEAD`.

### Modified Capabilities

*(none — there is no existing spec that pins branch-name derivation; this is a new
capability spec for previously-unspecified, incorrect behaviour)*

## Impact

- `claude/yas/info/git.py`: `GitInfo._read_head` staticmethod, the `head.startswith('ref:')`
  branch (line 78).
- `test/test_git_info.py`: new assertions in / alongside `test_read_head_ref_branch`.
- No change to `constants.py`, the renderer, layout, or the width model. A slashed
  branch produces a longer label, which flows through the existing header
  width/truncation path unchanged — validated via the demo visual gate.
- Downstream commit lookup at `git.py:85-91` (`Path(gitdir) / 'refs' / 'heads' / branch`)
  now receives `feat/123` and resolves the correct nested loose-ref path
  `refs/heads/feat/123` — no regression.
