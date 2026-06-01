from typing import Any

import pytest

import yas.session as session



_FROM_DICT_CASES = [
    ('Model',        session.Model,        session.Model()),
    ('OutputStyle',  session.OutputStyle,  session.OutputStyle()),
    ('Effort',       session.Effort,       session.Effort()),
    ('Thinking',     session.Thinking,     session.Thinking()),
    ('CurrentUsage', session.CurrentUsage, session.CurrentUsage()),
    ('RateBucket',   session.RateBucket,   session.RateBucket()),
    ('Workspace',    session.Workspace,    session.Workspace()),
    ('Cost',         session.Cost,         session.Cost()),
    ('ContextWindow',session.ContextWindow,session.ContextWindow()),
    ('RateLimits',   session.RateLimits,   session.RateLimits()),
    ('SessionInfo',  session.SessionInfo,  session.SessionInfo()),
]


@pytest.mark.parametrize('name,cls,default', _FROM_DICT_CASES, ids=[c[0] for c in _FROM_DICT_CASES])
def test_from_dict_empty_yields_defaults(name: str, cls: Any, default: object) -> None:
    assert cls.from_dict({}) == default



def test_session_info_ignores_unknown_key() -> None:
    result = session.SessionInfo.from_dict({'experimental_field': 'x'})
    assert result == session.SessionInfo()



def test_context_window_missing_current_usage() -> None:
    result = session.ContextWindow.from_dict({'used_percentage': 8})
    assert result.current_usage == session.CurrentUsage()
    assert result.used_percentage == 8



def test_rate_bucket_rounds_used_percentage() -> None:
    result = session.RateBucket.from_dict({'used_percentage': 12.3456, 'resets_at': 1700000000})
    assert result == session.RateBucket(used_percentage=12.35, resets_at=1700000000)



def test_session_info_recursive_population() -> None:
    payload = {
        'session_id': 'abc123',
        'model': {'id': 'claude-sonnet-4-6', 'display_name': 'Sonnet'},
        'workspace': {'current_dir': '/tmp', 'project_dir': '/tmp', 'added_dirs': []},
        'cost': {'total_cost_usd': 1.23, 'total_duration_ms': 500},
        'context_window': {
            'used_percentage': 42.0,
            'current_usage': {
                'input_tokens': 100,
                'output_tokens': 50,
                'cache_creation_input_tokens': 10,
                'cache_read_input_tokens': 5,
            },
        },
        'rate_limits': {
            'five_hour': {'used_percentage': 33.0, 'resets_at': 1700000001},
            'seven_day': {'used_percentage': 10.5, 'resets_at': 1700000002},
        },
    }

    result = session.SessionInfo.from_dict(payload)

    assert result.model == session.Model(id='claude-sonnet-4-6', display_name='Sonnet')
    assert result.workspace.current_dir == '/tmp'
    assert result.cost.total_cost_usd == pytest.approx(1.23)
    assert result.context_window.current_usage == session.CurrentUsage(
        input_tokens=100,
        output_tokens=50,
        cache_creation_input_tokens=10,
        cache_read_input_tokens=5,
    )
    assert result.rate_limits.five_hour == session.RateBucket(used_percentage=33.0, resets_at=1700000001)
    assert result.rate_limits.seven_day == session.RateBucket(used_percentage=10.5, resets_at=1700000002)
