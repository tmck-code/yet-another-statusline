## Why

The statusline renders attacker-influenceable strings — a repo's git branch (`.git/HEAD`), the host-supplied `cwd`/`project_dir`/`session_id`/model name, transcript-derived task/subagent/skill text, and a project's `enabledPlugins` keys — straight to stdout with no control-character sanitization. An adversarial audit (PR #35, SEC-1/SEC-2) empirically reproduced two zero-interaction attacks fired merely by rendering: an OSC-52 clipboard hijack and an OSC-0/2 window-title spoof, plus an unexpected trust-boundary read of a cloned repo's `.claude/settings.json`. The current `_ANSI_RE` strips only SGR colour codes, so OSC/C1/non-`m` CSI escapes pass through verbatim.

## What Changes

- **SEC-1 — sanitize untrusted field values at capture.** Strip C0/C1/DEL bytes (which include `ESC` `0x1b` and `BEL` `0x07`, the introducers/terminators for OSC and CSI) from every untrusted string as it is captured — centrally at the `_as_str` chokepoint (`display_name`, model `id`, `cwd`, `project_dir`, `session_id`, output-style name) and at the remaining capture sites that bypass it: the git branch read (`info/git.py`), and transcript-derived task subject/active_form, subagent description/tool-input, and skill names. Sanitization happens **at capture only** — the final rendered line is left untouched so the renderer's own legitimate SGR survives.
- **SEC-2 — stop reading a cloned repo's settings.** `Workspace.plugins` no longer reads `project_dir/.claude/settings.json`; it reads only the user's own `CLAUDE_DIR/settings.json`. This removes an attacker-controlled trust-boundary read that also doubled as an escape-injection sink.
- Add regression tests covering both: a malicious OSC payload in each sink renders inert, and a malicious `project_dir` settings file is never read.

## Capabilities

### New Capabilities
- `untrusted-input-hardening`: defines the trust boundary for host- and repo-supplied input — which fields are untrusted, the control-character sanitization applied at capture, and the restriction that only the user's own config directory is read for plugin state.

### Modified Capabilities
<!-- None: no existing spec specifies the current sanitization or settings-read behavior. -->

## Impact

- **Code**: `claude/yas/session.py` (`_as_str` sanitization helper; `Workspace.plugins` candidate list), `claude/yas/info/git.py` (`_read_head` branch), `claude/yas/info/tasks.py`, `claude/yas/info/subagents.py`, `claude/yas/info/skills.py`, `claude/yas/info/transcript.py` (transcript-derived captures).
- **Tests**: new `test/` module mirroring the audit's `test_security_hardening.py` (OSC-52/OSC-0 inert across all sinks; cloned-repo settings not read).
- **Behavior**: the only user-visible change is that a project-local `.claude/settings.json` no longer contributes to the rendered plugins list. No rendering/layout change for legitimate input.
- **Quality gates**: must keep `ruff check` and `mypy --strict` clean; tests run via `pytest`.
