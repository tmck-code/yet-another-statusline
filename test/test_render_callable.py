import json
import subprocess
import sys
from pathlib import Path

import pytest

import statusline_command as sl

_EXAMPLE = Path(__file__).resolve().parent.parent / 'claude' / 'statusline' / 'session-info-example.json'
_SCRIPT  = Path(__file__).resolve().parent.parent / 'claude' / 'statusline_command.py'


def _load_example() -> dict:
    return json.loads(_EXAMPLE.read_text())


def test_render_returns_nonempty():
    info   = _load_example()
    result = sl.render(info, 160)
    assert isinstance(result, str)
    assert len(result) > 0


def test_render_is_io_free(monkeypatch):
    class _Raise:
        def read(self, *a, **kw):   raise AssertionError('stdin touched')
        def write(self, *a, **kw):  raise AssertionError('stdout touched')
        def flush(self, *a, **kw):  raise AssertionError('stderr touched')

    monkeypatch.setattr(sys, 'stdin',  _Raise())
    monkeypatch.setattr(sys, 'stdout', _Raise())
    monkeypatch.setattr(sys, 'stderr', _Raise())

    info   = _load_example()
    result = sl.render(info, 160)
    assert len(result) > 0


def test_render_different_widths_produce_different_layouts():
    info    = _load_example()
    narrow  = sl.render(info, 50)
    wide    = sl.render(info, 160)
    assert narrow != wide


def test_yas_full_width_fills_terminal(tmp_path, monkeypatch, capsys):
    import io
    info = _load_example()
    fake_tw = 200  # wider than MAX_WIDTH so capping is observable

    monkeypatch.setattr(sl, 'terminal_width', lambda: fake_tw)
    monkeypatch.setattr(sl, 'HOME', tmp_path)

    def _first_line_width(env_extra):
        for k, v in env_extra.items():
            monkeypatch.setenv(k, v)
        buf = io.StringIO()
        monkeypatch.setattr(sl.sys, 'stdout', buf)
        monkeypatch.setattr(sl.sys, 'stdin', io.StringIO(sl.json.dumps(info)))
        sl.main()
        out = buf.getvalue()
        monkeypatch.delenv('YAS_FULL_WIDTH', raising=False)
        first_line = out.splitlines()[0] if out else ''
        return sl._visible_width(first_line)

    uncapped_w = _first_line_width({'YAS_FULL_WIDTH': '1'})
    default_w  = _first_line_width({})

    assert uncapped_w == fake_tw,      f'YAS_FULL_WIDTH: expected {fake_tw}, got {uncapped_w}'
    assert default_w  == sl.MAX_WIDTH, f'default: expected {sl.MAX_WIDTH}, got {default_w}'


def test_render_matches_cli_subprocess(tmp_path, monkeypatch):
    import os
    monkeypatch.setattr(sl, 'HOME', tmp_path)

    info = _load_example()

    proc = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        input=json.dumps(info),
        capture_output=True,
        text=True,
        env={**os.environ, 'COLUMNS': '166', 'HOME': str(tmp_path)},
    )
    result_cli = proc.stdout

    result_api = sl.render(info, 160)

    assert result_api == result_cli.rstrip('\n')
