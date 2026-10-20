import io
import json
from pathlib import Path

import yas.app as app
import yas.constants as constants
from helper import strip_ansi
from yas.config import Config
from yas.info import SessionView
from yas.info.git import GitInfo
from yas.info.subagents import RunningSubagents
from yas.session import SessionInfo

_EXAMPLE = Path(__file__).resolve().parent.parent / 'ops' / 'session-info-example.json'


def _info() -> dict:
    return json.loads(_EXAMPLE.read_text())


def _run_main(tmp_home, monkeypatch, capsys) -> tuple[str, str]:
    monkeypatch.setattr(app, 'terminal_width', lambda: 200)
    for k in ('YAS_MAX_WIDTH', 'YAS_FULL_WIDTH', 'YAS_SHOW_RENDER_TIME'):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(app.sys, 'stdin', io.StringIO(json.dumps(_info())))
    app.main()
    captured = capsys.readouterr()
    return captured.out, captured.err


def _boom(*a, **kw):
    raise KeyError('stale cache entry')


def test_failing_subagents_gather_falls_back_to_empty_and_marks(tmp_home, monkeypatch, capsys):
    monkeypatch.setattr(RunningSubagents, 'from_session', classmethod(_boom))
    out, err = _run_main(tmp_home, monkeypatch, capsys)
    text = strip_ansi(out)
    assert 'skipped subagents' in text
    assert 'Traceback' not in out + err
    assert len(out.splitlines()) > 3  # rest of the statusline still renders
    log = constants.errors_log().read_text()
    assert 'subagents KeyError' in log and 'Traceback' in log


def test_failing_git_gather_falls_back_to_empty_and_marks(tmp_home, monkeypatch, capsys):
    monkeypatch.setattr(GitInfo, 'from_cwd', classmethod(_boom))
    out, _ = _run_main(tmp_home, monkeypatch, capsys)
    assert 'skipped git' in strip_ansi(out)
    assert 'git KeyError' in constants.errors_log().read_text()


def test_guarded_view_field_returns_empty_value_and_records_name(tmp_home, monkeypatch):
    monkeypatch.setattr(RunningSubagents, 'from_session', classmethod(_boom))
    view = SessionView(SessionInfo.from_dict(_info()), Config())
    assert view.subagents.subagents == []
    assert view.failed == ['subagents']


def test_minimal_view_skips_every_optional_gather(monkeypatch):
    monkeypatch.setattr(RunningSubagents, 'from_session', classmethod(_boom))
    view = SessionView(SessionInfo.from_dict(_info()), Config(), minimal=True)
    assert view.subagents.subagents == []
    assert view.failed == []


def test_builder_failure_retries_without_optional_sections(tmp_home, monkeypatch, capsys):
    real  = app.build_wide
    calls = []

    def flaky(view, *a, **kw):
        calls.append(view.minimal)
        if not view.minimal:
            raise ValueError('bad section')
        return real(view, *a, **kw)

    monkeypatch.setattr(app, 'build_wide', flaky)
    out, err = _run_main(tmp_home, monkeypatch, capsys)
    assert calls == [False, True]
    assert 'skipped optional sections' in strip_ansi(out)
    assert 'Traceback' not in out + err
    assert 'render ValueError: bad section' in constants.errors_log().read_text()


def test_both_renders_failing_prints_single_fallback_line(tmp_home, monkeypatch, capsys):
    monkeypatch.setattr(app, 'build_wide', lambda *a, **kw: _boom())
    out, err = _run_main(tmp_home, monkeypatch, capsys)
    info = _info()
    assert '\n' not in out
    assert out.endswith('yas: render error')
    assert info['model']['display_name'] in out
    assert Path(info['cwd']).name in out
    assert 'Traceback' not in err
    assert 'render-retry' in constants.errors_log().read_text()


def test_fallback_line_without_model_or_cwd():
    assert app.fallback_line({}) == 'yas: render error'


def test_normal_render_has_no_marker_and_writes_no_error_log(tmp_home, monkeypatch, capsys):
    out, _ = _run_main(tmp_home, monkeypatch, capsys)
    assert 'skipped' not in strip_ansi(out)
    assert not constants.errors_log().exists()


def test_errors_log_stays_bounded(tmp_home, monkeypatch):
    from yas.guard import record_failure
    monkeypatch.setattr(constants, 'ERRORS_LOG_MAX_BYTES', 2000)
    import yas.guard as guard
    monkeypatch.setattr(guard, 'ERRORS_LOG_MAX_BYTES', 2000)
    for i in range(40):
        record_failure(f'sec{i}', ValueError('x' * 50))
    text = constants.errors_log().read_text()
    assert len(text) <= 2000 + 1500  # at most one entry over the cap
    assert text.startswith(constants.ERRORS_LOG_ENTRY_MARK)
    assert 'sec39' in text and 'sec0 ' not in text
