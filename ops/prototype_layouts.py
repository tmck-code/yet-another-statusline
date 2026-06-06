#!/usr/bin/env python3
"""PROTOTYPE — throwaway statusline layout explorer. DELETE ME once a layout wins.

Question being answered (from tmck01, 2026-06-06):
  Rethink the wide-layout arrangement. Specifically:
    - context fill bar need not span the whole row — what shares its row?
    - is the double-height session/daily token+cost block the right shape?
      do daily counts belong there, or in their own section?
    - the t/m sparkline is too wide — ~60s is enough
    - subagents + plans could share one row (plans left, subagents right)
    - drop the per-subagent t/m figure
    - openspec "name left / numbers right" — is there a better arrangement?

This paints SEVERAL radically different static mockups from fixed kitchen-sink
data. It is NOT wired into yas/renderer.py — the real renderer has hand-tuned
column math; here we only care about *arrangement*. Approximate is the point.

Run:
    uv run python ops/prototype_layouts.py          # print every variant
    uv run python ops/prototype_layouts.py B         # just variant B
    COLUMNS=110 uv run python ops/prototype_layouts.py

The switcher == the CLI arg (terminal equivalent of ?variant=).
"""
from __future__ import annotations

import os
import re
import shutil
import sys

_ANSI = re.compile(r'\x1b\[[0-9;]*m')


def vlen(s: str) -> int:
    return len(_ANSI.sub('', s))


def vtrim(s: str, w: int) -> str:
    """Truncate to visible width w, preserving (never slicing) ANSI escapes."""
    out, seen, i = [], 0, 0
    while i < len(s) and seen < w:
        m = _ANSI.match(s, i)
        if m:
            out.append(m.group())
            i = m.end()
            continue
        out.append(s[i])
        seen += 1
        i += 1
    out.append(s[i:] if _ANSI.match(s, i) else '')  # trailing reset if any
    return ''.join(out)

# ── faux palette (kept tiny; structure matters, not colour) ──────────────────
DIM    = '\x1b[2m'
BOLD   = '\x1b[1m'
RESET  = '\x1b[0m'
BORDER = '\x1b[38;2;120;128;140m'
ACCENT = '\x1b[38;2;147;164;143m'
WARN   = '\x1b[38;2;200;160;110m'

# plain BMP glyphs only — no PUA, so this survives chat/agent round-trips and
# renders in any terminal. (Real statusline uses Nerd Font icons in these slots.)
SID    = '51e977df'
PATH   = '~/my-project ∈ demo/3219308b1'
MODEL  = 'Opus 4.7 · high'

# fixed sample state lifted from demo/kitchen-sink.txt
CTX_PCT, CTX_TOK = 58, '150K'
FIVE_H, SEVEN_D  = '5h -02% T-2:00', '7d 49% -49%'
SESS_IN, SESS_OUT, SESS_COST = '155.8K', '18.0K', '$6.15'
DAY_IN,  DAY_OUT,  DAY_COST  = '8.4M', '1.5M', '$560.31'
ELAPSED, TPM = '0:13:27', '74.6K t/m'
SPARK60 = '▁▂▅▇▆▃▂▁▁▂▃▅▆▇▆▄▂▁'          # ~60s worth, short

PLANS = [   # (name, done, total, pct)
    ('add-gradient-engine',     6, 8, 75),
    ('port-statusline-to-py',   3, 8, 37),
    ('wire-alert-mode-pill',    1, 6, 16),
]
SUBAGENTS = [   # (type, description, tool, tokens)
    ('claude',  'Review border math',   'Read', '5.4K'),
    ('general', 'Fix sparkline buckets', 'Edit', '8.7K'),
    ('explore', 'Search token tracking', 'Bash', '3.2K'),
]


def width() -> int:
    return min(int(os.environ.get('COLUMNS', 92) or 92), 120)


def bar(pct: int, n: int) -> str:
    fill = round(pct / 100 * n)
    return '█' * fill + '░' * (n - fill)


# ── box primitives ───────────────────────────────────────────────────────────
def _pad(s: str, w: int) -> str:
    d = w - vlen(s)
    return s + ' ' * d if d >= 0 else vtrim(s, w)


def top(w: int, tag: str = '') -> str:
    label = f'──{tag}' if tag else ''
    return f'{BORDER}╭{label}{"─" * (w - 2 - len(label))}╮{RESET}'


def bot(w: int) -> str:
    return f'{BORDER}╰{"─" * (w - 2)}╯{RESET}'


def sep(w: int, dashed: bool = False) -> str:
    ch = '┄' if dashed else '─'
    return f'{BORDER}├{ch * (w - 2)}┤{RESET}'


def row(body: str, w: int, style: str = '') -> str:
    inner = _pad(body, w - 4)
    return f'{BORDER}│{RESET} {style}{inner}{RESET} {BORDER}│{RESET}'


def two_col(left: str, right: str, w: int, split: int) -> str:
    lw = split - 3
    rw = w - split - 2
    l = _pad(left, lw)
    r = _pad(right, rw)
    return f'{BORDER}│{RESET} {l}{BORDER}│{RESET} {r}{BORDER}│{RESET}'


def split_sep(w: int, split: int, kind: str) -> str:
    # kind: 'top' (┬), 'bot' (┴)
    j = {'top': '┬', 'bot': '┴'}[kind]
    return f'{BORDER}├{"─" * (split - 1)}{j}{"─" * (w - split - 1)}┤{RESET}'


# ── VARIANT A — Dense Cockpit ────────────────────────────────────────────────
# Consolidate hard. Context bar shares its row with the rate limits. Tokens go
# single-height (session only) next to a 60s spark. Plans|subagents share a row.
# Daily totals + cost demoted to one dim footer line.
def variant_a(w: int) -> list[str]:
    out = [top(w, SID), row(f'{PATH}{" " * 4}{ACCENT}{MODEL}{RESET}', w)]
    out.append(sep(w, dashed=True))
    out.append(row(f'ctx {CTX_PCT}%  {bar(CTX_PCT,14)} {CTX_TOK}    {DIM}│{RESET}  '
                   f'{FIVE_H}    {DIM}│{RESET}  {SEVEN_D}', w))
    out.append(sep(w, dashed=True))
    out.append(row(f'↓{SESS_IN} ↑{SESS_OUT}  {ACCENT}{SESS_COST}{RESET}   {DIM}│{RESET}  '
                   f'{TPM}  {SPARK60} {DIM}(60s){RESET}', w))
    out.append(sep(w))
    split = w // 2 + 2
    out.append(two_col(f'{BOLD}PLANS{RESET}', f'{BOLD}SUBAGENTS{RESET}', w, split))
    for i in range(3):
        n, d, t, p = PLANS[i]
        a_t, a_d, a_tool, a_tok = SUBAGENTS[i]
        out.append(two_col(f'{_pad(n,21)} {d}/{t} {p:>2}%',
                           f'▶ {a_t} · {a_tool} {a_tok}', w, split))
    out.append(sep(w))
    out.append(row(f'{DIM}today  ↓{DAY_IN} ↑{DAY_OUT} · {DAY_COST} · {ELAPSED} elapsed{RESET}', w))
    out.append(bot(w))
    return out


# ── VARIANT B — Two-Pane ─────────────────────────────────────────────────────
# Vertical split down the middle. Left pane = telemetry (context, limits,
# session tokens, rate, daily). Right pane = work-in-flight (subagents up top,
# openspec plans below). Plans become "name … pct bar" right-aligned.
def variant_b(w: int) -> list[str]:
    split = w // 2
    out = [top(w, SID), row(f'{PATH}{" " * 4}{ACCENT}{MODEL}{RESET}', w)]
    out.append(split_sep(w, split, 'top'))
    L = [
        f'context  {CTX_PCT}%  {bar(CTX_PCT,9)}  {CTX_TOK}',
        f'limits   {FIVE_H}   {SEVEN_D}',
        f'session  ↓{SESS_IN} ↑{SESS_OUT}  {ACCENT}{SESS_COST}{RESET}',
        f'rate     {TPM} {SPARK60[:12]}',
        f'{DIM}{"·" * (split - 5)}{RESET}',
        f'{DIM}today  ↓{DAY_IN} ↑{DAY_OUT}  {DAY_COST}{RESET}',
        f'{DIM}elapsed  {ELAPSED}{RESET}',
    ]
    R = [
        f'▶ {SUBAGENTS[0][0]} · {SUBAGENTS[0][1]}  {SUBAGENTS[0][3]}',
        f'▶ {SUBAGENTS[1][0]} · {SUBAGENTS[1][1]}  {SUBAGENTS[1][3]}',
        f'▶ {SUBAGENTS[2][0]} · {SUBAGENTS[2][1]}  {SUBAGENTS[2][3]}',
        '',
    ]
    for n, d, t, p in PLANS:
        R.append(f'◆ {_pad(n,22)} {p:>2}% {bar(p,8)}')
    for i in range(max(len(L), len(R))):
        out.append(two_col(L[i] if i < len(L) else '',
                           R[i] if i < len(R) else '', w, split))
    out.append(bot(w))
    return out


# ── VARIANT C — Stacked Minimal ──────────────────────────────────────────────
# One line per concern, nothing double-height. The whole telemetry block
# collapses to a SINGLE status line. openspec re-arranged: pct + bar LEAD, name
# trails (scan the progress column, not the names). Subagents = one compact row.
def variant_c(w: int) -> list[str]:
    out = [top(w, SID), row(f'{PATH}{" " * 4}{ACCENT}{MODEL}{RESET}', w)]
    out.append(sep(w, dashed=True))
    out.append(row(f'⬡ {CTX_PCT}% {bar(CTX_PCT,6)} {CTX_TOK} {DIM}·{RESET} '
                   f'{FIVE_H} {DIM}·{RESET} ↓{SESS_IN} ↑{SESS_OUT} '
                   f'{ACCENT}{SESS_COST}{RESET} {DIM}·{RESET} {TPM}', w))
    out.append(sep(w))
    for n, d, t, p in PLANS:
        out.append(row(f'{p:>3}% {bar(p,10)}  {_pad(n,24)} {DIM}{d}/{t}{RESET}', w))
    agents = '   '.join(f'▶ {a[0]} {DIM}{a[2].lower()}{RESET}' for a in SUBAGENTS)
    out.append(row(agents, w))
    out.append(sep(w, dashed=True))
    out.append(row(f'{DIM}today ↓{DAY_IN} ↑{DAY_OUT} · {DAY_COST} · {ELAPSED}{RESET}', w))
    out.append(bot(w))
    return out


# ── VARIANT D — Daily-as-own-section ─────────────────────────────────────────
# Keeps a richer "now" block but pulls ALL daily stats into a clearly separate
# boxed-off section at the very bottom (answers "could daily go in its own
# section"). openspec plans rendered vertically: name as a heading, bar beneath.
def variant_d(w: int) -> list[str]:
    out = [top(w, SID), row(f'{PATH}{" " * 4}{ACCENT}{MODEL}{RESET}', w)]
    out.append(sep(w, dashed=True))
    out.append(row(f'context  {CTX_PCT}%  {bar(CTX_PCT,20)}  {CTX_TOK}   '
                   f'{DIM}{FIVE_H}  {SEVEN_D}{RESET}', w))
    out.append(sep(w, dashed=True))
    out.append(row(f'now  ↓{SESS_IN} ↑{SESS_OUT}  {ACCENT}{SESS_COST}{RESET}   '
                   f'{TPM} {SPARK60}', w))
    out.append(sep(w))
    split = w // 2 + 2
    out.append(two_col(f'{BOLD}plans{RESET}', f'{BOLD}subagents{RESET}', w, split))
    for i in range(3):
        n, d, t, p = PLANS[i]
        a = SUBAGENTS[i]
        out.append(two_col(f'{_pad(n,18)} {bar(p,8)} {p:>2}%',
                           f'▶ {a[0]} {DIM}{a[1][:18]}{RESET}', w, split))
    out.append(sep(w))
    out.append(row(f'{DIM}{BOLD}TODAY{RESET}{DIM}   input ↓{DAY_IN}   output ↑{DAY_OUT}'
                   f'   cost {DAY_COST}   elapsed {ELAPSED}{RESET}', w))
    out.append(bot(w))
    return out


VARIANTS = {
    'A': ('Dense Cockpit — consolidate; ctx+limits share a row, single-height '
          'tokens+60s spark, plans|subagents share a row, daily in dim footer',
          variant_a),
    'B': ('Two-Pane — vertical split: telemetry left, work-in-flight right '
          '(subagents over plans)', variant_b),
    'C': ('Stacked Minimal — one line per concern, telemetry collapsed to one '
          'line, openspec pct+bar leads the name', variant_c),
    'D': ('Daily-as-own-section — rich "now" block, ALL daily stats boxed off '
          'at the bottom', variant_d),
}


def show(key: str, w: int) -> None:
    desc, fn = VARIANTS[key]
    print('\n'*int(shutil.get_terminal_size().lines/3))
    print(f'\n{BOLD}── Variant {key} ──{RESET} {DIM}{desc}{RESET}\n')
    print('\n'.join(fn(w)))


def main() -> None:
    w = width()
    arg = sys.argv[1].upper() if len(sys.argv) > 1 else None
    if arg and arg in VARIANTS:
        show(arg, w)
    else:
        for key in VARIANTS:
            os.system('clear -x')
            show(key, w)
            input()
    print(f'\n{DIM}switch: uv run python ops/prototype_layouts.py <A|B|C|D>   '
          f'(width {w}; set COLUMNS= to resize){RESET}\n')


if __name__ == '__main__':
    main()
