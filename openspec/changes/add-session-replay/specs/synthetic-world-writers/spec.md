## ADDED Requirements

### Requirement: Hermetic world writers live in a shared ops module

`ops/synth.py` SHALL hold the primitives that materialise a hermetic `$HOME` and
its session artifacts, and both `ops/demo.py` and `ops/replay.py` SHALL import
them from it. The moved set SHALL comprise at least: the synthetic environment
builder, the transcript writer, the subagent cohort writer, the settings writer,
the workflow writer, the openspec-changes writer, the token-rate-log writer, the
statusline subprocess invoker, and their private helpers and constants. Neither
`ops/replay.py` nor `ops/demo.py` SHALL hold a second, forked copy of any of
them.

#### Scenario: Both CLIs share one implementation

- **WHEN** `ops/demo.py` and `ops/replay.py` build a hermetic world
- **THEN** both call the same functions in `ops/synth.py`

#### Scenario: No duplicated writers

- **WHEN** the repository is searched for the writer function names
- **THEN** each is defined exactly once, in `ops/synth.py`

### Requirement: Behaviour of the moved writers is preserved exactly

Moving the writers SHALL NOT change their behaviour, signatures, or the files
they produce. The demo snapshot corpus under `demo/` SHALL be byte-identical
before and after the move, and the demo visual gate SHALL show no diff.

#### Scenario: Snapshots are unchanged

- **WHEN** the demo snapshots are regenerated after the extraction
- **THEN** every `demo/**` text snapshot is byte-identical to before

#### Scenario: Signatures are unchanged

- **WHEN** an existing caller invokes a moved writer with its previous arguments
- **THEN** it behaves identically

### Requirement: ops/demo.py re-exports every moved name

`ops/demo.py` SHALL continue to expose every moved name as an attribute of the
`demo` module, so existing direct importers keep working without edits. In
particular `test/test_cohort_visibility.py`, which reaches for
`ops_demo.build_synthetic_env`, `ops_demo.render_scenario`, `ops_demo.SCENARIOS`,
and `ops_demo.FIXTURE_PATH`, SHALL pass unchanged.

#### Scenario: Existing test passes untouched

- **WHEN** `test/test_cohort_visibility.py` is run after the extraction, with no
  edits to it
- **THEN** it passes

#### Scenario: Moved names remain module attributes

- **WHEN** `demo` is imported and a moved writer is accessed as an attribute
- **THEN** it resolves to the implementation in `ops/synth.py`

### Requirement: Demo editorial choices stay in the demo

The path-rewiring helper moved into `ops/synth.py` SHALL redirect only `cwd`,
`workspace`, and `transcript_path` into the temporary tree. The demo's editorial
payload mutations — forcing `thinking.enabled`, `effort.level`, and the
`rate_limits` reset times — SHALL remain in `ops/demo.py`, layered on top of the
shared helper, so replay's frames reflect the recorded payload rather than the
demo's choices.

#### Scenario: Shared helper only rewires paths

- **WHEN** the shared helper is applied to a payload
- **THEN** only `cwd`, `workspace`, and `transcript_path` change

#### Scenario: Demo keeps its editorial mutations

- **WHEN** `ops/demo.py` prepares a payload
- **THEN** it still applies its `thinking`, `effort`, and `rate_limits` values

#### Scenario: Replay preserves the recorded payload

- **WHEN** `ops/replay.py` prepares a frame payload whose recorded `effort.level`
  is `low`
- **THEN** the rendered frame shows `low`, not the demo's value

### Requirement: The extracted module is unit tested

`ops/synth.py` SHALL have direct unit tests covering, at minimum: the hermetic
environment builder produces the expected tree; the transcript writer produces
records the production readers parse into the intended totals; the subagent
writer clears stale agent files before writing and produces meta plus jsonl pairs
the cohort reader recognises. Before this change these writers were exercised
only transitively.

#### Scenario: Writers have their own tests

- **WHEN** the test suite is run
- **THEN** tests exist that call the extracted writers directly and assert on the
  files they produce

#### Scenario: Subagent writer is idempotent per call

- **WHEN** the subagent writer is called twice with different cohorts into one
  directory
- **THEN** only the second cohort's agent files remain
