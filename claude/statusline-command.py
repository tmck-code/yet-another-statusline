#!/usr/bin/env python3
'''Claude Code statusLine command (Python port).'''

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import NamedTuple


HOME = Path(os.path.expanduser('~'))


class Model(NamedTuple):
    id: str = ''
    display_name: str = ''

    @classmethod
    def from_dict(cls, d: dict) -> 'Model':
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
    def from_dict(cls, d: dict) -> 'OutputStyle':
        return cls(name=d.get('name', 'default'))


class CurrentUsage(NamedTuple):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> 'CurrentUsage':
        return cls(
            input_tokens=d.get('input_tokens', 0),
            output_tokens=d.get('output_tokens', 0),
            cache_creation_input_tokens=d.get('cache_creation_input_tokens', 0),
            cache_read_input_tokens=d.get('cache_read_input_tokens', 0),
        )


class RateBucket(NamedTuple):
    used_percentage: float = 0.0
    resets_at: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> 'RateBucket':
        return cls(
            used_percentage=round(float(d.get('used_percentage', 0.0)), 2),
            resets_at=d.get('resets_at', 0),
        )


@dataclass
class Workspace:
    current_dir: str = ''
    project_dir: str = ''
    added_dirs: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> 'Workspace':
        return cls(
            current_dir=d.get('current_dir', ''),
            project_dir=d.get('project_dir', ''),
            added_dirs=d.get('added_dirs') or [],
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
    def from_dict(cls, d: dict) -> 'Cost':
        return cls(
            total_cost_usd=d.get('total_cost_usd', 0.0),
            total_duration_ms=d.get('total_duration_ms', 0),
            total_api_duration_ms=d.get('total_api_duration_ms', 0),
            total_lines_added=d.get('total_lines_added', 0),
            total_lines_removed=d.get('total_lines_removed', 0),
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
    def from_dict(cls, d: dict) -> 'ContextWindow':
        return cls(
            total_input_tokens=d.get('total_input_tokens', 0),
            total_output_tokens=d.get('total_output_tokens', 0),
            context_window_size=d.get('context_window_size', 0),
            current_usage=CurrentUsage.from_dict(d.get('current_usage') or {}),
            used_percentage=d.get('used_percentage'),
            remaining_percentage=d.get('remaining_percentage'),
        )


@dataclass
class RateLimits:
    five_hour: RateBucket = field(default_factory=RateBucket)
    seven_day: RateBucket = field(default_factory=RateBucket)

    @classmethod
    def from_dict(cls, d: dict) -> 'RateLimits':
        return cls(
            five_hour=RateBucket.from_dict(d.get('five_hour') or {}),
            seven_day=RateBucket.from_dict(d.get('seven_day') or {}),
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
    rate_limits: RateLimits = field(default_factory=RateLimits)

    @classmethod
    def from_dict(cls, d: dict) -> 'SessionInfo':
        return cls(
            session_id=d.get('session_id', ''),
            transcript_path=d.get('transcript_path', ''),
            cwd=d.get('cwd', ''),
            model=Model.from_dict(d.get('model') or {}),
            workspace=Workspace.from_dict(d.get('workspace') or {}),
            version=d.get('version', ''),
            output_style=OutputStyle.from_dict(d.get('output_style') or {}),
            cost=Cost.from_dict(d.get('cost') or {}),
            context_window=ContextWindow.from_dict(d.get('context_window') or {}),
            exceeds_200k_tokens=d.get('exceeds_200k_tokens', False),
            rate_limits=RateLimits.from_dict(d.get('rate_limits') or {}),
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
    def total_in(self) -> int:
        return self.context_window.total_input_tokens

    @property
    def total_out(self) -> int:
        return self.context_window.total_output_tokens

    @property
    def model_name(self) -> str:
        return self.model.display_name or self.model.id or 'unknown'

    @property
    def plugin_names(self) -> str:
        return self.workspace.plugins

    @property
    def token_log(self) -> TokenLog:
        today = datetime.now().strftime('%Y-%m-%d')
        return TokenLog.update(self.session_id, today, self.total_in, self.total_out)

    @property
    def session_cost(self) -> float:
        rate_in, rate_out = self.model.cost_rates
        return (self.total_in * rate_in + self.total_out * rate_out) / 1_000_000

    @property
    def day_cost(self) -> float:
        rate_in, rate_out = self.model.cost_rates
        log = self.token_log
        return (log.day_in * rate_in + log.day_out * rate_out) / 1_000_000

    @property
    def helper(self) -> str:
        return Renderer().helper(self.rate_limits.five_hour)


@dataclass
class TokenLog:
    day_in: int = 0
    day_out: int = 0

    @classmethod
    def update(cls, session_id: str, today: str, total_in: int, total_out: int) -> 'TokenLog':
        log = HOME / '.claude' / 'statusline-tokens.log'
        lines = []
        if log.exists():
            for ln in log.read_text().splitlines():
                parts = ln.split()
                if len(parts) >= 2 and parts[1] == session_id:
                    continue
                lines.append(ln)
        if session_id and (total_in > 0 or total_out > 0):
            lines.append(f'{today} {session_id} {total_in} {total_out}')
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text('\n'.join(lines) + '\n')
        day_in = day_out = 0
        for ln in lines:
            parts = ln.split()
            if len(parts) < 4 or parts[0] != today:
                continue
            try:
                day_in += int(parts[2])
                day_out += int(parts[3])
            except ValueError:
                pass
        return cls(day_in=day_in, day_out=day_out)


@dataclass
class GitInfo:
    branch: str = ''
    commit: str = ''
    modified: str = ''
    untracked: str = ''

    @classmethod
    def from_cwd(cls, cwd: str) -> 'GitInfo':
        repo, gitdir = cls._find_repo(cwd)
        branch, commit = cls._read_head(gitdir)
        modified = untracked = ''
        if branch:
            modified, untracked = cls._dirty(repo)
        return cls(branch=branch, commit=commit, modified=modified, untracked=untracked)

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
    def _dirty(repo: str) -> tuple[str, str]:
        modified = untracked = ''
        if not repo:
            return modified, untracked
        try:
            r = subprocess.run(
                ['git', '-C', repo, 'ls-files', '-m', '--no-optional-locks'],
                capture_output=True, text=True, timeout=2,
            )
            if r.stdout.strip():
                modified = '\033[38;5;214m✹\033[0m'
        except Exception:
            pass
        try:
            r = subprocess.run(
                ['git', '-C', repo, 'ls-files', '--others', '--exclude-standard',
                 '--directory', '--no-empty-directory', '--no-optional-locks',
                 '--', ':/*'],
                capture_output=True, text=True, timeout=2,
            )
            if r.stdout.strip():
                untracked = '\033[38;5;214m✭\033[0m'
        except Exception:
            pass
        return modified, untracked


@dataclass
class OpenSpec:
    changes: list[tuple[str, int, int]] = field(default_factory=list)

    @classmethod
    def from_cwd(cls, cwd: str) -> 'OpenSpec':
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
    if n >= 1000:
        return f'{n/1000:.1f}K'
    return str(n)


class Renderer:
    R = '\033[0m'
    PWD = '\033[38;5;75m'
    BRANCH = '\033[38;5;114m'
    COMMIT = '\033[38;5;244m'
    SESSION = '\033[38;5;244m'
    MODEL = '\033[38;5;183m'
    SKILLS = '\033[38;5;222m'
    TIME = '\033[38;5;244m'
    TOK = '\033[38;5;116m'
    COST = '\033[38;5;210m'
    BAR_FILL = '\033[38;5;114m'
    BAR_EMPTY = '\033[38;5;238m'
    LABEL = '\033[38;5;244m'
    CTX = '\033[38;5;216m'
    BOLDW = '\033[1m\033[38;5;15m'
    BOLDY = '\033[38;5;226m'

    def path_git(self, short_pwd: str, git: GitInfo, session_id: str) -> str:
        return (
            f'{self.PWD}{short_pwd}{self.R}'
            f' {self.LABEL}∈{self.R}'
            f' {self.BRANCH}{git.branch}{self.R}'
            f'{self.LABEL}/{self.R}'
            f'{self.COMMIT}{git.commit}{self.R}'
            f'{git.modified}{git.untracked}'
            f' {self.SESSION}[{session_id}]{self.R}'
        )

    def model_section(self, model_name: str, skills_count: int, skills_names: str, ctx_used_pct: float | None, plugin_names: str, helper: str) -> str:
        line = f'{self.MODEL}󰢹  {model_name}{self.R}'
        if skills_count > 0:
            line += f' {self.LABEL}|{self.R} [{self.SKILLS}{skills_names}{self.R}]'
        if ctx_used_pct is not None and ctx_used_pct != '':
            try:
                ctx_fmt = f'{float(ctx_used_pct):.0f}'
                line += f' {self.LABEL}|{self.R} {self.LABEL}{self.BOLDW}  {self.R}{self.CTX}{ctx_fmt}%{self.R}'
            except (TypeError, ValueError):
                pass
        if plugin_names:
            line += f' {self.LABEL}|{self.R} {self.SKILLS}{plugin_names}{self.R}'
        if helper:
            line += f' |\033[35;5;15\033[1m   {helper}'
        return line

    def tokens_cost(self, sess_in: int, sess_out: int, day_in: int, day_out: int, sess_cost: float, day_cost: float) -> str:
        return (
            f'{self.R}\033[38;5;11m󱢧 {self.LABEL}{self.BOLDY}↓{self.R}{self.TOK}{fmt_tok(sess_in)}{self.R}'
            f'{self.LABEL} {self.BOLDY}↑{self.R}{self.TOK}{fmt_tok(sess_out)}{self.R}'
            f' / {self.LABEL}{self.BOLDY}↓{self.R}{self.TOK}{fmt_tok(day_in)}{self.R}'
            f'{self.LABEL} {self.BOLDY}↑{self.R}{self.TOK}{fmt_tok(day_out)}{self.R}'
            f' | 💰 {self.COST}${sess_cost:.4f}{self.R}'
            f'{self.LABEL}/{self.R}{self.COST}${day_cost:.4f}{self.R}'
        )

    def openspec_bar(self, name: str, done: int, total: int, width: int = 30) -> str:
        filled, pct = done*width//total, done*100//total
        bar_filled, bar_empty = '█' * filled, '░' * (width - filled)

        return (
            f'{self.BAR_FILL}{bar_filled}{self.R}{self.BAR_EMPTY}{bar_empty}{self.R}'
            f' {self.LABEL}{done}/{total}{self.R} \033[1m{pct:>3d}%\033[0m'
            f' {self.LABEL}\033[3m{name}\033[0m{self.R}'
        )

    def helper(self, five_hour: RateBucket) -> str:
        try:
            resets_at = datetime.fromtimestamp(five_hour.resets_at).astimezone()
            delta = resets_at - datetime.now().astimezone().replace(microsecond=0)
            return f'{five_hour.used_percentage}% {self.R}{self.COMMIT}{delta}'
        except Exception:
            return ''

def main() -> None:
    session = SessionInfo.from_dict(json.loads(sys.stdin.read()))

    r = Renderer()

    out = f'{Renderer.R}\n'.join([
        r.path_git(session.short_pwd, GitInfo.from_cwd(session.cwd), session.session_id),
        r.model_section(session.model_name, 0, '', session.context_window.used_percentage, session.workspace.plugins, r.helper(session.rate_limits.five_hour)),
        r.tokens_cost(session.total_in, session.total_out, session.token_log.day_in, session.token_log.day_out, session.session_cost, session.day_cost)
    ])
    for name, d, t in OpenSpec.from_cwd(session.cwd).changes:
        out += '\n' + r.openspec_bar(name, d, t)

    sys.stdout.write(out)


if __name__ == '__main__':
    main()
