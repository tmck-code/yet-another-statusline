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


HOME       = Path(os.path.expanduser('~'))
MIN_WIDTH  = 80
MAX_WIDTH  = 160
SOFT_LIMIT = 150_000
_ANSI_RE   = re.compile(r'\x1b\[[0-9;]*m')


def terminal_width() -> int:
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
CLR_SKY_BLUE   = '\033[38;5;75m'
CLR_GREEN_OK   = '\033[38;5;114m'
CLR_GREEN_DIM  = '\033[38;5;77m'
CLR_GREEN_BRT  = '\033[38;5;46m'
CLR_PURPLE     = '\033[38;5;183m'
CLR_GOLD       = '\033[38;5;222m'
CLR_YELLOW     = '\033[38;5;226m'
CLR_YELLOW_BRT = '\033[38;5;11m'
CLR_CYAN       = '\033[38;5;116m'
CLR_CYAN_DIM   = '\033[38;5;103m'
CLR_CYAN_ICON  = '\033[38;5;117m'
CLR_PINK       = '\033[38;5;210m'
CLR_PEACH      = '\033[38;5;216m'
CLR_WHITE_BRT  = '\033[38;5;15m'
CLR_WARN       = '\033[38;5;214m'
CLR_ALERT      = '\033[38;5;167m'


def _is_wide(ch: str) -> bool:
    cp = ord(ch)
    return 0x1F300 <= cp <= 0x1FAFF  # emoji only; nerd font PUA/SPUA are 1-wide in most terminals


def _visible_width(s: str) -> int:
    plain = _ANSI_RE.sub('', s)
    return sum(2 if _is_wide(ch) else 1 for ch in plain)


class Model(NamedTuple):
    id: str = ''
    display_name: str = ''

    @classmethod
    def from_dict(cls, d: dict) -> Model:
        return cls(id=d.get('id', ''), display_name=d.get('display_name', ''))

    @property
    def cost_rates(self) -> tuple[float, float]:
        m = (self.display_name or self.id).lower()
        if 'opus' in m:
            return 15.00, 75.00
        if 'haiku' in m:
            return 0.80, 4.00
        return 3.00, 15.00


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
    def elapsed(self) -> str:
        if not self.transcript_path:
            return ''
        p = Path(self.transcript_path)
        if not p.is_file():
            return ''
        try:
            secs = int(time.time() - p.stat().st_mtime)
        except OSError:
            return ''
        h, rem = divmod(secs, 3600)
        m = rem // 60
        return f'{h}h{m}m' if h > 0 else f'{m}m'

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
    def transcript_usage(self) -> TranscriptUsage:
        if not hasattr(self, '_transcript_usage_cache'):
            self._transcript_usage_cache = TranscriptUsage.from_transcript(self.transcript_path)
        return self._transcript_usage_cache

    @property
    def total_in(self) -> int:
        return self.transcript_usage.billed_in

    @property
    def cache_read(self) -> int:
        return self.transcript_usage.cache_read

    @property
    def total_out(self) -> int:
        return self.transcript_usage.out

    @property
    def model_name(self) -> str:
        return self.model.display_name or self.model.id or 'unknown'

    @property
    def model_thinking(self) -> str:
        if self.thinking.enabled and self.effort.level:
            return self.effort.level
        return ''

    @property
    def plugin_names(self) -> str:
        return self.workspace.plugins

    @property
    def token_log(self) -> TokenLog:
        today = datetime.now().strftime('%Y-%m-%d')
        return TokenLog.update(self.session_id, today, self.total_in, self.cache_read, self.total_out)

    @property
    def token_rate(self) -> int:
        return TokenRate.update(self.session_id, self.total_in + self.cache_read, self.total_out)

    @property
    def session_cost(self) -> float:
        rate_in, rate_out = self.model.cost_rates
        u = self.transcript_usage
        cost = (
            u.input_tokens * rate_in
            + u.cache_creation_input_tokens * rate_in * 1.25
            + u.cache_read_input_tokens * rate_in * 0.1
            + u.output_tokens * rate_out
        )
        return cost / 1_000_000

    @property
    def day_cost(self) -> float:
        rate_in, rate_out = self.model.cost_rates
        log = self.token_log
        cost = (
            log.day_in * rate_in
            + log.day_cache_read * rate_in * 0.1
            + log.day_out * rate_out
        )
        return cost / 1_000_000

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
    WINDOW = 60.0
    KEEP = 180.0

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


class Renderer:
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

    def border_top(self, width: int, session_id: str = '') -> str:
        if session_id:
            avail = max(0, width - 4)
            sid = session_id if len(session_id) <= avail else session_id[:max(0, avail - 1)] + '…'
            rest = max(0, width - 4 - _visible_width(sid))
            return f'{self.BORDER}╭──{self.SESSION}{sid}{self.BORDER}{"─" * rest}╮{self.R}'
        return f'{self.BORDER}╭{"─" * (width - 2)}╮{self.R}'

    def border_bottom(self, width: int) -> str:
        return f'{self.BORDER}╰{"─" * (width - 2)}╯{self.R}'

    def border_separator(self, width: int) -> str:
        return f'{self.BORDER}├{"─" * (width - 2)}┤{self.R}'

    def border_line(self, content: str, width: int) -> str:
        pad = max(0, width - 3 - _visible_width(content))
        return f'{self.BORDER}│{self.R} {content}{" " * pad}{self.BORDER}│{self.R}'

    def path_git(self, short_pwd: str, git: GitInfo, elapsed: str = '') -> str:
        dirty = ''
        if git.modified > 0:
            dirty += f' {CLR_WARN}✹ {git.modified}{RESET}'
        if git.untracked > 0:
            dirty += f' {CLR_WARN}✭ {git.untracked}{RESET}'
        tail = f' {self.SESSION}[{elapsed}]{self.R}' if (elapsed and elapsed != '0m') else ''

        return (
            f'{CLR_CYAN_ICON}  {self.PWD}{short_pwd}{self.R}'
            f' {self.LABEL}{CLR_GREEN_BRT}{BOLD}∈{self.R}'
            f' {self.BRANCH}{git.branch}{self.R}'
            f'{self.LABEL}/{self.R}'
            f'{self.COMMIT}{git.commit}{self.R}'
            f'{dirty}{tail}'
        )

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

    def model_section(self, model_name: str, model_thinking: str, rate_limits: RateLimits) -> str:
        step = rainbow_step()
        c_think = rainbow_at(step, 0)
        c_helper = rainbow_at(step, 9)
        model_clr = self.model_colour(model_name)
        line = f'{model_clr}󰢹  {model_name}{self.R} {c_think}{BOLD}󱩓  {self.R}{model_clr}{ITALIC}{model_thinking}{RESET}'
        line += f' |{self.R} {c_helper}{BOLD}{self.R} {CLR_WHITE_BRT}{BOLD} {self.helper(rate_limits.five_hour)}{self.R}'
        seven_day = rate_limits.seven_day
        if seven_day.used_percentage != 0 or seven_day.resets_at != 0:
            seven_clr = self.fill_colour(float(seven_day.used_percentage or 0))
            line += f' {self.LABEL}| 7d: {seven_clr}{seven_day.used_percentage}%{self.R}'
        return line

    def plugins_skills(self, skills_count: int, skills_names: str, plugin_names: str) -> str:
        step = rainbow_step()
        c_skills = rainbow_at(step, 3)
        c_plugins = rainbow_at(step, 6)
        extras = []
        if skills_count > 0:
            extras.append(f'{c_skills}{BOLD}󰟟  {self.R}{self.SKILLS}{skills_names}{self.R}')
        if plugin_names:
            extras.append(f'{c_plugins}{BOLD}  {self.R}{self.SKILLS}{plugin_names}{self.R}')
        return f' {self.LABEL}|{self.R} '.join(extras)

    def tokens_cost(self, sess_in: int, sess_cache: int, sess_out: int, day_in: int, day_cache: int, day_out: int, sess_cost: float, day_cost: float, tok_rate: int) -> str:
        day_clr = self.day_cost_colour(day_cost)
        return (
            f'{self.R}{CLR_YELLOW_BRT}󱢧  {self.LABEL}{self.BOLDY}↓ {self.R}{self.TOK}{fmt_tok(sess_in)}{self.R} {self.TOK_DIM}({fmt_tok(sess_cache)}){self.R}{self.LABEL} {self.BOLDY}↑ {self.R}{self.TOK}{fmt_tok(sess_out)}{self.R}'
            f' / {self.LABEL}{self.BOLDY}↓ {self.R}{self.TOK}{fmt_tok(day_in)}{self.R} {self.TOK_DIM}({fmt_tok(day_cache)}){self.R}{self.LABEL} {self.BOLDY}↑ {self.R}{self.TOK}{fmt_tok(day_out)}{self.R}'
            f' {self.LABEL}|{self.R} {self.TOK}{fmt_tok(tok_rate)}{self.R}{self.LABEL} t/m{self.R}'
            f' | 💰 {self.COST}${sess_cost:,.2f}{self.R}'
            f'{self.LABEL}/{self.R}{day_clr}${day_cost:,.2f}{self.R}'
        )

    def context_bar(self, fill_ratio: float) -> str:
        ratio = min(max(fill_ratio, 0.0), 1.0)
        filled = int(ratio * 30)
        bar_filled = '█' * filled
        bar_empty = '░' * (30 - filled)
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
            prefix = f'{secondary} {a}{fmt_tok(total_tokens)}{self.R} {a}{BOLD}{pct_soft:.0f}%{self.R}{a}⚡ /clear?{self.R} '
            bar_w  = max(4, available - _visible_width(prefix) - 3)
            filled = int(min(fill_ratio, 1.0) * bar_w)
            bar    = f'{a}{"█" * filled}{"░" * (bar_w - filled)}{self.R}'
            return f'{a}{self.R} {prefix}{bar}'

        bar_clr = self.fill_colour(pct_soft)
        secondary = ''
        if ctx.context_window_size > 0:
            pct_model = total_tokens / ctx.context_window_size * 100
            secondary = f' {self.DIM_GREEN}({pct_model:.0f}%){self.R}'
        prefix = f'{bar_clr}{self.R}{self.DIM_GREEN}{fmt_tok(total_tokens)}{self.R}{secondary} {bar_clr}{BOLD}{pct_soft:.0f}% '
        bar_w  = max(4, available - _visible_width(prefix) - 3)
        filled = int(fill_ratio * bar_w)
        bar    = f'{bar_clr}{"█" * filled}{self.R}{self.BAR_EMPTY}{"░" * (bar_w - filled)}{self.R}'
        return f'{bar_clr}{self.R} {prefix}{bar}'

    def openspec_bar(self, name: str, done: int, total: int, box_width: int = 80, title_w: int = 25) -> str:
        pct = done * 100 // total
        if len(name) > title_w:
            title = name[:max(1, title_w - 3)] + '...'
        else:
            title = name.ljust(title_w)
        suffix_visible = 7 + len(str(done)) + len(str(total))
        bar_w = max(4, (box_width - 3) - (title_w + 1) - suffix_visible)
        filled = done * bar_w // total
        bar_filled, bar_empty = '█' * filled, '░' * (bar_w - filled)

        return (
            f'{self.LABEL}{ITALIC}{title}{RESET}{self.R} '
            f'{self.BAR_FILL}{bar_filled}{self.R}{self.BAR_EMPTY}{bar_empty}{self.R}'
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

def main() -> None:
    info = json.loads(sys.stdin.read())
    session = SessionInfo.from_dict(info)
    r = Renderer()

    skills = LoadedSkills.from_transcript(session.transcript_path)
    skill_display = ','.join(s.split(':', 1)[-1] for s in skills.names)
    token_log = session.token_log

    git = GitInfo.from_cwd(session.cwd)
    line_path = r.path_git(session.short_pwd, git, session.elapsed)
    line_model = r.model_section(session.model_name, session.model_thinking, session.rate_limits)
    line_tokens = r.tokens_cost(session.total_in, session.cache_read, session.total_out, token_log.day_in, token_log.day_cache_read, token_log.day_out, session.session_cost, session.day_cost, session.token_rate)
    plugins_line = r.plugins_skills(len(skills.names), skill_display, session.workspace.plugins)

    width = max(MIN_WIDTH, min(MAX_WIDTH, terminal_width() - 6))
    changes = OpenSpec.from_cwd(session.cwd).changes
    title_cap = max(10, width - 45)
    title_w = min(40, title_cap, max((len(n) for n, _, _ in changes), default=25))
    openspec_bars = [r.openspec_bar(name, d, t, width, title_w) for name, d, t in changes]

    line_context = r.context_line(session.context_window, width - 3)

    lines = [
        r.border_top(width, session.session_id),
        r.border_line(line_path, width),
        r.border_line(line_context, width),
        r.border_line(line_model, width),
    ]
    if plugins_line:
        lines.append(r.border_line(plugins_line, width))
        lines.append(r.border_separator(width))
    lines.append(r.border_line(line_tokens, width))
    if openspec_bars:
        lines.append(r.border_separator(width))
        for bar in openspec_bars:
            lines.append(r.border_line(bar, width))
    lines.append(r.border_bottom(width))

    sys.stdout.write('\n'.join(lines))


if __name__ == '__main__':
    main()
