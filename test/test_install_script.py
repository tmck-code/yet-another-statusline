"""Hermetic tests for ops/install.sh.

All tests run against a fresh CLAUDE_CONFIG_DIR and (where wire-only)
CLAUDE_PLUGIN_ROOT in tmp_path, so nothing touches ~/.claude.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = REPO_ROOT / 'ops' / 'install.sh'


def run_install(
    *args: str,
    env_extra: dict | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess:
    env = {**os.environ, **(env_extra or {})}
    return subprocess.run(
        ['bash', str(INSTALL_SH), *args],
        env            = env,
        capture_output = True,
        text           = True,
    )


# ---------------------------------------------------------------------------
# Task 4.1 — hermetic wire-only tests
# ---------------------------------------------------------------------------

@pytest.fixture
def wire_env(tmp_path: Path) -> tuple[Path, Path, dict]:
    """Returns (claude_config_dir, plugin_root, env_extra)."""
    config_dir  = tmp_path / 'claude_config'
    config_dir.mkdir()
    plugin_root = tmp_path / 'plugin_root'
    (plugin_root / 'claude').mkdir(parents=True)
    (plugin_root / 'claude' / 'statusline_command.py').write_text('# fake renderer\n')
    env = {
        'CLAUDE_CONFIG_DIR': str(config_dir),
        'CLAUDE_PLUGIN_ROOT': str(plugin_root),
        'HOME': str(tmp_path),
    }
    return config_dir, plugin_root, env


def test_wire_only_writes_settings(wire_env):
    config_dir, plugin_root, env = wire_env
    result = run_install(env_extra=env)
    assert result.returncode == 0, result.stderr
    settings    = json.loads((config_dir / 'settings.json').read_text())
    script_path = str(plugin_root / 'claude' / 'statusline_command.py')
    # command should be: "<python>" "<script_path>"
    cmd = settings['statusLine']['command']
    assert script_path in cmd
    assert settings['statusLine']['async'] is True
    assert settings['statusLine']['type'] == 'command'


def test_wire_only_backup_created(wire_env):
    config_dir, plugin_root, env = wire_env
    # Pre-seed settings.json with a different command so a backup is taken.
    (config_dir / 'settings.json').write_text(
        json.dumps({'statusLine': {'command': '"python" "/old/path.py"'}})
    )
    result = run_install(env_extra=env)
    assert result.returncode == 0, result.stderr
    baks = list(config_dir.glob('settings.json.bak-yas-*'))
    assert len(baks) == 1


def test_wire_only_exact_match_skip(wire_env):
    config_dir, plugin_root, env = wire_env
    # First run: write the correct command.
    result1 = run_install(env_extra=env)
    assert result1.returncode == 0, result1.stderr
    mtime1 = (config_dir / 'settings.json').stat().st_mtime
    # Second run: settings already match — should skip.
    result2 = run_install(env_extra=env)
    assert result2.returncode == 0, result2.stderr
    assert 'skipping' in result2.stdout.lower()
    mtime2 = (config_dir / 'settings.json').stat().st_mtime
    assert mtime1 == mtime2  # file not re-written


def test_wire_only_removes_legacy_files(wire_env):
    config_dir, plugin_root, env = wire_env
    legacy1 = config_dir / 'statusline-info-abc123'
    legacy2 = config_dir / 'statusline-info-xyz789.json'
    legacy1.write_text('old')
    legacy2.write_text('old')
    result = run_install(env_extra=env)
    assert result.returncode == 0, result.stderr
    assert not legacy1.exists()
    assert not legacy2.exists()


def test_wire_only_output_is_valid_json(wire_env):
    config_dir, plugin_root, env = wire_env
    # Pre-seed with valid JSON that carries extra keys — they must survive.
    (config_dir / 'settings.json').write_text(
        json.dumps({'theme': 'dark', 'other': 123})
    )
    result = run_install(env_extra=env)
    assert result.returncode == 0, result.stderr
    data = json.loads((config_dir / 'settings.json').read_text())
    assert 'statusLine' in data
    assert data['theme'] == 'dark'   # existing key preserved
    assert data['other'] == 123


# ---------------------------------------------------------------------------
# Task 4.2 — dry-run assertions (full-mode decision logic)
#
# These tests run `--full --dry-run`.  They need `claude`, `curl`, and `jq`
# on PATH (preflight_full runs before --dry-run takes effect), plus a fake
# plugin root for do_wire to discover.
#
# `ensure_plugin` checks `has("yas@yet-another-statusline")` at the TOP-LEVEL
# of installed_plugins.json (not nested under .plugins).  `do_wire` then reads
# .plugins[...].installPath to find the renderer.  The fixtures therefore put
# the yas key BOTH at the top level (for ensure_plugin) and under .plugins (for
# do_wire).
# ---------------------------------------------------------------------------

# Guard: preflight_full requires claude, curl, and jq to be on PATH.
_PREFLIGHT_MISSING = [
    t for t in ('claude', 'curl', 'jq')
    if subprocess.run(['which', t], capture_output=True).returncode != 0
]
requires_full_preflight = pytest.mark.skipif(
    bool(_PREFLIGHT_MISSING),
    reason=f'full-mode preflight tools missing from PATH: {_PREFLIGHT_MISSING}',
)


@pytest.fixture
def full_dry_env(tmp_path: Path) -> tuple[Path, Path, dict]:
    """Returns (config_dir, plugin_root, env_extra).

    plugin_root has a real fake renderer so do_wire can resolve PLUGIN_ROOT
    from the seeded installed_plugins.json entry.
    """
    config_dir  = tmp_path / 'claude_config'
    plugin_root = tmp_path / 'plugin_root'
    (config_dir / 'plugins').mkdir(parents=True)
    (plugin_root / 'claude').mkdir(parents=True)
    (plugin_root / 'claude' / 'statusline_command.py').write_text('# fake renderer\n')
    env = {
        'CLAUDE_CONFIG_DIR': str(config_dir),
        'HOME':              str(tmp_path),
        # Empty string → [ -n "" ] is false → mode auto-detect falls to full.
        # --full is passed explicitly anyway, but keep this for clarity.
        'CLAUDE_PLUGIN_ROOT': '',
    }
    return config_dir, plugin_root, env


def _seed_installed_plugins(config_dir: Path, plugin_root: Path) -> None:
    """Write installed_plugins.json so both ensure_plugin and do_wire are happy.

    ensure_plugin reads: has("yas@yet-another-statusline") at top level.
    do_wire reads:       .plugins["yas@yet-another-statusline"][].installPath
    """
    data = {
        # Top-level key: satisfies ensure_plugin's has() check.
        'yas@yet-another-statusline': [{'installPath': str(plugin_root)}],
        # .plugins key: satisfies do_wire's jq path.
        'plugins': {
            'yas@yet-another-statusline': [{'installPath': str(plugin_root)}],
        },
    }
    (config_dir / 'plugins' / 'installed_plugins.json').write_text(json.dumps(data))


@requires_full_preflight
def test_dry_run_would_add_marketplace_when_absent(full_dry_env):
    config_dir, plugin_root, env = full_dry_env
    _seed_installed_plugins(config_dir, plugin_root)
    # No known_marketplaces.json → absent → "Would add marketplace"
    result = run_install('--full', '--dry-run', env_extra=env)
    assert result.returncode == 0, result.stderr
    assert 'Would add marketplace' in result.stdout


@requires_full_preflight
def test_dry_run_marketplace_already_present(full_dry_env):
    config_dir, plugin_root, env = full_dry_env
    _seed_installed_plugins(config_dir, plugin_root)
    # ensure_marketplace checks has("yet-another-statusline") at the top level.
    (config_dir / 'plugins' / 'known_marketplaces.json').write_text(
        json.dumps({'yet-another-statusline': {'url': 'x'}})
    )
    result = run_install('--full', '--dry-run', env_extra=env)
    assert result.returncode == 0, result.stderr
    combined = result.stdout.lower()
    assert 'already present' in combined or 'skipping' in combined


@requires_full_preflight
def test_dry_run_would_install_when_plugin_absent(full_dry_env):
    config_dir, plugin_root, env = full_dry_env
    # No installed_plugins.json → has() returns false → "Would install"
    # But do_wire still needs to find the plugin root, so we can't omit the
    # file entirely from the filesystem — we can leave it absent and accept
    # that do_wire will fail after the dry-run install message.  However the
    # spec says dry-run should print "Would install" and exit 0.
    #
    # The script: ensure_plugin prints "Would install" (DRY_RUN=1), then
    # do_wire tries to find PLUGIN_ROOT from installed_plugins.json which is
    # absent → exits 1.  So we seed a minimal installed_plugins.json that
    # does NOT have the top-level yas key (triggering install path) but DOES
    # have the .plugins entry so do_wire can resolve the renderer path.
    data = {
        # .plugins key satisfies do_wire discovery.
        'plugins': {
            'yas@yet-another-statusline': [{'installPath': str(plugin_root)}],
        },
        # Note: 'yas@yet-another-statusline' is NOT a top-level key here,
        # so ensure_plugin sees has() == false → "Would install".
    }
    (config_dir / 'plugins' / 'installed_plugins.json').write_text(json.dumps(data))
    result = run_install('--full', '--dry-run', env_extra=env)
    assert result.returncode == 0, result.stderr
    assert 'Would install' in result.stdout


@requires_full_preflight
def test_dry_run_would_update_when_plugin_present(full_dry_env):
    config_dir, plugin_root, env = full_dry_env
    _seed_installed_plugins(config_dir, plugin_root)
    result = run_install('--full', '--dry-run', env_extra=env)
    assert result.returncode == 0, result.stderr
    assert 'Would update' in result.stdout


@requires_full_preflight
def test_dry_run_does_not_touch_settings(full_dry_env):
    config_dir, plugin_root, env = full_dry_env
    _seed_installed_plugins(config_dir, plugin_root)
    settings_path = config_dir / 'settings.json'
    result = run_install('--full', '--dry-run', env_extra=env)
    assert result.returncode == 0, result.stderr
    assert not settings_path.exists()


# ---------------------------------------------------------------------------
# Uninstall tests
# ---------------------------------------------------------------------------

@pytest.fixture
def uninstall_env(tmp_path: Path) -> tuple[Path, dict]:
    """Returns (config_dir, env_extra) with settings.json pre-wired."""
    config_dir = tmp_path / 'claude_config'
    config_dir.mkdir()
    (config_dir / 'plugins').mkdir()
    settings = {
        'theme': 'dark',
        'statusLine': {
            'async': True,
            'command': '"python3" "/some/path/statusline_command.py"',
            'refreshInterval': 1,
            'type': 'command',
        },
    }
    (config_dir / 'settings.json').write_text(json.dumps(settings))
    env = {
        'CLAUDE_CONFIG_DIR': str(config_dir),
        'HOME':              str(tmp_path),
        'CLAUDE_PLUGIN_ROOT': '',
    }
    return config_dir, env


def test_uninstall_removes_status_line(uninstall_env):
    config_dir, env = uninstall_env
    result = run_install('--uninstall', env_extra=env)
    assert result.returncode == 0, result.stderr
    data = json.loads((config_dir / 'settings.json').read_text())
    assert 'statusLine' not in data
    assert data.get('theme') == 'dark'  # other keys preserved


def test_uninstall_creates_backup(uninstall_env):
    config_dir, env = uninstall_env
    result = run_install('--uninstall', env_extra=env)
    assert result.returncode == 0, result.stderr
    baks = list(config_dir.glob('settings.json.bak-yas-*'))
    assert len(baks) == 1


def test_uninstall_no_settings_is_noop(tmp_path):
    config_dir = tmp_path / 'claude_config'
    config_dir.mkdir()
    env = {'CLAUDE_CONFIG_DIR': str(config_dir), 'HOME': str(tmp_path), 'CLAUDE_PLUGIN_ROOT': ''}
    result = run_install('--uninstall', env_extra=env)
    assert result.returncode == 0, result.stderr
    assert 'nothing to unwire' in result.stdout.lower()


def test_uninstall_no_status_line_key_is_noop(tmp_path):
    config_dir = tmp_path / 'claude_config'
    config_dir.mkdir()
    (config_dir / 'settings.json').write_text(json.dumps({'theme': 'dark'}))
    env = {'CLAUDE_CONFIG_DIR': str(config_dir), 'HOME': str(tmp_path), 'CLAUDE_PLUGIN_ROOT': ''}
    result = run_install('--uninstall', env_extra=env)
    assert result.returncode == 0, result.stderr
    assert 'nothing to unwire' in result.stdout.lower()
    # File is unchanged
    data = json.loads((config_dir / 'settings.json').read_text())
    assert data == {'theme': 'dark'}


def test_uninstall_removes_legacy_files(uninstall_env):
    config_dir, env = uninstall_env
    legacy = config_dir / 'statusline-info-abc123'
    legacy.write_text('old')
    result = run_install('--uninstall', env_extra=env)
    assert result.returncode == 0, result.stderr
    assert not legacy.exists()


def test_uninstall_dry_run_no_changes(uninstall_env):
    config_dir, env = uninstall_env
    mtime_before = (config_dir / 'settings.json').stat().st_mtime
    result = run_install('--uninstall', '--dry-run', env_extra=env)
    assert result.returncode == 0, result.stderr
    assert 'Would remove statusLine' in result.stdout
    # File untouched
    mtime_after = (config_dir / 'settings.json').stat().st_mtime
    assert mtime_before == mtime_after
    assert not list(config_dir.glob('settings.json.bak-yas-*'))
