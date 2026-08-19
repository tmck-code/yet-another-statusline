import yas.renderer as renderer
from yas.constants import ICON_TOK_RATE
from yas.render.text import _visible_width, fmt_tok
from helper import strip_ansi

Renderer = renderer.Renderer


def _rate_label_w(r: renderer.Renderer, tok_rate: int, show_icons: bool = True) -> int:
    icon = f'{r.TOK_ICON}{ICON_TOK_RATE}  ' if show_icons else ''
    return _visible_width(f'{icon}{r.TOK}{fmt_tok(tok_rate)}{r.R}{r.LABEL} t/m{r.R}')


def test_tokens_over_time_returns_single_line() -> None:
    r = Renderer()
    line = r.tokens_over_time(0, '', box_width=160)
    assert isinstance(line, str)
    assert '\n' not in line


def test_tokens_over_time_contains_rate_icon() -> None:
    r = Renderer()
    line = r.tokens_over_time(1234, '', box_width=160)
    assert ICON_TOK_RATE in line


def test_tokens_over_time_fits_within_box() -> None:
    r = Renderer()
    for box in (60, 80, 110, 160, 220):
        line = r.tokens_over_time(74_600, 'sess', box_width=box)
        assert _visible_width(line) <= box - 3


def test_tokens_over_time_sparkline_omitted_below_10_chars() -> None:
    # The sparkline is dropped when fewer than 10 chars remain for the graph
    # (bar_w < 10); the bare rate label survives. Width-based so it doesn't
    # depend on the on-disk rate log.
    r = Renderer()
    rate_label_w = _rate_label_w(r, 0)

    def region_w(box: int) -> int:
        return _visible_width(r.tokens_over_time(0, '', box_width=box))

    # Small box: bar_w < 10, sparkline omitted -> region is just the bare label.
    small_box = rate_label_w + 3 + 5  # box_width - 3 - rate_label_w == 5 < 10
    assert region_w(small_box) == rate_label_w
    # Wide box: bar_w >= 10, graph space present -> region is wider.
    assert region_w(160) > rate_label_w
    assert ICON_TOK_RATE in r.tokens_over_time(0, '', box_width=small_box)


def test_tokens_over_time_blank_spark_without_session_id() -> None:
    # No session_id -> no history to plot; the graph region is blank spaces
    # rather than a rendered sparkline, but still fills the available width.
    r = Renderer()
    line = strip_ansi(r.tokens_over_time(500, '', box_width=160))
    rate_label_w = _rate_label_w(r, 500)
    assert line[rate_label_w:] == ' ' * (157 - rate_label_w)


def test_tokens_over_time_show_icons_false_drops_icon() -> None:
    r = Renderer()
    line = r.tokens_over_time(1234, '', box_width=160, show_icons=False)
    assert ICON_TOK_RATE not in line
