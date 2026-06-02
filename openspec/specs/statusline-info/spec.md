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

### Requirement: Render-independent gather seam

`SessionView` SHALL sit below the render layer: it MAY import `session`, the six reader modules (`git`, `skills`, `subagents`, `tasks`, `transcript`, `openspec`), `metrics`, `tokens` (cost computation only), and `config`, but SHALL NOT import `renderer`, `pill`, `gradient`, `borders`, or `layout`. `SessionView` SHALL hold no render geometry (bar fill ratio, pill percentage, model anchor/shift). It SHALL delegate to the readers' existing classmethods rather than inlining their logic, so each reader keeps its individually-stubbable seam.

#### Scenario: Info carries no render dependency

- **WHEN** `claude/statusline/info.py` is imported
- **THEN** it references no symbol from `renderer`, `pill`, `gradient`, `borders`, or `layout`

#### Scenario: Time math uses one frozen clock

- **WHEN** a `SessionView` is constructed with an explicit `now`
- **THEN** `elapsed` and task-freshness decisions derived through the view use that single `now` value

### Requirement: Single source for the Session In/Out denominator

`SessionView.session_inout` SHALL be the sole definition of the Session Share % denominator: `(billed_in + cache_read + out) + sum(total_input + output)` over the running subagents. No layout builder SHALL recompute this sum inline.

#### Scenario: Denominator composes usage and subagents

- **WHEN** `view.session_inout` is read with known transcript usage and a known set of running subagents
- **THEN** it equals the transcript billed-in plus cache-read plus output, plus each subagent's `total_input + output`

### Requirement: Per-render writes isolated in record_tick

The per-render token-log and token-rate writes SHALL be performed by a `record_tick(session, usage)` step owned by `app`, returning a `TickRecord` bundling `token_log`, `day_cost`, and the token rate. `app` SHALL thread the `TickRecord` into the wide layout builder. The Day Total and day-cost SHALL NOT be fields of `SessionView`.

#### Scenario: The wide builder receives day totals as data

- **WHEN** `app` renders a wide layout
- **THEN** `record_tick` performs the token-log and token-rate writes and the resulting `TickRecord` is passed into the wide builder, which reads `day_cost` from it rather than computing or persisting it
