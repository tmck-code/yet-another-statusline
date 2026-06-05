## ADDED Requirements

### Requirement: COLUMNS environment variable is the first width source

`terminal_width()` SHALL check the `COLUMNS` environment variable as its first width source, before any subprocess invocation or file read. When `COLUMNS` is set to a positive integer, that value SHALL be returned immediately without probing tmux, reading `CLAUDE_DIR/terminal-width`, or calling `shutil.get_terminal_size`.

#### Scenario: COLUMNS is returned immediately when set

- **WHEN** `COLUMNS=160` is set in the environment
- **THEN** `terminal_width()` returns `160` without invoking the tmux subprocess or reading any file

#### Scenario: Falls through to tmux when COLUMNS is absent

- **WHEN** `COLUMNS` is not set and a tmux pane is active
- **THEN** the tmux pane width is used

#### Scenario: Falls through to file fallback when COLUMNS is zero

- **WHEN** `COLUMNS=0` is set in the environment
- **THEN** `terminal_width()` continues to the next source (tmux or file)

### Requirement: Tmux subprocess probe has a bounded timeout

The `subprocess.run` call that probes the tmux pane width SHALL pass `timeout=0.2` (200 milliseconds). When the subprocess times out or raises `subprocess.TimeoutExpired`, the function SHALL catch the exception and continue to the next width source without blocking further.

#### Scenario: Wedged tmux server does not hang the render

- **WHEN** the tmux subprocess does not respond within 200 ms
- **THEN** `terminal_width()` catches `TimeoutExpired`, skips the tmux result, and continues to the next source

#### Scenario: Healthy tmux still returns the pane width

- **WHEN** the tmux subprocess responds within the timeout with a positive integer
- **THEN** that integer is returned (assuming `COLUMNS` was not set)
