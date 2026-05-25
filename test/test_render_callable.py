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


def test_render_matches_cli_subprocess(tmp_home, monkeypatch):
    import os
    # tmp_home patches both HOME and CLAUDE_DIR for the in-process render; the
    # subprocess must read the same (empty) CLAUDE_DIR or its token/cost/sparkline
    # rows diverge from the real ~/.claude logs. The CLI caps width at MAX_WIDTH
    # (raw_tw - 6), so feed COLUMNS = MAX_WIDTH + 6 and render the API at the cap.
    claude_dir = tmp_home / '.claude'

    info = _load_example()

    proc = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        input=json.dumps(info),
        capture_output=True,
        text=True,
        env={
            **os.environ,
            'COLUMNS':           str(sl.MAX_WIDTH + 6),
            'HOME':              str(tmp_home),
            'CLAUDE_CONFIG_DIR': str(claude_dir),
        },
    )
    result_cli = proc.stdout

    result_api = sl.render(info, sl.MAX_WIDTH)

    assert result_api == result_cli.rstrip('\n')
