# `yet-another-statusline` — Security, Performance & Architecture Audit + Roadmap

| | |
|---|---|
| **Repository** | https://github.com/tmck-code/yet-another-statusline |
| **What it is** | A Claude Code status-line renderer, shipped as a Claude Code plugin (`yas`) |
| **Commit audited** | `dd07509` (tip of `main`), authored 2026-05-27; declared version `0.2.0` |
| **License** | BSD-3-Clause |
| **Primary author** | Tom McKeesick (`tmck-code`) — 167/182 commits; small number of outside contributors |
| **Audit date** | 2026-05-27 |
| **Method** | Read-only clone; static reading of source; runtime model verified against official Claude Code statusline docs. **No repo code was executed.** |
| **Overall verdict** | **Safe to run (LOW risk).** Main weaknesses are **avoidable per-render CPU that grows with session length** and **Medium-severity metric-accuracy bugs in displayed cost/context** — all fixable in-place. Tooling is mostly right; the renderer is a 2,928-line monolith. |

> **Rigor note.** No timing benchmark was executed for this audit (it was read-only, and the repo's own `ops/bench.py` under-measures — see §5.6). Every latency figure below is an **estimate**, explicitly labeled, with "measure first" as a Phase 0 task. Security/behaviour findings were verified by reading source directly; the one genuinely unverified item (`async: true`) is flagged as such.

> **Revision note (2026-05-27).** This document was revised after an independent adversarial review of the first draft. Added: a metric & functional-correctness section (§5A — pricing C1, day-cost C2, context-metric C3, git-correctness G1/G2, operational O1–O5, ancillary A3) and corresponding register rows; tightened wording on responsiveness, "Windows-aware", and CI pinning. The per-model pricing claim (C1) was verified **live** against the official pricing page (`platform.claude.com/docs/en/about-claude/pricing`, retrieved 2026-05-27). The **security** verdict is unchanged (LOW); a **Metric-accuracy: MEDIUM** dimension is added.

---

## 1. Executive summary

- **Security: LOW risk; genuinely clean.** Zero runtime third-party dependencies (stdlib only), no network code anywhere, no auto-running Claude Code hooks, a minimal read-only permission allowlist, no `shell=True`/command-injection, all writes scoped to `~/.claude/`. Installation changes are user-initiated, backed up, and reversible.
- **Performance: the real concern, but fixable and not dangerous.** It will **not** break or freeze Claude Code (the host cancels an in-flight render if a new one is triggered). But each render does redundant work that **scales with session length**: it scans the conversation transcript **three separate times**, reads + fully rewrites two log files, spawns a fresh Python interpreter, and spawns 1–2 child processes. None of this is cached between renders despite the official docs recommending it.
- **Metric accuracy: MEDIUM (added in revision).** The displayed **session cost** is recomputed from a version-blind rate table that is ~3× too high for the current Opus line and ignores the host's own `cost.total_cost_usd`; **day cost** prices all of a day's sessions with whatever model is rendering now; and the headline **context %** is a 150k soft-pressure score (output tokens included), not the official context-window fill. The unifying root cause: the renderer parses host-authoritative fields and then recomputes them with its own logic. See §5A.
- **Right tools? Mostly.** stdlib-only Python is excellent for safety/portability; its weakness is interpreter cold-start on every render. The highest-value near-term fixes are **algorithmic** (single transcript pass + incremental tailing + caching) and language-independent. A compiled hot path (Go/Rust) is a sound later step for the fixed cold-start cost. The single 2,928-line file is the clearest maintainability smell.
- **Engineering hygiene is strong:** ~40 pytest files, `mypy --strict`, `ruff`, CI on Python 3.10/3.12/3.13, with the third-party CI action pinned by commit SHA (first-party `checkout` uses a moving major tag — see §4.6).

---

## 2. Scope & methodology

In scope: the full repository at commit `dd07509` — the Python renderer (`claude/statusline_command.py` and `claude/statusline/`, `claude/mon/`), the plugin manifest and skills (`.claude-plugin/`, `skills/`, `.claude/`), hooks, CI, Makefile, tests, and `ops/bench.py`.

Method: the repo was cloned read-only and inspected statically. Security-critical files were read in full; the performance hot path was read directly and cross-checked against the project's own tests. The Claude Code status-line execution model (how often the command runs, what it receives, blocking behaviour) was confirmed against the official documentation at `code.claude.com/docs/en/statusline`. No part of the repo was executed, installed, or wired into Claude Code during the audit.

Confidence labels used below: **(verified)** = read directly in source; **(corroborated)** = confirmed by an existing test or a second pass; **(estimate)** = not measured, stated as an estimate; **(unverified)** = could not be confirmed and is flagged.

---

## 3. What the software does (context for an independent auditor)

Claude Code lets users define a `statusLine.command` in `~/.claude/settings.json`. On certain events Claude Code runs that command, pipes a **JSON object describing the current session** to its stdin, and displays the command's stdout as the status line. `yas` is such a command, written in Python.

On each invocation `yas`:

1. Reads the session JSON from stdin (`main`, `claude/statusline_command.py:2900`). The JSON includes `session_id`, `transcript_path`, model, workspace dirs, cost, context-window token counts, rate-limit usage, etc.
2. Writes that raw payload to `~/.claude/statusline-output/statusline.{session_id}.json` so a multi-session observer can index it (`:2908-2912`).
3. Detects terminal width (`terminal_width`, `:101-129`).
4. Derives a set of stats and renders an ANSI status line at one of three widths (`render`, `:2858-2869`; `build_narrow`/`build_medium`/`build_wide`, `:2591`/`:2638`/`:2697`).

Stats are derived from: the stdin payload; the **session transcript** (a JSONL file that grows for the life of the session); two rolling log files under `~/.claude/`; the git repo at the workspace cwd; an optional `openspec/` directory; and per-session subagent transcripts.

The repo also ships:
- A `mon` package (`claude/mon/`) — a multi-session "observer" TUI that discovers active sessions by reading `~/.claude/statusline-output/*.json` and the active `*.jsonl` transcripts (`claude/mon/discovery.py:18-95`). **This observer seam is the natural data feed for a future macOS app.**
- Two user skills: `/yas:init` (wires the command into settings) and `/yas:uninstall` (removes it).
- Developer-only skills under `.claude/` (PR helper, renderer docs) that plugin users never load.

---

## 4. Security audit

### 4.1 Dependencies & supply chain — **clean**
- `pyproject.toml:9` → `dependencies = []`. **Zero runtime third-party packages**; the renderer imports only the Python standard library (`claude/statusline_command.py:5-17`). This is the single biggest safety property: there is essentially no third-party runtime supply-chain surface. **(verified)**
- Dev-only tools (`mypy`, `pytest`, `ruff`, `uv`) are isolated in a dependency group and never required to run the status line. **(verified)**

### 4.2 Network — **none**
- No `requests`/`urllib`/`http`/`socket`/`httpx`/`aiohttp` imports and no URL/host literals in any runtime path. No telemetry, analytics, or phone-home behaviour. **(verified across all `.py`)**

### 4.3 Plugin install footprint — **explicit, user-initiated, reversible**
- **No auto-running hooks.** `hooks/hooks.json:3` is `"hooks": {}` — the plugin registers nothing on PreToolUse/PostToolUse/Stop/SessionStart/UserPromptSubmit/etc. Nothing executes automatically on install. **(verified)**
- **Minimal permission allowlist.** `.claude-plugin/permissions-allow.json` pre-authorizes exactly 12 read-only/benign shell utilities: `cp, cut, date, dirname, find, grep, head, jq, printf, sort, which, xargs`. No `Bash(*)`, no `rm`/`mv`/`curl`/`wget`/`sudo`/`chmod`. **(verified)**
- **Settings mutation is user-triggered and backed up.** `/yas:init` writes a `statusLine` block into `~/.claude/settings.json` only when the user runs it: it backs up the existing file to `settings.json.bak-yas-<timestamp>` (`skills/init/SKILL.md:95-97`), then writes via a temp file + `mv` (`:100-109`). `/yas:uninstall` reverses it, refuses to touch a `statusLine` that is **not** yas (signature check), and removes only this tool's runtime files.
- **Runtime writes are scoped to `~/.claude/`** (or `$CLAUDE_CONFIG_DIR`): `statusline-tokens.log`, `statusline-token-rate.log`, `statusline-output/`, the optional `terminal-width`/`statusline-theme` files. No writes to system paths, shell rc files, crontab, or outside the Claude config dir. **(verified)**

### 4.4 Subprocess use / command injection — **safe**
- Every `subprocess.run` uses **list-form argv (no `shell=True`)**: the tmux width probe (`:103-105`), `git status --porcelain=v1 -z` with `timeout=2` (`:871-875`), `pgrep`/`os.kill(SIGWINCH)` in the optional alacritty helper, and dev-only calls in `demo.py`/`ops/bench.py`. Variable data (e.g. the repo path) is passed as a discrete argument (`git -C <repo> …`), not interpolated into a shell string → no command-injection vector. **(verified)**

### 4.5 Filesystem, secrets & dynamic execution — **safe**
- No credential access (no reading of `~/.aws`, `~/.ssh`, `.env`, tokens, keys). Environment reads are config-only (`CLAUDE_CONFIG_DIR`, `YAS_MAX_WIDTH`, `COLUMNS`, `TMUX_PANE`, `CLAUDE_STATUSLINE_THEME`, `STATUSLINE_TOKEN_WINDOW`, `YAS_FULL_WIDTH`). **(verified)**
- No `eval`/`exec`/`pickle`/`marshal`/unsafe-`yaml`. The one `importlib … exec_module` (`:27-37`) loads the repo's own `claude/statusline/themes.py` (static data) by absolute path, not anything user-controlled. **(verified)**

### 4.6 CI & git hooks — **safe, supply-chain aware**
- `.github/workflows/ci.yml`: runs pytest/ruff/mypy on push across Python 3.10/3.12/3.13. No secrets used. The one third-party action (`astral-sh/setup-uv`) is **pinned by commit SHA** (good practice); `actions/checkout@v6` is a **moving** major tag, not an immutable SHA pin — common and low-risk for a first-party action, but not strict supply-chain hygiene (finding S6). **(verified)**
- `.github/hooks/pre-commit` runs ruff/mypy/pytest on staged Python. It is **opt-in** — `make hooks` prompts `y/N` before setting `core.hooksPath`. It never runs for plugin users (who don't clone the repo). **(verified)**

### 4.7 Flagged uncertainty — `async: true` in the written config
`/yas:init` writes `'.statusLine = {"async":true,"command":$cmd,"refreshInterval":1,"type":"command"}'` (`skills/init/SKILL.md:101`). The **current official statusline documentation does not document an `async` field**; the documented execution model is synchronous with a 300 ms debounce and in-flight cancellation. So the practical effect of `async: true` is **unverified** — it may be a no-op, an undocumented/legacy field, or forward-looking. **Risk: negligible** (an unrecognized config key is harmless), but the tool is leaning on something undocumented. *Recommendation:* verify against the running Claude Code version; if unsupported, drop it to avoid implying behaviour that isn't there. **(unverified — flagged)**

### 4.8 Security verdict
**LOW risk. Safe to install and run.** It is a local, dependency-free, network-free renderer with no auto-running hooks, minimal permissions, and reversible, user-initiated configuration changes. The only security-adjacent nit is the undocumented `async` flag (§4.7).

---

## 5. Performance audit

This is where the real, actionable findings are. The tool will not harm correctness or freeze the UI, but it spends more CPU per render than it needs to, and that cost **grows with session length** and **multiplies across concurrent sessions**.

### 5.1 Verified runtime model (how often / how it runs)
Confirmed against the official Claude Code statusline docs:
- `statusLine.refreshInterval` is in **seconds**, with a **hard floor of 1**. `/yas:init` sets it to `1` → the timer re-runs the command **at most once per second**. (It is **not** "per keystroke".)
- The command **also** runs event-driven: after each new assistant message, after `/compact`, on permission-mode change, on vim-mode toggle.
- Updates are **debounced at 300 ms**; if a new trigger fires while a render is still running, **the in-flight render is cancelled**. → A slow render cannot pile up or block indefinitely; worst case the displayed line lags until the script finishes.
- The session JSON is delivered on **stdin** each invocation.
- Built-in caching is only the 300 ms debounce; **deeper caching is the command author's responsibility** — and the docs explicitly demonstrate caching expensive work (e.g. `git`) keyed by `session_id` with a short freshness window. `yas` does **not** do this.

### 5.2 Per-render cost — which work runs at which width **(verified)**
`render` (`:2858`) dispatches by width. The expensive data-collection differs per tier:

| Work item | narrow (`:2591`) | medium (`:2638`) | wide (`:2697`) | Evidence |
|---|:--:|:--:|:--:|---|
| `RunningSubagents.from_session` (glob + parse recent subagent JSONL) | ✓ | ✓ | ✓ | `:2610/2681/2714`, def `:956-1010` |
| `GitInfo.from_cwd` (fs walk + `git status` subprocess) | — | ✓ | ✓ | `:2647/2722`, def `:805-899` |
| `TaskList.from_session` (**full transcript scan**) | — | ✓ | ✓ | `:2680/2719`, def `:1091-1144` |
| `LoadedSkills.from_transcript` (**full transcript scan**) | — | — | ✓ | `:2706`, def `:906-934` |
| `TranscriptUsage.from_transcript` (**full transcript scan**) | — | — | ✓ | `:2708`, def `:1188-1223` |
| `TokenLog.update` (read+rewrite `statusline-tokens.log`) | — | — | ✓ | `:2710`, def `:653-685` |
| `TokenRate.update` (read+rewrite `statusline-token-rate.log`) | — | — | ✓ | `:2711`, def `:693-726` |
| `OpenSpec.from_cwd` (fs walk + read every non-archived `tasks.md`) | — | — | ✓ | `:2735`, def `:1242-1274` |
| Write raw payload to `statusline-output/{session_id}.json` | ✓ | ✓ | ✓ | `:2908-2912` |
| `terminal_width` (tmux subprocess if `$TMUX_PANE`) | ✓ | ✓ | ✓ | `:101-129` |
| Fresh Python interpreter + `importlib` theme load | ✓ | ✓ | ✓ | process model + `:27-37` |

Most users at a normal terminal width hit the **wide** path, i.e. the full cost.

### 5.3 The three-scan problem (primary finding)
On a **wide** render the session transcript JSONL is **opened and line-scanned three independent times** — `LoadedSkills` (`:918`), `TaskList` (`:1102`), `TranscriptUsage` (`:1198`). Each loops `for ln in fh:` doing a cheap substring pre-check before `json.loads` on matching lines. **(verified)**

- The transcript **grows unbounded** over a session, so this cost rises the longer you work.
- After the first read the file is in the OS page cache, so the dominant cost is **CPU** (Python line iteration + substring scans + `json.loads` on matching lines), repeated 3× per render and re-done from scratch on the **next** render — not heavy disk I/O, but real, redundant, linear-in-transcript-size work. **(estimate of nature, not magnitude)**
- It is **append-only**, which makes the fix clean: scan once, and only read newly-appended bytes on subsequent renders (§8 Phase 1).

**Correctness trap to preserve when fixing:** `TranscriptUsage` dedups usage by `message.id` via a `seen` set (`:1208-1210`), and the same id legitimately recurs on later lines — pinned by the existing test `test/test_transcript_usage.py::test_duplicate_message_id_counted_once`. Any incremental/tailing optimization **must persist the full seen-id set** (and the full task state machine), or it will silently miscount. This is detailed and de-risked in the Phase 1 design. **(corroborated by existing test)**

### 5.4 Token-log churn (secondary finding)
`TokenLog.update` rewrites `statusline-tokens.log` every wide render even when nothing changed (`:666`); `TokenRate.update` reads + rewrites `statusline-token-rate.log` every render (`:701`,`:717`), and `TokenRate.history`/`recently_active` read it again (`:728+`). These files are small (daily / 300 s window), so the impact is modest, but it is needless read-modify-write churn on a 1 Hz timer and creates a lost-update window across concurrent sessions sharing the rate log. **(verified)**

### 5.5 Per-render subprocesses & filesystem walks
- **Fresh Python process every render** — the command is `python3 …/statusline_command.py`; each invocation pays interpreter startup + `importlib` theme load. For small transcripts this fixed cost likely **dominates** total render time. **(estimate — not measured)**
- **1–2 child processes:** a tmux width probe whenever `$TMUX_PANE` is set — spawned **before** the cheaper width sources are tried (`:101-109`); and `git status` whenever in a repo (`:871`). **(verified)**
- **Filesystem walks every render:** `GitInfo._find_repo` walks parents looking for `.git` (`:821-830`); `OpenSpec._find_root` walks parents looking for `openspec/` (`:1265-1274`) — the latter is pure overhead for the majority who don't use OpenSpec. **(verified)**

### 5.6 The benchmark under-measures (why this matters)
`ops/bench.py` times the command against a static 1.2 KB fixture (`claude/statusline/session-info-example.json`, `ops/bench.py:25`,`:104-108`) whose `transcript_path` points at a non-existent file. So the benchmark **skips the very costs that matter** — the transcript scans, the token logs, real git. It effectively measures only interpreter startup + render on a tiny payload. **Before optimizing, the benchmark must be extended with a realistic large transcript** so improvements (and regressions) are visible and quantified. **(verified)**

### 5.7 Performance verdict
**Will not break Claude Code or build an unbounded render backlog** (in-flight cancellation protects the UI; no network; no heavy deps) — **but it can still consume avoidable local CPU/I/O**, and that cost is not free: per render it does redundant, session-length-scaling CPU (triple transcript scan), needless log rewrites, and a fresh interpreter + 1–2 subprocesses — up to ~1×/second plus on every message, **per active session**, so several concurrent sessions multiply it. All of it is fixable: single-pass + incremental tailing + per-session git cache (Phase 1), then optionally a long-lived collector / compiled binary to kill the fixed cold-start (Phases 3–4).

---

## 5A. Metric & functional correctness *(added in revision after an independent adversarial review)*

The first draft scoped itself to security, performance, and architecture and treated the displayed numbers as a performance input. For a tool whose entire purpose is showing accurate stats, the **accuracy of those numbers is itself in scope**. All findings below are confirmed in source; C1's pricing is additionally confirmed against the official pricing page.

**Cross-cutting root cause — the renderer ignores host-authoritative fields and recomputes them:**
- `Cost.total_cost_usd` is parsed from stdin (`:499`) but session cost is recomputed from a hard-coded table (`session_cost` `:333-343`, used at `build_wide:2712`).
- `ContextWindow.used_percentage` is parsed from stdin (`:527`) but the headline bar computes a different number (`context_line` `:2477-2504`).
Preferring the host values (recompute only as a fallback) fixes C1 and C3 at the root and tracks future pricing/context changes for free.

### C1 — Hard-coded model pricing is version-blind and wrong for the current Opus/Haiku line — **Medium**
`TokenAccounting.rates_for` (`:324-330`) is substring-only: any `opus` → `$15/$75`, any `haiku` → `$0.80/$4`, else `$3/$15`. Verified against the official pricing page (`platform.claude.com/docs/en/about-claude/pricing`, retrieved 2026-05-27):

| Model | Code charges (in/out $/MTok) | Official (in/out) | Error |
|---|---|---|---|
| Opus 4.7 / 4.6 / 4.5 | 15 / 75 | **5 / 25** | **~3× overstated** |
| Opus 4.1 / 4 (deprecated) | 15 / 75 | 15 / 75 | correct |
| Sonnet 4.6 / 4.5 | 3 / 15 | 3 / 15 | correct |
| Haiku 4.5 | 0.80 / 4 | **1 / 5** | ~20% understated |
| Haiku 3.5 (retired) | 0.80 / 4 | 0.80 / 4 | correct |

The table is right only for the deprecated/retired models and Sonnet; for the **current** Opus line it overstates displayed session/day cost ~3×. (The cache multipliers in `session_cost` — 1.25× write, 0.1× read — *do* match the official 5-minute-cache rates; only the base per-model rate is stale.) The recompute also can't track pricing **modifiers** the host already accounts for: **Fast mode bills Opus 4.6/4.7 at 6×** and the renderer detects `fast_mode` for display (`:2726`) but never prices it. Severity is Medium **for a stats tool** (it erodes trust), though the figure is an on-screen estimate, not a billing path.
*Fix:* prefer `cost.total_cost_usd` for session cost; keep a **version-keyed** table (by model id, not substring) only as a fallback, with tests that must be revisited when the model catalog changes.

### C2 — Daily cost prices every session with the currently-rendering model — **Medium**
`statusline-tokens.log` rows are `date session_id total_in cache_read total_out` with **no model** (`:664`); `day_cost` (`:346-355`) applies the current render's model rate to the whole day's summed tokens. A day mixing Opus and Sonnet sessions is priced as whichever model happens to be rendering.
*Fix:* record model id (and/or precomputed cost) per row in a backward-compatible `v2` log; price each row with its own model.

### C3 — The headline context bar is a 150k "soft-pressure" metric, not context fill — **Low/Medium**
`context_line` (`:2477-2504`) computes `fill = (total_input + total_output) / 150_000` (`SOFT_LIMIT`) and shows `pct_soft` as the headline %, with a secondary `(n%)` against `context_window_size` only when that field is present. The host's official `used_percentage` (input-based, parsed at `:527`) is not displayed. So the prominent number is a soft-limit pressure score that **includes output tokens**, not the official context-window fill.
*Fix:* label the soft-pressure bar as such and/or surface `used_percentage` (or `total / context_window_size`) as the true fill. **This matters for the macOS app:** its "context %" must be the official fill, not the soft-pressure score.

### G1 / G2 — Git detection breaks on worktrees/submodules and truncates branch namespaces — **Low/Medium**
`GitInfo._find_repo` treats `(cwd/.git).exists()` as a repo (`:825`), but `_read_head` then assumes `<gitdir>/HEAD` is a file (`:836-837`). In a linked worktree or submodule, `.git` is a **file** containing a `gitdir:` pointer, so HEAD resolution fails → blank branch — and because `_dirty` is gated on a non-empty branch, **dirty counts are suppressed too**. Branch display also drops namespace: `head.rsplit('/', 1)[-1]` turns `feature/foo` into `foo` (`:845`); a packed ref (no loose `refs/heads/<branch>` file) yields no commit.
*Fix (diverges from the reviewer's suggestion):* the reviewer proposed `git rev-parse` plumbing, but that **reintroduces per-render subprocesses** — exactly what finding P5 removes. Keep the fast file-reading path and make it correct: follow the `.git`-file `gitdir:` pointer, read `packed-refs`, and preserve the full branch path. (Claude Code's payload may also expose worktree info usable directly.)

### O1–O5 — Operational robustness
- **O1 (Low/Med):** `/yas:init` and `/yas:uninstall` use `mktemp`, `mv`, `rm`/`rm -f`, and run the discovered Python — none in `permissions-allow.json`. So the "reversible, pre-authorized" install can still prompt for approvals or fail under strict permission modes; §4.3's framing was too smooth. (Not a security issue — a UX/expectations caveat. Document it; be conservative about adding `rm` to any allowlist.)
- **O2 (Low/Med):** the lost-update window the audit noted for the rate log applies equally to `TokenLog.update` (`:653-685`) — concurrent sessions can clobber **daily** totals/cost, not just the sparkline.
- **O3 (Low):** atomic writes should cover the **existing** writes (payload `:2912`, both logs), not only new state/cache files; a torn payload write can make `mon` transiently drop a session.
- **O4 (Low):** `/yas:init` hardcodes `$HOME/.claude` (`skills/init/SKILL.md:91-108`) while the renderer and `/yas:uninstall` honor `CLAUDE_CONFIG_DIR`. A custom-config-dir user gets `statusLine` written where Claude Code won't read it. *Fix: resolve `CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"` in init, as uninstall already does.*
- **O5 (Low):** payloads are now one-per-session (PR #30) but ended sessions leave stale `statusline-output/*.json`; `mon` ignores but never prunes them. *Fix: opportunistically prune by mtime / missing transcript.*

### A3 — The optional Alacritty helper should be classified separately — **Low**
`claude/statusline/alacritty.py` is unreferenced by the README, writes `$HOME/.claude/terminal-width` directly (ignoring `CLAUDE_CONFIG_DIR`), runs `pgrep -f claude`, and sends `SIGWINCH` to every match. `SIGWINCH` is benign (resize), but this is broader than the scoped main renderer, and it is the one exception to §4.5's "all writes honor `$CLAUDE_CONFIG_DIR`" statement. *Mark optional/developer tooling, drop from distribution, or make it honor `CLAUDE_CONFIG_DIR` and target only the intended process.*

---

## 6. Tooling, language & architecture

### 6.1 Language: stdlib-only Python — right for now, with one structural cost
- **Pros:** zero supply-chain surface, trivial portability (any Python 3.10+), highly readable/maintainable, with **targeted** Windows accommodations (path-slug normalization at `:968`, UTF-8 stdout reconfigure at `:2880`) — though cross-platform path handling is **incomplete** (e.g. `short_pwd` splits on `/` at `:596`; OpenSpec filters the literal `'/archive/'` at `:1251`, which won't match Windows backslash paths). For a tool whose top user concern is "is it safe," dependency-free Python is a strong choice.
- **Con:** a fresh interpreter per render is the one cost the language imposes that algorithmic fixes can't remove. This is the legitimate basis for a later compiled hot path (Phase 3) — but only after the algorithmic wins (Phase 1), which matter regardless of language.

### 6.2 The monolith
`claude/statusline_command.py` is **2,928 lines** mixing data models, transcript parsing, token accounting, git, OpenSpec, the gradient/border/render engine, layout builders, and `main`. A `claude/statusline/` package already exists but holds only themes/demo/helpers. The single file is the clearest maintainability smell and the main obstacle to (a) the compiled rewrite and (b) sharing a data-collection core with a macOS app. *Recommendation:* split into a package behind stable public APIs (Phase 2).

### 6.3 Quality hygiene — strong (credit where due)
~40 pytest files in `test/`, `mypy --strict`, `ruff`, CI across three Python versions, ANSI render-parity fixtures, a benchmark harness, opt-in pre-commit hooks, and a clean user-vs-developer skill split. This is well above average for a status-line tool and makes the optimization work low-risk: existing tests act as a regression net.

---

## 7. Findings register

| ID | Area | Severity | Finding | Evidence | Recommendation |
|----|------|----------|---------|----------|----------------|
| S1 | Supply chain | Informational (positive) | Zero runtime deps; stdlib only | `pyproject.toml:9` | Keep it this way |
| S2 | Network | Informational (positive) | No outbound network anywhere | all `.py` | — |
| S3 | Plugin hooks | Informational (positive) | No auto-running hooks | `hooks/hooks.json:3` | — |
| S4 | Permissions | Low (positive) | 12 read-only shell allows only | `permissions-allow.json` | — |
| S5 | Config | Informational | `async: true` written but undocumented (effect unverified) | `skills/init/SKILL.md:101` | Verify vs running CC; drop if unsupported |
| P1 | CPU | **Medium** | Transcript scanned 3× per wide render; cost grows unbounded with session | `:918`,`:1102`,`:1198` | Single pass + incremental tailing (Phase 1) |
| P2 | I/O | Low | Two log files read+rewritten every render | `:666`,`:701`,`:717` | Append + write-on-change (Phase 1) |
| P3 | Process | **Medium** | Fresh Python interpreter every render (fixed cold-start) | process model | Collector/daemon or compiled binary (Phases 3–4) |
| P4 | Subprocess | Low | tmux probe spawned before cheaper width sources | `:101-109` | Reorder; spawn tmux last (Phase 1) |
| P5 | Subprocess | Low | `git status` every render, no cache | `:871` | Per-session 3–5 s cache (Phase 1) |
| P6 | I/O | Low | `openspec/` parent-walk every render even when unused | `:1265-1274` | Cache "no openspec here" per cwd (Phase 1) |
| P7 | Tooling | **Medium** | Benchmark uses tiny fixture, no real transcript → hides the real cost | `ops/bench.py:25` | Add realistic-transcript benchmark (Phase 0) |
| A1 | Maintainability | Medium | 2,928-line monolith | `statusline_command.py` | Split into package (Phase 2) |
| A2 | Correctness (latent) | Note | Incremental tailing must preserve id-dedup + task state | test `test_duplicate_message_id_counted_once` | Persist full `seen_ids` + task state; fail-safe to full scan (Phase 1) |
| S6 | Supply chain | Info/Low | CI `actions/checkout@v6` is a moving tag, not a SHA pin | `.github/workflows/ci.yml` | Pin by SHA or soften wording |
| C1 | Metric accuracy | **Medium** | Version-blind pricing (~3× high for current Opus, 20% low for Haiku 4.5); ignores host `total_cost_usd`; Fast-mode 6× unpriced | `:324-330`, `:499`, `:2712`; official pricing page | Prefer host cost; version-keyed fallback table (Phase 1) |
| C2 | Metric accuracy | **Medium** | Day cost prices all sessions with the current model (no per-row model) | `:346-355`, `:664` | Store model/cost per log row (Phase 1) |
| C3 | Metric accuracy | Low/Med | Headline context % is a 150k soft-pressure score (incl. output), not official fill | `:2477-2504`, `:527` | Use `used_percentage`/window size; relabel soft bar (Phase 1) |
| O1 | Operational | Low/Med | init/uninstall use `mktemp`/`mv`/`rm`/`python` outside the allowlist | `permissions-allow.json`; `skills/init/SKILL.md` | Document prompts; conservative allowlist (Phase 1/docs) |
| O2 | State consistency | Low/Med | Lost-update race also affects `TokenLog` (daily totals) | `:653-685` | Append-only / lock + atomic replace (Phase 1) |
| O3 | State robustness | Low | Existing payload/log writes are non-atomic | `:2912`, `:666`, `:717` | temp + `os.replace` for existing writes too (Phase 1) |
| O4 | Config | Low | `/yas:init` ignores `CLAUDE_CONFIG_DIR` (renderer/uninstall honor it) | `skills/init/SKILL.md:91-108` | Resolve `CONFIG_DIR` in init (Phase 1) |
| O5 | Housekeeping | Low | Stale `statusline-output/*.json` accumulate after sessions end | `mon/discovery.py`; `:2912` | Opportunistic prune (Phase 1/4) |
| G1 | Functional (git) | Low/Med | Worktree/submodule `.git`-file + packed-refs mishandled → blank git + suppressed dirty | `:805-899` | Parse `.git`-file pointer + packed-refs in file path (Phase 1) |
| G2 | Functional (git) | Low | Branch namespace truncated (`feature/foo`→`foo`) | `:845` | Preserve full branch path (Phase 1) |
| A3 | Ancillary | Low | Alacritty helper ignores `CLAUDE_CONFIG_DIR`; broad `pgrep`+SIGWINCH | `claude/statusline/alacritty.py` | Mark optional / harden (Phase 1/2) |

No High/Critical findings. The Medium items (C1, C2) are **metric-accuracy/trust** issues in an on-screen estimate, not security defects or functional breakage.

---

## 8. Recommended approach & roadmap

Ordered so each phase de-risks the next. **Phase 1 is where we start; the native macOS app (Phase 5) is the ultimate objective.** Each phase is independently shippable.

### Phase 0 — Land this audit + make performance measurable *(small)*
- Save this document as `AUDIT.md` at the repo root.
- **Extend `ops/bench.py`** with a realistic large transcript fixture (e.g. a generated multi-MB JSONL) and a populated git repo + token logs, so Phase 1's gains are quantified rather than asserted (addresses P7).
- Verify or drop `async: true` (S5).

### Phase 1 — Optimize & harden the Python statusline (in-place) *(the starting point)*
Keep Python + stdlib-only; keep visible output byte-identical. Guiding invariant: **the optimized result must equal a full scan, or fall back to a full scan** — every uncertain condition degrades to today's known-correct behaviour, so the worst outcome is "no speedup this render," never "wrong stats."

1. **Single-pass transcript scan.** Collapse the three scans (`LoadedSkills`/`TaskList`/`TranscriptUsage`) into one binary-mode pass that emits all three aggregates, parsing each line's JSON at most once. Keep the three existing classmethods as thin, test-stable projections over a memoized scan (so a wide render scans once; narrow scans none). (P1)
2. **Incremental append-only tailing.** Persist per session, under `~/.claude/statusline-scan/{session_id}.json`: last processed byte offset + full reconstructible state (the **complete `seen_ids` set**, the full task `by_id`/`next_id`/`last_event_ts`, the ordered skill list). Each render seeks to the offset and reads only new bytes. Correctness guards (all detailed, all fail-safe to full re-scan): persist `seen_ids` so duplicate ids never double/under-count across the boundary (A2); persist the task state machine (order-dependent); **never advance the offset past a non-newline-terminated final line** (mid-write protection); reset on inode/size/path mismatch (truncation/rotation/session-id reuse); atomic `os.replace` writes; wrap in try/except → full scan on any anomaly; `YAS_NO_INCREMENTAL` kill-switch. (P1, A2)
3. **Per-session git-status cache** (3–5 s TTL, env-tunable) keyed by `session_id` for the expensive `git status` only; branch/commit stay live (read from `.git/HEAD` every render so branch switches show instantly). (P5)
4. **Token-log churn reduction:** append new rate-log rows instead of full rewrite (prune lazily by size/age); rewrite the daily token log only when this session's totals changed. (P2)
5. **Gate the tmux subprocess:** try `terminal-width` file / `$COLUMNS` first; spawn tmux only if those don't yield a positive width. (P4)
6. **Cache the OpenSpec "not here" result** per cwd/session to skip the parent-walk when no `openspec/` exists. (P6)
7. **Add `_atomic_write_text`** (temp + `os.replace`) and route the new state/cache writes through it.

**Metric & state correctness (folded in after the independent review — these ship alongside the scan work, not later):**

8. **Cost (C1):** prefer the host's `cost.total_cost_usd` for session cost; replace substring pricing with a **version-keyed** table (by model id) as fallback, with tests that must be revisited when the model catalog changes.
9. **Day cost (C2):** store model id (and/or precomputed cost) per `statusline-tokens.log` row in a backward-compatible `v2` format; price each row with its own model.
10. **Context (C3):** surface the official `used_percentage` (or `total / context_window_size`) as the true fill; relabel the 150k soft-pressure bar.
11. **Atomic + lost-update (O2, O3):** route the **existing** payload and both logs through `_atomic_write_text`; move the rate/token logs to append-only + lazy compaction to close the multi-session lost-update window.
12. **Config dir (O4):** make `/yas:init` resolve and honor `CLAUDE_CONFIG_DIR`; document that init/uninstall may prompt for non-allowlisted commands (O1).
13. **Git correctness (G1, G2):** follow the `.git`-file `gitdir:` pointer, read `packed-refs`, and preserve full branch names — all in the file-reading path so **no per-render subprocess is added**.

Tests (extend `test/`): a **parity sweep** that splits a transcript at every newline boundary and asserts incremental-then-incremental == full-scan (directly proves no offset-boundary divergence); explicit dedup-across-boundary, partial-last-line, truncation/rotation/inode-reset, corrupt-state-fallback, atomicity, and git-cache tests. Existing transcript/task/usage tests are the regression net. Gate the PR on `pytest` + `mypy --strict` + `ruff` + the Phase-0 benchmark showing a win on a large transcript.

### Phase 2 — Maintainability refactor *(medium)*
Split the monolith into `claude/statusline/` modules (models, transcript scan, accounting, git, openspec, render/layout, themes) behind stable public APIs, leaving a thin `statusline_command.py` entry. No behaviour change; tests stay green. This isolates a clean **data-collection core** that both the compiled rewrite and the macOS app can reuse. (A1)

### Phase 3 — Compiled hot path (Go/Rust) *(larger; desirable after Phase 1–2)*
Port the per-render collection+render to a single statically-linked binary to eliminate Python interpreter cold-start (P3) — the one cost algorithmic fixes can't touch. The Phase 1 single-pass/incremental design ports directly. Ship prebuilt per-OS binaries (keep Python as fallback). **Recommendation: Rust**, because the same core can be compiled as a library and called from Swift over a C FFI — letting the terminal status line and the macOS app (Phase 5) share **one** collection engine. (Go is viable and simpler to build but doesn't give the Swift-library synergy.) Decision gate: confirm with the Phase-0 benchmark that cold-start is still the dominant cost after Phase 1.

### Phase 4 — Background collector + computed-stats JSON *(bridge to the app)*
Add a lightweight long-lived collector (the Rust core in daemon mode, or a small Python daemon) that incrementally watches all active transcripts and writes a **per-session computed-stats JSON** (model id + display name, **official context fill** *and* soft-pressure fill separately, session/day cost using the **host's `total_cost_usd`** with pricing source recorded, burn rate, subagents, tasks, rate limits, plus short **time-series history for charts**). Recording the *corrected* metrics here (per §5A: host cost, per-session model, official context %) is what lets the macOS app be a pure viewer. The terminal render then becomes a cheap read of that file. Today only the **raw** payload is persisted (`statusline-output/*.json`); a computed-stats artifact is the missing piece for charts.

### Phase 5 — Native macOS app (SwiftUI) — **ultimate objective** *(largest; detailed in §9)*
All four surfaces: menu-bar item + click popover, live Swift Charts, dock badge, multi-session overview. The app must be a **viewer of the Phase 4 computed-stats JSON** — it must **not** re-implement pricing, context %, transcript dedup, or task-state logic in Swift, or it would duplicate (and re-introduce) the C1/C2/C3 bugs in a second codebase.

---

## 9. macOS app — architecture & feature set

**Tech:** native **SwiftUI**, `MenuBarExtra` scene (macOS 13+) + **Swift Charts** + `NSApplication.dockTile`. Small footprint, no bundled runtime, dark-mode-aware, notarizable. (Rejected: Electron — heavy/ironic for a lightweight monitor; SwiftBar/xbar — fastest but no true native charts; Tauri — only if Windows/Linux tray becomes a goal.)

**Data flow (no stdin needed — the app reads files the renderer already produces):**
```
Claude Code ──stdin──▶ yas renderer ──writes──▶ ~/.claude/statusline-output/{session_id}.json     (raw payload, today)
                                          └────▶ ~/.claude/statusline-stats/{session_id}.json      (computed stats + history, Phase 4)
                                                          │  (FSEvents / DispatchSource watch)
                                                          ▼
                                              macOS SwiftUI app  ── reuses mon/discovery.py's discovery logic, reimplemented in Swift
```
- **MVP (no dependency on Phases 3–4):** read the existing `statusline-output/*.json` raw payloads (already contain model, context %, cost, rate limits) + `statusline-token-rate.log` for burn rate; compute the rest in Swift. Useful immediately.
- **Clean end-state:** consume the Phase 4 computed-stats JSON; the app is a thin viewer.

**Surfaces:**
1. **Menu-bar item** (`MenuBarExtra`): compact live indicator — context-fill % or a burn-state color dot + a tiny sparkline.
2. **Click → popover**: the most important stats, readable at a glance — model, context fill, session cost & day cost, burn rate (tok/min), 5h and 7d rate-limit usage, active task, running subagents, git branch/dirty. *(Per §5A: "context fill" must be the official `used_percentage`, not the 150k soft-pressure score; "cost" must use the host `total_cost_usd` / version-keyed rates — these come pre-corrected from the Phase 4 stats feed.)*
3. **Live charts** (Swift Charts) in the popover: burn rate over time, context fill, cumulative cost — backed by the Phase 4 history series.
4. **Dock**: a badge (context % or burn-state color) via `NSDockTile`. *Note:* full live charts rendered into the Dock tile are technically possible but low-value (tiny, easily missed); recommend a badge, with a richer dock tile only if specifically wanted.
5. **Multi-session overview**: list all active Claude Code sessions at once (port `mon/discovery.py`'s `find_active_jsonls` + `index_payloads_by_session` to Swift), select one to focus the popover/charts.
- **Plus:** native notifications when 5h/7d limits approach a threshold; sign + notarize the `.app`; optional Homebrew cask.

**Feature add/remove notes (the "superfluous?" question):**
- *Trim/make-optional/lazy:* the undocumented `async` flag (verify or drop); make the OpenSpec parent-walk lazy/cached (niche for most users); spawn tmux only as a last resort. None of these are user-facing removals — they cut per-render waste.
- *Add (mostly to enable the app & charts):* a computed-stats JSON artifact (Phase 4) and a short time-series history; a `--json` output mode on the renderer for a clean, testable stats API; rate-limit threshold notifications. Existing features (4 themes, width tiers, subagent/burndown/task rows) are low-cost and worth keeping.

---

## 10. Verification plan

- **Phase 0:** new realistic-transcript benchmark runs; capture baseline numbers (mean/min ms) for narrow/medium/wide on small + large transcripts.
- **Phase 1:** `uv run pytest test/` (existing + new tests) green; `uv run mypy .` clean under `--strict`; `uv run ruff check` clean; `ops/bench.py` (vs `main`) shows a measurable improvement on the large transcript and **no regression** on the small one; manual smoke via `make demo` to confirm byte-identical rendering across themes/widths; confirm the new state/cache files appear under `~/.claude/` and are correctly reset on truncation/rotation.
- **Phase 2:** test suite green with no behaviour change; import surface unchanged for tests.
- **Phase 3:** binary output diffed against the Python renderer across the fixture corpus (parity); benchmark quantifies the cold-start win.
- **Phase 4:** collector's computed-stats JSON validated against a full from-scratch recompute; the terminal renderer reading precomputed stats matches the direct-compute output.
- **Phase 5:** the macOS app's displayed numbers reconciled against the terminal status line for the same live session; multi-session list matches `mon`'s discovery; manual UX pass on the popover/charts/dock badge.

## 11. Evidence index (key file:line references)
- Entry/flow: `claude/statusline_command.py` `main` `:2872-2928`, `render` `:2858-2869`, builders `:2591/2638/2697`.
- Transcript scans: `:906-934`, `:1091-1144`, `:1188-1223`; id-dedup `:1208-1210`.
- Logs: `TokenLog` `:653-685`, `TokenRate` `:693-726`.
- Git: `:805-899` (subprocess `:871-875`). OpenSpec: `:1242-1274`. Subagents: `:956-1010`. Width: `:101-129`.
- Observer/data feed: `claude/mon/discovery.py:18-95`; payload write `:2908-2912`.
- Plugin surface: `hooks/hooks.json`, `.claude-plugin/permissions-allow.json`, `.claude-plugin/plugin.json`, `skills/init/SKILL.md` (settings write `:100-109`), `.github/workflows/ci.yml`.
- Deps/quality: `pyproject.toml` (`dependencies = []` `:9`, mypy strict `:19-32`). Benchmark: `ops/bench.py` (fixture `:25`).
- Metric correctness (§5A): pricing `rates_for` `:324-330` (+ test `test/test_model_cost_rates.py`); host cost parsed-but-unused `Cost` `:488-504`, recomputed at `build_wide:2712`; day cost `:346-355` + modelless log row `:664`; context `context_line` `:2477-2504` + parsed-but-unused `used_percentage` `:527`; git `:805-899` (worktree/branch); init config-dir `skills/init/SKILL.md:91-108`; Alacritty helper `claude/statusline/alacritty.py`. Pricing cross-checked against `platform.claude.com/docs/en/about-claude/pricing` (2026-05-27).
