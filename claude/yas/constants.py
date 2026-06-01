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
NARROW_WIDTH = 55
MEDIUM_WIDTH = 80
_ANSI_RE   = re.compile(r'\x1b\[[0-9;]*m')

FIVE_HOUR_MINUTES        = 300
SEVEN_DAY_MINUTES        = 10080
FIVE_HOUR_WARMUP_MINUTES = 5
SEVEN_DAY_WARMUP_MINUTES = 30


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

# Dim factor for the in-flight (currently-open) sparkline bucket.
LIVE_DIM = 0.5

# Sparkline slope glyphs from U+1FB3C-U+1FB6B "Symbols for Legacy Computing".
# Used by GradientEngine.sparkline to draw sloped peaks: a "rise" char on the
# peak cell pairs with a 'fall' char on the next cell to form a /\ shape.
SPARK_RISE_SMALL  = '\U0001fb48'  # small rise (bot row, idx 1-3)
SPARK_FALL_SMALL  = '\U0001fb3d'  # small fall (bot row, idx 1-3)
SPARK_RISE_MED    = '\U0001fb4a'  # medium rise (bot row, idx 4-7)
SPARK_FALL_MED    = '\U0001fb3f'  # medium fall (bot row, idx 4-7)
SPARK_RISE_TALL   = '\U0001fb45'  # tall rise (bot row, idx 8+)
SPARK_FALL_TALL   = '\U0001fb50'  # tall fall (bot row, idx 8+)
SPARK_RISE_TOP    = '\U0001fb4b'  # top-row rise (idx 9+)
SPARK_FALL_TOP    = '\U0001fb40'  # top-row fall (idx 9+)

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
