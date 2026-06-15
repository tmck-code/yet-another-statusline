## 1. Pre-edit baseline

- [x] 1.1 Run `make test` and record pass count
- [x] 1.2 Run `make demo` and confirm borders/elbows are clean

## 2. Newline stripping in tool-arg display

- [x] 2.1 In `claude/yas/renderer.py` `subagent_activity`: after `raw = str(inp[key])`, add `raw = raw.split('\n')[0]`
- [x] 2.2 In `claude/yas/renderer.py` `subagent_activity`: after `raw = str(next(iter(inp.values())))`, add `raw = raw.split('\n')[0]`
- [x] 2.3 Add test in `test/test_subagent_rows.py`: tool arg with `\n` shows only first line

## 3. Remove debug logging

- [x] 3.1 In `claude/yas/info/workflows.py` `_enrich`: restore `data = json.loads(json_path.read_text())` (remove `raw_text` variable and the `yas-wf-debug.json` write block) — already clean in tree (no-op)
- [x] 3.2 In `claude/yas/info/workflows.py` `from_session`: remove the large debug `try:` block that writes `yas-wf-debug.json` — already clean in tree (no-op)

## 4. Phase parsing data layer

- [x] 4.1 Add `_parse_script_phases(scripts_dir: Path, run_id: str) -> list[str]` to `claude/yas/info/workflows.py` (regex on `phases:\s*[...]` block, extract `title:` strings, return `[]` on any error)
- [x] 4.2 Add `phases: list[str] = field(default_factory=list)` to `RunningWorkflow` dataclass
- [x] 4.3 In `from_session`, after `cls._enrich(wf, session_dir)`, set `wf.phases = _parse_script_phases(session_dir / 'workflows' / 'scripts', wf.run_id)`
- [x] 4.4 Add test in `test/test_workflow_cohort.py`: script with 3 phases → `wf.phases` has 3 titles in order
- [x] 4.5 Add test: missing script → `wf.phases == []`, no exception

## 5. Phase list rendering in workflow header

- [x] 5.1 Update `workflow_header` in `claude/yas/renderer.py` to render inline phase list when `run.phases` is non-empty
- [x] 5.2 Current phase (matching `run.phase`) rendered with `SKILLS` colour and `❯` prefix; others `CTX_DIM`
- [x] 5.3 When `run.phase` is empty, all phases rendered `CTX_DIM`, no `❯` marker
- [x] 5.4 When `run.phases` is empty, fall back to existing `[phase]` bracket style
- [x] 5.5 Phase list truncated with `…` when too wide rather than truncating the name below minimum
- [x] 5.6 Add test in `test/test_workflow_cohort.py` or a new `test_workflow_header.py`: header with phases renders correct dim/highlight
- [x] 5.7 Add test: header with empty phases falls back to bracket style

## 6. Two-column agent layout

- [x] 6.1 In `build_workflow_rows` in `claude/yas/layout.py`, add two-column pairing branch: `if per_agent and width >= 160`
- [x] 6.2 Each half gets `(inner - 5) // 2` columns (`inner = width - 4`)
- [x] 6.3 Pair agents sequentially by `first_timestamp` order; odd agent rendered full-width
- [x] 6.4 Right-pad each half to its column width using `_visible_width` before joining with `f'  {r.BORDER}│{r.R}  '`
- [x] 6.5 Both halves rendered with `twoline=False`; `session_inout=0` unchanged
- [x] 6.6 Add test in `test/test_layout_seam.py` or `test/test_subagent_rows.py`: width=160 → agents paired; width=159 → one per row

## 7. Post-edit verification

- [x] 7.1 Run `make test` — pass count must be ≥ baseline plus new tests (835 → 842, +7 new, zero failures)
- [x] 7.2 Run `make demo` — confirm borders/elbows still align, pill flows correctly
- [x] 7.3 If possible, observe a live workflow run in the statusline and confirm: phase list visible, no multi-line tool-arg bleed, two-column layout active at wide width — no live run available; verified equivalently via direct `workflow_header` render smoke checks (phase list visible, current-phase `❯` marker) and the new unit tests for newline-stripping and two-column pairing
