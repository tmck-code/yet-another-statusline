# Prototype — statusline layout exploration

**Question (tmck01, 2026-06-06):** rethink the wide-layout arrangement —
context bar needn't span the full row; is the double-height token/cost block
right; do daily counts belong there or in their own section; the t/m sparkline
is too wide (~60s is enough); subagents + plans could share a row; drop the
per-subagent t/m; is there a better arrangement for openspec name/numbers.

**Artifact:** `ops/prototype_layouts.py` — throwaway switcher. Static mockups,
NOT wired into the real renderer. `uv run python ops/prototype_layouts.py [A|B|C|D]`.

## The four variants (each takes a coherent stance)

- **A — Dense Cockpit.** Context bar shares its row with the 5h/7d limit chips
  (bar no longer spans full width). Tokens go *single-height* (session only) on
  one row beside a 60s spark. Plans (left) | subagents (right) share one row.
  Per-subagent t/m dropped. Daily totals + cost demoted to a single dim footer.
- **B — Two-Pane.** Vertical split: telemetry left (context, limits, session
  tokens, rate, daily), work-in-flight right (subagents stacked over openspec
  plans). Plans become `◆ name … pct bar`.
- **C — Stacked Minimal.** One line per concern. *All* telemetry collapses to a
  single status line. openspec re-arranged so **pct + bar lead** and the name
  trails (scan the progress column, not the names). Subagents = one compact row.
- **D — Daily-as-own-section.** Rich "now" block up top; **all** daily stats
  boxed off in their own clearly-separated section at the bottom. Plans render
  `name bar pct`; subagents `▶ type description`.

## How each addresses the asks

| ask                              | A            | B          | C            | D            |
|----------------------------------|--------------|------------|--------------|--------------|
| context bar not full-width       | shares w/limits | left pane | inline       | still wide   |
| kill double-height tokens        | yes (1 row)  | yes        | yes (1 line) | yes (1 row)  |
| daily in own place               | dim footer   | left, dim  | dim footer   | own section  |
| 60s sparkline                    | yes          | tiny       | dropped      | yes          |
| plans + subagents share a row    | yes          | same pane  | adjacent     | yes          |
| drop per-subagent t/m            | yes          | yes        | yes          | yes          |
| openspec re-arranged             | name+nums    | pct-bar R  | **pct-bar leads** | bar+pct |

## Verdict

_TODO (tmck01): which variant wins, and which bits to graft from the others?_
_The interesting answer is usually "header from X, the plans row from Y."_
_Once decided: fold into `layout.py` build_wide + `renderer.py` helpers, then_
_delete `ops/prototype_layouts.py` and this file._
