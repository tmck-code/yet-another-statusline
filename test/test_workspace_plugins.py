"""Tests for Workspace.plugins (reads the user's trusted global settings only)."""
import json
from pathlib import Path

import statusline_command as sl


def _write_settings(path: Path, plugins: dict[str, bool]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'enabledPlugins': plugins}))


def test_plugins_from_home_only_project_ignored(tmp_home: Path, tmp_path: Path) -> None:
    """SEC-2: only the user's trusted global settings contribute plugins; a
    (possibly cloned/attacker-authored) project settings.json is NOT read."""
    _write_settings(tmp_home / '.claude' / 'settings.json', {'foo@1.0': True})
    project_dir = tmp_path / 'myproject'
    _write_settings(project_dir / '.claude' / 'settings.json', {'bar@2.0': True})

    ws = sl.Workspace(project_dir=str(project_dir))
    result = ws.plugins
    assert 'foo' in result
    assert 'bar' not in result  # project-local plugin must be ignored


def test_false_values_excluded(tmp_home: Path) -> None:
    """False values are excluded from plugins."""
    _write_settings(tmp_home / '.claude' / 'settings.json', {'foo@1.0': False})

    ws = sl.Workspace()
    result = ws.plugins
    assert 'foo' not in result


def test_duplicates_collapsed(tmp_home: Path) -> None:
    """Multiple enabled plugins in home settings render once each, in order."""
    _write_settings(tmp_home / '.claude' / 'settings.json', {'foo@1.0': True, 'foo@2.0': True})

    ws = sl.Workspace()
    result = ws.plugins
    assert result.split(',').count('foo') == 1


def test_malformed_home_json_silently_skipped(tmp_home: Path) -> None:
    """Malformed JSON in the global settings is silently skipped (no crash, no plugins)."""
    home_settings = tmp_home / '.claude' / 'settings.json'
    home_settings.parent.mkdir(parents=True, exist_ok=True)
    home_settings.write_text('not valid json')

    ws = sl.Workspace()
    assert ws.plugins == ''
