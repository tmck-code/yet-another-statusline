import statusline_command as sl
from conftest import strip_ansi

_visible_width = sl._visible_width
Renderer = sl.Renderer
RateLimits = sl.RateLimits
RateBucket = sl.RateBucket


def test_model_section_no_seven_day_suffix():
    r = Renderer()
    out = r.model_section('Sonnet 4.6', '', RateLimits())
    stripped = strip_ansi(out)
    assert '7d:' not in stripped


def test_model_section_seven_day_appears_when_used():
    r = Renderer()
    rate = RateLimits(seven_day=RateBucket(used_percentage=12.5))
    out = r.model_section('Sonnet 4.6', '', rate)
    stripped = strip_ansi(out)
    assert '7d:' in stripped
    assert '12.5%' in stripped


def test_model_section_compact_respects_max_width():
    r = Renderer()
    out = r.model_section_compact('A' * 100, RateLimits(), max_width=30)
    assert _visible_width(out) <= 30
    assert '…' in strip_ansi(out)
