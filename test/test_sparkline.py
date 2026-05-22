import statusline_command as sl
from conftest import strip_ansi


_r = sl.Renderer()


# ---------------------------------------------------------------------------
# 6.2  Empty history -> ('', '')
# ---------------------------------------------------------------------------

def test_sparkline_empty() -> None:
    assert _r.sparkline([]) == ('', '')


# ---------------------------------------------------------------------------
# 6.3  All-zero history -> bottom row all '▁' stubs, top row all spaces
# ---------------------------------------------------------------------------

def test_sparkline_all_zeros() -> None:
    top, bot = _r.sparkline([0, 0, 0])
    assert strip_ansi(top) == '   '
    assert strip_ansi(bot) == '▁▁▁'


# ---------------------------------------------------------------------------
# 6.4  [1, 2, 100] -> third column tops out at idx 16 ('█', '█')
# ---------------------------------------------------------------------------

def test_sparkline_peak_at_third() -> None:
    top, bot = _r.sparkline([1, 2, 100])
    s_top = strip_ansi(top)
    s_bot = strip_ansi(bot)
    assert len(s_top) == 3
    assert len(s_bot) == 3
    assert s_top[2] == '█'
    assert s_bot[2] == '█'


# ---------------------------------------------------------------------------
# 16-level encoding boundary table
# ---------------------------------------------------------------------------

def _encode_single(ratio_num: int, ratio_den: int) -> tuple[str, str]:
    # craft a history of two values so that h[1]/max = ratio_num/ratio_den
    top, bot = _r.sparkline([ratio_den, ratio_num])
    return strip_ansi(top)[1], strip_ansi(bot)[1]


def test_sparkline_idx_0_stub() -> None:
    assert _encode_single(0, 100) == (' ', '▁')


def test_sparkline_idx_8_bottom_full() -> None:
    # ratio = 8/16 = 0.5 -> idx 8 -> ( ' ', SPARK_CHARS[7] = '█' )
    assert _encode_single(8, 16) == (' ', '█')


def test_sparkline_idx_9_just_into_top() -> None:
    # ratio = 9/16 -> idx 9 -> ( SPARK_CHARS[0] = '▁', '█' )
    # Top row uses bottom-aligned blocks so the bar is flush against the
    # full block in the bottom row (no gap between the two halves).
    assert _encode_single(9, 16) == ('▁', '█')


def test_sparkline_idx_16_full_full() -> None:
    assert _encode_single(16, 16) == ('█', '█')
