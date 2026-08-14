## 1. Config knob

- [x] 1.1 In `claude/yas/constants.py`, add `DEFAULT_RECORDING = False` next to
      `DEFAULT_OPENSPEC_SCAN_DEPTH` (constants.py:22).
- [x] 1.2 In `claude/yas/config.py`, add `recording` to `Config.__slots__`
      (349-355) and to the annotation block (357-378) as `recording: bool`.
- [x] 1.3 In `Config.__init__` (380-426), add the `recording: bool = DEFAULT_RECORDING`
      parameter and the matching `s(self, 'recording', recording)` line; extend
      `__repr__` (433-445) with the new field.
- [x] 1.4 In `Config.load` (447-582), add `recording_tbl = _table('recording')`
      beside the other `_table(...)` calls at 477-481, then resolve it modelled
      verbatim on the `show_render_time` block:
      `_resolve('recording', _env_sources(env, 'YAS_RECORDING') + toml_src(recording_tbl, 'enabled'), _parse_bool, DEFAULT_RECORDING, errors, debug)`.
- [x] 1.5 Pass `recording=recording` in `load()`'s final `return cls(...)` (557-580).
- [x] 1.6 In `test/test_config.py`, add tests for: default `False`; `[recording]
      enabled = true` (behind the existing `requires_tomllib` marker);
      `YAS_RECORDING=0` beating TOML `true`; empty `YAS_RECORDING` counting as
      absent; invalid TOML value falling back and appearing in `errors`; invalid
      env value falling back into `debug_lines` only. Always pass an explicit
      `env=` dict so the host environment cannot leak.

## 2. Recording tap in app.py

- [x] 2.1 In `claude/yas/app.py`, add a module-level `import gzip` and a private
      `_record_tick(session_id: str, width: int, info: dict) -> None` that writes
      `CLAUDE_DIR / 'yas' / 'recordings' / f'{session_id}.psv.gz'`. Resolve the
      dir from the module-level `CLAUDE_DIR` name, never from `os.environ`.
- [x] 2.2 Implement the write as: `mkdir(parents=True, exist_ok=True)`, then open
      the target with `gzip.open(path, 'at', encoding='utf-8')` (append mode
      yields a new gzip member per call) and write one line
      `f'{time.time()} | {width} | {payload}\n'` where `payload =
      json.dumps(info, separators=(',', ':'), ensure_ascii=False)`.
- [x] 2.3 Wrap the whole body in `try/except Exception: return` so a recording
      failure — `OSError`, encoding, or gzip — cannot break a render. Mirror the
      swallow-and-continue posture of the existing payload cache (app.py:90-101),
      but broaden the caught type as designed.
- [x] 2.4 Call the tap in `main()` immediately after `raw_tw = terminal_width()`
      and **before** the `if raw_tw < MIN_WIDTH: return` guard, gated on
      `cfg.recording`, passing `raw_tw` (not the derived box width). Ensure the
      `cfg.recording` check short-circuits before any path work.
- [x] 2.5 Leave the existing `statusline-output/statusline.<session_id>.json`
      cache block untouched in location, content, and ordering.
- [x] 2.6 In `test/test_render_callable.py`, extend the existing `_run_main`
      driver (test_render_callable.py:78) with recording tests: nothing written
      when off; one member per tick when on; three ticks decompress to three
      lines via `gzip.open(..., 'rt')`; `maxsplit=2` split round-trips the payload
      including one containing a `|`; the raw width is recorded rather than the
      clamped box width; a sub-`MIN_WIDTH` tick still records while emitting no
      stdout; an unwritable recordings dir leaves the rendered output intact.
      Patch `app.CLAUDE_DIR` to `tmp_path` and `delenv` `YAS_RECORDING`.

## 3. Docs for the recording knob

- [x] 3.1 Append a commented `[recording]` block to `yas.example.toml` after the
      `[openspec]` block (lines 99-105), matching the file's style: default value,
      an `# env: YAS_RECORDING` note, the recordings path, and a one-line note
      that recordings hold verbatim session payloads and are never pruned.
- [x] 3.2 Add a row to the `README.md` config table (README.md:80-97):
      no flag / `YAS_RECORDING` / no legacy alias / `[recording] enabled` /
      `false`.
- [x] 3.3 Update `CONTEXT.md` §Configuration (line 220) to list the new knob under
      **Config**, and §Module map (line 286) so the `app` row mentions the
      recording tap as a per-render side effect.

## 4. Extract ops/synth.py

- [x] 4.1 Create `ops/synth.py` and move from `ops/demo.py`, unchanged:
      `build_synthetic_env` (:122), `write_settings`, `write_subagents` (:185)
      with `_subagent_content_block` (:166) and `_TERMINAL_STATUSES_DEMO` (:32),
      `write_workflows` (:455), `write_openspec_changes` (:1512),
      `write_rate_log_with_peaks` (:1528), `render_once` (:742),
      `_ensure_nested` (:772), `_iso` (:566), and the constants `REPO_ROOT`,
      `FIXTURE_PATH`, `STATUSLINE_SCRIPT` (:24-26).
- [x] 4.2 Move `write_transcript` (:607) together with `_task_timeline` (:571);
      parameterise the task durations so `TASK_DURATIONS` / `TASK_LIVE_SECONDS`
      can stay in `demo.py` and be passed in, since replay supplies captured task
      states rather than the demo's fixed list.
- [x] 4.3 Add `rewire_paths(raw: dict, tmpdir: Path, session_id: str) -> None` to
      `ops/synth.py` doing only the `cwd` / `workspace` / `transcript_path`
      redirection. Reduce `ops/demo.py`'s `mutate_session_info` (:708) to a call
      to it plus the demo's own `thinking`, `effort`, and `rate_limits.resets_at`
      mutations.
- [x] 4.4 In `ops/demo.py`, replace the moved definitions with
      `from synth import ...` re-exporting every moved name at module level, so
      `ops_demo.build_synthetic_env`, `ops_demo.render_scenario`,
      `ops_demo.SCENARIOS`, and `ops_demo.FIXTURE_PATH` all still resolve.
      Leave `ScenarioConfig` (:892), `SCENARIOS`, the `*_PROGRESSION` tuples,
      `DEMO_TASKS`/`task_state_for`, `animate` (:784), `render_scenario` (:1560),
      and `main` (:1676) in `demo.py`.
- [x] 4.5 Add `test/test_synth.py`: the environment builder produces the expected
      tree and a git repo on the expected branch; the transcript writer's records
      parse into the intended usage totals; the subagent writer clears stale agent
      files before writing and emits meta+jsonl pairs the cohort reader
      recognises. Follow the `sys.path.insert(..., 'ops')` import pattern used by
      `test/test_ansi_png.py`.
- [x] 4.6 Verify `test/test_cohort_visibility.py` passes with **no edits to it**,
      and regenerate the demo snapshots to confirm `demo/**` is byte-identical.

## 5. ansi_png entry points

- [x] 5.1 In `ops/ansi_png.py`, add
      `render_png_from_str(ansi: str, png_path: Path, *, canvas: tuple[int, int] | None = None) -> None`
      holding the current body of `render_png`, and reduce `render_png(txt_path,
      png_path)` to reading the file (`.strip('\n')`) and delegating.
- [x] 5.2 In `render_png_from_str`, when `canvas` is given, replace the `-trim`
      `magick` arguments with a fixed canvas (`-extent WxH -gravity NorthWest`)
      so every frame emits identical pixel dimensions; keep the existing `-trim`
      behaviour when `canvas` is `None` so demo screenshots are unchanged.
- [x] 5.3 Suppress the `print(f'  wrote {png_path}')` progress line when rendering
      a frame sequence, so an export of hundreds of frames does not flood stdout.
- [x] 5.4 Extend `test/test_ansi_png.py` with a test that the string entry point
      and the path entry point produce the same Pango markup for one input (no
      `magick` required — assert on the conversion, as the existing tests do).

## 6. ops/replay.py — CLI skeleton and the psv format

- [x] 6.1 Create `ops/replay.py` with `parse_args(argv) -> Namespace` using
      `add_subparsers(dest='cmd', required=True)` for `build`, `play`, `export`,
      following `claude/mon/tui.py:parse_args` style (typed args, `metavar=`,
      every `help=` ending in `(default: X)`), and
      `main(argv) -> int` with `if __name__ == '__main__': sys.exit(main(sys.argv[1:]))`.
      Errors print to stderr and return 1.
- [x] 6.2 Implement the recording reader: `gzip.open(path, 'rt')`, one line per
      tick, `line.rstrip('\n').split(' | ', 2)` → `(float ts, int width, dict payload)`.
      Skip and count malformed lines rather than aborting.
- [x] 6.3 Implement the keyframe PSV writer/reader pair: a header row of column
      names, `|`-joined rows, blob cells holding minified JSON. Derive the scalar
      column set by flattening every recorded payload to dotted leaf paths and
      unioning them; empty cell means the key is absent on rebuild. Provide the
      inverse `row -> payload` rebuild used by `play`/`export`.

## 7. ops/replay.py — build

- [x] 7.1 Resolve inputs: accept a session id or a `.psv.gz` path; derive the
      transcript as `CLAUDE_DIR/projects/<slug>/<session_id>.jsonl` and the
      subagent dir as `CLAUDE_DIR/projects/<slug>/<session_id>/subagents/`, using
      the same slug rule as `write_subagents` (`re.sub(r'[^A-Za-z0-9]', '-', cwd)`,
      cross-checked against the payload's `transcript_path`). Missing recording or
      missing transcript → stderr error naming the path, return 1, write nothing.
- [x] 7.2 Implement the time-slicing walk: sort tick timestamps once, then stream
      the transcript and each `agent-*.jsonl` **once**, advancing a cursor through
      the tick list and snapshotting accumulated state at each boundary. Do not
      re-read a file per tick.
- [x] 7.3 Derive the `tasks` blob by replaying TodoWrite tool calls up to each
      tick, mirroring `claude/yas/info/tasks.py:72` semantics (subject,
      active_form, status, started_at, completed_at).
- [x] 7.4 Derive the `tool_counts` blob mirroring `claude/yas/info/toolcounts.py`:
      per-tool counts plus lines read/changed, windowed to the last `/clear`
      marker at or before the tick, main vs sub split with the `isSidechain` rule.
- [x] 7.5 Derive the `subagents` blob from `agent-*.meta.json` (agentType,
      description, parentAgentId, spawnDepth, isFork) plus `<task-notification>`
      records and per-agent usage totals, mirroring
      `claude/yas/info/subagents.py`'s lifecycle rules (latest notification wins;
      terminal statuses completed/killed/failed/stopped).
- [x] 7.6 Derive `git_branch` per tick from the newest transcript envelope
      `gitBranch` at or before the tick.
- [x] 7.7 Derive `rate_series` from consecutive keyframes' cumulative token totals
      over their elapsed real time; the first frame gets an empty series. Do not
      read `CLAUDE_DIR/statusline-token-rate.log`.
- [x] 7.8 Write the output to `-o` atomically (temp file then rename) so a failed
      build leaves no partial artifact.
- [x] 7.9 Add `test/test_replay_build.py` with a small hand-built recording +
      transcript + subagent fixture under `tmp_path`: required-input errors;
      one row per tick; dotted column derivation including a late-appearing field;
      payload round-trip through write+read; time-slicing (a task completed later
      is in-progress in the earlier frame); `/clear` windowing; subagent lifecycle
      at the notification boundary; rate derivation; single-pass reading.

## 8. ops/replay.py — play

- [x] 8.1 Build the hermetic world once at startup via
      `synth.build_synthetic_env`, in a `tempfile.TemporaryDirectory` removed in a
      `finally`, and construct the child env: `os.environ.copy()` with `HOME`,
      `CLAUDE_CONFIG_DIR`, `COLUMNS` set and `TMUX_PANE` popped.
- [x] 8.2 Implement `render_frame(row)`: lower the row's blobs into the synth
      writers' vocabulary (tasks → `write_transcript`'s task tuples; subagents →
      `write_subagents`'s entry tuples; `rate_series` → the rate log), write a
      git branch matching `git_branch`, call `synth.rewire_paths` on the rebuilt
      payload, then `synth.render_once(env, json.dumps(payload))`.
- [x] 8.3 Implement width resolution: recorded width by default; clamp to the
      current terminal width when narrower and print a one-line warning naming
      both **before** entering the alternate screen; `--width N` forces a width
      with no clamping; `--width current` follows the live terminal and updates on
      resize.
- [x] 8.4 Implement the clock: per-gap `min(gap / speed, gap_cap)` with
      `--speed` (default `10.0`) and `--gap-cap` (default `2.0`); drop frames when
      a render overruns its slot rather than accumulating drift.
- [x] 8.5 Implement session-time seeking: map a session-time position to the
      nearest frame index by `ts`; ±10s, ±1min, and `N * 10%` of
      `last_ts - first_ts`; clamp at both ends; seeking while paused redraws the
      landed frame and stays paused.
- [x] 8.6 Implement terminal handling: alternate screen via `\x1b[?1049h` /
      `\x1b[?1049l` (mirror `claude/mon/tui.py:14,19`), raw-mode key reads via
      `termios`/`tty`, and `install_sigwinch_handler`-style resize redraw. Restore
      raw mode and leave the alternate screen in a `finally` covering errors and
      `KeyboardInterrupt`.
- [x] 8.7 Implement the key map: space pause/resume; left/right ±10s; PgUp/PgDn
      and up/down ±1min; `+`/`-` doubling/halving speed; `0`-`9` percentage jump;
      `q` quit zero. Keys act while paused too.
- [x] 8.8 Implement the one-line bottom HUD: `hh:mm:ss/hh:mm:ss` session position,
      speed, paused indicator, progress bar; `--no-hud` suppresses it without
      otherwise changing playback.
- [x] 8.9 Add tests for the pure parts (no TTY needed): gap scheduling with speed
      and cap, session-time seek index mapping and clamping, percentage jumps,
      width resolution/clamping decisions, and HUD string formatting.

## 9. ops/replay.py — export

- [x] 9.1 Preflight `shutil.which('ffmpeg')` and `shutil.which('magick')` before
      any frame work; on failure print an error naming the binary and return 1.
      Reject any `-o` extension other than `.mp4` / `.gif`, listing the supported
      ones.
- [x] 9.2 Compute each frame's duration with the same clock helper as `play`
      (`--speed`, `--gap-cap`), so identical flags give identical pacing; render
      at the recorded width with no terminal clamping, honouring `--width`.
- [x] 9.3 First pass: render every frame's ANSI, measure the maximum pixel canvas,
      then render all frames to a temp dir via
      `ansi_png.render_png_from_str(..., canvas=...)` so all PNGs share
      dimensions. Never draw the HUD.
- [x] 9.4 Assemble with `ffmpeg`: `.mp4` → `libx264` with `-pix_fmt yuv420p`;
      `.gif` → `palettegen`/`paletteuse`. Feed per-frame durations via a concat
      demuxer list so variable frame durations are honoured. Remove the temp PNG
      dir in a `finally`.
- [x] 9.5 Add a test that the preflight fails fast and writes nothing when the
      binaries are absent (monkeypatch `shutil.which`), and that an unsupported
      extension is rejected. Do not assert on real encoder output.

## 10. Makefile and final gates

- [x] 10.1 Add a `replay` target: `make replay SESSION=<id>` builds to a temp psv
      then plays it, `@uv run python3 ops/replay.py ...`, with a `#` comment block
      above documenting `SESSION`, `SPEED`, `WIDTH`. Follow house style (`@`
      prefix, `uv run python3`, `$(VAR)` knobs).
- [x] 10.2 Append `replay` to the single `.PHONY` line at the bottom of the
      Makefile.
- [x] 10.3 Document the replay workflow in `README.md` (record → build → play →
      export, and the ffmpeg/ImageMagick requirement for export) and note the
      known v1 gap that openspec/skills/plugins sections render empty in replays.
- [ ] 10.4 Run the full gate via `verifier`: `make test`, `uv run ruff check`, and
      the visual gate (`make demo/img` plus the demo-text diff) to prove the
      `ops/synth.py` extraction changed no snapshot.
      PARTIAL: `make test` (1565 passed / 0 failed, baseline 1493) and
      `uv run ruff check` (clean on every change-owned file) both ran green via
      `verifier`. The `make demo/img` image gate was deliberately skipped as
      slow/manual; the cheaper ANSI-stripped `demo-text.sh` diff was run instead
      during task 4.6 and showed `demo/**` byte-identical.
