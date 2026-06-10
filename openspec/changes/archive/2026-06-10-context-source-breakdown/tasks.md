## 1. Research outcome (no implementation)

- [x] 1.1 Confirm the stdin `context_window` payload exposes no per-source breakdown (only totals + single `current_usage`).
- [x] 1.2 Confirm transcript `attributionSkill`/`attributionPlugin` attribute message usage to the active skill/plugin, not system-prompt composition.
- [x] 1.3 Record the data gap and feasible alternatives in `proposal.md` / `design.md`.

## 2. Deferral / follow-up

- [x] 2.1 Leave context rendering unchanged; do not ship an approximate by-source breakdown.
- [x] 2.2 If pursued later, open a separate change for one feasible alternative: per-skill/plugin cumulative attribution, or the cache-base vs fresh structural split.
- [x] 2.3 Revisit if Claude Code ever exposes a `/context`-style breakdown in the statusline payload.
