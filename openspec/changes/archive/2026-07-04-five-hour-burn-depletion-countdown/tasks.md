## 1. Pre-flight (skill checklist)

- [x] 1.1 Read `CONTEXT.md`; baseline `make test` (note pass count) and `make demo/img` + `.claude/skills/yas-demo-text/scripts/demo-text.sh` (capture `demo/text` as the before-baseline for the 5-hour cell)
- [x] 1.2 Run the PUA-glyph scan over the lines to be edited in `renderer.py:1567-1598` (the `helper`) — `GLYPH_UNLIMITED` sits nearby; hoist/import per the PUA rule if any edited line carries a raw glyph

## 2. Sampler + config (independently implementable)

- [x] 2.1 `constants.py`: add `DT_FLOOR = 60.0` (minimum sample-span guard, seconds) near the other rate/limit constants; add `DEFAULT_FIVE_HOUR_RATE_WINDOW = 300.0` if defaults live in `config.py` instead, add it there beside `DEFAULT_TOKEN_WINDOW`
- [x] 2.2 `config.py`: mirror `token_window` for `five_hour_rate_window` — add to `__slots__` (line ~341), the field annotation (~351), the `__init__` default-arg `five_hour_rate_window: float = DEFAULT_FIVE_HOUR_RATE_WINDOW` (~372), assign in `__init__` body, add the `_resolve('five_hour_rate_window', _env_sources(env, 'YAS_FIVE_HOUR_RATE_WINDOW', 'STATUSLINE_FIVE_HOUR_RATE_WINDOW') + toml_src(tokens, 'five_hour_rate_window'), _parse_pos_float, DEFAULT_FIVE_HOUR_RATE_WINDOW, errors, debug)` block (~473) and wire `five_hour_rate_window=five_hour_rate_window` into the `cls(...)` return (~539)
- [x] 2.3 `tokens.py`: add a lazy `@functools.cache`d `_five_hour_rate_window()` mirroring `_token_window` (`tokens.py:153-156`), reading `Config.load().five_hour_rate_window`
- [x] 2.4 `tokens.py`: add class `FiveHourRate` mirroring `TokenRate` (`tokens.py:159-201`) — `WINDOW: float | None = None`, `KEEP` set to `>= ` the max lookback (e.g. `600.0`), a classmethod `update(cls, resets_at: int, used_pct: float) -> float | None`. Bail to `None` when `resets_at == 0`. Read-modify-`write_text` `CLAUDE_DIR / 'statusline-5h-rate.log'` with rows `f'{ts:.3f} {resets_at} {used_pct}'`; on read, skip malformed rows and rows older than `KEEP`. Append the new `(now, resets_at, used_pct)`. Filter samples to rows whose stored `resets_at == resets_at` (current window) AND within the resolved window (`cls.WINDOW` or `_five_hour_rate_window()`). Sort by ts; if `< 2` samples or `(t_last - t_first) < DT_FLOOR` return `None`; else `rate = (used_last - used_first) / ((t_last - t_first) / 60)`; return `rate` if `> 0` else `None` (or `0.0` — the renderer treats non-positive/None identically). Swallow `OSError` on write like `TokenRate`
- [x] 2.5 `tokens.py`: add `'five_h_rate'` to `TickRecord.__slots__` (line 27) and a `five_h_rate: float | None = None` parameter to `TickRecord.__init__` (lines 29-32), assigning `self.five_h_rate = five_h_rate`
- [x] 2.6 `README.md`: add a knob-table row after line 77 — `` | `five_hour_rate_window` | `YAS_FIVE_HOUR_RATE_WINDOW` | `[tokens].five_hour_rate_window` | `300` | `STATUSLINE_FIVE_HOUR_RATE_WINDOW` | `` — and a `five_hour_rate_window = 300` line in the `[tokens]` example (~line 142)

## 3. Depletion math (pure helper, independently implementable)

- [x] 3.1 `render/metrics.py`: add `deplete_minutes(used_pct: float, rate_per_min: float | None) -> float | None` beside `burndown_delta` (line 8) — return `None` when `rate_per_min` is falsy/`None` or `<= 0`, else `(100 - used_pct) / rate_per_min`. No I/O, no `time` dependency

## 4. Render wiring + format (depends on 2 and 3)

- [x] 4.1 `app.py` `record_tick` (line 20): call `FiveHourRate.update(session.rate_limits.five_hour.resets_at, session.rate_limits.five_hour.used_percentage)` and pass the result as `five_h_rate=` into the `TickRecord(...)` construction (line 25). Import `FiveHourRate` from `yas.tokens` (line 16)
- [x] 4.2 `renderer.py` `helper` (line 1567): add a `five_h_rate: float | None = None` parameter (after `gap`). At the countdown build (line 1585-1588), compute `remain_min = total_s / 60` and `deplete_min = deplete_minutes(float(five_hour.used_percentage or 0), five_h_rate)`; when `deplete_min is not None and deplete_min < remain_min`, build the combined form using the same `divmod` floor as the reset countdown: `dtot = int(deplete_min * 60); dh, drem = divmod(dtot, 3600); dm = drem // 60`. Import `deplete_minutes` from `yas.render.metrics`
- [x] 4.3 `renderer.py` `helper` return (line 1596): when depletion shown, wrap only the depletion segment in a WARN colour and reset to `self.COMMIT` before the closing paren — `countdown = f'(-{h}:{m:02d}{warn}/-{dh}:{dm:02d}{self.COMMIT})'` where `warn = self.fill_colour(100.0)` (or the red end of the fill gradient); otherwise `countdown = f'(-{h}:{m:02d})'` unchanged. Keep the existing `f'{self.COMMIT}{countdown}{self.R}{sp}{pct_clr}...'` wrapper so the reset portion + parens stay in COMMIT
- [x] 4.4 `renderer.py` `_rate_helpers` (line 543): add `five_h_rate: float | None = None` param and forward it to `self.helper(rate_limits.five_hour, gap_5h, five_h_rate=five_h_rate)` (line 551)
- [x] 4.5 `renderer.py` `model_right_section` (line 567): add `five_h_rate: float | None = None` param and forward it to `self._rate_helpers(rate_limits, five_h_rate=five_h_rate)` (line 598)
- [x] 4.6 `layout.py` `build_wide`: pass `five_h_rate=tick.five_h_rate` into `r.model_right_section(...)` (line 423) and into the justify gap-widen re-call `r._rate_helpers(session.rate_limits, gap_5h, gap_7d, five_h_rate=tick.five_h_rate)` (line 545). Confirm medium/narrow builders (`model_right_section_compact` at lines 267/337) are untouched and never pass a rate

## 5. Tests

- [x] 5.1 `test/test_burndown.py`: unit-test `deplete_minutes` — positive rate → correct span (`(100-used)/rate`), `rate=None`/`0.0`/negative → `None`, `used_pct=100` with positive rate → `0.0`
- [x] 5.2 `test/test_burndown.py` (or `test_tokens_cost.py`): unit-test `FiveHourRate.update` using the `tmp_home` fixture — global keying (two different session ids for the same `resets_at` both contribute), `resets_at` rollover discards the stale series, `< 2` in-window samples → `None`, sub-`DT_FLOOR` span → `None`, rising usage over `>= DT_FLOOR` → positive %/min. Set `FiveHourRate.WINDOW` and monkeypatch `time.time` for deterministic spans
- [x] 5.3 `test/test_helper.py`: verify the no-depletion path is byte-identical — existing pins `(-1:00)`, `(-2:00)`, `(-0:45)` from `helper(bucket)` (no `five_h_rate`) still pass unchanged
- [x] 5.4 `test/test_helper.py`: add cases passing `five_h_rate=` to `helper` (monkeypatching `datetime.now`/`time.time` as the existing `_patch` helper does) — assert the combined `(-0:11/-0:04)` form renders when depletion < remain, the WARN colour wraps only the depletion segment, and it collapses to `(-H:MM)` when `deplete_min >= remain_min` or `five_h_rate is None`

## 6. Verification & docs

- [x] 6.1 `make test` green (baseline + new tests) via `verifier`
- [x] 6.2 `make demo/img` + `demo-text.sh` diff against the 6.1 baseline via `verifier` — 5-hour cell widens from `(-H:MM)` to `(-H:MM/-DH:DMM)`; confirm every `┬`/`│`/`┴` in the top row still aligns and no ANSI leaked into the column math (`_visible_width`, not `len()`)
- [x] 6.3 Update `CONTEXT.md` glossary for the new displayed term (the depletion / burn-rate countdown) and add the `five_hour_rate_window` knob to any config documentation table if one is duplicated there
