import json
import types
from pathlib import Path

import pytest

import statusline_command as sl
from helper import strip_ansi

_visible_width = sl._visible_width
Renderer = sl.Renderer

_EXAMPLE = Path(__file__).resolve().parent.parent / 'claude' / 'statusline' / 'session-info-example.json'


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


# UX4: the row must budget to the box width and never overflow (it was the only
# content row with no width param — it ignored width entirely and ran off the
# right border with real skills/plugins lists).

def test_plugins_skills_width_zero_is_legacy_untruncated() -> None:
    r = Renderer()
    assert r.plugins_skills(1, 'tdd', 'foo,bar') == r.plugins_skills(1, 'tdd', 'foo,bar', 0)


def test_plugins_skills_truncates_to_width() -> None:
    r = Renderer()
    skills  = ','.join(f'skill-number-{i}' for i in range(12))
    plugins = ','.join(f'plugin-name-{i}' for i in range(12))
    for width in (80, 90, 100, 120, 140):
        out = r.plugins_skills(12, skills, plugins, width)
        # border_line allows at most width-3 of visible content before it overflows.
        assert _visible_width(out) <= width - 3, (width, _visible_width(out))


def test_plugins_skills_long_content_gets_ellipsis() -> None:
    r = Renderer()
    out = strip_ansi(r.plugins_skills(40, ','.join('xxxxxxxx' for _ in range(40)), 'yyyyyyyy', 100))
    assert '…' in out


def test_build_wide_no_overflow_with_long_skills_plugins(
    monkeypatch: pytest.MonkeyPatch, tmp_home: Path,
) -> None:
    # Integration guard: the *wide* layout must pass its width down to
    # plugins_skills so the rendered row stays inside the box border.
    monkeypatch.setattr(
        sl.LoadedSkills, 'from_transcript',
        staticmethod(lambda *a, **k: types.SimpleNamespace(names=[f'skill-number-{i}' for i in range(10)])),
    )
    monkeypatch.setattr(
        sl.Workspace, 'plugins',
        property(lambda self: ','.join(f'plugin-name-{i}' for i in range(10))),
    )
    sess = sl.SessionInfo.from_dict(json.loads(_EXAMPLE.read_text()))
    for width in (80, 100, 120, 140):
        out = '\n'.join(sl.render_layout(sl.build_wide(sess, width, Renderer()), Renderer()))
        for line in out.split('\n'):
            assert _visible_width(line) <= width, (width, _visible_width(line), strip_ansi(line))
