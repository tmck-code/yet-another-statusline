"""Theme system for the statusline.

A `Theme` is a flat dataclass holding every colour the statusline draws.
Selection is layered (CLI flag → env var → config file → built-in default)
and resolution happens in `statusline_command.py::main`. See
`docs/adr/0002-theme-system.md`.
"""

from __future__ import annotations

from dataclasses import dataclass

RGB = tuple[int, int, int]


def fg(r: int, g: int, b: int) -> str:
    return f'\033[38;2;{r};{g};{b}m'


def fg256(n: int) -> str:
    return f'\033[38;5;{n}m'


@dataclass(frozen=True)
class ModelColors:
    anchor:     RGB
    warm_shift: RGB
    cool_shift: RGB
    label:      str


@dataclass(frozen=True)
class Theme:
    name: str

    # Decorative slots (ANSI escapes)
    border:       str
    border_off:   str
    pwd:          str
    branch:       str
    commit:       str
    session:      str
    skills:       str
    time:         str
    tok:          str
    tok_dim:      str
    tok_day:      str
    tok_day_dim:  str
    cost:         str
    bar_fill:     str
    bar_empty:    str
    dim_green:    str
    label:        str
    ctx:          str
    ctx_dim:      str
    white_brt:    str
    arrow:        str
    dirty:        str
    icon_path:    str
    tok_icon:     str
    model:        str

    # Three-step ladder (fill_colour & day_cost_colour)
    safe:         str
    warn:         str
    alert:        str
    yellow:       str
    tok_arrow:    str

    # Per-model pill identity
    models:       dict[str, ModelColors]

    # Pill foreground — two-sided flip on per-cell luminance
    pill_fg_dark:  RGB
    pill_fg_light: RGB

    # Gradients
    grad_stops:      tuple[tuple[float, RGB], ...]
    grey_rgb:        RGB
    spark_stops:     tuple[tuple[float, RGB], ...]
    spec_gradients:  tuple[tuple[RGB, RGB, RGB], ...]
    spec_empty_ansi: str


CLAUDE_DARK = Theme(
    name        = 'claude-dark',

    border      = fg256(244),
    border_off  = fg256(242),
    pwd         = fg256(75),
    branch      = fg256(114),
    commit      = fg256(244),
    session     = fg256(244),
    skills      = fg256(222),
    time        = fg256(244),
    tok         = fg256(116),
    tok_dim     = fg256(244),
    tok_day     = fg256(109),
    tok_day_dim = fg256(240),
    cost        = fg256(210),
    bar_fill    = fg256(114),
    bar_empty   = fg256(238),
    dim_green   = fg256(77),
    label       = fg256(244),
    ctx         = fg256(216),
    ctx_dim     = fg256(248),
    white_brt   = fg256(15),
    arrow       = fg256(46),
    dirty       = fg256(214),
    icon_path   = fg256(117),
    tok_icon    = fg256(11),
    model       = fg256(183),

    safe        = fg256(114),
    warn        = fg256(214),
    alert       = fg256(167),
    yellow      = fg256(226),
    tok_arrow   = fg256(226),

    models = {
        'opus':   ModelColors(
            anchor     = (255, 255,   0),
            warm_shift = (255, 165,   0),
            cool_shift = (180, 230,  60),
            label      = fg256(226),
        ),
        'sonnet': ModelColors(
            anchor     = (135, 215, 135),
            warm_shift = ( 44, 208, 168),
            cool_shift = ( 44, 140,  80),
            label      = fg256(114),
        ),
        'haiku':  ModelColors(
            anchor     = ( 95, 175, 255),
            warm_shift = (123, 230, 255),
            cool_shift = ( 74, 110, 224),
            label      = fg256(75),
        ),
        'other':  ModelColors(
            anchor     = (215, 175, 255),
            warm_shift = (240, 165, 224),
            cool_shift = (138, 111, 214),
            label      = fg256(183),
        ),
    },

    pill_fg_dark  = ( 15,  15,  15),
    pill_fg_light = (235, 235, 235),

    grad_stops = (
        (0.00, ( 40, 210,  80)),
        (0.25, (240, 230,  20)),
        (0.50, (255, 140,  20)),
        (0.75, (220,  40,  50)),
        (1.00, (170,  60, 210)),
    ),
    grey_rgb    = (108, 108, 108),
    spark_stops = (
        (0.00, (179,  46,  32)),
        (0.50, (200,  55,  40)),
        (1.00, (204,  65,  51)),
    ),
    spec_gradients = (
        (( 20,  60, 200), ( 20, 180, 240), (100, 240, 255)),  # Ocean
        ((200,  80,  10), (245,  30, 100), (255, 160,  80)),  # Sunset
        (( 10, 120,  40), ( 80, 210,  20), (200, 255,  60)),  # Forest
        (( 80,  20, 200), (160,  60, 255), (220, 160, 255)),  # Lavender
        ((160,  20,  10), (240, 120,  10), (255, 220,  30)),  # Ember
        (( 20,  80, 160), ( 60, 180, 240), (210, 240, 255)),  # Arctic
        ((120,  50,  10), (200, 120,  20), (255, 200,  80)),  # Copper
        ((160,  10,  50), (240,  60, 130), (255, 180, 210)),  # Rose
        (( 10, 110,  90), ( 20, 210, 150), (120, 255, 200)),  # Mint
        (( 50,  10, 160), (180,  20, 220), (255, 100, 240)),  # Nebula
        ((140,  10, 180), ( 40, 100, 255), ( 20, 220, 200)),  # Aurora
        ((200, 160,  10), (240,  80,  20), (180,  20,  80)),  # Volcano
    ),
    spec_empty_ansi = fg256(233),
)


CLAUDE_LIGHT = Theme(
    name        = 'claude-light',

    border      = fg256(244),
    border_off  = fg256(246),
    pwd         = fg(0, 95, 175),
    branch      = fg256(28),
    commit      = fg256(243),
    session     = fg256(243),
    skills      = fg(160, 110, 30),
    time        = fg256(243),
    tok         = fg(40, 110, 150),
    tok_dim     = fg256(245),
    tok_day     = fg(70, 120, 130),
    tok_day_dim = fg256(247),
    cost        = fg(175, 80, 80),
    bar_fill    = fg256(28),
    bar_empty   = fg256(252),
    dim_green   = fg(60, 130, 70),
    label       = fg256(243),
    ctx         = fg(180, 100, 50),
    ctx_dim     = fg256(245),
    white_brt   = fg256(232),
    arrow       = fg(0, 135, 0),
    dirty       = fg(180, 110, 20),
    icon_path   = fg(40, 110, 160),
    tok_icon    = fg(160, 130, 20),
    model       = fg256(96),

    safe        = fg256(28),
    warn        = fg(180, 110, 20),
    alert       = fg(170, 50, 50),
    yellow      = fg(160, 130, 20),
    tok_arrow   = fg(0, 0, 0),

    models = {
        'opus':   ModelColors(
            anchor     = (212, 160,  23),
            warm_shift = (200, 120,  20),
            cool_shift = (170, 175,  40),
            label      = fg(150, 110,  20),
        ),
        'sonnet': ModelColors(
            anchor     = (110, 175, 110),
            warm_shift = ( 60, 170, 130),
            cool_shift = ( 50, 130,  80),
            label      = fg256(28),
        ),
        'haiku':  ModelColors(
            anchor     = ( 80, 145, 210),
            warm_shift = (100, 175, 215),
            cool_shift = ( 60,  95, 180),
            label      = fg(0, 95, 175),
        ),
        'other':  ModelColors(
            anchor     = (170, 130, 195),
            warm_shift = (190, 130, 180),
            cool_shift = (115,  90, 170),
            label      = fg256(96),
        ),
    },

    pill_fg_dark  = ( 10,  10,  10),
    pill_fg_light = (250, 250, 250),

    grad_stops = (
        (0.00, ( 30, 158,  60)),
        (0.25, (180, 172,  15)),
        (0.50, (191, 105,  15)),
        (0.75, (165,  30,  38)),
        (1.00, (128,  45, 158)),
    ),
    grey_rgb    = (160, 160, 160),
    spark_stops = (
        (0.00, (145,  35,  25)),
        (0.50, (165,  45,  32)),
        (1.00, (175,  55,  42)),
    ),
    spec_gradients = (
        (( 15,  45, 150), ( 15, 135, 180), ( 75, 180, 191)),  # Ocean
        ((150,  60,   8), (184,  22,  75), (191, 120,  60)),  # Sunset
        ((  8,  90,  30), ( 60, 158,  15), (150, 191,  45)),  # Forest
        (( 60,  15, 150), (120,  45, 191), (165, 120, 191)),  # Lavender
        ((120,  15,   8), (180,  90,   8), (191, 165,  23)),  # Ember
        (( 15,  60, 120), ( 45, 135, 180), (158, 180, 191)),  # Arctic
        (( 90,  38,   8), (150,  90,  15), (191, 150,  60)),  # Copper
        ((120,   8,  38), (180,  45,  98), (191, 135, 158)),  # Rose
        ((  8,  82,  68), ( 15, 158, 112), ( 90, 191, 150)),  # Mint
        (( 38,   8, 120), (135,  15, 165), (191,  75, 180)),  # Nebula
        ((105,   8, 135), ( 30,  75, 191), ( 15, 165, 150)),  # Aurora
        ((150, 120,   8), (180,  60,  15), (135,  15,  60)),  # Volcano
    ),
    spec_empty_ansi = fg256(254),
)


CATPPUCCIN_LATTE = Theme(
    name        = 'catppuccin-latte',

    border      = fg(140, 143, 161),
    border_off  = fg(156, 160, 176),
    pwd         = fg( 30, 102, 245),
    branch      = fg( 64, 160,  43),
    commit      = fg(108, 111, 133),
    session     = fg(108, 111, 133),
    skills      = fg(223, 142,  29),
    time        = fg(108, 111, 133),
    tok         = fg( 23, 146, 153),
    tok_dim     = fg(140, 143, 161),
    tok_day     = fg( 32, 159, 181),
    tok_day_dim = fg(156, 160, 176),
    cost        = fg(230,  69,  83),
    bar_fill    = fg( 64, 160,  43),
    bar_empty   = fg(188, 192, 204),
    dim_green   = fg( 64, 160,  43),
    label       = fg(140, 143, 161),
    ctx         = fg(254, 100,  11),
    ctx_dim     = fg(124, 127, 147),
    white_brt   = fg( 76,  79, 105),
    arrow       = fg( 64, 160,  43),
    dirty       = fg(254, 100,  11),
    icon_path   = fg( 32, 159, 181),
    tok_icon    = fg(223, 142,  29),
    model       = fg(136,  57, 239),

    safe        = fg( 64, 160,  43),
    warn        = fg(254, 100,  11),
    alert       = fg(210,  15,  57),
    yellow      = fg(223, 142,  29),
    tok_arrow   = fg(223, 142,  29),

    models = {
        'opus':   ModelColors(
            anchor     = (223, 142,  29),
            warm_shift = (254, 100,  11),
            cool_shift = ( 64, 160,  43),
            label      = fg(223, 142,  29),
        ),
        'sonnet': ModelColors(
            anchor     = ( 64, 160,  43),
            warm_shift = ( 23, 146, 153),
            cool_shift = ( 30, 102, 245),
            label      = fg( 64, 160,  43),
        ),
        'haiku':  ModelColors(
            anchor     = ( 32, 159, 181),
            warm_shift = (  4, 165, 229),
            cool_shift = ( 30, 102, 245),
            label      = fg( 30, 102, 245),
        ),
        'other':  ModelColors(
            anchor     = (234, 118, 203),
            warm_shift = (136,  57, 239),
            cool_shift = (114, 135, 253),
            label      = fg(136,  57, 239),
        ),
    },

    pill_fg_dark  = ( 30,  30,  46),
    pill_fg_light = (239, 241, 245),

    grad_stops = (
        (0.00, ( 64, 160,  43)),
        (0.25, (223, 142,  29)),
        (0.50, (254, 100,  11)),
        (0.75, (210,  15,  57)),
        (1.00, (136,  57, 239)),
    ),
    grey_rgb    = (156, 160, 176),
    spark_stops = (
        (0.00, (230,  69,  83)),
        (0.50, (210,  15,  57)),
        (1.00, (254, 100,  11)),
    ),
    spec_gradients = (
        (( 32, 159, 181), ( 30, 102, 245), (  4, 165, 229)),  # Ocean
        ((254, 100,  11), (230,  69,  83), (223, 142,  29)),  # Sunset
        (( 64, 160,  43), ( 23, 146, 153), (223, 142,  29)),  # Forest
        ((136,  57, 239), (114, 135, 253), (234, 118, 203)),  # Lavender
        ((210,  15,  57), (254, 100,  11), (223, 142,  29)),  # Ember
        (( 32, 159, 181), (  4, 165, 229), (188, 192, 204)),  # Arctic
        ((254, 100,  11), (223, 142,  29), (230,  69,  83)),  # Copper
        ((234, 118, 203), (220, 138, 120), (221, 120, 120)),  # Rose
        (( 23, 146, 153), ( 64, 160,  43), (  4, 165, 229)),  # Mint
        ((136,  57, 239), (234, 118, 203), (114, 135, 253)),  # Nebula
        (( 23, 146, 153), ( 32, 159, 181), (136,  57, 239)),  # Aurora
        ((210,  15,  57), (230,  69,  83), (254, 100,  11)),  # Volcano
    ),
    spec_empty_ansi = fg256(254),
)


CATPPUCCIN_MOCHA = Theme(
    name        = 'catppuccin-mocha',

    border      = fg(127, 132, 156),
    border_off  = fg(108, 112, 134),
    pwd         = fg(137, 180, 250),
    branch      = fg(166, 227, 161),
    commit      = fg(166, 173, 200),
    session     = fg(166, 173, 200),
    skills      = fg(249, 226, 175),
    time        = fg(166, 173, 200),
    tok         = fg(148, 226, 213),
    tok_dim     = fg(127, 132, 156),
    tok_day     = fg(116, 199, 236),
    tok_day_dim = fg(108, 112, 134),
    cost        = fg(235, 160, 172),
    bar_fill    = fg(166, 227, 161),
    bar_empty   = fg( 69,  71,  90),
    dim_green   = fg(166, 227, 161),
    label       = fg(127, 132, 156),
    ctx         = fg(250, 179, 135),
    ctx_dim     = fg(166, 173, 200),
    white_brt   = fg(205, 214, 244),
    arrow       = fg(166, 227, 161),
    dirty       = fg(250, 179, 135),
    icon_path   = fg(116, 199, 236),
    tok_icon    = fg(249, 226, 175),
    model       = fg(203, 166, 247),

    safe        = fg(166, 227, 161),
    warn        = fg(250, 179, 135),
    alert       = fg(243, 139, 168),
    yellow      = fg(249, 226, 175),
    tok_arrow   = fg(249, 226, 175),

    models = {
        'opus':   ModelColors(
            anchor     = (249, 226, 175),
            warm_shift = (250, 179, 135),
            cool_shift = (166, 227, 161),
            label      = fg(249, 226, 175),
        ),
        'sonnet': ModelColors(
            anchor     = (166, 227, 161),
            warm_shift = (148, 226, 213),
            cool_shift = (137, 220, 235),
            label      = fg(166, 227, 161),
        ),
        'haiku':  ModelColors(
            anchor     = (137, 180, 250),
            warm_shift = (116, 199, 236),
            cool_shift = (180, 190, 254),
            label      = fg(137, 180, 250),
        ),
        'other':  ModelColors(
            anchor     = (203, 166, 247),
            warm_shift = (245, 194, 231),
            cool_shift = (180, 190, 254),
            label      = fg(203, 166, 247),
        ),
    },

    pill_fg_dark  = ( 17,  17,  27),
    pill_fg_light = (205, 214, 244),

    grad_stops = (
        (0.00, (166, 227, 161)),
        (0.25, (249, 226, 175)),
        (0.50, (250, 179, 135)),
        (0.75, (243, 139, 168)),
        (1.00, (203, 166, 247)),
    ),
    grey_rgb    = (108, 112, 134),
    spark_stops = (
        (0.00, (235, 160, 172)),
        (0.50, (243, 139, 168)),
        (1.00, (250, 179, 135)),
    ),
    spec_gradients = (
        ((116, 199, 236), (137, 180, 250), (137, 220, 235)),  # Ocean
        ((250, 179, 135), (235, 160, 172), (249, 226, 175)),  # Sunset
        ((166, 227, 161), (148, 226, 213), (249, 226, 175)),  # Forest
        ((203, 166, 247), (180, 190, 254), (245, 194, 231)),  # Lavender
        ((243, 139, 168), (250, 179, 135), (249, 226, 175)),  # Ember
        ((116, 199, 236), (137, 220, 235), (180, 190, 254)),  # Arctic
        ((250, 179, 135), (249, 226, 175), (235, 160, 172)),  # Copper
        ((245, 194, 231), (245, 224, 220), (242, 205, 205)),  # Rose
        ((148, 226, 213), (166, 227, 161), (137, 220, 235)),  # Mint
        ((203, 166, 247), (245, 194, 231), (180, 190, 254)),  # Nebula
        ((148, 226, 213), (116, 199, 236), (203, 166, 247)),  # Aurora
        ((243, 139, 168), (235, 160, 172), (250, 179, 135)),  # Volcano
    ),
    spec_empty_ansi = fg256(233),
)


THEMES: dict[str, Theme] = {
    CLAUDE_DARK.name:      CLAUDE_DARK,
    CLAUDE_LIGHT.name:     CLAUDE_LIGHT,
    CATPPUCCIN_LATTE.name: CATPPUCCIN_LATTE,
    CATPPUCCIN_MOCHA.name: CATPPUCCIN_MOCHA,
}


def resolve(name: str | None) -> Theme:
    if name and name in THEMES:
        return THEMES[name]
    return CLAUDE_DARK
