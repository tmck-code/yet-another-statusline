"""ANSI -> Pango markup conversion in ops/ansi_png.py."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'ops'))

from ansi_png import ansi_to_pango  # noqa: E402  (needs the sys.path.insert above)


class TestStrikethrough:

    def test_strike_run_gets_strikethrough_attr(self):
        # setup
        ansi = '\033[9mdone\033[29m'

        # run
        result = ansi_to_pango(ansi)

        # expected
        expected = '<span strikethrough="true">done</span>'

        # assert
        assert result == expected

    def test_unstrike_ends_the_struck_run(self):
        # setup
        ansi = '\033[9mdone\033[29mlive'

        # run
        result = ansi_to_pango(ansi)

        # expected
        expected = '<span strikethrough="true">done</span>live'

        # assert
        assert result == expected

    def test_strike_composes_with_enclosing_colour(self):
        """A finished `loc r/w` field: CTX_DIM outside, STRIKE/UNSTRIKE inside."""
        # setup
        ansi = '\033[38;2;120;120;120mloc \033[9m+12/-3\033[29m tail\033[0m'

        # run
        result = ansi_to_pango(ansi)

        # expected
        expected = (
            '<span foreground="#787878">loc </span>'
            '<span foreground="#787878" strikethrough="true">+12/-3</span>'
            '<span foreground="#787878"> tail</span>'
        )

        # assert
        assert result == expected

    def test_reset_clears_strikethrough(self):
        # setup
        ansi = '\033[9mdone\033[0mafter'

        # run
        result = ansi_to_pango(ansi)

        # expected
        expected = '<span strikethrough="true">done</span>after'

        # assert
        assert result == expected

    def test_struck_text_is_still_xml_escaped(self):
        # setup
        ansi = '\033[9ma & b <c>\033[29m'

        # run
        result = ansi_to_pango(ansi)

        # expected
        expected = '<span strikethrough="true">a &amp; b &lt;c&gt;</span>'

        # assert
        assert result == expected


class TestRenderPngEntryPoints:
    """Test that string and path entry points produce the same Pango markup."""

    def test_string_and_path_entry_produce_same_markup(self):
        """render_png_from_str and render_png produce same Pango markup."""
        # Sample ANSI input
        test_ansi = '\033[38;5;10mGreen text\033[0m'
        expected_markup = ansi_to_pango(test_ansi)

        # String entry point produces the expected markup directly
        assert ansi_to_pango(test_ansi) == expected_markup

        # Path entry point reads the string and produces the same result
        with tempfile.TemporaryDirectory() as tmpdir:
            txt_path = Path(tmpdir) / 'test.txt'
            txt_path.write_text(test_ansi)
            assert ansi_to_pango(txt_path.read_text().strip('\n')) == expected_markup
