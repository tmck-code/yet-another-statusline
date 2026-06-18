## Update (2026-06-19) — lazy imports implemented + Python 3.15

The conditional-import deferrals (IMP-1/2/3 below) were implemented and verified on **Python 3.15.0b1**. All **1047 tests pass**.

**Changes made:**
- `render/text.py` — `subprocess` deferred into `terminal_width()` behind a `$TMUX_PANE` guard; `shutil.get_terminal_size` replaced with `os.get_terminal_size` (kills the `bz2`/`lzma`/`zlib` pull).
- `info/git.py` — `subprocess` deferred into `_dirty()`.
- `config.py` — `tomllib` deferred into `_load_toml()`, imported only after a `yas.toml` read succeeds.
- `tokens.py` — `TokenRate.WINDOW` was evaluated at **import time** (`= _token_window()`), forcing a full `Config.load()` (and, with a `yas.toml`, `tomllib`) into every startup. Made lazy + `@functools.cache`d. This is what lets the `tomllib` deferral actually land.
- Tests updated to not couple to removed module-level names (`config.tomllib`, `git.subprocess`): `test_config.py` uses `importlib.util.find_spec`/`sys.modules` patching; `test_git_info.py` patches the shared `subprocess` module.

**Result — `import yas.app` now pulls none of `subprocess`/`shutil`/`tomllib`.** Wall-clock (best-of-50 median, full invocation):

| Scenario (Python 3.15) | Before | After | Δ |
|---|---|---|---|
| No-tmux + no `yas.toml` (clean machine — full deferral) | 47.0 ms | **39.8 ms** | **−7.2 ms (−15%)** |
| This box (tmux + `yas.toml` — both still load at *runtime*) | 54.7 ms | **51.3 ms** | −3.4 ms |

`import yas.app` cumulative (`-X importtime`): **28.6 ms → 21.8 ms (−6.8 ms)**.

Notes:
- On tmux machines `subprocess` still loads — but now at *runtime* (the tmux width probe genuinely needs it), not on every import.
- With a `yas.toml` present, `tomllib` still loads (the file must be parsed) — but now lazily at render time, not at import. Machines without a `yas.toml` skip it entirely.
- **Python 3.15 is itself much faster** than the original 3.13 baseline (~70 ms → ~47–55 ms), partly because 3.15's `dataclasses` lazy-loads `inspect` (the ~5.5 ms `dataclasses→inspect→ast/dis` chain in IMP-4 is largely gone on 3.15 — that recommendation is now low-value).

Remaining opportunities unchanged: the render-side token-log triple-read (REN-1) and `Config.load()` memoisation (REN-3) below.

---

# Statusline CPU profiling — findings & recommendations

**Date:** 2026-06-19
**Target:** `cat ops/session-info-example.json | python3 claude/statusline_command.py`
**Baseline wall time:** ~70 ms (best-of-5, warm bytecode cache)
**Tooling:** `cProfile` (two scopes) + `python -X importtime` + wall-clock sampling. Harness: `ops/profile_statusline.py`. Raw artifacts in `ops/profile-out/`.

---

## TL;DR

> **The render is not slow. The startup is.**

| Phase | Time | Share |
|---|---|---|
| Bare interpreter startup (`python -c pass`) | ~10 ms | 14% |
| `import yas.app` (the whole package + stdlib it drags in) | ~50 ms | 71% |
| Actual `render()` work | ~3 ms | 4% |
| stdin parse + payload write + misc `main()` I/O | ~few ms | ~11% |

Optimising the rendering code (gradient math, borders, layout) would chase **3 ms**. The real budget is **import time (~50 ms)**. Effort should go there first.

Supporting measurement: removing the bytecode cache pushes the run to **110 ms** (cold) vs **60 ms** (warm) — the existing module-split-for-`.pyc` strategy already saves ~50 ms and is working as intended. The remaining 50 ms of warm import is what's addressable.

---

## Methodology

`ops/profile_statusline.py` profiles two scopes so import cost and render cost don't blur together:

- **`full`** — imports `yas.app` *inside* the profiled region, then one `render()`. Captures per-module import cost.
- **`render`** — warms imports/caches outside the profiled region, then `render()` × 200. Isolates steady-state render cost. Reports wall-clock ms/call alongside cProfile (cProfile inflates absolutes ~2×, so render findings quote *share of profiled run*, not raw ms).

Run them with:
```bash
cat ops/session-info-example.json | python3 ops/profile_statusline.py full
cat ops/session-info-example.json | python3 ops/profile_statusline.py render
cat ops/session-info-example.json | PYTHONPATH=claude python3 -X importtime claude/statusline_command.py >/dev/null 2> importtime.txt
```

Caveat on estimates: import savings below are derived from `-X importtime` *cumulative* numbers, which undercount real wall cost (they exclude some import-machinery overhead). Treat every "est. saving" as directional and **re-measure after each change** with the harness.

---

## Import & startup overhead  *(the 71% — do this first)*

The entire render path is imported eagerly through `yas/app.py` → `yas/config.py`, `yas/info/*`, `yas/layout.py`. Heavy stdlib pulls and who first triggers them:

| stdlib module | cum. import | first pulled by (file:line) | used | deferrable? | est. saving |
|---|---|---|---|---|---|
| `dataclasses` → `inspect` (+`ast`,`dis`,`tokenize`) | ~5.5 ms | every module via `from dataclasses import dataclass` (`themes.py:11`, `session.py:14`, …) | **always** (15+ `@dataclass` users) | only by dropping dataclasses | ~5.5 ms (structural) |
| `tomllib` (+`_parser`/`_re`/`_types`,`string`) | 4.3 ms (~2.8 ms net) | `config.py:17` (`try: import tomllib`) | **conditional** — only when `yas.toml` exists (`config.py:190`) | **yes** | ~2.8 ms (no `yas.toml`) |
| `json` | 5.0 ms | `config.py:14`, `app.py:3` | **always** (parses stdin) | no | 0 |
| `re` | 3.9 ms | `constants.py:5` (`_ANSI_RE`) + via `json`/`tomllib` | **always** | no | 0 |
| `subprocess` (+`threading`,`signal`,`selectors`,`locale`) | 2.1 ms | `render/text.py:6`, `info/git.py:2` | **conditional** — tmux probe (`text.py:23`, only if `$TMUX_PANE`); git shell-out (`git.py:87`) | **yes (both sites)** | ~2.1 ms (non-tmux / non-git) |
| `shutil` (+`bz2`,`lzma`,`zlib`) | 1.2 ms | `render/text.py:5` | **conditional** — only `shutil.get_terminal_size` (`text.py:45`), a 4th-choice fallback | **yes → `os.get_terminal_size`** | ~1.2 ms |
| `pathlib` | 1.9 ms | `constants.py:6` (`CLAUDE_DIR`) | **always** | no | 0 |
| `typing` | 1.7 ms | `config.py:23` (`TypeVar`), `session.py:17` (`NamedTuple`), via `tomllib` | **always** (runtime use) | no | ~0 |
| `enum` | 2.7 ms | via `re` | **always** (transitive) | no | 0 |

**Confirmed facts**
- In this Python 3.13, `dataclasses` does a top-level `import inspect`, so *every* `@dataclass` user transitively drags in `inspect`→`ast`→`dis`→`tokenize` (~4.5 ms). Locked in as long as any module uses `@dataclass`.
- `from __future__ import annotations` is present in the modules checked — so dataclass *annotations* aren't evaluated; the `inspect` cost is `dataclasses` itself, not annotation eval.
- `_load_toml` (`config.py:177`) reads the file *before* it needs `tomllib`, so the import can move after a successful read.
- Separately from import cost: `terminal_width()` (`text.py:21`) does a real `subprocess.run(["tmux", …])` fork/exec on **every** invocation when `$TMUX_PANE` is set. Not visible in the render profile (runs in `main()`), but it's runtime cost worth a follow-up.

### Recommended changes (ordered by win/effort)

1. **Defer `subprocess` in both `text.py` and `git.py`** — ~2.1 ms, low effort, safe.
   Move `import subprocess` out of module top-level and into the functions that shell out (`terminal_width()` near `text.py:22`; the git function around `git.py:87`). **Must be done at both sites** — one remaining top-level import keeps the module loaded.

2. **Replace `shutil` with `os.get_terminal_size`** — ~1.2 ms, low effort, safe.
   Delete `import shutil` (`text.py:5`); at `text.py:45`:
   ```python
   try:
       w = os.get_terminal_size().columns
   except OSError:
       w = 0
   ```
   `os` is already imported. Drops the `bz2`/`lzma`/`zlib` pulls `shutil` drags in.

3. **Defer `tomllib` into `_load_toml`** — ~2.8 ms when no `yas.toml`, low-medium effort, safe.
   Remove the top-level `try: import tomllib` (`config.py:16-19`); import it locally *after* the file read succeeds (`config.py:183-190`):
   ```python
   try:
       text = (config_dir / 'yas.toml').read_text()
   except OSError:
       return {}, None
   try:
       import tomllib
   except ImportError:        # Python 3.10
       return {}, None
   try:
       data = tomllib.loads(text)
   except (tomllib.TOMLDecodeError, ValueError):
       return {}, 'yas.toml: parse error'
   ```
   Users without a `yas.toml` never pay the parser/regex cost. (`typing`/`re` stay — needed by `TypeVar`/`_ANSI_RE` regardless.)

4. **(Structural, high effort, ~5.5 ms) Eliminate `dataclasses`.** Single largest lever, but touches 15+ modules (`themes`, `session`, `config`, `tokens`, `layout`, `render/pill`, `render/tasks_view`, all of `info/*`). Replace `@dataclass` with hand-written `__init__` classes (ideally `__slots__`) — removes the `dataclasses`→`inspect`→`ast`/`dis`/`tokenize` chain *and* the per-import decorator-exec cost (a big part of `themes` self=2.5 ms, `session` self=2.4 ms). Do it incrementally, hottest modules first, measuring each. **Do not** swap to `NamedTuple` (needs `typing`, similar decorator cost) — plain classes are cheapest. ⚠️ This conflicts with the skill's heavy reliance on dataclass views; weigh maintainability vs. the 5.5 ms.

5. **(Low priority) PEP 562 lazy submodule loading in `yas/info/__init__.py`.** `info/__init__.py` eagerly imports all readers (`git`, `workflows`, `subagents`, `tasks`, `transcript`, `openspec`, `skills`) — ~5 ms self + their `subprocess`/`re` pulls. A narrow render reads only a subset. A module-level `__getattr__` importing each reader on first access lets narrow/medium renders skip what they never touch. Medium effort; interacts with #1 (git) and the existing `SessionView` `@cached_property` seam (which gates *gathering* but not *importing*).

**Realistic total:** changes 1–3 are safe, mechanical, and recover **~6 ms** (~70 → ~64 ms) on the common no-`yas.toml`, non-tmux path. #4 adds ~5.5 ms but is a real refactor. #5 helps narrow/medium renders most. Floor is dominated by the unavoidable: interpreter (~10 ms) + `json`/`re`/`pathlib`/`enum` + executing the package's class definitions.

---

## Render runtime & per-invocation I/O  *(the 4% — only after imports)*

Render is genuinely cheap (~3 ms/call). The largest lever inside it is the **token-rate log**, read + parsed (and in `update`, rewritten) on *every* render — and read **three** separate times by three methods. cProfile absolutes are ~2× inflated, so shares of the profiled run are quoted.

| function | cum% | calls/render | note |
|---|---|---|---|
| `tokens.py:181 border_separator_dim` *(borders)* | 18.4% | 2 | per-column paint; `_dim_for_col` 320×/render |
| `tokens.py:143 TokenRate.update` | 15.7% | 1 | reads, parses **and rewrites** the rate log every render |
| `borders.py:175 _dim_for_col` | 11.2% | 320 | `min(abs(col-e) for e in elbow_cols)` per column |
| `tokens.py:178 TokenRate.history` | 9.2% | 1 | re-reads + re-parses the **same** rate log |
| `tokens.py:218 TokenRate.recently_active` | 9.2% | 1 | re-reads + re-parses the **same** rate log a 3rd time |
| `config.py:238 Config.load` | 8.9% | 1 | re-parses `os.environ` + re-reads `yas.toml` |
| `text.py:76 _visible_width` | 7.2% | 16 | `_ANSI_RE.sub` + per-char `_is_wide` genexpr |
| `gradient.py:178 grad_at` | 5.3% | 615 | per-column ANSI build |
| `{str.split}` | 5.3% | ~1500 | almost all from log-line parsing |

The three `TokenRate` methods + `TokenLog.update` are **~37% of render** — almost all spent reading and string-parsing on-disk logs. `str.split` and pathlib stat/open churn are downstream of the same reads.

### Recommendations (ordered by win/effort)

1. **Read the token-rate log once, parse once.** `TokenRate.update` (`tokens.py:144`), `.history` (`:178`), `.recently_active` (`:218`) each independently `read_text().splitlines()` + per-line `.split()` on the **same** file. Parse rows once (a small cached helper → `list[tuple]`), share them across all three. Eliminates 2 of 3 reads and ~2/3 of `str.split`; collapses ~33% of render to ~11%. **Biggest render win, low risk.**
2. **Don't rewrite the rate log in the hot read path unless it changed.** `TokenRate.update` (`tokens.py:163-168`) `write_text`s the whole log every render. With #1, write once at end of tick; skip the rewrite if the new sample equals the last.
3. **Compute the rate buckets in one pass.** Once rows are parsed once, `update`/`history`/`recently_active` can share one sorted, session-filtered list instead of each re-filtering/`.sort()`-ing (`tokens.py:170`, `:201`, `:226`).
4. **Cache `Config.load()` for the process lifetime.** `config.py:238` re-reads `yas.toml` + rebuilds from `os.environ` each call; config can't change mid-process. Memoise per `(config_dir, argv)`. Also removes the duplicate call — `render()` (`app.py:43`) and `main()` (`app.py:73`) both load it. ~9% off render.
5. **Hoist `_dim_for_col` out of the inner column loop** (`borders.py:175`, 320×/render, up to 18% via `border_separator_dim`). `elbow_cols` is fixed per border; precompute a `width`-length dim array once per call instead of recomputing per column. Caps a cost that **grows with terminal width**. Contained to `render/borders.py`.
6. **Minor — `_visible_width` fast path** (`text.py:76`, 7.2%): return `len(s)` when `'\033' not in s and s.isascii()`, skipping the regex and wide-char scan for plain-ASCII fragments. Only worth it if 1–5 land and it climbs the profile.

### Per-invocation I/O in `main()` (once per real run, not in the render loop)

7. **Statusline-output payload write** (`app.py:84-90`): `mkdir` + `json.dumps(info)` + `write_text` every invocation, purely for the `mon` observer. Sub-ms; **negligible vs ~50 ms import — not worth optimising for speed.** If ever desired, skip `mkdir` when the dir is known to exist, or gate behind "observer running".
8. **`stdin.read()` + `json.loads`** (`app.py:77`): unavoidable, ~0.05 ms. No action.

**Bottom line for render scope:** #1–#4 remove roughly half of the 3 ms render and a chunk of pathlib churn; #5 is a width-scaling safeguard. None of it dents the dominant import cost.

---

## Suggested order of work

1. **Import deferrals #1–#3** (subprocess, shutil, tomllib) — ~6 ms, safe, mechanical. Best ROI. Re-measure with the harness after each.
2. **Render log-read collapse #1–#4** — halves render and cuts FS churn; cheap and self-contained even if absolute ms is small.
3. **`border` width-scaling fix (#5)** — matters more on wide terminals.
4. **Decide on the dataclasses refactor (#4)** — biggest single import lever (~5.5 ms) but a real project with maintainability trade-offs; only if the ~64 ms floor is still unacceptable.

**Don't bother with:** the payload write, stdin parse, or micro-tuning gradient/`_visible_width` until the above land — they're in the noise next to import cost.
