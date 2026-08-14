## ADDED Requirements

### Requirement: External tools are preflighted before any work

`export` SHALL verify that `ffmpeg` is present on `PATH` before rendering any
frame, and SHALL exit non-zero with a message naming the missing binary and how
to install it. The ImageMagick `magick` binary that `ops/ansi_png.py` needs SHALL
be checked in the same preflight. Neither `build` nor `play` SHALL require either
binary.

#### Scenario: Missing ffmpeg fails fast

- **WHEN** `export` runs with no `ffmpeg` on `PATH`
- **THEN** it exits non-zero naming `ffmpeg`, before rendering a single frame, and
  writes no output

#### Scenario: Missing magick fails fast

- **WHEN** `magick` is absent
- **THEN** the preflight reports it and no frames are rendered

#### Scenario: Other subcommands are unaffected

- **WHEN** `build` or `play` runs with neither binary installed
- **THEN** both work normally

### Requirement: Export is non-interactive and shares the player's clock

`export` SHALL apply the same clock rules as `play` — the recorded inter-frame
gaps divided by the speed multiplier and then capped at the maximum gap — to
determine each frame's duration in the output, so an exported video has the same
pacing as the interactive playback with the same flags. It SHALL read no
keyboard, enter no alternate screen, and require no terminal. It SHALL render at
the recorded width with no terminal-based clamping, since there is no terminal to
fit, and SHALL accept the same `--width` override.

#### Scenario: Same flags give the same pacing

- **WHEN** `export` and `play` are run over one file with identical speed and gap
  settings
- **THEN** each frame occupies the same duration in both

#### Scenario: Runs headless

- **WHEN** `export` runs with stdin and stdout not attached to a terminal
- **THEN** it completes normally

#### Scenario: Recorded width is not clamped

- **WHEN** the recorded width is 200 and the invoking terminal is 80 columns
- **THEN** frames are exported at 200 columns

### Requirement: Frames are rendered to fixed-canvas PNGs

Each frame SHALL be rendered from its ANSI text to a PNG via `ops/ansi_png.py`.
`ansi_png` SHALL expose an entry point that renders an ANSI **string** to a PNG
path, so the caller need not manage a temporary text file, with the existing
path-taking `render_png` retained as a thin wrapper over it. For export, every
frame PNG SHALL have identical pixel dimensions: the canvas SHALL be sized from
the largest frame in the sequence and smaller frames padded to it, anchored at the
top-left, rather than trimmed to content. Trimming, which yields per-frame sizes,
SHALL NOT be used for exports, because the video encoder requires a constant frame
size.

#### Scenario: String entry point exists

- **WHEN** a caller has an ANSI frame in memory
- **THEN** it can render it to a PNG path without writing an intermediate text
  file

#### Scenario: Existing path API still works

- **WHEN** `render_png(txt_path, png_path)` is called as before
- **THEN** it behaves as it did, delegating to the string entry point

#### Scenario: All frames share one canvas

- **WHEN** a sequence contains frames of differing width and height
- **THEN** every emitted PNG has the same dimensions, matching the largest frame,
  with the content anchored top-left

### Requirement: Container is selected by output extension

The output container SHALL be chosen from the `-o` path's extension: `.mp4` SHALL
produce H.264 with a pixel format that is playable in browsers and standard
players, and `.gif` SHALL produce a palette-optimised animated GIF. Any other
extension SHALL be rejected with an error listing the supported ones. The
intermediate PNG frames SHALL be written to a temporary directory that is removed
on completion, including on failure.

#### Scenario: mp4 output

- **WHEN** `-o session.mp4` is given
- **THEN** an H.264 mp4 is produced whose pixel format plays in standard players

#### Scenario: gif output

- **WHEN** `-o session.gif` is given
- **THEN** an animated GIF is produced using a generated palette

#### Scenario: Unknown extension is rejected

- **WHEN** `-o session.webm` is given
- **THEN** the command exits non-zero listing `.mp4` and `.gif`

#### Scenario: Frame scratch is cleaned up

- **WHEN** export finishes or fails
- **THEN** the temporary PNG directory is removed

### Requirement: The HUD is never exported

The playback HUD — session clock, speed, progress bar, pause indicator — SHALL be
a `play`-only affordance and SHALL NOT appear in any exported frame. Exported
frames SHALL contain the statusline output only.

#### Scenario: Exported frames carry no HUD

- **WHEN** any frame PNG from an export is inspected
- **THEN** it shows only the rendered statusline, with no clock, speed, or
  progress bar
