"""Runtime config singletons: the resolved Claude config dir + the home dir.

Accessed via attribute lookup — `config.CLAUDE_DIR` / `config.HOME`, NOT
`from .config import CLAUDE_DIR` — so the test sandbox (conftest.tmp_home)
can patch one canonical location and every reader across every module sees
the patched value. Binding via `from ... import X` would freeze the
import-time value in the importing module and bypass the patch — the
sandbox would silently escape to the real ~/.claude.
"""
from __future__ import annotations

import os
from pathlib import Path

HOME       = Path(os.path.expanduser('~'))
CLAUDE_DIR = Path(os.environ.get('CLAUDE_CONFIG_DIR', str(HOME / '.claude')))
