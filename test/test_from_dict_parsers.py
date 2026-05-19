import pytest
import statusline_command as sl


# ---------------------------------------------------------------------------
# 2.2  Parametrised: from_dict({}) returns all-default instance
# ---------------------------------------------------------------------------

_FROM_DICT_CASES = [
    ('Model',        sl.Model,        sl.Model()),
    ('OutputStyle',  sl.OutputStyle,  sl.OutputStyle()),
    ('Effort',       sl.Effort,       sl.Effort()),
    ('Thinking',     sl.Thinking,     sl.Thinking()),
    ('CurrentUsage', sl.CurrentUsage, sl.CurrentUsage()),
    ('RateBucket',   sl.RateBucket,   sl.RateBucket()),
    ('Workspace',    sl.Workspace,    sl.Workspace()),
    ('Cost',         sl.Cost,         sl.Cost()),
    ('ContextWindow',sl.ContextWindow,sl.ContextWindow()),
    ('RateLimits',   sl.RateLimits,   sl.RateLimits()),
    ('SessionInfo',  sl.SessionInfo,  sl.SessionInfo()),
]


@pytest.mark.parametrize('name,cls,default', _FROM_DICT_CASES, ids=[c[0] for c in _FROM_DICT_CASES])
def test_from_dict_empty_yields_defaults(name, cls, default):
    assert cls.from_dict({}) == default


# ---------------------------------------------------------------------------
# 2.3  Unknown key is silently ignored
# ---------------------------------------------------------------------------

def test_session_info_ignores_unknown_key():
    result = sl.SessionInfo.from_dict({'experimental_field': 'x'})
    assert result == sl.SessionInfo()


# ---------------------------------------------------------------------------
# 2.4  ContextWindow: missing current_usage → default CurrentUsage
# ---------------------------------------------------------------------------

def test_context_window_missing_current_usage():
    result = sl.ContextWindow.from_dict({'used_percentage': 8})
    assert result.current_usage == sl.CurrentUsage()
    assert result.used_percentage == 8


# ---------------------------------------------------------------------------
# 2.5  RateBucket: used_percentage is rounded to two decimal places
# ---------------------------------------------------------------------------

def test_rate_bucket_rounds_used_percentage():
    result = sl.RateBucket.from_dict({'used_percentage': 12.3456, 'resets_at': 1700000000})
    assert result == sl.RateBucket(used_percentage=12.35, resets_at=1700000000)


# ---------------------------------------------------------------------------
# 2.6  SessionInfo.from_dict recursively populates nested objects
# ---------------------------------------------------------------------------

def test_session_info_recursive_population():
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

    result = sl.SessionInfo.from_dict(payload)

    assert result.model == sl.Model(id='claude-sonnet-4-6', display_name='Sonnet')
    assert result.workspace.current_dir == '/tmp'
    assert result.cost.total_cost_usd == pytest.approx(1.23)
    assert result.context_window.current_usage == sl.CurrentUsage(
        input_tokens=100,
        output_tokens=50,
        cache_creation_input_tokens=10,
        cache_read_input_tokens=5,
    )
    assert result.rate_limits.five_hour == sl.RateBucket(used_percentage=33.0, resets_at=1700000001)
    assert result.rate_limits.seven_day == sl.RateBucket(used_percentage=10.5, resets_at=1700000002)
