## Why

The wide layout's top row concentrates all horizontal slack in the path section, leaving inner sections (elapsed timer, rate limits, cache) cramped while a large blank gap sits between them and the right pill. Distributing that slack evenly across all sections produces a more balanced, readable bar at any terminal width.

## What Changes

- New boolean config knob `justify` (default `false`) under `[layout]` in `yas.toml`, with canonical env var `YAS_JUSTIFY`.
- When enabled, `build_wide` distributes the horizontal slack evenly across the active sections of the top content row instead of concentrating it in the path section.
- Path content stays left-aligned within its wider slot; inner sections (elapsed, helper, cache, and the pre-pill last slot) receive symmetric (centered) padding.
- All vsep divider columns shift accordingly so border elbows (`┬`/`┴`) stay aligned.
- Medium and narrow layouts are unaffected.

## Capabilities

### New Capabilities
- `justify-top-row`: Even distribution of horizontal slack across the top-row sections of the wide layout.

### Modified Capabilities
- `statusline-config`: New `[layout].justify` boolean knob added to the config precedence chain (`YAS_JUSTIFY` env var, `yas.toml` `[layout]` key, default `false`).

## Impact

- `yas/constants.py` — add `DEFAULT_JUSTIFY = False`
- `yas/config.py` — wire `justify` knob into `Config.load` and the `Config` dataclass
- `yas/layout.py` — `build_wide`: compute and apply justify padding when `cfg.justify` is true
- No changes to rendering primitives (`renderer.py`, `render/borders.py`, `render/gradient.py`)
- No public API changes; `render()` in `app.py` is unchanged
