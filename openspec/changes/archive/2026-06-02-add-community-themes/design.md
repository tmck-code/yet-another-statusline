## Context

The statusline currently ships 4 hardcoded themes. Users request more options aligned with popular community color schemes. The alacritty-theme repo (400+ themes) is well-maintained, canonical, and provides tested palettes.

A prior grill-me session evaluated three storage approaches:
- **TOML loading**: 449.9 µs/render (too slow)
- **Pickle caching**: 22.8 µs/render (500× slower than hardcoded, added complexity)
- **Hardcoded**: 41.6 µs/render (baseline, zero latency)

Decision: **hardcode themes as Python dataclasses** for zero latency impact on every statusline render.

## Goals / Non-Goals

**Goals:**
- Add 11 community themes (dracula, gruvbox-dark/light, nord, one-dark/light, solarized-dark/light, tokyo-night, palenight)
- Maintain 2 custom themes (claude-dark, claude-light) as branded defaults
- Build a repeatable converter script for future theme updates
- All themes hardcoded in `claude/yas/themes.py`
- Zero render-time latency impact

**Non-Goals:**
- Dynamic TOML/YAML theme loading (rejected due to latency)
- User-supplied custom themes via config file (future phase, not phase 1)
- Automatic syncing with upstream alacritty-theme repo
- Per-model theme customization (model pills use fixed derivation)

## Decisions

### Decision: Converter script (ops/extract_themes.py)

**Rationale**: Manual hand-porting 11 themes is slow and error-prone. A script:
- Reads alacritty YAML (already cloned locally by user)
- Extracts color values
- Maps to statusline field names
- Generates Python code automatically

**Alternatives considered**:
- Hand-port each theme manually (rejected: tedious, hard to update)
- Runtime YAML parsing (rejected: latency, dependency)

### Decision: Fixed color mapping (alacritty slots → statusline fields)

Alacritty defines colors in `colors.normal.*` and `colors.bright.*` slots. Mapping:
- `colors.normal.black` → `bar_empty`, `ctx_dim` (dims/backgrounds)
- `colors.normal.red` → `alert`, `dirty`
- `colors.normal.green` → `safe`, `branch`, `bar_fill`
- `colors.normal.yellow` → `warn`, `yellow`
- `colors.normal.blue` → `pwd`, `model`
- `colors.normal.cyan` → `ctx`, `tok`, `tok_day`
- `colors.bright.red` → `cost`
- `colors.bright.yellow` → `tok_arrow`, `tok_icon`
- `colors.bright.white` → `white_brt`

**Rationale**: Sensible defaults that respect semantic meaning (green=safe, red=alert, blue=pwd, etc.). All 11 themes use the same mapping, ensuring consistency.

**Trade-off**: Some themes may have mis-mapped colors. Mitigation: visual demo loop validates each theme; user hand-tweaks only themes that look wrong.

### Decision: Model pill colors via algorithmic derivation

Model pills need 4 colors per model (opus/sonnet/haiku/other). Rather than hardcode generics, **derive from the theme's color palette**:
- Extract 8 brightest/most-saturated colors from alacritty palette
- Assign opus → yellow family, sonnet → green family, haiku → blue family, other → magenta family
- For each family, pick anchor (primary), warm_shift (warm hue), cool_shift (cool hue)

**Rationale**: Ensures pill colors harmonize with the theme. Each theme gets visually coherent model indicators.

**Script logic**:
```
1. Read alacritty colors
2. Group by hue family (reds, greens, blues, magentas)
3. Pick brightest from each family
4. Assign to models: opus=yellow, sonnet=green, haiku=blue, other=magenta
5. Generate anchor, warm_shift, cool_shift by shifting hues
6. Output to Python code
```

**Validation**: User reviews in `make demo` and hand-tweaks if needed.

### Decision: Gradient and sparkline colors

For `grad_stops` (rainbow border) and `spec_gradients` (spec-level sparklines), **generate sensible defaults**:
- Use theme's primary colors (bright, saturated) to build a gradient
- Fallback: derive from model pill colors

**Validation**: Visual check in demo; hand-tweak if the gradient doesn't match the theme's aesthetic.

### Decision: Remove catppuccin variants, replace with canonical versions

Current themes include `catppuccin-latte` and `catppuccin-mocha` (hand-tuned). Alacritty-theme provides official Catppuccin variants. **Replace with upstream versions** to reduce maintenance.

## Risks / Trade-offs

**[Risk] Alacritty theme color interpretation** → **Mitigation**: Fixed mapping is sensible but imperfect. User visually validates all 13 themes with `make demo` and hand-tweaks model/gradient colors for any themes that don't look right.

**[Risk] Script is one-time-use / not maintained** → **Mitigation**: Document the script in `ops/README.md` with examples. If new themes are added later, rerun the script.

**[Risk] Model pill derivation produces clashing colors** → **Mitigation**: Script generates reasonable defaults; user adjusts in `themes.py` if needed. Demo catches these issues.

**[Risk] Gradient colors don't harmonize with theme** → **Mitigation**: Gradients generated from theme's own colors, so they're inherently coherent. User tweaks only if demo reveals issues.

## Migration Plan

1. Write `ops/extract_themes.py` converter script
2. Run script on user's local alacritty-theme clone → generates Python code appending to `themes.py`
3. Review generated code: spot-check color values
4. Append generated themes to `themes.py` and remove catppuccin variants
5. Run `make demo` for all 13 themes, visually validate
6. Hand-tweak model/gradient colors for any themes that look off
7. Run `make test` to ensure no regressions
8. Single PR: "Add 11 community themes from alacritty-theme"

## Open Questions

- **What's the exact alacritty-theme repo path?** (User provides or we auto-detect?)
  - **Decision**: User must provide path (already cloned locally)
- **How to handle themes with missing colors in alacritty YAML?** (Some themes may have sparse color definitions)
  - **Mitigation**: Script validates and reports missing colors; user fixes or skips theme
- **Which alacritty-theme commit SHA to reference?** (For traceability and future updates)
  - **Decision**: Document in commit message the alacritty-theme ref used
