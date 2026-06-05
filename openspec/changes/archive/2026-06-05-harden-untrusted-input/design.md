## Context

The statusline ingests a JSON payload from Claude Code on stdin plus on-disk repo artifacts (`.git/HEAD`, refs, transcript JSONL, `settings.json`). Several of these are attacker-influenceable the moment a cloned/malicious repo is opened. Today the only escape filtering is `_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')` (`claude/yas/constants.py:18`), which matches **only** SGR colour codes — OSC (`\x1b]…`), C1, and non-`m` CSI/DCS pass through verbatim. PR #35's audit reproduced an OSC-52 clipboard write and an OSC-0 title spoof through these sinks (SEC-1) and a trust-boundary read of `project_dir/.claude/settings.json` (SEC-2).

This codebase is the current `claude/yas/` package. PR #35's fixes were authored against a different, now-closed refactor branch (`claude/statusline/`), so they cannot be cherry-picked — only their approach is reused. The session model is built through `from_dict` classmethods in `claude/yas/session.py`, with `_as_str` (`session.py:41`) as the central string-coercion helper. Repo/transcript-derived fields are captured in `claude/yas/info/{git,tasks,subagents,skills,transcript}.py`, several of which bypass `_as_str`.

## Goals / Non-Goals

**Goals:**
- No untrusted OSC/CSI/C1 escape can reach stdout, eliminating the zero-interaction OSC-52 and OSC-0/2 attacks.
- Plugin state is sourced only from the user's own config dir; a cloned repo's `settings.json` is never read.
- Each fix is small and single-purpose (the repo owner asked for one-fix-per-change), with a regression test pinning it.
- `ruff` and `mypy --strict` stay clean.

**Non-Goals:**
- Broadening `_ANSI_RE` or the width helpers (`render/text.py`) to parse OSC for width accounting. With capture-time sanitization, only plain text reaches the width math, so it is correct by construction — widening the width regex is unnecessary and (per the audit) would risk slicing mid-escape on the colour-preserving truncation path. Out of scope.
- OSC-8 hyperlink support or any new rendering capability.
- Pricing/context/layout fixes from PR #35 (separate concerns).

## Decisions

**D1 — Sanitize at capture, with a single shared helper.**
Add one `_sanitize(s: str) -> str` in `claude/yas/session.py` (or a small `textutil`-style home) using `re.sub(r'[\x00-\x08\x0b-\x1f\x7f-\x9f]', '', s)`. Route the common fields through it by calling it inside `_as_str`, which already coerces `display_name`, model `id`, `cwd`/`current_dir`, `project_dir`, `session_id`, and output-style name. *Why at `_as_str`*: it is the existing chokepoint, so most sinks are covered by one edit and stay covered as new `_as_str`-based fields are added. *Why not at render*: the final line legitimately contains the renderer's own SGR; stripping there would break colour. *Alternative considered*: a decorator/validator per field — rejected as more surface area for the same effect.

**D2 — Cover the capture sites that bypass `_as_str`.**
The git branch (`info/git.py:_read_head`, read from `.git/HEAD` and `refs/heads/*`) and transcript-derived strings (`info/tasks.py` subject/active_form, `info/subagents.py` description/tool-input, `info/skills.py` names, and any raw slices in `info/transcript.py`) do not pass through `_as_str`. Apply `_sanitize` explicitly at each of these capture points. To avoid a circular import from `info/*` → `session`, the shared helper should live where both layers can import it cleanly (e.g. `constants.py` alongside `_ANSI_RE`, or a new `textutil.py`); pick whichever keeps the import graph acyclic — `constants.py` is the low-risk default.

**D3 — Drop the project-dir settings candidate (SEC-2).**
In `Workspace.plugins` (`session.py:150-168`) remove the `project_dir/.claude/settings.json` entry so the candidate list is exactly `[CLAUDE_DIR / 'settings.json']`. This kills the trust-boundary read outright; once it's gone, the `enabledPlugins`-key escape sink for that path disappears regardless of D1. *Alternative considered*: keep reading it but sanitize the keys — rejected: it still reads attacker-controlled config across a trust boundary, which is itself the finding.

**D4 — Tests mirror the audit's `test_security_hardening.py`.**
One new `test/` module: assert each sink (model name, git branch, task/subagent/skill text) renders inert when fed an OSC-52/OSC-0 payload (no `\x1b`/`\x07` in output), assert plain/CJK text is unchanged, and assert a malicious `project_dir/.claude/settings.json` contributes nothing while `CLAUDE_DIR/settings.json` still does.

## Risks / Trade-offs

- **A legitimate branch/path with a stray control byte loses that byte** → Acceptable and intended; statusline fields are single-line display strings and control bytes have no business there.
- **`project_dir`-local plugins no longer shown** → This is the explicit behavior change. It only affected plugins enabled solely via a repo-local settings file, which is exactly the untrusted read being removed; document in the proposal's Impact.
- **A future capture site bypasses both `_as_str` and the explicit calls** → Mitigate by keeping `_as_str` the funnel and adding a test that exercises each known sink, so a regression on a covered sink fails loudly.
- **Helper placement causing an import cycle** → Mitigated by D2's guidance to home the helper in a dependency-free module (`constants.py`).

## Migration Plan

Pure hardening; no data migration. Land as one change (optionally two commits: SEC-1 sanitization, then SEC-2 settings read) so either can be reverted independently. Rollback is a straight revert — no persisted state changes.

## Open Questions

- Helper home: `constants.py` vs a new `textutil.py`. Default to `constants.py` unless the import graph or existing convention favors a dedicated module — resolve during implementation.
