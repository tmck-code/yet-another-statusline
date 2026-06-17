## ADDED Requirements

### Requirement: Clear-marker epoch gather field

`SessionView` SHALL expose a render-independent, lazily-computed field giving the Unix epoch (seconds) of the most recent `/clear` in the current transcript, or `None` when the session has never been cleared. The field SHALL be read by a **bounded head-scan** of the transcript: it SHALL inspect at most the first 30 lines, match the `<command-name>/clear</command-name>` user marker, and parse that line's ISO-8601 `timestamp` to an epoch. Because each `/clear` forks a new transcript file, at most one such marker exists per transcript, so the first match is the only match. The scan SHALL early-exit on the first match and SHALL never read the whole file, so fresh sessions and large transcripts pay only the bounded cost. Malformed lines, an unreadable transcript, an empty `transcript_path`, or no marker within the budget SHALL yield `None` rather than raising. The field SHALL hold no ANSI or render geometry and SHALL be cached for the lifetime of the view.

#### Scenario: Cleared session exposes the marker epoch

- **WHEN** the current transcript contains a `<command-name>/clear</command-name>` marker within the first 30 lines with a parseable timestamp
- **THEN** the gather field returns that timestamp as a Unix epoch

#### Scenario: Fresh session exposes None

- **WHEN** the current transcript contains no `/clear` marker within the first 30 lines
- **THEN** the gather field returns `None`

#### Scenario: Bounded cost on a large transcript

- **WHEN** the transcript is hundreds of lines long and has no `/clear` marker in its first 30 lines
- **THEN** the scan reads at most 30 lines and returns `None` without scanning the remainder

#### Scenario: Unreadable or malformed input degrades to None

- **WHEN** the transcript path is empty, missing, or the candidate marker line is not valid JSON or lacks a parseable timestamp
- **THEN** the gather field returns `None` and does not raise
