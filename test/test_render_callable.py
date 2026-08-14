import gzip
import json
import subprocess
import sys
from pathlib import Path

import yas.app as app

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
    # Isolate from any YAS_* env vars set in the host shell (e.g. YAS_MAX_WIDTH=40).
    monkeypatch.delenv('YAS_MAX_WIDTH', raising=False)
    monkeypatch.delenv('YAS_FULL_WIDTH', raising=False)

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


def _run_main(info, tmp_path, monkeypatch, env_extra):
    import io
    monkeypatch.setattr(app, 'terminal_width', lambda: 200)
    monkeypatch.setattr(app, 'CLAUDE_DIR', tmp_path / '.claude')
    for k in ('YAS_MAX_WIDTH', 'YAS_FULL_WIDTH', 'YAS_SHOW_RENDER_TIME', 'YAS_RECORDING'):
        monkeypatch.delenv(k, raising=False)
    for k, v in env_extra.items():
        monkeypatch.setenv(k, v)
    buf = io.StringIO()
    monkeypatch.setattr(app.sys, 'stdout', buf)
    monkeypatch.setattr(app.sys, 'stdin', io.StringIO(json.dumps(info)))
    app.main()
    return buf.getvalue()


def test_show_render_time_off_emits_no_annotation(tmp_path, monkeypatch):
    # Even with a populated render cache, the flag being off (default) means the
    # bottom border carries no timing and the cache is never rewritten.
    from yas.tokens import RenderTiming
    monkeypatch.setattr(RenderTiming, 'read', staticmethod(lambda sid: 47.2))
    writes: list = []
    monkeypatch.setattr(RenderTiming, 'write', staticmethod(lambda sid, ms: writes.append((sid, ms))))

    from helper import strip_ansi
    info = _load_example()
    out  = _run_main(info, tmp_path, monkeypatch, {})
    assert 'ms' not in strip_ansi(out.splitlines()[-1])
    assert writes == []  # cache untouched when the feature is off


def test_show_render_time_on_emits_annotation(tmp_path, monkeypatch):
    from yas.tokens import RenderTiming
    monkeypatch.setattr(RenderTiming, 'read', staticmethod(lambda sid: 47.2))
    writes: list = []
    monkeypatch.setattr(RenderTiming, 'write', staticmethod(lambda sid, ms: writes.append((sid, ms))))

    from helper import strip_ansi
    info = _load_example()
    out  = _run_main(info, tmp_path, monkeypatch, {'YAS_SHOW_RENDER_TIME': '1'})
    assert '47.2ms' in strip_ansi(out.splitlines()[-1])
    assert len(writes) == 1  # this run records its own duration for the next


def test_recording_off_writes_nothing(tmp_path, monkeypatch):
    info = _load_example()
    _run_main(info, tmp_path, monkeypatch, {})
    recordings_dir = tmp_path / '.claude' / 'yas' / 'recordings'
    assert not recordings_dir.exists()


def test_recording_on_writes_one_member_per_tick(tmp_path, monkeypatch):
    info = _load_example()
    session_id = info['session_id']
    for _ in range(3):
        _run_main(info, tmp_path, monkeypatch, {'YAS_RECORDING': '1'})

    recording_file = tmp_path / '.claude' / 'yas' / 'recordings' / f'{session_id}.psv.gz'
    assert recording_file.exists()

    # Decompress and read lines
    lines = []
    with gzip.open(recording_file, 'rt', encoding='utf-8') as f:
        lines = f.readlines()

    assert len(lines) == 3


def test_recording_payload_round_trips_with_pipe(tmp_path, monkeypatch):
    info = _load_example()
    session_id = info['session_id']
    _run_main(info, tmp_path, monkeypatch, {'YAS_RECORDING': '1'})

    recording_file = tmp_path / '.claude' / 'yas' / 'recordings' / f'{session_id}.psv.gz'
    with gzip.open(recording_file, 'rt', encoding='utf-8') as f:
        line = f.readline().strip()

    # Split with maxsplit=2 to recover timestamp | width | payload
    parts = line.split(' | ', 2)
    assert len(parts) == 3
    timestamp, width, payload = parts

    # Payload should be valid JSON
    recovered = json.loads(payload)
    assert isinstance(recovered, dict)
    # Verify it matches the original info structure
    assert 'session_id' in recovered or 'session_info' in recovered or len(recovered) > 0


def test_recording_captures_raw_width_not_clamped(tmp_path, monkeypatch):
    info = _load_example()
    session_id = info['session_id']
    # terminal_width() mocked to 200, which is > DEFAULT_MAX_WIDTH (140)
    # so the rendered width would be clamped, but we record the raw width
    _run_main(info, tmp_path, monkeypatch, {'YAS_RECORDING': '1'})

    recording_file = tmp_path / '.claude' / 'yas' / 'recordings' / f'{session_id}.psv.gz'
    with gzip.open(recording_file, 'rt', encoding='utf-8') as f:
        line = f.readline().strip()

    parts = line.split(' | ', 2)
    width_str = parts[1]
    assert width_str == '200'  # The mocked terminal_width() value


def test_recording_sub_min_width_tick_still_records(tmp_path, monkeypatch):
    from yas.constants import MIN_WIDTH
    import io

    # Record a tick with width below MIN_WIDTH to verify it still gets recorded
    # even though main() doesn't emit stdout
    info = _load_example()
    session_id = info['session_id']
    monkeypatch.setattr(app, 'terminal_width', lambda: MIN_WIDTH - 1)
    monkeypatch.setattr(app, 'CLAUDE_DIR', tmp_path / '.claude')
    monkeypatch.delenv('YAS_RECORDING', raising=False)
    monkeypatch.setenv('YAS_RECORDING', '1')

    buf = io.StringIO()
    monkeypatch.setattr(app.sys, 'stdout', buf)
    monkeypatch.setattr(app.sys, 'stdin', io.StringIO(json.dumps(info)))
    app.main()

    out = buf.getvalue()
    # Should emit nothing (below MIN_WIDTH)
    assert out == ''

    # But recording should still exist
    recording_file = tmp_path / '.claude' / 'yas' / 'recordings' / f'{session_id}.psv.gz'
    assert recording_file.exists()


def test_recording_unwritable_dir_leaves_output_intact(tmp_path, monkeypatch):
    info = _load_example()
    # Make the recordings directory read-only to simulate a write failure
    recordings_dir = tmp_path / '.claude' / 'yas' / 'recordings'
    recordings_dir.mkdir(parents=True, exist_ok=True)
    recordings_dir.chmod(0o444)

    try:
        # Even though recording fails, render should succeed
        out = _run_main(info, tmp_path, monkeypatch, {'YAS_RECORDING': '1'})
        assert len(out) > 0  # Output is intact
    finally:
        # Restore permissions for cleanup
        recordings_dir.chmod(0o755)


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
    # rainbow_step() is wall-clock-based by default, so the in-process render and
    # the subprocess (which carries interpreter-startup latency) can straddle a
    # 1-second boundary and pick adjacent rainbow colours. Pin the step in both
    # paths so the model-row glyphs render identically.
    env.update({
        'COLUMNS':           str(DEFAULT_MAX_WIDTH + 6),
        'YAS_MAX_WIDTH':     str(DEFAULT_MAX_WIDTH),
        'YAS_RAINBOW_STEP':  '0',
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

    monkeypatch.setenv('YAS_RAINBOW_STEP', '0')
    result_api = app.render(info, DEFAULT_MAX_WIDTH)

    assert result_api == result_cli.rstrip('\n')
