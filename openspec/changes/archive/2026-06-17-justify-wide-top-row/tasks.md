## 1. Config wiring

- [x] 1.1 Add `DEFAULT_JUSTIFY = False` constant to `yas/constants.py`
- [x] 1.2 Add `justify: bool = DEFAULT_JUSTIFY` field to the `Config` dataclass in `yas/config.py`
- [x] 1.3 Wire `justify` into `Config.load`: resolve from `YAS_JUSTIFY` env var and `[layout].justify` TOML key using `_parse_bool` / `_env_sources` / `toml_src`
- [x] 1.4 Add `justify` to the `cls(...)` constructor call at the end of `Config.load`

## 2. Justify layout logic in build_wide

- [x] 2.1 After `line_path` and `path_w` are computed, compute `total_slack = target_w - path_w` and short-circuit to normal layout when `cfg.justify` is false or `total_slack == 0`
- [x] 2.2 Count active sections N: always 3 (path + helper + last-slot), +1 for elapsed, +1 for cache
- [x] 2.3 Compute `extra_per = total_slack // N` and `remainder = total_slack % N`; build a list of per-section extras using `extra_per + (1 if i < remainder else 0)`
- [x] 2.4 Apply path extra: append `path_extra` trailing spaces to `line_path` (or a separate `path_pad` string inserted before `vsep`)
- [x] 2.5 Apply elapsed extra (when active): prepend `e_left = extra // 2` spaces and append `e_right = extra - e_left` spaces around `elapsed_content`
- [x] 2.6 Apply helper extra: prepend `h_left = extra // 2` and append `h_right = extra - h_left` spaces around `helper_text`
- [x] 2.7 Apply cache extra (when active): prepend `c_left = extra // 2` and append `c_right = extra - c_left` spaces around `cache_content`
- [x] 2.8 Apply last-slot extra: in non-pill mode add to `pad`; in pill mode append spaces to `middle` before the pill branch

## 3. Divider column adjustment

- [x] 3.1 Shift `path_div_col` by `path_extra` after applying path padding
- [x] 3.2 Shift `elapsed_div_col` by `path_extra + elapsed_extra` (left + right combined)
- [x] 3.3 Shift `sep_rate_col` by the cumulative column offset up to and including `h_left` of the helper section
- [x] 3.4 Shift `cache_div_col` by the cumulative offset of all preceding sections' extras
- [x] 3.5 Verify all shifted columns are used in the re-computed `path_row_cols` list passed to `path_row_downs` / `path_row_ups`

## 4. Tests

- [x] 4.1 Add tests to `test/test_config.py`: `YAS_JUSTIFY=1` enables justify, `YAS_JUSTIFY=0` disables, `[layout].justify = true` in TOML enables, env overrides TOML, invalid value falls back to false
- [x] 4.2 Add tests to `test/test_layout_seam.py` (or a new `test_justify.py`): verify that with `cfg.justify=True` and known `total_slack`, the content row visible width equals `width - border_overhead` and all section extras sum to `total_slack`
- [x] 4.3 Add scenario: `total_slack == 0` with justify enabled produces output identical to justify-disabled
- [x] 4.4 Add scenario: N=3 (no elapsed, no cache) distributes slack across 3 sections correctly

## 5. Visual verification

- [x] 5.1 Run `make test` and confirm all tests pass (count matches baseline + new tests)
- [x] 5.2 Run `make demo` and confirm border elbows align correctly at all width thresholds with `YAS_JUSTIFY=1`
- [x] 5.3 Confirm pill mode renders correctly in justify mode by checking the pill stays flush-right
