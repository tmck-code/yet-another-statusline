"""Session data-classes and parser helpers.

The only package import is the leaf-level `_sanitize` from yas.constants (a
stdlib-only module, so no import cycle); everything else is stdlib.
TokenAccounting (used by Model.cost_rates) is imported lazily inside the
property so this module can be loaded before tokens.py exists; it will resolve
once task 4.1 creates claude/yas/tokens.py.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from yas.constants import _sanitize


HOME       = Path(os.path.expanduser('~'))
CLAUDE_DIR = Path(os.environ.get('CLAUDE_CONFIG_DIR', str(HOME / '.claude')))

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


def _parse_iso_to_epoch(ts: str) -> float:
    try:
        if ts.endswith('Z'):
            ts = ts[:-1] + '+00:00'
        return datetime.fromisoformat(ts).timestamp()
    except (ValueError, TypeError):
        return 0.0

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
        from yas.tokens import TokenAccounting  # wired up in task 4.1
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


class Workspace:
    __slots__ = ('current_dir', 'project_dir', 'added_dirs')

    def __init__(
        self,
        current_dir: str = '',
        project_dir: str = '',
        added_dirs:  list[object] | None = None,
    ) -> None:
        self.current_dir = current_dir
        self.project_dir = project_dir
        self.added_dirs  = added_dirs if added_dirs is not None else []

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Workspace):
            return NotImplemented
        return (self.current_dir, self.project_dir, self.added_dirs) == \
               (other.current_dir, other.project_dir, other.added_dirs)

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return (f'Workspace(current_dir={self.current_dir!r}, project_dir={self.project_dir!r}, '
                f'added_dirs={self.added_dirs!r})')

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
        # Only the user's own config dir is read. project_dir/.claude/settings.json
        # is attacker-controlled for a cloned repo — reading it was both an
        # unexpected trust-boundary read and an escape-injection sink (SEC-2).
        candidates = [CLAUDE_DIR / 'settings.json']
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


class Cost:
    __slots__ = (
        'total_cost_usd', 'total_duration_ms', 'total_api_duration_ms',
        'total_lines_added', 'total_lines_removed',
    )

    def __init__(
        self,
        total_cost_usd:        float = 0.0,
        total_duration_ms:     int = 0,
        total_api_duration_ms: int = 0,
        total_lines_added:     int = 0,
        total_lines_removed:   int = 0,
    ) -> None:
        self.total_cost_usd        = total_cost_usd
        self.total_duration_ms     = total_duration_ms
        self.total_api_duration_ms = total_api_duration_ms
        self.total_lines_added     = total_lines_added
        self.total_lines_removed   = total_lines_removed

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Cost):
            return NotImplemented
        return (self.total_cost_usd, self.total_duration_ms, self.total_api_duration_ms,
                self.total_lines_added, self.total_lines_removed) == \
               (other.total_cost_usd, other.total_duration_ms, other.total_api_duration_ms,
                other.total_lines_added, other.total_lines_removed)

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return (f'Cost(total_cost_usd={self.total_cost_usd}, total_duration_ms={self.total_duration_ms}, '
                f'total_api_duration_ms={self.total_api_duration_ms}, '
                f'total_lines_added={self.total_lines_added}, total_lines_removed={self.total_lines_removed})')

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> Cost:
        return cls(
            total_cost_usd        = _as_float(d.get('total_cost_usd', 0.0)),
            total_duration_ms     = _as_int(d.get('total_duration_ms', 0)),
            total_api_duration_ms = _as_int(d.get('total_api_duration_ms', 0)),
            total_lines_added     = _as_int(d.get('total_lines_added', 0)),
            total_lines_removed   = _as_int(d.get('total_lines_removed', 0)),
        )


class ContextWindow:
    __slots__ = (
        'total_input_tokens', 'total_output_tokens', 'context_window_size',
        'current_usage', 'used_percentage', 'remaining_percentage',
    )

    def __init__(
        self,
        total_input_tokens:   int = 0,
        total_output_tokens:  int = 0,
        context_window_size:  int = 0,
        current_usage:        CurrentUsage | None = None,
        used_percentage:      float | None = None,
        remaining_percentage: float | None = None,
    ) -> None:
        self.total_input_tokens   = total_input_tokens
        self.total_output_tokens  = total_output_tokens
        self.context_window_size  = context_window_size
        self.current_usage        = current_usage if current_usage is not None else CurrentUsage()
        self.used_percentage      = used_percentage
        self.remaining_percentage = remaining_percentage

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ContextWindow):
            return NotImplemented
        return (self.total_input_tokens, self.total_output_tokens, self.context_window_size,
                self.current_usage, self.used_percentage, self.remaining_percentage) == \
               (other.total_input_tokens, other.total_output_tokens, other.context_window_size,
                other.current_usage, other.used_percentage, other.remaining_percentage)

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return (f'ContextWindow(total_input_tokens={self.total_input_tokens}, '
                f'total_output_tokens={self.total_output_tokens}, '
                f'context_window_size={self.context_window_size}, '
                f'current_usage={self.current_usage!r}, used_percentage={self.used_percentage}, '
                f'remaining_percentage={self.remaining_percentage})')

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


class RateLimits:
    __slots__ = ('five_hour', 'seven_day')

    def __init__(
        self,
        five_hour: RateBucket | None = None,
        seven_day: RateBucket | None = None,
    ) -> None:
        self.five_hour = five_hour if five_hour is not None else RateBucket()
        self.seven_day = seven_day if seven_day is not None else RateBucket()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RateLimits):
            return NotImplemented
        return self.five_hour == other.five_hour and self.seven_day == other.seven_day

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return f'RateLimits(five_hour={self.five_hour!r}, seven_day={self.seven_day!r})'

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> RateLimits:
        fh = d.get('five_hour')
        sd = d.get('seven_day')
        return cls(
            five_hour = RateBucket.from_dict(fh if isinstance(fh, dict) else {}),
            seven_day = RateBucket.from_dict(sd if isinstance(sd, dict) else {}),
        )


class SessionInfo:
    # No __slots__: a test splats **session.__dict__ to clone a SessionInfo, so
    # the instance must keep a real __dict__.

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
