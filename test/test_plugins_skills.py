import yas.renderer as renderer
from helper import strip_ansi

Renderer = renderer.Renderer


def test_plugins_skills_skills_and_plugins() -> None:
    r = Renderer()
    out = r.plugins_skills(
        skills_count=1,
        skills_names='tdd',
        plugin_names='foo,bar',
    )
    stripped = strip_ansi(out)
    assert 'tdd' in stripped
    assert 'foo,bar' in stripped
    assert stripped.count('|') == 1


def test_plugins_skills_only_skills() -> None:
    r = Renderer()
    out = r.plugins_skills(
        skills_count=1,
        skills_names='tdd',
        plugin_names='',
    )
    stripped = strip_ansi(out)
    assert 'tdd' in stripped
    assert '|' not in stripped


def test_plugins_skills_nothing() -> None:
    r = Renderer()
    out = r.plugins_skills(
        skills_count=0,
        skills_names='',
        plugin_names='',
    )
    assert out == ''
