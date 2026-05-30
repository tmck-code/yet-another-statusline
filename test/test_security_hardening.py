'''Regression tests for the SEC-1 (escape injection), ROB-1 (stdin crash) and
NAN (non-finite numbers) audit fixes. SEC-2 (cloned-repo settings) is covered by
test_workspace_plugins.py::test_plugins_ignores_project_settings.'''
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from statusline.models import SessionInfo, _as_float, _as_int, _as_str
from statusline.textutil import _sanitize

OSC52 = '\x1b]52;c;ZXZpbA==\x07'   # OSC-52 clipboard-write escape
OSC0  = '\x1b]0;PWNED\x07'         # OSC-0 window-title escape

SCRIPT = Path(__file__).resolve().parent.parent / 'claude' / 'statusline_command.py'


# ---------------------------------------------------------------- SEC-1
def test_sanitize_strips_control_and_escape():
    assert _sanitize('ok') == 'ok'
    assert '\x1b' not in _sanitize(f'main{OSC52}')
    assert '\x07' not in _sanitize(f'x{OSC0}')
    assert _sanitize('a\nb\r\tc') == 'abc'            # newline/CR/tab stripped: no row injection
    assert _sanitize('a\x00\x08\x1f\x7f\x9bz') == 'az'  # C0 + DEL + C1 stripped
    assert _sanitize('héllo ✦ 漢字') == 'héllo ✦ 漢字'  # printable unicode preserved


def _no_ctrl(s: str) -> bool:
    # The escape is defanged once the ESC/BEL/CR/LF control bytes are gone — a
    # terminal renders the leftover printable payload (e.g. ']52;c;...') as inert
    # text. We assert the security property (no control bytes), not byte-equality.
    return not any(ord(c) < 0x20 or 0x7f <= ord(c) <= 0x9f for c in s)


def test_as_str_sanitizes_and_keeps_non_str_default():
    out = _as_str(f'Opus{OSC52}')
    assert _no_ctrl(out) and out.startswith('Opus') and '\x1b' not in out
    assert _as_str(123) == ''
    assert _as_str('plain') == 'plain'


def test_model_name_sanitized_via_from_dict():
    s = SessionInfo.from_dict({'model': {'display_name': f'Opus{OSC0}', 'id': f'id{OSC52}'}})
    assert _no_ctrl(s.model.display_name) and s.model.display_name.startswith('Opus')
    assert _no_ctrl(s.model.id) and '\x1b' not in s.model.id


def test_cwd_and_session_id_sanitized():
    s = SessionInfo.from_dict({'cwd': f'/tmp/p{OSC0}', 'session_id': f'sid{OSC52}'})
    for v in (s.cwd, s.session_id):
        assert '\x1b' not in v and '\x07' not in v


# ---------------------------------------------------------------- NAN
@pytest.mark.parametrize('bad', [float('nan'), float('inf'), float('-inf')])
def test_as_int_rejects_non_finite(bad):
    assert _as_int(bad) == 0
    assert _as_int(bad, default=7) == 7


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), float('-inf')])
def test_as_float_rejects_non_finite(bad):
    assert _as_float(bad) == 0.0


def test_from_dict_survives_nan_inf_numeric_fields():
    # json.loads accepts NaN/Infinity by default; int(nan)/int(inf) would crash.
    payload = json.loads(
        '{"context_window": {"total_input_tokens": NaN, "context_window_size": Infinity},'
        ' "cost": {"total_cost_usd": NaN},'
        ' "rate_limits": {"five_hour": {"used_percentage": Infinity, "resets_at": NaN}}}'
    )
    s = SessionInfo.from_dict(payload)
    assert s.context_window.total_input_tokens == 0
    assert s.context_window.context_window_size == 0
    assert s.cost.total_cost_usd == 0.0
    assert s.rate_limits.five_hour.resets_at == 0


# ---------------------------------------------------------------- ROB-1 (unit)
@pytest.mark.parametrize('bad', [[], 123, 'str', None, True, 3.5])
def test_from_dict_tolerates_non_object(bad):
    s = SessionInfo.from_dict(bad)   # must not raise
    assert s.model.display_name == ''


# ---------------------------------------------------------------- ROB-1 (end-to-end)
def _run(stdin_text, tmp_path):
    env = os.environ.copy()
    env['CLAUDE_CONFIG_DIR'] = str(tmp_path)
    env['COLUMNS'] = '120'
    env.pop('TMUX', None)
    env.pop('TMUX_PANE', None)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=stdin_text, capture_output=True, text=True, env=env, timeout=30,
    )


@pytest.mark.parametrize('stdin_text', ['', 'not json', '[]', '123', '"s"', 'null', 'NaN', '{}'])
def test_main_never_crashes_on_bad_stdin(stdin_text, tmp_path):
    proc = _run(stdin_text, tmp_path)
    assert proc.returncode == 0, f'crashed on {stdin_text!r}: {proc.stderr}'


def test_main_does_not_write_payload_on_bad_stdin(tmp_path):
    # crash-recovery {} must not clobber / create a payload file
    _run('[]', tmp_path)
    out_dir = tmp_path / 'statusline-output'
    assert not out_dir.exists() or not list(out_dir.glob('*.json'))


def test_main_renders_and_writes_payload_on_valid_stdin(tmp_path):
    proc = _run(json.dumps({'session_id': 'abc', 'model': {'display_name': 'Opus'}}), tmp_path)
    assert proc.returncode == 0
    assert list((tmp_path / 'statusline-output').glob('*.json'))
