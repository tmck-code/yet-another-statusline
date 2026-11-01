"""Bash tool calls still in flight in one transcript.

A Bash `tool_use` is in flight from the moment it is written until its
`tool_result` arrives. A `run_in_background` call keeps running after its
immediate result, so it stays in flight. The state is a JSON-serialisable
`{tool_use_id: [command, timestamp, background]}` dict, advanced line by line
so it can ride along an existing incremental transcript fold.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from yas.constants import _sanitize

MAX_INFLIGHT = 50

_RESULT_ID_RE = re.compile(r'"tool_use_id"\s*:\s*"([^"]+)"')


def normalise(command: str) -> str:
    'Command text in the same form `ShellCommand.command` uses.'
    return _sanitize(' '.join(command.split()))


def _epoch(ts: object) -> float:
    try:
        return datetime.fromisoformat(str(ts).replace('Z', '+00:00')).timestamp()
    except ValueError:
        return 0.0


def fold_line(state: dict[str, list[Any]], ln: str) -> None:
    'Advance `state` over one decoded transcript line.'
    if '"tool_use"' in ln and '"Bash"' in ln:
        note_uses(state, ln)
    elif '"tool_result"' in ln:
        for tid in _RESULT_ID_RE.findall(ln):
            entry = state.get(tid)
            if entry is not None and not entry[2]:
                del state[tid]


def note_uses(state: dict[str, list[Any]], ln: str) -> None:
    try:
        d = json.loads(ln)
        msg = d.get('message') or {}
        content = msg.get('content')
        ts = _epoch(d.get('timestamp', ''))
    except (ValueError, AttributeError):
        return
    if not isinstance(content, list):
        return
    for n, item in enumerate(content):
        if not isinstance(item, dict) or item.get('type') != 'tool_use' or item.get('name') != 'Bash':
            continue
        inp = item.get('input')
        if not isinstance(inp, dict):
            continue
        cmd = inp.get('command')
        if not isinstance(cmd, str):
            continue
        key = str(item.get('id') or f'{msg.get("id", "")}:{n}')
        if key in state:
            continue
        state[key] = [normalise(cmd), ts, inp.get('run_in_background') is True]
    while len(state) > MAX_INFLIGHT:
        del state[next(iter(state))]


def inflight(state: dict[str, list[Any]]) -> tuple[tuple[str, float], ...]:
    'In-flight `(command, timestamp)` pairs, oldest first.'
    return tuple((e[0], e[1]) for e in state.values())
