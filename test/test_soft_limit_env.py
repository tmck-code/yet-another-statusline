import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_SRC = Path(__file__).resolve().parent.parent / 'claude' / 'statusline_command.py'


def _fresh_load() -> ModuleType:
    sys.modules.pop('statusline_command', None)
    spec = importlib.util.spec_from_file_location('statusline_command', _SRC)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules['statusline_command'] = mod
    spec.loader.exec_module(mod)
    return mod


def test_soft_limit_defaults_to_150k(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('YAS_SOFT_LIMIT', raising=False)
    sl = _fresh_load()
    assert sl.SOFT_LIMIT == 150_000


def test_soft_limit_env_override_1m(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('YAS_SOFT_LIMIT', '1000000')
    sl = _fresh_load()
    assert sl.SOFT_LIMIT == 1_000_000


def test_soft_limit_env_empty_string_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('YAS_SOFT_LIMIT', '')
    sl = _fresh_load()
    assert sl.SOFT_LIMIT == 150_000


def teardown_module() -> None:
    _fresh_load()
