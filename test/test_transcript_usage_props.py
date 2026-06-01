import statusline_command as sl
import yas.info.transcript as transcript



class TestTranscriptUsageProps:
    def test_billed_in(self) -> None:
        u = transcript.TranscriptUsage(
            input_tokens=10,
            cache_creation_input_tokens=2,
            cache_read_input_tokens=3,
            output_tokens=4,
        )
        assert u.billed_in == 12  # 10 + 2

    def test_cache_read(self) -> None:
        u = transcript.TranscriptUsage(
            input_tokens=10,
            cache_creation_input_tokens=2,
            cache_read_input_tokens=3,
            output_tokens=4,
        )
        assert u.cache_read == 3

    def test_out(self) -> None:
        u = transcript.TranscriptUsage(
            input_tokens=10,
            cache_creation_input_tokens=2,
            cache_read_input_tokens=3,
            output_tokens=4,
        )
        assert u.out == 4

    def test_all_props_combined(self) -> None:
        u = transcript.TranscriptUsage(
            input_tokens=10,
            cache_creation_input_tokens=2,
            cache_read_input_tokens=3,
            output_tokens=4,
        )
        assert u.billed_in == 12
        assert u.cache_read == 3
        assert u.out == 4

    def test_zeros(self) -> None:
        u = transcript.TranscriptUsage()
        assert u.billed_in == 0
        assert u.cache_read == 0
        assert u.out == 0
