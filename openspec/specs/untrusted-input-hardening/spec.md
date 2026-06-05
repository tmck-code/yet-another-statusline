# untrusted-input-hardening Specification

## Purpose
TBD - created by archiving change harden-untrusted-input. Update Purpose after archive.
## Requirements
### Requirement: Untrusted field values are sanitized at capture

The statusline SHALL strip terminal control characters from every host- or repo-supplied string value as it is captured into the session model, before that value can reach stdout. The sanitizer MUST remove the C0 control bytes `0x00`–`0x08` and `0x0b`–`0x1f`, `DEL` (`0x7f`), and all C1 control bytes (`0x80`–`0x9f`). This range includes `ESC` (`0x1b`) and `BEL` (`0x07`), the introducers and terminators for OSC and CSI sequences, so no untrusted OSC/CSI escape can be emitted. (Statusline fields are single-line, so no in-band `\t`/`\n` needs to be preserved.)

The untrusted fields are: model `display_name` and `id`, `cwd`/`current_dir`, `project_dir`, `session_id`, output-style name, the git branch name read from `.git/HEAD` and refs, transcript-derived task subject and active_form, subagent description and tool-input text, skill names, and `enabledPlugins` keys.

Sanitization MUST be applied at the point of capture, NOT to the final rendered line, so that the renderer's own legitimate SGR colour escapes are preserved.

#### Scenario: OSC-52 clipboard payload in a model name is neutralized

- **WHEN** the host supplies a model `display_name` containing `\x1b]52;c;<base64>\x07`
- **THEN** the captured value contains no `\x1b` or `\x07` bytes and the rendered statusline emits no OSC-52 sequence

#### Scenario: OSC-0 title-spoof payload in a git branch is neutralized

- **WHEN** a repo's `.git/HEAD` resolves to a branch name containing `\x1b]0;PWNED\x07`
- **THEN** the captured branch contains no `\x1b` or `\x07` bytes and the rendered statusline emits no OSC-0 sequence

#### Scenario: Control bytes in transcript-derived task and subagent text are stripped

- **WHEN** a transcript yields a task subject, subagent description, or tool-input string containing C0/C1/DEL control bytes
- **THEN** those bytes are removed from the captured value before rendering

#### Scenario: Legitimate plain text is unchanged

- **WHEN** an untrusted field contains only printable characters (including non-ASCII/CJK text)
- **THEN** the sanitized value is byte-for-byte identical to the input

### Requirement: Plugin state is read only from the user's own config directory

The statusline SHALL determine the enabled-plugins list solely from the user's own `CLAUDE_DIR/settings.json`. It MUST NOT read `project_dir/.claude/settings.json` (or any settings file under a host-supplied workspace path), because `project_dir` is attacker-controlled for a cloned repository and constitutes both an unexpected trust-boundary read and an escape-injection sink.

#### Scenario: A cloned repo's settings file is ignored

- **WHEN** `project_dir/.claude/settings.json` exists and lists `enabledPlugins`
- **THEN** none of its keys appear in the rendered plugins list

#### Scenario: The user's own settings still drive the plugins list

- **WHEN** `CLAUDE_DIR/settings.json` lists `enabledPlugins`
- **THEN** its enabled keys appear in the rendered plugins list as before

