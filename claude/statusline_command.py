#!/usr/bin/env python3
'Claude Code statusLine command (Python port).'

from __future__ import annotations
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from collections.abc import Sequence
from typing import TYPE_CHECKING, NamedTuple


# Load the themes module via importlib because this script runs as a top-level
# file (not inside a package). The same shim is used by test/conftest.py.
# TYPE_CHECKING lets mypy resolve the types via a normal import path while the
# importlib load handles the runtime side.
if TYPE_CHECKING:
    from statusline.themes import ModelColors, Theme

_THEMES_PATH = Path(__file__).resolve().parent / 'statusline' / 'themes.py'
_themes_spec = importlib.util.spec_from_file_location('statusline_themes', _THEMES_PATH)
assert _themes_spec is not None and _themes_spec.loader is not None
themes = importlib.util.module_from_spec(_themes_spec)
sys.modules['statusline_themes'] = themes
_themes_spec.loader.exec_module(themes)
if not TYPE_CHECKING:
    Theme       = themes.Theme
    ModelColors = themes.ModelColors
THEMES:     dict[str, Theme] = themes.THEMES
CLAUDE_DARK: Theme           = themes.CLAUDE_DARK


class BarChars:
    FILLED = '█'
    HEAVY  = '▆'
    MID    = ''
    EMPTY  = '░'


HOME       = Path(os.path.expanduser('~'))
CLAUDE_DIR = Path(os.environ.get('CLAUDE_CONFIG_DIR', str(HOME / '.claude')))
MIN_WIDTH    = 40
DEFAULT_MAX_WIDTH = 140
MAX_WIDTH    = int(os.environ.get('YAS_MAX_WIDTH') or DEFAULT_MAX_WIDTH)
NARROW_WIDTH = 55
MEDIUM_WIDTH = 80
SOFT_LIMIT = 150_000
try:
    GIT_CACHE_TTL = float(os.environ.get('YAS_GIT_CACHE_TTL') or '4')  # seconds; per-session git-status freshness window
except ValueError:
    GIT_CACHE_TTL = 4.0
_ANSI_RE   = re.compile(r'\x1b\[[0-9;]*m')

FIVE_HOUR_MINUTES        = 300
SEVEN_DAY_MINUTES        = 10080
FIVE_HOUR_WARMUP_MINUTES = 5
SEVEN_DAY_WARMUP_MINUTES = 30


def burndown_delta(
    used_pct: float,
    resets_at: int,
    window_minutes: int,
    warmup_minutes: int,
    now: float | None = None,
) -> float | None:
    if not resets_at:
        return None
    t = now if now is not None else time.time()
    if t >= resets_at:
        return None
    window_start_ts = resets_at - window_minutes * 60
    elapsed_minutes = (t - window_start_ts) / 60
    if elapsed_minutes < warmup_minutes:
        return None
    ideal_pct = (elapsed_minutes / window_minutes) * 100
    return used_pct - ideal_pct


def subagent_avg_tpm(
    total_input: int,
    output: int,
    first_timestamp: float,
    now: float,
    floor_seconds: float = 3.0,
) -> int | None:
    if first_timestamp == 0 or now - first_timestamp < floor_seconds:
        return None
    return round((total_input + output) / ((now - first_timestamp) / 60))


def subagent_share(sub_inout: int, session_inout: int) -> float | None:
    if session_inout <= 0:
        return None
    return sub_inout / session_inout


def terminal_width() -> int:
    try:
        w = int(subprocess.run([
            "tmux", "display-message", "-p", "-t", f"{os.environ['TMUX_PANE']}", "'#{pane_width}'"
        ], capture_output=True, text=True).stdout.strip().replace("'", ""))
        if w > 0:
            return w
    except (OSError, ValueError, KeyError):
        pass
    try:
        w = int((CLAUDE_DIR / 'terminal-width').read_text().strip())
        if w > 0:
            return w
    except (OSError, ValueError):
        pass
    try:
        cols = int(os.environ.get('COLUMNS', '0'))
        if cols > 0:
            return cols
    except ValueError:
        pass
    w = shutil.get_terminal_size(fallback=(0, 0)).columns
    if w > 0:
        return w
    for fd in (2, 1, 0):
        try:
            return os.get_terminal_size(fd).columns
        except OSError:
            pass
    try:
        tty_fd = os.open('/dev/tty', os.O_RDONLY)
        try:
            return os.get_terminal_size(tty_fd).columns
        finally:
            os.close(tty_fd)
    except OSError:
        pass
    return MAX_WIDTH

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
ICON_COST     = '\uefc8'      # nf-md currency-usd  (cost row)
ICON_TOK_RATE = '\U000f18a7'  # nf-md gauge         (t/m rate label)
GLYPH_MODEL    = '\U000f08b9' # nf-md-monitor-dashboard
GLYPH_THINKING = '\U000f1a53' # nf-md-brain
GLYPH_BURN_FAST = '\uef76'  # nf-cod-zap (shown when the burn rate is too fast)
GLYPH_BURN_SLOW = '\uf490'  # nf-oct-flame (shown when the burn rate is _not_ too fast)
GLYPH_FOLDER   = '\uef85'     # nf-custom folder    (path row)
GLYPH_SUBAGENT = '\uf135'     # nf-fa-tasks         (subagent list)
GLYPH_SUBAGENT_ROW = '\u25b6'  # \u25b6 U+25B6           (per-row Running Subagent marker)
GLYPH_TASKS    = '\U000f0755'  # nf-md format-list-checks (Task Row marker)
GLYPH_SKILLS  = '\U000f07df'  # nf-md skills        (skills label)
GLYPH_PLUGINS = '\uf1e6'      # nf-fa-plug          (plugins label)
GLYPH_HELPER   = '\uf4cd'     # nf-mdi-star_circle  (5h rate-limit helper)
GLYPH_TRASH    = '\U000f0a7a' # nf-md-trash_can     (git deleted count)
GLYPH_RENAMED  = '\U000f1031' # nf-md-file_move     (git renamed count)
GLYPH_CONTINUATION = '└'    # U+2514 BOX DRAWINGS LIGHT UP AND RIGHT (└)
GLYPH_REPLYING     = '\U000f0189'  # nf-md-message  (replying state)
GLYPH_HOURGLASS    = '\uf253'  # nf-fa-hourglass_half (subagent context size)
GLYPH_PIE          = '\uf200'  # nf-fa-pie_chart     (subagent session share)

TOOL_ARG_KEY: dict[str, str] = {
    'Bash':        'command',
    'Read':        'file_path',
    'Edit':        'file_path',
    'Write':       'file_path',
    'NotebookEdit':'file_path',
    'Grep':        'pattern',
    'Glob':        'pattern',
    'Task':        'subagent_type',
}

# Dim factor for the in-flight (currently-open) sparkline bucket.
LIVE_DIM = 0.5

# Sparkline slope glyphs from U+1FB3C–U+1FB6B "Symbols for Legacy Computing".
# Used by GradientEngine.sparkline to draw sloped peaks: a "rise" char on the
# peak cell pairs with a "fall" char on the next cell to form a /\ shape.
SPARK_RISE_SMALL  = '\U0001fb48'  # 🭈 small rise (bot row, idx 1–3)
SPARK_FALL_SMALL  = '\U0001fb3d'  # 🬽 small fall (bot row, idx 1–3)
SPARK_RISE_MED    = '\U0001fb4a'  # 🭊 medium rise (bot row, idx 4–7)
SPARK_FALL_MED    = '\U0001fb3f'  # 🬿 medium fall (bot row, idx 4–7)
SPARK_RISE_TALL   = '\U0001fb45'  # 🭅 tall rise (bot row, idx 8+)
SPARK_FALL_TALL   = '\U0001fb50'  # 🭐 tall fall (bot row, idx 8+)
SPARK_RISE_TOP    = '\U0001fb4b'  # 🭋 top-row rise (idx 9+)
SPARK_FALL_TOP    = '\U0001fb40'  # 🭀 top-row fall (idx 9+)

PILL_TL    = '▗'  # U+2597 lower-right quadrant
PILL_TOP   = '▄'  # U+2584 lower half block
PILL_TR    = '▖'  # U+2596 lower-left quadrant
PILL_LEFT  = '▐'  # U+2590 right half block
PILL_RIGHT = '▌'  # U+258C left half block
PILL_BL    = '▝'  # U+259D upper-right quadrant
PILL_BOT   = '▀'  # U+2580 upper half block
PILL_BR    = '▘'  # U+2598 upper-left quadrant


@dataclass
class Pill:
    start: int = -1
    end: int = -1
    anchor: tuple[int, int, int] = (0, 0, 0)
    shift: tuple[int, int, int] = (0, 0, 0)
    pct: int = 0

    @property
    def active(self) -> bool:
        return self.pct > 0

    def gradient_fg(self, col: int) -> str:
        return pill_gradient_fg(col - self.start, 0, self.end - self.start, self.anchor, self.shift, self.pct)

    def border_char(self, col: int, edge: str = 'top') -> str:
        if not self.active or not (self.start <= col <= self.end):
            return ''
        if edge == 'top':
            if col == self.start:
                return PILL_TL
            if col == self.end:
                return PILL_TR
            return PILL_TOP
        else:
            if col == self.start:
                return PILL_BL
            if col == self.end:
                return PILL_BR
            return PILL_BOT

    def border_fg(self, col: int) -> str:
        return pill_gradient_fg(col - self.start, 0, self.end - self.start, self.anchor, self.shift, self.pct)


def _is_wide(ch: str) -> bool:
    cp = ord(ch)
    # Supplemental Arrows-C (U+1F800-U+1F8FF) are EAW=N despite being in the
    # emoji range — exclude them so arrow icons like 🡅/🡇 count as 1 col.
    if 0x1F800 <= cp <= 0x1F8FF:
        return False
    return 0x1F300 <= cp <= 0x1FAFF


def _visible_width(s: str) -> int:
    plain = _ANSI_RE.sub('', s)
    return sum(2 if _is_wide(ch) else 1 for ch in plain)


def _middle_ellipsis(text: str, max_w: int) -> str:
    if max_w <= 1:
        return '…'
    if _visible_width(text) <= max_w:
        return text
    left_vis  = (max_w - 1) // 2
    right_vis = max_w - 1 - left_vis

    # Tokenise into (is_escape, string) pairs to preserve ANSI across the cut.
    tokens: list[tuple[bool, str]] = []
    i = 0
    while i < len(text):
        m = _ANSI_RE.match(text, i)
        if m:
            tokens.append((True, m.group()))
            i = m.end()
        else:
            tokens.append((False, text[i]))
            i += 1

    def _take(toks: list[tuple[bool, str]], n: int) -> list[str]:
        out: list[str] = []
        seen = 0
        for is_esc, tok in toks:
            if is_esc:
                out.append(tok)
            elif seen < n:
                out.append(tok)
                seen += 1
            else:
                break
        return out

    prefix = _take(tokens, left_vis)
    suffix = _take(list(reversed(tokens)), right_vis)
    suffix.reverse()

    result = ''.join(prefix) + '…' + ''.join(suffix)
    if _visible_width(result) <= max_w:
        return result
    # Trim one visible char from prefix to fix wide-char overshoot.
    for j in range(len(prefix) - 1, -1, -1):
        if not _ANSI_RE.fullmatch(prefix[j]):
            prefix.pop(j)
            break
    return ''.join(prefix) + '…' + ''.join(suffix)


_MODEL_VER_RE   = re.compile(r'(\d+)[.\-](\d{1,2})(?!\d)')
_MODEL_MAJOR_RE = re.compile(r'(\d+)')


def _model_version(name: str) -> tuple[int, int] | None:
    'Extract (major, minor) from a model id or display name: "claude-opus-4-7"/"Opus 4.7" -> (4, 7); "Opus 4" -> (4, 0).'
    m = _MODEL_VER_RE.search(name)
    if m:
        return int(m.group(1)), int(m.group(2))
    m2 = _MODEL_MAJOR_RE.search(name)
    if m2:
        return int(m2.group(1)), 0
    return None


class TokenAccounting:
    @staticmethod
    def rates_for(model_name: str) -> tuple[float, float]:
        '''Input/output USD per million tokens, keyed by model family + version.

        Verified against the official pricing page (platform.claude.com,
        2026-05-27). UPDATE this table AND test_model_cost_rates.py whenever the
        model catalog or pricing changes. Unversioned names resolve to the
        current (latest) rate of their family. NOTE: the displayed session cost
        prefers the host's cost.total_cost_usd (see session_cost_display); this
        table is the fallback estimate and the basis for the cross-session day cost.
        '''
        m = model_name.lower()
        ver = _model_version(m)
        if 'opus' in m:
            if ver is not None and ver < (4, 5):
                return 15.00, 75.00   # Opus 4.1 / 4 / 3.x (legacy & deprecated)
            return 5.00, 25.00        # Opus 4.5 / 4.6 / 4.7+
        if 'haiku' in m:
            if ver is not None and ver < (4, 5):
                return 0.80, 4.00     # Haiku 3.5 and earlier (retired)
            return 1.00, 5.00         # Haiku 4.5+
        if 'sonnet' in m:
            return 3.00, 15.00        # all current Sonnet
        return 3.00, 15.00            # unknown model -> Sonnet-class default

    @staticmethod
    def session_cost(model: Model, usage: TranscriptUsage) -> float:
        rate_in, rate_out = TokenAccounting.rates_for(
            model.display_name or model.id
        )
        cost = (
            usage.input_tokens * rate_in
            + usage.cache_creation_input_tokens * rate_in * 1.25
            + usage.cache_read_input_tokens * rate_in * 0.1
            + usage.output_tokens * rate_out
        )
        return cost / 1_000_000

    @staticmethod
    def day_cost(model: Model, token_log: TokenLog) -> float:
        # Price each model's day tokens at its own rate. Rows with no recorded
        # model (legacy v1 rows) fall back to the current session's model.
        if token_log.by_model:
            total = 0.0
            for mid, (din, dcache, dout) in token_log.by_model.items():
                rate_in, rate_out = TokenAccounting.rates_for(mid) if mid else model.cost_rates
                total += din * rate_in + dcache * rate_in * 0.1 + dout * rate_out
            return total / 1_000_000
        rate_in, rate_out = TokenAccounting.rates_for(model.display_name or model.id)
        cost = (
            token_log.day_in * rate_in
            + token_log.day_cache_read * rate_in * 0.1
            + token_log.day_out * rate_out
        )
        return cost / 1_000_000


def _as_int(v: object, default: int = 0) -> int:
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    return default


def _as_float(v: object, default: float = 0.0) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    return default


def _as_str(v: object, default: str = '') -> str:
    if isinstance(v, str):
        return v
    return default


def _atomic_write_text(path: Path, text: str) -> None:
    '''Best-effort atomic write: write to a sibling temp file, then os.replace
    (atomic on POSIX and Windows) onto the target so a reader or a cancelled
    render never sees a half-written file. Swallows OSError — these are
    telemetry/cache files, and a failed write simply means the next render
    recomputes. The PID-suffixed temp name avoids concurrent-render collisions.'''
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
        with open(tmp, 'w', encoding='utf-8') as fh:
            fh.write(text)
        os.replace(tmp, path)
    except OSError:
        pass


class Model(NamedTuple):
    id: str = ''
    display_name: str = ''

    @classmethod
    def from_dict(cls, d: object) -> Model:
        if isinstance(d, str):
            return cls(id=d, display_name='')
        if isinstance(d, dict):
            return cls(
                id           = _as_str(d.get('id')),
                display_name = _as_str(d.get('display_name')),
            )
        return cls()

    @property
    def cost_rates(self) -> tuple[float, float]:
        return TokenAccounting.rates_for(self.display_name or self.id)


class OutputStyle(NamedTuple):
    name: str = 'default'

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> OutputStyle:
        return cls(name=_as_str(d.get('name'), 'default'))


class Effort(NamedTuple):
    level: str = ''

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> Effort:
        return cls(level=_as_str(d.get('level')))


class Thinking(NamedTuple):
    enabled: bool = False

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> Thinking:
        return cls(enabled=bool(d.get('enabled', False)))


class CurrentUsage(NamedTuple):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> CurrentUsage:
        return cls(
            input_tokens                = _as_int(d.get('input_tokens', 0)),
            output_tokens               = _as_int(d.get('output_tokens', 0)),
            cache_creation_input_tokens = _as_int(d.get('cache_creation_input_tokens', 0)),
            cache_read_input_tokens     = _as_int(d.get('cache_read_input_tokens', 0)),
        )


class RateBucket(NamedTuple):
    used_percentage: float = 0.0
    resets_at: int = 0

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> RateBucket:
        return cls(
            used_percentage = round(_as_float(d.get('used_percentage', 0.0)), 2),
            resets_at       = _as_int(d.get('resets_at', 0)),
        )


@dataclass
class Workspace:
    current_dir: str = ''
    project_dir: str = ''
    added_dirs: list[object] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> Workspace:
        current_dir = d.get('current_dir', '')
        project_dir = d.get('project_dir', '')
        added_dirs  = d.get('added_dirs')
        return cls(
            current_dir = str(current_dir) if current_dir else '',
            project_dir = str(project_dir) if project_dir else '',
            added_dirs  = list(added_dirs) if isinstance(added_dirs, list) else [],
        )

    @property
    def plugins(self) -> str:
        seen: dict[str, None] = {}
        candidates = [CLAUDE_DIR / 'settings.json']
        if self.project_dir:
            candidates.append(Path(self.project_dir) / '.claude' / 'settings.json')
        for sf in candidates:
            if not sf.is_file():
                continue
            try:
                data = json.loads(sf.read_text())
            except Exception:
                continue
            for key, val in (data.get('enabledPlugins') or {}).items():
                if val is True:
                    name = key.split('@', 1)[0]
                    if name not in seen:
                        seen[name] = None
        return ','.join(seen.keys())


@dataclass
class Cost:
    total_cost_usd: float = 0.0
    total_duration_ms: int = 0
    total_api_duration_ms: int = 0
    total_lines_added: int = 0
    total_lines_removed: int = 0

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> Cost:
        return cls(
            total_cost_usd        = _as_float(d.get('total_cost_usd', 0.0)),
            total_duration_ms     = _as_int(d.get('total_duration_ms', 0)),
            total_api_duration_ms = _as_int(d.get('total_api_duration_ms', 0)),
            total_lines_added     = _as_int(d.get('total_lines_added', 0)),
            total_lines_removed   = _as_int(d.get('total_lines_removed', 0)),
        )


@dataclass
class ContextWindow:
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    context_window_size: int = 0
    current_usage: CurrentUsage = field(default_factory=CurrentUsage)
    used_percentage: float | None = None
    remaining_percentage: float | None = None

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> ContextWindow:
        cu_raw = d.get('current_usage')
        cu = CurrentUsage.from_dict(cu_raw if isinstance(cu_raw, dict) else {})
        used_pct = d.get('used_percentage')
        rem_pct  = d.get('remaining_percentage')
        return cls(
            total_input_tokens   = _as_int(d.get('total_input_tokens', 0)),
            total_output_tokens  = _as_int(d.get('total_output_tokens', 0)),
            context_window_size  = _as_int(d.get('context_window_size', 0)),
            current_usage        = cu,
            used_percentage      = float(used_pct) if isinstance(used_pct, (int, float)) else None,
            remaining_percentage = float(rem_pct)  if isinstance(rem_pct,  (int, float)) else None,
        )


@dataclass
class RateLimits:
    five_hour: RateBucket = field(default_factory=RateBucket)
    seven_day: RateBucket = field(default_factory=RateBucket)

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> RateLimits:
        fh = d.get('five_hour')
        sd = d.get('seven_day')
        return cls(
            five_hour = RateBucket.from_dict(fh if isinstance(fh, dict) else {}),
            seven_day = RateBucket.from_dict(sd if isinstance(sd, dict) else {}),
        )


@dataclass
class SessionInfo:
    session_id: str = ''
    transcript_path: str = ''
    cwd: str = ''
    model: Model = field(default_factory=Model)
    workspace: Workspace = field(default_factory=Workspace)
    version: str = ''
    output_style: OutputStyle = field(default_factory=OutputStyle)
    cost: Cost = field(default_factory=Cost)
    context_window: ContextWindow = field(default_factory=ContextWindow)
    exceeds_200k_tokens: bool = False
    effort: Effort = field(default_factory=Effort)
    thinking: Thinking = field(default_factory=Thinking)
    fast_mode: bool = False
    rate_limits: RateLimits = field(default_factory=RateLimits)

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> SessionInfo:
        def _dict(key: str) -> dict[str, object]:
            v = d.get(key)
            return v if isinstance(v, dict) else {}
        session_id      = d.get('session_id', '')
        transcript_path = d.get('transcript_path', '')
        cwd             = d.get('cwd', '')
        version         = d.get('version', '')
        return cls(
            session_id          = str(session_id)      if session_id      is not None else '',
            transcript_path     = str(transcript_path) if transcript_path is not None else '',
            cwd                 = str(cwd)             if cwd             is not None else '',
            model               = Model.from_dict(d.get('model') or {}),
            workspace           = Workspace.from_dict(_dict('workspace')),
            version             = str(version)         if version         is not None else '',
            output_style        = OutputStyle.from_dict(_dict('output_style')),
            cost                = Cost.from_dict(_dict('cost')),
            context_window      = ContextWindow.from_dict(_dict('context_window')),
            exceeds_200k_tokens = bool(d.get('exceeds_200k_tokens', False)),
            effort              = Effort.from_dict(_dict('effort')),
            thinking            = Thinking.from_dict(_dict('thinking')),
            fast_mode           = bool(d.get('fast_mode', False)),
            rate_limits         = RateLimits.from_dict(_dict('rate_limits')),
        )

    @property
    def short_pwd(self) -> str:
        home = str(HOME)
        p = self.cwd
        if p.startswith(home):
            p = '~' + p[len(home):]
        parts = p.split('/')
        last = len(parts) - 1
        out_parts = []
        for i, seg in enumerate(parts):
            if i == last or seg == '' or seg == '~':
                out_parts.append(seg)
            else:
                out_parts.append(seg[0])
        return '/'.join(out_parts)

    @property
    def model_name(self) -> str:
        name = self.model.display_name or self.model.id or 'unknown'
        return name.replace('(1M context)', '1M').replace('  ', ' ').strip()

    @property
    def model_thinking(self) -> str:
        if self.thinking.enabled and self.effort.level:
            return f'{self.effort.level}/fast' if self.fast_mode else self.effort.level
        if self.fast_mode:
            return 'fast'
        return ''

    @property
    def plugin_names(self) -> str:
        return self.workspace.plugins


def elapsed_from_transcript(transcript_path: str) -> str:
    if not transcript_path:
        return ''
    p = Path(transcript_path)
    if not p.is_file():
        return ''
    try:
        secs = int(time.time() - p.stat().st_mtime)
    except OSError:
        return ''
    h, rem = divmod(secs, 3600)
    m = rem // 60
    return f'{h}h{m}m' if h > 0 else f'{m}m'


def compute_session_cost(model: Model, usage: TranscriptUsage) -> float:
    return TokenAccounting.session_cost(model, usage)


def compute_day_cost(model: Model, token_log: TokenLog) -> float:
    return TokenAccounting.day_cost(model, token_log)


def session_cost_display(session: SessionInfo, usage: TranscriptUsage) -> float:
    '''Session cost to display. Prefer Claude Code's own running estimate
    (cost.total_cost_usd): it is model-version-aware and already reflects pricing
    modifiers (e.g. Fast mode 6x, data residency) that the local rate-table
    estimate cannot see. Fall back to the local estimate only when the host
    value is missing/zero (e.g. before the first API response).'''
    host = session.cost.total_cost_usd
    if host > 0:
        return host
    return compute_session_cost(session.model, usage)


def _model_log_key(model: Model) -> str:
    'Space-free model key for the token log (a space would break the field-delimited row).'
    return (model.id or model.display_name).replace(' ', '-')


@dataclass
class TokenLog:
    day_in: int = 0
    day_cache_read: int = 0
    day_out: int = 0
    # Per-model day totals (model_key -> (in, cache_read, out)) so day cost can
    # price each model separately. Excluded from equality so a hand-built
    # TokenLog(day_in=..., ...) in tests still compares equal.
    by_model: dict[str, tuple[int, int, int]] = field(default_factory=dict, compare=False)

    @classmethod
    def update(cls, session_id: str, today: str, total_in: int, cache_read: int,
               total_out: int, model_id: str = '') -> TokenLog:
        log = CLAUDE_DIR / 'statusline-tokens.log'
        old_lines: list[str] = []
        if log.exists():
            try:
                old_lines = log.read_text().splitlines()
            except OSError:
                old_lines = []
        # A v2 row appends a space-free model id; an empty model keeps the legacy
        # 5-field shape (and on-disk format) byte-for-byte unchanged.
        new_row = f'{today} {session_id} {total_in} {cache_read} {total_out}'
        if model_id:
            new_row += f' {model_id}'
        has_tokens = bool(session_id) and (total_in > 0 or cache_read > 0 or total_out > 0)
        # Replace this session's row in place (preserves order, so an unchanged
        # render produces identical content and skips the write — churn fix).
        new_lines: list[str] = []
        replaced = False
        for ln in old_lines:
            parts = ln.split()
            if len(parts) >= 2 and parts[1] == session_id:
                replaced = True
                if has_tokens:
                    new_lines.append(new_row)
            else:
                new_lines.append(ln)
        if has_tokens and not replaced:
            new_lines.append(new_row)
        if new_lines != old_lines:
            _atomic_write_text(log, '\n'.join(new_lines) + '\n')
        return cls._rollup(new_lines, today)

    @staticmethod
    def _rollup(lines: list[str], today: str) -> TokenLog:
        day_in = day_cache_read = day_out = 0
        by_model: dict[str, tuple[int, int, int]] = {}
        for ln in lines:
            parts = ln.split()
            if len(parts) < 4 or parts[0] != today:
                continue
            r_in = r_cache = r_out = 0
            r_model = ''
            try:
                if len(parts) >= 6:
                    r_in, r_cache, r_out, r_model = int(parts[2]), int(parts[3]), int(parts[4]), parts[5]
                elif len(parts) == 5:
                    r_in, r_cache, r_out = int(parts[2]), int(parts[3]), int(parts[4])
                else:  # 4-field legacy: date sid in out
                    r_in, r_out = int(parts[2]), int(parts[3])
            except ValueError:
                continue
            day_in += r_in
            day_cache_read += r_cache
            day_out += r_out
            prev = by_model.get(r_model, (0, 0, 0))
            by_model[r_model] = (prev[0] + r_in, prev[1] + r_cache, prev[2] + r_out)
        return TokenLog(day_in=day_in, day_cache_read=day_cache_read, day_out=day_out, by_model=by_model)



class TokenRate:
    WINDOW = float(os.environ.get('STATUSLINE_TOKEN_WINDOW', '60'))
    KEEP = 300.0

    @classmethod
    def update(cls, session_id: str, total_in: int, total_out: int) -> int:
        if not session_id:
            return 0
        log = CLAUDE_DIR / 'statusline-token-rate.log'
        now = time.time()
        rows: list[tuple[float, str, int, int]] = []
        if log.exists():
            for ln in log.read_text().splitlines():
                parts = ln.split()
                if len(parts) < 4:
                    continue
                try:
                    ts = float(parts[0])
                    ti = int(parts[2])
                    to = int(parts[3])
                except ValueError:
                    continue
                if now - ts > cls.KEEP:
                    continue
                rows.append((ts, parts[1], ti, to))
        rows.append((now, session_id, total_in, total_out))
        _atomic_write_text(log, '\n'.join(f'{ts:.3f} {sid} {ti} {to}' for ts, sid, ti, to in rows) + '\n')
        samples = [(ts, ti, to) for ts, sid, ti, to in rows if sid == session_id and now - ts <= cls.WINDOW]
        if len(samples) < 2:
            return 0
        samples.sort()
        _, ti0, to0 = samples[0]
        _, ti1, to1 = samples[-1]
        return max(0, (ti1 + to1) - (ti0 + to0))

    @classmethod
    def history(cls, session_id: str, n_buckets: int, window: float) -> list[int]:
        if n_buckets <= 0 or not session_id:
            return []
        log = CLAUDE_DIR / 'statusline-token-rate.log'
        now = time.time()
        samples: list[tuple[float, int, int]] = []
        if log.exists():
            for ln in log.read_text().splitlines():
                parts = ln.split()
                if len(parts) < 4:
                    continue
                try:
                    ts = float(parts[0])
                    sid = parts[1]
                    ti = int(parts[2])
                    to = int(parts[3])
                except ValueError:
                    continue
                if sid == session_id and now - ts <= window + window / n_buckets:
                    samples.append((ts, ti, to))
        if len(samples) < 2:
            return [0] * n_buckets
        samples.sort()
        bucket_size = window / n_buckets
        last_bucket  = int(now // bucket_size)
        first_bucket = last_bucket - n_buckets + 1
        buckets = [0] * n_buckets
        for i in range(len(samples) - 1):
            ts0, ti0, to0 = samples[i]
            ts1, ti1, to1 = samples[i + 1]
            delta = max(0, (ti1 + to1) - (ti0 + to0))
            if delta == 0:
                continue
            midpoint = (ts0 + ts1) / 2
            abs_bucket = int(midpoint // bucket_size)
            if first_bucket <= abs_bucket <= last_bucket:
                buckets[abs_bucket - first_bucket] += delta
        return buckets

    @classmethod
    def recently_active(cls, session_id: str, window: float = 10.0) -> tuple[bool, bool]:
        """Return (in_active, out_active) — True if that count grew in the last `window` seconds."""
        if not session_id:
            return False, False
        log = CLAUDE_DIR / 'statusline-token-rate.log'
        if not log.exists():
            return False, False
        now = time.time()
        samples: list[tuple[float, int, int]] = []
        for ln in log.read_text().splitlines():
            parts = ln.split()
            if len(parts) < 4:
                continue
            try:
                ts, sid, ti, to = float(parts[0]), parts[1], int(parts[2]), int(parts[3])
            except ValueError:
                continue
            if sid == session_id and now - ts <= window:
                samples.append((ts, ti, to))
        if len(samples) < 2:
            return False, False
        samples.sort()
        ti0, to0 = samples[0][1], samples[0][2]
        ti1, to1 = samples[-1][1], samples[-1][2]
        return ti1 > ti0, to1 > to0


@dataclass
class GitInfo:
    branch: str = ''
    commit: str = ''
    modified: int = 0
    untracked: int = 0
    deleted: int = 0
    renamed: int = 0

    @classmethod
    def from_cwd(cls, cwd: str, session_id: str = '') -> GitInfo:
        repo, gitdir   = cls._find_repo(cwd)
        branch, commit = cls._read_head(gitdir)   # always live, so a branch switch shows immediately
        modified = untracked = deleted = renamed = 0
        if branch:
            modified, untracked, deleted, renamed = cls._dirty_cached(repo, cwd, session_id)
        return cls(
            branch    = branch,
            commit    = commit,
            modified  = modified,
            untracked = untracked,
            deleted   = deleted,
            renamed   = renamed,
        )

    @classmethod
    def _dirty_cached(cls, repo: str, cwd: str, session_id: str) -> tuple[int, int, int, int]:
        '''Cache the expensive `git status` dirty counts per session for
        GIT_CACHE_TTL seconds (the official statusline docs recommend exactly
        this). Only the counts are cached — branch/commit are re-read every
        render. Disabled without a session id, which keeps the cache out of the
        tmp_path-only git tests and out of any non-session caller.'''
        if not session_id:
            return cls._dirty(repo)
        cache_path = CLAUDE_DIR / 'statusline-git' / f'{session_id}.json'
        now = time.time()
        try:
            raw = cache_path.read_text()
        except OSError:
            raw = ''
        if raw:
            try:
                d = json.loads(raw)
            except ValueError:
                d = None
            if isinstance(d, dict):
                ts = d.get('ts')
                if (d.get('cwd') == cwd and isinstance(ts, (int, float))
                        and 0 <= now - ts <= GIT_CACHE_TTL):
                    return (_as_int(d.get('modified')), _as_int(d.get('untracked')),
                            _as_int(d.get('deleted')), _as_int(d.get('renamed')))
        modified, untracked, deleted, renamed = cls._dirty(repo)
        _atomic_write_text(cache_path, json.dumps({
            'v': 1, 'cwd': cwd, 'ts': now,
            'modified': modified, 'untracked': untracked, 'deleted': deleted, 'renamed': renamed,
        }))
        return modified, untracked, deleted, renamed

    @staticmethod
    def _find_repo(cwd: str) -> tuple[str, str]:
        curr = Path(cwd) if cwd else None
        while curr:
            dotgit = curr / '.git'
            if dotgit.exists():
                return str(curr), GitInfo._resolve_gitdir(dotgit)
            if curr == curr.parent:
                break
            curr = curr.parent
        return '', ''

    @staticmethod
    def _resolve_gitdir(dotgit: Path) -> str:
        '''Resolve a `.git` entry to the real git directory. `.git` is a
        directory in a normal clone, but a *file* containing `gitdir: <path>`
        in a linked worktree or submodule. Returns '' if unresolvable.'''
        if dotgit.is_dir():
            return str(dotgit)
        try:
            text = dotgit.read_text().strip()
        except OSError:
            return ''
        if text.startswith('gitdir:'):
            pointer = Path(text[len('gitdir:'):].strip())
            if not pointer.is_absolute():
                pointer = dotgit.parent / pointer
            try:
                return str(pointer.resolve())
            except OSError:
                return str(pointer)
        return ''

    @staticmethod
    def _read_head(gitdir: str) -> tuple[str, str]:
        if not gitdir:
            return '', ''
        gd = Path(gitdir)
        head_path = gd / 'HEAD'
        if not head_path.is_file():
            return '', ''
        try:
            head = head_path.read_text().strip()
        except OSError:
            return '', ''
        branch = ''
        if head.startswith('ref:'):
            target = head[4:].strip()
            prefix = 'refs/heads/'
            # Preserve the full branch namespace (e.g. 'feature/foo'); the old
            # rsplit('/', 1) collapsed it to 'foo'.
            branch = target[len(prefix):] if target.startswith(prefix) else target.rsplit('/', 1)[-1]
        elif head:
            branch = f'd:{head[:7]}'
        commit = ''
        if branch and not branch.startswith('d:'):
            commit = GitInfo._read_commit(gd, branch)
        if not commit:
            orig = gd / 'ORIG_HEAD'
            if orig.is_file():
                try:
                    commit = orig.read_text().strip()[:9]
                except OSError:
                    pass
        return branch, commit

    @staticmethod
    def _read_commit(gitdir: Path, branch: str) -> str:
        '''Resolve a branch's commit from a loose ref, the worktree common dir,
        or packed-refs — covering normal repos, linked worktrees (whose refs
        live in the common dir), and repos with packed refs.'''
        commondir = gitdir
        cd_file = gitdir / 'commondir'
        if cd_file.is_file():
            try:
                cd = Path(cd_file.read_text().strip())
                commondir = (cd if cd.is_absolute() else gitdir / cd).resolve()
            except OSError:
                commondir = gitdir
        for base in (gitdir, commondir):
            ref = base / 'refs' / 'heads' / branch
            if ref.is_file():
                try:
                    return ref.read_text().strip()[:9]
                except OSError:
                    pass
        packed = commondir / 'packed-refs'
        if packed.is_file():
            target = f'refs/heads/{branch}'
            try:
                for line in packed.read_text().splitlines():
                    line = line.strip()
                    if not line or line[0] in '#^':
                        continue
                    parts = line.split(' ', 1)
                    if len(parts) == 2 and parts[1] == target:
                        return parts[0][:9]
            except OSError:
                pass
        return ''

    @staticmethod
    def _dirty(repo: str) -> tuple[int, int, int, int]:
        modified = untracked = deleted = renamed = 0
        if not repo:
            return modified, untracked, deleted, renamed
        try:
            r = subprocess.run(
                ['git', '-C', repo, 'status', '--porcelain=v1', '-z',
                 '--untracked-files=normal'],
                capture_output=True, text=True, timeout=2,
            )
        except Exception:
            return modified, untracked, deleted, renamed
        entries = [e for e in r.stdout.split('\0') if e]
        i = 0
        while i < len(entries):
            entry = entries[i]
            if len(entry) < 2:
                i += 1
                continue
            x, y = entry[0], entry[1]
            if x == 'R' or y == 'R':
                renamed += 1
                i += 2  # rename consumes a second NUL-separated original-name field
                continue
            if x == '?' and y == '?':
                untracked += 1
            elif x == 'A' or y == 'A':
                untracked += 1
            elif x == 'D' or y == 'D':
                deleted += 1
            elif x == 'M' or y == 'M':
                modified += 1
            i += 1
        return modified, untracked, deleted, renamed


@dataclass
class LoadedSkills:
    names: list[str] = field(default_factory=list)

    @classmethod
    def from_transcript(cls, transcript_path: str) -> LoadedSkills:
        return _scan_transcript(transcript_path).loaded_skills()


@dataclass
class RunningSubagent:
    agent_type: str
    description: str
    billed_in: int
    output: int
    first_timestamp: float  # epoch seconds; baseline for live duration
    model:         str                   = ''
    cache_read_in: int                   = 0
    total_input:   int                   = 0
    last_activity: tuple[str, str, dict[str, object]] = field(default_factory=lambda: ('', '', {}))


@dataclass
class RunningSubagents:
    subagents: list[RunningSubagent] = field(default_factory=list)

    STALE_SECONDS = 20

    @classmethod
    def from_session(cls, session_id: str, project_dir: str) -> RunningSubagents:
        if not session_id or not project_dir:
            return cls()
        # Match Claude Code's projects/ dir convention: replace every non-
        # alphanumeric character with '-'. Works on both Unix
        # ('/home/user/my-project' -> '-home-user-my-project') and Windows
        # ('C:\\Users\\desal\\Project' -> 'C--Users-desal-Project'). The old
        # logic was Unix-only because it normalized only '/' and relied on a
        # leading slash producing the '-' prefix that Claude Code uses on
        # Unix; on Windows paths start with a drive letter (no leading '-'
        # in CC's dir name) so the f-string prefix gave a wrong path.
        project_slug = re.sub(r'[^A-Za-z0-9]', '-', project_dir)
        subagents_dir = CLAUDE_DIR / 'projects' / project_slug / session_id / 'subagents'
        if not subagents_dir.is_dir():
            return cls()
        now = time.time()
        subagents: list[RunningSubagent] = []
        try:
            for meta in subagents_dir.glob('*.meta.json'):
                agent_type = ''
                description = ''
                try:
                    data = json.loads(meta.read_text())
                    agent_type = data.get('agentType', '')
                    description = data.get('description', '')
                except Exception:
                    continue

                jsonl = meta.with_suffix('').with_suffix('.jsonl')
                if not jsonl.is_file():
                    continue
                try:
                    mtime = jsonl.stat().st_mtime
                    if now - mtime > cls.STALE_SECONDS:
                        continue
                except OSError:
                    continue

                billed_in, cache_read_in, output, first_ts, model, last_activity = cls._parse_transcript(jsonl)
                subagents.append(RunningSubagent(
                    agent_type      = agent_type,
                    description     = description,
                    billed_in       = billed_in,
                    output          = output,
                    first_timestamp = first_ts,
                    model           = model,
                    cache_read_in   = cache_read_in,
                    total_input     = billed_in + cache_read_in,
                    last_activity   = last_activity,
                ))
        except OSError:
            pass
        subagents.sort(key=lambda s: s.first_timestamp)
        return cls(subagents=subagents)

    @staticmethod
    def _parse_transcript(jsonl: Path) -> tuple[int, int, int, float, str, tuple[str, str, dict[str, object]]]:
        seen: set[str] = set()
        billed_in    = 0
        cache_read_in = 0
        output       = 0
        first_ts     = 0.0
        model        = ''
        last_activity: tuple[str, str, dict[str, object]] = ('', '', {})
        try:
            with jsonl.open('r', errors='ignore') as fh:
                for ln in fh:
                    if first_ts == 0.0 and '"timestamp"' in ln:
                        try:
                            d = json.loads(ln)
                            ts = d.get('timestamp', '')
                            if ts:
                                first_ts = _parse_iso_to_epoch(ts)
                        except (ValueError, TypeError):
                            pass
                    if '"usage"' not in ln or '"assistant"' not in ln:
                        continue
                    try:
                        d = json.loads(ln)
                    except (ValueError, TypeError):
                        continue
                    msg = d.get('message') or {}
                    mid = msg.get('id')
                    if not mid or mid in seen:
                        continue
                    seen.add(mid)
                    if not model:
                        m = msg.get('model') or ''
                        if m:
                            model = m
                    u = msg.get('usage') or {}
                    billed_in     += (u.get('input_tokens', 0) or 0) + (u.get('cache_creation_input_tokens', 0) or 0)
                    cache_read_in += u.get('cache_read_input_tokens', 0) or 0
                    output        += u.get('output_tokens', 0) or 0
                    content = msg.get('content') or []
                    if content:
                        item = content[-1]
                        kind = item.get('type', '')
                        if kind == 'tool_use':
                            last_activity = ('tool_use', item.get('name', ''), item.get('input') or {})
                        elif kind == 'thinking':
                            last_activity = ('thinking', '', {})
                        elif kind == 'text':
                            last_activity = ('text', '', {})
        except OSError:
            pass
        return billed_in, cache_read_in, output, first_ts, model, last_activity


def _parse_iso_to_epoch(ts: str) -> float:
    try:
        if ts.endswith('Z'):
            ts = ts[:-1] + '+00:00'
        return datetime.fromisoformat(ts).timestamp()
    except (ValueError, TypeError):
        return 0.0


@dataclass
class Task:
    id: int
    subject: str
    active_form: str
    status: str  # 'pending' | 'in_progress' | 'completed'


@dataclass
class TaskList:
    tasks: list[Task] = field(default_factory=list)
    last_event_ts: float = 0.0

    FRESHNESS_CAP = 120.0  # 2 min — see docs/adr/0004
    GRACE_SECONDS = 20.0   # matches RunningSubagents.STALE_SECONDS

    @classmethod
    def from_session(cls, transcript_path: str) -> TaskList:
        return _scan_transcript(transcript_path).task_list()

    @property
    def total(self) -> int:
        return len(self.tasks)

    @property
    def completed(self) -> int:
        return sum(1 for t in self.tasks if t.status == 'completed')

    @property
    def active(self) -> Task | None:
        for t in reversed(self.tasks):
            if t.status == 'in_progress':
                return t
        return None

    @property
    def next_pending(self) -> Task | None:
        for t in self.tasks:
            if t.status == 'pending':
                return t
        return None

    def is_visible(self, now: float | None = None) -> bool:
        if not self.tasks or self.last_event_ts <= 0:
            return False
        if now is None:
            now = time.time()
        age = now - self.last_event_ts
        if age > self.FRESHNESS_CAP:
            return False
        if self.completed == self.total:
            return age <= self.GRACE_SECONDS
        return True


@dataclass
class TranscriptUsage:
    input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    output_tokens: int = 0

    @classmethod
    def from_transcript(cls, transcript_path: str) -> TranscriptUsage:
        return _scan_transcript(transcript_path).transcript_usage()

    @property
    def billed_in(self) -> int:
        return self.input_tokens + self.cache_creation_input_tokens

    @property
    def cache_read(self) -> int:
        return self.cache_read_input_tokens

    @property
    def out(self) -> int:
        return self.output_tokens


# Regexes for skill detection in a transcript line. Module-level so they are
# compiled once per process instead of once per scan (the legacy code rebuilt
# them on every call).
_SKILL_PAT      = re.compile(r'"name"\s*:\s*"Skill"[^}]*?"skill"\s*:\s*"([^"]+)"')
_READ_PAT       = re.compile(r'"name"\s*:\s*"Read"[^}]*?"file_path"\s*:\s*"([^"]+)"')
_SKILL_PATH_PAT = re.compile(r'/skills/([^/"]+)/SKILL\.md$')


@dataclass
class TranscriptScan:
    '''Single pass over a session transcript JSONL, producing the three
    aggregates the renderer needs (loaded skills, task list, token usage) in
    one read instead of three independent full-file scans.

    Each line is decoded with json at most once, and only when a cheap
    substring pre-check matches, exactly as the three legacy scanners did
    individually. The projection methods rebuild the public LoadedSkills /
    TaskList / TranscriptUsage dataclasses so existing callers and tests see
    identical results.
    '''
    skill_names:                 dict[str, None] = field(default_factory=dict)
    usage_seen:                  set[str]        = field(default_factory=set)
    input_tokens:                int             = 0
    cache_creation_input_tokens: int             = 0
    cache_read_input_tokens:     int             = 0
    output_tokens:               int             = 0
    by_id:                       dict[int, Task] = field(default_factory=dict)
    next_id:                     int             = 1
    last_event_ts:               float           = 0.0

    @classmethod
    def scan_full(cls, transcript_path: str) -> TranscriptScan:
        'Read the whole transcript from the start. Always correct; the fallback for incremental tailing.'
        scan = cls()
        if not transcript_path:
            return scan
        p = Path(transcript_path)
        if not p.is_file():
            return scan
        try:
            with p.open('rb') as fh:
                data = fh.read()
        except OSError:
            return cls()
        scan._process_bytes(data)
        return scan

    def _process_bytes(self, data: bytes) -> int:
        '''Fold every complete (newline-terminated) line in `data` into the scan
        and return the bytes consumed (up to and including the last newline). Any
        unterminated trailing fragment is left unprocessed, so a mid-write final
        line is never counted. Shared by the full and incremental paths so their
        results are identical by construction.'''
        consumed = data.rfind(b'\n') + 1
        for raw in data[:consumed].split(b'\n'):
            if raw:
                self.process_line(raw.decode('utf-8', 'ignore'))
        return consumed

    def process_line(self, line: str) -> None:
        'Fold a single transcript line into all three aggregates (skills, tasks, usage).'
        if '"Skill"' in line:
            for m in _SKILL_PAT.finditer(line):
                self.skill_names.setdefault(m.group(1), None)
        if '"Read"' in line and 'SKILL.md' in line:
            for m in _READ_PAT.finditer(line):
                sm = _SKILL_PATH_PAT.search(m.group(1))
                if sm:
                    self.skill_names.setdefault(sm.group(1), None)
        need_usage = '"usage"' in line and '"assistant"' in line
        need_task  = '"TaskCreate"' in line or '"TaskUpdate"' in line
        if not (need_usage or need_task):
            return
        try:
            d = json.loads(line)
        except (ValueError, TypeError):
            return
        if not isinstance(d, dict):
            return
        if need_usage:
            self._apply_usage(d)
        if need_task:
            self._apply_tasks(d)

    def _apply_usage(self, d: dict[str, object]) -> None:
        msg = d.get('message')
        if not isinstance(msg, dict):
            return
        mid = msg.get('id')
        if not mid or mid in self.usage_seen:
            return
        self.usage_seen.add(mid)
        u_raw = msg.get('usage')
        u = u_raw if isinstance(u_raw, dict) else {}
        self.input_tokens                += _as_int(u.get('input_tokens'))
        self.cache_creation_input_tokens += _as_int(u.get('cache_creation_input_tokens'))
        self.cache_read_input_tokens     += _as_int(u.get('cache_read_input_tokens'))
        self.output_tokens               += _as_int(u.get('output_tokens'))

    def _apply_tasks(self, d: dict[str, object]) -> None:
        msg = d.get('message')
        if not isinstance(msg, dict):
            return
        raw_ts = d.get('timestamp', '')
        ts = _parse_iso_to_epoch(raw_ts) if isinstance(raw_ts, str) else 0.0
        content = msg.get('content', [])
        if not isinstance(content, list):
            return
        for c in content:
            if not isinstance(c, dict) or c.get('type') != 'tool_use':
                continue
            name = c.get('name', '')
            inp  = c.get('input') or {}
            if not isinstance(inp, dict):
                continue
            if name == 'TaskCreate':
                subj = inp.get('subject', '') or ''
                af   = inp.get('activeForm', '') or subj
                self.by_id[self.next_id] = Task(id=self.next_id, subject=subj, active_form=af, status='pending')
                self.next_id += 1
                if ts > self.last_event_ts:
                    self.last_event_ts = ts
            elif name == 'TaskUpdate':
                try:
                    tid = int(inp.get('taskId', '0'))
                except (TypeError, ValueError):
                    continue
                t = self.by_id.get(tid)
                if not t:
                    continue
                new_status = inp.get('status')
                if new_status in ('pending', 'in_progress', 'completed'):
                    t.status = new_status
                if 'activeForm' in inp and inp['activeForm']:
                    t.active_form = inp['activeForm']
                if 'subject' in inp and inp['subject']:
                    t.subject = inp['subject']
                if ts > self.last_event_ts:
                    self.last_event_ts = ts

    def loaded_skills(self) -> LoadedSkills:
        return LoadedSkills(names=list(self.skill_names))

    def transcript_usage(self) -> TranscriptUsage:
        return TranscriptUsage(
            input_tokens                = self.input_tokens,
            cache_creation_input_tokens = self.cache_creation_input_tokens,
            cache_read_input_tokens     = self.cache_read_input_tokens,
            output_tokens               = self.output_tokens,
        )

    def task_list(self) -> TaskList:
        # Fresh Task objects so a cached scan can't be mutated through a projection.
        tasks = [
            Task(id=t.id, subject=t.subject, active_form=t.active_form, status=t.status)
            for t in (self.by_id[k] for k in sorted(self.by_id))
        ]
        return TaskList(tasks=tasks, last_event_ts=self.last_event_ts)

    def to_state(self) -> dict[str, object]:
        'Serialize the accumulator for incremental-tailing persistence.'
        return {
            'skills':  list(self.skill_names),
            'seen':    list(self.usage_seen),
            'in':      self.input_tokens,
            'cc':      self.cache_creation_input_tokens,
            'cr':      self.cache_read_input_tokens,
            'out':     self.output_tokens,
            'tasks':   [{'id': t.id, 'subject': t.subject, 'active_form': t.active_form, 'status': t.status}
                        for t in (self.by_id[k] for k in sorted(self.by_id))],
            'next_id': self.next_id,
            'last_ts': self.last_event_ts,
        }

    @classmethod
    def from_state(cls, d: dict[str, object]) -> TranscriptScan:
        'Rehydrate an accumulator persisted by to_state (defensive against malformed data).'
        scan = cls()
        skills = d.get('skills')
        if isinstance(skills, list):
            scan.skill_names = {s: None for s in skills if isinstance(s, str)}
        seen = d.get('seen')
        if isinstance(seen, list):
            scan.usage_seen = {s for s in seen if isinstance(s, str)}
        scan.input_tokens                = _as_int(d.get('in'))
        scan.cache_creation_input_tokens = _as_int(d.get('cc'))
        scan.cache_read_input_tokens     = _as_int(d.get('cr'))
        scan.output_tokens               = _as_int(d.get('out'))
        tasks = d.get('tasks')
        if isinstance(tasks, list):
            for t in tasks:
                if isinstance(t, dict):
                    tid = _as_int(t.get('id'))
                    scan.by_id[tid] = Task(
                        id          = tid,
                        subject     = _as_str(t.get('subject')),
                        active_form = _as_str(t.get('active_form')),
                        status      = _as_str(t.get('status'), 'pending'),
                    )
        ni = d.get('next_id')
        scan.next_id = ni if isinstance(ni, int) and ni >= 1 else (max(scan.by_id, default=0) + 1)
        scan.last_event_ts = _as_float(d.get('last_ts'))
        return scan


# One-slot, file-identity-keyed cache so the three projections requested within a
# single wide render share ONE scan. Keyed on (path, size, mtime_ns).
_SCAN_CACHE: tuple[tuple[str, int, int], TranscriptScan] | None = None
_SCAN_STATE_V = 1


def _incremental_enabled(p: Path) -> bool:
    '''Incremental tailing applies only to real Claude session transcripts (those
    under CLAUDE_DIR/projects) — this keeps state writes out of arbitrary
    directories and out of the tmp_path-only tests. YAS_NO_INCREMENTAL is a kill
    switch that forces the always-correct full scan.'''
    if os.environ.get('YAS_NO_INCREMENTAL'):
        return False
    try:
        return p.resolve().is_relative_to((CLAUDE_DIR / 'projects').resolve())
    except (OSError, ValueError):
        return False


def _scan_state_path(p: Path) -> Path:
    h = hashlib.sha1(str(p).encode('utf-8')).hexdigest()[:16]
    return CLAUDE_DIR / 'statusline-scan' / f'{h}.json'


def _resume_point(state_path: Path, p: Path, st: os.stat_result) -> tuple[TranscriptScan, int]:
    '''(scan, start_offset) to resume from, or (empty, 0) to force a full re-scan
    on any mismatch: missing/corrupt state, schema bump, path or inode change
    (rotation/replacement), or an offset past EOF (truncation/shrink).'''
    try:
        d = json.loads(state_path.read_text())
    except (OSError, ValueError):
        return TranscriptScan(), 0
    if (not isinstance(d, dict) or d.get('v') != _SCAN_STATE_V
            or d.get('path') != str(p) or d.get('inode') != st.st_ino):
        return TranscriptScan(), 0
    offset = d.get('offset')
    scan_d = d.get('scan')
    if not isinstance(offset, int) or offset < 0 or offset > st.st_size or not isinstance(scan_d, dict):
        return TranscriptScan(), 0
    return TranscriptScan.from_state(scan_d), offset


def _save_scan_state(state_path: Path, p: Path, st: os.stat_result, offset: int, scan: TranscriptScan) -> None:
    _atomic_write_text(state_path, json.dumps({
        'v':      _SCAN_STATE_V,
        'path':   str(p),
        'inode':  st.st_ino,
        'offset': offset,
        'scan':   scan.to_state(),
    }))


def _scan_with_state(p: Path, st: os.stat_result) -> TranscriptScan:
    'Read only the bytes appended since the persisted offset; persist the advanced state.'
    state_path = _scan_state_path(p)
    scan, start = _resume_point(state_path, p, st)
    new_offset = start
    if start < st.st_size:
        with p.open('rb') as fh:
            fh.seek(start)
            data = fh.read()
        new_offset = start + scan._process_bytes(data)
    if new_offset != start:
        _save_scan_state(state_path, p, st, new_offset, scan)
    return scan


def _scan_transcript(transcript_path: str) -> TranscriptScan:
    '''Cached single-pass scan shared by the three projection classmethods within
    one render. For real session transcripts it tails incrementally (reading only
    newly-appended bytes via a persisted accumulator); everything else, and any
    anomaly, falls back to the always-correct full scan.'''
    global _SCAN_CACHE
    if not transcript_path:
        return TranscriptScan()
    p = Path(transcript_path)
    if not p.is_file():
        return TranscriptScan()
    try:
        st = p.stat()
    except OSError:
        return TranscriptScan()
    key = (str(p), st.st_size, st.st_mtime_ns)
    cached = _SCAN_CACHE
    if cached is not None and cached[0] == key:
        return cached[1]
    if _incremental_enabled(p):
        try:
            scan = _scan_with_state(p, st)
        except Exception:
            scan = TranscriptScan.scan_full(transcript_path)
    else:
        scan = TranscriptScan.scan_full(transcript_path)
    _SCAN_CACHE = (key, scan)
    return scan


@dataclass
class OpenSpec:
    changes: list[tuple[str, int, int]] = field(default_factory=list)

    @classmethod
    def from_cwd(cls, cwd: str) -> OpenSpec:
        root = cls._find_root(cwd)
        if not root:
            return cls()
        out: list[tuple[str, int, int]] = []
        open_re = re.compile(r'^\s*- \[ \]')
        done_re = re.compile(r'^\s*- \[x\]')
        for tasks in sorted(Path(root).rglob('tasks.md')):
            if '/archive/' in str(tasks):
                continue
            try:
                text = tasks.read_text()
            except OSError:
                continue
            t = sum(1 for ln in text.splitlines() if open_re.match(ln))
            d = sum(1 for ln in text.splitlines() if done_re.match(ln))
            total = t + d
            if total == 0:
                continue
            out.append((tasks.parent.name, d, total))
        return cls(changes=out)

    @staticmethod
    def _find_root(cwd: str) -> str:
        curr = Path(cwd) if cwd else None
        while curr:
            if (curr / 'openspec').is_dir():
                return str(curr / 'openspec')
            if curr == curr.parent:
                break
            curr = curr.parent
        return ''


def sparkline_width(terminal_width: int) -> int:
    if terminal_width >= 130:
        return 30
    if terminal_width >= 110:
        return 20
    if terminal_width >= 90:
        return 10
    return 0


def fmt_tok(n: int) -> str:
    # Promote at the rounding boundary (>= 999.95 rounds to 1000.0 at .1f) so the
    # result never exceeds 6 visible chars ("999.9B") and stays within the token
    # column budget (IN_W/CACHE_W/OUT_W = 6). Without the billions tier, a
    # multi-billion day total renders as "4660.5M" (7 chars) and pushes that
    # row's dividers one cell out of alignment.
    if n >= 999_950_000:
        return f'{n/1_000_000_000:.1f}B'
    if n >= 999_950:
        return f'{n/1_000_000:.1f}M'
    if n >= 1000:
        return f'{n/1000:.1f}K'
    return str(n)


def fmt_dur(seconds: float) -> str:
    s = int(seconds)
    if s < 0:
        s = 0
    if s < 60:
        return f'{s}s'
    if s < 3600:
        return f'{s // 60}m{s % 60:02d}s'
    return f'{s // 3600}h{(s % 3600) // 60:02d}m'


RAINBOW_PALETTE = (
    196, 202, 208, 214, 220, 226, 190, 154, 118, 82,
    46, 47, 48, 49, 50, 51, 45, 39, 33, 27,
    21, 57, 93, 129, 165, 201, 200, 199, 198, 197,
)


def rainbow_step() -> int:
    return int(time.time()) % len(RAINBOW_PALETTE)


def rainbow_at(step: int, offset: int = 0) -> str:
    color = RAINBOW_PALETTE[(step + offset) % len(RAINBOW_PALETTE)]
    return f'\033[38;5;{color}m'


def rainbow_color() -> str:
    return rainbow_at(rainbow_step())


LEVEL_PCT = {
    'low':    30,
    'medium': 55,
    'high':   80,
    'xhigh':  100,
    'max':    140,
}

BG_LUM_THRESHOLD = 110


def model_key(name: str) -> str:
    m = name.lower()
    if 'opus'   in m: return 'opus'
    if 'sonnet' in m: return 'sonnet'
    if 'haiku'  in m: return 'haiku'
    return 'other'


def _scale(rgb: tuple[int, int, int], pct: int) -> tuple[int, int, int]:
    r, g, b = rgb
    return (min(255, max(0, r * pct // 100)),
            min(255, max(0, g * pct // 100)),
            min(255, max(0, b * pct // 100)))


def paint_bg_span(cells: list[tuple[str, tuple[int, int, int] | None, bool, bool]],
                  anchor: tuple[int, int, int],
                  shift: tuple[int, int, int],
                  pct: int,
                  pill_fg_dark:  tuple[int, int, int] = (15, 15, 15),
                  pill_fg_light: tuple[int, int, int] | None = None) -> str:
    c0 = _scale(anchor, pct)
    c1 = _scale(shift, pct)
    n = max(1, len(cells) - 1)
    parts: list[str] = []
    prev_bg = prev_fg = None
    prev_bold = prev_italic = False
    for i, (ch, fg, bold, italic) in enumerate(cells):
        t = i / n
        r = int(c0[0] + (c1[0] - c0[0]) * t)
        g = int(c0[1] + (c1[1] - c0[1]) * t)
        b = int(c0[2] + (c1[2] - c0[2]) * t)
        lum = (r * 299 + g * 587 + b * 114) // 1000
        fg_rgb: tuple[int, int, int] | None
        if lum >= BG_LUM_THRESHOLD:
            fg_rgb = pill_fg_dark
        elif pill_fg_light is not None:
            fg_rgb = pill_fg_light
        else:
            fg_rgb = fg
        cur_bg = (r, g, b)
        if cur_bg != prev_bg:
            parts.append(f'\033[48;2;{r};{g};{b}m')
            prev_bg = cur_bg
        if fg_rgb != prev_fg:
            if fg_rgb is None:
                parts.append('\033[39m')
            else:
                parts.append(f'\033[38;2;{fg_rgb[0]};{fg_rgb[1]};{fg_rgb[2]}m')
            prev_fg = fg_rgb
        if bold != prev_bold:
            parts.append('\033[1m' if bold else '\033[22m')
            prev_bold = bold
        if italic != prev_italic:
            parts.append('\033[3m' if italic else '\033[23m')
            prev_italic = italic
        parts.append(ch)
    parts.append('\033[49m')
    if prev_bold:
        parts.append('\033[22m')
    if prev_italic:
        parts.append('\033[23m')
    parts.append('\033[39m')
    return ''.join(parts)



def pill_gradient_fg(col: int, pill_start: int, pill_end: int,
                     anchor: tuple[int, int, int], shift: tuple[int, int, int],
                     pct: int) -> str:
    c0 = _scale(anchor, pct)
    c1 = _scale(shift, pct)
    span = max(1, pill_end - pill_start)
    t = (col - pill_start) / span
    t = max(0.0, min(1.0, t))
    r = int(c0[0] + (c1[0] - c0[0]) * t)
    g = int(c0[1] + (c1[1] - c0[1]) * t)
    b = int(c0[2] + (c1[2] - c0[2]) * t)
    return f'[38;2;{r};{g};{b}m'


class GradientEngine:
    FADE        = 0.06
    SPARK_CHARS = '▁▂▃▄▅▆▇█'

    def __init__(self, theme: Theme | None = None) -> None:
        t = theme if theme is not None else CLAUDE_DARK
        self.theme       = t
        self.GRAD_STOPS  = t.grad_stops
        self.GREY_RGB    = t.grey_rgb
        self.SPARK_STOPS = t.spark_stops
        self.BORDER_OFF  = t.border_off

    def spark_rgb(self, t: float, dim: float = 1.0) -> tuple[int, int, int]:
        t = max(0.0, min(1.0, t))
        for i in range(len(self.SPARK_STOPS) - 1):
            t0, c0 = self.SPARK_STOPS[i]
            t1, c1 = self.SPARK_STOPS[i + 1]
            if t <= t1:
                u = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
                r = int((c0[0] + (c1[0] - c0[0]) * u) * dim)
                g = int((c0[1] + (c1[1] - c0[1]) * u) * dim)
                b = int((c0[2] + (c1[2] - c0[2]) * u) * dim)
                return r, g, b
        r, g, b = self.SPARK_STOPS[-1][1]
        return int(r * dim), int(g * dim), int(b * dim)

    def spark_color(self, t: float, dim: float = 1.0) -> str:
        r, g, b = self.spark_rgb(t, dim)
        return f'\033[38;2;{r};{g};{b}m'

    def gradient_rgb(self, t: float, dim: float = 1.0) -> tuple[int, int, int]:
        t = max(0.0, min(1.0, t))
        for i in range(len(self.GRAD_STOPS) - 1):
            t0, c0 = self.GRAD_STOPS[i]
            t1, c1 = self.GRAD_STOPS[i + 1]
            if t <= t1:
                u = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
                r = int((c0[0] + (c1[0] - c0[0]) * u) * dim)
                g = int((c0[1] + (c1[1] - c0[1]) * u) * dim)
                b = int((c0[2] + (c1[2] - c0[2]) * u) * dim)
                return r, g, b
        r, g, b = self.GRAD_STOPS[-1][1]
        return int(r * dim), int(g * dim), int(b * dim)

    def gradient_color(self, t: float, dim: float = 1.0) -> str:
        r, g, b = self.gradient_rgb(t, dim)
        return f'\033[38;2;{r};{g};{b}m'

    def grad_at(self, col: int, width: int, dim: float = 1.0, fill: float = 1.0) -> str:
        denom = max(1, width - 1)
        t = col / denom
        if fill <= 0:
            return self.BORDER_OFF
        fade = self.FADE
        if t <= fill - fade:
            return self.gradient_color(t, dim)
        if t >= fill + fade:
            return self.BORDER_OFF
        er, eg, eb = self.gradient_rgb(min(t, fill), dim)
        gr, gg, gb = self.GREY_RGB
        u = max(0.0, min(1.0, (t - (fill - fade)) / (2 * fade)))
        r = int(er + (gr - er) * u)
        g = int(eg + (gg - eg) * u)
        b = int(eb + (gb - eb) * u)
        return f'\033[38;2;{r};{g};{b}m'

    def gradient_bar(self, filled: int, bar_w: int) -> str:
        if filled <= 0 or bar_w <= 0:
            return ''
        denom = max(1, bar_w - 1)
        parts = []
        for i in range(filled):
            r, g, b = self.gradient_rgb(i / denom)
            parts.append(f'\033[48;2;{r};{g};{b}m ')
        if filled <= bar_w:
            parts.append(f'\033[49m{self.gradient_color(filled / denom)}{BarChars.MID}')
        return ''.join(parts)

    def _spark_flat(self, idx: int) -> tuple[str, str]:
        if idx <= 0:
            return ' ', self.SPARK_CHARS[0]
        if idx <= 8:
            return ' ', self.SPARK_CHARS[idx - 1]
        return self.SPARK_CHARS[idx - 9], '█'

    def _spark_rise(self, idx: int) -> tuple[str, str]:
        if idx <= 0:
            return ' ', self.SPARK_CHARS[0]
        if idx <= 3:
            return ' ', SPARK_RISE_SMALL
        if idx <= 7:
            return ' ', SPARK_RISE_MED
        if idx <= 8:
            return ' ', SPARK_RISE_TALL
        return SPARK_RISE_TOP, SPARK_RISE_TALL

    def _spark_fall(self, idx: int) -> tuple[str, str]:
        if idx <= 0:
            return ' ', self.SPARK_CHARS[0]
        if idx <= 3:
            return ' ', SPARK_FALL_SMALL
        if idx <= 7:
            return ' ', SPARK_FALL_MED
        if idx <= 8:
            return ' ', SPARK_FALL_TALL
        return SPARK_FALL_TOP, SPARK_FALL_TALL

    def sparkline(self, history: list[int], live: bool = False) -> tuple[str, str]:
        if not history:
            return '', ''
        max_val = max(history)
        indices = [
            min(int(((v / max_val) if max_val > 0 else 0.0) * 16), 16)
            for v in history
        ]
        last_i  = len(indices) - 1
        top_parts = []
        bot_parts = []
        for i, idx in enumerate(indices):
            prev_idx = indices[i - 1] if i > 0 else 0
            if idx > prev_idx:
                top_ch, bot_ch = self._spark_rise(idx)
                tint_idx       = idx
            elif prev_idx > idx:
                top_ch, bot_ch = self._spark_fall(prev_idx)
                tint_idx       = prev_idx
            else:
                top_ch, bot_ch = self._spark_flat(idx)
                tint_idx       = idx
            ratio     = tint_idx / 16.0
            ratio_bot = ratio * 0.5
            ratio_top = 0.5 + ratio * 0.5
            if live and i == last_i:
                bot_clr = self.spark_color(ratio_bot, dim=LIVE_DIM)
                top_clr = self.spark_color(ratio_top, dim=LIVE_DIM)
            else:
                bot_clr = self.spark_color(ratio_bot)
                top_clr = self.spark_color(ratio_top)
            top_parts.append(f'{top_clr}{top_ch}{RESET}')
            bot_parts.append(f'{bot_clr}{bot_ch}{RESET}')
        return ''.join(top_parts), ''.join(bot_parts)


class BorderRenderer:
    def __init__(self, gradient: GradientEngine):
        self.gradient = gradient
        self.SESSION  = gradient.theme.session

    R = RESET

    def border_top(self, width: int, session_id: str = '', downs: tuple[int, ...] = (), fill: float = 1.0, pill: Pill | None = None) -> str:
        downs_set = set(downs)
        p = pill or Pill()
        def _ch(col: int) -> str:
            pc = p.border_char(col, 'top')
            if pc:
                return pc
            return '┬' if col in downs_set else '─'
        def _clr(col: int, pos: int) -> str:
            if p.active and p.start <= col <= p.end:
                return p.border_fg(col)
            return self.gradient.grad_at(pos, width, fill=fill)
        if p.active and p.start <= 1:
            parts = [p.border_fg(p.start), PILL_TL]
        else:
            parts = [self.gradient.grad_at(0, width, fill=fill), '╭']
        if session_id:
            avail = max(0, width - 4)
            if p.active and p.end == width and p.start > 5:
                avail = max(0, min(avail, p.start - 5))
            sid = session_id if len(session_id) <= avail else session_id[:max(0, avail - 1)] + '…'
            sid_w = _visible_width(sid)
            parts += [_clr(2, 1), _ch(2), _clr(3, 2), _ch(3), self.SESSION, ITALIC, sid, '\033[23m']
            offset = 3 + sid_w
            rest = max(0, width - 4 - sid_w)
            for i in range(rest):
                col = offset + i + 1
                parts += [_clr(col, offset + i), _ch(col)]
        else:
            for i in range(1, width - 1):
                col = i + 1
                parts += [_clr(col, i), _ch(col)]
        if p.active and p.start <= width <= p.end:
            parts += [p.border_fg(width), p.border_char(width, 'top'), self.R]
        else:
            parts += [self.gradient.grad_at(width - 1, width, fill=fill), '╮', self.R]
        return ''.join(parts)

    def border_bottom(self, width: int, ups: tuple[int, ...] = (), fill: float = 1.0) -> str:
        ups_set = set(ups)
        parts = [self.gradient.grad_at(0, width, fill=fill), '╰']
        for i in range(width - 2):
            ch = '┴' if (i + 2) in ups_set else '─'
            parts += [self.gradient.grad_at(i + 1, width, fill=fill), ch]
        parts += [self.gradient.grad_at(width - 1, width, fill=fill), '╯', self.R]
        return ''.join(parts)

    def border_separator(self, width: int, ups: tuple[int, ...] = (), fill: float = 1.0) -> str:
        ups_set = set(ups)
        parts = [self.gradient.grad_at(0, width, fill=fill), '├']
        for i in range(width - 2):
            ch = '┴' if (i + 2) in ups_set else '─'
            parts += [self.gradient.grad_at(i + 1, width, fill=fill), ch]
        parts += [self.gradient.grad_at(width - 1, width, fill=fill), '┤', self.R]
        return ''.join(parts)

    DIM_MIN  = 0.6
    DIM_RAMP = 5

    def _dim_for_col(self, col: int, elbow_cols: set[int]) -> float:
        d = min(abs(col - e) for e in elbow_cols)
        if d == 0:
            return 1.0
        return max(self.DIM_MIN, 1.0 - (1.0 - self.DIM_MIN) * (d / self.DIM_RAMP))

    def border_separator_dim(self, width: int, downs: tuple[int, ...] = (), ups: tuple[int, ...] = (), fill: float = 1.0, pill: Pill | None = None, pill_edge: str = 'bottom') -> str:
        downs_set = set(downs)
        ups_set = set(ups)
        elbow_cols = {1, width} | downs_set | ups_set
        p = pill or Pill()
        edge = pill_edge if pill_edge == 'top' else 'bottom'
        if p.active and p.start <= 1:
            parts = [p.border_fg(p.start), p.border_char(p.start, edge)]
        else:
            parts = [self.gradient.grad_at(0, width, self._dim_for_col(1, elbow_cols), fill=fill), '├']
        for i in range(width - 2):
            col = i + 2
            pc = p.border_char(col, edge) if p.active else ''
            if pc:
                parts += [p.border_fg(col), pc]
            else:
                if col in downs_set and col in ups_set:
                    ch = '┼'
                elif col in downs_set:
                    ch = '┬'
                elif col in ups_set:
                    ch = '┴'
                else:
                    ch = '┄'
                parts += [self.gradient.grad_at(i + 1, width, self._dim_for_col(col, elbow_cols), fill=fill), ch]
        if p.active and p.start <= width <= p.end:
            parts += [p.border_fg(width), p.border_char(width, edge), self.R]
        else:
            parts += [self.gradient.grad_at(width - 1, width, self._dim_for_col(width, elbow_cols), fill=fill), '┤', self.R]
        return ''.join(parts)

    def border_line(self, content: str, width: int, fill: float = 1.0, bg_lead: str = '', bg_trail: str = '', pill_flush: bool = False, right_pill: str = '') -> str:
        if right_pill:
            pill_w  = _visible_width(right_pill)
            pad     = max(0, width - 2 - _visible_width(content) - pill_w)
            left    = self.gradient.grad_at(0, width, fill=fill)
            lead    = f'{bg_lead} \033[49m' if bg_lead else ' '
            return f'{left}│{self.R}{lead}{content}{" " * pad}{right_pill}{self.R}'
        if pill_flush:
            pad = max(0, width - 1 - _visible_width(content))
            right = self.gradient.grad_at(width - 1, width, fill=fill)
            pad_str = ' ' * pad
            return f'{content}{pad_str}{right}│{self.R}'
        pad = max(0, width - 3 - _visible_width(content))
        left  = self.gradient.grad_at(0, width, fill=fill)
        right = self.gradient.grad_at(width - 1, width, fill=fill)
        lead = f'{bg_lead} \033[49m' if bg_lead else ' '
        if bg_trail and pad > 0:
            pad_str = f'{" " * (pad - 1)}{bg_trail} \033[49m'
        else:
            pad_str = ' ' * pad
        return f'{left}│{self.R}{lead}{content}{pad_str}{right}│{self.R}'


class Renderer:
    def __init__(self, bg_shift: str = 'warm', theme: Theme | None = None) -> None:
        self.bg_shift = bg_shift if bg_shift in ('warm', 'cool') else 'warm'
        self.theme    = theme if theme is not None else CLAUDE_DARK
        self.gradient = GradientEngine(self.theme)
        self.border   = BorderRenderer(self.gradient)
        self._apply_theme(self.theme)

    def _apply_theme(self, t: Theme) -> None:
        self.BORDER      = t.border
        self.PWD         = t.pwd
        self.BRANCH      = t.branch
        self.COMMIT      = t.commit
        self.SESSION     = t.session
        self.MODEL       = t.model
        self.SKILLS      = t.skills
        self.TIME        = t.time
        self.TOK         = t.tok
        self.TOK_DIM     = t.tok_dim
        self.TOK_DAY     = t.tok_day
        self.TOK_DAY_DIM = t.tok_day_dim
        self.COST        = t.cost
        self.BAR_FILL    = t.bar_fill
        self.BAR_EMPTY   = t.bar_empty
        self.DIM_GREEN   = t.dim_green
        self.LABEL       = t.label
        self.CTX         = t.ctx
        self.CTX_DIM     = t.ctx_dim
        self.BOLDW       = BOLD + t.white_brt
        self.BOLDY       = t.tok_arrow
        self.DIRTY       = t.dirty
        self.ICON_PATH   = t.icon_path
        self.ARROW       = t.arrow
        self.TOK_ICON    = t.tok_icon
        self.OPUS        = t.models['opus'].label
        self.SONNET      = t.models['sonnet'].label
        self.HAIKU       = t.models['haiku'].label
        self.safe        = t.safe
        self.warn        = t.warn
        self.alert       = t.alert
        self.yellow      = t.yellow
        self.white_brt   = t.white_brt
        self.pill_fg_dark    = t.pill_fg_dark
        self.pill_fg_light   = t.pill_fg_light
        self.SPEC_GRADIENTS  = t.spec_gradients
        self.spec_empty_ansi = t.spec_empty_ansi

    def _model_bg_pct(self, effort_level: str) -> int:
        return LEVEL_PCT.get(effort_level.lower(), 0)

    def _model_anchor_pair(self, model_name: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
        mc    = self.theme.models[model_key(model_name)]
        shift = mc.warm_shift if self.bg_shift == 'warm' else mc.cool_shift
        return mc.anchor, shift

    def model_bg_lead(self, model_name: str, effort_level: str) -> str:
        pct = self._model_bg_pct(effort_level)
        if not pct:
            return ''
        anchor, _ = self._model_anchor_pair(model_name)
        r, g, b   = _scale(anchor, pct)
        return f'\033[48;2;{r};{g};{b}m'

    def model_bg_trail(self, model_name: str, effort_level: str) -> str:
        pct = self._model_bg_pct(effort_level)
        if not pct:
            return ''
        _, shift = self._model_anchor_pair(model_name)
        r, g, b  = _scale(shift, pct)
        return f'\033[48;2;{r};{g};{b}m'

    R         = RESET
    BORDER    = CLR_GREY_DIM
    PWD       = CLR_SKY_BLUE
    BRANCH    = CLR_GREEN_OK
    COMMIT    = CLR_GREY_DIM
    SESSION   = CLR_GREY_DIM
    MODEL     = CLR_PURPLE
    SKILLS    = CLR_GOLD
    TIME      = CLR_GREY_DIM
    TOK       = CLR_CYAN
    TOK_DIM   = CLR_CYAN_DIM
    TOK_DAY     = CLR_CYAN_DAY
    TOK_DAY_DIM = CLR_CYAN_DAY_DIM
    COST      = CLR_PINK
    BAR_FILL  = CLR_GREEN_OK
    BAR_EMPTY = CLR_GREY_DARK
    DIM_GREEN = CLR_GREEN_DIM
    LABEL     = CLR_GREY_DIM
    CTX       = CLR_PEACH
    CTX_DIM   = CLR_PEACH
    BOLDW     = BOLD + CLR_WHITE_BRT
    BOLDY     = CLR_YELLOW
    DIRTY     = CLR_WARN
    ICON_PATH = CLR_CYAN_ICON
    ARROW     = CLR_GREEN_BRT
    TOK_ICON  = CLR_YELLOW_BRT
    OPUS      = CLR_YELLOW
    SONNET    = CLR_GREEN_OK
    HAIKU     = CLR_SKY_BLUE

    # --- Gradient delegations (backward compat) ---
    # GRAD_STOPS / GREY_RGB / SPARK_STOPS now live on the GradientEngine
    # instance (driven by the active Theme). The legacy class-level constants
    # are gone; callers reach them via r.gradient.GRAD_STOPS etc.
    FADE        = GradientEngine.FADE
    SPARK_CHARS = GradientEngine.SPARK_CHARS

    def gradient_rgb(self, t: float, dim: float = 1.0) -> tuple[int, int, int]:
        return self.gradient.gradient_rgb(t, dim)

    def gradient_color(self, t: float, dim: float = 1.0) -> str:
        return self.gradient.gradient_color(t, dim)

    def grad_at(self, col: int, width: int, dim: float = 1.0, fill: float = 1.0) -> str:
        return self.gradient.grad_at(col, width, dim, fill)

    def gradient_bar(self, filled: int, bar_w: int) -> str:
        return self.gradient.gradient_bar(filled, bar_w)

    def vsep_block(self, col: int, width: int, fill: float = 1.0, *, leader: bool = False) -> str:
        color    = self.gradient.grad_at(col - 1, width, fill=fill)
        trailing = ' ' if leader else '  '
        return f'  {color}│{self.R}{trailing}'

    def sparkline(self, history: list[int], live: bool = False) -> tuple[str, str]:
        return self.gradient.sparkline(history, live)

    def spark_rgb(self, t: float, dim: float = 1.0) -> tuple[int, int, int]:
        return self.gradient.spark_rgb(t, dim)

    def spark_color(self, t: float, dim: float = 1.0) -> str:
        return self.gradient.spark_color(t, dim)

    # --- Border delegations (backward compat) ---
    def border_top(self, width: int, session_id: str = '', downs: tuple[int, ...] = (), fill: float = 1.0, pill: Pill | None = None) -> str:
        return self.border.border_top(width, session_id, downs, fill, pill)

    def border_bottom(self, width: int, ups: tuple[int, ...] = (), fill: float = 1.0) -> str:
        return self.border.border_bottom(width, ups, fill)

    def border_separator(self, width: int, ups: tuple[int, ...] = (), fill: float = 1.0) -> str:
        return self.border.border_separator(width, ups, fill)

    def border_separator_dim(self, width: int, downs: tuple[int, ...] = (), ups: tuple[int, ...] = (), fill: float = 1.0, pill: Pill | None = None, pill_edge: str = 'bottom') -> str:
        return self.border.border_separator_dim(width, downs, ups, fill, pill, pill_edge)

    def border_line(self, content: str, width: int, fill: float = 1.0, bg_lead: str = '', bg_trail: str = '', pill_flush: bool = False, right_pill: str = '') -> str:
        return self.border.border_line(content, width, fill, bg_lead, bg_trail, pill_flush, right_pill)

    def path_git(
        self, short_pwd: str, git: GitInfo, elapsed: str = '',
        *, show_commit: bool = True, show_dirty: bool = True, show_elapsed: bool = True,
    ) -> str:
        dirty = ''
        if show_dirty:
            if git.untracked > 0:
                dirty += f'{self.DIRTY}•{git.untracked}{RESET}'
            if git.modified > 0:
                dirty += f'{self.DIRTY}*{git.modified}{RESET}'
            if git.deleted > 0:
                dirty += f'{self.DIRTY}-{git.deleted}{RESET}'
            if git.renamed > 0:
                dirty += f'{self.DIRTY}{GLYPH_RENAMED} {git.renamed}{RESET}'
            if dirty:
                dirty = ' ' + dirty
        tail = f' {self.SESSION}[{elapsed}]{self.R}' if (show_elapsed and elapsed and elapsed != '0m') else ''
        commit_part = f'{self.LABEL}/{self.R}{self.COMMIT}{git.commit}{self.R}' if show_commit else ''

        return (
            f'{self.ICON_PATH}{GLYPH_FOLDER}  {self.PWD}{short_pwd}{self.R}'
            f' {self.LABEL}{self.ARROW}{BOLD}∈{self.R}'
            f' {self.BRANCH}{git.branch}{self.R}'
            f'{commit_part}{dirty}{tail}'
        )

    def path_git_compact(self, short_pwd: str, git: GitInfo) -> str:
        return (
            f'{self.ICON_PATH}  {self.PWD}{short_pwd}{self.R}'
            f' {self.LABEL}{self.ARROW}{BOLD}∈{self.R}'
            f' {self.BRANCH}{git.branch}{self.R}'
        )

    def fit_path(
        self, short_pwd: str, git: GitInfo, elapsed: str, target_w: int,
        *, compact_only: bool = False,
    ) -> str:
        def fits(s: str) -> bool:
            return _visible_width(s) <= target_w

        if not compact_only:
            for kwargs in (
                {},
                {'show_commit': False},
                {'show_commit': False, 'show_elapsed': False},
                {'show_commit': False, 'show_elapsed': False, 'show_dirty': False},
            ):
                candidate = self.path_git(short_pwd, git, elapsed, **kwargs)
                if fits(candidate):
                    return candidate

        compact = self.path_git_compact(short_pwd, git)
        if fits(compact):
            return compact

        # Ellipsis on short_pwd only
        for pwd_w in range(target_w - 1, 0, -1):
            trunc_pwd = _middle_ellipsis(short_pwd, pwd_w)
            candidate = self.path_git_compact(trunc_pwd, git)
            if fits(candidate):
                return candidate

        # Ellipsis on both short_pwd and branch
        # Overhead of path_git_compact with empty strings is 5 visible chars.
        half = max(1, (target_w - 5) // 2)
        trunc_pwd    = _middle_ellipsis(short_pwd,  half)
        trunc_branch = _middle_ellipsis(git.branch, half)
        truncated_git = GitInfo(
            branch=trunc_branch, commit=git.commit,
            modified=git.modified, untracked=git.untracked,
            deleted=git.deleted, renamed=git.renamed,
        )
        return self.path_git_compact(trunc_pwd, truncated_git)

    def model_colour(self, model_name: str) -> str:
        return self.theme.models[model_key(model_name)].label

    def fill_colour(self, pct: float) -> str:
        if pct >= 90:
            return self.alert
        if pct >= 70:
            return self.warn
        return self.safe

    def risk_zone_color(self, tokens: int) -> str:
        if tokens <= 50_000:
            return self.safe
        if tokens <= 80_000:
            return self.yellow
        if tokens <= 150_000:
            return self.warn
        return self.alert

    def day_cost_colour(self, cost: float) -> str:
        if cost > 50:
            return self.alert
        if cost >= 25:
            return self.yellow
        return self.safe

    def model_section_compact(self, model_name: str, rate_limits: RateLimits, max_width: int, effort_level: str = '') -> tuple[str, int]:
        model_clr = self.model_colour(model_name)
        pct_bg    = self._model_bg_pct(effort_level)
        anchor, shift = self._model_anchor_pair(model_name) if pct_bg else ((0, 0, 0), (0, 0, 0))
        pct       = rate_limits.five_hour.used_percentage or 0
        pct_clr   = self.fill_colour(float(pct))
        step      = rainbow_step()
        c_helper  = rainbow_at(step, 9)
        rate_pct  = f'{pct_clr}{pct}%{self.R}'

        rate_with_time = None
        try:
            if rate_limits.five_hour.resets_at:
                resets_at = datetime.fromtimestamp(rate_limits.five_hour.resets_at).astimezone()
                delta = resets_at - datetime.now().astimezone().replace(microsecond=0)
                if delta.total_seconds() > 0:
                    total_s = int(delta.total_seconds())
                    h, rem  = divmod(total_s, 3600)
                    m       = rem // 60
                    time_str       = f'{h}h{m}m' if h else f'{m}m'
                    rate_with_time = f'{rate_pct} {self.COMMIT}{time_str}{self.R}'
        except Exception:
            pass

        def _build(name: str, rate: str) -> tuple[str, int]:
            if pct_bg:
                cells: list[tuple[str, tuple[int, int, int] | None, bool, bool]] = []
                cells.append((GLYPH_MODEL, anchor, False, False))
                cells.append((' ', anchor, False, False))
                cells.append((' ', anchor, False, False))
                for ch in name:
                    cells.append((ch, anchor, False, False))
                cells.append((' ', anchor, False, False))
                pill_l = pill_gradient_fg(0, 0, len(cells), anchor, shift, pct_bg) + PILL_LEFT
                pill_r = pill_gradient_fg(len(cells), 0, len(cells), anchor, shift, pct_bg) + PILL_RIGHT
                painted = pill_l + paint_bg_span(cells, anchor, shift, pct_bg, self.pill_fg_dark, self.pill_fg_light) + pill_r + RESET
                pw = _visible_width(painted)
                return (
                    f'{painted}'
                    f'{self.LABEL}|{self.R}'
                    f' {c_helper}{BOLD}{GLYPH_HELPER}{self.R} {rate}'
                ), pw
            return (
                f'{model_clr}{GLYPH_MODEL}  {name}{self.R}'
                f' {self.LABEL}|{self.R}'
                f' {c_helper}{BOLD}{GLYPH_HELPER}{self.R} {rate}'
            ), 0

        if rate_with_time:
            line, pw = _build(model_name, rate_with_time)
            if _visible_width(line) <= max_width:
                return line, pw

        line, pw = _build(model_name, rate_pct)
        if _visible_width(line) <= max_width:
            return line, pw

        base_w      = _visible_width(_build('', rate_pct)[0])
        name_budget = max(3, max_width - base_w - 1)
        return _build(model_name[:name_budget] + '…', rate_pct)

    def model_right_section(self, model_name: str, model_thinking: str, rate_limits: RateLimits, effort_level: str = '', fast_mode: bool = False) -> tuple[str, str, int]:
        step      = rainbow_step()
        c_think   = rainbow_at(step, 0)
        c_helper  = rainbow_at(step, 9)
        model_clr = self.model_colour(model_name)
        pct       = self._model_bg_pct(effort_level)
        glyph     = GLYPH_BURN_FAST if fast_mode else GLYPH_THINKING

        if pct:
            anchor, shift = self._model_anchor_pair(model_name)
            cells: list[tuple[str, tuple[int, int, int] | None, bool, bool]] = []
            cells.append((GLYPH_MODEL,    anchor, False, False))
            cells.append((' ',            anchor, False, False))
            cells.append((' ',            anchor, False, False))
            for ch in model_name:
                cells.append((ch, anchor, False, False))
            cells.append((' ',            anchor, False, False))
            cells.append((glyph,          anchor, True,  False))
            cells.append((' ',            anchor, True,  False))
            cells.append((' ',            anchor, True,  False))
            for ch in model_thinking:
                cells.append((ch, anchor, False, True))
            cells.append((' ', anchor, False, False))
            pill_l    = pill_gradient_fg(0, 0, len(cells), anchor, shift, pct) + PILL_LEFT
            pill_r    = pill_gradient_fg(len(cells), 0, len(cells), anchor, shift, pct) + PILL_RIGHT
            right_text = pill_l + paint_bg_span(cells, anchor, shift, pct, self.pill_fg_dark, self.pill_fg_light) + pill_r + RESET
        elif model_thinking:
            right_text = f'{model_clr}{GLYPH_MODEL}  {model_name}{self.R} {c_think}{BOLD}{glyph}  {self.R}{model_clr}{ITALIC}{model_thinking}{RESET}'
        else:
            right_text = f'{model_clr}{GLYPH_MODEL}  {model_name}{self.R}'

        right_w = _visible_width(right_text)

        helper_text = f'{c_helper}{BOLD}{GLYPH_HELPER}{self.R}  {self.white_brt}{BOLD}{self.helper(rate_limits.five_hour)}{self.R}'
        seven_day = rate_limits.seven_day
        if seven_day.used_percentage != 0 or seven_day.resets_at != 0:
            seven_clr = self.fill_colour(float(seven_day.used_percentage or 0))
            seven_trend = self.burndown_trend(
                float(seven_day.used_percentage or 0),
                seven_day.resets_at,
                SEVEN_DAY_MINUTES,
                SEVEN_DAY_WARMUP_MINUTES,
            )
            seven_trend_part = f' {seven_trend}' if seven_trend else ''
            helper_text += f' {self.LABEL}| {seven_clr}{seven_day.used_percentage}%{self.R}{seven_trend_part}'

        return helper_text, right_text, right_w

    def model_right_section_compact(self, model_name: str, rate_limits: RateLimits, max_right_width: int, effort_level: str = '') -> tuple[str, str, int]:
        model_clr = self.model_colour(model_name)
        pct_bg    = self._model_bg_pct(effort_level)
        anchor, shift = self._model_anchor_pair(model_name) if pct_bg else ((0, 0, 0), (0, 0, 0))
        pct       = rate_limits.five_hour.used_percentage or 0
        pct_clr   = self.fill_colour(float(pct))
        rate_text = f'{pct_clr}{pct}%{self.R}'
        try:
            if rate_limits.five_hour.resets_at:
                resets_at = datetime.fromtimestamp(rate_limits.five_hour.resets_at).astimezone()
                delta = resets_at - datetime.now().astimezone().replace(microsecond=0)
                if delta.total_seconds() > 0:
                    trend = self.burndown_trend(
                        float(pct),
                        rate_limits.five_hour.resets_at,
                        FIVE_HOUR_MINUTES,
                        FIVE_HOUR_WARMUP_MINUTES,
                    )
                    trend_part = f' {trend}' if trend else ''
                    total_s = int(delta.total_seconds())
                    h, rem  = divmod(total_s, 3600)
                    m       = rem // 60
                    time_str = f'{h}h{m}m' if h else f'{m}m'
                    rate_text = f'{rate_text}{trend_part} {self.COMMIT}{time_str}{self.R}'
        except Exception:
            pass

        def _make_right(name: str) -> tuple[str, int]:
            if pct_bg:
                cells: list[tuple[str, tuple[int, int, int] | None, bool, bool]] = []
                cells.append((GLYPH_MODEL, anchor, False, False))
                cells.append((' ', anchor, False, False))
                cells.append((' ', anchor, False, False))
                for ch in name:
                    cells.append((ch, anchor, False, False))
                cells.append((' ', anchor, False, False))
                pill_l  = pill_gradient_fg(0, 0, len(cells), anchor, shift, pct_bg) + PILL_LEFT
                pill_r  = pill_gradient_fg(len(cells), 0, len(cells), anchor, shift, pct_bg) + PILL_RIGHT
                painted = pill_l + paint_bg_span(cells, anchor, shift, pct_bg, self.pill_fg_dark, self.pill_fg_light) + pill_r + RESET
                return painted, _visible_width(painted)
            text = f'{model_clr}{GLYPH_MODEL}  {name}{self.R}'
            return text, _visible_width(text)

        right_text, right_w = _make_right(model_name)
        if right_w > max_right_width and max_right_width > 0:
            _, base_w = _make_right('')
            budget    = max(3, max_right_width - base_w - 1)
            right_text, right_w = _make_right(model_name[:budget] + '…')
        return rate_text, right_text, right_w

    def plugins_skills(self, skills_count: int, skills_names: str, plugin_names: str) -> str:
        step = rainbow_step()
        c_skills = rainbow_at(step, 3)
        c_plugins = rainbow_at(step, 6)
        extras = []
        if skills_count > 0:
            extras.append(f'{c_skills}{BOLD}{GLYPH_SKILLS}  {self.R}{self.SKILLS}{skills_names}{self.R}')
        if plugin_names:
            extras.append(f'{c_plugins}{BOLD}{GLYPH_PLUGINS}  {self.R}{self.SKILLS}{plugin_names}{self.R}')
        return f' {self.LABEL}|{self.R} '.join(extras)

    SUBAGENT_TOK_W = 6  # fmt_tok('999.9K') is 6 chars; reserve to avoid jitter

    def subagent_activity(self, last_activity: tuple[str, str, dict[str, object]]) -> str:
        kind, name, inp = last_activity
        if kind == 'tool_use':
            key = TOOL_ARG_KEY.get(name)
            if key and key in inp:
                raw = str(inp[key])
                if key == 'file_path':
                    raw = Path(raw).name
            elif inp:
                raw = str(next(iter(inp.values())))
            else:
                raw = ''
            if _visible_width(raw) > 36:
                raw = raw[:36] + '…'  # U+2026 HORIZONTAL ELLIPSIS
            return f'{GLYPH_TASKS} {name}[{raw}]'
        if kind == 'thinking':
            return f'{GLYPH_THINKING} (thinking)'
        if kind == 'text':
            return f'{GLYPH_REPLYING} (replying)'
        return ''

    def subagent_row(self, sub: RunningSubagent, width: int, session_inout: int = 0) -> str:
        now     = time.time()
        dur     = max(0.0, now - sub.first_timestamp) if sub.first_timestamp > 0 else 0.0
        dur_s   = fmt_dur(dur).rjust(5)
        out_s   = fmt_tok(sub.output)
        tok_s   = fmt_tok(sub.total_input)

        short_model = model_key(sub.model)  # 'opus'/'sonnet'/'haiku'/'other'
        model_clr   = self.model_colour(sub.model)
        ctx_clr     = self.risk_zone_color(sub.total_input)

        step     = rainbow_step()
        c_marker = rainbow_at(step, 12)
        type_text = sub.agent_type or '?'

        target_w = width - 4  # content width (2 for '│ ' left, 2 for ' │' right)

        if width > 100:
            # --- identity line (▶) : agent type · description (full width) ---
            head1_w  = 3 + _visible_width(type_text) + 3  # '▶  ' + type + ' · '
            desc_budget = max(0, target_w - head1_w)
            desc_text   = sub.description or ''
            if _visible_width(desc_text) > desc_budget:
                desc_text = (desc_text[:desc_budget - 1] + '…') if desc_budget > 0 else ''

            left1 = (
                f'{c_marker}{BOLD}{GLYPH_SUBAGENT_ROW}{self.R}  '
                f'{self.SKILLS}{type_text}{self.R}'
                f' {self.LABEL}·{self.R} '
                f'{self.CTX}{desc_text}{self.R}'
            )
            left1_w = head1_w + _visible_width(desc_text)
            pad1    = max(1, target_w - left1_w)
            line1   = f'{left1}{" " * pad1}'  # right side empty; pad keeps equal widths

            # --- continuation line (└) : burn-metric cluster ---
            # Stats live here as ' · '-joined fields; duration and model relocate
            # from the identity line. When width is tight, stats are shed in
            # priority order — share % first, then ↑output, then the t/m rate.
            # The token count, elapsed, and model always remain.
            tpm   = subagent_avg_tpm(sub.total_input, sub.output, sub.first_timestamp, now)
            share = subagent_share(sub.total_input + sub.output, session_inout)

            sep       = f' {self.LABEL}·{self.R} '
            tok_field = fmt_tok(sub.total_input).rjust(5)
            out_plain = f'↑ {out_s}'
            out_pad   = ' ' * max(0, 6 - len(out_plain))

            tpm_str = f'{tpm:,d}'.rjust(5) if tpm is not None else ''
            if share is not None:
                share_clr = self.gradient.gradient_color(share)
                share_str = f'{share * 100:.1f}%'.rjust(6)

            activity = self.subagent_activity(sub.last_activity)
            left2_w  = 6 + _visible_width(activity)
            left2 = (
                f'   {self.CTX_DIM}{GLYPH_CONTINUATION}{self.R}  '
                f'{self.CTX_DIM}{activity}{self.R}'
            )

            def cluster(show_tpm: bool, show_share: bool, show_out: bool) -> str:
                frags: list[str] = []
                if show_tpm:
                    frags.append(f'{self.TOK}{tpm_str}{self.R}{self.LABEL} t/m{self.R}')
                if show_share:
                    frags.append(f'{share_clr}{GLYPH_PIE} {share_str}{self.R}')
                # tok and ↑out are one space-grouped field (no · between them).
                tok_seg = f'{ctx_clr}{tok_field}{self.R}'
                if show_out:
                    tok_seg += f' {out_pad}{self.LABEL}{BOLD}↑ {self.R}{self.CTX}{out_s}{self.R}'
                frags.append(tok_seg)
                frags.append(f'{self.CTX}{dur_s}{self.R}')
                frags.append(f'{model_clr}{short_model.rjust(6)}{self.R}')
                return sep.join(frags)

            show_tpm, show_share, show_out = tpm is not None, share is not None, True

            def fits() -> bool:
                return left2_w + _visible_width(cluster(show_tpm, show_share, show_out)) + 1 <= target_w

            if not fits() and show_share:
                show_share = False
            if not fits() and show_out:
                show_out = False
            if not fits() and show_tpm:
                show_tpm = False

            right2 = cluster(show_tpm, show_share, show_out)
            pad2   = max(1, target_w - left2_w - _visible_width(right2))
            line2  = f'{left2}{" " * pad2}{right2}'

            return f'{line1}\n{line2}'

        else:
            # --- narrow single-line collapse ---
            kind = sub.last_activity[0]
            tool_verb = sub.last_activity[1] if kind == 'tool_use' else (
                '(thinking)' if kind == 'thinking' else
                '(replying)' if kind == 'text' else ''
            )

            right_n = (
                f'{ctx_clr}{GLYPH_HOURGLASS} {tok_s}{self.R}'
                f'  {self.LABEL}{BOLD}↑{self.R}{self.CTX}{out_s}{self.R}'
                f'  {self.CTX}{dur_s}{self.R}'
            )
            right_n_w = _visible_width(right_n)

            left_n = (
                f'{c_marker}{BOLD}{GLYPH_SUBAGENT_ROW}{self.R}  '
                f'{self.SKILLS}{type_text}{self.R}'
                f'  {model_clr}{short_model}{self.R}'
                f'  {self.CTX}{tool_verb}{self.R}'
            )
            left_n_w = _visible_width(left_n)
            pad_n    = max(1, target_w - left_n_w - right_n_w)
            return f'{left_n}{" " * pad_n}{right_n}'

    def task_row(self, tasks: TaskList, width: int, compact: bool = False) -> str:
        step    = rainbow_step()
        c_glyph = rainbow_at(step, 9)
        done    = tasks.completed
        total   = tasks.total
        count_s = f'{done}/{total}'

        head = f'{c_glyph}{BOLD}{GLYPH_TASKS}{self.R}  {self.SKILLS}{count_s}{self.R}'
        if compact:
            return head

        if done == total:
            text = ''
        else:
            active = tasks.active
            if active is not None:
                text = active.active_form or active.subject
            else:
                nxt = tasks.next_pending
                text = nxt.subject if nxt else ''

        if not text:
            return head

        target_w = width - 4
        head_w   = 3 + len(count_s) + 2  # glyph + '  ' + count + '  '
        budget   = max(0, target_w - head_w)
        if len(text) > budget:
            text = (text[:budget - 1] + '…') if budget > 0 else ''
        return f'{head}  {self.CTX}{text}{self.R}'

    RATE_W  = 6
    IN_W    = 6
    CACHE_W = 6
    OUT_W   = 6

    def tokens_cost(self, sess_in: int, sess_cache: int, sess_out: int, day_in: int, day_cache: int, day_out: int, sess_cost: float, day_cost: float, tok_rate: int, session_id: str = '', box_width: int = 80, fill: float = 1.0) -> tuple[list[str], tuple[int, int], int]:
        day_clr = self.day_cost_colour(day_cost)
        in_active, out_active = TokenRate.recently_active(session_id)
        in_icon  = '\U0001f847 ' if in_active  else '↓ '  # 🡇+space or ↓+space (both 2 cols)
        out_icon = '\U0001f845 ' if out_active else '↑ '  # 🡅+space or ↑+space (both 2 cols)

        sess_in_s    = fmt_tok(sess_in).rjust(self.IN_W)
        day_in_s     = fmt_tok(day_in).rjust(self.IN_W)
        sess_cache_s = fmt_tok(sess_cache).rjust(self.CACHE_W)
        day_cache_s  = fmt_tok(day_cache).rjust(self.CACHE_W)
        sess_out_s   = fmt_tok(sess_out).rjust(self.OUT_W)
        day_out_s    = fmt_tok(day_out).rjust(self.OUT_W)

        vsep_w        = 4
        vsep_leader_w = 4

        middle1 = f'{self.LABEL}{self.BOLDY}{in_icon}{self.R}{self.TOK}{sess_in_s}{self.R} {self.TOK_DIM}({sess_cache_s}){self.R}{self.LABEL} {self.BOLDY}{out_icon}{self.R}{self.TOK}{sess_out_s}{self.R}'
        middle2 = f'{self.LABEL}{self.BOLDY}{in_icon}{self.R}{self.TOK_DAY}{day_in_s}{self.R} {self.TOK_DAY_DIM}({day_cache_s}){self.R}{self.LABEL} {self.BOLDY}{out_icon}{self.R}{self.TOK_DAY}{day_out_s}{self.R}'

        cost1 = f'${sess_cost:,.2f}'
        cost2 = f'${day_cost:,.2f}'
        cost_width = max(_visible_width(cost1), _visible_width(cost2))

        end1 = f'{self.safe}{ICON_COST}{self.R} {self.COST}{cost1.rjust(cost_width)}{self.R}'
        end2 = f'  {self.LABEL}{self.R}{day_clr}{cost2.rjust(cost_width)}{self.R}'

        label_w = 15
        w_middle = _visible_width(middle1)
        w_end    = max(_visible_width(end1), _visible_width(end2))
        content_w = box_width - 3
        leader_w = max(label_w + 1, content_w - w_middle - w_end - vsep_w - vsep_leader_w)

        col1 = w_middle + 5                  # 1-indexed position of vsep │
        col2 = w_middle + vsep_w + w_end + 5  # 1-indexed position of vsep_leader │
        vsep        = self.vsep_block(col1, box_width, fill=fill, leader=True)
        vsep_leader = self.vsep_block(col2, box_width, fill=fill, leader=True)
        # bar_w = leader_w - label_w

        rate_label = f'{self.TOK_ICON}{ICON_TOK_RATE} {self.TOK}{fmt_tok(tok_rate)}{self.R}{self.LABEL} t/m{self.R}'
        rate_label_w = _visible_width(rate_label)
        rate_label_padded = f'{rate_label}' #{" " * max(0, label_w - rate_label_w)}'
        bar_w = leader_w - rate_label_w

        if bar_w <= 0:
            leader1 = rate_label_padded
            leader2 = ' ' * label_w
        else:
            if session_id:
                spark_history = TokenRate.history(session_id, bar_w, TokenRate.WINDOW * 2)
                top_row, bot_row = self.sparkline(spark_history[::-1], live=True)
            else:
                top_row, bot_row = ' ' * bar_w, ' ' * bar_w
            leader1 = f'{rate_label_padded}{top_row}'
            # leader2 = f'{" " * label_w}{bot_row}'
            leader2 = f'{" " * rate_label_w}{bot_row}'

        # 1-indexed column of the WINDOW (60s) tick inside the sparkline. History
        # spans WINDOW*2 (=120s) across bar_w buckets reversed so index 0 is "now",
        # which puts the 60s boundary at bar_w // 2. col2 is the vsep_leader │
        # column; sparkline starts rate_label_w cells past that.
        mark_col = col2 + rate_label_w + (bar_w // 2) if bar_w > 0 else 0

        return [
            f'{middle1}{vsep}{end1}{vsep_leader}{leader1}',
            f'{middle2}{vsep}{end2}{vsep_leader}{leader2}',
        ], (col1, col2), mark_col

    def context_bar(self, fill_ratio: float) -> str:
        ratio = min(max(fill_ratio, 0.0), 1.0)
        filled = int(ratio * 30)
        bar_filled = BarChars.FILLED * filled
        bar_empty = BarChars.EMPTY * (30 - filled)
        if ratio >= 0.9:
            color = self.alert
        elif ratio >= 0.7:
            color = self.warn
        else:
            color = self.safe
        return f'{color}{bar_filled}{self.R}{self.BAR_EMPTY}{bar_empty}{self.R}'

    def context_bar_color(self, fill_ratio: float) -> str:
        ratio = min(max(fill_ratio, 0.0), 1.0)
        if ratio >= 0.9:
            return self.alert
        elif ratio >= 0.7:
            return self.warn
        else:
            return self.safe

    _EMPTY_FADE_256 = re.compile(r'\x1b\[38;5;(\d+)m')
    _EMPTY_FADE_RGB = re.compile(r'\x1b\[38;2;(\d+);(\d+);(\d+)m')

    def _empty_fade_colors(self) -> list[str]:
        # 3-step ramp going from a darker shade up to BAR_EMPTY, so the fill→empty
        # seam blends instead of butting a coloured glyph against flat grey.
        m = self._EMPTY_FADE_256.search(self.BAR_EMPTY)
        if m:
            n = int(m.group(1))
            return [f'\033[38;5;{max(232, n - k)}m' for k in (6, 4, 2)]
        m = self._EMPTY_FADE_RGB.search(self.BAR_EMPTY)
        if m:
            r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return [f'\033[38;2;{int(r*k)};{int(g*k)};{int(b*k)}m' for k in (0.3, 0.5, 0.7)]
        return [self.BAR_EMPTY] * 3

    def _empty_section(self, empty: int, blend: bool = True) -> str:
        if empty <= 0:
            return ''
        if not blend:
            return f'{self.BAR_EMPTY}{BarChars.EMPTY * empty}'
        fade  = self._empty_fade_colors()
        n     = min(len(fade), empty)
        parts = [f'{fade[i]}{BarChars.EMPTY}' for i in range(n)]
        if empty > n:
            parts.append(f'{self.BAR_EMPTY}{BarChars.EMPTY * (empty - n)}')
        return ''.join(parts)

    def context_line(self, ctx: ContextWindow, available: int = 76) -> str:
        total_tokens = ctx.total_input_tokens + ctx.total_output_tokens
        # Real context-window fill, 0-100% -- never the old tokens/150K
        # "pressure" number (which could read e.g. 524%). Fall back to the soft
        # limit as the scale only when the model's window size is unknown.
        scale      = ctx.context_window_size if ctx.context_window_size > 0 else SOFT_LIMIT
        fill_ratio = min(total_tokens / scale, 1.0) if scale > 0 else 0.0
        pct        = fill_ratio * 100
        clr        = self.fill_colour(pct)
        prefix = f'{clr}{self.R}{self.DIM_GREEN}{fmt_tok(total_tokens)}{self.R} {clr}{BOLD}{pct:.0f}%{self.R} '
        bar_w  = max(4, available - _visible_width(prefix) - 3)
        filled = int(fill_ratio * bar_w)
        empty  = max(0, bar_w - filled - (1 if filled < bar_w else 0))
        bar    = f'{self.gradient_bar(filled, bar_w)}{self.R}{self._empty_section(empty, blend=filled > 0)}{self.R}'
        return f'{clr}{self.R} {prefix}{bar}'


    def context_line_compact(self, ctx: ContextWindow, available: int) -> str:
        total_tokens = ctx.total_input_tokens + ctx.total_output_tokens
        scale      = ctx.context_window_size if ctx.context_window_size > 0 else SOFT_LIMIT
        fill_ratio = min(total_tokens / scale, 1.0) if scale > 0 else 0.0
        pct        = fill_ratio * 100
        clr        = self.fill_colour(pct)
        prefix  = f'{clr}{BOLD}{pct:.0f}%{self.R} '
        bar_w   = max(4, available - _visible_width(prefix) - 3)
        filled  = int(fill_ratio * bar_w)
        empty   = max(0, bar_w - filled - (1 if filled < bar_w else 0))
        bar     = f'{self.gradient_bar(filled, bar_w)}{self.R}{self._empty_section(empty, blend=filled > 0)}{self.R}'
        return f' {prefix}{bar}'

    SPEC_GRADIENTS: Sequence[tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]] = [
        ((20, 60, 200),  (30, 200, 180),  (220, 255, 120)),     # Ocean    blue → teal → pale green
        ((60, 20, 160),  (240, 60, 140),  (255, 200, 60)),      # Sunset   indigo → magenta → gold
        ((10, 80, 120),  (120, 220, 40),  (240, 240, 60)),      # Forest   navy → lime → yellow
        ((80, 20, 200),  (240, 100, 220), (255, 200, 160)),     # Lavender purple → hot-pink → peach
        ((140, 20, 30),  (240, 120, 20),  (255, 230, 80)),      # Ember    dark-red → orange → yellow
        ((30, 40, 140),  (60, 200, 240),  (220, 240, 255)),     # Arctic   navy → cyan → white
        ((90, 30, 10),   (220, 120, 30),  (255, 220, 100)),     # Copper   brown → orange → gold
        ((160, 10, 50),  (240, 100, 160), (255, 220, 220)),     # Rose     wine → pink → cream
        ((10, 90, 100),  (60, 220, 160),  (220, 255, 180)),     # Mint     dark-teal → mint → pale-yellow
        ((40, 10, 140),  (220, 40, 200),  (60, 220, 240)),      # Nebula   violet → magenta → cyan
        ((140, 30, 200), (40, 180, 240),  (60, 230, 120)),      # Aurora   violet → cyan → green
        ((60, 0, 20),    (220, 60, 20),   (255, 220, 40)),      # Volcano  black-red → orange → yellow
    ]

    SPEC_MID_MIN_WIDTH = 20

    def _spec_rgb_at(self, t: float, idx: int, three_stops: bool = True) -> tuple[int, int, int]:
        stops: tuple[tuple[int, int, int], ...] = self.SPEC_GRADIENTS[idx % len(self.SPEC_GRADIENTS)]
        if not three_stops:
            stops = (stops[0], stops[-1])
        n = len(stops)
        seg = max(0.0, min(1.0, t)) * (n - 1)
        s0 = min(int(seg), n - 2)
        s1 = s0 + 1
        u = seg - s0
        c0, c1 = stops[s0], stops[s1]
        return (
            int(c0[0] + (c1[0] - c0[0]) * u),
            int(c0[1] + (c1[1] - c0[1]) * u),
            int(c0[2] + (c1[2] - c0[2]) * u),
        )

    def spec_gradient_bar(self, filled: int, bar_w: int, idx: int) -> str:
        if filled <= 0 or bar_w <= 0:
            return ''
        denom = max(1, bar_w - 1)
        three_stops = bar_w >= self.SPEC_MID_MIN_WIDTH
        parts = []
        for i in range(filled):
            r, g, b = self._spec_rgb_at(i / denom, idx, three_stops)
            parts.append(f'\033[38;2;{r};{g};{b}m{BarChars.HEAVY}')
        return ''.join(parts)

    def openspec_bar(self, name: str, done: int, total: int, box_width: int = 80, title_w: int = 25, idx: int = 0) -> str:
        pct = done * 100 // total
        if len(name) > title_w:
            title = name[:max(1, title_w - 3)] + '...'
        else:
            title = name.ljust(title_w)
        suffix_visible = 7 + len(str(done)) + len(str(total))
        bar_w = max(4, (box_width - 3) - (title_w + 1) - suffix_visible)
        filled = done * bar_w // total
        empty = bar_w - filled

        bar_filled = self.spec_gradient_bar(filled, bar_w, idx)
        if filled > 0 and empty > 0:
            denom = max(1, bar_w - 1)
            three_stops = bar_w >= self.SPEC_MID_MIN_WIDTH
            cr, cg, cb = self._spec_rgb_at(filled / denom, idx, three_stops)
            r, g, b = int(cr * 0.45), int(cg * 0.45), int(cb * 0.45)
            bar_filled += f'\033[38;2;{r};{g};{b}m{BarChars.HEAVY}'
            empty -= 1
        bar_empty = f'{self.spec_empty_ansi}{BarChars.HEAVY * empty}\033[0m'

        return (
            f'{CLR_WHITE_BRT}{ITALIC}{title}{RESET}{self.R} '
            f'{bar_filled}{self.R}{bar_empty}'
            f' {self.LABEL}{done}/{total}{self.R} {BOLD}{pct:>3d}%{RESET}'
        )

    def burndown_trend(self, used_pct: float, resets_at: int, window_minutes: int, warmup_minutes: int, now: float | None = None) -> str:
        delta = burndown_delta(used_pct, resets_at, window_minutes, warmup_minutes, now=now)
        if delta is None:
            return ''
        abs_delta = abs(delta)
        # Map delta onto the fill gradient: t=0 (green) at max under-burn,
        # t=0.5 (yellow-orange midpoint) at neutral, t=1 (red/purple) at max over-burn.
        t = max(0.0, min(1.0, 0.5 + delta / 50.0))
        colour = self.gradient.gradient_color(t)
        glyph = GLYPH_BURN_FAST if delta > 0 else GLYPH_BURN_SLOW # colour modulation carries over/under-burn direction
        sign  = '-' if delta < 0 else '+'
        return f'{colour}{glyph} {sign}{abs_delta:05.2f}%{self.R}'

    def helper(self, five_hour: RateBucket) -> str:
        pct_clr = self.fill_colour(float(five_hour.used_percentage or 0))
        try:
            if not five_hour.resets_at:
                if not five_hour.used_percentage:
                    return '∞'
                return f'{pct_clr}{five_hour.used_percentage}%{self.R} {self.COMMIT}∞'
            resets_at = datetime.fromtimestamp(five_hour.resets_at).astimezone()
            delta = resets_at - datetime.now().astimezone().replace(microsecond=0)
            if delta.total_seconds() <= 0:
                if not five_hour.used_percentage:
                    return '∞'
                return f'{pct_clr}{five_hour.used_percentage}%{self.R} {self.COMMIT}∞'
            trend = self.burndown_trend(
                float(five_hour.used_percentage or 0),
                five_hour.resets_at,
                FIVE_HOUR_MINUTES,
                FIVE_HOUR_WARMUP_MINUTES,
            )
            trend_part = f' {trend}' if trend else ''
            return f'{pct_clr}{five_hour.used_percentage}%{self.R}{trend_part} {self.COMMIT}T-{delta}'
        except Exception as e:
            return f'{e.__class__.__name__}, {str(e)}'

@dataclass
class RowSpec:
    kind: str  # 'top_border', 'bottom_border', 'separator', 'separator_dim', 'content'
    content: str = ''
    bg_lead: str = ''
    bg_trail: str = ''
    pill_flush: bool = False
    ups: tuple[int, ...] = ()
    downs: tuple[int, ...] = ()
    pill: Pill | None = None
    pill_edge: str = 'bottom'
    right_pill: str = ''


@dataclass
class LayoutSpec:
    width: int
    fill: float
    session_id: str
    rows: list[RowSpec] = field(default_factory=list)


def build_narrow(session: SessionInfo, width: int, r: Renderer) -> LayoutSpec:
    ctx          = session.context_window
    total_tokens = ctx.total_input_tokens + ctx.total_output_tokens
    fill         = min(total_tokens / SOFT_LIMIT, 1.0)

    effort_for_bg = session.effort.level if session.thinking.enabled else ''
    pill_pct      = r._model_bg_pct(effort_for_bg)
    pill_anchor, pill_shift = r._model_anchor_pair(session.model_name) if pill_pct else ((0, 0, 0), (0, 0, 0))

    max_right    = max(8, width // 2)
    rate_text, right_text, right_w = r.model_right_section_compact(
        session.model_name, session.rate_limits, max_right, effort_for_bg,
    )
    line_context = r.context_line_compact(ctx, width - 3)

    pill: Pill | None = None
    if pill_pct:
        pill = Pill(start=width - right_w + 1, end=width, anchor=pill_anchor, shift=pill_shift, pct=pill_pct)

    subagents = RunningSubagents.from_session(session.session_id, session.workspace.project_dir)
    spec = LayoutSpec(width=width, fill=fill, session_id=session.session_id)
    if pill_pct:
        rows: list[RowSpec] = [
            RowSpec('top_border', pill=pill),
            RowSpec('content', content=rate_text, right_pill=right_text),
            RowSpec('separator_dim', pill=pill),
        ]
    else:
        rate_w = _visible_width(rate_text)
        pad    = max(1, (width - 4) - rate_w - right_w)
        full   = f'{rate_text}{" " * pad}{right_text}'
        rows = [
            RowSpec('top_border'),
            RowSpec('content', content=full),
            RowSpec('separator_dim'),
        ]
    if subagents.subagents:
        for sub in subagents.subagents:
            for line in r.subagent_row(sub, width, session_inout=0).split('\n'):
                rows.append(RowSpec('content', content=line))
        rows.append(RowSpec('separator_dim'))
    rows.append(RowSpec('content', content=line_context))
    rows.append(RowSpec('bottom_border'))
    spec.rows = rows
    return spec


def build_medium(session: SessionInfo, width: int, r: Renderer) -> LayoutSpec:
    ctx          = session.context_window
    total_tokens = ctx.total_input_tokens + ctx.total_output_tokens
    fill         = min(total_tokens / SOFT_LIMIT, 1.0)

    effort_for_bg = session.effort.level if session.thinking.enabled else ''
    pill_pct      = r._model_bg_pct(effort_for_bg)
    pill_anchor, pill_shift = r._model_anchor_pair(session.model_name) if pill_pct else ((0,0,0), (0,0,0))

    git          = GitInfo.from_cwd(session.cwd, session.session_id)
    line_context = r.context_line_compact(ctx, width - 3)

    max_right    = max(8, width // 2)
    rate_text, right_text, right_w = r.model_right_section_compact(
        session.model_name, session.rate_limits, max_right, effort_for_bg,
    )

    spec = LayoutSpec(width=width, fill=fill, session_id=session.session_id)

    vsep_w   = 5
    rate_w   = _visible_width(rate_text)
    target_w = (width - 4) - vsep_w - rate_w - right_w
    line_path = r.fit_path(session.short_pwd, git, '', target_w, compact_only=True)
    path_w   = _visible_width(line_path)

    pill: Pill | None = None
    if pill_pct:
        pill = Pill(start=width - right_w + 1, end=width, anchor=pill_anchor, shift=pill_shift, pct=pill_pct)

    path_div_col = 3 + path_w + 2
    vsep = r.vsep_block(path_div_col, width, fill=fill, leader=True)
    content = f'{line_path}{vsep}{rate_text}'
    if pill_pct:
        top_row     = RowSpec('top_border', downs=(path_div_col,), pill=pill)
        content_row = RowSpec('content', content=content, right_pill=right_text)
        sep_row     = RowSpec('separator_dim', ups=(path_div_col,), pill=pill)
    else:
        pad = max(1, (width - 3) - (path_w + vsep_w + rate_w + right_w))
        full = f'{content}{" " * pad}{right_text}'
        top_row     = RowSpec('top_border', downs=(path_div_col,))
        content_row = RowSpec('content', content=full)
        sep_row     = RowSpec('separator_dim', ups=(path_div_col,))
    tasks     = TaskList.from_session(session.transcript_path)
    subagents = RunningSubagents.from_session(session.session_id, session.workspace.project_dir)
    rows: list[RowSpec] = [top_row, content_row, sep_row]
    if tasks.is_visible():
        rows.append(RowSpec('content', content=r.task_row(tasks, width, compact=True)))
        rows.append(RowSpec('separator_dim'))
    if subagents.subagents:
        for sub in subagents.subagents:
            for line in r.subagent_row(sub, width, session_inout=0).split('\n'):
                rows.append(RowSpec('content', content=line))
        rows.append(RowSpec('separator_dim'))
    rows.append(RowSpec('content', content=line_context))
    rows.append(RowSpec('bottom_border'))
    spec.rows = rows
    return spec


def build_wide(session: SessionInfo, width: int, r: Renderer) -> LayoutSpec:
    ctx          = session.context_window
    total_tokens = ctx.total_input_tokens + ctx.total_output_tokens
    fill         = min(total_tokens / SOFT_LIMIT, 1.0)

    effort_for_bg = session.effort.level if session.thinking.enabled else ''
    pill_pct      = r._model_bg_pct(effort_for_bg)
    pill_anchor, pill_shift = r._model_anchor_pair(session.model_name) if pill_pct else ((0,0,0), (0,0,0))

    skills        = LoadedSkills.from_transcript(session.transcript_path)
    skill_display = ','.join(s.split(':', 1)[-1] for s in skills.names)
    usage         = TranscriptUsage.from_transcript(session.transcript_path)
    today         = datetime.now().strftime('%Y-%m-%d')
    token_log     = TokenLog.update(session.session_id, today, usage.billed_in, usage.cache_read, usage.out, _model_log_key(session.model))
    tok_rate      = TokenRate.update(session.session_id, usage.billed_in, usage.out)
    sess_cost     = session_cost_display(session, usage)
    day_cost      = compute_day_cost(session.model, token_log)
    subagents     = RunningSubagents.from_session(session.session_id, session.workspace.project_dir)
    session_inout = (
        (usage.billed_in + usage.cache_read) + usage.out
        + sum(s.total_input + s.output for s in subagents.subagents)
    )
    tasks         = TaskList.from_session(session.transcript_path)
    elapsed       = elapsed_from_transcript(session.transcript_path)

    git          = GitInfo.from_cwd(session.cwd, session.session_id)
    helper_text, right_text, right_w = r.model_right_section(
        session.model_name, session.model_thinking, session.rate_limits,
        session.effort.level if session.thinking.enabled else '',
        fast_mode=session.fast_mode,
    )
    line_tokens, vsep_cols, spark_mark_col = r.tokens_cost(
        usage.billed_in, usage.cache_read, usage.out,
        token_log.day_in, token_log.day_cache_read, token_log.day_out,
        sess_cost, day_cost, tok_rate,
        session.session_id, width, fill,
    )
    plugins_line = r.plugins_skills(len(skills.names), skill_display, session.workspace.plugins)
    changes      = OpenSpec.from_cwd(session.cwd).changes
    title_cap    = max(10, width - 45)
    title_w      = min(40, title_cap, max((len(n) for n, _, _ in changes), default=25))
    openspec_bars = [r.openspec_bar(name, d, t, width, title_w, i) for i, (name, d, t) in enumerate(changes)]

    line_context = r.context_line(ctx, width - 3)

    spec = LayoutSpec(width=width, fill=fill, session_id=session.session_id)
    rows: list[RowSpec] = []

    vsep_w   = 5
    helper_w = _visible_width(helper_text)
    target_w = (width - 4) - vsep_w - helper_w - right_w
    line_path = r.fit_path(session.short_pwd, git, elapsed, target_w, compact_only=False)
    path_w   = _visible_width(line_path)

    pill: Pill | None = None
    if pill_pct:
        pill = Pill(start=width - right_w + 1, end=width, anchor=pill_anchor, shift=pill_shift, pct=pill_pct)

    path_div_col = 3 + path_w + 2
    vsep = r.vsep_block(path_div_col, width, fill=fill, leader=True)
    content = f'{line_path}{vsep}{helper_text}'
    if pill_pct:
        rows += [
            RowSpec('top_border', downs=(path_div_col,), pill=pill),
            RowSpec('content', content=content, right_pill=right_text),
        ]
    else:
        pad = max(1, (width - 3) - (path_w + vsep_w + helper_w + right_w))
        content_full = f'{content}{" " * pad}{right_text}'
        rows += [
            RowSpec('top_border', downs=(path_div_col,)),
            RowSpec('content', content=content_full),
        ]

    rows.append(RowSpec('separator_dim', ups=(path_div_col,), pill=pill))
    rows.append(RowSpec('content', content=line_context))

    tokens_downs = vsep_cols + ((spark_mark_col,) if spark_mark_col else ())
    rows.append(RowSpec('separator_dim', downs=tokens_downs))
    for lt in line_tokens:
        rows.append(RowSpec('content', content=lt))

    # First post-tokens separator threads `ups` back into the tokens vseps and
    # is drawn as the heavy "seam" marking the static→dynamic split. Only the
    # first one — later inter-section separators keep their normal style. When
    # nothing dynamic follows, no seam is drawn (the bottom border closes off).
    pending_ups: tuple[int, ...] = vsep_cols
    seam_pending = True

    def sep_kind(normal: str) -> str:
        nonlocal seam_pending
        if seam_pending:
            seam_pending = False
            return 'separator_seam'
        return normal

    if plugins_line:
        rows.append(RowSpec(sep_kind('separator_dim'), ups=pending_ups))
        rows.append(RowSpec('content', content=plugins_line))
        pending_ups = ()

    if tasks.is_visible():
        rows.append(RowSpec(sep_kind('separator_dim'), ups=pending_ups))
        rows.append(RowSpec('content', content=r.task_row(tasks, width)))
        pending_ups = ()

    if subagents.subagents:
        rows.append(RowSpec(sep_kind('separator_dim'), ups=pending_ups))
        for sub in subagents.subagents:
            for line in r.subagent_row(sub, width, session_inout=session_inout).split('\n'):
                rows.append(RowSpec('content', content=line))
        pending_ups = ()

    if openspec_bars:
        rows.append(RowSpec(sep_kind('separator'), ups=pending_ups))
        for bar in openspec_bars:
            rows.append(RowSpec('content', content=bar))
        rows.append(RowSpec('bottom_border'))
    else:
        rows.append(RowSpec('bottom_border', ups=pending_ups))

    spec.rows = rows
    return spec


def render_layout(spec: LayoutSpec, r: Renderer) -> list[str]:
    lines: list[str] = []
    for row in spec.rows:
        if row.kind == 'top_border':
            lines.append(r.border_top(spec.width, spec.session_id, downs=row.downs, fill=spec.fill, pill=row.pill))
        elif row.kind == 'bottom_border':
            lines.append(r.border_bottom(spec.width, ups=row.ups, fill=spec.fill))
        elif row.kind == 'separator':
            lines.append(r.border_separator(spec.width, ups=row.ups, fill=spec.fill))
        elif row.kind == 'separator_seam':
            # Static→dynamic split: a full-brightness solid rule (vs the dotted-dim
            # separators between dynamic sections). Renders via the solid separator.
            lines.append(r.border_separator(spec.width, ups=row.ups, fill=spec.fill))
        elif row.kind == 'separator_dim':
            lines.append(r.border_separator_dim(spec.width, downs=row.downs, ups=row.ups, fill=spec.fill, pill=row.pill, pill_edge=row.pill_edge))
        elif row.kind == 'content':
            lines.append(r.border_line(row.content, spec.width, fill=spec.fill, bg_lead=row.bg_lead, bg_trail=row.bg_trail, pill_flush=row.pill_flush, right_pill=row.right_pill))
    return lines


def resolve_theme(cli_name: str | None) -> Theme:
    """Layered theme selection: CLI → env → config file → CLAUDE_DARK."""
    if cli_name and cli_name in THEMES:
        return THEMES[cli_name]
    env = os.environ.get('CLAUDE_STATUSLINE_THEME', '').strip()
    if env in THEMES:
        return THEMES[env]
    try:
        cfg = (CLAUDE_DIR / 'statusline-theme').read_text().strip()
        if cfg in THEMES:
            return THEMES[cfg]
    except OSError:
        pass
    return CLAUDE_DARK


def render(session_info: dict[str, object], width: int, *, bg_shift: str = 'warm', theme: Theme | None = None) -> str:
    if width < MIN_WIDTH:
        return ''
    session = SessionInfo.from_dict(session_info)
    r       = Renderer(bg_shift=bg_shift, theme=theme)
    if width < NARROW_WIDTH:
        spec = build_narrow(session, width, r)
    elif width < MEDIUM_WIDTH:
        spec = build_medium(session, width, r)
    else:
        spec = build_wide(session, width, r)
    return '\n'.join(render_layout(spec, r))


def main() -> None:
    # Force UTF-8 on stdout so the script renders correctly on Windows
    # (cp1252 default codec can't encode box-drawing or Nerd Font glyphs,
    # crashes with UnicodeEncodeError on the first border char). Python's
    # PEP 540 UTF-8 mode and PYTHONIOENCODING env var both fix this from
    # the outside; reconfiguring stdout here removes the requirement that
    # callers set either. No-op on platforms whose default codec is
    # already UTF-8 (most Unix systems since Python 3.7).
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    bg_shift   = 'warm'
    theme_name: str | None = None
    args = sys.argv[1:]
    while args:
        a = args.pop(0)
        if a == '--bg-shift' and args:
            v = args.pop(0).lower()
            if v in ('warm', 'cool'):
                bg_shift = v
        elif a.startswith('--bg-shift='):
            v = a.split('=', 1)[1].lower()
            if v in ('warm', 'cool'):
                bg_shift = v
        elif a == '--theme' and args:
            theme_name = args.pop(0)
        elif a.startswith('--theme='):
            theme_name = a.split('=', 1)[1]

    info  = json.loads(sys.stdin.read())
    theme = resolve_theme(theme_name)

    # Write payload so the multi-session observer can index it. Keyed by
    # session_id and overwritten in place, so the dir holds one file per
    # session rather than one per render tick. The observer already collapses
    # to the newest payload per session (mon/discovery.index_payloads_by_session),
    # so the old timestamped filenames only ever accumulated dead weight.
    session_id = _as_str(info.get('session_id')) or 'unknown'
    _atomic_write_text(CLAUDE_DIR / 'statusline-output' / f'statusline.{session_id}.json', json.dumps(info))

    raw_tw = terminal_width()
    if raw_tw < MIN_WIDTH:
        return
    if os.environ.get('YAS_FULL_WIDTH'):
        width = max(MIN_WIDTH, raw_tw-6)
    else:
        width = max(MIN_WIDTH, min(MAX_WIDTH, raw_tw - 6))

    sys.stdout.write(render(info, width, bg_shift=bg_shift, theme=theme))


if __name__ == '__main__':
    main()
