## 1. Pre-edit baseline

- [ ] 1.1 Run `make test` and record pass count
- [ ] 1.2 Run `make demo` and confirm borders/elbows are clean

## 2. Newline stripping in tool-arg display

- [ ] 2.1 In `claude/yas/renderer.py` `subagent_activity`: after `raw = str(inp[key])`, add `raw = raw.split('\n')[0]`
- [ ] 2.2 In `claude/yas/renderer.py` `subagent_activity`: after `raw = str(next(iter(inp.values())))`, add `raw = raw.split('\n')[0]`
- [ ] 2.3 Add test in `test/test_subagent_rows.py`: tool arg with `\n` shows only first line

## 3. Remove debug logging

- [ ] 3.1 In `claude/yas/info/workflows.py` `_enrich`: restore `data = json.loads(json_path.read_text())` (remove `raw_text` variable and the `yas-wf-debug.json` write block)
- [ ] 3.2 In `claude/yas/info/workflows.py` `from_session`: remove the large debug `try:` block that writes `yas-wf-debug.json`

## 4. Phase parsing data layer

- [ ] 4.1 Add `_parse_script_phases(scripts_dir: Path, run_id: str) -> list[str]` to `claude/yas/info/workflows.py` (regex on `phases:\s*[...]` block, extract `title:` strings, return `[]` on any error)
- [ ] 4.2 Add `phases: list[str] = field(default_factory=list)` to `RunningWorkflow` dataclass
- [ ] 4.3 In `from_session`, after `cls._enrich(wf, session_dir)`, set `wf.phases = _parse_script_phases(session_dir / 'workflows' / 'scripts', wf.run_id)`
- [ ] 4.4 Add test in `test/test_workflow_cohort.py`: script with 3 phases → `wf.phases` has 3 titles in order
- [ ] 4.5 Add test: missing script → `wf.phases == []`, no exception

## 5. Phase list rendering in workflow header

- [ ] 5.1 Update `workflow_header` in `claude/yas/renderer.py` to render inline phase list when `run.phases` is non-empty
- [ ] 5.2 Current phase (matching `run.phase`) rendered with `SKILLS` colour and `❯` prefix; others `CTX_DIM`
- [ ] 5.3 When `run.phase` is empty, all phases rendered `CTX_DIM`, no `❯` marker
- [ ] 5.4 When `run.phases` is empty, fall back to existing `[phase]` bracket style
- [ ] 5.5 Phase list truncated with `…` when too wide rather than truncating the name below minimum
- [ ] 5.6 Add test in `test/test_workflow_cohort.py` or a new `test_workflow_header.py`: header with phases renders correct dim/highlight
- [ ] 5.7 Add test: header with empty phases falls back to bracket style

## 6. Two-column agent layout

- [ ] 6.1 In `build_workflow_rows` in `claude/yas/layout.py`, add two-column pairing branch: `if per_agent and width >= 160`
- [ ] 6.2 Each half gets `(inner - 5) // 2` columns (`inner = width - 4`)
- [ ] 6.3 Pair agents sequentially by `first_timestamp` order; odd agent rendered full-width
- [ ] 6.4 Right-pad each half to its column width using `_visible_width` before joining with `f'  {r.BORDER}│{r.R}  '`
- [ ] 6.5 Both halves rendered with `twoline=False`; `session_inout=0` unchanged
- [ ] 6.6 Add test in `test/test_layout_seam.py` or `test/test_subagent_rows.py`: width=160 → agents paired; width=159 → one per row

## 7. Post-edit verification

- [ ] 7.1 Run `make test` — pass count must be ≥ baseline plus new tests
- [ ] 7.2 Run `make demo` — confirm borders/elbows still align, pill flows correctly
- [ ] 7.3 If possible, observe a live workflow run in the statusline and confirm: phase list visible, no multi-line tool-arg bleed, two-column layout active at wide width
