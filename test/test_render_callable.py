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
