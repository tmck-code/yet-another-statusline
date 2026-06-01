'''Tests for the UserPromptSubmit hook and read_last_prompt_ts.

Covers:
- Two-session concurrent write preserves both entries
- Truncated/invalid JSON in the state file → read_last_prompt_ts returns None and does not raise
- Missing state file → read_last_prompt_ts returns None
'''
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import pytest

from yas.info.subagents import read_last_prompt_ts


# ---------------------------------------------------------------------------
# Hook script helpers
# ---------------------------------------------------------------------------

_HOOK_SCRIPT = Path(__file__).resolve().parent.parent / 'hooks' / 'yas-prompt-hook.py'


def _run_hook_logic(session_id: str, state_file: Path) -> None:
    '''Invoke the hook's core logic directly against a given state file path.

    We import the hook module once (or reuse the cached import) and call main()
    with stdin and CLAUDE_CONFIG_DIR patched to point at our temp directory.
    '''
    # Import the hook module (cache it so subsequent calls reuse it).
    mod_name = '_yas_prompt_hook'
    if mod_name not in sys.modules:
        spec = importlib.util.spec_from_file_location(mod_name, _HOOK_SCRIPT)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
    mod = sys.modules[mod_name]

    import io
    payload = json.dumps({'session_id': session_id})
    env_backup = os.environ.copy()
    try:
        os.environ['CLAUDE_CONFIG_DIR'] = str(state_file.parent)
        old_stdin = sys.stdin
        sys.stdin = io.StringIO(payload)
        try:
            mod.main()
        finally:
            sys.stdin = old_stdin
    finally:
        # Restore env
        for k in list(os.environ.keys()):
            if k not in env_backup:
                del os.environ[k]
        for k, v in env_backup.items():
            os.environ[k] = v


# ---------------------------------------------------------------------------
# Tests: read_last_prompt_ts
# ---------------------------------------------------------------------------

def test_missing_state_file_returns_none(tmp_home: Path) -> None:
    '''Missing state file → None, no raise.'''
    result = read_last_prompt_ts('any-session')
    assert result is None


def test_invalid_json_returns_none(tmp_home: Path) -> None:
    '''Truncated/invalid JSON → None, no raise.'''
    state = tmp_home / '.claude' / 'yas-last-prompt.json'
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text('{ "sess": 12345')  # truncated JSON

    result = read_last_prompt_ts('sess')
    assert result is None


def test_empty_file_returns_none(tmp_home: Path) -> None:
    '''Empty file → None, no raise.'''
    state = tmp_home / '.claude' / 'yas-last-prompt.json'
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text('')

    result = read_last_prompt_ts('any-session')
    assert result is None


def test_session_not_in_map_returns_none(tmp_home: Path) -> None:
    '''State file exists but session not in map → None.'''
    state = tmp_home / '.claude' / 'yas-last-prompt.json'
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({'other-session': 1234567890.0}))

    result = read_last_prompt_ts('missing-session')
    assert result is None


def test_session_present_returns_float(tmp_home: Path) -> None:
    '''Session in map → correct float returned.'''
    state = tmp_home / '.claude' / 'yas-last-prompt.json'
    state.parent.mkdir(parents=True, exist_ok=True)
    ts = 1700000000.5
    state.write_text(json.dumps({'my-session': ts}))

    result = read_last_prompt_ts('my-session')
    assert result == pytest.approx(ts)


def test_non_dict_json_returns_none(tmp_home: Path) -> None:
    '''JSON that is not a dict (e.g. a list) → None.'''
    state = tmp_home / '.claude' / 'yas-last-prompt.json'
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps([1, 2, 3]))

    result = read_last_prompt_ts('any')
    assert result is None


# ---------------------------------------------------------------------------
# Tests: hook script
# ---------------------------------------------------------------------------

def test_hook_writes_single_session(tmp_path: Path) -> None:
    '''Hook creates the state file and records a timestamp for the session.'''
    state = tmp_path / 'yas-last-prompt.json'
    before = time.time()
    _run_hook_logic('sess-a', state)
    after = time.time()

    assert state.is_file()
    data = json.loads(state.read_text())
    assert 'sess-a' in data
    assert before <= data['sess-a'] <= after


def test_hook_two_session_concurrent_write_preserves_both(tmp_path: Path) -> None:
    '''Two calls with different session IDs both persist in the state file.'''
    state = tmp_path / 'yas-last-prompt.json'

    before_a = time.time()
    _run_hook_logic('sess-alpha', state)
    after_a = time.time()

    before_b = time.time()
    _run_hook_logic('sess-beta', state)
    after_b = time.time()

    data = json.loads(state.read_text())
    assert 'sess-alpha' in data, 'first session entry must be preserved'
    assert 'sess-beta' in data, 'second session entry must be present'
    assert before_a <= data['sess-alpha'] <= after_a
    assert before_b <= data['sess-beta'] <= after_b


def test_hook_overwrites_same_session(tmp_path: Path) -> None:
    '''Calling the hook twice for the same session updates the timestamp.'''
    state = tmp_path / 'yas-last-prompt.json'

    _run_hook_logic('sess-x', state)
    ts1 = json.loads(state.read_text())['sess-x']

    time.sleep(0.01)  # ensure clock advances
    _run_hook_logic('sess-x', state)
    ts2 = json.loads(state.read_text())['sess-x']

    assert ts2 >= ts1


def test_hook_corrupt_file_recovers(tmp_path: Path) -> None:
    '''Hook tolerates corrupt existing file and writes fresh data.'''
    state = tmp_path / 'yas-last-prompt.json'
    state.write_text('{bad json!!!')

    _run_hook_logic('sess-recover', state)

    data = json.loads(state.read_text())
    assert 'sess-recover' in data


def test_hook_missing_session_id_does_not_crash(tmp_path: Path) -> None:
    '''Hook silently exits when session_id is absent from the payload.'''
    import io
    mod = sys.modules.get('_yas_prompt_hook')
    if mod is None:
        spec = importlib.util.spec_from_file_location('_yas_prompt_hook', _HOOK_SCRIPT)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        sys.modules['_yas_prompt_hook'] = mod
        spec.loader.exec_module(mod)

    state = tmp_path / 'yas-last-prompt.json'
    env_backup = os.environ.copy()
    try:
        os.environ['CLAUDE_CONFIG_DIR'] = str(tmp_path)
        sys.stdin, old = io.StringIO(json.dumps({})), sys.stdin
        try:
            mod.main()  # must not raise
        finally:
            sys.stdin = old
    finally:
        for k in list(os.environ.keys()):
            if k not in env_backup:
                del os.environ[k]
        for k, v in env_backup.items():
            os.environ[k] = v

    assert not state.exists()
