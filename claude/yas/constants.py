"""Constants shared across the statusline package."""

from __future__ import annotations
import os
import re
from pathlib import Path


HOME       = Path(os.path.expanduser('~'))
CLAUDE_DIR = Path(os.environ.get('CLAUDE_CONFIG_DIR', str(HOME / '.claude')))
MIN_WIDTH    = 40
DEFAULT_MAX_WIDTH    = 140
DEFAULT_SOFT_LIMIT   = 150_000
DEFAULT_TOKEN_WINDOW = 60.0
DEFAULT_THEME        = 'claude-dark'
DEFAULT_SHOW_DAY_STATS = True
DEFAULT_JUSTIFY        = False
DEFAULT_LABELS         = False
# Context-state word (ported from Dumbometer, MIT). Opt-in: off by default so
# the context line's byte output is unchanged unless explicitly enabled.
DEFAULT_CONTEXT_STATE      = False
DEFAULT_CONTEXT_LABELS:     tuple[str, ...] = ('Smart', 'Coasting', 'Foggy', 'Cooked', 'Dumb')
DEFAULT_CONTEXT_THRESHOLDS: tuple[int, ...] = (25, 50, 70, 90)
NARROW_WIDTH = 55
MEDIUM_WIDTH = 80
# Box width at/above which the wide layout's workflow cohort pairs agents into
# two side-by-side columns (each ~half the inner width minus the 5-col divider).
# Below this the agents stack single-column. Set under DEFAULT_MAX_WIDTH=140 so
# the two-column layout is actually reachable in a default-config wide terminal.
TWO_COL_WF_WIDTH = 120
# Floor for the wide layout's three-segment tokens │ cost │ rate row. Below this
# the row cannot hold both columns at full size plus the rate/spark leader, so
# build_wide drops it for the compact context line instead of overflowing the
# box. The exact, content-aware minimum is computed per-render by
# Renderer.tokens_cost (its ``min_width`` return) — this constant is the
# realistic-widest floor (the wide layout owns box >= MEDIUM_WIDTH=80, and the
# row first fits around box 84-85 for typical 6-7 digit token magnitudes).
TOKENS_COST_MIN_WIDTH = 85

# Minimum gap between the narrow tasks-header's left cluster (glyph + done/total)
# and its right-anchored active-task timer. The timer is flush to the content
# edge to use the otherwise-dead trailing space as a second anchor (mirroring the
# subagent rows' two-anchor read); this floor guarantees a readable separation
# and triggers the middle-ellipsis fallback before left + timer would collide.
TASK_HEADER_RIGHT_GAP_MIN = 2
_ANSI_RE   = re.compile(r'\x1b\[[0-9;]*m')

# Terminal control characters: C0 (0x00-0x08, 0x0b-0x1f), DEL (0x7f), and C1
# (0x80-0x9f). This range includes ESC (0x1b) and BEL (0x07) — the introducers
# and terminators for OSC/CSI sequences — so stripping it neutralizes OSC-52
# clipboard writes, OSC-0/2 title spoofs, and any other escape injection from
# untrusted input. TAB (0x09) and LF (0x0a) are deliberately preserved.
_CTRL_RE = re.compile(r'[\x00-\x08\x0b-\x1f\x7f-\x9f]')


def _sanitize(s: str) -> str:
    """Strip terminal control characters from an untrusted, host-/repo-supplied
    string at capture time, before it can reach stdout. Printable text
    (including non-ASCII/CJK) passes through byte-for-byte unchanged."""
    return _CTRL_RE.sub('', s)

FIVE_HOUR_MINUTES        = 300
SEVEN_DAY_MINUTES        = 10080
FIVE_HOUR_WARMUP_MINUTES = 5
SEVEN_DAY_WARMUP_MINUTES = 30

CACHE_TTL_SECONDS    = 300
CACHE_TTL_1H_SECONDS = 3600


class BarChars:
    FILLED = '█'
    HEAVY  = '▆'
    MID    = ''
    EMPTY  = '░'


RESET  = '\033[0m'
BOLD   = '\033[1m'
FAINT  = '\033[2m'
ITALIC = '\033[3m'

# Tools excluded from the per-tool tool_use counts row: todo/UI-plumbing tools,
# not "work". `Task` is deliberately NOT in this set — it represents a subagent
# delegation and is a meaningful main-column entry.
META_EXCLUDE_TOOLS = frozenset({'TodoWrite', 'ExitPlanMode', 'AskUserQuestion'})

# Plain-ASCII caption for the tool-counts separator. The label overlay applies
# superscript() at render time, so no raw superscript glyphs live in source.
TOOL_COUNTS_LABEL = 'tools main/sub'

CLR_GREY_DIM   = '\033[38;5;244m'
CLR_GREY_DARK  = '\033[38;5;238m'
CLR_BORDER_OFF = '\033[38;5;242m'
CLR_SKY_BLUE   = '\033[38;5;75m'
CLR_GREEN_OK   = '\033[38;5;114m'
CLR_GREEN_DIM  = '\033[38;5;77m'
CLR_GREEN_BRT  = '\033[38;5;46m'
CLR_PURPLE     = '\033[38;5;183m'
CLR_GOLD       = '\033[38;5;222m'
CLR_YELLOW     = '\033[38;5;226m'
CLR_YELLOW_BRT = '\033[38;5;11m'
CLR_CYAN       = '\033[38;5;116m'
CLR_CYAN_DIM   = '\033[38;5;244m'
CLR_CYAN_DAY   = '\033[38;5;109m'
CLR_CYAN_DAY_DIM = '\033[38;5;240m'
CLR_CYAN_ICON  = '\033[38;5;117m'
CLR_PINK       = '\033[38;5;210m'
CLR_PEACH      = '\033[38;5;216m'
CLR_WHITE_BRT  = '\033[38;5;15m'
CLR_WARN       = '\033[38;5;214m'
CLR_ALERT      = '\033[38;5;167m'

# Nerd Font Private Use Area glyphs. Encoded as escapes so Edit, diff, and
# chat round-trips never lose the bytes. Render only in a Nerd-Font-capable
# terminal.
ICON_COST           = '\uefc8' # nf-md currency-usd (cost row)
GLYPH_BURN_FAST     = '\uef76' # nf-cod-zap         (shown when the burn rate is too fast)
GLYPH_BURN_SLOW     = '\uf490' # nf-oct-flame       (shown when the burn rate is _not_ too fast)
GLYPH_FOLDER        = '\uef85' # nf-custom folder   (path row)
GLYPH_SUBAGENT      = '\uf135' # nf-fa-tasks        (subagent list)
GLYPH_SUBAGENT_ROW  = '\u25b6' # U+25B6             (per-row Running Subagent marker)
GLYPH_SUBAGENT_DONE = '\u2713' # U+2713             (Done subagent row marker)
GLYPH_PLUGINS       = '\uf1e6' # nf-fa-plug         (plugins label)
GLYPH_HELPER        = '\uf4cd' # nf-mdi-star_circle (5h rate-limit helper)
ICON_TOK_RATE       = '\U000f18a7'  # nf-md gauge         (t/m rate label)
GLYPH_MODEL         = '\U000f08b9' # nf-md-monitor-dashboard
GLYPH_THINKING      = '\U000f1a53' # nf-md-brain
GLYPH_TASKS         = '\U000f08a8'  # nf-md-clipboard-check-outline (Task Row marker)
GLYPH_TASK_PENDING  = '\ue640'      # nf-fa-circle_o          (pending task)
GLYPH_TASK_ACTIVE   = '\U000f0117'  # nf-md-arrow_right_thick (in_progress task)
GLYPH_TASK_DONE     = '\uf4a7'      # nf-oct-check_circle_fill (completed task)
GLYPH_SKILLS        = '\U000f07df'  # nf-md skills        (skills label)
GLYPH_TRASH         = '\U000f0a7a' # nf-md-trash_can     (git deleted count)
GLYPH_RENAMED       = '\U000f1031' # nf-md-file_move     (git renamed count)
GLYPH_CONTINUATION  = '└'  # U+2514 BOX DRAWINGS LIGHT UP AND RIGHT
GLYPH_REPLYING      = '\U000f0189'  # nf-md-message  (replying state)
GLYPH_HOURGLASS     = '\uf253' # nf-fa-hourglass_half (subagent context size)
GLYPH_PIE           = '\uf200' # nf-fa-pie_chart     (subagent session share)
GLYPH_CONFIG_WARN   = '\u26a0' # U+26A0 WARNING SIGN (config-error row marker)
GLYPH_CACHE         = '\uf49b'  # nf-oct-cache  (cache countdown)
GLYPH_WF_HEADER     = '\u25b8'  # \u25b8 U+25B8 BLACK RIGHT-POINTING SMALL TRIANGLE (workflow run header)
GLYPH_WF_SUMMARY    = '\u2514'  # \u2514 U+2514 BOX DRAWINGS LIGHT UP AND RIGHT (workflow run summary)
GLYPH_WF_CURRENT    = '\u276f'  # \u276f U+276F HEAVY RIGHT-POINTING ANGLE QUOTATION MARK ORNAMENT (current-phase marker)
GLYPH_WF_DIVIDER    = '\u250a'  # \u250a U+250A BOX DRAWINGS LIGHT QUADRUPLE DASH VERTICAL (two-column workflow divider)
GLYPH_CLEAR         = '\U000f0450'  # nf-md-refresh             (since-last-/clear timer)
ICON_LIMIT_5H       = '\U000f051b'  # nf-md-timer_outline       (5-hour rate-limit icon)
ICON_LIMIT_7D       = '\U000f0a34'  # nf-md-calendar_week_begin (7-day rate-limit icon)
GLYPH_MODEL_LIGHT   = '\U000f1a51'  # nf-md-lightbulb_on_40     (single model-pill glyph)
SEP_RATE            = GLYPH_WF_DIVIDER  # \u250a rate-limit separator (same codepoint as the workflow divider)

# Token-rate direction arrows (t/m row). Each is paired with a trailing space by
# the caller to a fixed 2 visible columns: the heavy arrows show when that
# direction is recently active, the plain arrows otherwise. The heavy arrows are
# Supplemental Arrows-C (EAW=N, so 1 col \u2014 see render.text._is_wide); the plain
# arrows are 1 col too, so both forms measure 2 cols with the trailing space.
ARROW_IN_ACTIVE  = '\U0001f847'  # \ud83e\udc47 heavy downwards arrow (billed-in recently active)
ARROW_IN_IDLE    = '\u2193'      # \u2193 U+2193 downwards arrow
ARROW_OUT_ACTIVE = '\U0001f845'  # \ud83e\udc45 heavy upwards arrow (output recently active)
ARROW_OUT_IDLE   = '\u2191'      # \u2191 U+2191 upwards arrow

MIDDLE_DOT    = '\u00b7'  # \u00b7 U+00B7 MIDDLE DOT (generic separator)
WF_PHASE_DOT  = MIDDLE_DOT  # workflow phase-trail separator (alias of MIDDLE_DOT)

# Model-effort pill quadrant/half glyphs (render/pill.py). All width-1.
PILL_TL    = '\u2597'  # U+2597 lower-right quadrant
PILL_TOP   = '\u2584'  # U+2584 lower half block
PILL_TR    = '\u2596'  # U+2596 lower-left quadrant
PILL_LEFT  = '\u2590'  # U+2590 right half block
PILL_RIGHT = '\u258c'  # U+258C left half block
PILL_BL    = '\u259d'  # U+259D upper-right quadrant
PILL_BOT   = '\u2580'  # U+2580 upper half block
PILL_BR    = '\u2598'  # U+2598 upper-left quadrant

# Box-drawing frame glyphs (used by borders.py / layout.py for the box outline,
# elbows, and inline dividers). All width-1; ascii mode maps each to a single
# ascii char so the hand-tuned column math survives.
BOX_H       = '\u2500'  # U+2500 light horizontal
BOX_V       = '\u2502'  # U+2502 light vertical
BOX_H_DASH  = '\u2504'  # U+2504 light triple-dash horizontal
BOX_T_RIGHT = '\u251c'  # U+251C vertical and right
BOX_T_LEFT  = '\u2524'  # U+2524 vertical and left
BOX_T_DOWN  = '\u252c'  # U+252C down and horizontal (top elbow)
BOX_T_UP    = '\u2534'  # U+2534 up and horizontal (separator elbow)
BOX_CROSS   = '\u253c'  # U+253C vertical and horizontal
BOX_ARC_TL  = '\u256d'  # U+256D arc down and right (top-left corner)
BOX_ARC_TR  = '\u256e'  # U+256E arc down and left (top-right corner)
BOX_ARC_BR  = '\u256f'  # U+256F arc up and left (bottom-right corner)
BOX_ARC_BL  = '\u2570'  # U+2570 arc up and right (bottom-left corner)

# Inline symbols rendered in section text (renderer.py). All width-1.
GLYPH_UNTRACKED = '\u2022'  # U+2022 bullet (untracked git count marker)
ELLIPSIS        = '\u2026'  # U+2026 horizontal ellipsis (text truncation)
GLYPH_IN        = '\u2208'  # U+2208 element-of (path/branch separator)
GLYPH_UNLIMITED = '\u221e'  # U+221E infinity (unlimited rate limit)
SPARK_RAMP      = '\u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588'  # U+2581..U+2588 sparkline density ramp

# ASCII fallbacks for the non-ASCII glyphs above. Used by ascii render mode
# (Config.ascii_mode / YAS_ASCII_MODE) to keep the statusline legible in
# terminals without a Nerd Font. This table now covers EVERY non-ASCII char the
# statusline renders \u2014 not just Nerd Font PUA icons, but also the box-drawing
# frame, block/sparkline elements, arrows, and inline punctuation. Each char
# maps to exactly ONE ASCII char so visible width \u2014 and therefore the
# hand-tuned border/elbow column math \u2014 is preserved.
ASCII_GLYPHS: dict[str, str] = {
    ICON_COST:          '$',
    ICON_TOK_RATE:      '~',
    GLYPH_MODEL:        '@',
    GLYPH_THINKING:     '*',
    GLYPH_BURN_FAST:    '!',
    GLYPH_BURN_SLOW:    '^',
    GLYPH_FOLDER:       '/',
    GLYPH_SUBAGENT:     '+',
    GLYPH_TASKS:        '=',
    GLYPH_TASK_PENDING: 'o',
    GLYPH_TASK_ACTIVE:  '>',
    GLYPH_TASK_DONE:    'x',
    GLYPH_SKILLS:       '&',
    GLYPH_PLUGINS:      '%',
    GLYPH_HELPER:       '*',
    GLYPH_TRASH:        '-',
    GLYPH_RENAMED:      '>',
    GLYPH_REPLYING:     ':',
    GLYPH_HOURGLASS:    'H',
    GLYPH_PIE:          '%',
    GLYPH_CACHE:        '~',
    GLYPH_CLEAR:        'C',
    ICON_LIMIT_5H:      'T',
    ICON_LIMIT_7D:      'D',
    GLYPH_MODEL_LIGHT:  '@',
    BarChars.MID:       '>',
    # Box / structure.
    BOX_H:              '-',
    BOX_V:              '|',
    BOX_H_DASH:         '-',
    BOX_T_RIGHT:        '+',
    BOX_T_LEFT:         '+',
    BOX_T_DOWN:         '+',
    BOX_T_UP:           '+',
    BOX_CROSS:          '+',
    BOX_ARC_TL:         '+',
    BOX_ARC_TR:         '+',
    BOX_ARC_BR:         '+',
    BOX_ARC_BL:         '+',
    GLYPH_CONTINUATION: '+',
    GLYPH_WF_SUMMARY:   '+',
    GLYPH_WF_DIVIDER:   ':',
    # Markers / arrows.
    WF_PHASE_DOT:       '.',
    GLYPH_SUBAGENT_ROW: '>',
    GLYPH_SUBAGENT_DONE:'v',
    GLYPH_WF_HEADER:    '>',
    GLYPH_WF_CURRENT:   '>',
    GLYPH_CONFIG_WARN:  '!',
    ARROW_IN_ACTIVE:    'v',
    ARROW_IN_IDLE:      'v',
    ARROW_OUT_ACTIVE:   '^',
    ARROW_OUT_IDLE:     '^',
    # Symbols.
    GLYPH_UNTRACKED:    '*',
    ELLIPSIS:           '~',
    GLYPH_IN:           ':',
    GLYPH_UNLIMITED:    '*',
    # Bars / pill.
    BarChars.FILLED:    '#',
    BarChars.HEAVY:     '+',
    BarChars.EMPTY:     '.',
    PILL_TOP:           '-',
    PILL_BOT:           '-',
    PILL_LEFT:          '|',
    PILL_RIGHT:         '|',
    PILL_TL:            ' ',
    PILL_TR:            ' ',
    PILL_BL:            ' ',
    PILL_BR:            ' ',
}

# Sparkline density ramp fallbacks (U+2581..U+2588), low->high. Some of these
# block codepoints already have constant-level mappings above (\u2584=PILL_TOP,
# \u2586=BarChars.HEAVY, \u2588=BarChars.FILLED); the explicit ramp gives every block a
# monotonic ascii density step, and the `|` merge below lets these win for the
# shared codepoints so the rendered ramp stays consistent. Purely cosmetic \u2014
# every entry is width-1, so no column moves either way.
_RAMP_FALLBACK = {0x2581:'_', 0x2582:'.', 0x2583:':', 0x2584:'-',
                  0x2585:'=', 0x2586:'+', 0x2587:'*', 0x2588:'#'}

# Pre-built {codepoint: ascii} map for str.translate; a no-op for any char with
# no entry. Ramp entries win for the shared block codepoints (see above).
ASCII_TRANSLATE = {ord(g): a for g, a in ASCII_GLYPHS.items()} | _RAMP_FALLBACK

# Unicode (no-Nerd-Font) fallbacks. `unicode` glyph_mode replaces ONLY the Nerd
# Font Private Use Area icon glyphs with non-PUA, width-1 BMP equivalents, while
# leaving box-drawing, block/sparkline, arrow, and punctuation glyphs (which are
# standard Unicode) intact. Keys are the 21 PUA ICON_*/GLYPH_* constants plus
# BarChars.MID; every value is a single non-PUA char (escaped so the bytes
# survive diff/chat round-trips). Geometric-Shapes/Arrows are preferred over
# emoji-presentation symbols, which many terminals render double-width.
UNICODE_PUA: dict[str, str] = {
    ICON_COST:          '$',  # $  currency-usd
    ICON_TOK_RATE:      '◷',  # gauge
    GLYPH_MODEL:        '▦',  # monitor-dashboard
    GLYPH_THINKING:     '◍',  # brain
    GLYPH_BURN_FAST:    '↯',  # zap
    GLYPH_BURN_SLOW:    '∿',  # flame
    GLYPH_FOLDER:       '▭',  # folder
    GLYPH_SUBAGENT:     '☰',  # tasks
    GLYPH_TASKS:        '▤',  # clipboard-check
    GLYPH_TASK_PENDING: '○',  # circle
    GLYPH_TASK_ACTIVE:  '▸',  # arrow-right
    GLYPH_TASK_DONE:    '◉',  # check-circle-fill
    GLYPH_SKILLS:       '◆',  # skills
    GLYPH_PLUGINS:      '⌁',  # plug
    GLYPH_HELPER:       '★',  # star-circle
    GLYPH_TRASH:        '⌫',  # trash-can
    GLYPH_RENAMED:      '⇄',  # file-move
    GLYPH_REPLYING:     '»',  # message
    GLYPH_HOURGLASS:    '⧖',  # hourglass
    GLYPH_PIE:          '◕',  # pie-chart
    GLYPH_CACHE:        '↻',  # cache
    GLYPH_CLEAR:        '⟳',  # refresh (since-last-/clear)
    ICON_LIMIT_5H:      '◴',  # 5h rate-limit timer
    ICON_LIMIT_7D:      '◵',  # 7d rate-limit window
    GLYPH_MODEL_LIGHT:  '⊡',  # single model-pill
    BarChars.MID:       '▪',  # progress sep
}

# Pre-built {codepoint: char} map for str.translate (used by `unicode` glyph_mode).
UNICODE_TRANSLATE = {ord(g): u for g, u in UNICODE_PUA.items()}

# GitHub-paste-safe mode. `github` glyph_mode folds EVERY browser-wide glyph
# (East-Asian-Width Ambiguous/Wide/Fullwidth) and every Nerd Font PUA codepoint
# to a width-1, EAW-narrow (N/Na/H) or ASCII replacement, so a pasted statusline
# keeps its column geometry in a proportional-blind monospace web font (GitHub,
# Slack, etc.) where Ambiguous chars otherwise render double-width. Unlike
# `unicode` (which only swaps PUA icons), `github` also ASCII-folds the
# box-drawing frame and block ramp, because those are EAW-Ambiguous in a browser.
#
# PUA icons keep the prettier `unicode` substitutions where those are already
# EAW-narrow; the five whose `unicode` target is EAW-Ambiguous get a narrow
# override below (verified against unicodedata.east_asian_width).
GITHUB_PUA: dict[str, str] = dict(UNICODE_PUA)

# EAW-narrow overrides for icons whose `unicode` substitution is EAW-Ambiguous
# (would render double-width in a browser), plus one non-PUA nicety. Every target
# is verified width-1 and EAW N/Na/H so the C1 invariant holds.
GITHUB_ICON_OVERRIDE: dict[str, str] = {
    GLYPH_MODEL:        '⊞',  # ⊞ squared plus      (was ▦ U+25A6, EAW=A)
    GLYPH_TASKS:        '⊟',  # ⊟ squared minus     (was ▤ U+25A4, EAW=A)
    GLYPH_TASK_PENDING: '◌',  # ◌ dotted circle     (was ○ U+25CB, EAW=A)
    GLYPH_SKILLS:       '⬦',  # ⬦ white medium diamond (was ◆ U+25C6, EAW=A)
    GLYPH_HELPER:       '✦',  # ✦ black four-pointed star (was ★ U+2605, EAW=A)
    GLYPH_SUBAGENT:     '⫶',  # ⫶ triple colon (stacked list, was ☰ tasks)
    GLYPH_SUBAGENT_ROW: '▸',  # ▸ small right triangle (was ▶ U+25B6, EAW=A)
}

# Pre-built {codepoint: str} map for str.translate (used by `github` glyph_mode).
# Precedence (later wins on key collision): ASCII frame/punctuation/block/PUA
# fallback, then the sparkline ramp, then prettier narrow unicode for PUA icons,
# then the EAW-narrow overrides.
GITHUB_TRANSLATE: dict[int, str] = (
    {ord(g): a for g, a in ASCII_GLYPHS.items()}
    | _RAMP_FALLBACK
    | {ord(g): u for g, u in GITHUB_PUA.items()}
    | {ord(g): u for g, u in GITHUB_ICON_OVERRIDE.items()}
)

# Workflow cohort thresholds. A run is kept visible while any agent transcript
# was written within WORKFLOW_LIVENESS_SECONDS (longer than the subagent
# cohort's windows so a run rides through between-phase lulls). At most
# WORKFLOW_AGENT_CAP agent rows render per run and WORKFLOW_RUN_CAP run blocks
# render concurrently; overflow is summarised, never dropped silently.
WORKFLOW_LIVENESS_SECONDS = 120
WORKFLOW_AGENT_CAP        = 6
WORKFLOW_RUN_CAP          = 2

# At most SUBAGENT_DISPLAY_CAP subagent rows render in the standalone cohort;
# the layout builders keep the most recent (latest-started) rows and drop the
# older overflow. Matches WORKFLOW_AGENT_CAP so both sections cap identically.
SUBAGENT_DISPLAY_CAP      = 6

# Maximum lines to scan from the head of a transcript when searching for a
# /clear marker. Keeps the lookup O(1) even on large transcripts.
CLEAR_SCAN_MAX_LINES      = 30

# Workflow run-header phase-trail layout. WF_NAME_MIN is the minimum run-name
# width preserved before the inline phase trail truncates with `…`; WF_PHASE_GAP
# is the spaces reserved between the name and the trail (the header prepends
# two). WF_PHASE_DOT separates phases in the trail.
WF_NAME_MIN   = 12
WF_PHASE_GAP  = 2

# Dim factor for the in-flight (currently-open) sparkline bucket.
LIVE_DIM = 0.5

RAINBOW_PALETTE = (
    196, 202, 208, 214, 220, 226, 190, 154, 118, 82,
    46, 47, 48, 49, 50, 51, 45, 39, 33, 27,
    21, 57, 93, 129, 165, 201, 200, 199, 198, 197,
)

BG_LUM_THRESHOLD = 110
