"""Tests for Workspace.plugins (merges settings.json files)."""
import json

import statusline_command as sl


def _write_settings(path, plugins: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'enabledPlugins': plugins}))


def test_plugins_merged_from_home_and_project(tmp_home, tmp_path):
    """8.2 Plugins from home and project settings are merged."""
    _write_settings(tmp_home / '.claude' / 'settings.json', {'foo@1.0': True})
    project_dir = tmp_path / 'myproject'
    _write_settings(project_dir / '.claude' / 'settings.json', {'bar@2.0': True})

    ws = sl.Workspace(project_dir=str(project_dir))
    result = ws.plugins
    assert 'foo' in result
    assert 'bar' in result


def test_false_values_excluded(tmp_home):
    """8.3 False values are excluded from plugins."""
    _write_settings(tmp_home / '.claude' / 'settings.json', {'foo@1.0': False})

    ws = sl.Workspace()
    result = ws.plugins
    assert 'foo' not in result


def test_duplicates_collapsed_first_seen_order(tmp_home, tmp_path):
    """8.4 Duplicates collapsed; first-seen order preserved."""
    # foo appears in both home (first) and project (second)
    _write_settings(tmp_home / '.claude' / 'settings.json', {'foo@1.0': True})
    project_dir = tmp_path / 'proj'
    _write_settings(project_dir / '.claude' / 'settings.json', {'foo@1.0': True})

    ws = sl.Workspace(project_dir=str(project_dir))
    result = ws.plugins
    assert result.split(',').count('foo') == 1


def test_malformed_json_silently_skipped(tmp_home, tmp_path):
    """8.5 Malformed JSON in one file is silently skipped; other file still read."""
    # Write invalid JSON to home settings
    home_settings = tmp_home / '.claude' / 'settings.json'
    home_settings.parent.mkdir(parents=True, exist_ok=True)
    home_settings.write_text('not valid json')

    project_dir = tmp_path / 'proj'
    _write_settings(project_dir / '.claude' / 'settings.json', {'bar@2.0': True})

    ws = sl.Workspace(project_dir=str(project_dir))
    result = ws.plugins
    assert 'bar' in result
    assert 'foo' not in result
