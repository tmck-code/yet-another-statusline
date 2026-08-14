## Why

YAS renders a rich picture of a session — context burn, token rate, task
checklist, subagent cohort — and then throws every frame away. When a session
goes sideways (a runaway subagent, a context cliff, a stalled task list) there is
no way to look at what the statusline *said* at the moment it happened, and no
way to show anyone else. `ops/demo.py` can only animate invented state, and
`claude/mon.py` only reads the single latest cached payload per session; nothing
in the repo turns a *real* session into something you can scrub through.

A recording tap costs one appended line per render tick and makes the whole
session replayable through the unmodified renderer — the same code path, at the
recorded width, on a real clock — and exportable to an mp4 or gif for a PR or a
bug report.

## What Changes

- **Recording tap in `claude/yas/app.py`** — opt-in, default OFF. When enabled,
  each render tick appends one line to
  `CLAUDE_DIR/yas/recordings/<session_id>.psv.gz`, as its own gzip member
  (concatenated members decompress as one stream, so appends need no rewrite).
  Line format is PSV with three fields:
  `<epoch timestamp> | <terminal width> | <verbatim minified stdin JSON>`.
  This is an append-style sibling of the existing overwrite-in-place payload
  cache at `CLAUDE_DIR/statusline-output/statusline.<session_id>.json`
  (`app.py:90-101`), which stays exactly as it is.
- **New config knob** — `[recording] enabled = false` in `yas.toml`, canonical
  env `YAS_RECORDING`, no CLI flag, resolved through the existing precedence
  chain in `claude/yas/config.py`.
- **New CLI `ops/replay.py`** with three subcommands:
  - `build <session-id | recording-path> -o session.psv` — fuses the recording
    with the session's transcript jsonl and subagent files into a self-contained
    **keyframe PSV**: one full-snapshot row per recorded tick, flattened payload
    fields under dotted column names plus JSON-blob columns for the non-scalar
    state (tasks, subagent tree, tool counts, token-rate series, `gitBranch`).
    Both inputs are **required**; a session with no recording, or whose
    transcript has been deleted, is an error and is explicitly out of scope.
  - `play session.psv` — an interactive alt-screen player. Per frame it
    synthesises a minimal transcript + subagent tree in a hermetic temp `$HOME`
    and pipes the frame's payload into **unmodified** yas as a subprocess
    (`claude/statusline_command.py`), exactly as `ops/demo.py` does. Real
    timestamps, a speed multiplier, idle-gap compression, a one-line HUD, and
    pause/seek/speed keys.
  - `export session.psv -o session.mp4` — the same clock, non-interactively,
    rendering each frame to PNG via `ops/ansi_png.py` and assembling with
    `ffmpeg`. `.gif` is selected by output extension. HUD excluded.
- **New `ops/synth.py`** — the hermetic-world writers currently living in
  `ops/demo.py` (`build_synthetic_env`, `write_transcript`, `write_subagents`,
  `write_settings`, `write_rate_log_with_peaks`, `render_once`, and their
  helpers) move to a shared module that both `demo.py` and `replay.py` import.
  `ops/demo.py` re-exports every moved name, so
  `test/test_cohort_visibility.py`'s direct imports keep working.
- **`ops/ansi_png.py` grows `render_png_from_str`** so a frame can be rendered
  without a caller-managed temp `.txt`, and grows a fixed-canvas mode so every
  exported frame has identical pixel dimensions (ffmpeg requires it; the current
  `-trim` gives per-frame sizes).
- **Makefile** — `make replay SESSION=<id>` builds then plays in one step.

Not breaking for users: the tap is default-off and the renderer is untouched.
**BREAKING (internal, ops only):** the demo writers' canonical home becomes
`ops/synth.py`.

## Capabilities

### New Capabilities

- `session-recording`: the opt-in per-tick recording tap, its on-disk location,
  the gzip-member append discipline, the PSV line format, and its
  never-break-the-render error posture.
- `replay-keyframes`: the `build` subcommand — required inputs, the keyframe PSV
  schema (dotted scalar columns plus JSON-blob columns), and how transcript
  state is time-sliced as of each tick.
- `replay-player`: the `play` subcommand — hermetic per-frame synthesis through
  unmodified yas, width resolution and clamping, the playback clock (speed +
  idle-gap cap + session-time seeking), the HUD, and the key map.
- `replay-export`: the `export` subcommand — ffmpeg preflight, fixed-canvas PNG
  frames, container selection by extension, and clock parity with `play`.
- `synthetic-world-writers`: `ops/synth.py` as the shared home of the hermetic
  `$HOME`/transcript/subagent writers, and the re-export contract that keeps
  `ops/demo.py`'s public names importable.

### Modified Capabilities

- `statusline-config`: adds the `[recording] enabled` knob and its `YAS_RECORDING`
  canonical env var to the resolved `Config`.

## Impact

- **Code:** `claude/yas/app.py` (tap), `claude/yas/config.py` +
  `claude/yas/constants.py` (knob + default), new `ops/replay.py`, new
  `ops/synth.py`, `ops/demo.py` (writers moved out, re-exported),
  `ops/ansi_png.py` (string + fixed-canvas entry points), `Makefile`.
- **Docs:** `yas.example.toml` (`[recording]` block), `README.md` config table,
  `CONTEXT.md` §Configuration and §Module map.
- **Tests:** `test/test_config.py` (knob precedence), `test/test_render_callable.py`
  (tap on/off, format, failure is non-fatal), new `test/test_replay_build.py`
  (keyframe schema + time-slicing), new `test/test_synth.py` (extracted writers),
  `test/test_ansi_png.py` (new entry point). `test/test_cohort_visibility.py`
  must keep passing unchanged.
- **Dependencies:** no new Python dependencies (stdlib `gzip`). `export` adds a
  hard external dependency on `ffmpeg` (checked up front, error if missing),
  alongside `ansi_png.py`'s existing ImageMagick `magick` requirement.
- **Privacy:** recordings contain verbatim session payloads (cwd, model, cost).
  Default-off, written under `CLAUDE_DIR`, never uploaded, never pruned
  automatically in v1.
- **Known gap (accepted, v1):** openspec / skills / plugins sections render empty
  during replay, since the recording does not capture the disk state those
  readers scan.
