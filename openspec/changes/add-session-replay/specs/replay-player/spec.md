## ADDED Requirements

### Requirement: Frames render through unmodified yas

`play` SHALL render every frame by invoking the production statusline as a
subprocess — `[sys.executable, claude/statusline_command.py]` — with the frame's
rebuilt payload on stdin, exactly as `ops/demo.py`'s `render_once` does. The
renderer SHALL NOT gain any replay-specific code path, flag, or environment
switch. The subprocess environment SHALL set `HOME` and `CLAUDE_CONFIG_DIR` to
the hermetic temporary world, SHALL set `COLUMNS` to the resolved render width,
and SHALL remove `TMUX_PANE`, because the width probe consults tmux before
`COLUMNS` and would otherwise override the pinned width.

#### Scenario: Production entry point is used

- **WHEN** a frame is rendered
- **THEN** `claude/statusline_command.py` is executed as a subprocess with the
  frame payload on stdin, and its stdout is the frame

#### Scenario: Renderer has no replay awareness

- **WHEN** the change is implemented
- **THEN** no module under `claude/` refers to replay, keyframes, or the player

#### Scenario: TMUX_PANE is removed from the child environment

- **WHEN** `play` runs inside tmux
- **THEN** the child process does not see `TMUX_PANE`, and renders at the pinned
  `COLUMNS` width

### Requirement: Per-frame hermetic world synthesis

`play` SHALL build one hermetic temporary `$HOME` at startup and, for each frame,
overwrite within it the transcript, subagent cohort, and token-rate log
reconstructed from that frame's blob columns, then rewire the frame payload's
`cwd`, `workspace`, and `transcript_path` to point into that temporary tree. Each
frame's world SHALL reflect only that frame's state: the subagent cohort
directory SHALL be cleared of stale agent files before writing, so state does not
accumulate across frames. The temporary tree SHALL be removed on exit, including
on error and on interrupt, leaving no residue.

#### Scenario: World is rebuilt, not accumulated

- **WHEN** frame 40 has fewer subagents than frame 39
- **THEN** frame 40 renders exactly its own cohort, with no leftover agents from
  frame 39

#### Scenario: Paths are rewired into the temp tree

- **WHEN** a frame payload is prepared
- **THEN** its `transcript_path`, `cwd`, and `workspace` point inside the
  temporary `$HOME`, never at the user's real project

#### Scenario: No residue on exit

- **WHEN** `play` exits, whether normally, by `q`, by error, or by interrupt
- **THEN** the temporary directory has been removed

### Requirement: Synthesised state and its accepted gaps

The player SHALL reconstruct, from the keyframe blobs: the task checklist, the
subagent cohort (types, descriptions, parents, tokens, models, lifecycle status),
tool counts, the token-rate log, and a git repository reporting the frame's
`git_branch`. Fidelity SHALL be a faithful reconstruction, not a byte-exact
reproduction, where the synthetic writers cannot express a transcript detail. The
openspec, skills, and plugins sections SHALL render empty, because the recording
does not capture the live disk state those readers scan; this SHALL be documented
as a known v1 gap rather than faked.

#### Scenario: Task and subagent state appear

- **WHEN** a frame's blobs describe three tasks and two running subagents
- **THEN** the rendered frame shows that checklist and that cohort

#### Scenario: Branch is reproduced

- **WHEN** a frame's `git_branch` is `feature/x`
- **THEN** the rendered frame's git section shows `feature/x`

#### Scenario: Unrecorded sections render empty

- **WHEN** any frame is rendered
- **THEN** the openspec, skills, and plugins sections are empty, and this is
  documented as a known limitation

### Requirement: Width is recorded, clamped, and overridable

`play` SHALL render at the width recorded in each frame. When the current
terminal is narrower than that width, it SHALL clamp to the current terminal
width and SHALL print a one-line warning naming both widths **before** entering
the alternate screen. `--width N` SHALL force a fixed width for every frame, and
`--width current` SHALL follow the live terminal width, updating on resize.
Clamping SHALL NOT apply when a width is forced.

#### Scenario: Recorded width is used when it fits

- **WHEN** the recorded width is 120 and the terminal is 200 columns
- **THEN** frames render at 120

#### Scenario: Narrower terminal clamps with a warning

- **WHEN** the recorded width is 200 and the terminal is 120 columns
- **THEN** frames render at 120 and a warning naming both widths is printed before
  the alternate screen is entered

#### Scenario: Explicit width wins

- **WHEN** `--width 90` is given in a 200-column terminal replaying 120-column
  frames
- **THEN** every frame renders at 90 and no clamping warning is printed

#### Scenario: Current width follows the terminal

- **WHEN** `--width current` is given and the terminal is resized mid-playback
- **THEN** subsequent frames render at the new terminal width

### Requirement: Playback clock uses real timestamps with speed and gap capping

Frame scheduling SHALL be driven by the real inter-frame gaps recorded in the
`ts` column. Each gap SHALL be divided by a speed multiplier, default `10.0`,
and the result SHALL then be capped at a maximum wall-clock gap, default `2.0`
seconds, so long idle pauses are compressed while dense activity keeps its
relative rhythm. Both SHALL be configurable by flag. When a frame render takes
longer than its scheduled slot, the player SHALL drop frames to stay on the clock
rather than accumulate drift.

#### Scenario: Speed divides the gaps

- **WHEN** two frames are 20 real seconds apart and the speed is `10`
- **THEN** they are shown 2 wall-clock seconds apart

#### Scenario: Idle gap is capped

- **WHEN** two frames are 40 real minutes apart, at speed `10` with a `2.0` second
  cap
- **THEN** they are shown 2 wall-clock seconds apart, not 4 minutes

#### Scenario: Rhythm is preserved below the cap

- **WHEN** three frames are 1 and 4 real seconds apart at speed `1` with a `2.0`
  cap
- **THEN** the second interval is capped at 2 seconds while the first stays at 1

#### Scenario: Slow renders drop frames rather than drift

- **WHEN** a frame takes longer to render than its slot allows
- **THEN** the player skips ahead to the frame due at the current clock position

### Requirement: Seeking operates on session time

The `0`-`9` jump keys and the fixed-interval seeks SHALL be interpreted in
**session time** — position within the span from the first to the last frame
timestamp — not in playback time. A jump to `5` SHALL land at the frame nearest
50% of that span, regardless of how gap compression distorted wall-clock
progress. Seeking past either end SHALL clamp to the first or last frame.

#### Scenario: Percentage jump is a session-time position

- **WHEN** `5` is pressed in a session spanning one real hour
- **THEN** playback resumes at the frame nearest the 30-minute mark

#### Scenario: Compression does not distort jumps

- **WHEN** the session contains a long compressed idle stretch and `5` is pressed
- **THEN** the landing frame is still the one nearest the session's midpoint

#### Scenario: Seeks clamp at the ends

- **WHEN** a backward seek is issued while on the first frame
- **THEN** playback stays on the first frame and does not error

### Requirement: Player key map

While playing, the player SHALL respond to these keys:

| Key | Action |
| --- | --- |
| space | toggle pause / resume |
| left / right | seek -10s / +10s of session time |
| PgUp / PgDn (and up / down) | seek -1min / +1min of session time |
| `+` / `-` | double / halve the speed multiplier |
| `0`-`9` | jump to N x 10% of session time |
| `q` | quit |

Keys SHALL take effect while paused as well as while playing; seeking while
paused SHALL redraw the landed frame and remain paused. The terminal SHALL be put
into raw mode to read keys unbuffered and SHALL be restored on exit, including on
error and on interrupt.

#### Scenario: Space pauses and resumes

- **WHEN** space is pressed during playback
- **THEN** the clock stops on the current frame; pressing space again resumes from
  it

#### Scenario: Seek while paused redraws and stays paused

- **WHEN** right is pressed while paused
- **THEN** the frame 10 session-seconds later is drawn and playback remains paused

#### Scenario: Speed keys step by doubling

- **WHEN** `+` is pressed twice at speed `10`
- **THEN** the speed becomes `40`

#### Scenario: q exits cleanly

- **WHEN** `q` is pressed
- **THEN** the alternate screen is left, the terminal mode is restored, the temp
  world is removed, and the process exits zero

#### Scenario: Terminal is restored on error

- **WHEN** an exception is raised mid-playback
- **THEN** raw mode is undone and the alternate screen is left before the error is
  reported

### Requirement: Alternate screen with a one-line HUD

`play` SHALL run inside the alternate screen buffer, entering on start and
leaving on exit so the user's scrollback is untouched. It SHALL draw a single HUD
line at the bottom showing: the session clock position and total as
`hh:mm:ss/hh:mm:ss`, the current speed multiplier, a paused indicator when
paused, and a progress bar. `--no-hud` SHALL suppress the HUD line while leaving
playback otherwise identical. The player SHALL handle terminal resize and redraw
rather than corrupt the frame.

#### Scenario: Scrollback is preserved

- **WHEN** `play` exits
- **THEN** the terminal shows the content that was on screen before it started

#### Scenario: HUD reports position and speed

- **WHEN** playback is 90 seconds into a 10-minute session at speed 10
- **THEN** the HUD shows `00:01:30/00:10:00` and the speed `10`

#### Scenario: Pause is indicated

- **WHEN** playback is paused
- **THEN** the HUD shows a paused indicator

#### Scenario: HUD can be suppressed

- **WHEN** `--no-hud` is given
- **THEN** no HUD line is drawn and the frames play identically

#### Scenario: Resize is handled

- **WHEN** the terminal is resized during playback
- **THEN** the player redraws the current frame and HUD at the new size
