import yas.constants as constants
import yas.render.text as text
from yas.render.gradient import rainbow_at
from yas.render.text import _is_wide


class TestFmtTok:
    def test_zero(self) -> None:
        assert text.fmt_tok(0) == '0'

    def test_one(self) -> None:
        assert text.fmt_tok(1) == '1'

    def test_below_thousand_unchanged(self) -> None:
        assert text.fmt_tok(999) == '999'

    def test_thousand_rounds_to_k(self) -> None:
        assert text.fmt_tok(1000) == '1.0K'

    def test_five_digit_rounds_to_one_decimal_k(self) -> None:
        assert text.fmt_tok(12_345) == '12.3K'

    def test_just_below_million_promotes_to_m(self) -> None:
        # 999_999/1e3 rounds to 1000.0K (7 chars); promote to M so it stays <= 6.
        assert text.fmt_tok(999_999) == '1.0M'

    def test_million_displays_as_m(self) -> None:
        assert text.fmt_tok(1_000_000) == '1.0M'

    def test_multi_million_displays_as_m(self) -> None:
        assert text.fmt_tok(2_500_000) == '2.5M'

    def test_just_below_billion_promotes_to_b(self) -> None:
        # Avoids "1000.0M" (7 chars) at the M->B boundary.
        assert text.fmt_tok(999_999_999) == '1.0B'

    def test_multi_billion_displays_as_b(self) -> None:
        assert text.fmt_tok(4_660_500_000) == '4.7B'

    def test_never_exceeds_six_chars(self) -> None:
        for n in (0, 999, 999_999, 1_000_000, 999_999_999, 4_660_500_000, 99_999_999_999):
            assert len(text.fmt_tok(n)) <= 6, (n, text.fmt_tok(n))


class TestIsWide:
    def test_ascii_not_wide(self) -> None:
        assert _is_wide('a') is False

    def test_cjk_not_wide(self) -> None:
        # CJK ideograph — outside the emoji block this function covers
        assert _is_wide('中') is False

    def test_emoji_is_wide(self) -> None:
        assert _is_wide('🎨') is True

    def test_lower_boundary(self) -> None:
        # U+1F300 is the first emoji in range
        assert _is_wide('\U0001F300') is True

    def test_upper_boundary(self) -> None:
        # U+1FAFF is the last codepoint in range
        assert _is_wide('\U0001FAFF') is True

    def test_just_below_range(self) -> None:
        assert _is_wide('\U0001F2FF') is False

    def test_just_above_range(self) -> None:
        assert _is_wide('\U0001FB00') is False


class TestVisibleWidth:
    def test_empty_string(self) -> None:
        assert text._visible_width('') == 0

    def test_plain_text(self) -> None:
        assert text._visible_width('hello') == 5

    def test_ansi_wrapped(self) -> None:
        assert text._visible_width('\x1b[31mhi\x1b[0m') == 2

    def test_emoji_counts_as_two(self) -> None:
        assert text._visible_width('a🎨b') == 4

    def test_ansi_plus_emoji(self) -> None:
        # ANSI escapes stripped, emoji = 2
        assert text._visible_width('\x1b[38;5;75m🎨\x1b[0m') == 2


class TestSparklineWidth:
    def test_below_lower_threshold_returns_zero(self) -> None:
        assert text.sparkline_width(89) == 0

    def test_at_lower_threshold_returns_ten(self) -> None:
        assert text.sparkline_width(90) == 10

    def test_below_second_threshold_returns_ten(self) -> None:
        assert text.sparkline_width(109) == 10

    def test_at_second_threshold_returns_twenty(self) -> None:
        assert text.sparkline_width(110) == 20

    def test_below_third_threshold_returns_twenty(self) -> None:
        assert text.sparkline_width(129) == 20

    def test_at_third_threshold_returns_thirty(self) -> None:
        assert text.sparkline_width(130) == 30

    def test_above_all_thresholds_returns_thirty(self) -> None:
        assert text.sparkline_width(200) == 30

    def test_zero_returns_zero(self) -> None:
        assert text.sparkline_width(0) == 0


class TestRainbowAt:
    def test_returns_escape_for_palette_entry(self) -> None:
        step = 5
        offset = 3
        idx = (step + offset) % len(constants.RAINBOW_PALETTE)
        expected = f'\033[38;5;{constants.RAINBOW_PALETTE[idx]}m'
        assert rainbow_at(step, offset) == expected

    def test_zero_offset(self) -> None:
        step = 0
        expected = f'\033[38;5;{constants.RAINBOW_PALETTE[0]}m'
        assert rainbow_at(step, 0) == expected

    def test_wraps_around(self) -> None:
        palette_len = len(constants.RAINBOW_PALETTE)
        step = palette_len - 1
        offset = 2
        idx = (step + offset) % palette_len
        expected = f'\033[38;5;{constants.RAINBOW_PALETTE[idx]}m'
        assert rainbow_at(step, offset) == expected


class TestMiddleEllipsis:
    def test_fits_no_truncation(self) -> None:
        assert text._middle_ellipsis('hello', 10) == 'hello'

    def test_exact_fit(self) -> None:
        assert text._middle_ellipsis('hello', 5) == 'hello'

    def test_ascii_truncates_width_respected(self) -> None:
        result = text._middle_ellipsis('abcdefghij', 7)
        assert text._visible_width(result) <= 7
        assert '…' in result

    def test_ascii_truncates_contains_both_ends(self) -> None:
        result = text._middle_ellipsis('abcdefghij', 7)
        assert result.startswith('abc')
        assert result.endswith('ij')

    def test_edge_zero_width(self) -> None:
        assert text._middle_ellipsis('hello', 0) == '…'

    def test_edge_one_width(self) -> None:
        assert text._middle_ellipsis('hello', 1) == '…'

    def test_edge_two_width(self) -> None:
        result = text._middle_ellipsis('hello', 2)
        assert text._visible_width(result) <= 2
        assert '…' in result

    def test_ansi_wrapped_visible_width_respected(self) -> None:
        colored = '\x1b[31m' + 'abcdefghij' + '\x1b[0m'
        result = text._middle_ellipsis(colored, 7)
        assert text._visible_width(result) <= 7
        assert '…' in result

    def test_ansi_wrapped_escapes_preserved(self) -> None:
        colored = '\x1b[31m' + 'abcdefghij' + '\x1b[0m'
        result = text._middle_ellipsis(colored, 7)
        assert '\x1b[' in result
