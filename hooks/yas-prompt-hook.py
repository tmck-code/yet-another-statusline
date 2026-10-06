#!/usr/bin/env python3
'''YAS UserPromptSubmit hook — records session prompt timestamps.

Claude Code invokes this script on every UserPromptSubmit event, passing a
JSON payload on stdin.  The script reads session_id from the payload, then
atomically updates <config_dir>/yas/state/signals/last-prompt.json (where
config_dir is $CLAUDE_CONFIG_DIR, defaulting to ~/.claude) with the current
epoch timestamp for that session.  All other sessions' entries are preserved.

Never raises — any failure is silently swallowed and the process exits 0.
'''
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

# Duplicates yas.constants.WATCHDOG_SECONDS (see that comment for the why);
# same bare-script constraint as _state_path below.
_WATCHDOG_SECONDS = 10.0


def _arm_watchdog(seconds: float) -> None:
    '''Hard-exit the process after `seconds`, even while blocked reading stdin.'''
    timer = threading.Timer(seconds, os._exit, args=(0,))
    timer.daemon = True
    timer.start()


def _state_path() -> Path:
    # NOTE: this duplicates yas.constants.last_prompt_path() on purpose.  Claude
    # Code runs this hook as a bare script, without the `yas` package on
    # sys.path, so it cannot import the helper.  yas.constants remains the
    # source of truth for the layout: keep the two in sync when it changes.
    config_dir = os.environ.get('CLAUDE_CONFIG_DIR', '')
    base = Path(config_dir) if config_dir else Path.home() / '.claude'
    return base / 'yas' / 'state' / 'signals' / 'last-prompt.json'


def main() -> None:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw)
        session_id = payload.get('session_id', '')
        if not session_id:
            return

        state_file = _state_path()

        # Read existing map, tolerating missing or corrupt file.
        data: dict[str, float] = {}
        try:
            text = state_file.read_text()
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                data = {k: float(v) for k, v in parsed.items() if isinstance(v, (int, float))}
        except (OSError, ValueError, TypeError):
            data = {}

        # Update only this session's entry.
        data[session_id] = time.time()

        # Atomic write: temp file in same directory, then rename.
        state_file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir    = state_file.parent,
            prefix = '.yas-last-prompt-',
            suffix = '.tmp',
        )
        try:
            with os.fdopen(fd, 'w') as fh:
                json.dump(data, fh)
            os.replace(tmp_path, state_file)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    except Exception:
        pass


if __name__ == '__main__':
    _arm_watchdog(_WATCHDOG_SECONDS)
    main()
