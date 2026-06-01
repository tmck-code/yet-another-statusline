import yas.renderer as renderer
from yas.constants import CLR_ALERT
from yas.session import ContextWindow
from yas.render.text import _visible_width

Renderer = renderer.Renderer


def test_context_line_under_soft_limit() -> None:
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


def test_context_line_over_soft_limit() -> None:
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


def test_context_line_compact_respects_available() -> None:
    r = Renderer()
    ctx = ContextWindow(
        total_input_tokens=10_000,
        total_output_tokens=5_000,
    )
    available = 30
    out = r.context_line_compact(ctx, available)
    assert _visible_width(out) <= available
