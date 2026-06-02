## Why

Users want more color theme options beyond the current 4 hardcoded themes. Popular color schemes (Dracula, Gruvbox, Nord, Solarized, etc.) from the community alacritty-theme repo provide well-tested palettes that work across many terminal applications. Adding these increases accessibility and user satisfaction with minimal maintenance burden.

## What Changes

- Extract 11 community-sourced themes from [alacritty-theme](https://github.com/alacritty/alacritty-theme) repo using a converter script
- Hardcode these themes as `Theme` dataclass instances in `claude/yas/themes.py` (benchmarks show hardcoded is ~500× faster than TOML loading with pickle caching)
- Maintain 2 custom themes: `claude-dark` and `claude-light` (branded defaults)
- Remove `catppuccin-latte` and `catppuccin-mocha` (replaced by canonical versions from alacritty-theme)
- Result: 13 total themes (2 custom + 11 community), all hardcoded, zero latency impact
- Create `ops/extract_themes.py` — converter script that reads alacritty-theme YAML, extracts colors, maps to statusline fields, derives model pill colors algorithmically, and generates Python code to append to `themes.py`

## Capabilities

### New Capabilities

None. Theme selection already exists and is governed by `statusline-config` specification.

### Modified Capabilities

None. No spec-level behavior changes—existing configuration precedence and theme resolution remain identical. We're expanding the available theme options, which is an implementation detail.

## Impact

- **Code**: `claude/yas/themes.py` (adds ~11 Theme instances), `ops/extract_themes.py` (new converter script, ~150 lines)
- **Dependencies**: None (colors extracted from alacritty-theme repo, not added as a dependency)
- **User-visible**: `THEMES` registry grows from 4 to 13 entries; users gain `dracula`, `gruvbox-dark`, `gruvbox-light`, `nord`, `one-dark`, `one-light`, `solarized-dark`, `solarized-light`, `tokyo-night`, `palenight` (plus existing `claude-dark`, `claude-light`)
- **Testing**: Visual validation via `make demo` for each of the 13 themes; hand-tweak model pill colors / gradients as needed
