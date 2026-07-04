# git-branch-display Specification

## Purpose
TBD - created by archiving change branch-name-slash-support. Update Purpose after archive.
## Requirements
### Requirement: Branch name is displayed in full including slashes

The statusline SHALL derive a git branch label from `.git/HEAD` by stripping the `refs/heads/` prefix from the symbolic ref target, preserving every `/` path separator, and SHALL NOT reduce the label to only its final `/`-delimited segment. When the ref target does not begin with `refs/heads/`, the statusline SHALL fall back to the final `/`-delimited segment of the target. The derived label SHALL continue to be passed through control-character sanitisation before display, and the detached-HEAD label (`d:<sha[:7]>`) SHALL be unaffected.

#### Scenario: Single-slash prefixed branch is preserved

- **WHEN** `.git/HEAD` contains `ref: refs/heads/feat/123`
- **THEN** `_read_head` returns branch `feat/123`
- **AND** the label is not truncated to `123`

#### Scenario: Multi-slash branch is preserved in full

- **WHEN** `.git/HEAD` contains `ref: refs/heads/a/b/c`
- **THEN** `_read_head` returns branch `a/b/c`

#### Scenario: Slash-free branch is unchanged

- **WHEN** `.git/HEAD` contains `ref: refs/heads/main`
- **THEN** `_read_head` returns branch `main`

#### Scenario: Commit is still resolved for a slashed branch

- **WHEN** `.git/HEAD` contains `ref: refs/heads/feat/123`
- **AND** the loose ref file `refs/heads/feat/123` exists holding a commit sha
- **THEN** `_read_head` resolves the commit from `refs/heads/feat/123`
- **AND** returns branch `feat/123` alongside the first 9 chars of the sha

#### Scenario: Symbolic ref outside refs/heads falls back to basename

- **WHEN** `.git/HEAD` contains a symbolic ref target that does not start with `refs/heads/`
- **THEN** `_read_head` returns the final `/`-delimited segment of the ref target

#### Scenario: Detached HEAD is unaffected

- **WHEN** `.git/HEAD` contains a raw 40-char commit sha (no `ref:` prefix)
- **THEN** `_read_head` returns branch `d:<sha[:7]>` and commit `''`, exactly as before

