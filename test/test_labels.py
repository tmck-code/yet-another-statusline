from yas.render.text import _visible_width, superscript

# The vocabulary the label overlay must render. Every string here must satisfy
# the width-equals-length invariant (see TestWidthInvariant below).
LABEL_VOCAB = [
    'cache', 'clear', 'session', 'remain', 'used', 'burn rate', '5h', '7d',
    'input', 'output', 'cost', 'tokens over time', 'skills + plugins',
    'context', 'fill', 'dumb', 'path', 'git',
    'changes', 'input sess/day', 'cache sess/day',
    'output sess/day', 'cost sess/day',
    'plan', 'subagents', 'specs', 'workflow',
]


class TestSuperscript:
    def test_lowercase_word(self) -> None:
        assert superscript('cache') == 'ᶜᵃᶜʰᵉ'

    def test_digit_and_letter(self) -> None:
        assert superscript('5h') == '⁵ʰ'

    def test_unmapped_char_passes_through(self) -> None:
        # 'q' has no standard Unicode superscript form, so it is emitted as-is.
        assert superscript('q') == 'q'
        assert superscript('aqz') == 'ᵃqᶻ'


class TestWidthInvariant:
    def test_vocab_width_equals_length(self) -> None:
        for label in LABEL_VOCAB:
            assert _visible_width(superscript(label)) == len(label), label
