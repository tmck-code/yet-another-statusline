#!/usr/bin/env python3
'Claude Code statusLine command (Python port).'

from __future__ import annotations
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
from typing import NamedTuple


class BarChars:
    FILLED = '█'
    HEAVY  = '▆'
    MID    = ''
    EMPTY  = '░'


HOME       = Path(os.path.expanduser('~'))
MIN_WIDTH    = 40
MAX_WIDTH    = 160
NARROW_WIDTH = 55
MEDIUM_WIDTH = 80
SOFT_LIMIT = 150_000
_ANSI_RE   = re.compile(r'\x1b\[[0-9;]*m')


def terminal_width() -> int:
    try:
        w = int(subprocess.run(["tmux", "display-message", "-p", "'#{pane_width}'"], capture_output=True, text=True).stdout.strip().replace("'", ""))
        if w > 0:
            return w
    except (OSError, ValueError):
        pass
    try:
        w = int((HOME / '.claude' / 'terminal-width').read_text().strip())
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
GLYPH_FOLDER   = '\uef85'     # nf-custom folder    (path row)

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


class TokenAccounting:
    @staticmethod
    def rates_for(model_name: str) -> tuple[float, float]:
        m = model_name.lower()
        if 'opus' in m:
            return 15.00, 75.00
        if 'haiku' in m:
            return 0.80, 4.00
        return 3.00, 15.00

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
        rate_in, rate_out = TokenAccounting.rates_for(
            model.display_name or model.id
        )
        cost = (
            token_log.day_in * rate_in
            + token_log.day_cache_read * rate_in * 0.1
            + token_log.day_out * rate_out
        )
        return cost / 1_000_000


class Model(NamedTuple):
    id: str = ''
    display_name: str = ''

    @classmethod
    def from_dict(cls, d: dict) -> Model:
        return cls(id=d.get('id', ''), display_name=d.get('display_name', ''))

    @property
    def cost_rates(self) -> tuple[float, float]:
        return TokenAccounting.rates_for(self.display_name or self.id)


class OutputStyle(NamedTuple):
    name: str = 'default'

    @classmethod
    def from_dict(cls, d: dict) -> OutputStyle:
        return cls(name=d.get('name', 'default'))


class Effort(NamedTuple):
    level: str = ''

    @classmethod
    def from_dict(cls, d: dict) -> Effort:
        return cls(level=d.get('level', ''))


class Thinking(NamedTuple):
    enabled: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> Thinking:
        return cls(enabled=bool(d.get('enabled', False)))


class CurrentUsage(NamedTuple):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> CurrentUsage:
        return cls(
            input_tokens                = d.get('input_tokens', 0),
            output_tokens               = d.get('output_tokens', 0),
            cache_creation_input_tokens = d.get('cache_creation_input_tokens', 0),
            cache_read_input_tokens     = d.get('cache_read_input_tokens', 0),
        )


class RateBucket(NamedTuple):
    used_percentage: float = 0.0
    resets_at: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> RateBucket:
        return cls(
            used_percentage = round(float(d.get('used_percentage', 0.0)), 2),
            resets_at       = d.get('resets_at', 0),
        )


@dataclass
class Workspace:
    current_dir: str = ''
    project_dir: str = ''
    added_dirs: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> Workspace:
        return cls(
            current_dir = d.get('current_dir', ''),
            project_dir = d.get('project_dir', ''),
            added_dirs  = d.get('added_dirs') or [],
        )

    @property
    def plugins(self) -> str:
        seen: dict[str, None] = {}
        candidates = [HOME / '.claude' / 'settings.json']
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
    def from_dict(cls, d: dict) -> Cost:
        return cls(
            total_cost_usd        = d.get('total_cost_usd', 0.0),
            total_duration_ms     = d.get('total_duration_ms', 0),
            total_api_duration_ms = d.get('total_api_duration_ms', 0),
            total_lines_added     = d.get('total_lines_added', 0),
            total_lines_removed   = d.get('total_lines_removed', 0),
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
    def from_dict(cls, d: dict) -> ContextWindow:
        return cls(
            total_input_tokens   = d.get('total_input_tokens', 0),
            total_output_tokens  = d.get('total_output_tokens', 0),
            context_window_size  = d.get('context_window_size', 0),
            current_usage        = CurrentUsage.from_dict(d.get('current_usage') or {}),
            used_percentage      = d.get('used_percentage'),
            remaining_percentage = d.get('remaining_percentage'),
        )


@dataclass
class RateLimits:
    five_hour: RateBucket = field(default_factory=RateBucket)
    seven_day: RateBucket = field(default_factory=RateBucket)

    @classmethod
    def from_dict(cls, d: dict) -> RateLimits:
        return cls(
            five_hour = RateBucket.from_dict(d.get('five_hour')  or {}),
            seven_day = RateBucket.from_dict(d.get('seven_day') or {}),
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
    rate_limits: RateLimits = field(default_factory=RateLimits)

    @classmethod
    def from_dict(cls, d: dict) -> SessionInfo:
        return cls(
            session_id          = d.get('session_id', ''),
            transcript_path     = d.get('transcript_path', ''),
            cwd                 = d.get('cwd', ''),
            model               = Model.from_dict(d.get('model') or {}),
            workspace           = Workspace.from_dict(d.get('workspace') or {}),
            version             = d.get('version', ''),
            output_style        = OutputStyle.from_dict(d.get('output_style') or {}),
            cost                = Cost.from_dict(d.get('cost') or {}),
            context_window      = ContextWindow.from_dict(d.get('context_window') or {}),
            exceeds_200k_tokens = d.get('exceeds_200k_tokens', False),
            effort              = Effort.from_dict(d.get('effort') or {}),
            thinking            = Thinking.from_dict(d.get('thinking') or {}),
            rate_limits         = RateLimits.from_dict(d.get('rate_limits') or {}),
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
            return self.effort.level
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


@dataclass
class TokenLog:
    day_in: int = 0
    day_cache_read: int = 0
    day_out: int = 0

    @classmethod
    def update(cls, session_id: str, today: str, total_in: int, cache_read: int, total_out: int) -> TokenLog:
        log = HOME / '.claude' / 'statusline-tokens.log'
        lines = []
        if log.exists():
            for ln in log.read_text().splitlines():
                parts = ln.split()
                if len(parts) >= 2 and parts[1] == session_id:
                    continue
                lines.append(ln)
        if session_id and (total_in > 0 or cache_read > 0 or total_out > 0):
            lines.append(f'{today} {session_id} {total_in} {cache_read} {total_out}')
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text('\n'.join(lines) + '\n')
        day_in = day_cache_read = day_out = 0
        for ln in lines:
            parts = ln.split()
            if len(parts) < 4 or parts[0] != today:
                continue
            try:
                if len(parts) == 6:
                    day_in += int(parts[2])
                    day_out += int(parts[3])
                elif len(parts) >= 5:
                    day_in += int(parts[2])
                    day_cache_read += int(parts[3])
                    day_out += int(parts[4])
                else:
                    day_in += int(parts[2])
                    day_out += int(parts[3])
            except ValueError:
                pass
        return cls(day_in=day_in, day_cache_read=day_cache_read, day_out=day_out)



class TokenRate:
    WINDOW = float(os.environ.get('STATUSLINE_TOKEN_WINDOW', '60'))
    KEEP = 300.0

    @classmethod
    def update(cls, session_id: str, total_in: int, total_out: int) -> int:
        if not session_id:
            return 0
        log = HOME / '.claude' / 'statusline-token-rate.log'
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
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text('\n'.join(f'{ts:.3f} {sid} {ti} {to}' for ts, sid, ti, to in rows) + '\n')
        except OSError:
            pass
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
        log = HOME / '.claude' / 'statusline-token-rate.log'
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
                if sid == session_id and now - ts <= window:
                    samples.append((ts, ti, to))
        if len(samples) < 2:
            return [0] * n_buckets
        samples.sort()
        bucket_size = window / n_buckets
        start = now - window
        buckets = [0] * n_buckets
        for i in range(len(samples) - 1):
            ts0, ti0, to0 = samples[i]
            ts1, ti1, to1 = samples[i + 1]
            delta = max(0, (ti1 + to1) - (ti0 + to0))
            if delta == 0:
                continue
            midpoint = (ts0 + ts1) / 2
            idx = int((midpoint - start) / bucket_size)
            idx = max(0, min(n_buckets - 1, idx))
            buckets[idx] += delta
        return buckets


@dataclass
class GitInfo:
    branch: str = ''
    commit: str = ''
    modified: int = 0
    untracked: int = 0

    @classmethod
    def from_cwd(cls, cwd: str) -> GitInfo:
        repo, gitdir   = cls._find_repo(cwd)
        branch, commit = cls._read_head(gitdir)
        modified = untracked = 0
        if branch:
            modified, untracked = cls._dirty(repo)
        return cls(
            branch    = branch,
            commit    = commit,
            modified  = modified,
            untracked = untracked,
        )

    @staticmethod
    def _find_repo(cwd: str) -> tuple[str, str]:
        curr = Path(cwd) if cwd else None
        while curr:
            if (curr / '.git').exists():
                return str(curr), str(curr / '.git')
            if curr == curr.parent:
                break
            curr = curr.parent
        return '', ''

    @staticmethod
    def _read_head(gitdir: str) -> tuple[str, str]:
        if not gitdir:
            return '', ''
        head_path = Path(gitdir) / 'HEAD'
        if not head_path.is_file():
            return '', ''
        try:
            head = head_path.read_text().strip()
        except OSError:
            return '', ''
        branch = ''
        if head.startswith('ref:'):
            branch = head.rsplit('/', 1)[-1]
        elif head:
            branch = f'd:{head[:7]}'
        commit = ''
        if branch and not branch.startswith('d:'):
            ref = Path(gitdir) / 'refs' / 'heads' / branch
            if ref.is_file():
                try:
                    commit = ref.read_text().strip()[:9]
                except OSError:
                    pass
        if not commit:
            orig = Path(gitdir) / 'ORIG_HEAD'
            if orig.is_file():
                try:
                    commit = orig.read_text().strip()[:9]
                except OSError:
                    pass
        return branch, commit

    @staticmethod
    def _dirty(repo: str) -> tuple[int, int]:
        modified = untracked = 0
        if not repo:
            return modified, untracked
        try:
            r = subprocess.run(
                ['git', '-C', repo, 'ls-files', '-m'],
                capture_output=True, text=True, timeout=2,
            )
            modified = sum(1 for ln in r.stdout.splitlines() if ln.strip())
        except Exception:
            pass
        try:
            r = subprocess.run(
                ['git', '-C', repo, 'ls-files', '--others', '--exclude-standard',
                 '--directory', '--no-empty-directory'],
                capture_output=True, text=True, timeout=2,
            )
            untracked = sum(1 for ln in r.stdout.splitlines() if ln.strip())
        except Exception:
            pass
        return modified, untracked


@dataclass
class LoadedSkills:
    names: list[str] = field(default_factory=list)

    @classmethod
    def from_transcript(cls, transcript_path: str) -> LoadedSkills:
        if not transcript_path:
            return cls()
        p = Path(transcript_path)
        if not p.is_file():
            return cls()
        skill_pat = re.compile(r'"name"\s*:\s*"Skill"[^}]*?"skill"\s*:\s*"([^"]+)"')
        read_pat = re.compile(r'"name"\s*:\s*"Read"[^}]*?"file_path"\s*:\s*"([^"]+)"')
        skill_path_pat = re.compile(r'/skills/([^/"]+)/SKILL\.md$')
        seen: dict[str, None] = {}
        try:
            with p.open('r', errors='ignore') as fh:
                for ln in fh:
                    if '"Skill"' in ln:
                        for m in skill_pat.finditer(ln):
                            name = m.group(1)
                            if name not in seen:
                                seen[name] = None
                    if '"Read"' in ln and 'SKILL.md' in ln:
                        for m in read_pat.finditer(ln):
                            sm = skill_path_pat.search(m.group(1))
                            if sm:
                                name = sm.group(1)
                                if name not in seen:
                                    seen[name] = None
        except OSError:
            return cls()
        return cls(names=list(seen.keys()))


@dataclass
class RunningSubagents:
    subagents: list[tuple[str, str]] = field(default_factory=list)  # (agentType, description)

    STALE_SECONDS = 30

    @classmethod
    def from_session(cls, session_id: str, project_dir: str) -> RunningSubagents:
        if not session_id or not project_dir:
            return cls()
        project_slug = project_dir.replace('/', '-')
        if project_slug.startswith('-'):
            project_slug = project_slug[1:]
        subagents_dir = HOME / '.claude' / 'projects' / f'-{project_slug}' / session_id / 'subagents'
        if not subagents_dir.is_dir():
            return cls()
        now = time.time()
        subagents: list[tuple[str, str]] = []
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
                subagents.append((agent_type, description))
        except OSError:
            pass
        return cls(subagents=subagents)


@dataclass
class TranscriptUsage:
    input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    output_tokens: int = 0

    @classmethod
    def from_transcript(cls, transcript_path: str) -> TranscriptUsage:
        if not transcript_path:
            return cls()
        p = Path(transcript_path)
        if not p.is_file():
            return cls()
        seen: set[str] = set()
        ti = cc = cr = to = 0
        try:
            with p.open('r', errors='ignore') as fh:
                for ln in fh:
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
                    u = msg.get('usage') or {}
                    ti += u.get('input_tokens', 0) or 0
                    cc += u.get('cache_creation_input_tokens', 0) or 0
                    cr += u.get('cache_read_input_tokens', 0) or 0
                    to += u.get('output_tokens', 0) or 0
        except OSError:
            return cls()
        return cls(
            input_tokens                = ti,
            cache_creation_input_tokens = cc,
            cache_read_input_tokens     = cr,
            output_tokens               = to,
        )

    @property
    def billed_in(self) -> int:
        return self.input_tokens + self.cache_creation_input_tokens

    @property
    def cache_read(self) -> int:
        return self.cache_read_input_tokens

    @property
    def out(self) -> int:
        return self.output_tokens


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
    if n >= 1_000_000:
        return f'{n/1_000_000:.1f}M'
    if n >= 1000:
        return f'{n/1000:.1f}K'
    return str(n)


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


ANCHOR_RGB = {
    'opus':   (255, 255,   0),
    'sonnet': (135, 215, 135),
    'haiku':  ( 95, 175, 255),
    'other':  (215, 175, 255),
}

SHIFT_WARM = {
    'opus':   (255, 165,   0),
    'sonnet': ( 44, 208, 168),
    'haiku':  (123, 230, 255),
    'other':  (240, 165, 224),
}

SHIFT_COOL = {
    'opus':   (180, 230,  60),
    'sonnet': ( 44, 140,  80),
    'haiku':  ( 74, 110, 224),
    'other':  (138, 111, 214),
}

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
    return tuple(min(255, max(0, c * pct // 100)) for c in rgb)


def paint_bg_span(cells: list[tuple[str, tuple[int, int, int] | None, bool, bool]],
                  anchor: tuple[int, int, int],
                  shift: tuple[int, int, int],
                  pct: int) -> str:
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
        fg_rgb = (15, 15, 15) if lum >= BG_LUM_THRESHOLD else (fg if fg is not None else None)
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


def _short_agent_name(agent_type: str, description: str) -> str:
    if agent_type.lower() in ('general-purpose', 'explore', 'plan'):
        parts = description.split(' - ', 1)
        return parts[0] if len(parts) > 1 else description[:20]
    return agent_type.replace('-executor', '')


class GradientEngine:
    GRAD_STOPS = (
        (0.00, ( 40, 210,  80)),
        (0.25, ( 80, 230,  40)),
        (0.45, (180, 240,  20)),
        (0.55, (240, 230,  20)),
        (0.68, (255, 170,  15)),
        (0.78, (250, 100,  20)),
        (0.88, (235,  55,  35)),
        (1.00, (210,  20,  50)),
    )
    GREY_RGB = (108, 108, 108)
    FADE     = 0.06
    SPARK_CHARS = '▁▂▃▄▅▆▇█'

    SPARK_STOPS = (
        # (0.00, (110,  35,  30)),
        # (0.50, (200,  55,  40)),
        # (1.00, (255, 110,  60)),
        (0.00, (179, 46, 32)),
        (0.50, (200,  55,  40)),
        (1.00, (204,  65,  51)),
    )

    def spark_rgb(self, t: float) -> tuple[int, int, int]:
        t = max(0.0, min(1.0, t))
        for i in range(len(self.SPARK_STOPS) - 1):
            t0, c0 = self.SPARK_STOPS[i]
            t1, c1 = self.SPARK_STOPS[i + 1]
            if t <= t1:
                u = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
                r = int(c0[0] + (c1[0] - c0[0]) * u)
                g = int(c0[1] + (c1[1] - c0[1]) * u)
                b = int(c0[2] + (c1[2] - c0[2]) * u)
                return r, g, b
        return self.SPARK_STOPS[-1][1]

    def spark_color(self, t: float) -> str:
        r, g, b = self.spark_rgb(t)
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
            return CLR_BORDER_OFF
        fade = self.FADE
        if t <= fill - fade:
            return self.gradient_color(t, dim)
        if t >= fill + fade:
            return CLR_BORDER_OFF
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
            parts.append(f'{self.gradient_color(i / denom)}{BarChars.FILLED}')
        if filled <= bar_w:
            parts.append(f'{self.gradient_color(filled / denom)}{BarChars.MID}')
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

    def sparkline(self, history: list[int]) -> tuple[str, str]:
        if not history:
            return '', ''
        max_val = max(history)
        indices = [
            min(int(((v / max_val) if max_val > 0 else 0.0) * 16), 16)
            for v in history
        ]
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
            ratio = tint_idx / 16.0
            bot_clr = self.spark_color(ratio * 0.5)
            top_clr = self.spark_color(0.5 + ratio * 0.5)
            top_parts.append(f'{top_clr}{top_ch}{RESET}')
            bot_parts.append(f'{bot_clr}{bot_ch}{RESET}')
        return ''.join(top_parts), ''.join(bot_parts)


class BorderRenderer:
    def __init__(self, gradient: GradientEngine):
        self.gradient = gradient

    R       = RESET
    SESSION = CLR_GREY_DIM

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
            parts += [_clr(2, 1), _ch(2), _clr(3, 2), _ch(3), self.SESSION, sid]
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

    def border_separator_dim(self, width: int, downs: tuple[int, ...] = (), ups: tuple[int, ...] = (), fill: float = 1.0, pill: Pill | None = None, pill_edge: str = 'bottom') -> str:
        downs_set = set(downs)
        ups_set = set(ups)
        p = pill or Pill()
        edge = pill_edge if pill_edge == 'top' else 'bottom'
        if p.active and p.start <= 1:
            parts = [p.border_fg(p.start), p.border_char(p.start, edge)]
        else:
            parts = [self.gradient.grad_at(0, width, 0.6, fill=fill), '├']
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
                parts += [self.gradient.grad_at(i + 1, width, 0.6, fill=fill), ch]
        if p.active and p.start <= width <= p.end:
            parts += [p.border_fg(width), p.border_char(width, edge), self.R]
        else:
            parts += [self.gradient.grad_at(width - 1, width, 0.6, fill=fill), '┤', self.R]
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
    def __init__(self, bg_shift: str = 'warm'):
        self.bg_shift = bg_shift if bg_shift in ('warm', 'cool') else 'warm'
        self.gradient = GradientEngine()
        self.border = BorderRenderer(self.gradient)

    def _bg_shift_table(self) -> dict:
        return SHIFT_WARM if self.bg_shift == 'warm' else SHIFT_COOL

    def _model_bg_pct(self, effort_level: str) -> int:
        return LEVEL_PCT.get(effort_level.lower(), 0)

    def _model_anchor_pair(self, model_name: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
        key    = model_key(model_name)
        anchor = ANCHOR_RGB[key]
        shift  = self._bg_shift_table()[key]
        return anchor, shift

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
    GRAD_STOPS  = GradientEngine.GRAD_STOPS
    GREY_RGB    = GradientEngine.GREY_RGB
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

    def sparkline(self, history: list[int]) -> tuple[str, str]:
        return self.gradient.sparkline(history)

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
            if git.modified > 0:
                dirty += f'{CLR_WARN}●{git.modified}{RESET}'
            if git.untracked > 0:
                dirty += f'{CLR_WARN}*{git.untracked}{RESET}'
            if dirty:
                dirty = ' ' + dirty
        tail = f' {self.SESSION}[{elapsed}]{self.R}' if (show_elapsed and elapsed and elapsed != '0m') else ''
        commit_part = f'{self.LABEL}/{self.R}{self.COMMIT}{git.commit}{self.R}' if show_commit else ''

        return (
            f'{CLR_CYAN_ICON}{GLYPH_FOLDER}  {self.PWD}{short_pwd}{self.R}'
            f' {self.LABEL}{CLR_GREEN_BRT}{BOLD}∈{self.R}'
            f' {self.BRANCH}{git.branch}{self.R}'
            f'{commit_part}{dirty}{tail}'
        )

    def path_git_compact(self, short_pwd: str, git: GitInfo) -> str:
        return (
            f'{CLR_CYAN_ICON}  {self.PWD}{short_pwd}{self.R}'
            f' {self.LABEL}{CLR_GREEN_BRT}{BOLD}∈{self.R}'
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
        )
        return self.path_git_compact(trunc_pwd, truncated_git)

    def model_colour(self, model_name: str) -> str:
        m = model_name.lower()
        if 'opus' in m:
            return CLR_YELLOW
        if 'sonnet' in m:
            return CLR_GREEN_OK
        if 'haiku' in m:
            return CLR_SKY_BLUE
        return CLR_PURPLE

    def fill_colour(self, pct: float) -> str:
        if pct >= 90:
            return CLR_ALERT
        if pct >= 70:
            return CLR_WARN
        return CLR_GREEN_OK

    def day_cost_colour(self, cost: float) -> str:
        if cost > 50:
            return CLR_ALERT
        if cost >= 25:
            return CLR_YELLOW
        return CLR_GREEN_OK

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
                cells = []
                cells.append((GLYPH_MODEL, anchor, False, False))
                cells.append((' ', anchor, False, False))
                cells.append((' ', anchor, False, False))
                for ch in name:
                    cells.append((ch, anchor, False, False))
                cells.append((' ', anchor, False, False))
                pill_l = pill_gradient_fg(0, 0, len(cells), anchor, shift, pct_bg) + PILL_LEFT
                pill_r = pill_gradient_fg(len(cells), 0, len(cells), anchor, shift, pct_bg) + PILL_RIGHT
                painted = pill_l + paint_bg_span(cells, anchor, shift, pct_bg) + pill_r + RESET
                pw = _visible_width(painted)
                return (
                    f'{painted}'
                    f'{self.LABEL}|{self.R}'
                    f' {c_helper}{BOLD}{self.R} {rate}'
                ), pw
            return (
                f'{model_clr}{GLYPH_MODEL}  {name}{self.R}'
                f' {self.LABEL}|{self.R}'
                f' {c_helper}{BOLD}{self.R} {rate}'
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

    def model_right_section(self, model_name: str, model_thinking: str, rate_limits: RateLimits, effort_level: str = '') -> tuple[str, str, int]:
        step      = rainbow_step()
        c_think   = rainbow_at(step, 0)
        c_helper  = rainbow_at(step, 9)
        model_clr = self.model_colour(model_name)
        pct       = self._model_bg_pct(effort_level)

        if pct:
            anchor, shift = self._model_anchor_pair(model_name)
            cells: list[tuple[str, tuple[int, int, int] | None, bool, bool]] = []
            cells.append((GLYPH_MODEL,    anchor, False, False))
            cells.append((' ',            anchor, False, False))
            cells.append((' ',            anchor, False, False))
            for ch in model_name:
                cells.append((ch, anchor, False, False))
            cells.append((' ',            anchor, False, False))
            cells.append((GLYPH_THINKING, anchor, True,  False))
            cells.append((' ',            anchor, True,  False))
            cells.append((' ',            anchor, True,  False))
            for ch in model_thinking:
                cells.append((ch, anchor, False, True))
            cells.append((' ', anchor, False, False))
            pill_l    = pill_gradient_fg(0, 0, len(cells), anchor, shift, pct) + PILL_LEFT
            pill_r    = pill_gradient_fg(len(cells), 0, len(cells), anchor, shift, pct) + PILL_RIGHT
            right_text = pill_l + paint_bg_span(cells, anchor, shift, pct) + pill_r + RESET
        elif model_thinking:
            right_text = f'{model_clr}{GLYPH_MODEL}  {model_name}{self.R} {c_think}{BOLD}{GLYPH_THINKING}  {self.R}{model_clr}{ITALIC}{model_thinking}{RESET}'
        else:
            right_text = f'{model_clr}{GLYPH_MODEL}  {model_name}{self.R}'

        right_w = _visible_width(right_text)

        helper_text = f'{c_helper}{BOLD}{self.R} {CLR_WHITE_BRT}{BOLD} {self.helper(rate_limits.five_hour)}{self.R}'
        seven_day = rate_limits.seven_day
        if seven_day.used_percentage != 0 or seven_day.resets_at != 0:
            seven_clr = self.fill_colour(float(seven_day.used_percentage or 0))
            helper_text += f' {self.LABEL}| {seven_clr}{seven_day.used_percentage}%{self.R}'

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
                    total_s = int(delta.total_seconds())
                    h, rem  = divmod(total_s, 3600)
                    m       = rem // 60
                    time_str = f'{h}h{m}m' if h else f'{m}m'
                    rate_text = f'{rate_text} {self.COMMIT}{time_str}{self.R}'
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
                painted = pill_l + paint_bg_span(cells, anchor, shift, pct_bg) + pill_r + RESET
                return painted, _visible_width(painted)
            text = f'{model_clr}{GLYPH_MODEL}  {name}{self.R}'
            return text, _visible_width(text)

        right_text, right_w = _make_right(model_name)
        if right_w > max_right_width and max_right_width > 0:
            _, base_w = _make_right('')
            budget    = max(3, max_right_width - base_w - 1)
            right_text, right_w = _make_right(model_name[:budget] + '…')
        return rate_text, right_text, right_w

    def plugins_skills(self, skills_count: int, skills_names: str, plugin_names: str, subagents: list[tuple[str, str]] | None = None) -> str:
        step = rainbow_step()
        c_skills = rainbow_at(step, 3)
        c_plugins = rainbow_at(step, 6)
        c_subagent = rainbow_at(step, 12)
        extras = []
        if skills_count > 0:
            extras.append(f'{c_skills}{BOLD}󰟟  {self.R}{self.SKILLS}{skills_names}{self.R}')
        if plugin_names:
            extras.append(f'{c_plugins}{BOLD}  {self.R}{self.SKILLS}{plugin_names}{self.R}')
        if subagents:
            names = ','.join((_short_agent_name(t, d)) for t, d in subagents)
            extras.append(f'{c_subagent}{BOLD}  {self.R}{CLR_PEACH}{names}{self.R}')
        return f' {self.LABEL}|{self.R} '.join(extras)

    RATE_W  = 6
    IN_W    = 6
    CACHE_W = 6
    OUT_W   = 6

    def tokens_cost(self, sess_in: int, sess_cache: int, sess_out: int, day_in: int, day_cache: int, day_out: int, sess_cost: float, day_cost: float, tok_rate: int, session_id: str = '', box_width: int = 80) -> str:
        day_clr = self.day_cost_colour(day_cost)

        sess_in_s    = fmt_tok(sess_in).rjust(self.IN_W)
        day_in_s     = fmt_tok(day_in).rjust(self.IN_W)
        sess_cache_s = fmt_tok(sess_cache).rjust(self.CACHE_W)
        day_cache_s  = fmt_tok(day_cache).rjust(self.CACHE_W)
        sess_out_s   = fmt_tok(sess_out).rjust(self.OUT_W)
        day_out_s    = fmt_tok(day_out).rjust(self.OUT_W)

        vsep    = f'  {self.BORDER}│{self.R}  '
        vsep_w  = 5
        vsep_leader   = f'  {self.BORDER}│{self.R} '
        vsep_leader_w = 4

        middle1 = f'{self.LABEL}{self.BOLDY}↓ {self.R}{self.TOK}{sess_in_s}{self.R} {self.TOK_DIM}({sess_cache_s}){self.R}{self.LABEL} {self.BOLDY}↑ {self.R}{self.TOK}{sess_out_s}{self.R}'
        middle2 = f'{self.LABEL}{self.BOLDY}↓ {self.R}{self.TOK_DAY}{day_in_s}{self.R} {self.TOK_DAY_DIM}({day_cache_s}){self.R}{self.LABEL} {self.BOLDY}↑ {self.R}{self.TOK_DAY}{day_out_s}{self.R}'

        cost1 = f'${sess_cost:,.2f}'
        cost2 = f'${day_cost:,.2f}'
        cost_width = max(_visible_width(cost1), _visible_width(cost2))

        end1 = f'{CLR_GREEN_OK}{ICON_COST} {self.R} {self.COST}{cost1.rjust(cost_width)}{self.R}'
        end2 = f'   {self.LABEL}{self.R}{day_clr}{cost2.rjust(cost_width)}{self.R}'

        label_w = 15
        w_middle = _visible_width(middle1)
        w_end    = max(_visible_width(end1), _visible_width(end2))
        content_w = box_width - 3
        leader_w = max(label_w + 1, content_w - w_middle - w_end - vsep_w - vsep_leader_w)
        # bar_w = leader_w - label_w

        rate_label = f'{CLR_YELLOW_BRT}{ICON_TOK_RATE} {self.TOK}{fmt_tok(tok_rate)}{self.R}{self.LABEL} t/m{self.R}'
        rate_label_w = _visible_width(rate_label)
        rate_label_padded = f'{rate_label}' #{" " * max(0, label_w - rate_label_w)}'
        bar_w = leader_w - rate_label_w

        if bar_w <= 0:
            leader1 = rate_label_padded
            leader2 = ' ' * label_w
        else:
            if session_id:
                spark_history = TokenRate.history(session_id, bar_w, TokenRate.WINDOW * 2)
                top_row, bot_row = self.sparkline(spark_history[::-1])
            else:
                top_row, bot_row = ' ' * bar_w, ' ' * bar_w
            leader1 = f'{rate_label_padded}{top_row}'
            # leader2 = f'{" " * label_w}{bot_row}'
            leader2 = f'{" " * rate_label_w}{bot_row}'

        col1 = w_middle + vsep_w
        col2 = w_middle + w_end + vsep_w + 5

        return [
            f'{middle1}{vsep}{end1}{vsep_leader}{leader1}',
            f'{middle2}{vsep}{end2}{vsep_leader}{leader2}',
        ], (col1, col2)

    def context_bar(self, fill_ratio: float) -> str:
        ratio = min(max(fill_ratio, 0.0), 1.0)
        filled = int(ratio * 30)
        bar_filled = BarChars.FILLED * filled
        bar_empty = BarChars.EMPTY * (30 - filled)
        if ratio >= 0.9:
            color = CLR_ALERT
        elif ratio >= 0.7:
            color = CLR_WARN
        else:
            color = CLR_GREEN_OK
        return f'{color}{bar_filled}{self.R}{self.BAR_EMPTY}{bar_empty}{self.R}'

    def context_bar_color(self, fill_ratio: float) -> str:
        ratio = min(max(fill_ratio, 0.0), 1.0)
        if ratio >= 0.9:
            return CLR_ALERT
        elif ratio >= 0.7:
            return CLR_WARN
        else:
            return CLR_GREEN_OK

    def context_line(self, ctx: ContextWindow, available: int = 76) -> str:
        total_tokens = ctx.total_input_tokens + ctx.total_output_tokens
        fill_ratio   = min(total_tokens / SOFT_LIMIT, 1.0)
        pct_soft     = total_tokens / SOFT_LIMIT * 100

        if total_tokens >= SOFT_LIMIT:
            a = BOLD + CLR_ALERT
            secondary = ''
            if ctx.context_window_size > 0:
                pct_model = total_tokens / ctx.context_window_size * 100
                secondary = f' {a}({pct_model:.0f}%){self.R}'
            prefix = f'{secondary} {a}{fmt_tok(total_tokens)}{self.R} {a}{BOLD}{pct_soft:.0f}%{self.R} '
            bar_w  = max(4, available - _visible_width(prefix) - 3)
            filled = int(min(fill_ratio, 1.0) * bar_w)
            empty  = max(0, bar_w - filled - (1 if filled < bar_w else 0))
            bar    = f'{self.gradient_bar(filled, bar_w)}{self.R}{a}{BarChars.EMPTY * empty}{self.R}'
            return f'{a}{self.R} {prefix}{bar}'

        bar_clr = self.fill_colour(pct_soft)
        secondary = ''
        if ctx.context_window_size > 0:
            pct_model = total_tokens / ctx.context_window_size * 100
            secondary = f' {self.DIM_GREEN}({pct_model:.0f}%){self.R}'
        prefix = f'{bar_clr}{self.R}{self.DIM_GREEN}{fmt_tok(total_tokens)}{self.R}{secondary} {bar_clr}{BOLD}{pct_soft:.0f}% '
        bar_w  = max(4, available - _visible_width(prefix) - 3)
        filled = int(fill_ratio * bar_w)
        empty  = max(0, bar_w - filled - (1 if filled < bar_w else 0))
        bar    = f'{self.gradient_bar(filled, bar_w)}{self.R}{self.BAR_EMPTY}{BarChars.EMPTY * empty}{self.R}'
        return f'{bar_clr}{self.R} {prefix}{bar}'


    def context_line_compact(self, ctx: ContextWindow, available: int) -> str:
        total_tokens = ctx.total_input_tokens + ctx.total_output_tokens
        fill_ratio   = min(total_tokens / SOFT_LIMIT, 1.0)
        pct_soft     = total_tokens / SOFT_LIMIT * 100

        if total_tokens >= SOFT_LIMIT:
            a      = BOLD + CLR_ALERT
            prefix = f'{a}{pct_soft:.0f}%{self.R} '
            bar_w  = max(4, available - _visible_width(prefix) - 3)
            filled = int(min(fill_ratio, 1.0) * bar_w)
            empty  = max(0, bar_w - filled - (1 if filled < bar_w else 0))
            bar    = f'{self.gradient_bar(filled, bar_w)}{self.R}{a}{BarChars.EMPTY * empty}{self.R}'
            return f' {prefix}{bar}'

        bar_clr = self.fill_colour(pct_soft)
        prefix  = f'{bar_clr}{BOLD}{pct_soft:.0f}%{self.R} '
        bar_w   = max(4, available - _visible_width(prefix) - 3)
        filled  = int(fill_ratio * bar_w)
        empty   = max(0, bar_w - filled - (1 if filled < bar_w else 0))
        bar     = f'{self.gradient_bar(filled, bar_w)}{self.R}{self.BAR_EMPTY}{BarChars.EMPTY * empty}{self.R}'
        return f' {prefix}{bar}'

    SPEC_GRADIENTS = [
        ((20, 60, 200), (20, 180, 240), (100, 240, 255)),       # Ocean
        ((200, 80, 10), (245, 30, 100), (255, 160, 80)),        # Sunset
        ((10, 120, 40), (80, 210, 20), (200, 255, 60)),         # Forest
        ((80, 20, 200), (160, 60, 255), (220, 160, 255)),       # Lavender
        ((160, 20, 10), (240, 120, 10), (255, 220, 30)),        # Ember
        ((20, 80, 160), (60, 180, 240), (210, 240, 255)),       # Arctic
        ((120, 50, 10), (200, 120, 20), (255, 200, 80)),        # Copper
        ((160, 10, 50), (240, 60, 130), (255, 180, 210)),       # Rose
        ((10, 110, 90), (20, 210, 150), (120, 255, 200)),       # Mint
        ((50, 10, 160), (180, 20, 220), (255, 100, 240)),       # Nebula
        ((140, 10, 180), (40, 100, 255), (20, 220, 200)),       # Aurora
        ((200, 160, 10), (240, 80, 20), (180, 20, 80)),         # Volcano
    ]

    def spec_gradient_bar(self, filled: int, bar_w: int, idx: int) -> str:
        if filled <= 0:
            return ''
        stops = self.SPEC_GRADIENTS[idx % len(self.SPEC_GRADIENTS)]
        n = len(stops)
        denom = max(1, filled - 1)
        parts = []
        for i in range(filled):
            t = i / denom if denom > 0 else 0.0
            seg = t * (n - 1)
            s0 = min(int(seg), n - 2)
            s1 = s0 + 1
            u = seg - s0
            c0, c1 = stops[s0], stops[s1]
            r = int(c0[0] + (c1[0] - c0[0]) * u)
            g = int(c0[1] + (c1[1] - c0[1]) * u)
            b = int(c0[2] + (c1[2] - c0[2]) * u)
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
            c_last = self.SPEC_GRADIENTS[idx % len(self.SPEC_GRADIENTS)][-1]
            r, g, b = int(c_last[0] * 0.45), int(c_last[1] * 0.45), int(c_last[2] * 0.45)
            bar_filled += f'\033[38;2;{r};{g};{b}m{BarChars.HEAVY}'
            empty -= 1
        bar_empty = f'\033[38;5;233m{BarChars.HEAVY * empty}\033[0m'

        return (
            f'{self.LABEL}{ITALIC}{title}{RESET}{self.R} '
            f'{bar_filled}{self.R}{bar_empty}'
            f' {self.LABEL}{done}/{total}{self.R} {BOLD}{pct:>3d}%{RESET}'
        )

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
            return f'{pct_clr}{five_hour.used_percentage}%{self.R} {self.COMMIT}T-{delta}'
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

    spec = LayoutSpec(width=width, fill=fill, session_id=session.session_id)
    if pill_pct:
        spec.rows = [
            RowSpec('top_border', pill=pill),
            RowSpec('content', content=rate_text, right_pill=right_text),
            RowSpec('separator_dim', pill=pill),
            RowSpec('content', content=line_context),
            RowSpec('bottom_border'),
        ]
    else:
        rate_w = _visible_width(rate_text)
        pad    = max(1, (width - 3) - rate_w - right_w)
        full   = f'{rate_text}{" " * pad}{right_text}'
        spec.rows = [
            RowSpec('top_border'),
            RowSpec('content', content=full),
            RowSpec('separator_dim'),
            RowSpec('content', content=line_context),
            RowSpec('bottom_border'),
        ]
    return spec


def build_medium(session: SessionInfo, width: int, r: Renderer) -> LayoutSpec:
    ctx          = session.context_window
    total_tokens = ctx.total_input_tokens + ctx.total_output_tokens
    fill         = min(total_tokens / SOFT_LIMIT, 1.0)

    effort_for_bg = session.effort.level if session.thinking.enabled else ''
    pill_pct      = r._model_bg_pct(effort_for_bg)
    pill_anchor, pill_shift = r._model_anchor_pair(session.model_name) if pill_pct else ((0,0,0), (0,0,0))

    git          = GitInfo.from_cwd(session.cwd)
    line_context = r.context_line_compact(ctx, width - 3)

    max_right    = max(8, width // 2)
    rate_text, right_text, right_w = r.model_right_section_compact(
        session.model_name, session.rate_limits, max_right, effort_for_bg,
    )

    spec = LayoutSpec(width=width, fill=fill, session_id=session.session_id)

    vsep     = f'  {r.BORDER}│{r.R}  '
    vsep_w   = 5
    rate_w   = _visible_width(rate_text)
    target_w = (width - 4) - vsep_w - rate_w - right_w
    line_path = r.fit_path(session.short_pwd, git, '', target_w, compact_only=True)
    path_w   = _visible_width(line_path)

    pill: Pill | None = None
    if pill_pct:
        pill = Pill(start=width - right_w + 1, end=width, anchor=pill_anchor, shift=pill_shift, pct=pill_pct)

    path_div_col = 3 + path_w + 2
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
    spec.rows = [
        top_row,
        content_row,
        sep_row,
        RowSpec('content', content=line_context),
        RowSpec('bottom_border'),
    ]
    return spec


def build_wide(session: SessionInfo, width: int, r: Renderer) -> LayoutSpec:
    ctx          = session.context_window
    total_tokens = ctx.total_input_tokens + ctx.total_output_tokens
    fill         = min(total_tokens / SOFT_LIMIT, 1.0)

    effort_for_bg = session.effort.level if session.thinking.enabled else ''
    bg_lead       = r.model_bg_lead(session.model_name, effort_for_bg)
    bg_trail      = r.model_bg_trail(session.model_name, effort_for_bg)
    pill_pct      = r._model_bg_pct(effort_for_bg)
    pill_anchor, pill_shift = r._model_anchor_pair(session.model_name) if pill_pct else ((0,0,0), (0,0,0))

    skills        = LoadedSkills.from_transcript(session.transcript_path)
    skill_display = ','.join(s.split(':', 1)[-1] for s in skills.names)
    usage         = TranscriptUsage.from_transcript(session.transcript_path)
    today         = datetime.now().strftime('%Y-%m-%d')
    token_log     = TokenLog.update(session.session_id, today, usage.billed_in, usage.cache_read, usage.out)
    tok_rate      = TokenRate.update(session.session_id, usage.billed_in, usage.out)
    sess_cost     = compute_session_cost(session.model, usage)
    day_cost      = compute_day_cost(session.model, token_log)
    subagents     = RunningSubagents.from_session(session.session_id, session.workspace.project_dir)
    elapsed       = elapsed_from_transcript(session.transcript_path)

    git          = GitInfo.from_cwd(session.cwd)
    helper_text, right_text, right_w = r.model_right_section(
        session.model_name, session.model_thinking, session.rate_limits,
        session.effort.level if session.thinking.enabled else '',
    )
    line_tokens, vsep_cols = r.tokens_cost(
        usage.billed_in, usage.cache_read, usage.out,
        token_log.day_in, token_log.day_cache_read, token_log.day_out,
        sess_cost, day_cost, tok_rate,
        session.session_id, width,
    )
    plugins_line = r.plugins_skills(len(skills.names), skill_display, session.workspace.plugins, subagents.subagents or None)
    changes      = OpenSpec.from_cwd(session.cwd).changes
    title_cap    = max(10, width - 45)
    title_w      = min(40, title_cap, max((len(n) for n, _, _ in changes), default=25))
    openspec_bars = [r.openspec_bar(name, d, t, width, title_w, i) for i, (name, d, t) in enumerate(changes)]

    line_context = r.context_line(ctx, width - 3)

    spec = LayoutSpec(width=width, fill=fill, session_id=session.session_id)
    rows: list[RowSpec] = []

    vsep     = f'  {r.BORDER}│{r.R}  '
    vsep_w   = 5
    helper_w = _visible_width(helper_text)
    target_w = (width - 4) - vsep_w - helper_w - right_w
    line_path = r.fit_path(session.short_pwd, git, elapsed, target_w, compact_only=False)
    path_w   = _visible_width(line_path)

    pill: Pill | None = None
    if pill_pct:
        pill = Pill(start=width - right_w + 1, end=width, anchor=pill_anchor, shift=pill_shift, pct=pill_pct)

    path_div_col = 3 + path_w + 2
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
    next_ups: tuple[int, ...] = (path_div_col,)

    if plugins_line:
        rows.append(RowSpec('separator_dim', ups=next_ups, pill=pill))
        rows.append(RowSpec('content', content=plugins_line))
        next_ups = ()
        rows.append(RowSpec('separator_dim', ups=next_ups))
    else:
        rows.append(RowSpec('separator_dim', ups=next_ups, pill=pill))

    rows.append(RowSpec('content', content=line_context))
    rows.append(RowSpec('separator_dim', downs=vsep_cols))
    for lt in line_tokens:
        rows.append(RowSpec('content', content=lt))

    if openspec_bars:
        rows.append(RowSpec('separator', ups=vsep_cols))
        for bar in openspec_bars:
            rows.append(RowSpec('content', content=bar))
        rows.append(RowSpec('bottom_border'))
    else:
        rows.append(RowSpec('bottom_border', ups=vsep_cols))

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
        elif row.kind == 'separator_dim':
            lines.append(r.border_separator_dim(spec.width, downs=row.downs, ups=row.ups, fill=spec.fill, pill=row.pill, pill_edge=row.pill_edge))
        elif row.kind == 'content':
            lines.append(r.border_line(row.content, spec.width, fill=spec.fill, bg_lead=row.bg_lead, bg_trail=row.bg_trail, pill_flush=row.pill_flush, right_pill=row.right_pill))
    return lines


def main() -> None:
    bg_shift = 'warm'
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

    info    = json.loads(sys.stdin.read())
    session = SessionInfo.from_dict(info)
    r       = Renderer(bg_shift=bg_shift)

    raw_tw = terminal_width()
    if raw_tw < MIN_WIDTH:
        return

    width = max(MIN_WIDTH, min(MAX_WIDTH, raw_tw - 6))

    if width < NARROW_WIDTH:
        spec = build_narrow(session, width, r)
    elif width < MEDIUM_WIDTH:
        spec = build_medium(session, width, r)
    else:
        spec = build_wide(session, width, r)

    sys.stdout.write('\n'.join(render_layout(spec, r)))


if __name__ == '__main__':
    main()
