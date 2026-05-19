import statusline_command as sl


# ---------------------------------------------------------------------------
# 2.1  fmt_tok
# ---------------------------------------------------------------------------

class TestFmtTok:
    def test_zero(self):
        assert sl.fmt_tok(0) == '0'

    def test_one(self):
        assert sl.fmt_tok(1) == '1'

    def test_999(self):
        assert sl.fmt_tok(999) == '999'

    def test_1k(self):
        assert sl.fmt_tok(1000) == '1.0K'

    def test_12345(self):
        assert sl.fmt_tok(12_345) == '12.3K'

    def test_999k(self):
        assert sl.fmt_tok(999_999) == '1000.0K'

    def test_1m(self):
        assert sl.fmt_tok(1_000_000) == '1.0M'

    def test_2_5m(self):
        assert sl.fmt_tok(2_500_000) == '2.5M'


# ---------------------------------------------------------------------------
# 2.2  _is_wide
# ---------------------------------------------------------------------------

class TestIsWide:
    def test_ascii_not_wide(self):
        assert sl._is_wide('a') is False

    def test_cjk_not_wide(self):
        # CJK ideograph — outside the emoji block this function covers
        assert sl._is_wide('中') is False

    def test_emoji_is_wide(self):
        assert sl._is_wide('🎨') is True

    def test_lower_boundary(self):
        # U+1F300 is the first emoji in range
        assert sl._is_wide('\U0001F300') is True

    def test_upper_boundary(self):
        # U+1FAFF is the last codepoint in range
        assert sl._is_wide('\U0001FAFF') is True

    def test_just_below_range(self):
        assert sl._is_wide('\U0001F2FF') is False

    def test_just_above_range(self):
        assert sl._is_wide('\U0001FB00') is False


# ---------------------------------------------------------------------------
# 2.3  _visible_width
# ---------------------------------------------------------------------------

class TestVisibleWidth:
    def test_empty_string(self):
        assert sl._visible_width('') == 0

    def test_plain_text(self):
        assert sl._visible_width('hello') == 5

    def test_ansi_wrapped(self):
        assert sl._visible_width('\x1b[31mhi\x1b[0m') == 2

    def test_emoji_counts_as_two(self):
        assert sl._visible_width('a🎨b') == 4

    def test_ansi_plus_emoji(self):
        # ANSI escapes stripped, emoji = 2
        assert sl._visible_width('\x1b[38;5;75m🎨\x1b[0m') == 2


# ---------------------------------------------------------------------------
# 2.4  sparkline_width
# ---------------------------------------------------------------------------

class TestSparklineWidth:
    def test_89(self):
        assert sl.sparkline_width(89) == 0

    def test_90(self):
        assert sl.sparkline_width(90) == 10

    def test_109(self):
        assert sl.sparkline_width(109) == 10

    def test_110(self):
        assert sl.sparkline_width(110) == 20

    def test_129(self):
        assert sl.sparkline_width(129) == 20

    def test_130(self):
        assert sl.sparkline_width(130) == 30

    def test_200(self):
        assert sl.sparkline_width(200) == 30

    def test_0(self):
        assert sl.sparkline_width(0) == 0


# ---------------------------------------------------------------------------
# 2.5  _short_agent_name
# ---------------------------------------------------------------------------

class TestShortAgentName:
    def test_general_purpose_uses_description_prefix(self):
        result = sl._short_agent_name('general-purpose', 'Branch ship-readiness audit - other detail')
        assert result == 'Branch ship-readiness audit'

    def test_explore_uses_description_prefix(self):
        result = sl._short_agent_name('Explore', 'Investigate - more')
        assert result == 'Investigate'

    def test_plan_uses_description_prefix(self):
        result = sl._short_agent_name('Plan', 'Design system - details')
        assert result == 'Design system'

    def test_executor_suffix_stripped(self):
        result = sl._short_agent_name('code-reviewer-executor', '')
        assert result == 'code-reviewer'

    def test_generic_no_separator_truncates_to_20(self):
        result = sl._short_agent_name('explore', 'a' * 50)
        assert result == 'a' * 20

    def test_case_insensitive_general_purpose(self):
        result = sl._short_agent_name('GENERAL-PURPOSE', 'Foo - Bar')
        assert result == 'Foo'


# ---------------------------------------------------------------------------
# 2.6  rainbow_at
# ---------------------------------------------------------------------------

class TestRainbowAt:
    def test_returns_escape_for_palette_entry(self):
        step = 5
        offset = 3
        idx = (step + offset) % len(sl.RAINBOW_PALETTE)
        expected = f'\033[38;5;{sl.RAINBOW_PALETTE[idx]}m'
        assert sl.rainbow_at(step, offset) == expected

    def test_zero_offset(self):
        step = 0
        expected = f'\033[38;5;{sl.RAINBOW_PALETTE[0]}m'
        assert sl.rainbow_at(step, 0) == expected

    def test_wraps_around(self):
        palette_len = len(sl.RAINBOW_PALETTE)
        step = palette_len - 1
        offset = 2
        idx = (step + offset) % palette_len
        expected = f'\033[38;5;{sl.RAINBOW_PALETTE[idx]}m'
        assert sl.rainbow_at(step, offset) == expected
