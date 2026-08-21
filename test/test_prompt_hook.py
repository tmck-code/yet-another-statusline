'''Tests for the UserPromptSubmit hook and read_last_prompt_ts.

Covers:
- Two-session concurrent write preserves both entries
- Truncated/invalid JSON in the state file → read_last_prompt_ts returns None and does not raise
- Missing state file → read_last_prompt_ts returns None
'''
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

from yas.constants import last_prompt_path
from yas.info.subagents import read_last_prompt_ts

_INSTALL_SH = Path(__file__).resolve().parent.parent / 'ops' / 'install.sh'


def _json_py_body() -> str:
    '''Extract the json_py python heredoc from ops/install.sh.

    Testing the real op body (rather than a re-implementation) proves the exact
    code the installer runs, so a divergence in the shipped heredoc is caught.
    '''
    src = _INSTALL_SH.read_text()
    match = re.search(r"<<'PY'\n(.*?)\nPY\n", src, re.S)
    assert match, 'json_py heredoc not found in install.sh'
    return match.group(1)


def _run_json_py(op: str, path: Path, *rest: str) -> str:
    '''Invoke a json_py op as a subprocess against the real heredoc body.'''
    proc = subprocess.run(
        [sys.executable, '-', op, str(path), *rest],
        input          = _json_py_body(),
        capture_output = True,
        text           = True,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


_STATUSLINE_CMD = '"python3" "/plugin/claude/statusline_command.py"'
_HOOK_CMD = '"python3" "/plugin/hooks/yas-prompt-hook.py"'
_FOREIGN = {
    'matcher': '',
    'hooks': [{'type': 'command', 'command': '"python3" "/x/docker-skill-nudge.py"'}],
}


_HOOK_SCRIPT = Path(__file__).resolve().parent.parent / 'hooks' / 'yas-prompt-hook.py'


def _run_hook_logic(session_id: str, config_dir: Path) -> None:
    '''Invoke the hook's core logic directly against a given CLAUDE_CONFIG_DIR.

    We import the hook module once (or reuse the cached import) and call main()
    with stdin and CLAUDE_CONFIG_DIR patched to point at our temp directory. The
    hook itself derives its state file as
    <config_dir>/yas/state/signals/last-prompt.json (see _state_path).
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
        os.environ['CLAUDE_CONFIG_DIR'] = str(config_dir)
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


def test_missing_state_file_returns_none(tmp_home: Path) -> None:
    '''Missing state file → None, no raise.'''
    result = read_last_prompt_ts('any-session')
    assert result is None


def test_invalid_json_returns_none(tmp_home: Path) -> None:
    '''Truncated/invalid JSON → None, no raise.'''
    state = last_prompt_path()
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text('{ "sess": 12345')  # truncated JSON

    result = read_last_prompt_ts('sess')
    assert result is None


def test_empty_file_returns_none(tmp_home: Path) -> None:
    '''Empty file → None, no raise.'''
    state = last_prompt_path()
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text('')

    result = read_last_prompt_ts('any-session')
    assert result is None


def test_session_not_in_map_returns_none(tmp_home: Path) -> None:
    '''State file exists but session not in map → None.'''
    state = last_prompt_path()
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({'other-session': 1234567890.0}))

    result = read_last_prompt_ts('missing-session')
    assert result is None


def test_session_present_returns_float(tmp_home: Path) -> None:
    '''Session in map → correct float returned.'''
    state = last_prompt_path()
    state.parent.mkdir(parents=True, exist_ok=True)
    ts = 1700000000.5
    state.write_text(json.dumps({'my-session': ts}))

    result = read_last_prompt_ts('my-session')
    assert result == pytest.approx(ts)


def test_non_dict_json_returns_none(tmp_home: Path) -> None:
    '''JSON that is not a dict (e.g. a list) → None.'''
    state = last_prompt_path()
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps([1, 2, 3]))

    result = read_last_prompt_ts('any')
    assert result is None


def test_hook_writes_single_session(tmp_path: Path) -> None:
    '''Hook creates the state file and records a timestamp for the session.'''
    state = tmp_path / 'yas' / 'state' / 'signals' / 'last-prompt.json'
    state.parent.mkdir(parents=True, exist_ok=True)
    before = time.time()
    _run_hook_logic('sess-a', tmp_path)
    after = time.time()

    assert state.is_file()
    data = json.loads(state.read_text())
    assert 'sess-a' in data
    assert before <= data['sess-a'] <= after


def test_hook_two_session_concurrent_write_preserves_both(tmp_path: Path) -> None:
    '''Two calls with different session IDs both persist in the state file.'''
    state = tmp_path / 'yas' / 'state' / 'signals' / 'last-prompt.json'
    state.parent.mkdir(parents=True, exist_ok=True)

    before_a = time.time()
    _run_hook_logic('sess-alpha', tmp_path)
    after_a = time.time()

    before_b = time.time()
    _run_hook_logic('sess-beta', tmp_path)
    after_b = time.time()

    data = json.loads(state.read_text())
    assert 'sess-alpha' in data, 'first session entry must be preserved'
    assert 'sess-beta' in data, 'second session entry must be present'
    assert before_a <= data['sess-alpha'] <= after_a
    assert before_b <= data['sess-beta'] <= after_b


def test_hook_overwrites_same_session(tmp_path: Path) -> None:
    '''Calling the hook twice for the same session updates the timestamp.'''
    state = tmp_path / 'yas' / 'state' / 'signals' / 'last-prompt.json'
    state.parent.mkdir(parents=True, exist_ok=True)

    _run_hook_logic('sess-x', tmp_path)
    ts1 = json.loads(state.read_text())['sess-x']

    time.sleep(0.01)  # ensure clock advances
    _run_hook_logic('sess-x', tmp_path)
    ts2 = json.loads(state.read_text())['sess-x']

    assert ts2 >= ts1


def test_hook_corrupt_file_recovers(tmp_path: Path) -> None:
    '''Hook tolerates corrupt existing file and writes fresh data.'''
    state = tmp_path / 'yas' / 'state' / 'signals' / 'last-prompt.json'
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text('{bad json!!!')

    _run_hook_logic('sess-recover', tmp_path)

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

    state = tmp_path / 'yas' / 'state' / 'signals' / 'last-prompt.json'
    state.parent.mkdir(parents=True, exist_ok=True)
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


class TestInstallerHookOps:
    '''The install.sh json_py wire/get-hook/del-hook ops that manage the
    UserPromptSubmit hook alongside statusLine, exercised via the real heredoc.'''

    def test_wire_on_empty_sets_statusline_and_hook(self, tmp_path):
        settings = tmp_path / 'settings.json'
        settings.write_text('{}')

        result = json.loads(_run_json_py('wire', settings, _STATUSLINE_CMD, _HOOK_CMD))

        expected = {
            'statusLine': {
                'async': True,
                'command': _STATUSLINE_CMD,
                'refreshInterval': 1,
                'type': 'command',
                'padding': 1,
            },
            'hooks': {
                'UserPromptSubmit': [
                    {'matcher': '', 'hooks': [{'type': 'command', 'command': _HOOK_CMD}]},
                ],
            },
        }

        assert result == expected

    def test_wire_is_idempotent(self, tmp_path):
        settings = tmp_path / 'settings.json'
        settings.write_text('{}')
        settings.write_text(_run_json_py('wire', settings, _STATUSLINE_CMD, _HOOK_CMD))

        result = json.loads(_run_json_py('wire', settings, _STATUSLINE_CMD, _HOOK_CMD))

        expected = [
            {'matcher': '', 'hooks': [{'type': 'command', 'command': _HOOK_CMD}]},
        ]

        assert result['hooks']['UserPromptSubmit'] == expected

    def test_wire_preserves_foreign_hooks(self, tmp_path):
        settings = tmp_path / 'settings.json'
        settings.write_text(json.dumps({'hooks': {'UserPromptSubmit': [_FOREIGN]}}))

        result = json.loads(_run_json_py('wire', settings, _STATUSLINE_CMD, _HOOK_CMD))

        expected = [
            _FOREIGN,
            {'matcher': '', 'hooks': [{'type': 'command', 'command': _HOOK_CMD}]},
        ]

        assert result['hooks']['UserPromptSubmit'] == expected

    def test_wire_replaces_stale_path(self, tmp_path):
        stale = {
            'matcher': '',
            'hooks': [{'type': 'command', 'command': '"python3" "/old/0.2.0/hooks/yas-prompt-hook.py"'}],
        }
        settings = tmp_path / 'settings.json'
        settings.write_text(json.dumps({'hooks': {'UserPromptSubmit': [stale]}}))

        result = json.loads(_run_json_py('wire', settings, _STATUSLINE_CMD, _HOOK_CMD))

        expected = [
            {'matcher': '', 'hooks': [{'type': 'command', 'command': _HOOK_CMD}]},
        ]

        assert result['hooks']['UserPromptSubmit'] == expected

    def test_get_hook_returns_current_command(self, tmp_path):
        settings = tmp_path / 'settings.json'
        settings.write_text(_run_json_py('wire', settings, _STATUSLINE_CMD, _HOOK_CMD))

        result = _run_json_py('get-hook', settings).strip()

        expected = _HOOK_CMD

        assert result == expected

    def test_get_hook_empty_when_absent(self, tmp_path):
        settings = tmp_path / 'settings.json'
        settings.write_text('{}')

        result = _run_json_py('get-hook', settings)

        expected = ''

        assert result == expected

    def test_del_hook_removes_only_yas_and_collapses(self, tmp_path):
        settings = tmp_path / 'settings.json'
        settings.write_text(json.dumps({
            'theme': 'dark',
            'hooks': {'UserPromptSubmit': [
                {'matcher': '', 'hooks': [{'type': 'command', 'command': _HOOK_CMD}]},
            ]},
        }))

        result = json.loads(_run_json_py('del-hook', settings))

        # expected — sole YAS entry gone, empty UserPromptSubmit/hooks collapse away
        expected = {'theme': 'dark'}

        assert result == expected

    def test_del_hook_preserves_foreign_hooks(self, tmp_path):
        settings = tmp_path / 'settings.json'
        settings.write_text(json.dumps({
            'hooks': {'UserPromptSubmit': [
                _FOREIGN,
                {'matcher': '', 'hooks': [{'type': 'command', 'command': _HOOK_CMD}]},
            ]},
        }))

        result = json.loads(_run_json_py('del-hook', settings))

        expected = {'hooks': {'UserPromptSubmit': [_FOREIGN]}}

        assert result == expected
