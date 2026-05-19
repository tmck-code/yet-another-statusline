import statusline_command as sl


# ---------------------------------------------------------------------------
# 3.1  SessionInfo.short_pwd
# ---------------------------------------------------------------------------

class TestShortPwd:
    def test_home_prefix_collapsed(self, tmp_home, monkeypatch):
        monkeypatch.setattr(sl, 'HOME', tmp_home)
        info = sl.SessionInfo(cwd=str(tmp_home) + '/dev/proj/sub')
        assert info.short_pwd == '~/d/p/sub'

    def test_absolute_non_home(self, tmp_home, monkeypatch):
        monkeypatch.setattr(sl, 'HOME', tmp_home)
        info = sl.SessionInfo(cwd='/etc/systemd/network')
        assert info.short_pwd == '/e/s/network'

    def test_bare_home(self, tmp_home, monkeypatch):
        monkeypatch.setattr(sl, 'HOME', tmp_home)
        info = sl.SessionInfo(cwd=str(tmp_home))
        assert info.short_pwd == '~'

    def test_root_path(self, tmp_home, monkeypatch):
        monkeypatch.setattr(sl, 'HOME', tmp_home)
        info = sl.SessionInfo(cwd='/')
        assert info.short_pwd == '/'


# ---------------------------------------------------------------------------
# 3.2  SessionInfo.model_name
# ---------------------------------------------------------------------------

class TestModelName:
    def test_display_name_preferred(self):
        info = sl.SessionInfo(model=sl.Model(id='claude-sonnet-4-6', display_name='Sonnet 4.6'))
        assert info.model_name == 'Sonnet 4.6'

    def test_falls_back_to_id(self):
        info = sl.SessionInfo(model=sl.Model(id='claude-sonnet-4-6', display_name=''))
        assert info.model_name == 'claude-sonnet-4-6'

    def test_falls_back_to_unknown(self):
        info = sl.SessionInfo(model=sl.Model(id='', display_name=''))
        assert info.model_name == 'unknown'


# ---------------------------------------------------------------------------
# 3.3  SessionInfo.model_thinking
# ---------------------------------------------------------------------------

class TestModelThinking:
    def test_returns_effort_when_thinking_enabled_and_level_set(self):
        info = sl.SessionInfo(
            thinking=sl.Thinking(enabled=True),
            effort=sl.Effort(level='high'),
        )
        assert info.model_thinking == 'high'

    def test_empty_when_thinking_disabled(self):
        info = sl.SessionInfo(
            thinking=sl.Thinking(enabled=False),
            effort=sl.Effort(level='high'),
        )
        assert info.model_thinking == ''

    def test_empty_when_level_empty(self):
        info = sl.SessionInfo(
            thinking=sl.Thinking(enabled=True),
            effort=sl.Effort(level=''),
        )
        assert info.model_thinking == ''

    def test_empty_when_both_disabled_and_level_empty(self):
        info = sl.SessionInfo(
            thinking=sl.Thinking(enabled=False),
            effort=sl.Effort(level=''),
        )
        assert info.model_thinking == ''
