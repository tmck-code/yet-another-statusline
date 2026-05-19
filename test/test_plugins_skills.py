import statusline_command as sl
from conftest import strip_ansi

_visible_width = sl._visible_width
Renderer = sl.Renderer


def test_plugins_skills_all_three_groups():
    r = Renderer()
    out = r.plugins_skills(
        skills_count=1,
        skills_names='tdd',
        plugin_names='foo,bar',
        subagents=[('Explore', 'find X - something')],
    )
    stripped = strip_ansi(out)
    assert 'tdd' in stripped
    assert 'foo,bar' in stripped
    assert 'find X' in stripped
    assert stripped.count('|') == 2


def test_plugins_skills_only_skills():
    r = Renderer()
    out = r.plugins_skills(
        skills_count=1,
        skills_names='tdd',
        plugin_names='',
        subagents=None,
    )
    stripped = strip_ansi(out)
    assert 'tdd' in stripped
    assert '|' not in stripped


def test_plugins_skills_nothing():
    r = Renderer()
    out = r.plugins_skills(
        skills_count=0,
        skills_names='',
        plugin_names='',
        subagents=None,
    )
    assert out == ''
