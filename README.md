# YAS! (Yet Another Statusline)

<img width="1685" height="320" alt="image" src="https://github.com/user-attachments/assets/516cb692-3318-4552-b813-e3e34ca96858" />

_Most common form is displaying these stats, which include the loaded plugins & skills. Extra sections appear as needed_

To install (note: currently requires a ["Nerd font"](https://www.nerdfonts.com/font-downloads) for the icons):

```shell
# to install to ~/.claude/
make install

# to install to another dir
CLAUDE_CONFIG_DIR=~/.claude_blah/ make install
```

This symlinks the files into your claude user dir, allowing you to easily update them via a `git pull`

## Demo

A dummy session to demonstrate the layout:

<img width="1524" height="530" alt="statusline-demo-1779720526" src="https://github.com/user-attachments/assets/6be6e870-5207-4737-89f4-b85723c86620" />

## Layout Reference

<img width="1835" height="884" alt="image" src="https://github.com/user-attachments/assets/4a410cd6-5afa-401d-b3f0-5b8726187a03" />

## Widths

The statusline also renders differently according to available width

| mode | width | screenshot |
|------|-------|------------|
| "medium" | <=80 pixels | <img width="839" height="122" alt="image" src="https://github.com/user-attachments/assets/56519acc-a65c-446a-a938-5a14f093c817" /> |
| "narrow" | <=55 pixels | <img width="537" height="120" alt="image" src="https://github.com/user-attachments/assets/7254cbb7-ea37-4f41-8adc-506cf6b48033" /> |

---

## Commands

To demo/test:

```bash
# animated demo
make demo

# screenshot demo - writes to demo/
make demo/img
```

## Claude Subscription Quota Mode

YAS can display an approximate **subscription quota gauge** instead of the per-session dollar cost rows. This is useful on flat-rate plans (Claude Pro, Max 5x, Max 20x) where dollar totals matter less than remaining headroom for the window.

### Why approximation?

Anthropic does not expose live quota data through the transcript API the way Codex rollouts do. YAS approximates usage from local session/day token totals against hardcoded plan ceilings. The ceilings are heuristic estimates based on Anthropic's "5x / 20x of Pro" framing — [check the current plan page](https://www.anthropic.com/pricing) and tune via env vars if the defaults diverge from your observed experience.

### Env-var contract

| Variable | Default | Description |
|---|---|---|
| `YAS_CLAUDE_MODE` | `cost` | `cost` = existing dollar rows · `quota` = subscription gauge |
| `YAS_CLAUDE_PLAN` | `max20` | `pro` · `max5` · `max20` |
| `YAS_CLAUDE_5H_CAP_TOKENS` | _(plan default)_ | Override the 5-hour window ceiling |
| `YAS_CLAUDE_WEEKLY_CAP_TOKENS` | _(plan default)_ | Override the weekly window ceiling |

### Plan ceilings (heuristic defaults)

| Plan | 5h cap | Weekly cap |
|---|---|---|
| `pro` | 1.5M tokens | 18M tokens |
| `max5` | 7.5M tokens | 90M tokens |
| `max20` | 30M tokens | 360M tokens |

### Quota gauge render

```
Wide:    󱙄 5h ▆▆░░░░░░ 24%  │  7d ▆░░░░░░░ 12%  │  max20x
Medium:  󱙄 5h 24% · 7d 12%
Narrow:  󱙄 5h 24%
```

Color thresholds: `< 60%` green · `60–85%` yellow · `> 85%` red (same as Codex gauge).

When `YAS_CLAUDE_MODE=quota`, the two cost rows are replaced by a single quota gauge row. The Codex gauge row (if Codex data is present) still appears beneath it.

### Example

```bash
YAS_CLAUDE_MODE=quota YAS_CLAUDE_PLAN=max20 python3 ~/.claude/statusline_command.py < session.json
```

---

## Codex Rate-Limit Gauge

A third row beneath the Claude cost rows shows your **Codex rate-limit window consumption** (rate limits, not dollars — Codex Pro is flat-rate).

```
  󰞬 5h ▆░░░░░░░ 12%  │  7d ▆▆░░░░░░ 28%  │  pro
```

- Reads from `~/.codex/sessions/<YYYY>/<MM>/<DD>/rollout-*.jsonl`
- Override the sessions root with `YAS_CODEX_SESSIONS_DIR`
- Shows the **5-hour** and **7-day** window consumption percentages
- Color thresholds: `< 60%` green · `60–85%` yellow · `> 85%` red
- If the latest rollout is older than 1 hour, a `(stale Xh)` indicator appears
- Narrows gracefully: medium width shows both percentages without bars; narrow shows only the 5h window
- If no Codex session data is found, renders `no codex data` in dim grey

