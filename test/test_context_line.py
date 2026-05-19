import statusline_command as sl
from conftest import strip_ansi

_visible_width = sl._visible_width
Renderer = sl.Renderer
ContextWindow = sl.ContextWindow
CLR_ALERT = sl.CLR_ALERT
SOFT_LIMIT = sl.SOFT_LIMIT


def test_context_line_under_soft_limit():
    r = Renderer()
    ctx = ContextWindow(
        total_input_tokens=10_000,
        total_output_tokens=5_000,
        context_window_size=200_000,
    )
    available = 76
    out = r.context_line(ctx, available)
    assert _visible_width(out) <= available
    assert CLR_ALERT not in out


def test_context_line_over_soft_limit():
    r = Renderer()
    ctx = ContextWindow(
        total_input_tokens=200_000,
        total_output_tokens=0,
        context_window_size=200_000,
    )
    available = 76
    out = r.context_line(ctx, available)
    assert CLR_ALERT in out
    assert _visible_width(out) <= available


def test_context_line_compact_respects_available():
    r = Renderer()
    ctx = ContextWindow(
        total_input_tokens=10_000,
        total_output_tokens=5_000,
    )
    available = 30
    out = r.context_line_compact(ctx, available)
    assert _visible_width(out) <= available
