import re
import statusline_command as sl
from conftest import strip_ansi


_r = sl.Renderer()


# ---------------------------------------------------------------------------
# 6.2  Empty history → empty string
# ---------------------------------------------------------------------------

def test_sparkline_empty():
    assert _r.sparkline([]) == ''


# ---------------------------------------------------------------------------
# 6.3  All-zero history → spaces of the same length after ANSI strip
# ---------------------------------------------------------------------------

def test_sparkline_all_zeros():
    result = _r.sparkline([0, 0, 0])
    stripped = strip_ansi(result)
    assert stripped == '   '


# ---------------------------------------------------------------------------
# 6.4  [1, 2, 100] → third char is '█' after ANSI strip
# ---------------------------------------------------------------------------

def test_sparkline_peak_at_third():
    result = _r.sparkline([1, 2, 100])
    stripped = strip_ansi(result)
    assert len(stripped) == 3
    assert stripped[2] == '█'
