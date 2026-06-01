## ADDED Requirements

### Requirement: Plugin-shipped UserPromptSubmit hook

The YAS plugin SHALL declare a `UserPromptSubmit` hook in its own `hooks/hooks.json` so the behaviour travels with the plugin and requires no per-user `settings.json` edits. The hook SHALL record the prompt-submit timestamp for the submitting session.

#### Scenario: Hook fires on user prompt

- **WHEN** the user submits a prompt in a session where the YAS plugin is installed
- **THEN** the hook runs and records the current timestamp for that `session_id`

#### Scenario: Hook ships with the plugin

- **WHEN** a user installs the YAS plugin
- **THEN** the `UserPromptSubmit` hook is present without the user editing `~/.claude/settings.json`

### Requirement: Shared per-session state file with atomic writes

The hook SHALL persist a mapping of `session_id` to the latest prompt-submit timestamp in a single shared state file. Writes SHALL be atomic and SHALL preserve other sessions' entries: read the existing map, update only the current session's entry, write to a temporary file, and rename it into place.

#### Scenario: Concurrent sessions do not clobber each other

- **WHEN** two sessions submit prompts close together
- **THEN** both sessions' timestamps are present in the state file after the writes settle

#### Scenario: Atomic replace avoids partial reads

- **WHEN** the statusline reads the state file while the hook is updating it
- **THEN** the reader sees either the old complete map or the new complete map, never a truncated file

### Requirement: Statusline consumes the prompt timestamp

The statusline SHALL read the current session's prompt-submit timestamp from the shared state file and use it as the authoritative lower bound for turn-scoped cohort membership. A missing or unreadable file SHALL trigger the subagent-cohort capability's recency-window fallback rather than an error.

#### Scenario: Timestamp scopes the cohort

- **WHEN** the state file contains a timestamp for the current `session_id`
- **THEN** the statusline uses it as the cohort lower bound

#### Scenario: Absent entry falls back

- **WHEN** the state file has no entry for the current `session_id`
- **THEN** the statusline falls back to the recency window without error
