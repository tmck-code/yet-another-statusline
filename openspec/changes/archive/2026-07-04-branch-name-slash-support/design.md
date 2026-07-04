## Context

`GitInfo._read_head` (`claude/yas/info/git.py:65-99`) reads `.git/HEAD` and derives
the branch label. For a normal checkout the file contains a symbolic ref such as
`ref: refs/heads/feat/123`. The current code (`git.py:78`) computes the label as:

```python
branch = head.rsplit('/', 1)[-1]
```

For `ref: refs/heads/feat/123` this splits on the **last** `/` and keeps only
`123`, discarding the `feat/` prefix. Git branch names legitimately contain `/`
(prefixed branches are the dominant convention), so this truncation is wrong for a
large fraction of real repos. `refs/heads/main` happens to render correctly only
because it has no embedded slash after the prefix.

The full ref always begins with the literal marker `refs/heads/`. Everything after
that marker is the branch name, slashes included. Stripping the prefix — rather than
splitting on the last separator — reconstructs the true name.

Downstream, `_read_head` uses the derived `branch` twice:
1. Control-char sanitisation via `_sanitize(branch)` (`git.py:83`) — `.git/HEAD` is
   attacker-controllable for a cloned repo, so the label is scrubbed of escapes.
2. Commit lookup: `Path(gitdir) / 'refs' / 'heads' / branch` (`git.py:86`). With
   the corrected `branch='feat/123'` this resolves to the nested loose-ref path
   `refs/heads/feat/123`, which is exactly where git stores that ref — so the fix
   makes the commit lookup *more* correct, not less. Packed-ref repos (where the
   loose file is absent) already fall through to `ORIG_HEAD` (`git.py:92-98`) today
   and continue to do so, unchanged.

## Goals / Non-Goals

**Goals:**
- Display git branch names in full, preserving `/` separators (`feat/123`, `a/b/c`).
- Keep `refs/heads/main` and other slash-free names working exactly as before.
- Preserve a sensible fallback for symbolic refs that do not point under
  `refs/heads/` (e.g. an unusual `ref: refs/something/x`).
- Keep the change surgical — a single line of derivation logic plus tests.

**Non-Goals:**
- Changing the detached-HEAD label (`d:<sha[:7]>`) — untouched.
- Changing sanitisation, commit lookup, dirty-count, or repo-discovery logic.
- Handling worktree/gitlink `.git` files or packed-refs resolution beyond today's
  behaviour.
- Truncating, eliding, or restyling long branch labels in the renderer. Any width
  interaction with the header row is handled by the existing layout/truncation
  path and validated by the demo gate; no renderer code changes here.

## Decisions

### 1. Strip the `refs/heads/` prefix instead of taking the basename

Replace `branch = head.rsplit('/', 1)[-1]` with logic that, for a `ref:` HEAD,
first extracts the ref target (the token after `ref:`), then removes the
`refs/heads/` prefix:

- Parse the ref target from `head` (strip the leading `ref:` and surrounding
  whitespace).
- If the target starts with `refs/heads/`, the branch is the remainder after that
  prefix (`target[len('refs/heads/'):]`) — this preserves every embedded `/`.
- Otherwise (marker absent), fall back to the existing basename behaviour
  `target.rsplit('/', 1)[-1]` so unusual refs still yield a non-empty, bounded
  label.

Rationale over alternatives:
- **`rsplit('/', 1)[-1]` (status quo)** — wrong: drops the prefix segment.
- **`split('/', 2)[-1]` on the whole `refs/heads/...`** — works for the common
  case but is positional and brittle if the marker is absent; an explicit
  `refs/heads/` prefix check is clearer and directly expresses intent.
- **Prefix strip with basename fallback (chosen)** — correct for the common case,
  robust for the odd case, minimal blast radius.

### 2. Keep sanitisation exactly where it is

`_sanitize(branch)` still runs after derivation (`git.py:83`). The branch name is
now longer/richer but still repo-supplied, so it must stay scrubbed. No change to
the call site or ordering.

### 3. No renderer or width-model changes

A slashed branch is simply a longer string flowing into the same header pipeline.
Column math already uses the visible-width model, not `len()`, and long labels are
handled by existing truncation. Because a longer branch label *can* interact with
header width/truncation, the change is validated with the demo visual gate
(`make demo/img`) in addition to `make test`; no code in the renderer is edited.

## Risks / Trade-offs

- [A branch name could contain an unusual embedded newline or control sequence] →
  Mitigated: `_sanitize` still runs and is unchanged; the derivation only affects
  which substring is passed to it.
- [A longer branch label overflows the header row] → Mitigated: existing
  layout/truncation handles overflow; verified by the demo gate. No new truncation
  logic is introduced (Non-Goal).
- [Symbolic ref not under `refs/heads/`] → Mitigated: basename fallback preserves
  today's behaviour for those refs; no worse than before.

## Migration Plan

Pure bug-fix; no data, config, or interface migration. Rollback is reverting the
single derivation change in `_read_head`.

## Open Questions

- None blocking. Assumption made: symbolic refs outside `refs/heads/` are rare
  enough that preserving the legacy basename fallback (rather than showing the full
  odd ref) is acceptable. Confirm before apply if full-ref display is preferred for
  those cases.
