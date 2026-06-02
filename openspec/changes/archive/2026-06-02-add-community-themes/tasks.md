## 1. Converter Script Development

- [x] 1.1 Create `ops/extract_themes.py` with color mapping logic
  - Read alacritty-theme YAML files
  - Map alacritty colors (normal/bright slots) → statusline fields per design
  - Generate Python Theme dataclass code
  - Mark complete when script runs without errors on one test theme
  
- [x] 1.2 Implement model pill color derivation algorithm
  - Extract bright/saturated colors from theme palette
  - Assign to model families (opus=yellow, sonnet=green, haiku=blue, other=magenta)
  - Generate anchor, warm_shift, cool_shift per model
  - Mark complete when script outputs valid ModelColors for all 4 models
  
- [x] 1.3 Test converter script on a few themes
  - Extract colors for dracula, gruvbox-dark, nord
  - Verify output is valid Python that appends to themes.py
  - Check for missing color errors in alacritty YAML
  - Mark complete when script successfully generates 3 themes without manual fixes

## 2. Theme Extraction & Integration (Can start after 1.3)

- [x] 2.1 Extract all 11 community themes using the converter script
  - Run `ops/extract_themes.py` with all 11 theme names
  - Verify all 11 themes extract successfully
  - Mark complete when script outputs all 11 themes with no errors
  
- [x] 2.2 Append extracted themes to `claude/yas/themes.py`
  - Insert generated code after existing claude-dark/light definitions
  - Verify Python syntax is valid (`python -m py_compile`)
  - Update `THEMES` registry to include all 13 themes
  - Mark complete when `import yas.themes` succeeds with all 13 in THEMES dict

- [x] 2.3 Remove catppuccin-latte and catppuccin-mocha from themes.py
  - Delete class definitions
  - Remove from THEMES registry
  - Verify no other code references these themes
  - Mark complete when tests run without references to catppuccin-latte/mocha

## 3. Visual Validation & Tweaking (Can happen in parallel with 2.2–2.3)

- [x] 3.1 Run demo for all 13 themes
  - `make demo` through each theme (narrow/medium/wide)
  - Check border alignment, color harmony, readability
  - Note which themes need model/gradient color adjustments
  - Mark complete when you've visually validated all 13 and identified tweaks needed

- [x] 3.2 Hand-tweak model pill colors / gradients for themes that need it
  - Edit `grad_stops`, `spec_gradients`, `models` in `themes.py` for flagged themes
  - Re-run `make demo` for each adjusted theme
  - Iterate until colors look good
  - Mark complete when all 13 themes pass visual review

## 4. Testing & Code Quality (Can start after 2.2)

- [x] 4.1 Run unit tests
  - `make test` (or `uv run pytest -q`)
  - Verify no regressions, all tests pass
  - Mark complete when test output shows 100% pass

- [x] 4.2 Verify theme resolution and config loading
  - Test that all 13 theme names are recognized by config resolution
  - Test CLI `--theme dracula`, env `YAS_THEME=nord`, config file `[appearance] theme = "tokyo-night"`
  - Mark complete when config tests pass for at least 3 of the new themes

## 5. Documentation & ADR Updates (Can happen in parallel with 3–4)

- [x] 5.1 Check ADR 0002 (theme system) for updates
  - If it lists available themes by name, update to mention "11 community themes from alacritty-theme"
  - Document that themes are hardcoded for latency (include benchmark ratios from grill-me)
  - Mark complete when ADR is reviewed and any updates are committed

- [x] 5.2 Document the converter script
  - Add usage example to `ops/README.md` or new `ops/THEMES.md`
  - Explain how to re-run on future alacritty-theme updates
  - Note the alacritty-theme commit SHA used
  - Mark complete when docs include command and example output

## 6. Finalization

- [ ] 6.1 Create git commit with all changes
  - Message: "Add 11 community themes from alacritty-theme"
  - Include reference to alacritty-theme commit used
  - Verify `make test` passes one final time
  - Mark complete when commit is created and branch is clean

- [ ] 6.2 (Optional) Open PR with `/yas-pr` skill
  - Or manually: `gh pr create --draft` and request review
  - Mark complete when PR is open and CI/checks pass
