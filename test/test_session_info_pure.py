from pathlib import Path

import pytest

import statusline_command as sl
import yas.session as session



class TestShortPwd:
    def test_home_prefix_collapsed(self, tmp_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(session, 'HOME', tmp_home)
        info = session.SessionInfo(cwd=str(tmp_home) + '/dev/proj/sub')
        assert info.short_pwd == '~/d/p/sub'

    def test_absolute_non_home(self, tmp_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(session, 'HOME', tmp_home)
        info = session.SessionInfo(cwd='/etc/systemd/network')
        assert info.short_pwd == '/e/s/network'

    def test_bare_home(self, tmp_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(session, 'HOME', tmp_home)
        info = session.SessionInfo(cwd=str(tmp_home))
        assert info.short_pwd == '~'

    def test_root_path(self, tmp_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(session, 'HOME', tmp_home)
        info = session.SessionInfo(cwd='/')
        assert info.short_pwd == '/'



class TestModelName:
    def test_display_name_preferred(self) -> None:
        info = session.SessionInfo(model=session.Model(id='claude-sonnet-4-6', display_name='Sonnet 4.6'))
        assert info.model_name == 'Sonnet 4.6'

    def test_falls_back_to_id(self) -> None:
        info = session.SessionInfo(model=session.Model(id='claude-sonnet-4-6', display_name=''))
        assert info.model_name == 'claude-sonnet-4-6'

    def test_falls_back_to_unknown(self) -> None:
        info = session.SessionInfo(model=session.Model(id='', display_name=''))
        assert info.model_name == 'unknown'



class TestModelThinking:
    def test_returns_effort_when_thinking_enabled_and_level_set(self) -> None:
        info = session.SessionInfo(
            thinking=session.Thinking(enabled=True),
            effort=session.Effort(level='high'),
        )
        assert info.model_thinking == 'high'

    def test_empty_when_thinking_disabled(self) -> None:
        info = session.SessionInfo(
            thinking=session.Thinking(enabled=False),
            effort=session.Effort(level='high'),
        )
        assert info.model_thinking == ''

    def test_empty_when_level_empty(self) -> None:
        info = session.SessionInfo(
            thinking=session.Thinking(enabled=True),
            effort=session.Effort(level=''),
        )
        assert info.model_thinking == ''

    def test_empty_when_both_disabled_and_level_empty(self) -> None:
        info = session.SessionInfo(
            thinking=session.Thinking(enabled=False),
            effort=session.Effort(level=''),
        )
        assert info.model_thinking == ''
