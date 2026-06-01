#!/usr/bin/env python3
'''YAS UserPromptSubmit hook — records session prompt timestamps.

Claude Code invokes this script on every UserPromptSubmit event, passing a
JSON payload on stdin.  The script reads session_id from the payload, then
atomically updates ~/.claude/yas-last-prompt.json (or
$CLAUDE_CONFIG_DIR/yas-last-prompt.json) with the current epoch timestamp for
that session.  All other sessions' entries are preserved.

Never raises — any failure is silently swallowed and the process exits 0.
'''
import json
import os
import sys
import tempfile
import time
from pathlib import Path


def _state_path() -> Path:
    config_dir = os.environ.get('CLAUDE_CONFIG_DIR', '')
    if config_dir:
        return Path(config_dir) / 'yas-last-prompt.json'
    return Path.home() / '.claude' / 'yas-last-prompt.json'


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
    main()
