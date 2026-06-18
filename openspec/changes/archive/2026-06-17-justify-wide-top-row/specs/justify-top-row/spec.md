## ADDED Requirements

### Requirement: Even slack distribution across wide top-row sections

When `cfg.justify` is `true`, the wide layout's top content row SHALL distribute horizontal slack evenly across its active sections rather than concentrating all slack in the path section. The active sections, in order, are: path (always), elapsed (when present), helper (always), cache (when present), and last-slot (always — the space between the final section and the right pill/text). Let N be the count of active sections and `total_slack = target_w - path_w`. Each section i (0-indexed) SHALL receive `extra_per + (1 if i < remainder else 0)` extra columns, where `extra_per = total_slack // N` and `remainder = total_slack % N`. When `total_slack == 0` the layout SHALL fall through to the normal (non-justify) rendering unchanged.

#### Scenario: Slack distributed across four active sections

- **WHEN** `cfg.justify` is true, elapsed and cache are active (N=5), and `total_slack` is 20
- **THEN** each section receives 4 extra columns (`20 // 5 = 4`, remainder 0)

#### Scenario: Remainder spread left-to-right

- **WHEN** `cfg.justify` is true, N=5, and `total_slack` is 22
- **THEN** sections 0–1 receive 5 extra columns each and sections 2–4 receive 4 columns each

#### Scenario: Zero slack falls through

- **WHEN** `cfg.justify` is true and `total_slack == 0` (path fills its full target width)
- **THEN** the layout renders identically to the non-justify layout

#### Scenario: Sub-N slack still distributes remainders

- **WHEN** `cfg.justify` is true, N=5, and `total_slack` is 3
- **THEN** sections 0–2 receive 1 extra column each and sections 3–4 receive 0

### Requirement: Padding placement per section

The path section SHALL remain left-aligned; its `extra` columns SHALL be added as trailing spaces after the path content and before the vsep block. The elapsed, helper, and cache sections SHALL each have their content centered within the wider slot: `left_pad = extra // 2` spaces SHALL be prepended to the section content and `right_pad = extra - left_pad` spaces SHALL be appended, with the result sitting between the surrounding vsep blocks. The last-slot SHALL receive its `extra` columns as trailing space before the right pill or `right_text`.

#### Scenario: Path extra goes to trailing side

- **WHEN** the path section receives 6 extra columns in justify mode
- **THEN** 6 spaces are appended after the path content and before the adjacent vsep, and path content remains left-aligned

#### Scenario: Helper content centered symmetrically

- **WHEN** the helper section receives 8 extra columns
- **THEN** 4 spaces are prepended and 4 spaces are appended around the helper content

#### Scenario: Odd extra splits left-biased

- **WHEN** a middle section receives 7 extra columns
- **THEN** 3 spaces are prepended (left) and 4 spaces are appended (right)

### Requirement: Divider column adjustment for border elbow alignment

When justify padding is applied, every vsep divider column SHALL be shifted by the cumulative extra padding of all sections preceding it (including the section's own left-pad where applicable) before being recorded in `path_row_cols` for `ups`/`downs` elbow threading. The `sep_rate_col` (the `┆` inside `helper_text`) SHALL likewise be shifted by the cumulative padding up to and including the helper section's left-pad. The resulting `path_row_downs` and `path_row_ups` tuples SHALL have every column in the same relative position relative to their vsep blocks as in the non-justify layout.

#### Scenario: Path divider column shifts by path extra

- **WHEN** justify mode adds 6 extra columns to the path section
- **THEN** `path_div_col` increases by 6 and the `┬` on the top border aligns with the `│` in the content row

#### Scenario: All downstream columns shift cumulatively

- **WHEN** path receives 4 extra, elapsed receives 6 extra (left=3, right=3), helper receives 4 extra (left=2, right=2)
- **THEN** `elapsed_div_col` shifts by 4 (path extra) + 6 (elapsed total), `helper's sep_rate_col` shifts by 4 + 6 + 2 (helper left)

### Requirement: Justify applies in both pill and non-pill mode

When the model pill is active, the extra columns for the last slot SHALL be appended to the `middle` string before the `right_pill` rendering branch. When the pill is not active, the extra columns SHALL be added to the `pad` value before the `right_text` concatenation. In both cases the pill or `right_text` SHALL remain flush to the right edge.

#### Scenario: Non-pill mode last-slot padding

- **WHEN** justify mode is active and the pill is not active, and the last slot receives 8 extra columns
- **THEN** `pad` is increased by 8, placing 8 additional spaces before `right_text`

#### Scenario: Pill mode last-slot padding

- **WHEN** justify mode is active and the pill is active, and the last slot receives 8 extra columns
- **THEN** 8 spaces are appended to `middle` before the pill branch, and the pill remains at the right edge
