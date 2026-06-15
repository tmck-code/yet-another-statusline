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
ITALIC = '\033[3m'

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
ICON_COST     = ''      # nf-md currency-usd  (cost row)
ICON_TOK_RATE = '\U000f18a7'  # nf-md gauge         (t/m rate label)
GLYPH_MODEL    = '\U000f08b9' # nf-md-monitor-dashboard
GLYPH_THINKING = '\U000f1a53' # nf-md-brain
GLYPH_BURN_FAST = ''  # nf-cod-zap (shown when the burn rate is too fast)
GLYPH_BURN_SLOW = ''  # nf-oct-flame (shown when the burn rate is _not_ too fast)
GLYPH_FOLDER   = ''     # nf-custom folder    (path row)
GLYPH_SUBAGENT = ''     # nf-fa-tasks         (subagent list)
GLYPH_SUBAGENT_ROW = '▶'  # U+25B6           (per-row Running Subagent marker)
GLYPH_SUBAGENT_DONE = '✓'  # U+2713           (Done subagent row marker)
GLYPH_TASKS    = '\U000f08a8'  # nf-md-clipboard-check-outline (Task Row marker)
GLYPH_TASK_PENDING = '\ue640'      # nf-fa-circle_o          (pending task)
GLYPH_TASK_ACTIVE  = '\U000f0117'  # nf-md-arrow_right_thick (in_progress task)
GLYPH_TASK_DONE    = '\uf4a7'      # nf-oct-check_circle_fill (completed task)
GLYPH_SKILLS  = '\U000f07df'  # nf-md skills        (skills label)
GLYPH_PLUGINS = ''      # nf-fa-plug          (plugins label)
GLYPH_HELPER   = ''     # nf-mdi-star_circle  (5h rate-limit helper)
GLYPH_TRASH    = '\U000f0a7a' # nf-md-trash_can     (git deleted count)
GLYPH_RENAMED  = '\U000f1031' # nf-md-file_move     (git renamed count)
GLYPH_CONTINUATION = '└'  # U+2514 BOX DRAWINGS LIGHT UP AND RIGHT
GLYPH_REPLYING     = '\U000f0189'  # nf-md-message  (replying state)
GLYPH_HOURGLASS    = ''  # nf-fa-hourglass_half (subagent context size)
GLYPH_PIE          = ''  # nf-fa-pie_chart     (subagent session share)
GLYPH_CONFIG_WARN  = '⚠'  # U+26A0 WARNING SIGN (config-error row marker)
GLYPH_CACHE        = '\uf49b'  # nf-oct-cache  (cache countdown)
GLYPH_WF_HEADER    = '\u25b8'  # \u25b8 U+25B8 BLACK RIGHT-POINTING SMALL TRIANGLE (workflow run header)
GLYPH_WF_SUMMARY   = '\u2514'  # \u2514 U+2514 BOX DRAWINGS LIGHT UP AND RIGHT (workflow run summary)
GLYPH_WF_CURRENT   = '\u276f'  # \u276f U+276F HEAVY RIGHT-POINTING ANGLE QUOTATION MARK ORNAMENT (current-phase marker)

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

# Workflow run-header phase-trail layout. WF_NAME_MIN is the minimum run-name
# width preserved before the inline phase trail truncates with `…`; WF_PHASE_GAP
# is the spaces reserved between the name and the trail (the header prepends
# two). WF_PHASE_DOT separates phases in the trail.
WF_NAME_MIN   = 12
WF_PHASE_GAP  = 2
WF_PHASE_DOT  = '·'  # · U+00B7 MIDDLE DOT (workflow phase-trail separator)

# Dim factor for the in-flight (currently-open) sparkline bucket.
LIVE_DIM = 0.5

PILL_TL    = '▗'  # U+2597 lower-right quadrant
PILL_TOP   = '▄'  # U+2584 lower half block
PILL_TR    = '▖'  # U+2596 lower-left quadrant
PILL_LEFT  = '▐'  # U+2590 right half block
PILL_RIGHT = '▌'  # U+258C left half block
PILL_BL    = '▝'  # U+259D upper-right quadrant
PILL_BOT   = '▀'  # U+2580 upper half block
PILL_BR    = '▘'  # U+2598 upper-left quadrant

RAINBOW_PALETTE = (
    196, 202, 208, 214, 220, 226, 190, 154, 118, 82,
    46, 47, 48, 49, 50, 51, 45, 39, 33, 27,
    21, 57, 93, 129, 165, 201, 200, 199, 198, 197,
)

BG_LUM_THRESHOLD = 110
