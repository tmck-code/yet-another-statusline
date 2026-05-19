import re
import pytest
import statusline_command as sl


_r = sl.Renderer()


# ---------------------------------------------------------------------------
# 5.2  gradient_rgb(0.0) → (40, 210, 80)
# ---------------------------------------------------------------------------

def test_gradient_rgb_at_zero():
    assert _r.gradient_rgb(0.0) == (40, 210, 80)


# ---------------------------------------------------------------------------
# 5.3  gradient_rgb(1.0) and gradient_rgb(1.5) both clamp to (210, 20, 50)
# ---------------------------------------------------------------------------

def test_gradient_rgb_at_one():
    assert _r.gradient_rgb(1.0) == (210, 20, 50)


def test_gradient_rgb_clamps_above_one():
    assert _r.gradient_rgb(1.5) == (210, 20, 50)


# ---------------------------------------------------------------------------
# 5.4  gradient_rgb(0.0, dim=0.5) → (20, 105, 40)
# ---------------------------------------------------------------------------

def test_gradient_rgb_dim():
    # int(40 * 0.5)=20, int(210 * 0.5)=105, int(80 * 0.5)=40
    assert _r.gradient_rgb(0.0, dim=0.5) == (20, 105, 40)


# ---------------------------------------------------------------------------
# 5.5  gradient_color(0.5) starts with '\033[38;2;' and round-trips via gradient_rgb
# ---------------------------------------------------------------------------

def test_gradient_color_format():
    color = _r.gradient_color(0.5)
    assert color.startswith('\033[38;2;')


def test_gradient_color_round_trips_rgb():
    color = _r.gradient_color(0.5)
    # parse \033[38;2;r;g;bm
    m = re.match(r'\x1b\[38;2;(\d+);(\d+);(\d+)m', color)
    assert m is not None, f'ANSI escape not parsed: {color!r}'
    parsed = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    assert parsed == _r.gradient_rgb(0.5)


# ---------------------------------------------------------------------------
# 5.6  grad_at(0, width=10, fill=1.0) == gradient_color(0.0)
# ---------------------------------------------------------------------------

def test_grad_at_start_of_full_bar():
    # col=0, width=10 → t=0/9=0.0; fill=1.0; t <= fill-FADE=0.94 → gradient_color(0.0)
    assert _r.grad_at(0, width=10, fill=1.0) == _r.gradient_color(0.0)


# ---------------------------------------------------------------------------
# 5.7  grad_at(9, width=10, fill=0.0) → CLR_BORDER_OFF
# ---------------------------------------------------------------------------

def test_grad_at_past_zero_fill():
    # fill=0.0 → fill <= 0 → CLR_BORDER_OFF immediately
    assert _r.grad_at(9, width=10, fill=0.0) == sl.CLR_BORDER_OFF
