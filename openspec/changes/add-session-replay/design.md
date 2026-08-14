## Context

Three facts about the codebase shape this design.

1. **yas is a one-shot subprocess.** `claude/statusline_command.py` stamps
   `perf_counter()` and calls `yas.app.main(_T0)`; `app.py:88` reads one JSON
   object from stdin, renders once to stdout, and exits. Everything else it
   shows — token totals, tasks, subagents, tool counts, cache countdown — is
   read off disk from `transcript_path` and its sibling `subagents/` dir by the
   lazy readers behind `SessionView` (`claude/yas/info/__init__.py`). So the
   stdin payload alone is **not** enough to reproduce a frame; the transcript
   state at that instant is the other half.

2. **`ops/demo.py` already knows how to fake that other half.** It builds a
   hermetic `$HOME` (`build_synthetic_env` :122), writes a synthetic transcript
   (`write_transcript` :607) and subagent cohort (`write_subagents` :185),
   rewires the fixture's paths (`mutate_session_info` :708), and pipes it into
   the real statusline (`render_once` :742) with `HOME` and `CLAUDE_CONFIG_DIR`
   pointed at the tempdir and `COLUMNS` pinning the width. It has no global
   mutable state — every writer takes explicit paths — so those writers are
   cheap to share. What demo.py *lacks* is any notion of real captured input.

3. **Nothing captures input over time.** The payload cache at
   `CLAUDE_DIR/statusline-output/statusline.<session_id>.json` (`app.py:90-101`)
   is overwritten in place for `mon.py`; the transcript jsonl is append-only but
   carries no terminal width and no `cost.*` totals. Replay therefore needs a new
   append-only tap, and must fuse it with the transcript afterwards.

Constraints: stdlib-only in `claude/**` (CODING_STANDARDS.md); the tap lives in
`app.py`, the one place per-render side effects are allowed (`info/` is
read-only by layering rule); the recording must never be able to break a render.

## Goals / Non-Goals

**Goals:**

- Capture enough per tick, at negligible cost, to reconstruct a session's
  statusline frames later.
- Replay through **unmodified yas** — the renderer must not learn what a replay
  is. Fidelity comes from reconstructing its *inputs*, not from a special path.
- One CLI, three verbs, one intermediate artifact (`session.psv`) that is
  self-contained: after `build`, replay needs neither the original recording nor
  the original transcript.
- Share the hermetic-world writers with `ops/demo.py` rather than forking them.

**Non-Goals:**

- Replaying sessions that were not recorded. Reconstructing payload-only fields
  (`cost.total_cost_usd`, `context_window.used_percentage`, terminal width) from
  a transcript alone is guesswork; `build` errors out instead.
- Bit-exact reproduction. Where the synthetic writers cannot express a transcript
  detail, the frame is a faithful reconstruction, not a byte match.
- Openspec / skills / plugins sections. Those readers scan live disk state the
  recording does not capture; they render empty in v1.
- Editing, trimming, or annotating a recording. Retention/pruning of the
  recordings dir.
- Multi-session replay (the `mon.py` view).

## Decisions

### 1. Recording format: gzip-member-per-line PSV

Each tick appends **one complete gzip member** containing one PSV line. The gzip
spec allows concatenated members; `gzip.open(...,'rt')` and `zcat` both read the
concatenation as a single stream. That gives an append-only, crash-safe,
compressed log with no read-modify-write and no index — which matters because the
tap runs inside every render and must add ~a millisecond, not rewrite a file.

Line: `<epoch> | <terminal_width> | <minified payload JSON>` with `' | '` as the
separator. Only three fields, and the last one is the rest of the line, so a
parser splits with `maxsplit=2` and never has to escape the `|` characters that
occur inside the JSON. The JSON is written with `separators=(',',':')` and
`ensure_ascii=False`; it contains no raw newline by construction, so a line is a
record. **Alternative rejected:** JSONL with the width folded into the object —
it would mean re-serialising and mutating the captured payload, and the whole
point is that column 3 is byte-verbatim what yas was handed.

The recorded width is the raw `terminal_width()`, not the derived box width, so
the replayer can re-derive the box width with the same clamping rules.

### 2. Tap placement: after the payload cache, before the MIN_WIDTH early return

`app.py` returns early when `raw_tw < MIN_WIDTH` (a too-narrow terminal renders
nothing). The tap sits immediately after `raw_tw = terminal_width()` and **before**
that guard, so a session that spent time in a narrow pane still records those
ticks (with their real width) instead of a hole in the timeline.

It mirrors the payload cache's error posture — wrapped in `try/except`, swallowed,
never propagated — but catches `Exception`, not just `OSError`, because gzip and
encoding failures are also possible and a recording bug must not cost a user
their statusline. It resolves the directory from `app.py`'s module-level
`CLAUDE_DIR` (not from `os.environ`) so `test/conftest.py`'s `tmp_home` isolation
keeps working.

### 3. `build` produces keyframes, not deltas

Every row of `session.psv` is a **full snapshot** of everything a frame needs.
This makes seeking O(1) — jump to any row, render it, no replay of preceding
state — which is what the player's `0`-`9` percentage jumps and ±1min seeks need.
It costs file size; at one tick every few seconds with heavy repetition, gzip is
not applied to the built artifact in v1 and the file stays human-inspectable,
greppable, and diffable. **Alternative rejected:** a delta/journal format — smaller,
but every seek becomes a re-fold from the start and the format stops being
inspectable.

Schema: a header row of column names. Scalar payload fields are flattened with
dotted names taken verbatim from the payload's own structure
(`context_window.current_usage.input_tokens`, `cost.total_cost_usd`, `model.id`,
…), so the column set is derived, not hand-listed, and a payload gaining a field
gains a column. Non-scalar state gets JSON-blob columns: `tasks`, `subagents`,
`tool_counts`, `rate_series`. Plus `ts`, `width`, and `git_branch`.

`git_branch` comes from the transcript record envelope's `gitBranch`, which is the
only place it exists — the payload does not carry it.

### 4. Transcript-derived state is time-sliced, payload state is verbatim

For each tick at time *t*, the payload columns are copied straight out of the
recording (they are ground truth — yas was literally given them). The blob
columns are computed by walking the transcript and subagent jsonl files and
considering only records with `timestamp <= t`. That is exactly the semantics the
live readers have, since at real time *t* those were the only records on disk.

The walk is done **once**, streaming, with the tick timestamps sorted: one pass
over each file advancing through the tick list, rather than one pass per tick.
Task state replays TodoWrite calls (as `info/tasks.py:72` does); tool counts are
windowed to the last `/clear` (as `info/toolcounts.py` does); subagent state comes
from `agent-*.meta.json` plus the `<task-notification>` records (as
`info/subagents.py` does).

`rate_series` is derived from consecutive keyframes' cumulative token totals — the
live `~/.claude/statusline-token-rate.log` is not part of the recording, and
consecutive payloads already contain everything needed to reconstruct it.

### 5. `play` reconstructs inputs into a hermetic temp world

Per frame the player: writes the frame's transcript + subagent files into the temp
`$HOME` built once at startup, writes the rate log, rewires the payload's
`transcript_path`/`cwd`/`workspace` to the temp tree, and runs
`[sys.executable, claude/statusline_command.py]` with `HOME`,
`CLAUDE_CONFIG_DIR`, and `COLUMNS` set — and with `TMUX_PANE` **popped**, because
`terminal_width()` consults tmux before `COLUMNS` and would otherwise override the
pinned width (this is the same trick `render_scenario` uses at demo.py:1618).

`write_subagents` already deletes the cohort dir's regular files before writing,
so it is idempotent per frame — the temp world is rebuilt, not accumulated.

**Alternative rejected:** importing `yas.app` in-process and calling `render()`.
Faster, but it would bind replay to internal APIs and make the frame a different
code path from a real render. Subprocess-per-frame is the honest one, and at
~10x with a 2s gap cap the frame rate is low enough for it.

### 6. Extract the writers to `ops/synth.py`, re-export from `ops/demo.py`

`demo.py` keeps its scenario model, progression tuples, `animate`, and
`render_scenario`; the world-building primitives move. `test/test_cohort_visibility.py`
imports `ops_demo.build_synthetic_env` / `render_scenario` / `SCENARIOS` /
`FIXTURE_PATH` directly, so `demo.py` re-exports every moved name and that test
stays untouched. `mutate_session_info` is *not* moved verbatim — it hardcodes demo
editorial choices (`thinking.enabled`, `effort.level`, `rate_limits.resets_at`);
`synth.py` gets a narrower `rewire_paths` that only redirects
`cwd`/`workspace`/`transcript_path`, and demo.py's `mutate_session_info` calls it
and then layers its editorial fields on top.

### 7. Playback clock: session time is the master

Frames are scheduled by their real inter-keyframe gaps, divided by `speed`
(default 10.0), with every gap capped at `gap_cap` wall-seconds (default 2.0)
*after* the speed division — so a 40-minute think pause becomes 2 seconds, and
dense activity keeps its relative rhythm. Seeks and the `0`-`9` jumps operate on
**session time** (the position within `last_ts - first_ts`), not on playback
time, so "jump to 50%" means the middle of the session regardless of where the
compression put the wall clock. The HUD shows session clock position, which is
the number a user can correlate with their transcript.

### 8. Width: recorded, clamped, overridable

Render at the recorded width; if the current terminal is narrower, clamp to it and
print a one-line warning before entering the alt screen (a frame wider than the
terminal wraps and turns the box art into confetti). `--width N` forces a width;
`--width current` follows the live terminal. `export` uses the recorded width
with no clamping, since there is no terminal to fit.

### 9. `export`: fixed canvas, ffmpeg preflight

`ops/ansi_png.py`'s `render_png` takes a *path* and passes `-trim` to `magick`, so
frame PNGs currently vary in size — ffmpeg's image sequence input requires
constant dimensions. Two additions: `render_png_from_str(ansi, png_path)` (the
conversion core `ansi_to_pango` is already pure, so `render_png` becomes a thin
wrapper over it) and a fixed-canvas mode that pads to a caller-supplied
`(width, height)` with `-extent`/`-gravity NorthWest` instead of `-trim`. The
canvas is measured from the widest/tallest frame in a first pass.

`ffmpeg` is checked with `shutil.which` **before** any frame is rendered, and
missing means a clear error naming the binary — not a stack trace after five
minutes of PNG work. Container follows the output extension: `.mp4` →
`libx264 -pix_fmt yuv420p`, `.gif` → palettegen/paletteuse. The HUD is a player
affordance and is never drawn into an export.

### 10. One CLI module, `mon/tui.py`'s argparse style

`ops/replay.py` uses `add_subparsers(dest='cmd', required=True)` following
`claude/mon/tui.py:parse_args` (typed args, `metavar=`, every `help=` ending in
`(default: X)`), rather than `demo.py`'s single-flag `main()`. Terminal handling
mirrors `mon/tui.py` too: `\x1b[?1049h`/`\x1b[?1049l` for the alt screen and
`install_sigwinch_handler` for resize. Raw-mode key reading (`termios`/`tty`) is
new to the repo and lives only in `ops/replay.py`, restored in a `finally`.

## Risks / Trade-offs

- **Recording grows unbounded** → one line per tick, gzipped, ~1KB payload
  compressing well; no automatic pruning in v1. Documented in `yas.example.toml`;
  the dir is a flat `<session_id>.psv.gz` so `rm` is obvious.
- **Recordings contain verbatim payloads** (cwd, model, cost, project paths) →
  default-off, opt-in per user, written only under `CLAUDE_DIR`, never uploaded.
  Called out in the README knob row.
- **Tap adds work to the hot render path** → append-only single write of one
  small gzip member, after the payload cache write that already happens; no read,
  no index, no fsync. Guarded by a config check that short-circuits when off.
- **Synthesised frames are approximations** → accepted and stated: openspec,
  skills, and plugins render empty; tool-count and subagent detail are only as
  faithful as `write_subagents`/`write_transcript` can express. Replay is for
  reading the shape of a session, not for forensic byte comparison.
- **Subprocess-per-frame is slow** → bounded by the gap cap and speed multiplier;
  if a frame render outruns its slot the player drops frames rather than drifting.
- **External dependencies** (`ffmpeg`, ImageMagick `magick`) → confined to
  `export`; `build` and `play` need neither, and `export` preflights both.
- **`play` as a verb collides with `ops/f.sh play`** (the width-archive viewer) →
  accepted; different tool, different front door, and `make replay` is the
  documented entry point.
