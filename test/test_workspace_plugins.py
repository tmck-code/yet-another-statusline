"""Tests for Workspace.plugins (merges settings.json files)."""
import json
from pathlib import Path

import yas.session as session


def _write_settings(path: Path, plugins: dict[str, bool]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'enabledPlugins': plugins}))


def test_plugins_merged_from_home_and_project(tmp_home: Path, tmp_path: Path, monkeypatch) -> None:
    """Plugins from home and project settings are merged."""
    monkeypatch.setattr(session, 'CLAUDE_DIR', tmp_home / '.claude')
    _write_settings(tmp_home / '.claude' / 'settings.json', {'foo@1.0': True})
    project_dir = tmp_path / 'myproject'
    _write_settings(project_dir / '.claude' / 'settings.json', {'bar@2.0': True})

    ws = session.Workspace(project_dir=str(project_dir))
    result = ws.plugins
    assert 'foo' in result
    assert 'bar' in result


def test_false_values_excluded(tmp_home: Path, monkeypatch) -> None:
    """False values are excluded from plugins."""
    monkeypatch.setattr(session, 'CLAUDE_DIR', tmp_home / '.claude')
    _write_settings(tmp_home / '.claude' / 'settings.json', {'foo@1.0': False})

    ws = session.Workspace()
    result = ws.plugins
    assert 'foo' not in result


def test_duplicates_collapsed_first_seen_order(tmp_home: Path, tmp_path: Path, monkeypatch) -> None:
    """Duplicates collapsed; first-seen order preserved."""
    monkeypatch.setattr(session, 'CLAUDE_DIR', tmp_home / '.claude')
    # foo appears in both home (first) and project (second)
    _write_settings(tmp_home / '.claude' / 'settings.json', {'foo@1.0': True})
    project_dir = tmp_path / 'proj'
    _write_settings(project_dir / '.claude' / 'settings.json', {'foo@1.0': True})

    ws = session.Workspace(project_dir=str(project_dir))
    result = ws.plugins
    assert result.split(',').count('foo') == 1


def test_malformed_json_silently_skipped(tmp_home: Path, tmp_path: Path, monkeypatch) -> None:
    """Malformed JSON in one file is silently skipped; other file still read."""
    monkeypatch.setattr(session, 'CLAUDE_DIR', tmp_home / '.claude')
    # Write invalid JSON to home settings
    home_settings = tmp_home / '.claude' / 'settings.json'
    home_settings.parent.mkdir(parents=True, exist_ok=True)
    home_settings.write_text('not valid json')

    project_dir = tmp_path / 'proj'
    _write_settings(project_dir / '.claude' / 'settings.json', {'bar@2.0': True})

    ws = session.Workspace(project_dir=str(project_dir))
    result = ws.plugins
    assert 'bar' in result
    assert 'foo' not in result
