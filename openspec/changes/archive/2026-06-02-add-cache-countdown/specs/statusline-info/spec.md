## MODIFIED Requirements

### Requirement: Lazy pure-read SessionView gather

The statusline SHALL gather all *derived* session state through a single `SessionView` module (`claude/statusline/info.py`), constructed once per render from a parsed `SessionInfo` plus a `Config`. `SessionView` SHALL expose the derived state as lazily-evaluated, cached fields: `git`, `skills`, `subagents`, `tasks`, `transcript_usage`, `changes` (OpenSpec changes), `elapsed`, `session_cost`, `session_inout`, and `cache_countdown`. A field SHALL read its underlying source on first access and cache the result; a second access SHALL NOT re-read. Constructing a `SessionView` SHALL perform no source reads. `SessionView` SHALL perform no disk writes and SHALL NOT call `TokenLog.update` or `TokenRate.update`. The `cache_countdown` field SHALL be derived from `transcript_usage`'s raw cache anchor and the view's single frozen `now`, reusing the already-cached transcript scan rather than re-reading the transcript.

#### Scenario: A narrow render reads only what it draws

- **WHEN** a `SessionView` is constructed and a narrow-width build reads only `view.subagents`
- **THEN** the git subprocess, the transcript scan, and the openspec walk are not triggered (only the subagent source is read)

#### Scenario: A field is read at most once per view

- **WHEN** `view.session_inout` and `view.transcript_usage` are both accessed on one `SessionView`
- **THEN** the transcript is scanned exactly once (the cached value feeds both)

#### Scenario: Cache countdown reuses the cached transcript scan

- **WHEN** `view.transcript_usage` and `view.cache_countdown` are both accessed on one `SessionView`
- **THEN** the transcript is scanned exactly once (the cached usage feeds both, and `cache_countdown` triggers no additional read)

#### Scenario: Constructing a view writes nothing

- **WHEN** a `SessionView` is constructed and any subset of its fields is accessed
- **THEN** no token-log or token-rate file is written by the view
