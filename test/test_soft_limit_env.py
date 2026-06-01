import pytest

import yas.config as config


def test_soft_limit_defaults_to_150k(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('YAS_SOFT_LIMIT', raising=False)
    cfg = config.Config.load(env={})
    assert cfg.soft_limit == 150_000


def test_soft_limit_env_override_1m(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = config.Config.load(env={'YAS_SOFT_LIMIT': '1000000'})
    assert cfg.soft_limit == 1_000_000


def test_soft_limit_env_empty_string_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = config.Config.load(env={'YAS_SOFT_LIMIT': ''})
    assert cfg.soft_limit == 150_000
