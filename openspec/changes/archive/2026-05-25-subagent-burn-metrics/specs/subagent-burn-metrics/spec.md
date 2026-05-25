## ADDED Requirements

### Requirement: Average token throughput per subagent

The wide subagent row (terminal width greater than 100 columns) SHALL display the cumulative average token throughput of each running subagent, expressed in tokens per minute (t/m). The value SHALL be computed as `(total_input + output) / duration_minutes`, where `total_input` is `billed_in + cache_read_in`, `output` is the subagent's output tokens, and `duration_minutes` is `(now - first_timestamp) / 60`. The figure SHALL be prefixed with the gauge glyph (`ICON_TOK_RATE`) and rendered in the flat token colour (`self.TOK`), matching the main row's t/m styling.

#### Scenario: Throughput shown for an established subagent
- **WHEN** a subagent has run for at least 3 seconds with a valid `first_timestamp` and non-zero tokens
- **THEN** the wide subagent row shows `{gauge} <N> t/m` where `<N>` is `(total_input + output)` divided by elapsed minutes

#### Scenario: Throughput omitted for a just-spawned subagent
- **WHEN** a subagent's elapsed duration is less than 3 seconds, OR its `first_timestamp` is 0
- **THEN** the average t/m figure is omitted from the row (no zero, no placeholder number) to avoid a first-second spike or divide-by-zero

### Requirement: Session token-share per subagent

The wide subagent row SHALL display each subagent's share of the whole session's token spend, expressed as a percentage. The share SHALL be computed as `sub_inout / session_inout`, where `sub_inout` is the subagent's `total_input + output` and `session_inout` is `main_inout + Σ subagent_inout` across the main thread and all running subagents. The main thread's contribution `main_inout` SHALL be `(billed_in + cache_read) + output` taken from the main session transcript usage. The figure SHALL be prefixed with the pie-chart glyph (`GLYPH_PIE`) and colour-mapped by magnitude via the fill gradient so that the dominant subagent is rendered hot and small slices stay cool.

#### Scenario: Share reflects fraction of session burn
- **WHEN** the session denominator `session_inout` is greater than 0
- **THEN** the row shows `{pie} <P>%` where `<P>` is `sub_inout / session_inout` as a percentage, and the percentage's colour intensity scales with its magnitude

#### Scenario: Shares are computed against main plus all subagents
- **WHEN** the session has a main thread and one or more running subagents
- **THEN** the denominator includes the main thread's `main_inout` plus every running subagent's `sub_inout`, so the main thread and all subagents' shares are mutually consistent fractions of one total

#### Scenario: Share omitted when nothing has been spent
- **WHEN** the session denominator `session_inout` is 0
- **THEN** the share figure is omitted from the row (no divide-by-zero, no `0%` placeholder)

### Requirement: Burn-metric cluster placement and responsive drop

The average t/m and session-share figures SHALL be appended to the subagent row's line-2 right cluster, after the existing `⧗tok · $cost` segment, in the form `· {gauge} <N> t/m · {pie} <P>%`. When the horizontal room remaining for the row falls below the threshold needed to fit the pair (the row's content padding would drop below its minimum gap), both figures SHALL be omitted together and the row SHALL fall back to the existing `⧗tok · $cost` segment. A partial state showing only one of the two figures SHALL NOT occur.

#### Scenario: Cluster shown when room permits
- **WHEN** the wide subagent row has enough horizontal room to fit both figures while preserving the minimum content gap
- **THEN** both `{gauge} <N> t/m` and `{pie} <P>%` are appended to the line-2 right cluster

#### Scenario: Cluster dropped atomically when cramped
- **WHEN** including the figure pair would push the row's content padding below its minimum gap
- **THEN** both figures are omitted and the row renders only `⧗tok · $cost`, never just one of the two

### Requirement: Burn metrics are confined to the wide subagent row

The average t/m and session-share figures SHALL appear only on the wide subagent row (terminal width greater than 100 columns). The narrow single-line subagent collapse (width 100 or less) SHALL remain unchanged and SHALL NOT render either figure.

#### Scenario: Narrow row unaffected
- **WHEN** the terminal width is 100 columns or less and the subagent row uses the single-line collapse
- **THEN** neither the average t/m nor the session-share figure is rendered, and the narrow row's existing content is unchanged
