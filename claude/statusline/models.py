"""Session payload models + pricing.

The dataclasses Claude Code's session-info JSON parses into — the reusable
type system the renderer (and the future macOS app) read. Plus TokenAccounting
(pricing per model family/version) which co-locates because Model.cost_rates
calls it, and model_key (canonical 'opus'/'sonnet'/'haiku'/'other' bucket).

Runtime config (CLAUDE_DIR, HOME) is read dynamically via `config.X` so the
test sandbox can patch one location and see it everywhere.

Forward references to TranscriptUsage / TokenLog are intentional: those data-
collection types still live in statusline_command for now; with `from __future__
import annotations` their names are strings at runtime, and the TYPE_CHECKING
block lets mypy resolve them without a circular import.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, NamedTuple

from statusline import config
from statusline.textutil import _sanitize

if TYPE_CHECKING:
    from statusline.accounting import TokenLog
    from statusline.transcript import TranscriptUsage


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
        # `din` is billed input (plain + cache-creation, already at 1.0x); add a
        # 0.25x surcharge on the cache-creation portion so day cost matches
        # session_cost's 1.25x cache-write rate (Audit ACCT-1). Pre-v3 rows have
        # cache_creation==0, so they keep the old 1.0x behaviour.
        if token_log.by_model:
            total = 0.0
            for mid, (din, dcc, dcache, dout) in token_log.by_model.items():
                rate_in, rate_out = TokenAccounting.rates_for(mid) if mid else model.cost_rates
                total += din * rate_in + dcc * rate_in * 0.25 + dcache * rate_in * 0.1 + dout * rate_out
            return total / 1_000_000
        rate_in, rate_out = TokenAccounting.rates_for(model.display_name or model.id)
        cost = (
            token_log.day_in * rate_in
            + token_log.day_cache_creation * rate_in * 0.25
            + token_log.day_cache_read * rate_in * 0.1
            + token_log.day_out * rate_out
        )
        return cost / 1_000_000


def _as_int(v: object, default: int = 0) -> int:
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        # json.loads accepts NaN/Infinity by default; int(nan) raises ValueError
        # and int(inf) raises OverflowError, which would crash the whole render.
        return int(v) if math.isfinite(v) else default
    return default


def _as_float(v: object, default: float = 0.0) -> float:
    if isinstance(v, (int, float)):
        f = float(v)
        return f if math.isfinite(f) else default  # reject NaN/Infinity (see _as_int)
    return default


def _as_str(v: object, default: str = '') -> str:
    if isinstance(v, str):
        return _sanitize(v)  # strip control chars: untrusted field -> rendered line (terminal-escape injection)
    return default


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
        # SEC: read only the user's own (trusted) global settings. A cloned repo's
        # project_dir/.claude/settings.json is attacker-authored content; rendering
        # its enabledPlugins keys is both an unexpected trust-boundary read and a
        # terminal-escape injection sink, for near-zero value. (Audit SEC-2.)
        sf = config.CLAUDE_DIR / 'settings.json'
        if sf.is_file():
            try:
                data = json.loads(sf.read_text())
            except Exception:
                data = {}
            for key, val in (data.get('enabledPlugins') or {}).items():
                if val is True:
                    name = _sanitize(key.split('@', 1)[0])
                    if name and name not in seen:
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
            # Floor at 0: a stray negative count (host glitch / post-/compact
            # transient) must never produce a negative fill or overflow the bar
            # (Audit CTX-NEG). NaN/Inf are already rejected by _as_int.
            total_input_tokens   = max(0, _as_int(d.get('total_input_tokens', 0))),
            total_output_tokens  = max(0, _as_int(d.get('total_output_tokens', 0))),
            context_window_size  = max(0, _as_int(d.get('context_window_size', 0))),
            current_usage        = cu,
            # Finite-guard the pre-calc percentages: json.loads accepts NaN/Inf,
            # which would poison the bar's clamp math (min/max propagate NaN).
            used_percentage      = float(used_pct) if isinstance(used_pct, (int, float)) and math.isfinite(used_pct) else None,
            remaining_percentage = float(rem_pct)  if isinstance(rem_pct,  (int, float)) and math.isfinite(rem_pct)  else None,
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
        if not isinstance(d, dict):  # defence-in-depth: render(non-dict stdin) must not crash
            d = {}
        def _dict(key: str) -> dict[str, object]:
            v = d.get(key)
            return v if isinstance(v, dict) else {}
        session_id      = d.get('session_id', '')
        transcript_path = d.get('transcript_path', '')
        cwd             = d.get('cwd', '')
        version         = d.get('version', '')
        return cls(
            session_id          = _sanitize(str(session_id)) if session_id is not None else '',
            transcript_path     = str(transcript_path) if transcript_path is not None else '',
            cwd                 = _sanitize(str(cwd))        if cwd        is not None else '',
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
        home = str(config.HOME)
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


def model_key(name: str) -> str:
    m = name.lower()
    if 'opus'   in m: return 'opus'
    if 'sonnet' in m: return 'sonnet'
    if 'haiku'  in m: return 'haiku'
    return 'other'
