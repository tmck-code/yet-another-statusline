"""Wall-clock singleton: `now()` for the renderer + data-core.

All modules that need the current time call `clock.now()` (attribute access via
`from statusline import clock`) rather than `datetime.now()` directly. This
mirrors the `config` pattern: one canonical location the test fixture patches,
seen by every module across the package. Binding via `from .clock import now`
would freeze the import-time function in the importing module and bypass the
patch — the snapshot fixture would only affect statusline_command's own calls.

Deterministic conversions (`datetime.fromtimestamp(ts)`, `datetime.fromisoformat`)
don't go through this module; they're stable given their input.
"""
from __future__ import annotations

from datetime import datetime


def now() -> datetime:
    'The current wall-clock datetime. The frozen-snapshot fixture patches this.'
    return datetime.now()
