"""ANSI -> Pango markup conversion in ops/ansi_png.py."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'ops'))

from ansi_png import ansi_to_pango  # noqa: E402  (needs the sys.path.insert above)


class TestStrikethrough:

    def test_strike_run_gets_strikethrough_attr(self):
        ansi = '\033[9mdone\033[29m'

        result = ansi_to_pango(ansi)

        expected = '<span strikethrough="true">done</span>'

        assert result == expected

    def test_unstrike_ends_the_struck_run(self):
        ansi = '\033[9mdone\033[29mlive'

        result = ansi_to_pango(ansi)

        expected = '<span strikethrough="true">done</span>live'

        assert result == expected

    def test_strike_composes_with_enclosing_colour(self):
        """A finished `loc r/w` field: CTX_DIM outside, STRIKE/UNSTRIKE inside."""
        ansi = '\033[38;2;120;120;120mloc \033[9m+12/-3\033[29m tail\033[0m'

        result = ansi_to_pango(ansi)

        expected = (
            '<span foreground="#787878">loc </span>'
            '<span foreground="#787878" strikethrough="true">+12/-3</span>'
            '<span foreground="#787878"> tail</span>'
        )

        assert result == expected

    def test_reset_clears_strikethrough(self):
        ansi = '\033[9mdone\033[0mafter'

        result = ansi_to_pango(ansi)

        expected = '<span strikethrough="true">done</span>after'

        assert result == expected

    def test_struck_text_is_still_xml_escaped(self):
        ansi = '\033[9ma & b <c>\033[29m'

        result = ansi_to_pango(ansi)

        expected = '<span strikethrough="true">a &amp; b &lt;c&gt;</span>'

        assert result == expected
