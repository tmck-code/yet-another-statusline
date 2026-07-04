<!-- AGENT INSTRUCTIONS: Mark each subtask done with TaskUpdate (status: completed) the
     moment it is finished — before starting the next task. This keeps progress visible
     to observers in real time. Subtasks within the same numbered group that have no
     dependency on each other MAY be delegated to parallel subagents. -->

## 1. Understand current code

- [x] 1.1 Read `claude/yas/info/git.py` lines 65–99 (`GitInfo._read_head`), confirming the current derivation `branch = head.rsplit('/', 1)[-1]` at line 78 and the surrounding `head.startswith('ref:')` / `elif head:` (detached) branches, `_sanitize(branch)` at line 83, and the commit lookup `Path(gitdir) / 'refs' / 'heads' / branch` at line 86.
- [x] 1.2 Read `test/test_git_info.py`, noting the `_make_git_dir` helper (writes `ref: refs/heads/{branch}\n` to HEAD and a loose ref file at `refs/heads/{branch}`) and `test_read_head_ref_branch` as the template for new assertions.
- [x] 1.3 Record the baseline `make test` pass count (via `verifier`).

## 2. Fix branch derivation in `_read_head`

- [x] 2.1 In `claude/yas/info/git.py`, inside the `if head.startswith('ref:'):` branch (line 77–78), replace `branch = head.rsplit('/', 1)[-1]` with logic that: (a) extracts the ref target by stripping the leading `ref:` marker and surrounding whitespace (e.g. `target = head[4:].strip()`); (b) if `target.startswith('refs/heads/')`, set `branch = target[len('refs/heads/'):]` to preserve embedded `/`; (c) otherwise fall back to `branch = target.rsplit('/', 1)[-1]`.
- [x] 2.2 Leave the `elif head:` detached-HEAD branch (`branch = f'd:{head[:7]}'`, line 79–80), the `_sanitize(branch)` call (line 83), the commit lookup block (lines 85–91), and the `ORIG_HEAD` fallback (lines 92–98) completely unchanged.
- [x] 2.3 Confirm no other call sites derive the branch label — `_read_head` is the sole producer (`grep -rn "rsplit\|refs/heads" claude/`).

## 3. Tests

- [x] 3.1 In `test/test_git_info.py`, add `test_read_head_slashed_branch`: build a git dir with `_make_git_dir(tmp_path, branch='feat/123', commit='abcdef1234567890')` (the helper's `refs/heads/feat/123` mkdir handles the nested dir via `parents=True`), call `git.GitInfo._read_head(str(gitdir))`, assert `branch == 'feat/123'` and `commit == 'abcdef123'`.
- [x] 3.2 Add `test_read_head_multi_slash_branch`: same pattern with `branch='a/b/c'`, assert `branch == 'a/b/c'`.
- [x] 3.3 Confirm the existing `test_read_head_ref_branch` (branch `main`) still passes unchanged — this is the no-regression / slash-free case. Add an inline comment noting it guards the slash-free path if not already clear.
- [x] 3.4 (Optional, if `_make_git_dir` needs it) verify the loose-ref write for a slashed branch lands at `refs/heads/feat/123` so the commit assertion in 3.1 exercises the corrected `Path(gitdir) / 'refs' / 'heads' / branch` lookup.

## 4. Verify (via `verifier`)

- [x] 4.1 Run `make test` — green, pass count ≥ baseline + 2 new tests.
- [x] 4.2 Run the demo visual gate (`make demo/img` then `.claude/skills/yas-demo-text/scripts/demo-text.sh`); eyeball the header row with a slashed branch to confirm a longer branch label flows through header width/truncation without breaking column math. Re-baseline any `demo/text/*.txt` that legitimately changed.
