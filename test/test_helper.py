from datetime import datetime, timezone

import statusline_command as sl
from conftest import strip_ansi

_visible_width = sl._visible_width
Renderer = sl.Renderer
RateBucket = sl.RateBucket


def test_helper_no_usage_no_reset():
    r = Renderer()
    out = r.helper(RateBucket())
    assert out == '∞'


def test_helper_used_no_reset():
    r = Renderer()
    out = r.helper(RateBucket(used_percentage=10.0, resets_at=0))
    stripped = strip_ansi(out)
    assert stripped.endswith('∞')
    assert '10.0%' in stripped


def test_helper_reset_in_future(monkeypatch):
    fixed_now = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)

    class _FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is not None:
                return fixed_now.astimezone(tz)
            return fixed_now

    monkeypatch.setattr(sl, 'datetime', _FakeDatetime)

    future_ts = int(fixed_now.timestamp()) + 3600
    r = Renderer()
    out = r.helper(RateBucket(used_percentage=50.0, resets_at=future_ts))
    stripped = strip_ansi(out)
    assert '50.0%' in stripped
    assert 'T-' in stripped
