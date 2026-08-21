"""Session data-classes and parser helpers."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from yas.constants import _sanitize, settings_path


HOME = Path(os.path.expanduser('~'))

# helpers ---------------------------------------

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
        return _sanitize(v)
    return default


# models ----------------------------------------

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
        from yas.tokens import TokenAccounting
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


@dataclass(slots=True)
class Workspace:
    current_dir: str = ''
    project_dir: str = ''
    added_dirs:  list[object] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> Workspace:
        current_dir = d.get('current_dir', '')
        project_dir = d.get('project_dir', '')
        added_dirs  = d.get('added_dirs')
        return cls(
            current_dir = _sanitize(str(current_dir)) if current_dir else '',
            project_dir = _sanitize(str(project_dir)) if project_dir else '',
            added_dirs  = list(added_dirs) if isinstance(added_dirs, list) else [],
        )

    @property
    def plugins(self) -> str:
        seen: dict[str, None] = {}
        candidates = [settings_path()]  # only the user's own config dir; project settings.json is untrusted
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


@dataclass(slots=True)
class Cost:
    total_cost_usd:        float = 0.0
    total_duration_ms:     int = 0
    total_api_duration_ms: int = 0
    total_lines_added:     int = 0
    total_lines_removed:   int = 0

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> Cost:
        return cls(
            total_cost_usd        = _as_float(d.get('total_cost_usd', 0.0)),
            total_duration_ms     = _as_int(d.get('total_duration_ms', 0)),
            total_api_duration_ms = _as_int(d.get('total_api_duration_ms', 0)),
            total_lines_added     = _as_int(d.get('total_lines_added', 0)),
            total_lines_removed   = _as_int(d.get('total_lines_removed', 0)),
        )


@dataclass(slots=True)
class ContextWindow:
    total_input_tokens:   int = 0
    total_output_tokens:  int = 0
    context_window_size:  int = 0
    current_usage:        CurrentUsage = field(default_factory=CurrentUsage)
    used_percentage:      float | None = None
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


@dataclass(slots=True)
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


class SessionInfo:
    # no __slots__: a test splats **session.__dict__ to clone a SessionInfo

    def __init__(
        self,
        session_id:          str = '',
        transcript_path:     str = '',
        cwd:                 str = '',
        model:               Model | None = None,
        workspace:           Workspace | None = None,
        version:             str = '',
        output_style:        OutputStyle | None = None,
        cost:                Cost | None = None,
        context_window:      ContextWindow | None = None,
        exceeds_200k_tokens: bool = False,
        effort:              Effort | None = None,
        thinking:            Thinking | None = None,
        fast_mode:           bool = False,
        rate_limits:         RateLimits | None = None,
    ) -> None:
        self.session_id          = session_id
        self.transcript_path     = transcript_path
        self.cwd                 = cwd
        self.model               = model if model is not None else Model()
        self.workspace           = workspace if workspace is not None else Workspace()
        self.version             = version
        self.output_style        = output_style if output_style is not None else OutputStyle()
        self.cost                = cost if cost is not None else Cost()
        self.context_window      = context_window if context_window is not None else ContextWindow()
        self.exceeds_200k_tokens = exceeds_200k_tokens
        self.effort              = effort if effort is not None else Effort()
        self.thinking            = thinking if thinking is not None else Thinking()
        self.fast_mode           = fast_mode
        self.rate_limits         = rate_limits if rate_limits is not None else RateLimits()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SessionInfo):
            return NotImplemented
        return self.__dict__ == other.__dict__

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        fields = ', '.join(f'{k}={v!r}' for k, v in self.__dict__.items())
        return f'SessionInfo({fields})'

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
            session_id          = _sanitize(str(session_id))      if session_id      is not None else '',
            transcript_path     = str(transcript_path) if transcript_path is not None else '',
            cwd                 = _sanitize(str(cwd))             if cwd             is not None else '',
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
