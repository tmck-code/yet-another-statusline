## ADDED Requirements

### Requirement: Recording is opt-in and off by default

The recording tap SHALL be inert unless explicitly enabled. With no `yas.toml`
and no environment override, no recordings directory SHALL be created and no
file SHALL be written. When disabled, the tap SHALL short-circuit before any
path resolution, directory creation, serialisation, or compression work.

#### Scenario: Default configuration records nothing

- **WHEN** `main()` renders a tick with no `[recording]` section and no
  `YAS_RECORDING` in the environment
- **THEN** no `yas/recordings` directory exists under `CLAUDE_DIR`
- **AND** the rendered output is byte-identical to the output before this change

#### Scenario: Disabled tap does no work

- **WHEN** recording is disabled
- **THEN** the tap performs no filesystem access of any kind

#### Scenario: Env var enables the tap

- **WHEN** `YAS_RECORDING=1` is set and a tick is rendered
- **THEN** a recording file is written for that session

### Requirement: One gzip member appended per tick

For each recorded tick the system SHALL append to
`CLAUDE_DIR/yas/recordings/<session_id>.psv.gz` exactly one complete, independent
gzip member containing exactly one newline-terminated line. Appends SHALL NOT
rewrite, decompress, or read back existing content. The resulting file SHALL be a
valid gzip stream whose decompression yields the recorded lines in tick order —
that is, `gzip.open(path, 'rt')` and `zcat` SHALL both read the whole
concatenation. The directory SHALL be created with parents as needed. The session
id SHALL be taken from the payload's `session_id`, falling back to `unknown`,
consistent with the existing payload cache.

#### Scenario: Successive ticks append members

- **WHEN** three ticks are recorded for one session
- **THEN** the file contains three gzip members
- **AND** decompressing the file yields three lines in tick order

#### Scenario: Concatenation decompresses as one stream

- **WHEN** a multi-member recording is opened with `gzip.open(path, 'rt')`
- **THEN** iterating it yields every recorded line, not just the first member's

#### Scenario: Appending never reads the existing file

- **WHEN** a tick is appended to an existing recording
- **THEN** the existing bytes are not read and are left unmodified

#### Scenario: Directory is created on demand

- **WHEN** the first tick of the first session is recorded and
  `CLAUDE_DIR/yas/recordings` does not exist
- **THEN** the directory is created with its parents

#### Scenario: Missing session id falls back

- **WHEN** the payload has no `session_id`
- **THEN** the recording is written to `unknown.psv.gz`

### Requirement: Recorded line is a three-field PSV record

Each recorded line SHALL consist of exactly three fields joined by the separator
`' | '` (space, pipe, space), in order:

1. the tick's wall-clock time as a Unix epoch float,
2. the raw terminal width as an integer,
3. the stdin payload re-serialised as minified JSON.

Field 3 SHALL be the remainder of the line, so a reader SHALL split on the
separator with a maximum of two splits and SHALL NOT require any escaping of
pipe characters occurring inside the JSON. The JSON SHALL be serialised with
compact separators and without ASCII escaping, and SHALL contain no literal
newline, so one line is exactly one record.

#### Scenario: Line has three fields

- **WHEN** a tick is recorded
- **THEN** splitting the decompressed line on `' | '` with `maxsplit=2` yields a
  timestamp, a width, and a JSON document

#### Scenario: Pipes inside the payload need no escaping

- **WHEN** the payload contains a string value with a `|` character
- **THEN** the recorded line is not escaped, and a `maxsplit=2` split still
  recovers the exact original JSON

#### Scenario: Payload round-trips

- **WHEN** the third field of a recorded line is parsed as JSON
- **THEN** it equals the object yas was given on stdin

#### Scenario: One line per tick

- **WHEN** a payload containing multi-line string values is recorded
- **THEN** the recorded member still contains exactly one newline, at the end

### Requirement: Recorded width is the raw terminal width

The width field SHALL be the value returned by `terminal_width()` for that tick —
the raw terminal columns — and SHALL NOT be the derived box width after the
`max_width`, `full_width`, or `MIN_WIDTH` adjustments. This SHALL let a replayer
re-derive the box width by applying the same rules.

#### Scenario: Raw width is recorded, not the clamped box width

- **WHEN** a tick renders in a 300-column terminal with `max_width` set to 160
- **THEN** the recorded width is 300

### Requirement: Ticks below the minimum render width are still recorded

The tap SHALL run after the terminal width is obtained but before the early
return taken when the width is below `MIN_WIDTH`, so ticks that render nothing
still appear in the recording with their real width and leave no gap in the
timeline.

#### Scenario: Narrow tick is recorded

- **WHEN** a tick occurs in a terminal narrower than `MIN_WIDTH`
- **THEN** nothing is written to stdout
- **AND** a line is still appended to the recording, carrying that narrow width

### Requirement: Recording failure never affects the render

The tap SHALL catch and swallow every error it raises, including `OSError`,
encoding errors, and compression errors. A failing tap SHALL NOT
change, truncate, or delay the statusline written to stdout, SHALL NOT raise, and
SHALL NOT write to stderr on the normal path.

#### Scenario: Unwritable recordings directory is survived

- **WHEN** the recordings directory cannot be created or written
- **THEN** `main()` completes normally and the full statusline is written to
  stdout

#### Scenario: Serialisation failure is survived

- **WHEN** re-serialising the payload raises
- **THEN** the render still completes and no exception escapes `main()`

### Requirement: The recording tap is additive to the existing payload cache

The system SHALL preserve the existing overwrite-in-place cache at
`CLAUDE_DIR/statusline-output/statusline.<session_id>.json`, which `mon.py`
reads, unchanged in location, format, and behaviour. The
recording SHALL be a separate, append-only artifact under a separate directory.

#### Scenario: Both artifacts are written when recording is on

- **WHEN** recording is enabled and a tick renders
- **THEN** `statusline-output/statusline.<session_id>.json` holds the latest
  payload as before
- **AND** `yas/recordings/<session_id>.psv.gz` has gained one member

#### Scenario: mon.py is unaffected when recording is off

- **WHEN** recording is disabled
- **THEN** the payload cache is written exactly as it was before this change

### Requirement: The tap lives in the present layer

The tap SHALL be implemented in `claude/yas/app.py`, the single place per-render
side effects belong. No module under `claude/yas/info/` or `claude/yas/render/`
SHALL write to disk for recording purposes. The recordings directory SHALL be
derived from `app.py`'s module-level `CLAUDE_DIR` reference rather than re-read
from the environment, so test isolation that patches that reference holds.

#### Scenario: Gather layer stays read-only

- **WHEN** the recording feature is implemented
- **THEN** no module under `info/` or `render/` opens a file for writing

#### Scenario: Patched CLAUDE_DIR redirects recordings

- **WHEN** a test patches `app.CLAUDE_DIR` to a temporary directory
- **THEN** recordings are written under that temporary directory and nowhere else
