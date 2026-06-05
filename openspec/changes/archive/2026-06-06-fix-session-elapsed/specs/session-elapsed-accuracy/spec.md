## ADDED Requirements

### Requirement: Elapsed is derived from host-supplied session duration

`SessionView.elapsed` SHALL be derived from `session.cost.total_duration_ms` (the host-supplied wall-clock session duration in milliseconds), not from the modification time of the transcript file. The displayed format SHALL remain `Nm` for durations under one hour and `HhMm` for durations of one hour or more.

#### Scenario: Duration under one hour formats as minutes

- **WHEN** `cost.total_duration_ms` is `807000` (13 minutes 27 seconds)
- **THEN** `elapsed` is `'13m'`

#### Scenario: Duration of one hour or more formats as hours and minutes

- **WHEN** `cost.total_duration_ms` is `5580000` (1 hour 33 minutes)
- **THEN** `elapsed` is `'1h33m'`

#### Scenario: Zero duration returns empty string or zero representation

- **WHEN** `cost.total_duration_ms` is `0`
- **THEN** `elapsed` is `''` or `'0m'` (consistent with existing behaviour for unknown duration)

#### Scenario: Elapsed does not trigger a transcript file stat

- **WHEN** `view.elapsed` is accessed on a `SessionView` whose `transcript_usage` has not been accessed
- **THEN** no file stat is performed for the elapsed property alone (the value comes from the in-memory payload)
