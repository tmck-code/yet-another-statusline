import json
import subprocess
import sys
from pathlib import Path

import statusline_command as sl
import yas.app as app
import yas.render.text as _text_mod
import yas.constants as _const_mod

_EXAMPLE = Path(__file__).resolve().parent.parent / 'ops' / 'session-info-example.json'
_SCRIPT  = Path(__file__).resolve().parent.parent / 'claude' / 'statusline_command.py'


def _load_example() -> dict:
    return json.loads(_EXAMPLE.read_text())


def test_render_returns_nonempty():
    info   = _load_example()
    result = app.render(info, 160)
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
    result = app.render(info, 160)
    assert len(result) > 0


def test_render_different_widths_produce_different_layouts():
    info    = _load_example()
    narrow  = app.render(info, 50)
    wide    = app.render(info, 160)
    assert narrow != wide


def test_yas_full_width_fills_terminal(tmp_path, monkeypatch, capsys):
    import io
    info    = _load_example()
    fake_tw = 200  # wider than DEFAULT_MAX_WIDTH so capping is observable

    monkeypatch.setattr(app, 'terminal_width', lambda: fake_tw)
    monkeypatch.setattr(app, 'CLAUDE_DIR', tmp_path / '.claude')

    def _first_line_width(env_extra):
        for k, v in env_extra.items():
            monkeypatch.setenv(k, v)
        buf = io.StringIO()
        monkeypatch.setattr(app.sys, 'stdout', buf)
        monkeypatch.setattr(app.sys, 'stdin', io.StringIO(json.dumps(info)))
        app.main()
        out = buf.getvalue()
        monkeypatch.delenv('YAS_FULL_WIDTH', raising=False)
        first_line = out.splitlines()[0] if out else ''
        from yas.render.text import _visible_width
        return _visible_width(first_line)

    from yas.constants import DEFAULT_MAX_WIDTH
    max_width = DEFAULT_MAX_WIDTH

    uncapped_w = _first_line_width({'YAS_FULL_WIDTH': '1'})
    default_w  = _first_line_width({})

    assert uncapped_w == fake_tw - 6, f'YAS_FULL_WIDTH: expected {fake_tw-6}, got {uncapped_w}'
    assert default_w  == max_width,   f'default: expected {max_width}, got {default_w}'


def test_render_matches_cli_subprocess(tmp_home, monkeypatch):
    import os
    from yas.constants import DEFAULT_MAX_WIDTH

    # tmp_home patches both HOME and CLAUDE_DIR for the in-process render; the
    # subprocess must read the same (empty) CLAUDE_DIR or its token/cost/sparkline
    # rows diverge from the real ~/.claude logs. The CLI caps width at DEFAULT_MAX_WIDTH
    # (raw_tw - 6), so feed COLUMNS = DEFAULT_MAX_WIDTH + 6 and render the API at the cap.
    claude_dir = tmp_home / '.claude'

    info = _load_example()

    # Build an env the subprocess can't escape the sandbox through. Inheriting
    # os.environ wholesale lets the host leak in:
    #   - TMUX_PANE / TMUX make terminal_width() query the real tmux pane and
    #     ignore COLUMNS, so the subprocess renders at the pane width, not DEFAULT_MAX_WIDTH.
    #   - YAS_FULL_WIDTH switches main() to the uncapped (raw_tw - 6) branch.
    # Strip both so the subprocess deterministically caps at DEFAULT_MAX_WIDTH via COLUMNS,
    # and pin YAS_MAX_WIDTH to DEFAULT_MAX_WIDTH so the cap matches exactly.
    env = {k: v for k, v in os.environ.items()
           if k not in ('TMUX_PANE', 'TMUX', 'YAS_FULL_WIDTH')}
    env.update({
        'COLUMNS':           str(DEFAULT_MAX_WIDTH + 6),
        'YAS_MAX_WIDTH':     str(DEFAULT_MAX_WIDTH),
        'HOME':              str(tmp_home),
        'CLAUDE_CONFIG_DIR': str(claude_dir),
    })

    proc = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        input=json.dumps(info),
        capture_output=True,
        text=True,
        env=env,
    )
    result_cli = proc.stdout

    result_api = app.render(info, DEFAULT_MAX_WIDTH)

    assert result_api == result_cli.rstrip('\n')
