# HANDOFF.md — `perf/phase1-hotpath`

> Working handoff for the next engineer (or future AI session) continuing the `perf/phase1-hotpath` branch of **yet-another-statusline**, a stdlib-only Python Claude Code statusline. The eventual goal is a clean PR to `main`.

---

## 1. TL;DR / Status at a glance

**What this branch is.** `perf/phase1-hotpath` lands the audit-driven roadmap from `AUDIT.md`: it (a) hardens and speeds up the per-render hot path (Phase 1), (b) does a UX glyph/gradient/contrast/layout pass, and (c) splits the ~3,300-line monolith into a reusable `statusline/` data-core subpackage (Phase 2). Phases 3–5 (compiled core, background collector, native macOS app) are **not started**.

**Commit count.** `git rev-list --count origin/main..HEAD` and `git rev-list --count main..HEAD` both report **20 commits ahead**, working tree clean. (Note: the session brief stated 21; the repo measured 20 this session — the 19 feature/refactor commits documented below plus the initial `AUDIT.md` commit `8055255` = 20. Treat **20** as the verified figure and re-check before writing PR copy.)

**Green-state line** (measured this session, macOS, Python 3.12.2; see §6 for the toolchain caveat):

| Check | Command (as run) | Result |
|---|---|---|
| Tests | `python3 -m pytest -q` | **545 passed** in ~4.3s |
| Lint | `ruff check claude/` (ruff 0.11.8) | **All checks passed** |
| Types | `mypy` strict (1.17.1) | **Success: no issues in 13 source files** |
| Bench | `ops/bench.py` (Python fallback timer; hyperfine absent) | PR (current tree) **188.0 ± 9.4 ms** (min 170.4); `main` (base worktree) **194.7 ± 8.8 ms** (min 178.9); `main` 1.04 ± 0.07x slower than PR |

**Bench caveat (important):** this is a **full-process, realistic-transcript** scenario, so Python interpreter startup dominates the wall time and the 1.04x ratio **understates** the per-render compute savings. See §5.

**Monolith size:** `claude/statusline_command.py` is now **1,832 lines** (verified `wc -l`), down from ~3,277; Phase 2 extracted ~1,445 lines net (-44%) into the subpackage.

---

## 2. What changed on this branch

Three themes. Commits map to findings in the `AUDIT.md` register (P = performance, C = cost/metric, G = git, O = ops/state, A = architecture, R = render, UX = branch UX work not in the register).

### 2a. Phase 0/1 — hot-path performance + correctness

| Commit | Subject | Findings |
|---|---|---|
| `8055255` | docs: add security/performance/architecture audit + roadmap (AUDIT.md) | establishes the register P1–P7 / C1–C3 / O1–O5 / G1–G2 / A1–A3 + Phase 0–5 roadmap |
| `2d8f470` | perf+fix: hot-path optimization + metric/git/state correctness | **P1, P2, C1, C2, O3, G1, G2** |
| `89c2293` | perf: cache git status per session | **P5** |
| `91596fa` | bench: add realistic-transcript scenario to ops/bench.py | **P7** |
| `7cce934` | fix(bench): always sandbox CLAUDE_CONFIG_DIR | follow-up to P7 (bench never touches real `~/.claude`) |
| `d4107e5` | docs: record R1 (render engine dominates per-render cost) in AUDIT.md | **R1** (records finding + reorders Phase priorities) |

Highlights from `2d8f470`: the three independent wide-render transcript scans (skills / tasks / usage) collapse into one single-pass `TranscriptScan` with incremental tailing (P1); session cost now prefers the host-authoritative `cost.total_cost_usd` with a version-keyed fallback rate table (C1); a backward-compatible **v2** token-log format records a per-row model id so day cost is priced per-model (C2); payload + both logs are written atomically via temp-file + `os.replace` (O3); git worktree/`.git`-file/`packed-refs` resolution and full branch-name preservation are fixed in the file-read path with no new subprocess (G1/G2). Test count rose 509 → 529 across this work (parity sweep, git, v2 log/per-model, version-keyed pricing); `89c2293` added ~68 new git-cache test lines (and +47 implementation lines in the monolith).

### 2b. UX pass (UX1–UX4 — branch work, not in the AUDIT register)

| Commit | Subject | Maps to |
|---|---|---|
| `5c1d3fa` | fix(ux): context shows real window fill %, not the 150K soft-pressure number | UX1 / implements audit **C3** |
| `6b70dba` | style(ux): calm fuel-gauge gradient (green→amber→red), retire the rainbow | UX2 (later superseded by `0ecb94a`) |
| `46e9254` | feat(ux): universal Unicode glyphs by default; Nerd Font now opt-in | UX3 |
| `0ecb94a` | feat(ux): high-contrast monochrome theme + fully universal glyphs | UX2 (supersedes) + UX3 (completes) |
| `8a9f72c` | fix(ux): plugins/skills row honours width — no more wide-layout overflow | UX4 |

Net effect: the context line now shows true context-window fill (`total/context_window_size`, capped 0–100%) instead of the old `total/150000` that read e.g. 524% on a 1M-context session; the rainbow gradient is retired in favour of a calm fuel-gauge and then a high-contrast greyscale `claude-dark`; default glyphs are universal BMP Unicode with Nerd-Font PUA glyphs gated behind `YAS_NERD_FONT=1`; the plugins/skills row now budgets to width and truncates with an ellipsis.

### 2c. Phase 2 — monolith → `statusline/` subpackage (A1)

Nine `refactor(phase2)` commits, in order:

| Commit | Subject | Monolith after |
|---|---|---|
| `5a50c17` | import the statusline subpackage normally (retire themes importlib shim) | (foundation) |
| `7c6e54b` | extract pure text/width/format helpers → `textutil.py` | 3264 → 3168 |
| `50fc79f` | runtime-config singletons → `config.py` (canonical patch point) | (foundation) |
| `48dbff9` | extract payload data model + pricing → `models.py` | 3168 → 2820 |
| `27b34e5` | wall-clock singleton → `clock.py` (cross-module datetime hazard) | (foundation) |
| `10c8b70` | extract token accounting + cost computation → `accounting.py` | 2820 → 2592 |
| `281c289` | extract transcript scanning + derived data → `transcript.py` (~565 lines) | 2069 |
| `26d0364` | extract git repo inspection → `git.py` | 1870 |
| `c010418` | extract openspec change-set inspection → `openspec.py` (completes Phase 2) | **1832** |

Byte-identity snapshots were preserved across the split; `c010418` declares "Phase 2 complete" at a cumulative 3277 → 1832 (-1445 lines, -44%). The **render/layout engine was intentionally NOT extracted** — Phase 2 only carved out the reusable data-core. See §3.

---

## 3. Architecture after the refactor

### Module responsibility table (`claude/statusline/`)

| Path | Responsibility | Key exports | Depends on |
|---|---|---|---|
| `config.py` | Runtime config singletons (resolved Claude config dir + home), read via attribute access so the test sandbox patches one place | `HOME`, `CLAUDE_DIR` (honours `$CLAUDE_CONFIG_DIR`) | — |
| `clock.py` | Wall-clock singleton; `clock.now()` is the single `datetime.now()` seam every module calls | `now() -> datetime` | — |
| `textutil.py` | Pure stdlib text/width/number helpers + atomic file write | `_atomic_write_text`, `_is_wide`, `_visible_width`, `_middle_ellipsis`, `fmt_tok`, `fmt_dur`, `sparkline_width`, `_ANSI_RE` | — |
| `themes.py` | Theme system: frozen `Theme` dataclass, four built-in themes, name→Theme resolution | `Theme`, `ModelColors`, `RGB`, `fg`, `fg256`, `CLAUDE_DARK`, `CLAUDE_LIGHT`, `CATPPUCCIN_LATTE`, `CATPPUCCIN_MOCHA`, `THEMES`, `resolve` | — |
| `models.py` | Session-info payload dataclasses + `TokenAccounting` pricing + `model_key` | `SessionInfo`, `Model`, `Workspace`, `Cost`, `ContextWindow`, `CurrentUsage`, `RateLimits`, `RateBucket`, `OutputStyle`, `Effort`, `Thinking`, `TokenAccounting`, `model_key`, `_model_version`, `_as_int/_as_float/_as_str` | `config` |
| `accounting.py` | Per-session token accounting + cost: daily token log, rolling rate log, cost wrappers | `TokenLog`, `TokenRate`, `compute_session_cost`, `compute_day_cost`, `session_cost_display`, `elapsed_from_transcript`, `_model_log_key` | `config`, `models`, `textutil`, `transcript` (TYPE_CHECKING-only) |
| `transcript.py` | Single-pass JSONL scanning (skills/tasks/usage) with file-identity caching + incremental tailing; running-subagents scanner | `TranscriptScan`, `TranscriptUsage`, `LoadedSkills`, `TaskList`, `Task`, `RunningSubagents`, `RunningSubagent`, `_scan_transcript`, `_incremental_enabled`, `_scan_with_state`, `_resume_point`, `_save_scan_state`, `_scan_state_path`, `_parse_iso_to_epoch`, `_SCAN_CACHE`, `_SCAN_STATE_V` | `config`, `models`, `textutil` |
| `git.py` | Git repo inspection: live branch/commit from `.git` reads + per-session-cached `git status` dirty counts; worktree/submodule/packed-refs aware | `GitInfo`, `GIT_CACHE_TTL` | `config`, `models`, `textutil` |
| `openspec.py` | OpenSpec change-set inspection: walks `openspec/` for `tasks.md` (excluding `archive/`), reports done/total checkbox counts | `OpenSpec` (`OpenSpec.from_cwd`) | — |
| `demo.py` | Hermetic demo/snapshot harness: synthetic `~/.claude` + project tree under a tempdir, pipes scenarios to the production statusline subprocess | `main`, `animate`, `render_scenario`, `ScenarioConfig`, `SCENARIOS`, `build_synthetic_env`, `write_transcript`, `write_subagents`, `write_openspec_changes`, `render_once` | stdlib only (invokes `statusline_command.py` as a subprocess) |
| `alacritty.py` | Standalone Alacritty helper: parses `alacritty -v` resize logs, writes `~/.claude/terminal-width`, SIGWINCHes claude processes. **Not part of the renderer pipeline.** | (module-level script; no exports) | — |
| `__init__.py` | Empty package marker (no re-exports); submodules imported by full dotted path | — | — |

Pre-existing module line counts (this session): `themes.py` 488, `demo.py` 709, `alacritty.py` 40. New-module lines: `accounting.py` 251, `clock.py` 20, `config.py` 16, `git.py` 229, `models.py` 375, `openspec.py` 51, `textutil.py` 127, `transcript.py` 565.

### What remains in `statusline_command.py` (1,832 lines)

The file is now **only the presentation + orchestration layer**. It still re-imports nearly every extracted symbol (with `# noqa: F401`) so legacy callers, `mon.py`, and tests that reach them via `statusline_command.X` keep working. What lives there:

1. **The layered ANSI renderer:** `class GradientEngine` (l.361 — gradient/spark RGB interpolation, `gradient_bar`, `sparkline`), `class BorderRenderer` (l.474 — borders/separators, elbow/up-down column math, pill painting), `class Renderer` (l.600 — composes the two, binds every `Theme` colour via `_apply_theme`, owns all section builders: `fit_path`, `model_right_section[_compact]`, `tokens_cost`, `context_line[_compact]`, `plugins_skills`, `subagent_row`, `task_row`, `openspec_bar`, `vsep_block`, `helper`, `burndown_trend`, `fill_colour`/`day_cost_colour` ladders).
2. **Layout pipeline:** `@dataclass RowSpec` / `@dataclass LayoutSpec`, the three width-tier builders `build_narrow` / `build_medium` / `build_wide` (l.1500/1547/1606), and `render_layout` (l.1731).
3. **Render-engine support:** `class BarChars`, `@dataclass Pill`, `paint_bg_span`, `pill_gradient_fg`, `rainbow_step/at/color`, `_scale`, `_glyph`, `terminal_width`, `burndown_delta`, `subagent_avg_tpm`, `subagent_share`, plus width/limit constants `MIN_WIDTH`/`NARROW_WIDTH`/`MEDIUM_WIDTH`/`MAX_WIDTH`/`SOFT_LIMIT`, `FIVE_HOUR`/`SEVEN_DAY`.
4. **Entry/orchestration:** `resolve_theme` (layered CLI → env → config-file → `CLAUDE_DARK`), `render`, and `main` (UTF-8 stdout reconfigure, argv parse for `--theme`/`--bg-shift`, stdin JSON parse, payload write-out for the `mon` observer, width clamp, dispatch to the tier builder).

These classes were left in place because they are tightly coupled to `Theme` and to one another; a **renderer-split phase** is deferred.

### Patch points (critical for tests)

Two canonical singletons, **patched by attribute on the module object** — never `from X import name`, which would freeze the import-time value:

- **CONFIG:** `test/conftest.py`'s `tmp_home` fixture does `from statusline import config; monkeypatch.setattr(config, 'HOME', tmp_path)` and `setattr(config, 'CLAUDE_DIR', tmp_path / '.claude')`. Because every module reads `config.CLAUDE_DIR` / `config.HOME` dynamically, this one patch reaches `models`, `accounting`, `transcript`, `git`, `openspec` (indirect), and `statusline_command`.
- **CLOCK:** tests freeze wall time via `monkeypatch.setattr(clock, 'now', _FakeDatetime.now)` (e.g. `test/test_helper.py` l.107), often paired with `monkeypatch.setattr(sl.time, 'time', lambda: _NOW)` for `time.time()`-based code paths.

Tests load the monolith itself via `importlib.util.spec_from_file_location` under the name `statusline_command` (`conftest` l.12–19) and reference symbols as `sl.<name>` (submodules via `sl.<module>.<name>`).

### Import style

The importlib shim is **retired** (`5a50c17`). `statusline_command.py` runs as a top-level file: at l.21 it does `sys.path.insert(0, str(Path(__file__).resolve().parent))` (same trick `mon.py` uses), then imports the subpackage with plain `from statusline.themes import ...`, `from statusline import clock, config, transcript`, etc. (l.23–35, `# noqa: E402,F401`). Submodules import each other the same way by full dotted path — a single shared instance per submodule, no double-load identity bugs.

---

## 4. Findings register status

Status legend: **resolved** = done & tested on this branch · **partial** = some sub-items landed, others open · **open** = not addressed on this branch · **n/a** = branch UX work not in the AUDIT register.

| ID | Title | Severity | Status | Evidence |
|---|---|---|---|---|
| **S1** | Zero runtime deps; stdlib only (positive) | Info (positive) | resolved | `pyproject.toml dependencies=[]`; Phase 2 kept stdlib-only |
| **S2** | No outbound network anywhere (positive) | Info (positive) | resolved | design property, unchanged |
| **S3** | No auto-running hooks (positive) | Info (positive) | resolved | `hooks/hooks.json`, unchanged |
| **S4** | 12 read-only shell allows (positive) | Low (positive) | resolved | design property, unchanged |
| **S5** | `async:true` written but undocumented (effect unverified) | Info | **open** | `skills/init/SKILL.md:101` still writes `"async":true`; SKILL.md unchanged on branch; no commit verifies/drops it |
| **P1** | Transcript scanned 3x per wide render | Medium | resolved | `2d8f470`; `transcript.py` `TranscriptScan`/`_process_bytes`/`_scan_with_state`; parity sweep green |
| **P2** | Two log files read+rewritten every render | Low | **partial** | `2d8f470`: `TokenLog.update` rewrites only on change (done); **`TokenRate.update` still full read-modify-write+rewrite each render — NOT append-only** |
| **P3** | Fresh Python interpreter every render | Medium | **open** | no daemon/compiled binary; R1 downgraded priority (startup ~13 ms) but the finding itself is unaddressed |
| **P4** | tmux probe spawned before cheaper width sources | Low | **open** | `statusline_command.py` `terminal_width()` l.98–100 still probes tmux **first**, then terminal-width file, then `$COLUMNS`; no reorder commit |
| **P5** | git status every render, no cache | Low | resolved | `89c2293`; `git.py` `_dirty_cached` + `GIT_CACHE_TTL` (env `YAS_GIT_CACHE_TTL`, default 4s); branch/commit re-read live |
| **P6** | openspec parent-walk every render even when unused | Low | **open** | `openspec.py` `_find_root` l.43–51 still walks parents with no cache; literal `'/archive/'` filter (l.28) still Windows-broken |
| **P7** | Benchmark uses tiny fixture, hides real cost | Medium | resolved | `91596fa` `--transcript-lines N`; `7cce934` sandboxes `CLAUDE_CONFIG_DIR` |
| **C1** | Version-blind pricing (~3x high for Opus; ignores host total_cost_usd; Fast-mode unpriced) | Medium | **partial** | `2d8f470`: session cost prefers host `cost.total_cost_usd`; rate table version-keyed (Opus 4.5+ $5/$25, Haiku 4.5 $1/$5). **Fast-mode 6x sub-item NOT claimed in commit body — verify separately (likely unaddressed)** |
| **C2** | Day cost prices all sessions with current model | Medium | resolved | `2d8f470`; per-row model id (v2 format, backward-compatible 4/5/6-field parse); day cost priced per-model |
| **C3** | Headline context % is a 150k soft-pressure score, not official fill | Low/Med | resolved | `5c1d3fa` (UX1); `context_line` l.1340–1354 use `scale=context_window_size` (fall back to `SOFT_LIMIT` only when unknown), capped 0–100% |
| **S6** | CI `actions/checkout@v6` is a moving tag, not a SHA pin | Info/Low | **open** | no `.github/workflows/ci.yml` change on branch |
| **O1** | init/uninstall use mktemp/mv/rm/python outside the allowlist | Low/Med | **open** | no docs added; `skills/init/SKILL.md` unchanged; `README.md:142` only mentions the hooks prompt |
| **O2** | Lost-update race also affects `TokenLog` (daily totals) | Low/Med | **partial** | `2d8f470` added atomic `os.replace` (closes O3 torn-write) but **NO file lock (no fcntl/flock)** — concurrent sessions can still clobber each other's row; window remains open |
| **O3** | Existing payload/log writes are non-atomic | Low | resolved | `2d8f470`; `_atomic_write_text` (temp+`os.replace`) used for payload (`statusline_command.py:1818`) and both logs (`accounting.py:120,177`) |
| **O4** | `/yas:init` ignores `CLAUDE_CONFIG_DIR` | Low | **open** | `skills/init/SKILL.md` still hardcodes `$HOME/.claude` (l.91,92,96,105,108); unchanged on branch |
| **O5** | Stale `statusline-output/*.json` accumulate after sessions end | Low | **open** | no prune/cleanup/unlink in `statusline_command.py` or `mon/discovery.py`; no commit |
| **G1** | Worktree/submodule `.git`-file + packed-refs mishandled | Low/Med | resolved | `2d8f470` (+ extracted in `26d0364`); `git.py` `_resolve_gitdir`/`_read_commit`; worktree/packed-refs tests |
| **G2** | Branch namespace truncated (feature/foo → foo) | Low | resolved | `2d8f470`; `git.py` `_read_head` l.142–145 preserve full `refs/heads/` namespace |
| **R1** | Pure-Python gradient/ANSI render engine dominates per-render cost | Medium-High | **open** | only documented (`d4107e5`) + marginally helped by fewer `GRAD_STOPS` (`6b70dba`); `grad_at`/`gradient_rgb`/`spark_rgb` (`statusline_command.py:373–425`) have **no memoization/lru_cache**. Highest-value remaining latency target |
| **A1** | 2,928-line monolith | Medium | resolved | Phase 2 (8 extraction commits `5a50c17..c010418`); monolith now 1832 lines |
| **A2** | Incremental tailing must preserve id-dedup + task state | Note | resolved | `2d8f470`; `transcript.py` persists `usage_seen` + task state; never advances past a non-newline-terminated final line; fail-safe full rescan + `YAS_NO_INCREMENTAL` kill switch |
| **A3** | Alacritty helper ignores `CLAUDE_CONFIG_DIR`; broad `pgrep`+SIGWINCH | Low | **open** | `alacritty.py` still writes `os.environ['HOME']/.claude/terminal-width` (l.26), still `pgrep -f claude` (l.29) + SIGWINCH to every match (l.33); unchanged |
| **UX1** | Context showed 150K soft-pressure number (e.g. 524%) | n/a (overlaps C3) | resolved | `5c1d3fa`; implements the C3 fix |
| **UX2** | Rainbow gradient → calm green→amber→red fuel gauge | n/a | resolved | `6b70dba`; later superseded for claude-dark by monochrome (`0ecb94a`) |
| **UX3** | Nerd Font required → universal Unicode default, Nerd Font opt-in | n/a | resolved | `46e9254` + `0ecb94a`; `statusline_command.py:165–191` `_glyph`/`YAS_NERD_FONT`; `test_glyphs.py` |
| **UX4** | plugins/skills row overflowed wide layout | n/a | resolved | `8a9f72c`; budgets to width-4 and truncates |

**At a glance — what is still OUTSTANDING:** P2 (rate log not append-only), P3 (no compiled core), **P4** (tmux ordering), P6 (openspec cache + Windows `/archive/` bug), C1 Fast-mode 6x sub-item, S5 (`async:true`), S6 (CI SHA pin), O1 (init/uninstall docs), **O2** (lost-update race — no lock), O4 (init `CONFIG_DIR`), O5 (stale JSON prune), **R1** (render-engine memoization), A3 (Alacritty hardening).

---

## 5. Performance story

### What Phase 1 landed
- **P1 / A2 — single-pass + incremental scan.** Three independent wide-render scans (`LoadedSkills`, `TaskList`, `TranscriptUsage`) collapsed into one binary-mode `TranscriptScan` (`transcript.py`, `def` ~l.275, full-scan fallback `scan_full` — classmethod `TranscriptScan.scan_full`, l.297). On re-render it tails incrementally, reading only newly-appended bytes via a persisted byte offset (`_incremental_enabled` ~l.477, incremental path ~l.557); `2d8f470` measured the warm read at ~0.15% of a 369KB transcript. Gated to real session transcripts under `projects/`, fail-safe to a full scan, dedup/task-state correctness preserved by serializing the full accumulator (`to_state` ~l.426).
- **C1 / C2** — host-authoritative `cost.total_cost_usd` preferred; version-keyed fallback table; per-model day cost via the backward-compatible v2 token-log format.
- **P2 (partial)** — token log rewritten only when content changes.
- **O3** — atomic writes (`textutil._atomic_write_text`, `os.replace` ~l.27) for payload + both logs.
- **G1 / G2** — git correctness in the fast file-read path with no new subprocess.
- **P5** — per-session `git status` dirty-count cache (`GIT_CACHE_TTL`, env `YAS_GIT_CACHE_TTL`, default 4s); branch/commit still re-read every render so a branch switch shows immediately; cache disabled when there is no session id; corrupt/missing/expired cache reruns git.

Test count rose 509 → 529 across this work; `2d8f470`'s commit body states mypy --strict + ruff clean and the wide golden snapshot regenerated (only the session-cost cell changed).

### The R1 conclusion (a humbling correction to the audit's premise)
After the scan optimizations landed, the realistic benchmark plus in-process phase profiling found scanning/startup is **not** the dominant per-render cost. Bare `python3` startup is only ~13 ms here; the warm incremental scan is ~0.5 ms (single-pass+incremental makes `main` only ~3% slower at 4,000 transcript lines, but ~23% / ~37 ms slower at 12,000 lines — so the scan win is **real and grows with session length**, but small for short sessions). The dominant per-render cost is the **pure-Python gradient/ANSI render engine**: `build_narrow` ~0.04 ms, `build_medium` ~37 ms, `build_wide` ~60–100 ms — independent of transcript size AND terminal width, and unchanged when token-log I/O is stubbed. The hot path is per-cell RGB interpolation (`grad_at` / `spark_rgb`, hundreds of calls per render). This **reorders priorities**: the highest-value remaining latency target is the render engine (rated Medium-High in the §7 table), and it strengthens the case for the eventual compiled core, which would help the render math most.

### What the benchmark does and its limitation
`ops/bench.py` times `python3 <script>` subprocess invocations of the current working tree (**"PR"**) against a base git ref (default `main`) checked out into a throwaway detached worktree (`base_worktree`, l.50–60). It auto-selects hyperfine when present, else a stdlib `perf_counter` timer (`Stats.measure`, l.136–155; default 50 runs / 3 warmup). The P7 fix is `--transcript-lines N`: by default (N=0) it uses the legacy 1.2KB `session-info-example.json` fixture whose `transcript_path` points nowhere — explicitly noted as **not** exercising transcript scanning; with N>0 the `scenario()` context manager (l.63–96) generates an N-line JSONL transcript under `projects/bench-slug/` plus a matching session JSON fed on stdin, so incremental tailing actually engages (N>0 forces the python timer because hyperfine can't supply custom stdin+env). `scenario()` **always** points `CLAUDE_CONFIG_DIR` at a fresh `tempfile.mkdtemp()` (l.71–74) so the benchmark never reads/writes the real `~/.claude`, regardless of N; the temp dir is `shutil.rmtree`'d in `finally` (l.95–96).

**Limitation (restating the green-state caveat):** the headline numbers in §1 are full-process wall time on a **realistic-transcript** scenario, so interpreter startup dominates and the 1.04x ratio **understates** per-render compute savings. The compute win is best seen at large transcript line counts (~23% / ~37 ms at 12,000 lines) and via in-process phase profiling, not the floor run.

### Open perf work (priority order)
1. **R1 / render engine (highest value, Medium-High).** Memoize/precompute the gradient engine and/or cache rendered segments to attack `build_wide`'s ~60–100 ms per-cell RGB interpolation (`grad_at`/`spark_rgb`). AUDIT calls this **"Phase 2.5"** — the cheapest near-term win before any compiled core. **Not started; no `lru_cache` in the render engine.**
2. **Phase 3 — compiled hot path (recommendation: Rust).** Port per-render collection+render to one statically-linked binary. Post-R1: the payoff is the render math, not the ~13 ms startup. Rust chosen so the same core compiles as a library callable from Swift via C FFI for the macOS app. **Not started.**
3. **P4** — reorder `terminal_width()` so the tmux subprocess is spawned **last**, after the cheaper width sources.
4. **P6** — cache "no openspec here" per cwd; also fix the Windows-broken literal `'/archive/'` filter.
5. **O2 / O5 housekeeping** — O2 lost-update race on `TokenLog` daily totals across concurrent sessions (needs append-only or a file lock + atomic replace; O3 atomic write alone does NOT close it); O5 opportunistic pruning of stale `statusline-output/*.json`.
6. **Phase 4 — background collector + per-session computed-stats JSON.** A long-lived daemon watching all active transcripts, writing corrected computed stats (host `total_cost_usd`, per-session model, official context fill vs soft-pressure separately, burn rate, history). Today only the raw payload is persisted (`statusline_command.py:1818`). Bridge to the Phase 5 macOS viewer.

---

## 6. How to build / test / run

> **Toolchain caveat (read first).** This repo expects **`uv`**, but `uv` is **NOT installed on this machine and there is no `.venv`**, so `make test` / `make bench` / any `uv run …` **fail with `uv: No such file or directory`**. This session ran pytest / ruff / mypy directly via the anaconda `python3` (3.12.2) and ran `ops/bench.py` directly with `python3`. The green-state in §1 was obtained that way. The canonical commands below are the intended path once `uv` is available; the "direct equivalent" column is what actually works in this environment.

| Canonical (intended) | Direct equivalent (works here without `uv`) | Purpose |
|---|---|---|
| `make test` | `python3 -m pytest -q` | Full suite (**545 passed ~4.3s** this session). Scope with `-k <expr>` or a path. |
| `uv run pytest -q` | `python3 -m pytest -q` | Same as above. |
| `make bench [BENCH_ARGS=...]` | `python3 ops/bench.py [args]` | PR (current tree) vs base ref (default `main`). hyperfine if present, else Python timer. Add `--transcript-lines N` for the realistic scenario. |
| `uv run mypy claude/statusline_command.py claude/statusline/` | `mypy claude/statusline_command.py claude/statusline/` (strict) | Strict type check of the statusline production source (**Success: no issues in 13 files**). `test/`, `openspec/`, `.claude/` excluded. |
| `uv run ruff check . && uv run ruff format --check .` | `ruff check claude/` (+ `ruff format --check .`) | Lint + format check (**All checks passed**). |
| `make demo` | `python3 claude/statusline/demo.py` | Animated hermetic **human** visual check (synthetic `~/.claude`, `$HOME` repointed, no residue). |
| `make demo/img` | `python3 claude/statusline/demo.py --snapshots demo/` | Render demo scenarios as static images into `demo/`. |
| `make hooks` | `git config core.hooksPath .github/hooks` | Enable repo pre-commit hooks (same checks CI runs on push). |
| `make mon/run` | `python3 claude/mon.py` | Companion monitor TUI (exercised by `test_mon_*.py`). |
| `make pr-info` | — | Print environment provenance for PR bug reports. |

---

## 7. Open items / next steps

### Immediate, low-risk wins (do before a compiled core)
- **R1 render-engine memoization ("Phase 2.5").** The single highest-value latency target. Memoize/`lru_cache` `grad_at`/`gradient_rgb`/`spark_rgb` and/or cache rendered segments. No memoization exists today. Verify with `ops/bench.py --transcript-lines 12000` and in-process phase profiling — the floor run won't show it.
- **P4 tmux ordering** — trivial reorder in `terminal_width()`; spawn tmux last.
- **P6 openspec cache + Windows fix** — cache "no openspec here" per cwd; replace the literal `'/archive/'` substring filter with a path-aware check.

### Correctness / state hardening
- **O2 lost-update race (still OPEN).** Atomic `os.replace` closed the *torn-write* (O3) but **not** the concurrent-clobber race — there is **no file lock (no `fcntl`/`flock`)** and both logs are still read-modify-write. Two concurrent sessions on the same day can still overwrite each other's row. Needs append-only or lock + atomic replace.
- **P2 (still PARTIAL).** `TokenRate.update` (`accounting.py:156–177`) is still full read-modify-write+rewrite every render; Phase 1 step 4 specified converting it to append-only. Not done.
- **O5** — no pruning of stale `statusline-output/*.json`.

### Documentation / config / CI
- **S5** — `skills/init/SKILL.md:101` still writes `"async":true`; Phase 0 said "verify or drop." Unverified.
- **C1 Fast-mode 6x** — the commit body for `2d8f470` does **not** claim Fast-mode 6x pricing was added. Treat this sub-item as **likely unaddressed** and verify against `models.py` before claiming C1 fully resolved.
- **O1 / O4** — init/uninstall use non-allowlisted commands (mktemp/mv/rm/python) with no docs, and `/yas:init` hardcodes `$HOME/.claude` ignoring `CLAUDE_CONFIG_DIR`. `skills/init/SKILL.md` is unchanged on this branch.
- **S6** — `actions/checkout@v6` is a moving tag; pin by SHA or soften wording. No CI change on branch.
- **A3** — `alacritty.py` ignores `CLAUDE_CONFIG_DIR` and broadcasts SIGWINCH to every `pgrep -f claude` match. Unchanged. Consider marking optional / hardening.

### Bigger phases (not started)
- **Phase 3** compiled hot path (Rust recommended for Swift FFI synergy) — no Rust/Go code on the branch.
- **Phase 4** background collector + computed-stats JSON — no daemon/computed artifact; only the raw payload is persisted.
- **Phase 5** native macOS app (SwiftUI viewer of Phase 4 stats) — no Swift/Xcode project. Commit `281c289` references a future "Vantage" Swift port mirroring `transcript.py`, but no app code exists.

### Honest uncertainty
- **Commit count:** measured **20** ahead of `origin/main` this session; the brief said 21. Re-run `git rev-list --count origin/main..HEAD` before writing PR copy.
- **C1 Fast-mode 6x** and **S5 `async:true`**: both flagged "verify separately" by the research; neither was confirmed this session.
- The full suite was **545 passed** via direct `python3 -m pytest -q` here; the per-commit "509→529" figures come from commit bodies, not re-measured per commit this session. The session brief also notes one parallel reader could **not** run the suite (no `uv`/`.venv` on their shell) — the 545 here was the direct-pytest run, treat it as the authoritative count.

---

## 8. Conventions & gotchas

### Conventions
- **Stdlib-only.** `pyproject.toml` `dependencies = []`. Dev tools (mypy/pytest/ruff/uv) live in `[dependency-groups].dev`. **Do not add third-party imports to `claude/`.**
- **Python 3.10+** (`requires-python = >=3.10`, ruff `target-version = py310`). Uses `X | Y` unions and `from __future__ import annotations`.
- **Style:** line length 140, 4-space indent. Ruff lint selects only E4/E7/E9 + F; **E401 and E701 are explicitly ignored and unfixable** — the codebase deliberately uses `import a, b` and one-line `if x: y`. Single quotes enforced via flake8-quotes; `ruff format` uses `quote-style = preserve` (it won't flip quotes — write single yourself). Aligned-assignment column style is common and preserved.
- **mypy strict** (`strict = true`, `disallow_untyped_defs`, `warn_return_any`, …). All production functions need annotations. **`test/`, `openspec/`, `.claude/`, `.venv/` are excluded** — production `claude/` is strict-typed; tests are NOT mypy-checked (they freely use `# type: ignore[no-untyped-def]`).
- **Terminology (governed by `CONTEXT.md`):** "Billed Input" (not "input tokens"), "Cache Read" (not "cache hits"), "Compaction-Risk Zone" (not "context full"), "Theme" (not "palette"), "Shift"/"Anchor" for gradient endpoints, "Task"/"Task Row" (not "todo"). Match exactly in code, comments, PRs.
- **ADRs** under `docs/adr/` (0001 thinking-level bg fill, 0002 theme system, 0004 task-progress row). Cite/update them for behavior changes to those subsystems.
- **Git hooks:** `make hooks` opts in to `core.hooksPath=.github/hooks` (pre-commit = the CI checks). `conftest`'s `pytest_report_header` nudges contributors who haven't enabled them (silent on CI/xdist).

### Gotchas
- **`.ansi` snapshot fixtures** (`test/fixtures/claude_dark_{narrow,medium,wide}.ansi`) are RAW ANSI byte-identity baselines consumed ONLY by `test/test_themes.py::test_claude_dark_byte_identity`. They contain ESC sequences + box-drawing/glyph bytes (don't `cat` them blindly). On first run the test writes the fixture and skips; thereafter it asserts byte equality. To re-baseline **intentionally**, delete the fixture and re-run. Only claude-dark × 3 layouts are pinned (light/Catppuccin have none by design). They drifted on this branch because rendered bytes changed (context-line/cost).
- **Snapshot determinism** depends on the `frozen` fixture: it patches `statusline.clock.now` to a fixed datetime and `sl.time.time` to `FROZEN_EPOCH` so countdowns and rainbow phase don't drift. Patch **`clock.now`**, not per-module `datetime`. It also needs `tmp_home` so day-token totals from `CLAUDE_DIR/statusline-tokens.log` resolve to 0.
- **conftest sandbox:** `tmp_home` monkeypatches `statusline.config.HOME` and `statusline.config.CLAUDE_DIR` — **NOT `sl.HOME`/`sl.CLAUDE_DIR`** (that binding was removed in Phase 2). Every module reads `config.X` dynamically. Any test touching token logs, scan state, subagents, theme, or git cache MUST use `tmp_home` or it writes to the real `~/.claude`. `test_transcript_scan` and `test_token_log` assert nothing is written outside the sandbox.
- **Module-global caches reset on the SUBMODULE, not via `sl`:** the scan cache is `sl.transcript._SCAN_CACHE` (set to `None` before each scan); `TokenLog`'s writer is `accounting._atomic_write_text` (patch on `accounting`, not `sl`). Assigning to `sl._SCAN_CACHE` only rebinds `sl`'s namespace and silently breaks the test. Also clear `CLAUDE_DIR/statusline-scan` between incremental runs and `CLAUDE_DIR/statusline-git` for the dirty cache.
- **Nerd Font PUA glyph hazard** (`test_glyphs.py`): default glyphs MUST render in any monospace font. Forbidden by default = PUA (U+E000–F8FF, U+F0000–FFFFD), Supplemental Arrows-C (U+1F800–1F8FF), Symbols for Legacy Computing diagonals (U+1FB00–1FBFF), emoji (U+1F300–1FAFF) — they show as `?`/tofu. PUA glyphs are gated behind `YAS_NERD_FONT=1` (`sl._NERD_FONT`). `GLYPH_FOLDER` default is `●`, not the PUA folder glyph. **The regression that motivated the file:** scanning only the static example render missed the active token in/out arrows and the rate sparkline's second row — any new glyph must be exercised in an ACTIVE/multi-row render, not just the static example.
- **Incremental scan parity sweep** (`test_transcript_scan.py`) only works because the test transcript is pure ASCII (1 char == 1 byte), so a character cut index equals the byte offset. **Adding multibyte content to those fixtures breaks the every-byte-boundary sweep.** Incremental tailing is enabled only for transcripts under `CLAUDE_DIR/projects` (`sl._incremental_enabled`); loose paths and `YAS_NO_INCREMENTAL=1` force full scans and write no state.
- **`make demo` is a HUMAN visual check, not an assertion.** It animates hermetic scenarios (synthetic `~/.claude`, `$HOME` repointed, no residue). Use it to eyeball glyphs/gradients/border-elbow math/subagent layout after touching the renderer; `make demo/img` writes static snapshots.
- **`test_from_cwd_real_repo`** (`test_git_info.py`) is guarded by `@pytest.mark.skipif(shutil.which('git') is None)`. The git-dirty-cache tests deliberately monkeypatch `sl.subprocess.run` to raise if git is spawned, proving a fresh cache avoids the subprocess — **keep that invariant when editing `git.py`.**
- **Doc/behavior mismatch to flag:** `CONTEXT.md` says the skills/plugins row "is always rendered" showing `*none*` when empty, but `Renderer.plugins_skills(0,'','')` returns `''` (`test_plugins_skills_nothing`). The `*none*` placeholder is added by a higher layout layer, not the row method — don't assume the method alone enforces that invariant.

---

## Post-handoff update — audit remediation (supersedes "outstanding" items above)

This handoff was written at the 20-commit branch state. Since then, six audit
clusters (see `AUDIT-2.md` "Remediation status") were implemented on this branch
with tests, each verified green (595 tests pass, ruff clean, mypy --strict clean):
`edc009c` security hardening (SEC-1/SEC-2/ROB-1/NAN), `caa5a36` input-only context %
(DATA-1/2/3 + CTX-NEG, refines C3/UX1), `11f8448` COLUMNS-first width (WIDTH-1 +
PERF-TMUX, refines P4), `160941e` mon CLAUDE_CONFIG_DIR (MON-1, the O4 class),
`1615e83` wide-char/overflow (CWIDTH/CTRUNC/MODELW), `e850345` openspec archive
filter (OS-ARCHIVE, refines P6). Still open: DATA-4, DATA-5, ACCT-1, the Low/Info
batch, and TRN-1 (skipped pending `/compact` rewrite confirmation).
