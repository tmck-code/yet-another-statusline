## 1. Shared sanitizer (SEC-1 foundation)

- [x] 1.1 Add `_sanitize(s: str) -> str` using `re.sub(r'[\x00-\x08\x0b-\x1f\x7f-\x9f]', '', s)` in a dependency-free home importable by both `session.py` and `info/*` (default: `claude/yas/constants.py`, alongside `_ANSI_RE`); confirm no import cycle is introduced.
- [x] 1.2 Add a focused unit test for `_sanitize`: strips `ESC`/`BEL`/C0/C1/DEL; leaves printable ASCII and CJK/non-ASCII text byte-for-byte unchanged.

## 2. Route untrusted fields through the sanitizer (SEC-1)

- [x] 2.1 Call `_sanitize` inside `_as_str` (`claude/yas/session.py:41`) so `display_name`, model `id`, `current_dir`/`cwd`, `project_dir`, `session_id`, and output-style name are covered centrally.
- [x] 2.2 Sanitize the git branch in `claude/yas/info/git.py:_read_head` (value read from `.git/HEAD` and `refs/heads/*`).
- [x] 2.3 Sanitize transcript-derived captures that bypass `_as_str`: task subject/active_form (`info/tasks.py`), subagent description/tool-input (`info/subagents.py`), skill names (`info/skills.py`), and any raw string slices in `info/transcript.py`.

## 3. Remove the cloned-repo settings read (SEC-2)

- [x] 3.1 In `Workspace.plugins` (`claude/yas/session.py:150-168`), drop the `Path(self.project_dir)/'.claude'/'settings.json'` candidate so only `CLAUDE_DIR/settings.json` is read.

## 4. Regression tests (mirror PR #35 `test_security_hardening.py`)

- [x] 4.1 SEC-1 sinks: feed an OSC-52 payload to model `display_name` and an OSC-0 payload to a git branch; assert the rendered output contains no `\x1b`/`\x07` and no OSC sequence.
- [x] 4.2 SEC-1 transcript sinks: feed control bytes into task subject, subagent description/tool-input, and skill name; assert they are stripped from the captured/rendered values.
- [x] 4.3 SEC-1 no-op: assert plain and CJK field values render unchanged (no over-stripping).
- [x] 4.4 SEC-2: a malicious `project_dir/.claude/settings.json` listing `enabledPlugins` contributes nothing to the plugins list; a `CLAUDE_DIR/settings.json` still does.

## 5. Quality gates

- [x] 5.1 Run `pytest` (full suite) — all green, including the new tests.
- [x] 5.2 Run `ruff check claude/ test/` — clean.
- [x] 5.3 Run `mypy --strict` over the touched modules — clean.
- [x] 5.4 Sanity-check the demo render (`make demo/img` or equivalent) shows no layout/colour regression for legitimate input.
