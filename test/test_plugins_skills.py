import yas.renderer as renderer
from helper import strip_ansi

Renderer = renderer.Renderer
_r = Renderer()


def test_plugins_skills_skills_and_plugins() -> None:
    out = _r.plugins_skills(
        skills_count=1,
        skills_names='tdd',
        plugin_names='foo,bar',
    )
    stripped = strip_ansi(out)
    assert 'tdd' in stripped
    assert 'foo,bar' in stripped
    assert stripped.count('|') == 1


def test_plugins_skills_only_skills() -> None:
    out = _r.plugins_skills(
        skills_count=1,
        skills_names='tdd',
        plugin_names='',
    )
    stripped = strip_ansi(out)
    assert 'tdd' in stripped
    assert '|' not in stripped


def test_plugins_skills_nothing() -> None:
    out = _r.plugins_skills(
        skills_count=0,
        skills_names='',
        plugin_names='',
    )
    assert out == ''


def test_plugins_skills_show_icons_false_reserves_one_col_margin() -> None:
    """With no glyph to reserve the row's left margin, plugins_skills falls
    back to a single literal leading space -- matching path_git/tokens_cost's
    fallback -- so this row's left margin lines up with the rest of the box."""
    out = _r.plugins_skills(
        skills_count=1, skills_names='tdd', plugin_names='', show_icons=False,
    )
    stripped = strip_ansi(out)
    assert stripped.startswith(' tdd')


def test_plugins_skills_show_icons_false_nothing_stays_empty() -> None:
    # No leading-margin space should leak in when there's nothing to show.
    out = _r.plugins_skills(
        skills_count=0, skills_names='', plugin_names='', show_icons=False,
    )
    assert out == ''


def test_plugins_skills_show_icons_true_unchanged() -> None:
    """The icons-on row already reserves its own margin via the glyph; the
    icons-off fallback space must not leak into this path."""
    on_default  = _r.plugins_skills(skills_count=1, skills_names='tdd', plugin_names='')
    on_explicit = _r.plugins_skills(skills_count=1, skills_names='tdd', plugin_names='', show_icons=True)
    assert on_default == on_explicit
