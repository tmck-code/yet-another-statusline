## ADDED Requirements

### Requirement: Exceeds-200k alert badge is displayed in the context row

When `session.exceeds_200k_tokens` is `True`, the context row SHALL prepend a compact `!200K` badge rendered in a warning colour (amber/yellow, distinct from the normal bar fill colour). The badge SHALL be present in all layout widths (narrow, medium, wide) that render a context row. The bar width SHALL be reduced by the badge's visible width (6 columns: 5 for `!200K` plus 1 separator space) to prevent the row from overflowing the border. When `exceeds_200k_tokens` is `False`, no badge is rendered and the bar width is unchanged.

#### Scenario: Badge appears when exceeds_200k_tokens is true

- **WHEN** `session.exceeds_200k_tokens` is `True`
- **THEN** the context row contains the text `!200K` in a warning colour before the token count

#### Scenario: No badge when exceeds_200k_tokens is false

- **WHEN** `session.exceeds_200k_tokens` is `False`
- **THEN** the context row contains no `!200K` text and the bar width is at its normal value

#### Scenario: Bar width is reduced when badge is active

- **WHEN** `exceeds_200k_tokens` is `True` and `available` is `60`
- **THEN** the bar fills at most `54` columns (60 minus 6 for the badge)

#### Scenario: Badge is present in narrow layout

- **WHEN** `exceeds_200k_tokens` is `True` and the terminal is narrow
- **THEN** the context row still shows the `!200K` badge (the bar may be very short or zero)

#### Scenario: Badge colour is visually distinct from the fill bar

- **WHEN** the badge is rendered
- **THEN** the ANSI colour applied to `!200K` is the amber/yellow warning constant, not the bar's gradient or risk-zone colour
