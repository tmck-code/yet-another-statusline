import statusline_command as sl


# ---------------------------------------------------------------------------
# 4.2  TranscriptUsage properties: billed_in, cache_read, out
# ---------------------------------------------------------------------------

class TestTranscriptUsageProps:
    def test_billed_in(self):
        u = sl.TranscriptUsage(
            input_tokens=10,
            cache_creation_input_tokens=2,
            cache_read_input_tokens=3,
            output_tokens=4,
        )
        assert u.billed_in == 12  # 10 + 2

    def test_cache_read(self):
        u = sl.TranscriptUsage(
            input_tokens=10,
            cache_creation_input_tokens=2,
            cache_read_input_tokens=3,
            output_tokens=4,
        )
        assert u.cache_read == 3

    def test_out(self):
        u = sl.TranscriptUsage(
            input_tokens=10,
            cache_creation_input_tokens=2,
            cache_read_input_tokens=3,
            output_tokens=4,
        )
        assert u.out == 4

    def test_all_props_combined(self):
        u = sl.TranscriptUsage(
            input_tokens=10,
            cache_creation_input_tokens=2,
            cache_read_input_tokens=3,
            output_tokens=4,
        )
        assert u.billed_in == 12
        assert u.cache_read == 3
        assert u.out == 4

    def test_zeros(self):
        u = sl.TranscriptUsage()
        assert u.billed_in == 0
        assert u.cache_read == 0
        assert u.out == 0
