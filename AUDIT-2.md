# Adversarial System-Audit Report — `yet-another-statusline`

*Scope: a stdlib-only Python Claude Code statusline plus a Claude Code data/feature review. Every finding below survived adversarial verification; refuted findings were removed (one — see appendix). Severities used are the verifier's `corrected_severity`; where that differs from the finder's original, both are shown. Locations are `file:line` against the repository state at audit time.*

---

## Executive summary

**Counts by corrected severity** (32 retained findings):

| Severity | Count | IDs |
|---|---|---|
| Critical | 0 | — |
| High | 6 | D1-1 (context-metric), FG-5†, DW-1, T1-1, A1-1, A1-2, D-1 |
| Medium | 9 | D1-1 (accounting), D1-2 (accounting), D1-5 (scan), FG-4, DW-2†, R-2†, R-3, R-4, R-5, R-6, R-7, R-8, A1-3, D-2, D-3† |
| Low | 14 | D1-2/D1-3/D1-4 (context-metric), FG-1†, FG-6/7/8/9/10/11, DW-3†, DW-4, D1-2/D1-3 (scan), D1-9 (scan)†, D1-2/D1-3/D1-4/D1-5 (accounting), T1-3, T1-4, T1-5, O2, G1, G2, G3, G4, T1, T2-clear, C1, R-9, R-10, A1-4, A1-5, A1-6, A1-7, D-5, D-6, D-7 |
| Info | many | (data-effectiveness "checked-OK" notes, FG-3†, G4†, D-8, D-9, R1, D1-1/D1-3/D1-4/D1-6/D1-7/D1-8-residual) |

†indicates a corrected severity that differs from the finder's original (detailed in each entry). Several IDs appear at more than one severity because distinct findings share an ID prefix across finder streams; this report disambiguates by `(stream)` tag and merges true duplicates.

> Note on counting: the finder streams reused short ID prefixes (`D1-*` appears in the context-metric, scan-redundancy, and accounting streams). To keep IDs stable and auditable, this report assigns each finding a **report ID** of the form `<stream>-<n>` and cross-references the finder's original ID in each entry.

**Highest-impact items.** The single most consequential cluster is **terminal-escape / trust-boundary security** (`SEC-1`/A1-1 and `SEC-2`/A1-2): attacker-authored repo artifacts (`.git/HEAD`, a cloned repo's `.claude/settings.json`, crafted transcripts/subagent files) flow verbatim to stdout with no control-character sanitization, enabling zero-interaction OSC-52 clipboard hijack and window-title spoofing the moment a trusted repo is opened — both empirically reproduced, and both directly contradicting the prior audit's "Security: LOW risk; genuinely clean" verdict. Equally load-bearing on the data-correctness side is the **context-percentage cluster** (`DATA-1`/D1-1 et al.): the headline context bar adds output tokens to an already-cache-inclusive input total and ignores the host's pre-calculated `used_percentage`, so it systematically reads higher than Claude Code's own `/context` indicator. On robustness, `ROB-1`/R-1 (non-object stdin crashes `main()` before any render) and `TRN-1`/T1-1 (in-place `/compact` rewrite defeats incremental-scan validation, producing stale/under-counted token, cost, task, and skill stats) are both high-severity and trivially or routinely reachable. Finally, two data-effectiveness/operational defects round out the top tier: `WIDTH-1`/DW-1 (the authoritative `COLUMNS` width is consulted *third*, behind a tmux subprocess and a stale width-file, mis-sizing the box for tmux power users) and `MON-1`/D-1 (the `mon` TUI hardcodes `~/.claude` and shows "no active sessions" forever for any `CLAUDE_CONFIG_DIR` user).

---

## 1. Data-effectiveness and doc-alignment

*Are we pulling Claude Code's data the best way?*

### WIDTH-1 — `COLUMNS` (the authoritative width per the official contract) is consulted third, behind a tmux subprocess and a stale width-file
- **Severity:** High *(finder D3 original: high; confirmed high)*
- **Location:** `claude/statusline_command.py:96-133` (probe order); `COLUMNS` read at `:112`
- **Evidence:** `terminal_width()` probes in order: (1) `tmux display-message` subprocess (`:98-104`), (2) `CLAUDE_DIR/'terminal-width'` file (`:105-110`), (3) `COLUMNS` env (`:111-116`), (4) `shutil.get_terminal_size` (`:117-119`), (5) `os.get_terminal_size` on fds 2/1/0 (`:120-124`), (6) `/dev/tty` ioctl (`:125-132`), (7) `MAX_WIDTH` fallback (`:133`). `test/test_render_callable.py:85-91` strips `TMUX_PANE/TMUX` precisely so `COLUMNS` becomes authoritative — independently documenting the consequence. Downstream cap: `width = max(MIN_WIDTH, min(MAX_WIDTH=140, raw_tw-6))` (`:1820-1828`).
- **Doc basis:** Per the official contract (v2.1.153+), Claude Code captures the script's stdout (non-tty) and **sets `COLUMNS`/`LINES` to the exact dimensions it allocated** before invoking the script. `COLUMNS` is therefore correct by construction.
- **Impact:** Inside tmux (the common power-user case) the renderer sizes to the raw pane width, not Claude Code's allocated statusline width — these differ whenever `statusLine` padding/reserved margin/pane chrome is in play, producing overflow/wrap or under-fill. (Bounded: on wide panes both paths collapse to the 140 cap; divergence manifests below ~146 columns or when pane vs allocation differs by more than the 6-col margin.)
- **Fix:** Move the `COLUMNS` block (`:111-116`) to the top of `terminal_width()`, ahead of the tmux probe; return it when `>0` before any subprocess or file read. Keep tmux + width-file as fallbacks for older Claude Code / the standalone `make demo` path. Update `README.md:63,77-82` (which currently calls `COLUMNS` a "fallback when tmux / width-file detection fail"). Secondary win: removes a `tmux display-message` fork/exec from every tmux render. Cross-refs prior **P4 + A3**.

### DATA-1 — Context bar adds output tokens to an already-cache-inclusive input total, overstating % vs official `used_percentage`
*Merged: context-metric stream D1-1, D1-3; scan stream D1-1; feature-coverage FG-2.*
- **Severity:** High *(context-metric D1-1: high, confirmed high; the D1-3/D1-2/FG-2 facets are medium — see below)*
- **Location:** `claude/statusline_command.py:1341,1346-1347` (`context_line`); `1358,1360-1361` (`context_line_compact`); `1502-1503/1549-1550/1608-1609` (`build_narrow/medium/wide` fill). Pre-calc parsed (and ignored) at `claude/statusline/models.py:259,266,273`.
- **Evidence:** All five sites compute `total_tokens = ctx.total_input_tokens + ctx.total_output_tokens`, then `pct = min(total/scale,1.0)*100`. Per the schema, `total_input_tokens` is **already** `input + cache_creation + cache_read`, and the official `used_percentage` is **input-only** (excludes `output_tokens`). Worked example (verified numerically): input 5k + cache_creation 20k + cache_read 100k ⇒ `total_input_tokens=125000`; output 8k; window 200000 ⇒ official `used_percentage = 62.5%`, renderer `= 66.5%` (+4.0 pp, 6.4% relative overstatement; grows with assistant-turn length). This is **not** cache double-counting — cache is inside `total_input_tokens`; the defect is the added output term.
- **Doc basis:** "`used_percentage` … from INPUT TOKENS ONLY"; "Use `used_percentage` for the simplest accurate context state"; "use the same input-only formula to match `used_percentage`."
- **Impact:** Headline % and gradient fill read higher than Claude Code's own context indicator and `/context`, persistently. No crash; persistent misinformation in the headline data widget.
- **Fix (verifier-improved):** Introduce **one shared helper**: `pct = ctx.used_percentage if ctx.used_percentage is not None else 100*total_input_tokens/(ctx.context_window_size or SOFT_LIMIT)` — input-only, never adding `total_output_tokens`. Route all five sites through it so the headline number, the bar fill, and `/context` agree. The null fallback is **required** (per schema `used_percentage` is null early and after `/compact`). Separately note the `build_*` fill uses a hardcoded `SOFT_LIMIT=150000` denominator while `context_line` uses the true window — a denominator inconsistency the same helper resolves. Cross-refs prior **C3 / UX1** (refines them).

### DATA-2 — Pre-calculated `context_window.used_percentage` is parsed but never read (and `remaining_percentage` is dead-parsed)
*Merged: context-metric D1-2; feature-coverage FG-2 + FG-3.*
- **Severity:** Medium *(finder context-metric D1-2 original: high → corrected **medium**; FG-2 confirmed medium; FG-3 original low → corrected **info**)*
- **Location:** parsed at `claude/statusline/models.py:259-260,266-267,273-274`; never read by any renderer — every `.used_percentage` read in `statusline_command.py` (`854,946-955,963,1455-1474`) is on `RateBucket`, not `ContextWindow`.
- **Evidence:** Grep confirms zero `ctx.used_percentage`/`ctx.remaining_percentage` consumers. The renderer recomputes from raw token fields instead of consuming the authoritative pre-calc. `remaining_percentage`'s only other repo occurrence is the example fixture.
- **Doc basis:** `used_percentage`/`remaining_percentage` are pre-calculated, authoritative, input-only.
- **Impact:** The script discards "the simplest accurate context state" and substitutes a manual calc that can disagree with `/context`. `remaining_percentage` is genuinely dead (one `isinstance`+`float()` over already-parsed JSON; no user-visible effect).
- **Confidence:** High.
- **Fix:** Subsumed by DATA-1's shared-helper change (prefer `used_percentage` when non-null). For `remaining_percentage`: either wire it as the directly-displayed "remaining" figure (preferred — display the host value rather than computing `100 - used_percentage`, since both can independently be null) or delete the field; decide jointly with DATA-1. Cross-refs prior **C3 / UX1**.

### DATA-3 — Null-handling: `used_percentage`/`current_usage` null early and after `/compact` are silently treated as 0% via raw token fields
- **Severity:** Low *(finder context-metric D1-4: low, confirmed low)*
- **Location:** `claude/statusline/models.py:273-274` (`used_pct→None`), `264-265/176-181` (`CurrentUsage` defaults 0); `claude/statusline_command.py:1341,1346` (renderer ignores None).
- **Evidence:** `used_percentage` correctly parses to `None`; `current_usage` defaults to an all-zero `CurrentUsage` when null. No crash today (renderer never divides by the pre-calc), but no explicit null-vs-zero branch exists.
- **Doc basis:** `used_percentage`/`current_usage` "may be null early / after `/compact`".
- **Impact:** Forward-looking robustness gap gating the DATA-1/DATA-2 switch: adopting `used_percentage` without a guard would crash (`None/100`) or mis-render. Today's only symptom is a possible transient 0% read after `/compact`.
- **Confidence:** Medium (low present-day impact; arguably info).
- **Fix:** When adopting `used_percentage`, guard `None`: if `None` **and** `total_input_tokens == 0`, render a neutral "no data yet" bar; else fall back to the input-only manual calc. The fallback must be input-only (`total_input_tokens`, excluding output). Distinguishing "present and zero" from "absent" for `current_usage` would require an `Optional` wrapper rather than the `{}`→zero coercion at `models.py:265`.

### DATA-4 — `exceeds_200k_tokens` parsed but never used — no >200k context alert despite a ready-made host flag
- **Severity:** Medium *(finder FG-4: medium, confirmed medium)*
- **Location:** field `claude/statusline/models.py:304`; parse `:329`; no consumer.
- **Evidence:** Grep finds no reader. Context color comes solely from `fill_colour(pct)` (`statusline_command.py:827-832`: `≥90` alert, `≥70` warn) keyed off `context_window_size`. On a 1M window, 200k = 20% fill ⇒ "safe"; warn isn't reached until ~700k. The host's explicit fixed-threshold boolean is dropped exactly where the manual pct can't catch it. The boolean is `total` (incl. output) against a **fixed** 200k threshold, so it is not strictly redundant even on 200k windows.
- **Doc basis:** `exceeds_200k_tokens` — bool, "total exceeds 200k; fixed threshold regardless of window size."
- **Impact:** On extended (1M) windows the statusline gives no warning when the conversation crosses the 200k cost/behavior boundary.
- **Confidence:** High.
- **Fix:** Thread the boolean from `SessionInfo` (where `build_*` already has `session`) into a **distinct marker** (a warn-colored glyph/badge), not merely flooring `fill_colour` to warn — the two quantities (window-relative fill vs fixed-200k total) differ and collapsing them is misleading. Keep it a top-level `SessionInfo` flag (do **not** nest under `ContextWindow`). Gate it to be most prominent when `context_window_size > 200000`.

### DATA-5 — Session elapsed is computed from transcript file mtime, but stdin ships `cost.total_duration_ms` (true wall clock)
*Merged: scan-redundancy D1-5; the scan-reduction recommendation D1-9 corroborates.*
- **Severity:** Medium *(finder scan D1-5: medium, confirmed medium)*
- **Location:** `claude/statusline/accounting.py:39-51` (`elapsed_from_transcript`); call site `statusline_command.py:1629`; `cost.total_duration_ms` parsed at `models.py:246` and never read.
- **Evidence:** `elapsed_from_transcript` reports `now - p.stat().st_mtime` (time-since-last-write / staleness), not session duration. `cost.total_duration_ms` ("wall clock since session start") is parsed but unused; grep shows zero renderer consumers. Rendered inline with cwd/branch (`statusline_command.py:766`) where a user reads it as session duration.
- **Doc basis:** `cost.total_duration_ms` = wall clock since session start.
- **Impact:** Displayed elapsed is semantically wrong (measures recency, drifts between writes) **and** forces a `stat()` on the wide hot path for a value stdin already provides correctly.
- **Confidence:** High.
- **Fix:** Pass a formatting of `session.cost.total_duration_ms` (ms→h/m) at `:1629`, removing the `stat()`. Guard the zero case (`total_duration_ms==0` before first response → return `''`/`'0m'` so the existing tail-suppression at `:766` hides it). The function signature and call site both change (accept ms; divide by 1000); a pure rename is insufficient. If an "idle since" indicator is later wanted, reintroduce it under an explicit name/label. Cross-refs prior scan-reduction recommendation **D1-9** (reducible piece #1).

### DATA-6 — Scan-redundancy survey: which scan outputs are genuinely load-bearing (mostly "checked-OK")
*Merged: scan-redundancy D1-1, D1-2, D1-3, D1-4, D1-6, D1-7, D1-9.*
- **Severity:** Info / Low *(all confirmed at info except D1-2 cache-split = low and D1-9 = low; D1-9 finder original medium → corrected **low**)*
- **Locations / verdicts:**
  - **D1-1 (info):** Headline context line runs entirely off stdin (`statusline_command.py:1340-1368`); the transcript scan is **not** load-bearing for it. The scan's input/cache/output are session-cumulative sums (`transcript.py:350-363`), a different quantity from stdin's most-recent-response snapshot — must not be conflated.
  - **D1-2 (low):** Current-context cache split is on stdin via `current_usage` (`models.py:168-181`) but is **never read** (import-only, `# noqa F401` at `statusline_command.py:34`). The TOKENS panel deliberately shows *cumulative* session cache from the scan (`TranscriptUsage.billed_in/cache_read/out`), which stdin does not provide — so the scan stays load-bearing here. `current_usage` is dead-parsed weight. **Fix:** delete the unused `CurrentUsage` import/parse (preferred), or wire it as an *additional* per-turn breakdown (not a scan replacement); guard for null after `/compact`.
  - **D1-3 (info):** Session cost prefers stdin `cost.total_cost_usd` (`accounting.py:62-71`); the scan estimate is only the host==0 fallback. Day cost & cross-session token-log have **no** stdin equivalent — scan is load-bearing.
  - **D1-4 (info):** Per-message burn-rate sparkline + t/m are **not** derivable from stdin (`total_input_tokens` is a non-monotonic snapshot; only `total_duration_ms` is on stdin). Scan + rate log are load-bearing. (Refinement: USD-burn/lines-burn *are* derivable from stdin's cumulative `total_cost_usd`/`total_lines_*`; only the *token* time series needs the scan.)
  - **D1-6 (info):** Loaded skills have no stdin equivalent — scan fully load-bearing.
  - **D1-7 (info):** Main-session task list has no base-hook stdin equivalent (the `subagentStatusLine` `tasks` array is a different, subagent-scoped surface) — scan stays.
  - **D1-9 (low):** **MUST STAY:** the single-pass `TranscriptScan` (skills + tasks + cumulative usage). **CAN BE REDUCED:** (1) `elapsed_from_transcript` → `cost.total_duration_ms` (see DATA-5); (2) `RunningSubagents.from_session` → migrate to `subagentStatusLine` (see FEAT-1), keeping the scanner as legacy fallback. **CONSIDER:** drop the unused `CurrentUsage` parse.
- **Confidence:** High throughout.

---

## 2. Feature-capture opportunities

*Unconsumed official fields/features.*

### FEAT-1 — Running-subagent rows are reconstructed by scanning `subagents/*.jsonl + *.meta.json`; the official `subagentStatusLine` hook is the native source
- **Severity:** Medium *(finder scan D1-8: high → corrected **medium**)*
- **Location:** `claude/statusline_command.py:1519,1590,1623,1069-1185` (`subagent_row`); `claude/statusline/transcript.py:62-175` (`RunningSubagents.from_session`).
- **Evidence:** `from_session` re-derives Claude Code's slug (`re.sub(r'[^A-Za-z0-9]','-', project_dir)`, `transcript.py:80` — a documented past Windows-path hazard), globs `subagents/*.meta.json`, applies a bespoke `STALE_SECONDS=20` mtime cutoff, and line-parses every `.jsonl` (message-id dedup, first-timestamp baseline). The official `subagentStatusLine` hook ships this natively as a `tasks` array (`id,name,type,status,description,label,startTime,tokenCount,tokenSamples,cwd`). The hook is **not** configured anywhere (grep across `hooks/hooks.json`, `.claude-plugin/*.json`).
- **Doc basis:** `subagentStatusLine {type,command}`; stdin `tasks[]`; output one `{id,content}` line per row.
- **Why downgraded from high:** the finder framed the hook as a drop-in "delete the scanner entirely" replacement, but **(A)** `subagentStatusLine` renders in a *separate agent panel*, while this repo renders subagent rows **inline** inside the main bordered box (`build_narrow:1536-1539`, `build_medium:1595-1599`, `build_wide:1712-1715`) — migrating relocates the data to a different UI surface; and **(B)** the schema does not define `tokenCount`'s components or `status`'s enum, while the renderer actively uses a token breakdown (`total_input = billed_in + cache_read`, `transcript.py:116`; risk-zone color at `:1078`; share % at `:1110`) — a naive swap could silently change displayed numbers.
- **Impact:** The bespoke scanner (slug re-derivation, glob, per-file stat/parse, 20s heuristic) duplicates host bookkeeping and is fragile to `projects/` layout changes — a fragility-reduction opportunity, not a correctness defect (the code is tested and working).
- **Fix (verifier-improved):** Decide product intent first (inline vs agent-panel). The **lowest-risk concrete win**: `tasks[]` provides per-task `cwd`, which eliminates the slug re-derivation (the Windows hazard) entirely — do this even if the per-`.jsonl` token parse is retained. If the agent panel is acceptable, add a dedicated `subagentStatusLine` entrypoint reading `tasks[]` and emitting `{id,content}`, then retire the inline scanner, keeping it as a fallback for pre-hook Claude Code. Before trusting `tokenCount/tokenSamples` as a 1:1 substitute, verify their semantics against a live Claude Code instance. Cross-refs prior subagent-burn work (CONTEXT.md:57,69; AUDIT.md:111).

### FEAT-2 — `pr.{number,url,review_state}` not parsed or displayed
- **Severity:** Low *(finder FG-5: medium → corrected **low**)*
- **Location:** no PR model; `SessionInfo.from_dict` ignores `'pr'` (`models.py:310-334`); natural sibling is `path_git` (`statusline_command.py:769-774`).
- **Evidence:** Grep confirms no `pr`/`review_state`/PR handling. `pr.*` is present only while an open PR exists for the branch; `review_state ∈ {approved,pending,changes_requested,draft}`, each field independently absent.
- **Doc basis:** `pr.number, pr.url, pr.review_state`.
- **Why downgraded from medium:** pure feature gap for an optional, ephemeral, branch-scoped field — nothing is broken or misleading; the "highest-value missing git signal" framing is an editorial judgment. The repo already surfaces branch + commit + dirty.
- **Impact:** Whether a branch's PR is approved / needs changes is invisible on the statusline.
- **Confidence:** High.
- **Fix (verifier-corrected):** Add a `Pr` model parsed in `SessionInfo.from_dict`; render a colour-coded badge after the branch. **Corrections to the finder's recommendation:** (1) the renderer emits **zero OSC-8 sequences today** (grep-confirmed) — OSC-8 hyperlinking the PR badge is *new* capability, and `_visible_width` (`:788`) must be confirmed to strip OSC-8 or the badge mis-budgets; (2) degrade to neutral `#<number>` when `review_state` is absent; (3) don't collapse `pending`/`changes_requested` — use green=approved, red/orange=changes_requested, yellow=pending, dim=draft, neutral=absent; (4) place the badge in the `fit_path` drop-priority ladder (`:790-822`).

### FEAT-3 — `session_name` (from `--name`/`/rename`) not parsed or displayed
- **Severity:** Low *(finder FG-6: low, confirmed low)*
- **Location:** `SessionInfo` (no field); `from_dict :310-334`. Raw `session_id` UUID is already rendered in the top border (`border_top :481-503`).
- **Evidence:** Grep empty for `session_name`. `SESSION` colour role exists (`:477,766`).
- **Doc basis:** `session_name` — custom name from `--name`/`/rename`; absent if unset.
- **Impact:** Multi-session users get no human-friendly identifier on the line.
- **Confidence:** High.
- **Fix:** Add `session_name: str = ''`, parse defensively (`str(sn) if sn is not None else ''`). Prefer displaying it **in place of** the existing `session_id` UUID in `border_top` (which already owns the identity slot and has truncation logic), rather than crowding the path row.

### FEAT-4 — `agent.name` (`--agent`/agent settings) not parsed or displayed
- **Severity:** Low *(finder FG-7: low, confirmed low)*
- **Location:** `SessionInfo` (no field); `from_dict :310-334`. (Unrelated to `RunningSubagents.agent_type`, which is per-subagent `agentType`.)
- **Doc basis:** `agent.name` — when running with `--agent` or agent settings.
- **Impact:** When the main session is itself an agent, the active persona is not surfaced (uncommon for interactive use).
- **Confidence:** High.
- **Fix:** Add a `@dataclass Agent` with `from_dict` (matching the repo's Effort/Thinking pattern, **not** NamedTuple), wire `agent = Agent.from_dict(_dict('agent'))`, render a badge near the model pill only when `name` is non-empty; respect the LayoutSpec/RowSpec width pipeline (per the `tmck-code-statusline` skill's column-math hazards).

### FEAT-5 — `workspace.git_worktree` not parsed/displayed (no cue the cwd is inside a linked worktree)
- **Severity:** Low *(finder FG-8: low, confirmed low)*
- **Location:** `Workspace.from_dict` parses only `current_dir/project_dir/added_dirs` (`models.py:204-210`); `git.py` resolves worktree gitdirs internally (`_resolve_gitdir:106-125`, `_read_commit` commondir `:160-193`) but never surfaces the worktree **name**.
- **Doc basis:** `workspace.git_worktree` — worktree name when cwd is inside ANY linked git worktree (broader than `worktree.*`).
- **Impact:** Multi-worktree users see identical framing with no disambiguation; absent for the main-tree majority.
- **Confidence:** High.
- **Fix:** Add `git_worktree: str = ''` to `Workspace`; render adjacent to the branch styled distinctly. The display is more than "one conditional": thread the tag through **both** `path_git` and `path_git_compact` (`:776-781`) and add it to the `fit_path` drop ladder (`:791-795`, e.g. dropped after commit, before elapsed). `GitInfo` carries no worktree data, so pass it from the `Workspace` side.

### FEAT-6 — `worktree.{name,path,branch,original_cwd,original_branch}` not parsed/displayed (`--worktree` sessions)
- **Severity:** Low *(finder FG-9: low, confirmed low)*
- **Location:** `SessionInfo` (no `worktree` field); `from_dict :310-334`.
- **Doc basis:** `worktree.*` — only during `--worktree` sessions; `branch`/`original_branch` absent for hook-based worktrees.
- **Impact:** Narrow (`--worktree`-only); largely overlaps FEAT-5. `original_branch` is a useful "where I came from" breadcrumb.
- **Confidence:** High.
- **Fix:** Implement conditionally alongside FEAT-5, preferring `git_worktree` as the primary signal; show `name (from original_branch)` and guard for absent `branch`/`original_branch`. Parse is trivial (mirror Effort/Thinking); the effort is display/layout.

### FEAT-7 — `workspace.repo.{host,owner,name}` not parsed/displayed (origin-remote identity)
- **Severity:** Low *(finder FG-10: low, confirmed low)*
- **Location:** `Workspace :196-211` (no `repo` field); `short_pwd :336-350`.
- **Doc basis:** `workspace.repo.{host,owner,name}` — parsed from origin remote; absent outside a git repo / with no origin.
- **Impact:** cwd already conveys identity in the common single-repo case; marginal value disambiguating same-named local dirs across forks.
- **Confidence:** High.
- **Fix (verifier-corrected):** Parse defensively (treat the whole sub-object as optional). The finder's "show when it differs from the leaf dir" heuristic is wrong (owner almost always differs → near-always renders); better: show `owner/` dim prefix only when the leaf dir name ≠ `repo.name`, or gate behind an opt-in flag. Defer the "feed the PR badge's OSC-8 host" synergy until FEAT-2 lands. Low payoff; rank after the PR badge.

### FEAT-8 — `vim.mode` not parsed/displayed; `hideVimModeIndicator` not honored
- **Severity:** Low *(finder FG-11: low, confirmed low)*
- **Location:** `SessionInfo` (no `vim` field); `Workspace.plugins` reads `settings.json` `:213-231` but not `hideVimModeIndicator`.
- **Doc basis:** `vim.mode` — `NORMAL|INSERT|VISUAL|VISUAL LINE` (only when vim mode on); settings has `hideVimModeIndicator`.
- **Impact:** Editor-input concern, largely out of scope for a monitoring statusline; rendering it would also require coordinating `hideVimModeIndicator` to avoid a doubled "-- INSERT --".
- **Confidence:** High.
- **Fix (lowest priority; likely skip):** If added, parse `vim.mode` (absent when off → render nothing), render a tiny tag, and **document/auto-suggest** `statusLine.hideVimModeIndicator:true` (the script cannot itself "honor" it — Claude Code acts on the flag).

### FEAT-9 — Redundancy check: `workspace.git_worktree`/`workspace.repo` do **not** make `git.py` redundant (`git.py` is necessary)
- **Severity:** Info *(finder R1: info, confirmed info)*
- **Location:** `claude/statusline/git.py` (whole); `models.py:196-211`.
- **Evidence:** `git.py` computes branch, commit `[:9]`, and dirty counts — none of which appear in the official JSON. The stdin `git_worktree`/`repo` fields are not even parsed.
- **Impact:** `git.py` is necessary, not redundant. Separately, the free official fields (FEAT-5, FEAT-7) are left on the table.
- **Confidence:** High.
- **Fix:** Keep `git.py`. The `repo.owner/name` opportunity (FEAT-7) is genuinely additive; the `git_worktree` opportunity (FEAT-5) is only a name badge (worktree correctness already handled).

---

## 3. Correctness bugs

### ACCT-1 — `day_cost` prices cache-creation tokens at 1.0× instead of 1.25×, undercounting day cost (inconsistent with `session_cost`)
- **Severity:** Medium *(finder C1 D1-1: high → corrected **medium**)*
- **Location:** `claude/statusline/models.py:85-101` (`day_cost`, lines `:93` and `:97`) vs `:77-82` (`session_cost`); fed by `statusline_command.py:1619`.
- **Evidence:** `usage.billed_in = input + cache_creation` (`transcript.py:253-255`) is logged as the single "in" column (`accounting.py:101`), rolled into `day_in` (`:142`) and `by_model[...][0]` (`:146`), then priced at `rate_in * 1.0` in both `day_cost` paths. `session_cost` prices `cache_creation` separately at `rate_in * 1.25`. Reproduced numerically (Opus 4.7, input=0/cache_creation=1M/out=0): `session_cost=6.25` vs `day_cost=5.00` (dropped 0.25× write surcharge). No `day_cost` test embeds cache_creation in `total_in`, so all 15 relevant tests pass.
- **Doc basis:** Official 5-minute-cache pricing: cache write = 1.25× base input (the ratio `session_cost` already uses; AUDIT.md:178 verified live 2026-05-27).
- **Why downgraded:** affects only a secondary derived **day-cost estimate** (no billing impact); the primary displayed session cost is usually the host's `cost.total_cost_usd`; error is bounded at 25% of base-input rate on the day's cache-creation portion.
- **Fix (verifier-improved):** The token log conflates plain-input and cache-creation into one column, so 1.25× is unrecoverable downstream — **option (a) is required**: log cache_creation as its own column (extend the row to `date sid input cache_creation cache_read out model`), pass `usage.input_tokens` and `usage.cache_creation_input_tokens` separately at `:1619`, extend `by_model` tuples, and price `dcache_creation * rate_in * 1.25`. **Caveat the finder missed:** this is an on-disk log *format* change — revise the v2 6-field parse (`:134-135`) and legacy branches, add a migration path (old rows keep 1.0×), and keep the `tokens_cost` display consumers (`:1638-1639`) working. Add a test embedding cache_creation in a day row.

### CTX-NEG — Negative `total_input_tokens` produces an unclamped negative fill_ratio → context bar overflows the box and prints a negative %
- **Severity:** Medium *(finder C4 R-4: medium, confirmed medium)*
- **Location:** `claude/statusline_command.py:1346 & 1360` (`fill_ratio = min(total/scale, 1.0)`); `build_narrow/medium` `1503/1550` (and `1609`).
- **Evidence:** `min(..., 1.0)` caps the top but has no `max(0.0, ...)` floor. With `total_tokens=-100000, scale=200000` ⇒ `fill_ratio=-0.5`; `filled<0` ⇒ `empty = bar_w + |filled| - 1`. Reproduced end-to-end: box 114 wide, context row renders at 158 cells (44-cell overflow) and prints `-50%`/`-100000`. Both `context_line` (build_wide) and `context_line_compact` (build_narrow/medium) overflow.
- **Doc basis:** token counts are `≥0`; a negative value is out-of-contract input the renderer should clamp.
- **Impact:** A negative count (host bug or post-`/compact` transient) corrupts box-border alignment by tens of cells and shows a nonsensical negative %. No crash.
- **Fix (verifier-improved):** Clamping `fill_ratio` to `[0,1]` alone is **insufficient** (still ~117 cells at avail 120, still shows wide `-100000`). **Floor the token total at zero** — preferred single point: `ContextWindow.from_dict` (`models.py:~269-270`) `total_input_tokens=max(0,_as_int(...))`, `total_output_tokens=max(0,_as_int(...))`, protecting every consumer. The `build_*` fill clamps are unnecessary (that value flows only to `grad_at`, which tolerates `fill≤0` with no geometry impact).

### CWIDTH — `_is_wide` miscounts all non-emoji wide characters (CJK, fullwidth, Hangul) as width 1 → box overflow on wide model/dir/branch
- **Severity:** Medium *(finder C4 R-5: medium, confirmed medium)*
- **Location:** `claude/statusline/textutil.py:32-43` (`_is_wide`/`_visible_width`).
- **Evidence:** `_is_wide` returns True only for emoji `0x1F300–0x1FAFF` (minus Supplemental-Arrows-C). East-Asian Wide/Fullwidth/Hangul (EAW=W/F) occupy 2 cells but count as 1. Verified: `'漢'*32` → `_visible_width=32` vs true 64; `border_line` padding `pad = max(0, width - K - _visible_width(content))` (`statusline_command.py:580,585,589`) then pushes the right `│` past the true width.
- **Doc basis:** cwd/`current_dir`, `model.display_name`, `session_name`, branch are arbitrary strings; the renderer must keep box width = terminal width.
- **Impact:** Any CJK/fullwidth/Hangul in cwd/branch/model/skill/session-name overflows and misaligns the box. ASCII (common case) unaffected.
- **Fix (verifier-improved):** Layer the tests: `wide = _is_wide_emoji(cp) OR unicodedata.east_asian_width(ch) in ('W','F')` (keep the emoji range — some pictographs are EAW=N). Treat `unicodedata.combining(ch)` or category `'Mn','Cf'` as width 0. Disclose residual limits (ZWJ sequences, `U+FE0F`, regional-indicator flag pairs cannot be resolved per-codepoint). Box-drawing chars and `…` are EAW=N → stay 1 (no regression).

### CTRUNC — `_middle_ellipsis` can exceed its `max_w` budget on wide characters
- **Severity:** Medium *(finder C4 R-6: medium, confirmed medium)*
- **Location:** `claude/statusline/textutil.py:46-91` (single-char overshoot trim at `86-91`); `fit_path` final both-sides candidate at `statusline_command.py:822` (no `fits()` recheck).
- **Evidence:** `left_vis/right_vis` are computed as visible cells but consumed by `_take` as codepoint counts, undercounting wide chars; the lone single-codepoint prefix-only trim can't recover. `_middle_ellipsis('😀'*20, 7)` → visible width 11; a sweep (n=2..39, max_w=2..29) found 844 over-budget results, worst overshoot 26 cells. `fit_path`'s final `:822` candidate also overshoots with emoji input.
- **Doc basis:** function contract — result must satisfy `_visible_width(result) ≤ max_w`.
- **Impact:** Emoji/wide-char-laden cwd/branch overflows the path cell even on narrow widths; compounds CWIDTH.
- **Fix:** Make `_take` width-aware (stop once accumulated visible width would exceed the budget; refuse a wide char that would push past it); replace the single-shot trim with a loop popping a codepoint from whichever side overshoots until `_visible_width(result) ≤ max_w` (degrading to `'…'`). Add a `fits()` guard on `fit_path`'s final candidate. Add a regression sweep asserting the contract.

### MODELW — `model` `display_name` is emitted full-length with no truncation in the wide layout → unbounded box overflow
- **Severity:** Medium *(finder C4 R-8: medium, confirmed medium)*
- **Location:** `claude/statusline_command.py:911-940` (`model_right_section`); wide call site `:1632`.
- **Evidence:** `model_right_section` interpolates `{model_name}` with no width budget in **all three** branches (pill `:925-926`, thinking `:937-938`, plain `:939-940`); `right_w = _visible_width(right_text)` (`:942`) only measures. By contrast `model_right_section_compact` truncates to a budget. Reproduced: a 5000-char `display_name` → right section width 5003 (vs 30 for the compact path), fed into `target_w` and rendered into the fixed box.
- **Doc basis:** `model.display_name` is an arbitrary string; the renderer must fit it.
- **Impact:** An over-long host-supplied `display_name` blows out the wide box without bound. Low likelihood, zero defense.
- **Fix (verifier-improved):** Add a `max_width` param to `model_right_section`, update the `:1632` caller to pass a budget, cover the **pill** branch too, and budget the combined `model_name + model_thinking`. Use a visible-width-aware ellipsis (per CTRUNC), not a raw codepoint slice — and retrofit the existing raw `[:budget]` slices in `model_right_section_compact:1006`, `model_section_compact:909`, and `plugins_skills:1036` so the new code doesn't replicate the wide-char bug.

### OS-ARCHIVE — OpenSpec `'/archive/'` filter false-positives on any project under an `'/archive/'` path segment
- **Severity:** Medium *(finder C3 O1: medium, confirmed medium)*
- **Location:** `claude/statusline/openspec.py:28`.
- **Evidence:** `from_cwd` discards a `tasks.md` when `'/archive/' in str(tasks)`, but `str(tasks)` is the **full absolute** path (`rglob` anchored at the absolute `openspec` root). Reproduced: a tree at `/tmp/archive/myproject/openspec/changes/live-change/tasks.md` → the live change is skipped; empty `changes` → empty `openspec_bars` → nothing rendered (`statusline_command.py:1719-1721`), indistinguishable from "openspec not detected."
- **Doc basis:** internal OpenSpec convention (archived changes live under `openspec/changes/archive/`).
- **Impact:** Any repo under a directory literally named `archive` (e.g. `~/archive`) silently loses all OpenSpec progress bars.
- **Fix (verifier-improved):** Match against the path relative to the changes dir, anchored to be precise: `rel = tasks.relative_to(Path(root)); if rel.parts[:2] == ('changes','archive'):`. (The finder's bare `'archive' in tasks.relative_to(root).parts` also fixes the bug but over-excludes a change literally named `archive`.) Separator-agnostic → also fixes OS-ARCHIVE-WIN.

### OS-ARCHIVE-WIN — OpenSpec `'/archive/'` filter is broken on Windows — archived changes leak into the display
- **Severity:** Low *(finder C3 O2: low, confirmed low)*
- **Location:** `claude/statusline/openspec.py:28`.
- **Evidence:** On Windows `str(tasks)` uses backslashes; `'/archive/' in r'C:\proj\openspec\changes\archive\old\tasks.md'` is `False`, so the archive exclusion is a no-op. The existing test (`test_openspec.py:45`) runs on posix and does not catch this.
- **Impact:** On Windows, archived change-sets render stale progress bars alongside live ones. Cosmetic; project primarily targets macOS/Linux.
- **Fix:** Same `relative_to(root).parts` fix as OS-ARCHIVE; parametrize the test across separators.

### GIT-STAGED — Staged-add files (`A`/`AM`/`AD`) are counted as "untracked", mislabeling staged work
- **Severity:** Low *(finder C3 G3: low, confirmed low)*
- **Location:** `claude/statusline/git.py:222-223`.
- **Evidence:** `elif x == 'A' or y == 'A': untracked += 1` — this branch precedes the D/M branches, so `A ` (clean staged add), `AM` (staged-add + worktree-modify), and `AD` (staged-add + worktree-delete) all increment `untracked`; the file renders under the `•` marker (`statusline_command.py:756-757`). Counting is 1-per-entry (totals correct), only the label is wrong; `AM`/`AD` additionally hide real worktree changes.
- **Doc basis:** git porcelain v1 XY semantics.
- **Fix:** Make `??` the only untracked case (it already is structurally) and route index-add `A` to modified/staged: change `:222-223` to `elif x == 'A' or y == 'A': modified += 1`. (Single-bucket-per-entry can't perfectly represent `AD`/`AM`, but this is strictly less misleading.) Or document that `•` means "untracked or newly added." Add a test for `A `/`AM`/`AD`.

### GIT-CACHE-HEAD — Dirty cache validates cwd but not repo root or HEAD ref — stale counts survive a branch/state change within TTL
- **Severity:** Low *(finder C3 G2: low, confirmed low)*
- **Location:** `claude/statusline/git.py:48-51, 83-86`.
- **Evidence:** `from_cwd` reads branch/commit **live** but serves dirty counts from a cache keyed by `session_id`, validated only on `(cwd, ts within GIT_CACHE_TTL=4s)` — not repo root or HEAD. After `git checkout`/`stash`/`reset` the live branch updates immediately while dirty counts lag up to TTL. The committed test `test_from_cwd_branch_live_dirty_cached` asserts exactly this and passes. No wrong-repo risk (a cwd change forces recompute).
- **Doc basis:** docs explicitly recommend ~5s `session_id`-keyed git caching — staleness is the accepted tradeoff.
- **Confidence:** High.
- **Fix:** Acceptable as designed; document the TTL window in the docstring and note `YAS_GIT_CACHE_TTL` tunes it. **Do not** implement the finder's "add HEAD to the cache key" as if it closes the gap — it misses plain edits / `git add` / `restore` / `stash` (HEAD-unmoved dirtiness changes); a shorter TTL bounds *all* staleness sources uniformly.

### KEY-DERIV — `_model_log_key` prefers `model.id` while `rates_for`/`cost_rates` prefer `display_name` — inconsistent key derivation feeding `day_cost`
- **Severity:** Low *(finder C1 D1-3: low, confirmed low)*
- **Location:** `claude/statusline/accounting.py:74-76` (id-first) vs `models.py:74-75` (`session_cost`) and `:141` (`cost_rates`) (display-first).
- **Evidence:** `_model_log_key` returns `(model.id or model.display_name).replace(' ','-')`; the stored key is re-priced via `rates_for(mid)` in `day_cost`. For real catalog models both precedences resolve identically (verified across opus/sonnet/haiku). Latent divergence reproduced on the catalog's own mismatch fixture `Model(id='claude-haiku-3', display_name='Opus 3')`: session prices at `(15,75)`, day at `(0.8,4)` — ~18.75× input-rate gap for the same session.
- **Doc basis:** internal consistency between two pricing entry points.
- **Confidence:** Medium (latent; no current model triggers it).
- **Fix:** Align `_model_log_key` to the same `display_name or id` precedence as `rates_for`, or store the resolved family+version directly (more robust, immune to name-format changes). Note precedence-alignment changes the on-disk log key for new rows (safe — `rates_for` regex-parses any string). Add a guard test asserting `rates_for(_model_log_key(m)) == m.cost_rates` for an id/display mismatch.

### MON-FOOTER — `mon` footer always reports "refreshed 0s ago" — `refresh_age_seconds` hardcoded to 0
- **Severity:** Info *(finder C6 D-9: info, confirmed info)*
- **Location:** `claude/mon.py:77 & 106` (both call sites pass literal `0`); `format_footer` renders `f'refreshed {refresh_age_seconds}s ago'` (`mon/layout.py:79`).
- **Evidence:** The main loop tracks no last-redraw wall-clock; per-session ages are correctly rendered elsewhere (`mon.py:89-90`).
- **Impact:** Cosmetic dead element; no data corruption.
- **Fix:** Touch **both** call sites (the finder cited only `:106`). Prefer dropping the "refreshed Ns ago" element (since on a fixed-cadence loop it would always show ~`refresh_seconds`), or display seconds since most-recent session activity if a freshness indicator is wanted.

---

## 4. Security and adversarial-input robustness

### SEC-1 — Terminal escape (ANSI/OSC) injection: attacker-controlled strings rendered raw to stdout with no control-char sanitization
*Merged: security A1-1; render-robustness R-9 (the same defect from the cwd/branch/model-only angle).*
- **Severity:** High *(finder C5 A1-1: high, confirmed high; the narrower R-9 facet was low)*
- **Location:** final write `claude/statusline_command.py:1828`; sinks at `:772/780/816/818` (git.branch), `:925/938/940` (model_name), `:1041` (skills + plugin names), `:1062` (subagent tool name/input), `:1096/1098` (subagent agentType/description), `:1203/1206/1215` (task subject/active_form); `textutil._ANSI_RE :13` matches **only** SGR.
- **Evidence:** `render(...)` is written verbatim with no control-char filter. `_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')` strips only SGR color codes — not OSC (`\x1b]…`), C1, or non-`m` CSI/DCS. **Empirically reproduced** for two sinks live: a `model.display_name` carrying `\x1b]0;…\x07` and `\x1b]52;c;…\x07` appeared raw in stdout; a crafted `/tmp/.git/HEAD` with embedded OSC-0/OSC-52 likewise. `json.loads`-backed sinks (tasks `transcript.py:365`, subagent meta `:91-93`, subagent tool input `:147/:168`) decode JSON `\u001b` into real ESC bytes and are exploitable; the `Skill` field is incidentally protected because `_SKILL_PAT` (`:269`) matches the **raw** JSONL line before any `json.loads`.
- **Doc basis:** Official doc: statusline output supports "ANSI colors, OSC 8 hyperlinks" — raw escapes pass through; the renderer is responsible for not emitting *untrusted* escapes.
- **Impact:** OSC-52 clipboard write (silently overwrite the user's clipboard with attacker-chosen content), OSC-0/2 window/tab-title spoof — zero user interaction, fired merely by rendering. Delivery: a malicious repo committing `.claude/settings.json`, a crafted `.git/HEAD`, or a crafted transcript/subagent file. Not critical (requires a hostile *local* artifact, not a network vector; OSC-52 is terminal-opt-in). The prior **AUDIT.md §4.8 "LOW risk; genuinely clean" verdict is wrong** for untrusted repo/transcript content.
- **Fix (verifier-improved):** Add a sanitization pass **only at the point of capture of untrusted fields** (not on the final rendered lines — that would strip the renderer's own legitimate SGR). Strip C0/C1/DEL and any ESC-introduced sequence; the proposed class `re.sub(r'[\x00-\x08\x0b-\x1f\x7f-\x9f]','',s)` is adequate for control bytes (ESC `0x1b` and BEL `0x07` are within it). Best applied centrally in `models.py _as_str` (covers `display_name`, `id`, effort, output_style), `git.py _read_head` (branch), and the transcript capture sites for task/skill/subagent fields. Also sanitize the `Skill` capture defensively (currently inert). Pair with SEC-3 (broaden `_visible_width`'s escape handling for trusted OSC-8 output).

### SEC-2 — Trust-boundary violation: `Workspace.plugins` reads `project_dir/.claude/settings.json` from a (possibly cloned/attacker-controlled) repo and renders its keys
- **Severity:** High *(finder C5 A1-2: high, confirmed high)*
- **Location:** `claude/statusline/models.py:213-231` (`.plugins`, esp. `:218` and `:226-230`); rendered at `statusline_command.py:1643/1017/1041`.
- **Evidence:** `.plugins` appends `Path(self.project_dir)/'.claude'/'settings.json'` and `json.loads` it, surfacing every `enabledPlugins` key with value `True`. `project_dir` comes from host stdin and for a cloned repo is attacker-controlled. **Reproduced end-to-end:** a repo `settings.json` with key `evilplugin\x1b]0;PLUGPWN\x07@marketplace` → `plugins_skills` emits the raw OSC-0 (`statusline_command.py:1041`). So this is both an unexpected trust-boundary read **and** an escape-injection sink (chains with SEC-1).
- **Doc basis:** `statusLine` runs only after workspace-trust accepted; but the renderer still reads attacker-authored in-repo `settings.json` once trusted. (The prior audit's overall "Security: LOW risk; genuinely clean" verdict, AUDIT.md §4.8, is contradicted.)
- **Impact:** Opening any trusted-but-untrusted-origin repo causes the statusline to parse and display repo-author-chosen content and execute embedded terminal escapes.
- **Fix (verifier-improved):** Prefer **removing** the `project_dir/.claude/settings.json` candidate (`models.py:217-218`) and reading only `config.CLAUDE_DIR/'settings.json'` — rendering a cloned repo's `enabledPlugins` has near-zero value and is the entire attack surface (update `test_plugins_merged_from_home_and_project`). If repo-local display must stay, gate behind explicit opt-in **and** apply the SEC-1 sanitization. Per-field sanitization at `plugins_skills` alone is insufficient (other untrusted strings reach stdout through the same path) — the robust mitigation is the centralized capture-time strip from SEC-1.

### MON-1 — `mon.py` ignores `CLAUDE_CONFIG_DIR` — finds zero sessions for any custom-config-dir user
- **Severity:** High *(finder C6 D-1: high, confirmed high)*
- **Location:** `claude/mon/discovery.py:21,43`.
- **Evidence:** `find_active_jsonls()` defaults `projects_root=Path.home()/'.claude'/'projects'` (`:21`) and `index_payloads_by_session()` defaults `payloads_root=Path.home()/'.claude'/'statusline-output'` (`:43`); `discover()` (`:70-95`) never overrides. Grep confirms no `CLAUDE_CONFIG_DIR` reads in `mon`. The renderer writes payloads to `config.CLAUDE_DIR/'statusline-output'` (`statusline_command.py:1818`), which honors `CLAUDE_CONFIG_DIR` (`claude/statusline/config.py:16`).
- **Doc basis:** `CLAUDE_CONFIG_DIR` is the documented base dir (README.md:60); renderer + uninstall honor it.
- **Impact:** Any `CLAUDE_CONFIG_DIR` user runs the renderer writing to `<custom>/statusline-output` but `make mon/run` reads `~/.claude/*` — the TUI shows "(no active sessions)" permanently. Same **O4** class the prior audit flagged for `init`, here uncovered in `mon`.
- **Fix (verifier-corrected — important):** Resolve from **`config.CLAUDE_DIR` (attribute lookup), not `os.environ`** — the test suite patches `config.CLAUDE_DIR` via `monkeypatch.setattr` (conftest.py:56-57), so an env-direct read would escape the sandbox to real `~/.claude` during tests. And resolve at **call time inside `discover()`**, not via default-arg expressions (Python evaluates defaults once at import, re-freezing the value): compute `base = config.CLAUDE_DIR`, then call `find_active_jsonls(..., base/'projects')` and `index_payloads_by_session(base/'statusline-output')`. Add a regression test setting `config.CLAUDE_DIR` to a tmp dir. Cross-refs prior **O4**.

### R-CONTROL-MEM — No size cap on stdin or transcript reads; newline-free transcript defeats incremental tailing
*Merged: security A1-5; transcript T1-4 (huge-file/huge-line full-scan into RAM).*
- **Severity:** Low *(finder C5 A1-5: low, confirmed low; T1-4: low, confirmed low)*
- **Location:** `statusline_command.py:1809` (`sys.stdin.read()`); `transcript.py:307` (`scan_full` `fh.read()`), `:531` (`_scan_with_state` `fh.read()`), `:319` (`consumed = data.rfind(b'\n')+1`); subagent `:124-175`.
- **Evidence:** All reads materialize the file/stream with no size limit. For a newline-free file, `rfind` returns -1 ⇒ `consumed=0` ⇒ the persisted offset never advances ⇒ every render re-reads from offset 0 (incremental optimization fully defeated). A 219MB transcript full scan peaked at ~1015MB RSS (~4.6× file size, because `data[:consumed]` + `.split` + decoded strs). A 5MB single line handled in ~7ms (no crash).
- **Doc basis:** docs recommend "cache expensive operations"; in-flight render is cancelled on the next update (bounds but doesn't eliminate per-render cost). Mitigating: `transcript_path` is host-supplied under normal operation; worst case is CPU/RAM spikes, not RCE.
- **Fix (verifier-improved):** Cap the full scan (stat-and-bail above a threshold, or read only the trailing N MB starting at a clean newline — documented as graceful degradation since it undercounts cumulative usage). For the incremental path, when `consumed==0` **and** `(st_size - start) > CAP`, set `new_offset = st_size` (treat the giant unterminated fragment as malformed and advance) — **not** the finder's blind offset-advance, which could drop a legitimately large line awaiting its newline. Add a per-line length guard (the huge-single-line subcase is unaffected by chunking). Use a single shared chunk-reader for both scan paths so byte-for-byte equivalence is structural.

### R-SYMLINK — `transcript_path` symlink is followed and its target read fully into memory (arbitrary-file read into RAM)
- **Severity:** Low *(finder C5 A1-6: low, confirmed low)*
- **Location:** `claude/statusline/transcript.py:303` (`p.is_file()` follows symlinks), `:306-307` (`p.open('rb').read()`); `_incremental_enabled :485` correctly confines only the state-**write** path.
- **Evidence:** Reproduced: `link_passwd.jsonl -> /etc/passwd` is read without error (`input_tokens=0`). The production entry `_scan_transcript` (`:538`) falls through to `scan_full` (`:563`) for any out-of-tree path. The narrow parse means file contents are not echoed unless they happen to be valid Claude-transcript JSONL (no practical exfiltration). Char/block devices are already blocked (`is_file()` is False for `/dev/zero`).
- **Doc basis:** threat model — `transcript_path` may be a symlinked/crafted path. Mitigating: `transcript_path` is host-supplied, not derived from untrusted repo content; the trust gate must be accepted.
- **Impact:** Arbitrary-*regular*-file-read-into-RAM (DoS amplifier with R-CONTROL-MEM) and a latent info-leak if parse patterns broaden.
- **Fix (verifier-improved):** Reject symlinks whose resolved target escapes `CLAUDE_DIR/projects` (more surgical than confining all reads), **and** pair with the R-CONTROL-MEM size cap — the cap is the higher-value half given there's no exfiltration channel. (Tests already place transcripts under `CLAUDE_DIR/projects`, so confinement won't break them.)

### R-ESCAPE-LEAK — `helper()` leaks raw exception class+message into the rendered statusline content
- **Severity:** Low *(finder C4 R-10: low, confirmed low)*
- **Location:** `claude/statusline_command.py:1475-1476`.
- **Evidence:** The five-hour rate-limit `helper()` catches `except Exception as e: return f'{e.__class__.__name__}, {str(e)}'` — the only place that converts an error into visible content; its siblings (`model_section_compact :871-872`, `model_right_section_compact :983-984`) `pass`. The error string flows into rendered content (via `:944`) **and** into `_visible_width`. Reachable from stdin: `resets_at` comes via `_as_int` (no magnitude clamp), so a large finite integer (e.g. `10**19`) is truthy, bypasses the guard, and crashes `datetime.fromtimestamp()` into the catch-all.
- **Doc basis:** loud-failure-vs-silent policy — this is neither; it renders the error as data.
- **Impact:** Mild info leak + width-garbling on an unforeseen error.
- **Confidence:** Medium.
- **Fix:** Fail closed like the siblings — `except Exception: return <plain coloured pct cell> if five_hour.used_percentage else '∞'`. Optionally range-clamp `resets_at` in `RateBucket.from_dict` (`:192`). Add a regression test feeding `resets_at=10**19` (the except branch is currently uncovered per `test_helper.py`).

### CI-PIN — CI uses moving tag `actions/checkout@v6` (not SHA-pinned) — supply-chain pinning gap
- **Severity:** Low *(finder C6 D-7: low, confirmed low)*
- **Location:** `.github/workflows/ci.yml:13,31,49`.
- **Evidence:** All three jobs use `actions/checkout@v6` (a repointable major tag), while the only third-party action `astral-sh/setup-uv` is full-SHA-pinned with a version comment (`:16/34/52`). Workflow is `on: [push]` with no secrets/deploy steps.
- **Impact:** A repointed `v6` tag would run arbitrary code in CI — low risk (first-party action, no secrets) but inconsistent hygiene. Matches prior **S6**.
- **Fix:** SHA-pin `checkout` with a `# v6.x.x` comment (lines 13/31/49), matching the `setup-uv` style; optionally add Dependabot for `github-actions`.

---

## 5. Performance

### PERF-TMUX — tmux pane-width probe is an unbounded subprocess on the hot path AND can return the wrong width
- **Severity:** Medium *(finder D3 DW-2: high → corrected **medium**)*
- **Location:** `claude/statusline_command.py:98-104`.
- **Evidence:** The first width source spawns `subprocess.run(['tmux','display-message','-p','-t', TMUX_PANE, "'#{pane_width}'"])` with **no `timeout=`** (cf. `git.py:204` which uses `timeout=2`), on every render (debounced 300ms; `refreshInterval` ~1Hz). (a) PERF/hang: an unbounded fork+exec before the zero-cost `COLUMNS` read; a wedged tmux server blocks unbounded, and per the docs an in-flight render is **cancelled** on the next update — so a slow probe can mean the line never repaints. (b) CORRECTNESS: `pane_width` ≠ Claude Code's allocated statusline width (padding reserves space). The fixed `raw_tw-6` at `:1826` then renders too wide for tmux users on v2.1.153+. The argv carries a shell-quoting leftover `"'#{pane_width}'"` (stripped via `.replace("'","")`).
- **Doc basis:** "If a new update fires while the script is still running, the in-flight execution is cancelled"; the COLUMNS-sets-real-dimensions contract.
- **Why downgraded:** in the common case the cost is one lightweight tmux query plus an occasional width overshoot; the unbounded-timeout hang requires a degenerate/wedged server (uncommon). Non-tmux users skip the probe entirely (guarded by `KeyError` on `TMUX_PANE`).
- **Fix (verifier-improved):** Reorder `COLUMNS` first overall (per WIDTH-1). Add `timeout=0.2` **and** add `subprocess.TimeoutExpired` to the catch tuple (it is a `SubprocessError`, **not** an `OSError` — the existing `except` would not catch it). Preferred: retire the tmux probe entirely on v2.1.153+ (COLUMNS supersedes it). Fix the argv to `'#{pane_width}'` (no embedded quotes → `.replace` becomes unnecessary). Re-examine the `raw_tw-6` fudge once standardized on COLUMNS to avoid double-counting reserved space. Cross-refs prior **P4**.

### PERF-STATE — Persisted seen-id set and full task/skill state grow unbounded with session length; rewritten on each advancing render
- **Severity:** Low *(finder C2 T1-3: low, confirmed low)*
- **Location:** `claude/statusline/transcript.py:425-438` (`to_state`), `:513-520` (`_save_scan_state`), `:287/357` (`usage_seen`).
- **Evidence:** `to_state()` serializes the complete `usage_seen` id set + full task list; `_save_scan_state` rewrites the entire JSON each time the offset advances (gated at `:533` on `new_offset != start` — **not** every render, as the title loosely implies). Growth is O(unique messages). Real ~24-char ids → ~56KB state at 2000 ids (the finder's 26KB *understated* it). Persisting the full seen set is required for cross-boundary dedup correctness (prior **A2**).
- **Impact:** Linear state-file growth + per-advance rewrite for very long sessions; bounded by message count, no correctness impact.
- **Confidence:** High.
- **Fix:** Acceptable as-is for typical sessions; at minimum document that state size is O(unique assistant messages). If compaction is wanted, use fixed-width hashing (≥64 bits) of ids — **never** a Bloom-style structure (false positives would silently skip legitimate usage rows, undercounting tokens/cost) and never drop/cap old ids (re-introduces the A2 miscount).

---

## 6. Peripherals / operational robustness

### ROB-1 — Non-object / invalid stdin JSON crashes `main()` before any rendering
*Merged: render-robustness R-1 (non-object) + R-2 (empty/non-JSON); security A1-4 (same crash).*
- **Severity:** High *(R-1: high, confirmed high; R-2: high → corrected **medium**; A1-4: low, confirmed low — taken together the entrypoint crash is **high**)*
- **Location:** `claude/statusline_command.py:1809` (`json.loads(sys.stdin.read())`), `:1817` (`info.get('session_id')`); `SessionInfo.from_dict` assumes a dict (`models.py:311,315`).
- **Evidence:** No `isinstance(dict)` guard and no `try/except`. **Verified through the real entrypoint:** `[]`, `123`, `"s"`, `null`, `true`, `NaN` all parse successfully into non-dicts and crash at `:1817` with `AttributeError: '<type>' object has no attribute 'get'` (rc=1); empty stdin and `not json` crash at `:1809` with `JSONDecodeError` (rc=1); `{}` → rc=0. The install wiring (`skills/init/SKILL.md:100-109`) sets the command with no `|| echo`/`2>/dev/null` fallback. The crash blanks the status line; the traceback goes to discarded stderr.
- **Doc basis:** stdin is a JSON object; a crashed `statusLine` command blanks the line. The 300ms-debounce + in-flight-cancellation behavior makes a partially-delivered/empty stdin a plausible real-world event.
- **Why R-2 facet is medium / overall high:** the empty/malformed case is cosmetic and self-recovers next tick (`refreshInterval:1`); but the **non-object** case (R-1) is a guaranteed full blank-out on trivially-formed valid JSON on the primary input path, with no graceful degradation — high.
- **Fix:** At the top of `main()`: `try: info = json.loads(sys.stdin.read()) except (ValueError, OSError): info = {}` then `if not isinstance(info, dict): info = {}` (the `isinstance` guard is required and **not** redundant — `NaN/Infinity/true/123/[]/"s"/null` all parse to non-dicts and bypass the `except`). When falling back to `{}`, also skip the per-session payload write at `:1818` so a crash-recovery render doesn't clobber the last good payload (the `mon` observer indexes it). Add a regression test for non-object/empty stdin through `main()`. Harden `SessionInfo.from_dict`'s `d` as defense-in-depth. Cross-refs prior render-robustness.

### NAN — `NaN`/`Infinity` in ANY integer-typed field crashes `_as_int` via `int(nan)`/`int(inf)`
- **Severity:** Medium *(finder C4 R-3: high → corrected **medium**)*
- **Location:** `claude/statusline/models.py:104-109` (`_as_int`, crash at `:108`); reached from `ContextWindow.from_dict :269-271`, `CurrentUsage :177-180`, `Cost :246-249`, `RateBucket :192`.
- **Evidence:** `json.loads` accepts `NaN`/`Infinity`/`-Infinity` by default. `_as_int` does `if isinstance(v, float): return int(v)` with no finite guard — `int(nan)` raises `ValueError`, `int(inf)` raises `OverflowError`. **Verified through `main()`:** NaN/Inf in `total_input_tokens`, `context_window_size`, `current_usage.input_tokens`, `cost.total_duration_ms`, `cost.total_lines_added`, `rate_limits.five_hour.resets_at` all exit rc=1. (`_as_float` preserves NaN/Inf, but float consumers don't crash — verified rc=0 for `used_percentage`, `total_cost_usd`.)
- **Doc basis:** token/cost/percentage fields are numbers (several nullable); `json.loads` NaN-acceptance is a stdlib default.
- **Why downgraded:** triggering requires a non-standard JSON token in an integer field; the authoritative producer (Claude Code) never emits these; realistic triggers are a host bug or a non-conforming proxy. Impact is a transient blank line, self-healing.
- **Fix:** Guard `_as_int`: `import math; if isinstance(v, float): return default if not math.isfinite(v) else int(v)` (covers all current + future call sites). Optionally harden `_as_float` for consistency. Strongest belt-and-suspenders: pass `parse_constant=` to `json.loads` at `:1809` to neutralize the class at the source. Add NaN/Inf test coverage (currently none).

### R-ENAMETOOLONG — Attacker-controlled cwd with an over-length path component crashes via uncaught `OSError(ENAMETOOLONG)` in git resolution
- **Severity:** Medium *(finder C4 R-7: medium, confirmed medium)*
- **Location:** `claude/statusline/git.py:99` (`dotgit.exists()` in `_find_repo`); reached from `build_medium :1556` and `build_wide :1631`.
- **Evidence:** `_find_repo` walks parents calling `dotgit.exists()` with no `try/except` — the lone unguarded probe (`_resolve_gitdir :115`, `_read_head :137`, `_read_commit :178/191` all wrap reads). On this macOS/py3.12.2 build `Path('/'+'a'*300+'/.git').exists()` raises `OSError errno 63 (ENAMETOOLONG)` rather than returning False (Python only suppresses a specific errno allowlist; ENAMETOOLONG is not in it). `build_narrow` (<55 cols) doesn't call git, so the crash is **width-dependent**.
- **Doc basis:** cwd is a path string; the renderer must not crash on it. Loud-failure policy prefers a degraded render over a blank line.
- **Impact:** A cwd with a segment over `NAME_MAX` blanks the line at medium/wide widths; cwd is host-supplied but unvalidated by the renderer.
- **Fix (verifier-improved):** Wrap line 99: `try: is_repo = dotgit.exists() except OSError: is_repo = False`. Better, harden the whole walk and the sibling `is_file()` probes (`_read_head :133`, `_read_commit :167/175/181`) which share the hazard. Strongest: wrap `GitInfo.from_cwd` (or the `build_medium/wide` git call) in a `try/except OSError` yielding an empty `GitInfo()` so a future unguarded probe can't reintroduce the blank-line crash.

### A1-3 — `_visible_width`/`_middle_ellipsis` don't account for OSC or non-SGR escapes → layout corruption and broken truncation budget on injected content
- **Severity:** Medium *(finder C5 A1-3: medium, confirmed medium)*
- **Location:** `claude/statusline/textutil.py:13` (`_ANSI_RE`), `:41-43` (`_visible_width`), `:46-91` (`_middle_ellipsis`); raw slices at `statusline_command.py:1036/1061/1092/1215`.
- **Evidence:** `_ANSI_RE` matches only SGR, so `_visible_width('x\x1b]52;c;AAAA\x07y')` returns 14 (should be 2) — every OSC byte counts as a visible column. The four raw `text[:N]` truncations on transcript-derived content (subagent description, tool-arg value, task subject/active_form — read verbatim with no sanitization) can slice mid-escape, leaving a dangling partial sequence (reproduced: `'Refactor module \x1b]8;;file:///…'`). (The `_middle_ellipsis` path/git callers operate on cwd/branch, which normally lack ESC bytes, so the genuine exposure is the four transcript-content slice sites.)
- **Doc basis:** OSC-8 hyperlinks are supported output, so OSC content is expected and must be width-accounted; otherwise an injection-amplifier for SEC-1.
- **Impact:** Misaligned borders / overflow when a field carries non-SGR escapes; a dangling OSC introducer at a row boundary can swallow following bytes.
- **Fix (verifier-improved — invert the priority):** Broadening `_ANSI_RE` for width alone would make matters *worse* (correct width math packs more escape-laden content per row while the raw slices still cut mid-escape). The robust fix is **upstream sanitization** (the SEC-1 capture-time strip) so only plain text reaches the width/truncation helpers; then width math is correct by construction and slicing is safe. Use a **dedicated strip-only regex** for width (CSI any-final-byte, OSC `\x1b\].*?(\x07|\x1b\\)`, lone C0) — do **not** widen `_ANSI_RE` itself, since `_middle_ellipsis` re-emits matched tokens to preserve color across the cut. Replace the four raw `text[:N]` slices with a visible-width-aware truncator.

### INSTALL-CLOBBER — `/yas:init` silently clobbers a user's existing custom (non-yas) `statusLine`
- **Severity:** Medium *(finder C6 D-2: medium, confirmed medium)*
- **Location:** `skills/init/SKILL.md:60-110`.
- **Evidence:** Step 2 only checks whether the current `statusLine.command` *contains* the yas `$SCRIPT` (`:62-64`) and skips if so. A *different* command (a user's own or third-party statusline) is not detected; Step 4 then unconditionally runs `jq '.statusLine = {…}'` (`:100-102`), wholesale-replacing the block. Uninstall, by contrast, sets `CFG_STATE=foreign` and refuses to touch a foreign `statusLine` (`uninstall/SKILL.md:40-50`). A timestamped backup is taken first (`:95-97`), but the replacement is silent.
- **Doc basis:** the `statusLine` block is user-owned config; uninstall's foreign-guard sets the project's own expectation that a custom statusLine is preserved.
- **Impact:** Running `/yas:init` overwrites a user's custom statusLine without asking (recoverable from `settings.json.bak-yas-<ts>`).
- **Fix:** In Step 2, after the already-current check, detect a present-but-foreign command (non-empty, not containing `statusline_command.py` — use uninstall's exact `grep -q` signature for consistency) and **prompt/refuse**, or at minimum print a loud "replacing your existing custom statusLine (backed up to …)" warning *before* the destructive Step 4 write, referencing the actual backup path.

### INSTALL-RESTORE — `/yas:init` Step 5 "restore backup on invalid JSON" is prose-only — no actual restore code
- **Severity:** Low *(finder C6 D-6: low, confirmed low)*
- **Location:** `skills/init/SKILL.md:112-124`.
- **Evidence:** Step 5 has only `jq empty ~/.claude/settings.json` + prose "If invalid: restore backup, report error, stop." — no `cp` restore. Uninstall Step 2 has explicit restore code (`uninstall/SKILL.md:72`). Step 4 already largely precludes the failure (atomic `mktemp+mv`, non-empty `_result` check at `:103`, and `jq` exit-0 implies valid JSON), so reaching an invalid-JSON state at Step 5 is essentially impossible.
- **Confidence:** Medium.
- **Fix (verifier-corrected):** Each `## Step` runs as a **separate** Bash invocation, so `${BAK_TS}` set in Step 4 is unset in Step 5 — the finder's standalone command would restore nothing. Fold validation+restore **into Step 4's block** (where `BAK_TS` is in scope), guarded on the file-existed case (a freshly-created `settings.json` has no backup). Or simply drop the unreachable prose claim. Match uninstall's validate-then-restore structure.

### ALACRITTY — `alacritty.py`: broad `pgrep -f claude` + SIGWINCH broadcast to every match; writes `$HOME/.claude/terminal-width` ignoring `CLAUDE_CONFIG_DIR`
*Merged: security A1-7 + peripherals D-4 (same defect); related to the obsolete-width-file finding WIDTH-3.*
- **Severity:** Low *(A1-7: low, confirmed low; D-4: low, confirmed low)*
- **Location:** `claude/statusline/alacritty.py:26` (write), `:29` (pgrep), `:31-33` (`os.kill(pid, SIGWINCH)` per match).
- **Evidence:** Writes `f'{os.environ["HOME"]}/.claude/terminal-width'` directly, ignoring `CLAUDE_CONFIG_DIR` (which the renderer honors at `statusline_command.py:106` via `config.CLAUDE_DIR`). `pgrep -f claude` matched **22** processes live (only 1 the real TUI — the rest tmux sessions, monitoring scripts, opencode); SIGWINCH is sent to all. The `open()` is **outside** the `try/except`, so an unset `HOME` crashes the whole helper at line 26. The file is never `import`ed by the renderer pipeline (HANDOFF.md:93). Matches prior **A3**.
- **Doc basis:** README.md:60 — `CLAUDE_CONFIG_DIR` is the base for the width file; this helper bypasses it.
- **Impact:** Indiscriminate (benign) SIGWINCH to unrelated processes; for `CLAUDE_CONFIG_DIR` users the width hint is written where the renderer never reads it (silently non-functional). Narrow real-world blast radius — opt-in dev tooling.
- **Fix:** Cleanest: **exclude `alacritty.py` from the distributed plugin** (it currently ships because `marketplace.json` source is `./`) or mark it unsupported dev tooling — it is arguably obsolete now that Claude Code sets `COLUMNS` itself. If kept: use `config.CLAUDE_DIR/'terminal-width'` (the security **and** functional fix), narrow the pgrep target (signal only the recorded parent Claude PID, or anchor on the resolved binary path; add a `os.getuid()` ownership check), and guard `HOME` with `os.environ.get`.

### WIDTH-3 — The `terminal-width` file source and `alacritty.py` SIGWINCH helper are obsolete pre-`COLUMNS` workarounds (the file overrides authoritative `COLUMNS`)
- **Severity:** Low *(finder D3 DW-3: medium → corrected **low**)*
- **Location:** `claude/statusline_command.py:105-110` (file read, ranked **above** `COLUMNS` at `:111-116`); `claude/statusline/alacritty.py` (whole file).
- **Evidence:** The width-file source reads `config.CLAUDE_DIR/'terminal-width'` and sits **ahead** of `COLUMNS`, so a present file overrides the contractually-correct value. Per v2.1.153+, Claude Code sets `COLUMNS`/`LINES` per invocation, superseding any externally-pushed width cache.
- **Doc basis:** `COLUMNS`/`LINES` set to real dimensions per invocation, superseding cached width.
- **Why downgraded:** the harmful override only manifests while the (undocumented, unreferenced) `alacritty.py` is actively run; for all other users the file never exists and `terminal_width()` falls through correctly. Already tracked as low (**A3/P4**).
- **Correction to the finder:** the recommendation said the file source should "use `config.CLAUDE_DIR`, not `$HOME`" — the **reader** already uses `config.CLAUDE_DIR` (`:106`) and honors `CLAUDE_CONFIG_DIR`; the `$HOME` bug is on the **writer** side (`alacritty.py:26`, see ALACRITTY).
- **Fix:** Drop the terminal-width file source from `terminal_width()` (remove `:105-110`) so `COLUMNS` is consulted right after the tmux probe; if a file fallback is kept for pre-v2.1.153, it must rank **below** `COLUMNS`. Update `README.md:60,63,75-82` and uninstall references.

### WIDTH-4 — `COLUMNS` is checked redundantly: `shutil.get_terminal_size` already reads `COLUMNS` internally
- **Severity:** Low *(finder D3 DW-4: low, confirmed low)*
- **Location:** `claude/statusline_command.py:112-119`.
- **Evidence:** Source #3 reads `COLUMNS` directly (`:112`); source #4 `shutil.get_terminal_size(fallback=(0,0))` (`:117`) reads `os.environ['COLUMNS']` as its own first step (verified from CPython 3.12 source + empirically: `COLUMNS=123` → 123; unset → 0; LINES-only ioctl does not overwrite a positive columns). So #4 only ever contributes the ioctl path; the explicit #3 is harmless but signals the precedence wasn't reasoned about as a unit.
- **Impact:** No behavioral bug; duplication obscures intent (a future reorder may not realize #4 re-reads `COLUMNS`).
- **Confidence:** High.
- **Fix:** After making `COLUMNS` first (WIDTH-1), keep exactly one intentional `COLUMNS` source and use `os.get_terminal_size(sys.__stdout__.fileno())` (wrapped in `try/except`) for the ioctl fallback so no source silently re-reads `COLUMNS`. Add a comment that `shutil` reads `COLUMNS`/`LINES` itself.

### WIDTH-5 — `LINES` is never read; the renderer emits a variable number of lines with no vertical budget
- **Severity:** Low *(finder D3 DW-5: medium → corrected **low**)*
- **Location:** `claude/statusline_command.py` (no `LINES` read); render dispatch `:1767-1778`; `main :1820-1828`.
- **Evidence:** `terminal_width()` returns only `.columns`; `build_*` emit a variable row count joined with `'\n'` and written verbatim. `LINES` (set by Claude Code v2.1.153+) is ignored.
- **Doc basis:** Claude Code sets `LINES` to the real dimensions.
- **Confidence:** Medium / **partially-confirmed** — the *literal* claim (LINES unread) is true, but the finder's load-bearing premise (that Claude Code allocates N statusline rows and truncates/scrolls overflow) is **unsupported**: the schema says `LINES` is the real terminal height and explicitly supports multi-line output ("multiple lines, one per echo"). This is a deliberately multi-line bordered-box renderer (per README).
- **Fix (verifier-corrected — do not overreach):** Surfacing `terminal_height()` reading `int(os.environ.get('LINES','0'))` is harmless. But do **not** wire a priority-ordered row-shedding scheme against `LINES`: there's no evidence Claude Code enforces a statusline height budget, shedding against full terminal height would essentially never trigger, and shedding against a wrong allocation assumption could hide expected sections. Before any shedding logic, empirically confirm what `LINES` actually holds in the statusline context and whether multi-line output is ever truncated.

### MON-ZIP — `mon tick()` assumes `rendered_boxes` is parallel to `active`; latent misalignment if any `render()` returns empty, plus value-equality box matching
- **Severity:** Low *(finder C6 D-5: low, confirmed low)*
- **Location:** `claude/mon.py:86-101`.
- **Evidence:** `rendered_boxes` is built only for truthy boxes (`:88`); `:101` does `zip(active, rendered_boxes)` (positional) and selects via `if box in visible_boxes` (string membership). Today `width >= MIN_WIDTH` (`:84`) so `render()` never returns `''` and the lists stay aligned; `render_layout` always emits ≥2 border lines otherwise. If a box is ever empty, `zip` silently pairs the wrong session with each box, corrupting the header 5h/7d% and day-cost aggregation. (The value-equality path is near-unreachable in practice because each box embeds the unique `session_id` UUID in `border_top :503`.)
- **Confidence:** Medium.
- **Fix:** Carry `(ActiveSession, box)` together in one list, appending only truthy boxes; pass `[b for _,b in rendered]` to `clip_to_height`; derive `visible_sessions = [s for (s,_) in rendered[:len(visible_boxes)]]` (valid because `clip_to_height` returns a contiguous front prefix). Removes both the zip-parallelism assumption and the string-equality match. Add a `tick()` unit test (currently untested).

### DOC-REFRESH — README git-clone install snippet omits `refreshInterval` — clock/burn-rate/rate-limit countdown go stale while idle
- **Severity:** Low *(finder C6 D-3: medium → corrected **low**)*
- **Location:** `README.md:129-135` vs `skills/init/SKILL.md:101`.
- **Evidence:** The init skill writes `"refreshInterval":1`; the README git-clone JSON writes only `{"async":true,"command":…,"type":"command"}`. The renderer recomputes time-derived segments from wall-clock each render: rate-limit countdown `resets_at - clock.now()` (`statusline_command.py:864/969/1462`), daily key `clock.now().strftime` (`:1618`), burndown `time.time()` (`:67`), token-rate (`accounting.py:160/191/234`). `async` is **not** an inter-event re-run mechanism (and is undocumented — see DOC-ASYNC).
- **Doc basis:** `refreshInterval` (seconds, min 1) is "recommended for time-based data (clocks, burn rate) and when background subagents change git state while idle."
- **Why downgraded:** doc-only inconsistency with cosmetic effect — values are correct at each event and merely fail to tick down while idle on the git-clone path; affected rate-limit/burndown segments are additionally Pro/Max-only.
- **Fix:** Add `"refreshInterval": 1` to the README block so both install paths match. Consider dropping `"async":true` from both (see DOC-ASYNC).

### DOC-ASYNC — `statusLine async: true` is written by both init and README but is not in the official `statusLine` settings schema
- **Severity:** Info *(finder C6 D-8: info, confirmed info)*
- **Location:** `skills/init/SKILL.md:101`, `README.md:131`.
- **Evidence:** Both include an `async` key; the authoritative `statusLine` schema lists only `type, command, padding, refreshInterval, hideVimModeIndicator, subagentStatusLine`. The execution model is synchronous (300ms debounce + cancellation). Claude Code ignores unknown keys (no-op at worst). Matches a prior flagged-but-unverified note.
- **Confidence:** Medium (relies on the supplied schema; the live version cannot be queried here — which is why prior **§4.7 / S5** kept flagging it).
- **Fix:** Drop `async` from both snippets to avoid implying non-existent behavior. Secondary observation (out of scope but confirmed): `permissions-allow.json` (the 12-utility allowlist) is referenced only by audit docs, never by `plugin.json`/`marketplace.json`/`hooks.json`.

---

## Transcript-scanner correctness (cross-cutting; placed in §3 by severity but grouped here for provenance)

### TRN-1 — In-place `/compact` (same inode, size ≥ old offset) is NOT detected → stale token/task/skill stats
- **Severity:** High *(finder C2 T1-1: high, confirmed high)*
- **Location:** `claude/statusline/transcript.py:495-510` (`_resume_point`), `:513-520` (`_save_scan_state`).
- **Evidence:** The persisted state stores only `{v, path, inode, offset, scan}` — no size/mtime/prefix fingerprint. `_resume_point` validates `v`, `path`, `inode==st_ino`, `0≤offset≤st_size` — it does **not** verify the prefix `[0:offset)` is unchanged. **Reproduced cleanly:** a transcript scanned to offset 185 (input 60), then rewritten in place (same inode, truncate+write) to a `/compact` summary (input 1000, cache_read 500) + tail (input 5); inode unchanged, new size ≥ old offset, so every guard passes; the scanner resumes at byte 185, reads only the tail, folds 5 onto the stale accumulator → **reports input 65 and cache_read 0** vs the correct full-scan **input 1005, cache_read 500**. `_SCAN_CACHE` is process-local (cleared each render), so the disk resume is the only cross-render carrier and it ignores the prefix.
- **Doc basis:** the module docstring's "always-correct fallback … never wrong stats" guarantee; design intent "reset on inode/size/path mismatch."
- **Impact:** After `/compact` (or any in-place rewrite keeping the inode and growing ≥ prior offset), context-window %, session/day cost inputs, task list, and loaded skills are wrong until the inode changes or the file shrinks below the offset — typically a large undercount.
- **Residual uncertainty (flagged by the finder):** whether real Claude Code `/compact` rewrites in place (same inode) vs creates a new file. If it always creates a new file, the bug is unreachable in practice; if it ever rewrites in place, the documented fail-safe guarantee is broken.
- **Fix (verifier-improved):** Reject the finder's weaker "compare stored size/mtime for equality" option — a normal append legitimately changes both and that would destroy incrementality. Adopt the **stronger** option: persist a bounded prefix fingerprint and re-verify before resuming. To bound cost, hash a window (e.g. blake2b/sha1 over the first 4KB + the 4KB immediately preceding the offset) combined with the exact offset; on mismatch return `TranscriptScan(),0` for a full rescan. Bump `_SCAN_STATE_V` (currently 1) so existing sidecar files lacking the fingerprint are discarded.

### TRN-CLEAR — Parity-sweep verification: pure-ASCII assumption does **not** hide a multibyte UTF-8 byte-offset bug
- **Severity:** Info *(finder C2 T1-2: info, confirmed info — checked-and-clear)*
- **Location:** `claude/statusline/transcript.py:313-323` (`_process_bytes`), `:523-535` (`_scan_with_state`); test note at `test/test_transcript_scan.py:118`.
- **Evidence:** `_process_bytes` computes `consumed = data.rfind(b'\n')+1` on raw bytes. UTF-8 is self-synchronizing (exhaustively verified: `0x0A` never appears inside any multibyte encoding), so `rfind` always lands on a true line boundary and the offset can never fall mid-character. A byte-level parity sweep over 1/2/3/4-byte sequences (974 bytes, all 975 cut points) found 0 divergences. The suspected miscount **does not exist**.
- **Fix:** Optional **test-only** hardening — feed the existing byte-parity loop a multibyte blob to lock in the property; correct the misleading "pure ASCII" comment (the test already reads/writes in binary). No production change.

### TRN-SIDECHAIN — Scanner counts all assistant usage lines regardless of `isSidechain`/`sessionId`
- **Severity:** Low *(finder C2 T1-5: low, **partially-confirmed**)*
- **Location:** `claude/statusline/transcript.py:335` (`need_usage`), `:350-363` (`_apply_usage`).
- **Evidence (mechanism — confirmed):** `_apply_usage` folds every line where `"usage"` and `"assistant"` substrings appear and `message.id` is unique; it does **not** inspect `isSidechain`/`parentUuid`/`sessionId`. RunningSubagents reads the separate `subagents/*.jsonl`, so subagent stats come from there — but the main token/cost line uses unfiltered `TranscriptScan` totals.
- **Confidence:** Low / partially-confirmed — the **harm** (inflated main totals) is conditional on an unverified premise: that Claude Code interleaves sidechain/subagent usage lines into the *main* session JSONL. Could not be confirmed from this repo.
- **Impact:** *If* sidechain usage lines appear in the main transcript, main-session token/cost figures are inflated. Even if triggered, it inflates a soft client-side estimate, not a hard gate.
- **Fix (verifier-cautioned):** Do **not** apply blindly. First empirically confirm CC's main-transcript format. If sidechain lines are present, skip only `isSidechain==true` lines (read from the top-level object, `d.get('isSidechain')`) — **avoid** the finder's "filter to host `sessionId`" suggestion, which would drop legitimate usage on resumed/forked/compacted sessions and *undercount*. If absent, add a cheap defensive `if d.get('isSidechain'): return` plus a regression test.

### TRN-LOCK — Lost-update race on shared logs; full read-modify-write rewrite each render
*Merged: accounting C1 D1-5 + git-openspec C3 T1/T2 (orphaned temp files + atomicity-without-isolation).*
- **Severity:** Low *(all confirmed low)*
- **Location:** `claude/statusline/accounting.py:90-121` (`TokenLog.update` RMW), `:156-177` (`TokenRate.update` RMW); `claude/statusline/textutil.py:16-29` (`_atomic_write_text`: temp + `os.replace`, no flock).
- **Evidence:** Both updaters read the whole shared global file, mutate in memory, then `_atomic_write_text` rewrites it. `os.replace` gives atomicity (no torn reads) but **not isolation**: two concurrent processes both read the old state and the later `os.replace` wins, dropping the other's row. `TokenRate.update` always rewrites (`:177`, fresh timestamp); `TokenLog.update` is gated on change (`:119`). No `flock`/`fcntl`/`O_APPEND` anywhere. Separately, a render killed between `open(tmp)` and `os.replace` orphans a PID-suffixed `.tmp` file with no cleanup (bounded by PID reuse). Session-keyed cache files (git cache, statusline output, scan state) are unaffected.
- **Doc basis:** docs anticipate concurrent renders (`refreshInterval` ~1Hz; background subagents mutate state while idle); recommend caching keyed by `session_id`.
- **Impact:** Transient under-count of day totals/cost and lost rate samples under concurrent sessions; self-healing for `TokenLog` (idempotent per-session row replacement), persistent-but-aging for `TokenRate`. Slow unbounded accumulation of orphan `.tmp` files. Display-only.
- **Fix (verifier-improved, split per file):** For `statusline-token-rate.log` (genuinely append-only): use `O_APPEND` single-line writes (atomic under `PIPE_BUF`), moving pruning to read-time/periodic compaction — fixes both the race and the per-render full-rewrite churn. For `statusline-tokens.log` (in-place row replacement, summed with no dedup in `_rollup`): `O_APPEND` is **unsafe** (would double-count a session rendering twice/day) — use an `flock(LOCK_EX)` on a dedicated `<log>.lock` wrapping the whole read+write (note `fcntl` is POSIX-only; the module runs cross-platform, so add a Windows path or no-op fallback). For temp orphans: opportunistic mtime-guarded glob-unlink of `.<name>.*.tmp` siblings in the target dir (scoped, guarded so it never deletes a concurrent live render's temp). Do not drop the temp+replace (concurrent readers exist).

### CONFIG-EXPAND — `CLAUDE_CONFIG_DIR` used without `expanduser`/`abspath` — a tilde or relative value yields a bogus relative config dir
- **Severity:** Low *(finder C3 C1: low, confirmed low)*
- **Location:** `claude/statusline/config.py:16`.
- **Evidence:** `CLAUDE_DIR = Path(os.environ.get('CLAUDE_CONFIG_DIR', str(HOME/'.claude')))`. Verified: `CLAUDE_CONFIG_DIR='~/myclaude'` → literal relative `'~/myclaude'` (not absolute); `'relconfig'` → relative; default branch → absolute. `HOME` (line 15) *does* `expanduser`; `CLAUDE_DIR` does not. Every cache/log/output path derives from this.
- **Impact:** A tilde/relative value scatters files under the process cwd (or creates a literal `~` dir) and reads miss the real config dir. Misconfiguration-triggered; default unset → absolute, so latent.
- **Fix (verifier-improved):** `CLAUDE_DIR = Path(os.path.expanduser(os.environ.get('CLAUDE_CONFIG_DIR') or str(HOME / '.claude'))).resolve()`. The `or` form (vs `.get(key, default)`) also fixes the empty-string edge case (`''` → `Path('.')` = cwd). Keep `config.CLAUDE_DIR` attribute access so the test sandbox patch still works.

### TRN-OK — RunningSubagents staleness uses jsonl mtime only; per-subagent dedup is internally consistent (checked-OK)
- **Severity:** Info *(finder C2 T1-6: info, confirmed info)*
- **Location:** `claude/statusline/transcript.py:100-122, 124-175`.
- **Evidence:** `from_session` globs `subagents/*.meta.json`, derives the jsonl (`<uuid>.meta.json → <uuid>.jsonl`), drops any whose jsonl mtime is older than `STALE_SECONDS=20`, and per-subagent dedups usage by `message.id`. These totals are independent of the main `TranscriptScan` — no double-count within the panel. Behavior is intentional and internally consistent. (The module docstring loosely says it reads `subagents/*.jsonl`; the actual glob is `*.meta.json` — the finding is more accurate than the docstring.)
- **Fix:** No change needed; optionally document that subagent liveness is mtime-based (a >20s stall hides the row).

---

## Recommended remediation order

1. **SEC-1 + SEC-2 (High, security):** add capture-time control-char/escape sanitization (centralized in `_as_str` / `git.py` / transcript capture) and stop reading the cloned repo's `.claude/settings.json` for plugin display. Single highest-impact cluster; contradicts the prior "clean" verdict.
2. **ROB-1 (High, robustness):** guard `main()`'s stdin parse with `try/except` + `isinstance(dict)`; skip the payload write on fallback. One-line class of crashes on the primary input path.
3. **TRN-1 (High, correctness):** add a bounded prefix-fingerprint check in `_resume_point` and bump `_SCAN_STATE_V` — restores the fail-safe-to-full-scan guarantee after `/compact`. (First confirm CC `/compact` rewrites in place; if it always replaces the file, demote.)
4. **DATA-1 / DATA-2 (High/Medium, data-effectiveness):** route all five context sites through one input-only helper preferring `used_percentage`; resolves DATA-1, DATA-2, DATA-3, and the scan-stream context findings together.
5. **WIDTH-1 + PERF-TMUX (High/Medium):** make `COLUMNS` the first width source; add `timeout=0.2` + `TimeoutExpired` to the tmux probe (or retire it on v2.1.153+); drop the obsolete width-file source (WIDTH-3) and the redundant `COLUMNS` re-read (WIDTH-4); update README.
6. **MON-1 (High, operational):** resolve `mon` roots from `config.CLAUDE_DIR` at call time inside `discover()`.
7. **NAN + R-ENAMETOOLONG (Medium, robustness):** finite-guard `_as_int`; wrap the git `exists()`/`is_file()` probes in `try/except OSError`.
8. **Rendering width/overflow cluster (Medium):** CTX-NEG (floor token total in `from_dict`), CWIDTH (EAW-aware `_is_wide`), CTRUNC (width-aware `_middle_ellipsis`), MODELW (budget the wide model section), A1-3 (resolved by SEC-1's sanitization + width fixes).
9. **Accounting + OpenSpec correctness (Medium):** ACCT-1 (cache-creation column + 1.25× day cost, with on-disk format migration), OS-ARCHIVE (anchored `relative_to(root).parts` filter; fixes OS-ARCHIVE-WIN too).
10. **Install/operational (Medium):** INSTALL-CLOBBER (foreign-statusLine guard/prompt), DATA-4 (`exceeds_200k_tokens` marker), DATA-5 (elapsed from `total_duration_ms`).
11. **Low/Info polish (batch):** DOC-REFRESH + DOC-ASYNC, CI-PIN, ALACRITTY/WIDTH-3 disposition, CONFIG-EXPAND, GIT-STAGED, KEY-DERIV, TRN-LOCK, R-SYMLINK + R-CONTROL-MEM, R-ESCAPE-LEAK, MON-ZIP, MON-FOOTER, INSTALL-RESTORE, PERF-STATE; plus the feature-capture items (FEAT-1 slug-elimination win, FEAT-2…FEAT-9) as roadmap.

---

## Checked-and-found-OK (so the report isn't only negative)

From the verifiers' own notes, several adversarial hypotheses were tested and **cleared**: multibyte UTF-8 byte-offset tailing is correct because UTF-8 is self-synchronizing (TRN-CLEAR, exhaustively verified, 0/975 divergences); the headline context line already runs entirely off stdin with no transcript-scan contamination, and the scan is genuinely load-bearing only for skills, tasks, cumulative usage, day cost, and the burn-rate sparkline (DATA-6 / scan-redundancy survey); `git.py` is necessary and not made redundant by the stdin `git_worktree`/`repo` fields (FEAT-9); session-keyed cache files (git cache, statusline output, scan state) are race-free because targets are per-session (TRN-LOCK scope); the RunningSubagents per-subagent dedup and mtime-based staleness are internally consistent (TRN-OK); and the dual-clock concern (`clock.now()` vs `time.time()`) was **refuted** outright — every frozen-clock test fixture patches both, all 21 theme snapshot tests pass deterministically, and `clock.now()` exists only because `datetime.now()` can't be patched via the module-attribute trick (see appendix).

*Appendix — refuted finding (excluded): "clock.now() is patchable but time.time() is used for all TTL/window/cache timestamps and is not — two clocks diverge under a frozen snapshot" (finder C3). Refuted: the load-bearing claim that the fixture does not patch `time.time` is false — `test_themes.py:145`, `test_helper.py:108`, and `test_git_info.py:188/195/203/221` all patch `time.time` alongside `clock.now`; all modules share one `time` module object, so `monkeypatch.setattr` is observed uniformly. The only accurate residual (naive-local-tz `.astimezone()`) is correct behavior, not a defect.*
---

## Remediation status (updated after implementation)

Six finding-clusters from this report were fixed on `perf/phase1-hotpath` after
the audit, each with tests and verified green (pytest + ruff + mypy --strict):

| Commit | Findings resolved |
|---|---|
| `edc009c` | **SEC-1** (terminal-escape injection — capture-time `_sanitize`), **SEC-2** (trust boundary — drop cloned-repo `settings.json`), **ROB-1** (non-object/empty stdin crash), **NAN** (`NaN`/`Inf` int fields) |
| `caa5a36` | **DATA-1/DATA-2/DATA-3** (input-only context %, prefers host `used_percentage`), **CTX-NEG** (negative-token clamp) |
| `11f8448` | **WIDTH-1** (`COLUMNS` is now the first width source), **PERF-TMUX** (tmux probe `timeout=0.2` + `SubprocessError` catch) |
| `160941e` | **MON-1** (`mon` resolves roots from `config.CLAUDE_DIR`, honours `CLAUDE_CONFIG_DIR`) |
| `1615e83` | **CWIDTH** (EAW-aware width), **CTRUNC** (width-aware middle-ellipsis), **MODELW** (bounded model name) |
| `e850345` | **OS-ARCHIVE / OS-ARCHIVE-WIN** (anchored `relative_to(root).parts` filter) |

**Not yet implemented** (still open as written above): DATA-4 (`exceeds_200k_tokens`
badge), DATA-5 (elapsed from `cost.total_duration_ms` — confirmed it would *not*
drift the snapshots, since the example fixture's `transcript_path` does not exist
so `elapsed_from_transcript` already returns `''`), ACCT-1 (day-cost cache-creation
1.25× — deferred because it requires an on-disk token-log format change), and the
remaining Low/Info items (R-CONTROL-MEM, R-SYMLINK, R-ESCAPE-LEAK, CI-PIN, GIT-STAGED,
GIT-CACHE-HEAD, KEY-DERIV, MON-FOOTER, MON-ZIP, INSTALL-CLOBBER/RESTORE, ALACRITTY,
WIDTH-3/4/5, DOC-REFRESH, DOC-ASYNC, CONFIG-EXPAND, PERF-STATE, FEAT-1..9). **TRN-1**
was intentionally skipped pending confirmation of whether Claude Code's `/compact`
rewrites the transcript in place.
