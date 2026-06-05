## ADDED Requirements

### Requirement: Context percentage matches Claude Code's authoritative value

The context bar fill ratio and displayed percentage SHALL be derived from the host-supplied `context_window.used_percentage` field when that field is present and non-negative. When `used_percentage` is absent (`None`), the statusline SHALL fall back to an input-only manual calculation: `total_input_tokens / context_window_size`, clamped to `[0, 1]`. The statusline SHALL NOT add `total_output_tokens` to the numerator in either path. Negative derived values SHALL be clamped to zero.

#### Scenario: Host-supplied percentage is preferred

- **WHEN** `context_window.used_percentage` is `42.7` (host-provided)
- **THEN** the displayed percentage is `43%` (rounded) and the bar fill ratio is `0.427`, regardless of the raw token counts

#### Scenario: Fallback to input-only when field is absent

- **WHEN** `context_window.used_percentage` is `None` and `total_input_tokens` is `80000` with `context_window_size` of `200000`
- **THEN** the displayed percentage is `40%` and the fill ratio is `0.40`

#### Scenario: Output tokens are not counted

- **WHEN** `context_window.used_percentage` is `None`, `total_input_tokens` is `60000`, `total_output_tokens` is `40000`, and `context_window_size` is `200000`
- **THEN** the fill ratio is `0.30` (input-only), not `0.50` (input+output)

#### Scenario: Negative value is clamped to zero

- **WHEN** `context_window.used_percentage` is `-2.0` (malformed host payload)
- **THEN** the fill ratio is `0.0` and the displayed percentage is `0%`

#### Scenario: Zero context_window_size does not divide by zero

- **WHEN** `used_percentage` is `None` and `context_window_size` is `0`
- **THEN** the fill ratio is `0.0` and no exception is raised
