"""Theme system for the statusline.

A `Theme` is a flat dataclass holding every colour the statusline draws.
Selection is layered (CLI flag → env var → config file → built-in default)
and resolution happens in `statusline_command.py::main`. See
`docs/adr/0002-theme-system.md`.
"""

from __future__ import annotations

RGB = tuple[int, int, int]


def fg(r: int, g: int, b: int) -> str:
    return f'\033[38;2;{r};{g};{b}m'


def fg256(n: int) -> str:
    return f'\033[38;5;{n}m'


class _Frozen:
    """Mixin emulating dataclass(frozen=True) immutability without dataclasses."""

    __slots__ = ()

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(f'cannot assign to field {name!r}')

    def __delattr__(self, name: str) -> None:
        raise AttributeError(f'cannot delete field {name!r}')


class ModelColors(_Frozen):
    __slots__ = ('anchor', 'warm_shift', 'cool_shift', 'label')

    anchor:     RGB
    warm_shift: RGB
    cool_shift: RGB
    label:      str

    def __init__(self, anchor: RGB, warm_shift: RGB, cool_shift: RGB, label: str) -> None:
        object.__setattr__(self, 'anchor', anchor)
        object.__setattr__(self, 'warm_shift', warm_shift)
        object.__setattr__(self, 'cool_shift', cool_shift)
        object.__setattr__(self, 'label', label)

    def __repr__(self) -> str:
        return (f'ModelColors(anchor={self.anchor!r}, warm_shift={self.warm_shift!r}, '
                f'cool_shift={self.cool_shift!r}, label={self.label!r})')


class Theme(_Frozen):
    __slots__ = (
        'name',
        'border', 'border_off', 'pwd', 'branch', 'commit', 'session', 'skills',
        'time', 'tok', 'tok_dim', 'tok_day', 'tok_day_dim', 'cost', 'bar_fill',
        'bar_empty', 'dim_green', 'label', 'ctx', 'ctx_dim', 'white_brt', 'arrow',
        'dirty', 'icon_path', 'tok_icon', 'model',
        'safe', 'warn', 'alert', 'yellow', 'tok_arrow',
        'models',
        'pill_fg_dark', 'pill_fg_light',
        'grad_stops', 'grey_rgb', 'spark_stops', 'spec_gradients', 'spec_empty_ansi',
    )

    name:            str
    border:          str
    border_off:      str
    pwd:             str
    branch:          str
    commit:          str
    session:         str
    skills:          str
    time:            str
    tok:             str
    tok_dim:         str
    tok_day:         str
    tok_day_dim:     str
    cost:            str
    bar_fill:        str
    bar_empty:       str
    dim_green:       str
    label:           str
    ctx:             str
    ctx_dim:         str
    white_brt:       str
    arrow:           str
    dirty:           str
    icon_path:       str
    tok_icon:        str
    model:           str
    safe:            str
    warn:            str
    alert:           str
    yellow:          str
    tok_arrow:       str
    models:          dict[str, ModelColors]
    pill_fg_dark:    RGB
    pill_fg_light:   RGB
    grad_stops:      tuple[tuple[float, RGB], ...]
    grey_rgb:        RGB
    spark_stops:     tuple[tuple[float, RGB], ...]
    spec_gradients:  tuple[tuple[RGB, RGB, RGB], ...]
    spec_empty_ansi: str

    def __init__(
        self,
        name: str,
        # Decorative slots (ANSI escapes)
        border:       str,
        border_off:   str,
        pwd:          str,
        branch:       str,
        commit:       str,
        session:      str,
        skills:       str,
        time:         str,
        tok:          str,
        tok_dim:      str,
        tok_day:      str,
        tok_day_dim:  str,
        cost:         str,
        bar_fill:     str,
        bar_empty:    str,
        dim_green:    str,
        label:        str,
        ctx:          str,
        ctx_dim:      str,
        white_brt:    str,
        arrow:        str,
        dirty:        str,
        icon_path:    str,
        tok_icon:     str,
        model:        str,
        # Three-step ladder (fill_colour & day_cost_colour)
        safe:         str,
        warn:         str,
        alert:        str,
        yellow:       str,
        tok_arrow:    str,
        # Per-model pill identity
        models:       dict[str, ModelColors],
        # Pill foreground — two-sided flip on per-cell luminance
        pill_fg_dark:  RGB,
        pill_fg_light: RGB,
        # Gradients
        grad_stops:      tuple[tuple[float, RGB], ...],
        grey_rgb:        RGB,
        spark_stops:     tuple[tuple[float, RGB], ...],
        spec_gradients:  tuple[tuple[RGB, RGB, RGB], ...],
        spec_empty_ansi: str,
    ) -> None:
        s = object.__setattr__
        s(self, 'name', name)
        s(self, 'border', border)
        s(self, 'border_off', border_off)
        s(self, 'pwd', pwd)
        s(self, 'branch', branch)
        s(self, 'commit', commit)
        s(self, 'session', session)
        s(self, 'skills', skills)
        s(self, 'time', time)
        s(self, 'tok', tok)
        s(self, 'tok_dim', tok_dim)
        s(self, 'tok_day', tok_day)
        s(self, 'tok_day_dim', tok_day_dim)
        s(self, 'cost', cost)
        s(self, 'bar_fill', bar_fill)
        s(self, 'bar_empty', bar_empty)
        s(self, 'dim_green', dim_green)
        s(self, 'label', label)
        s(self, 'ctx', ctx)
        s(self, 'ctx_dim', ctx_dim)
        s(self, 'white_brt', white_brt)
        s(self, 'arrow', arrow)
        s(self, 'dirty', dirty)
        s(self, 'icon_path', icon_path)
        s(self, 'tok_icon', tok_icon)
        s(self, 'model', model)
        s(self, 'safe', safe)
        s(self, 'warn', warn)
        s(self, 'alert', alert)
        s(self, 'yellow', yellow)
        s(self, 'tok_arrow', tok_arrow)
        s(self, 'models', models)
        s(self, 'pill_fg_dark', pill_fg_dark)
        s(self, 'pill_fg_light', pill_fg_light)
        s(self, 'grad_stops', grad_stops)
        s(self, 'grey_rgb', grey_rgb)
        s(self, 'spark_stops', spark_stops)
        s(self, 'spec_gradients', spec_gradients)
        s(self, 'spec_empty_ansi', spec_empty_ansi)


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
        'fable':  ModelColors(
            anchor     = (255, 105, 180),
            warm_shift = (255,  70, 130),
            cool_shift = (230, 140, 190),
            label      = fg256(211),
        ),
        'mythos': ModelColors(
            anchor     = ( 90, 200, 180),
            warm_shift = ( 60, 180, 210),
            cool_shift = (130, 110, 220),
            label      = fg256(80),
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
        'fable':  ModelColors(
            anchor     = (205,  90, 130),
            warm_shift = (190,  70, 110),
            cool_shift = (180, 100, 140),
            label      = fg(160,  60,  90),
        ),
        'mythos': ModelColors(
            anchor     = ( 70, 150, 150),
            warm_shift = ( 60, 140, 160),
            cool_shift = (100, 120, 180),
            label      = fg( 50, 120, 130),
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


DRACULA = Theme(
    name        = 'dracula',

    border      = fg(144, 145, 148),
    border_off  = fg(123, 124, 129),
    pwd         = fg(189, 147, 249),
    branch      = fg( 80, 250, 123),
    commit      = fg(113, 114, 120),
    session     = fg(113, 114, 120),
    skills      = fg(241, 250, 140),
    time        = fg(113, 114, 120),
    tok         = fg(139, 233, 253),
    tok_dim     = fg(102, 104, 110),
    tok_day     = fg(139, 233, 253),
    tok_day_dim = fg(102, 104, 110),
    cost        = fg(255,  85,  85),
    bar_fill    = fg( 80, 250, 123),
    bar_empty   = fg(  0,   0,   0),
    dim_green   = fg( 80, 250, 123),
    label       = fg(113, 114, 120),
    ctx         = fg(139, 233, 253),
    ctx_dim     = fg(113, 114, 120),
    white_brt   = fg(255, 255, 255),
    arrow       = fg( 80, 250, 123),
    dirty       = fg(255,  85,  85),
    icon_path   = fg(139, 233, 253),
    tok_icon    = fg(241, 250, 140),
    model       = fg(189, 147, 249),

    safe        = fg( 80, 250, 123),
    warn        = fg(241, 250, 140),
    alert       = fg(255,  85,  85),
    yellow      = fg(241, 250, 140),
    tok_arrow   = fg(241, 250, 140),

    models = {
        'opus':   ModelColors(
            anchor     = (241, 250, 140),
            warm_shift = (247, 184, 118),
            cool_shift = (177, 250, 133),
            label      = fg(241, 250, 140),
        ),
        'sonnet': ModelColors(
            anchor     = ( 80, 250, 123),
            warm_shift = (104, 243, 175),
            cool_shift = (107, 224, 154),
            label      = fg( 80, 250, 123),
        ),
        'haiku':  ModelColors(
            anchor     = (189, 147, 249),
            warm_shift = (164, 190, 251),
            cool_shift = (209, 139, 234),
            label      = fg(189, 147, 249),
        ),
        'other':  ModelColors(
            anchor     = (255, 121, 198),
            warm_shift = (255, 110, 164),
            cool_shift = (235, 129, 213),
            label      = fg(255, 121, 198),
        ),
        'fable':  ModelColors(
            anchor     = (255,  90, 120),
            warm_shift = (255,  70,  90),
            cool_shift = (255, 130, 150),
            label      = fg(255,  90, 120),
        ),
        'mythos': ModelColors(
            anchor     = (140, 120, 255),
            warm_shift = (160, 110, 240),
            cool_shift = (110, 140, 255),
            label      = fg(140, 120, 255),
        ),
    },

    pill_fg_dark  = ( 15,  15,  15),
    pill_fg_light = (235, 235, 235),

    grad_stops = (
        (0.00, ( 80, 250, 123)),
        (0.25, (241, 250, 140)),
        (0.50, (248, 168, 112)),
        (0.75, (255,  85,  85)),
        (1.00, (255, 121, 198)),
    ),
    grey_rgb    = (144, 145, 148),
    spark_stops = (
        (0.00, (212,  76,  79)),
        (0.50, (234,  81,  82)),
        (1.00, (255,  85,  85)),
    ),
    spec_gradients = (
        ((189, 147, 249), (139, 233, 253), (139, 233, 253)),  # Ocean
        ((255,  85,  85), (255, 121, 198), (241, 250, 140)),  # Sunset
        (( 56, 175,  86), ( 80, 250, 123), ( 80, 250, 123)),  # Forest
        ((255, 121, 198), (189, 147, 249), (255, 121, 198)),  # Lavender
        ((255,  85,  85), (255,  85,  85), (241, 250, 140)),  # Ember
        ((189, 147, 249), (202, 169, 250), (139, 233, 253)),  # Arctic
        ((241, 250, 140), (255,  85,  85), (241, 250, 140)),  # Copper
        ((255, 121, 198), (255, 121, 198), (255,  85,  85)),  # Rose
        ((139, 233, 253), ( 80, 250, 123), (139, 233, 253)),  # Mint
        ((255, 121, 198), (189, 147, 249), (139, 233, 253)),  # Nebula
        ((139, 233, 253), (255, 121, 198), (189, 147, 249)),  # Aurora
        ((241, 250, 140), (255,  85,  85), (255, 121, 198)),  # Volcano
    ),
    spec_empty_ansi = fg256(233),
)

GRUVBOX_DARK = Theme(
    name        = 'gruvbox-dark',

    border      = fg(138, 130, 109),
    border_off  = fg(118, 112,  95),
    pwd         = fg( 69, 133, 136),
    branch      = fg(152, 151,  26),
    commit      = fg(108, 103,  88),
    session     = fg(108, 103,  88),
    skills      = fg(215, 153,  33),
    time        = fg(108, 103,  88),
    tok         = fg(104, 157, 106),
    tok_dim     = fg( 98,  94,  81),
    tok_day     = fg(142, 192, 124),
    tok_day_dim = fg( 98,  94,  81),
    cost        = fg(251,  73,  52),
    bar_fill    = fg(152, 151,  26),
    bar_empty   = fg( 40,  40,  40),
    dim_green   = fg(152, 151,  26),
    label       = fg(108, 103,  88),
    ctx         = fg(104, 157, 106),
    ctx_dim     = fg(108, 103,  88),
    white_brt   = fg(235, 219, 178),
    arrow       = fg(184, 187,  38),
    dirty       = fg(204,  36,  29),
    icon_path   = fg(142, 192, 124),
    tok_icon    = fg(250, 189,  47),
    model       = fg( 69, 133, 136),

    safe        = fg(152, 151,  26),
    warn        = fg(215, 153,  33),
    alert       = fg(204,  36,  29),
    yellow      = fg(215, 153,  33),
    tok_arrow   = fg(250, 189,  47),

    models = {
        'opus':   ModelColors(
            anchor     = (215, 153,  33),
            warm_shift = (211, 106,  31),
            cool_shift = (190, 152,  30),
            label      = fg(215, 153,  33),
        ),
        'sonnet': ModelColors(
            anchor     = (152, 151,  26),
            warm_shift = (133, 153,  58),
            cool_shift = (131, 146,  54),
            label      = fg(152, 151,  26),
        ),
        'haiku':  ModelColors(
            anchor     = ( 69, 133, 136),
            warm_shift = ( 86, 145, 121),
            cool_shift = (101, 122, 135),
            label      = fg( 69, 133, 136),
        ),
        'other':  ModelColors(
            anchor     = (177,  98, 134),
            warm_shift = (185,  79, 102),
            cool_shift = (145, 108, 135),
            label      = fg(177,  98, 134),
        ),
        'fable':  ModelColors(
            anchor     = (214,  93, 101),
            warm_shift = (220,  60,  60),
            cool_shift = (190, 110, 120),
            label      = fg(214,  93, 101),
        ),
        'mythos': ModelColors(
            anchor     = (142, 108, 177),
            warm_shift = (158,  90, 180),
            cool_shift = (120, 120, 190),
            label      = fg(142, 108, 177),
        ),
    },

    pill_fg_dark  = ( 15,  15,  15),
    pill_fg_light = (235, 235, 235),

    grad_stops = (
        (0.00, (152, 151,  26)),
        (0.25, (215, 153,  33)),
        (0.50, (210,  94,  31)),
        (0.75, (204,  36,  29)),
        (1.00, (177,  98, 134)),
    ),
    grey_rgb    = (138, 130, 109),
    spark_stops = (
        (0.00, (209,  66,  50)),
        (0.50, (230,  70,  51)),
        (1.00, (251,  73,  52)),
    ),
    spec_gradients = (
        (( 69, 133, 136), (104, 157, 106), (142, 192, 124)),  # Ocean
        ((204,  36,  29), (177,  98, 134), (215, 153,  33)),  # Sunset
        ((118, 118,  30), (152, 151,  26), (184, 187,  38)),  # Forest
        ((177,  98, 134), ( 69, 133, 136), (211, 134, 155)),  # Lavender
        ((204,  36,  29), (251,  73,  52), (215, 153,  33)),  # Ember
        (( 69, 133, 136), (131, 165, 152), (142, 192, 124)),  # Arctic
        ((215, 153,  33), (204,  36,  29), (250, 189,  47)),  # Copper
        ((177,  98, 134), (211, 134, 155), (251,  73,  52)),  # Rose
        ((104, 157, 106), (152, 151,  26), (142, 192, 124)),  # Mint
        ((177,  98, 134), ( 69, 133, 136), (104, 157, 106)),  # Nebula
        ((104, 157, 106), (177,  98, 134), ( 69, 133, 136)),  # Aurora
        ((215, 153,  33), (204,  36,  29), (177,  98, 134)),  # Volcano
    ),
    spec_empty_ansi = fg256(233),
)

GRUVBOX_LIGHT = Theme(
    name        = 'gruvbox-light',

    border      = fg(156, 148, 126),
    border_off  = fg(175, 167, 141),
    pwd         = fg( 69, 133, 136),
    branch      = fg(152, 151,  26),
    commit      = fg(184, 176, 148),
    session     = fg(184, 176, 148),
    skills      = fg(215, 153,  33),
    time        = fg(184, 176, 148),
    tok         = fg(104, 157, 106),
    tok_dim     = fg(194, 186, 156),
    tok_day     = fg( 66, 123,  88),
    tok_day_dim = fg(194, 186, 156),
    cost        = fg(157,   0,   6),
    bar_fill    = fg(152, 151,  26),
    bar_empty   = fg(175, 167, 141),
    dim_green   = fg(152, 151,  26),
    label       = fg(184, 176, 148),
    ctx         = fg(104, 157, 106),
    ctx_dim     = fg(156, 148, 126),
    white_brt   = fg( 60,  56,  54),
    arrow       = fg(121, 116,  14),
    dirty       = fg(204,  36,  29),
    icon_path   = fg( 66, 123,  88),
    tok_icon    = fg(181, 118,  20),
    model       = fg( 69, 133, 136),

    safe        = fg(152, 151,  26),
    warn        = fg(215, 153,  33),
    alert       = fg(204,  36,  29),
    yellow      = fg(215, 153,  33),
    tok_arrow   = fg(181, 118,  20),

    models = {
        'opus':   ModelColors(
            anchor     = (215, 153,  33),
            warm_shift = (211, 106,  31),
            cool_shift = (190, 152,  30),
            label      = fg(215, 153,  33),
        ),
        'sonnet': ModelColors(
            anchor     = (152, 151,  26),
            warm_shift = (133, 153,  58),
            cool_shift = (131, 146,  54),
            label      = fg(152, 151,  26),
        ),
        'haiku':  ModelColors(
            anchor     = ( 69, 133, 136),
            warm_shift = ( 86, 145, 121),
            cool_shift = (101, 122, 135),
            label      = fg( 69, 133, 136),
        ),
        'other':  ModelColors(
            anchor     = (177,  98, 134),
            warm_shift = (185,  79, 102),
            cool_shift = (145, 108, 135),
            label      = fg(177,  98, 134),
        ),
        'fable':  ModelColors(
            anchor     = (214,  93, 101),
            warm_shift = (220,  60,  60),
            cool_shift = (190, 110, 120),
            label      = fg(214,  93, 101),
        ),
        'mythos': ModelColors(
            anchor     = (142, 108, 177),
            warm_shift = (158,  90, 180),
            cool_shift = (120, 120, 190),
            label      = fg(142, 108, 177),
        ),
    },

    pill_fg_dark  = ( 10,  10,  10),
    pill_fg_light = (250, 250, 250),

    grad_stops = (
        (0.00, (152, 151,  26)),
        (0.25, (215, 153,  33)),
        (0.50, (210,  94,  31)),
        (0.75, (204,  36,  29)),
        (1.00, (177,  98, 134)),
    ),
    grey_rgb    = (156, 148, 126),
    spark_stops = (
        (0.00, (176,  48,  45)),
        (0.50, (166,  24,  25)),
        (1.00, (157,   0,   6)),
    ),
    spec_gradients = (
        (( 69, 133, 136), (104, 157, 106), ( 66, 123,  88)),  # Ocean
        ((204,  36,  29), (177,  98, 134), (215, 153,  33)),  # Sunset
        ((182, 178,  78), (152, 151,  26), (121, 116,  14)),  # Forest
        ((177,  98, 134), ( 69, 133, 136), (143,  63, 113)),  # Lavender
        ((204,  36,  29), (157,   0,   6), (215, 153,  33)),  # Ember
        (( 69, 133, 136), (  7, 102, 120), ( 66, 123,  88)),  # Arctic
        ((215, 153,  33), (204,  36,  29), (181, 118,  20)),  # Copper
        ((177,  98, 134), (143,  63, 113), (157,   0,   6)),  # Rose
        ((104, 157, 106), (152, 151,  26), ( 66, 123,  88)),  # Mint
        ((177,  98, 134), ( 69, 133, 136), (104, 157, 106)),  # Nebula
        ((104, 157, 106), (177,  98, 134), ( 69, 133, 136)),  # Aurora
        ((215, 153,  33), (204,  36,  29), (177,  98, 134)),  # Volcano
    ),
    spec_empty_ansi = fg256(254),
)

NORD = Theme(
    name        = 'nord',

    border      = fg(131, 137, 148),
    border_off  = fg(114, 120, 132),
    pwd         = fg(129, 161, 193),
    branch      = fg(163, 190, 140),
    commit      = fg(106, 112, 123),
    session     = fg(106, 112, 123),
    skills      = fg(235, 203, 139),
    time        = fg(106, 112, 123),
    tok         = fg(136, 192, 208),
    tok_dim     = fg( 97, 103, 115),
    tok_day     = fg(143, 188, 187),
    tok_day_dim = fg( 97, 103, 115),
    cost        = fg(191,  97, 106),
    bar_fill    = fg(163, 190, 140),
    bar_empty   = fg( 59,  66,  82),
    dim_green   = fg(163, 190, 140),
    label       = fg(106, 112, 123),
    ctx         = fg(136, 192, 208),
    ctx_dim     = fg(106, 112, 123),
    white_brt   = fg(236, 239, 244),
    arrow       = fg(163, 190, 140),
    dirty       = fg(191,  97, 106),
    icon_path   = fg(143, 188, 187),
    tok_icon    = fg(235, 203, 139),
    model       = fg(129, 161, 193),

    safe        = fg(163, 190, 140),
    warn        = fg(235, 203, 139),
    alert       = fg(191,  97, 106),
    yellow      = fg(235, 203, 139),
    tok_arrow   = fg(235, 203, 139),

    models = {
        'opus':   ModelColors(
            anchor     = (235, 203, 139),
            warm_shift = (217, 161, 126),
            cool_shift = (206, 198, 139),
            label      = fg(235, 203, 139),
        ),
        'sonnet': ModelColors(
            anchor     = (163, 190, 140),
            warm_shift = (152, 191, 167),
            cool_shift = (154, 183, 153),
            label      = fg(163, 190, 140),
        ),
        'haiku':  ModelColors(
            anchor     = (129, 161, 193),
            warm_shift = (132, 176, 200),
            cool_shift = (144, 155, 187),
            label      = fg(129, 161, 193),
        ),
        'other':  ModelColors(
            anchor     = (180, 142, 173),
            warm_shift = (183, 128, 153),
            cool_shift = (165, 148, 179),
            label      = fg(180, 142, 173),
        ),
        'fable':  ModelColors(
            anchor     = (191, 110, 130),
            warm_shift = (200,  90, 110),
            cool_shift = (180, 130, 150),
            label      = fg(191, 110, 130),
        ),
        'mythos': ModelColors(
            anchor     = (136, 170, 190),
            warm_shift = (140, 180, 200),
            cool_shift = (150, 150, 200),
            label      = fg(140, 170, 195),
        ),
    },

    pill_fg_dark  = ( 15,  15,  15),
    pill_fg_light = (235, 235, 235),

    grad_stops = (
        (0.00, (163, 190, 140)),
        (0.25, (235, 203, 139)),
        (0.50, (213, 150, 122)),
        (0.75, (191,  97, 106)),
        (1.00, (180, 142, 173)),
    ),
    grey_rgb    = (131, 137, 148),
    spark_stops = (
        (0.00, (162,  88,  98)),
        (0.50, (176,  92, 102)),
        (1.00, (191,  97, 106)),
    ),
    spec_gradients = (
        ((129, 161, 193), (136, 192, 208), (143, 188, 187)),  # Ocean
        ((191,  97, 106), (180, 142, 173), (235, 203, 139)),  # Sunset
        ((132, 153, 123), (163, 190, 140), (163, 190, 140)),  # Forest
        ((180, 142, 173), (129, 161, 193), (180, 142, 173)),  # Lavender
        ((191,  97, 106), (191,  97, 106), (235, 203, 139)),  # Ember
        ((129, 161, 193), (129, 161, 193), (143, 188, 187)),  # Arctic
        ((235, 203, 139), (191,  97, 106), (235, 203, 139)),  # Copper
        ((180, 142, 173), (180, 142, 173), (191,  97, 106)),  # Rose
        ((136, 192, 208), (163, 190, 140), (143, 188, 187)),  # Mint
        ((180, 142, 173), (129, 161, 193), (136, 192, 208)),  # Nebula
        ((136, 192, 208), (180, 142, 173), (129, 161, 193)),  # Aurora
        ((235, 203, 139), (191,  97, 106), (180, 142, 173)),  # Volcano
    ),
    spec_empty_ansi = fg256(233),
)

ONE_DARK = Theme(
    name        = 'one-dark',

    border      = fg(106, 111, 122),
    border_off  = fg( 92,  98, 108),
    pwd         = fg( 97, 175, 239),
    branch      = fg(152, 195, 121),
    commit      = fg( 86,  91, 101),
    session     = fg( 86,  91, 101),
    skills      = fg(209, 154, 102),
    time        = fg( 86,  91, 101),
    tok         = fg( 86, 182, 194),
    tok_dim     = fg( 79,  84,  94),
    tok_day     = fg( 86, 182, 194),
    tok_day_dim = fg( 79,  84,  94),
    cost        = fg(224, 108, 117),
    bar_fill    = fg(152, 195, 121),
    bar_empty   = fg( 30,  33,  39),
    dim_green   = fg(152, 195, 121),
    label       = fg( 86,  91, 101),
    ctx         = fg( 86, 182, 194),
    ctx_dim     = fg( 86,  91, 101),
    white_brt   = fg(255, 255, 255),
    arrow       = fg(152, 195, 121),
    dirty       = fg(224, 108, 117),
    icon_path   = fg( 86, 182, 194),
    tok_icon    = fg(209, 154, 102),
    model       = fg( 97, 175, 239),

    safe        = fg(152, 195, 121),
    warn        = fg(209, 154, 102),
    alert       = fg(224, 108, 117),
    yellow      = fg(209, 154, 102),
    tok_arrow   = fg(209, 154, 102),

    models = {
        'opus':   ModelColors(
            anchor     = (209, 154, 102),
            warm_shift = (215, 136, 108),
            cool_shift = (186, 170, 110),
            label      = fg(209, 154, 102),
        ),
        'sonnet': ModelColors(
            anchor     = (152, 195, 121),
            warm_shift = (126, 190, 150),
            cool_shift = (138, 190, 150),
            label      = fg(152, 195, 121),
        ),
        'haiku':  ModelColors(
            anchor     = ( 97, 175, 239),
            warm_shift = ( 92, 178, 216),
            cool_shift = (127, 158, 234),
            label      = fg( 97, 175, 239),
        ),
        'other':  ModelColors(
            anchor     = (198, 120, 221),
            warm_shift = (206, 116, 190),
            cool_shift = (168, 136, 226),
            label      = fg(198, 120, 221),
        ),
        'fable':  ModelColors(
            anchor     = (224, 130, 145),
            warm_shift = (230, 100, 120),
            cool_shift = (210, 140, 160),
            label      = fg(224, 130, 145),
        ),
        'mythos': ModelColors(
            anchor     = (150, 130, 230),
            warm_shift = (170, 120, 220),
            cool_shift = (130, 150, 235),
            label      = fg(150, 130, 230),
        ),
    },

    pill_fg_dark  = ( 15,  15,  15),
    pill_fg_light = (235, 235, 235),

    grad_stops = (
        (0.00, (152, 195, 121)),
        (0.25, (209, 154, 102)),
        (0.50, (216, 131, 110)),
        (0.75, (224, 108, 117)),
        (1.00, (198, 120, 221)),
    ),
    grey_rgb    = (106, 111, 122),
    spark_stops = (
        (0.00, (187,  95, 104)),
        (0.50, (206, 102, 110)),
        (1.00, (224, 108, 117)),
    ),
    spec_gradients = (
        (( 97, 175, 239), ( 86, 182, 194), ( 86, 182, 194)),  # Ocean
        ((224, 108, 117), (198, 120, 221), (209, 154, 102)),  # Sunset
        ((115, 146,  96), (152, 195, 121), (152, 195, 121)),  # Forest
        ((198, 120, 221), ( 97, 175, 239), (198, 120, 221)),  # Lavender
        ((224, 108, 117), (224, 108, 117), (209, 154, 102)),  # Ember
        (( 97, 175, 239), ( 97, 175, 239), ( 86, 182, 194)),  # Arctic
        ((209, 154, 102), (224, 108, 117), (209, 154, 102)),  # Copper
        ((198, 120, 221), (198, 120, 221), (224, 108, 117)),  # Rose
        (( 86, 182, 194), (152, 195, 121), ( 86, 182, 194)),  # Mint
        ((198, 120, 221), ( 97, 175, 239), ( 86, 182, 194)),  # Nebula
        (( 86, 182, 194), (198, 120, 221), ( 97, 175, 239)),  # Aurora
        ((209, 154, 102), (224, 108, 117), (198, 120, 221)),  # Volcano
    ),
    spec_empty_ansi = fg256(233),
)

ONE_LIGHT = Theme(
    name        = 'one-light',

    border      = fg(145, 146, 150),
    border_off  = fg(166, 166, 169),
    pwd         = fg( 47,  90, 243),
    branch      = fg( 62, 149,  58),
    commit      = fg(176, 176, 179),
    session     = fg(176, 176, 179),
    skills      = fg(210, 182, 123),
    time        = fg(176, 176, 179),
    tok         = fg( 62, 149,  58),
    tok_dim     = fg(186, 186, 189),
    tok_day     = fg( 62, 149,  58),
    tok_day_dim = fg(186, 186, 189),
    cost        = fg(222,  61,  53),
    bar_fill    = fg( 62, 149,  58),
    bar_empty   = fg(166, 166, 169),
    dim_green   = fg( 62, 149,  58),
    label       = fg(176, 176, 179),
    ctx         = fg( 62, 149,  58),
    ctx_dim     = fg(145, 146, 150),
    white_brt   = fg( 42,  43,  51),
    arrow       = fg( 62, 149,  58),
    dirty       = fg(222,  61,  53),
    icon_path   = fg( 62, 149,  58),
    tok_icon    = fg(210, 182, 123),
    model       = fg( 47,  90, 243),

    safe        = fg( 62, 149,  58),
    warn        = fg(210, 182, 123),
    alert       = fg(222,  61,  53),
    yellow      = fg(210, 182, 123),
    tok_arrow   = fg(210, 182, 123),

    models = {
        'opus':   ModelColors(
            anchor     = (210, 182, 123),
            warm_shift = (215, 134,  95),
            cool_shift = (151, 169,  97),
            label      = fg(210, 182, 123),
        ),
        'sonnet': ModelColors(
            anchor     = ( 62, 149,  58),
            warm_shift = ( 62, 149,  58),
            cool_shift = ( 58, 134, 104),
            label      = fg( 62, 149,  58),
        ),
        'haiku':  ModelColors(
            anchor     = (100, 160, 255),
            warm_shift = (110, 175, 245),
            cool_shift = (120, 130, 255),
            label      = fg(100, 160, 255),
        ),
        'other':  ModelColors(
            anchor     = (200, 100, 210),
            warm_shift = (210, 110, 185),
            cool_shift = (170, 120, 225),
            label      = fg(200, 100, 210),
        ),
        'fable':  ModelColors(
            anchor     = (210, 100, 130),
            warm_shift = (215,  80, 100),
            cool_shift = (195, 120, 150),
            label      = fg(210, 100, 130),
        ),
        'mythos': ModelColors(
            anchor     = ( 90, 160, 170),
            warm_shift = ( 80, 150, 190),
            cool_shift = (110, 140, 200),
            label      = fg( 90, 160, 170),
        ),
    },

    pill_fg_dark  = ( 10,  10,  10),
    pill_fg_light = (250, 250, 250),

    grad_stops = (
        (0.00, ( 62, 149,  58)),
        (0.25, (210, 182, 123)),
        (0.50, (216, 122,  88)),
        (0.75, (222,  61,  53)),
        (1.00, (200, 100, 210)),
    ),
    grey_rgb    = (145, 146, 150),
    spark_stops = (
        (0.00, (227,  98,  92)),
        (0.50, (225,  80,  72)),
        (1.00, (222,  61,  53)),
    ),
    spec_gradients = (
        (( 47,  90, 243), ( 62, 149,  58), ( 62, 149,  58)),  # Ocean
        ((222,  61,  53), (160,   0, 149), (210, 182, 123)),  # Sunset
        (( 43, 104,  41), ( 62, 149,  58), ( 62, 149,  58)),  # Forest
        ((160,   0, 149), ( 47,  90, 243), (160,   0, 149)),  # Lavender
        ((222,  61,  53), (222,  61,  53), (210, 182, 123)),  # Ember
        (( 47,  90, 243), ( 47,  90, 243), ( 62, 149,  58)),  # Arctic
        ((210, 182, 123), (222,  61,  53), (210, 182, 123)),  # Copper
        ((160,   0, 149), (160,   0, 149), (222,  61,  53)),  # Rose
        (( 62, 149,  58), ( 62, 149,  58), ( 62, 149,  58)),  # Mint
        ((160,   0, 149), ( 47,  90, 243), ( 62, 149,  58)),  # Nebula
        (( 62, 149,  58), (160,   0, 149), ( 47,  90, 243)),  # Aurora
        ((210, 182, 123), (222,  61,  53), (160,   0, 149)),  # Volcano
    ),
    spec_empty_ansi = fg256(254),
)

SOLARIZED_DARK = Theme(
    name        = 'solarized-dark',

    border      = fg( 66,  96, 102),
    border_off  = fg( 52,  85,  92),
    pwd         = fg( 38, 139, 210),
    branch      = fg(133, 153,   0),
    commit      = fg( 46,  80,  88),
    session     = fg( 46,  80,  88),
    skills      = fg(181, 137,   0),
    time        = fg( 46,  80,  88),
    tok         = fg( 42, 161, 152),
    tok_dim     = fg( 39,  74,  83),
    tok_day     = fg(147, 161, 161),
    tok_day_dim = fg( 39,  74,  83),
    cost        = fg(203,  75,  22),
    bar_fill    = fg(133, 153,   0),
    bar_empty   = fg(  7,  54,  66),
    dim_green   = fg(133, 153,   0),
    label       = fg( 46,  80,  88),
    ctx         = fg( 42, 161, 152),
    ctx_dim     = fg( 46,  80,  88),
    white_brt   = fg(253, 246, 227),
    arrow       = fg( 88, 110, 117),
    dirty       = fg(220,  50,  47),
    icon_path   = fg(147, 161, 161),
    tok_icon    = fg(101, 123, 131),
    model       = fg( 38, 139, 210),

    safe        = fg(133, 153,   0),
    warn        = fg(181, 137,   0),
    alert       = fg(220,  50,  47),
    yellow      = fg(181, 137,   0),
    tok_arrow   = fg(101, 123, 131),

    models = {
        'opus':   ModelColors(
            anchor     = (181, 137,   0),
            warm_shift = (197, 102,  19),
            cool_shift = (162, 143,   0),
            label      = fg(181, 137,   0),
        ),
        'sonnet': ModelColors(
            anchor     = (133, 153,   0),
            warm_shift = ( 97, 156,  61),
            cool_shift = (109, 150,  52),
            label      = fg(133, 153,   0),
        ),
        'haiku':  ModelColors(
            anchor     = ( 38, 139, 210),
            warm_shift = ( 40, 150, 181),
            cool_shift = ( 90, 114, 186),
            label      = fg( 38, 139, 210),
        ),
        'other':  ModelColors(
            anchor     = (215,  65, 135),
            warm_shift = (214,  53, 105),
            cool_shift = (159,  80, 154),
            label      = fg(215,  65, 135),
        ),
        'fable':  ModelColors(
            anchor     = (220,  90,  90),
            warm_shift = (210,  60,  70),
            cool_shift = (200, 110, 110),
            label      = fg(220,  90,  90),
        ),
        'mythos': ModelColors(
            anchor     = (108, 113, 196),
            warm_shift = ( 90, 120, 190),
            cool_shift = (130, 110, 200),
            label      = fg(108, 113, 196),
        ),
    },

    pill_fg_dark  = ( 15,  15,  15),
    pill_fg_light = (235, 235, 235),

    grad_stops = (
        (0.00, (133, 153,   0)),
        (0.25, (181, 137,   0)),
        (0.50, (200,  94,  24)),
        (0.75, (220,  50,  47)),
        (1.00, (215,  65, 135)),
    ),
    grey_rgb    = ( 66,  96, 102),
    spark_stops = (
        (0.00, (162,  69,  28)),
        (0.50, (183,  72,  25)),
        (1.00, (203,  75,  22)),
    ),
    spec_gradients = (
        (( 38, 139, 210), ( 42, 161, 152), (147, 161, 161)),  # Ocean
        ((220,  50,  47), (211,  54, 130), (181, 137,   0)),  # Sunset
        (( 95, 123,  20), (133, 153,   0), ( 88, 110, 117)),  # Forest
        ((211,  54, 130), ( 38, 139, 210), (108, 113, 196)),  # Lavender
        ((220,  50,  47), (203,  75,  22), (181, 137,   0)),  # Ember
        (( 38, 139, 210), (131, 148, 150), (147, 161, 161)),  # Arctic
        ((181, 137,   0), (220,  50,  47), (101, 123, 131)),  # Copper
        ((211,  54, 130), (108, 113, 196), (203,  75,  22)),  # Rose
        (( 42, 161, 152), (133, 153,   0), (147, 161, 161)),  # Mint
        ((211,  54, 130), ( 38, 139, 210), ( 42, 161, 152)),  # Nebula
        (( 42, 161, 152), (211,  54, 130), ( 38, 139, 210)),  # Aurora
        ((181, 137,   0), (220,  50,  47), (211,  54, 130)),  # Volcano
    ),
    spec_empty_ansi = fg256(233),
)

SOLARIZED_LIGHT = Theme(
    name        = 'solarized-light',

    border      = fg(170, 178, 172),
    border_off  = fg(187, 192, 183),
    pwd         = fg( 38, 139, 210),
    branch      = fg(133, 153,   0),
    commit      = fg(195, 198, 188),
    session     = fg(195, 198, 188),
    skills      = fg(181, 137,   0),
    time        = fg(195, 198, 188),
    tok         = fg( 42, 161, 152),
    tok_dim     = fg(204, 205, 194),
    tok_day     = fg(147, 161, 161),
    tok_day_dim = fg(204, 205, 194),
    cost        = fg(203,  75,  22),
    bar_fill    = fg(133, 153,   0),
    bar_empty   = fg(187, 192, 183),
    dim_green   = fg(133, 153,   0),
    label       = fg(195, 198, 188),
    ctx         = fg( 42, 161, 152),
    ctx_dim     = fg(170, 178, 172),
    white_brt   = fg( 88, 110, 117),
    arrow       = fg( 88, 110, 117),
    dirty       = fg(220,  50,  47),
    icon_path   = fg(147, 161, 161),
    tok_icon    = fg(101, 123, 131),
    model       = fg( 38, 139, 210),

    safe        = fg(133, 153,   0),
    warn        = fg(181, 137,   0),
    alert       = fg(220,  50,  47),
    yellow      = fg(181, 137,   0),
    tok_arrow   = fg(101, 123, 131),

    models = {
        'opus':   ModelColors(
            anchor     = (181, 137,   0),
            warm_shift = (197, 102,  19),
            cool_shift = (162, 143,   0),
            label      = fg(181, 137,   0),
        ),
        'sonnet': ModelColors(
            anchor     = (133, 153,   0),
            warm_shift = ( 97, 156,  61),
            cool_shift = (109, 150,  52),
            label      = fg(133, 153,   0),
        ),
        'haiku':  ModelColors(
            anchor     = ( 38, 139, 210),
            warm_shift = ( 40, 150, 181),
            cool_shift = ( 90, 114, 186),
            label      = fg( 38, 139, 210),
        ),
        'other':  ModelColors(
            anchor     = (215,  65, 135),
            warm_shift = (214,  53, 105),
            cool_shift = (159,  80, 154),
            label      = fg(215,  65, 135),
        ),
        'fable':  ModelColors(
            anchor     = (220,  90,  90),
            warm_shift = (210,  60,  70),
            cool_shift = (200, 110, 110),
            label      = fg(220,  90,  90),
        ),
        'mythos': ModelColors(
            anchor     = (108, 113, 196),
            warm_shift = ( 90, 120, 190),
            cool_shift = (130, 110, 200),
            label      = fg(108, 113, 196),
        ),
    },

    pill_fg_dark  = ( 10,  10,  10),
    pill_fg_light = (250, 250, 250),

    grad_stops = (
        (0.00, (133, 153,   0)),
        (0.25, (181, 137,   0)),
        (0.50, (200,  94,  24)),
        (0.75, (220,  50,  47)),
        (1.00, (215,  65, 135)),
    ),
    grey_rgb    = (170, 178, 172),
    spark_stops = (
        (0.00, (213, 109,  63)),
        (0.50, (208,  92,  42)),
        (1.00, (203,  75,  22)),
    ),
    spec_gradients = (
        (( 38, 139, 210), ( 42, 161, 152), (147, 161, 161)),  # Ocean
        ((220,  50,  47), (211,  54, 130), (181, 137,   0)),  # Sunset
        (( 95, 123,  20), (133, 153,   0), ( 88, 110, 117)),  # Forest
        ((211,  54, 130), ( 38, 139, 210), (108, 113, 196)),  # Lavender
        ((220,  50,  47), (203,  75,  22), (181, 137,   0)),  # Ember
        (( 38, 139, 210), (131, 148, 150), (147, 161, 161)),  # Arctic
        ((181, 137,   0), (220,  50,  47), (101, 123, 131)),  # Copper
        ((211,  54, 130), (108, 113, 196), (203,  75,  22)),  # Rose
        (( 42, 161, 152), (133, 153,   0), (147, 161, 161)),  # Mint
        ((211,  54, 130), ( 38, 139, 210), ( 42, 161, 152)),  # Nebula
        (( 42, 161, 152), (211,  54, 130), ( 38, 139, 210)),  # Aurora
        ((181, 137,   0), (220,  50,  47), (211,  54, 130)),  # Volcano
    ),
    spec_empty_ansi = fg256(254),
)

TOKYO_NIGHT = Theme(
    name        = 'tokyo-night',

    border      = fg( 98, 102, 126),
    border_off  = fg( 83,  87, 108),
    pwd         = fg(122, 162, 247),
    branch      = fg(158, 206, 106),
    commit      = fg( 76,  80, 100),
    session     = fg( 76,  80, 100),
    skills      = fg(224, 175, 104),
    time        = fg( 76,  80, 100),
    tok         = fg( 68, 157, 171),
    tok_dim     = fg( 69,  72,  91),
    tok_day     = fg( 13, 185, 215),
    tok_day_dim = fg( 69,  72,  91),
    cost        = fg(255, 122, 147),
    bar_fill    = fg(158, 206, 106),
    bar_empty   = fg( 50,  52,  74),
    dim_green   = fg(158, 206, 106),
    label       = fg( 76,  80, 100),
    ctx         = fg( 68, 157, 171),
    ctx_dim     = fg( 76,  80, 100),
    white_brt   = fg(172, 176, 208),
    arrow       = fg(185, 242, 124),
    dirty       = fg(247, 118, 142),
    icon_path   = fg( 13, 185, 215),
    tok_icon    = fg(255, 158, 100),
    model       = fg(122, 162, 247),

    safe        = fg(158, 206, 106),
    warn        = fg(224, 175, 104),
    alert       = fg(247, 118, 142),
    yellow      = fg(224, 175, 104),
    tok_arrow   = fg(255, 158, 100),

    models = {
        'opus':   ModelColors(
            anchor     = (224, 175, 104),
            warm_shift = (233, 152, 119),
            cool_shift = (198, 187, 105),
            label      = fg(224, 175, 104),
        ),
        'sonnet': ModelColors(
            anchor     = (158, 206, 106),
            warm_shift = (122, 186, 132),
            cool_shift = (149, 195, 141),
            label      = fg(158, 206, 106),
        ),
        'haiku':  ModelColors(
            anchor     = (122, 162, 247),
            warm_shift = ( 95, 160, 209),
            cool_shift = (137, 156, 242),
            label      = fg(122, 162, 247),
        ),
        'other':  ModelColors(
            anchor     = (173, 142, 230),
            warm_shift = (195, 135, 204),
            cool_shift = (158, 148, 235),
            label      = fg(173, 142, 230),
        ),
        'fable':  ModelColors(
            anchor     = (247, 140, 160),
            warm_shift = (255, 110, 140),
            cool_shift = (230, 150, 170),
            label      = fg(247, 140, 160),
        ),
        'mythos': ModelColors(
            anchor     = (100, 190, 200),
            warm_shift = ( 70, 180, 220),
            cool_shift = (120, 170, 230),
            label      = fg(100, 190, 200),
        ),
    },

    pill_fg_dark  = ( 15,  15,  15),
    pill_fg_light = (235, 235, 235),

    grad_stops = (
        (0.00, (158, 206, 106)),
        (0.25, (224, 175, 104)),
        (0.50, (236, 146, 123)),
        (0.75, (247, 118, 142)),
        (1.00, (173, 142, 230)),
    ),
    grey_rgb    = ( 98, 102, 126),
    spark_stops = (
        (0.00, (209, 103, 125)),
        (0.50, (232, 112, 136)),
        (1.00, (255, 122, 147)),
    ),
    spec_gradients = (
        ((122, 162, 247), ( 68, 157, 171), ( 13, 185, 215)),  # Ocean
        ((247, 118, 142), (173, 142, 230), (224, 175, 104)),  # Sunset
        ((126, 160,  96), (158, 206, 106), (185, 242, 124)),  # Forest
        ((173, 142, 230), (122, 162, 247), (187, 154, 247)),  # Lavender
        ((247, 118, 142), (255, 122, 147), (224, 175, 104)),  # Ember
        ((122, 162, 247), (125, 166, 255), ( 13, 185, 215)),  # Arctic
        ((224, 175, 104), (247, 118, 142), (255, 158, 100)),  # Copper
        ((173, 142, 230), (187, 154, 247), (255, 122, 147)),  # Rose
        (( 68, 157, 171), (158, 206, 106), ( 13, 185, 215)),  # Mint
        ((173, 142, 230), (122, 162, 247), ( 68, 157, 171)),  # Nebula
        (( 68, 157, 171), (173, 142, 230), (122, 162, 247)),  # Aurora
        ((224, 175, 104), (247, 118, 142), (173, 142, 230)),  # Volcano
    ),
    spec_empty_ansi = fg256(233),
)

PALENIGHT = Theme(
    name        = 'palenight',

    border      = fg(124, 126, 135),
    border_off  = fg(108, 110, 120),
    pwd         = fg(130, 170, 255),
    branch      = fg(195, 232, 141),
    commit      = fg( 99, 102, 113),
    session     = fg( 99, 102, 113),
    skills      = fg(255, 203, 107),
    time        = fg( 99, 102, 113),
    tok         = fg(137, 221, 255),
    tok_dim     = fg( 91,  94, 106),
    tok_day     = fg(163, 247, 255),
    tok_day_dim = fg( 91,  94, 106),
    cost        = fg(255, 139, 146),
    bar_fill    = fg(195, 232, 141),
    bar_empty   = fg( 41,  45,  62),
    dim_green   = fg(195, 232, 141),
    label       = fg( 99, 102, 113),
    ctx         = fg(137, 221, 255),
    ctx_dim     = fg( 99, 102, 113),
    white_brt   = fg(255, 255, 255),
    arrow       = fg(221, 255, 167),
    dirty       = fg(240, 113, 120),
    icon_path   = fg(163, 247, 255),
    tok_icon    = fg(255, 229, 133),
    model       = fg(130, 170, 255),

    safe        = fg(195, 232, 141),
    warn        = fg(255, 203, 107),
    alert       = fg(240, 113, 120),
    yellow      = fg(255, 203, 107),
    tok_arrow   = fg(255, 229, 133),

    models = {
        'opus':   ModelColors(
            anchor     = (255, 203, 107),
            warm_shift = (249, 167, 112),
            cool_shift = (231, 215, 121),
            label      = fg(255, 203, 107),
        ),
        'sonnet': ModelColors(
            anchor     = (195, 232, 141),
            warm_shift = (172, 228, 187),
            cool_shift = (179, 216, 170),
            label      = fg(195, 232, 141),
        ),
        'haiku':  ModelColors(
            anchor     = (130, 170, 255),
            warm_shift = (134, 196, 255),
            cool_shift = (151, 163, 249),
            label      = fg(130, 170, 255),
        ),
        'other':  ModelColors(
            anchor     = (199, 146, 234),
            warm_shift = (211, 136, 200),
            cool_shift = (178, 153, 240),
            label      = fg(199, 146, 234),
        ),
        'fable':  ModelColors(
            anchor     = (255, 150, 170),
            warm_shift = (255, 120, 140),
            cool_shift = (240, 160, 180),
            label      = fg(255, 150, 170),
        ),
        'mythos': ModelColors(
            anchor     = (120, 200, 210),
            warm_shift = (100, 190, 220),
            cool_shift = (150, 180, 230),
            label      = fg(120, 200, 210),
        ),
    },

    pill_fg_dark  = ( 15,  15,  15),
    pill_fg_light = (235, 235, 235),

    grad_stops = (
        (0.00, (195, 232, 141)),
        (0.25, (255, 203, 107)),
        (0.50, (248, 158, 114)),
        (0.75, (240, 113, 120)),
        (1.00, (199, 146, 234)),
    ),
    grey_rgb    = (124, 126, 135),
    spark_stops = (
        (0.00, (212, 120, 129)),
        (0.50, (234, 130, 138)),
        (1.00, (255, 139, 146)),
    ),
    spec_gradients = (
        ((130, 170, 255), (137, 221, 255), (163, 247, 255)),  # Ocean
        ((240, 113, 120), (199, 146, 234), (255, 203, 107)),  # Sunset
        ((149, 176, 117), (195, 232, 141), (221, 255, 167)),  # Forest
        ((199, 146, 234), (130, 170, 255), (225, 172, 255)),  # Lavender
        ((240, 113, 120), (255, 139, 146), (255, 203, 107)),  # Ember
        ((130, 170, 255), (156, 196, 255), (163, 247, 255)),  # Arctic
        ((255, 203, 107), (240, 113, 120), (255, 229, 133)),  # Copper
        ((199, 146, 234), (225, 172, 255), (255, 139, 146)),  # Rose
        ((137, 221, 255), (195, 232, 141), (163, 247, 255)),  # Mint
        ((199, 146, 234), (130, 170, 255), (137, 221, 255)),  # Nebula
        ((137, 221, 255), (199, 146, 234), (130, 170, 255)),  # Aurora
        ((255, 203, 107), (240, 113, 120), (199, 146, 234)),  # Volcano
    ),
    spec_empty_ansi = fg256(233),
)


CATPPUCCIN_LATTE = Theme(
    name        = 'catppuccin-latte',

    border      = fg(158, 160, 175),
    border_off  = fg(174, 176, 189),
    pwd         = fg( 30, 102, 245),
    branch      = fg( 64, 160,  43),
    commit      = fg(182, 184, 196),
    session     = fg(182, 184, 196),
    skills      = fg(223, 142,  29),
    time        = fg(182, 184, 196),
    tok         = fg( 23, 146, 153),
    tok_dim     = fg(190, 192, 203),
    tok_day     = fg( 23, 146, 153),
    tok_day_dim = fg(190, 192, 203),
    cost        = fg(210,  15,  57),
    bar_fill    = fg( 64, 160,  43),
    bar_empty   = fg(174, 176, 189),
    dim_green   = fg( 64, 160,  43),
    label       = fg(182, 184, 196),
    ctx         = fg( 23, 146, 153),
    ctx_dim     = fg(158, 160, 175),
    white_brt   = fg( 76,  79, 105),
    arrow       = fg( 64, 160,  43),
    dirty       = fg(210,  15,  57),
    icon_path   = fg( 23, 146, 153),
    tok_icon    = fg(223, 142,  29),
    model       = fg( 30, 102, 245),

    safe        = fg( 64, 160,  43),
    warn        = fg(223, 142,  29),
    alert       = fg(210,  15,  57),
    yellow      = fg(223, 142,  29),
    tok_arrow   = fg(223, 142,  29),

    models = {
        'opus':   ModelColors(
            anchor     = (223, 142,  29),
            warm_shift = (218,  91,  40),
            cool_shift = (159, 149,  35),
            label      = fg(223, 142,  29),
        ),
        'sonnet': ModelColors(
            anchor     = ( 64, 160,  43),
            warm_shift = ( 48, 154,  87),
            cool_shift = ( 56, 146,  94),
            label      = fg( 64, 160,  43),
        ),
        'haiku':  ModelColors(
            anchor     = (  4, 165, 229),
            warm_shift = ( 15, 165, 200),
            cool_shift = ( 60, 140, 240),
            label      = fg(  4, 165, 229),
        ),
        'other':  ModelColors(
            anchor     = (234, 118, 203),
            warm_shift = (227,  87, 159),
            cool_shift = (173, 113, 216),
            label      = fg(234, 118, 203),
        ),
        'fable':  ModelColors(
            anchor     = (220,  90, 110),
            warm_shift = (210,  60,  80),
            cool_shift = (200, 110, 130),
            label      = fg(220,  90, 110),
        ),
        'mythos': ModelColors(
            anchor     = ( 90, 150, 190),
            warm_shift = ( 70, 140, 200),
            cool_shift = (120, 130, 210),
            label      = fg( 90, 150, 190),
        ),
    },

    pill_fg_dark  = ( 10,  10,  10),
    pill_fg_light = (250, 250, 250),

    grad_stops = (
        (0.00, ( 64, 160,  43)),
        (0.25, (223, 142,  29)),
        (0.50, (216,  78,  43)),
        (0.75, (210,  15,  57)),
        (1.00, (234, 118, 203)),
    ),
    grey_rgb    = (158, 160, 175),
    spark_stops = (
        (0.00, (216,  60,  95)),
        (0.50, (213,  38,  76)),
        (1.00, (210,  15,  57)),
    ),
    spec_gradients = (
        (( 30, 102, 245), ( 23, 146, 153), ( 23, 146, 153)),  # Ocean
        ((210,  15,  57), (234, 118, 203), (223, 142,  29)),  # Sunset
        (( 72, 140,  66), ( 64, 160,  43), ( 64, 160,  43)),  # Forest
        ((234, 118, 203), ( 30, 102, 245), (234, 118, 203)),  # Lavender
        ((210,  15,  57), (210,  15,  57), (223, 142,  29)),  # Ember
        (( 30, 102, 245), ( 30, 102, 245), ( 23, 146, 153)),  # Arctic
        ((223, 142,  29), (210,  15,  57), (223, 142,  29)),  # Copper
        ((234, 118, 203), (234, 118, 203), (210,  15,  57)),  # Rose
        (( 23, 146, 153), ( 64, 160,  43), ( 23, 146, 153)),  # Mint
        ((234, 118, 203), ( 30, 102, 245), ( 23, 146, 153)),  # Nebula
        (( 23, 146, 153), (234, 118, 203), ( 30, 102, 245)),  # Aurora
        ((223, 142,  29), (210,  15,  57), (234, 118, 203)),  # Volcano
    ),
    spec_empty_ansi = fg256(254),
)

CATPPUCCIN_MOCHA = Theme(
    name        = 'catppuccin-mocha',

    border      = fg(118, 122, 145),
    border_off  = fg(100, 104, 125),
    pwd         = fg(137, 180, 250),
    branch      = fg(166, 227, 161),
    commit      = fg( 91,  94, 115),
    session     = fg( 91,  94, 115),
    skills      = fg(249, 226, 175),
    time        = fg( 91,  94, 115),
    tok         = fg(148, 226, 213),
    tok_dim     = fg( 82,  85, 105),
    tok_day     = fg(148, 226, 213),
    tok_day_dim = fg( 82,  85, 105),
    cost        = fg(243, 139, 168),
    bar_fill    = fg(166, 227, 161),
    bar_empty   = fg( 69,  71,  90),
    dim_green   = fg(166, 227, 161),
    label       = fg( 91,  94, 115),
    ctx         = fg(148, 226, 213),
    ctx_dim     = fg( 69,  71,  90),
    white_brt   = fg(166, 173, 200),
    arrow       = fg(166, 227, 161),
    dirty       = fg(243, 139, 168),
    icon_path   = fg(148, 226, 213),
    tok_icon    = fg(249, 226, 175),
    model       = fg(137, 180, 250),

    safe        = fg(166, 227, 161),
    warn        = fg(249, 226, 175),
    alert       = fg(243, 139, 168),
    yellow      = fg(249, 226, 175),
    tok_arrow   = fg(249, 226, 175),

    models = {
        'opus':   ModelColors(
            anchor     = (249, 226, 175),
            warm_shift = (247, 191, 172),
            cool_shift = (216, 226, 169),
            label      = fg(249, 226, 175),
        ),
        'sonnet': ModelColors(
            anchor     = (166, 227, 161),
            warm_shift = (159, 227, 182),
            cool_shift = (159, 215, 183),
            label      = fg(166, 227, 161),
        ),
        'haiku':  ModelColors(
            anchor     = (137, 180, 250),
            warm_shift = (142, 203, 232),
            cool_shift = (169, 184, 244),
            label      = fg(137, 180, 250),
        ),
        'other':  ModelColors(
            anchor     = (245, 194, 231),
            warm_shift = (244, 178, 212),
            cool_shift = (213, 190, 237),
            label      = fg(245, 194, 231),
        ),
        'fable':  ModelColors(
            anchor     = (240, 150, 170),
            warm_shift = (235, 120, 150),
            cool_shift = (230, 160, 180),
            label      = fg(240, 150, 170),
        ),
        'mythos': ModelColors(
            anchor     = (150, 190, 220),
            warm_shift = (130, 180, 230),
            cool_shift = (170, 170, 230),
            label      = fg(150, 190, 220),
        ),
    },

    pill_fg_dark  = ( 15,  15,  15),
    pill_fg_light = (235, 235, 235),

    grad_stops = (
        (0.00, (166, 227, 161)),
        (0.25, (249, 226, 175)),
        (0.50, (246, 182, 172)),
        (0.75, (243, 139, 168)),
        (1.00, (245, 194, 231)),
    ),
    grey_rgb    = (118, 122, 145),
    spark_stops = (
        (0.00, (200, 117, 144)),
        (0.50, (222, 128, 156)),
        (1.00, (243, 139, 168)),
    ),
    spec_gradients = (
        ((137, 180, 250), (148, 226, 213), (148, 226, 213)),  # Ocean
        ((243, 139, 168), (245, 194, 231), (249, 226, 175)),  # Sunset
        ((137, 180, 140), (166, 227, 161), (166, 227, 161)),  # Forest
        ((245, 194, 231), (137, 180, 250), (245, 194, 231)),  # Lavender
        ((243, 139, 168), (243, 139, 168), (249, 226, 175)),  # Ember
        ((137, 180, 250), (137, 180, 250), (148, 226, 213)),  # Arctic
        ((249, 226, 175), (243, 139, 168), (249, 226, 175)),  # Copper
        ((245, 194, 231), (245, 194, 231), (243, 139, 168)),  # Rose
        ((148, 226, 213), (166, 227, 161), (148, 226, 213)),  # Mint
        ((245, 194, 231), (137, 180, 250), (148, 226, 213)),  # Nebula
        ((148, 226, 213), (245, 194, 231), (137, 180, 250)),  # Aurora
        ((249, 226, 175), (243, 139, 168), (245, 194, 231)),  # Volcano
    ),
    spec_empty_ansi = fg256(233),
)


THEMES: dict[str, Theme] = {
    CLAUDE_DARK.name:        CLAUDE_DARK,
    CLAUDE_LIGHT.name:       CLAUDE_LIGHT,
    CATPPUCCIN_LATTE.name:   CATPPUCCIN_LATTE,
    CATPPUCCIN_MOCHA.name:   CATPPUCCIN_MOCHA,
    DRACULA.name:            DRACULA,
    GRUVBOX_DARK.name:       GRUVBOX_DARK,
    GRUVBOX_LIGHT.name:      GRUVBOX_LIGHT,
    NORD.name:               NORD,
    ONE_DARK.name:           ONE_DARK,
    ONE_LIGHT.name:          ONE_LIGHT,
    SOLARIZED_DARK.name:     SOLARIZED_DARK,
    SOLARIZED_LIGHT.name:    SOLARIZED_LIGHT,
    TOKYO_NIGHT.name:        TOKYO_NIGHT,
    PALENIGHT.name:          PALENIGHT,
}


def resolve(name: str | None) -> Theme:
    if name and name in THEMES:
        return THEMES[name]
    return CLAUDE_DARK
