## ADDED Requirements

### Requirement: Name-derived gradient selection

An OpenSpec change bar SHALL select its gradient from `SPEC_GRADIENTS` using a
hash of the change name modulo the palette length, not the change's position in
the list. The same change name SHALL always map to the same gradient, and the
mapping SHALL be independent of the change's order among the rendered bars.

#### Scenario: Same name maps to the same gradient

- **WHEN** a change with a given name is rendered in two different list
  positions
- **THEN** it uses the same gradient in both cases

#### Scenario: Distinct names spread across the palette

- **WHEN** several differently-named changes are rendered
- **THEN** their gradient selection is driven by their names rather than their
  ordinal positions

### Requirement: Render-stable hashing

The hash used to select the gradient SHALL be stable across separate process
invocations. The system SHALL NOT use Python's builtin `hash()` on the name
(which is salted per process via `PYTHONHASHSEED`); it SHALL use a
deterministic hash such as `zlib.crc32` or a `hashlib` digest so the colour does
not change between render ticks.

#### Scenario: Colour does not change across render ticks

- **WHEN** the same change is rendered in two separate statusline subprocess
  invocations
- **THEN** it is assigned the same gradient both times (no strobing)
