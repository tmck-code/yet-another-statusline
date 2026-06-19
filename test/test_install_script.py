"""Hermetic tests for ops/install.sh.

All tests run against a fresh CLAUDE_CONFIG_DIR and (where wire-only)
CLAUDE_PLUGIN_ROOT in tmp_path, so nothing touches ~/.claude.
"""

from __future__ import annotations

import json
import os
import subprocess
import tomllib
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
        # Force non-interactive so the mutating (non --dry-run) wire-only tests
        # never enter the wizard. is_interactive() keys off a *readable* /dev/tty
        # (intentional, for `curl | bash`), which is present whenever the suite
        # runs attached to a real terminal — without this the wizard blocks on
        # `read < /dev/tty` and the test hangs. CI has no tty, so it only bites
        # locally.
        'YAS_NO_TTY': '1',
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
# Task 7.2 — wire-only proves no jq dependency
# ---------------------------------------------------------------------------

def test_wire_only_works_without_jq(wire_env, tmp_path):
    """Run wire-only with a `jq` stub that always fails (and is first on PATH).

    If install.sh shelled `jq` anywhere, the stub's non-zero exit would corrupt
    the read/merge/validate and the wiring would break. A clean exit 0 with a
    correctly wired settings.json proves all JSON now goes through Python.
    """
    config_dir, plugin_root, env = wire_env
    stub_bin = tmp_path / 'stub_bin'
    stub_bin.mkdir()
    jq_stub = stub_bin / 'jq'
    jq_stub.write_text('#!/usr/bin/env bash\necho "jq must not be called" >&2\nexit 127\n')
    jq_stub.chmod(0o755)
    env = {**env, 'PATH': f'{stub_bin}:{os.environ["PATH"]}'}
    result = run_install(env_extra=env)
    assert result.returncode == 0, result.stderr
    assert 'jq must not be called' not in result.stderr
    settings = json.loads((config_dir / 'settings.json').read_text())
    script_path = str(plugin_root / 'claude' / 'statusline_command.py')
    assert script_path in settings['statusLine']['command']
    assert settings['statusLine']['type'] == 'command'


# ---------------------------------------------------------------------------
# Task 7.3 — uv bootstrap dry-run preview (hermetic, no network)
# ---------------------------------------------------------------------------

def test_wire_only_dry_run_previews_uv_bootstrap_when_uv_absent(wire_env, tmp_path):
    """With `uv` absent from PATH and --dry-run set, provision_python must report
    it would bootstrap uv → .uv, write nothing, and make no network call.

    PATH is scrubbed to a curated dir holding only the binaries install.sh needs
    (bash, python3, coreutils, find, grep, sed) plus a `curl` stub that fails if
    called — proving the dry-run path never fetches the installer.
    """
    config_dir, plugin_root, env = wire_env

    curated = tmp_path / 'curated_bin'
    curated.mkdir()
    # Symlink the real interpreters/coreutils install.sh relies on, but NOT uv.
    needed = [
        'bash', 'sh', 'env', 'python3', 'find', 'grep', 'sed', 'sort', 'head',
        'mktemp', 'date', 'dirname', 'basename', 'rm', 'cp', 'mv', 'cat',
        'printf', 'xargs', 'which',
    ]
    for tool in needed:
        src = subprocess.run(['which', tool], capture_output=True, text=True).stdout.strip()
        if src:
            (curated / tool).symlink_to(src)
    # curl stub: any invocation is a failure (the dry-run path must not fetch).
    curl_stub = curated / 'curl'
    curl_stub.write_text('#!/usr/bin/env bash\necho "curl must not be called in dry-run" >&2\nexit 99\n')
    curl_stub.chmod(0o755)

    env = {**env, 'PATH': str(curated)}
    result = run_install('--wire-only', '--dry-run', env_extra=env)
    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert 'Would bootstrap uv' in combined
    assert '.uv' in combined
    assert 'curl must not be called' not in combined
    # Dry-run writes nothing.
    assert not (config_dir / 'settings.json').exists()
    assert not (plugin_root / '.uv').exists()
    assert not (plugin_root / '.python').exists()


# ---------------------------------------------------------------------------
# Task 4.2 — dry-run assertions (full-mode decision logic)
#
# These tests run `--full --dry-run`.  They need `claude` and `curl`
# on PATH (preflight_full runs before --dry-run takes effect), plus a fake
# plugin root for do_wire to discover.
#
# `ensure_plugin` checks `.plugins | has("yas@yet-another-statusline")`.
# `do_wire` scans `.plugins` for any key whose ascii-lower contains "yas" to
# find the renderer installPath.  The fixtures seed installed_plugins.json with
# the yas key under `.plugins` to satisfy both checks.
# ---------------------------------------------------------------------------

# Guard: preflight_full requires claude and curl to be on PATH (jq is no longer
# a dependency — JSON goes through the resolved Python interpreter via json_py).
_PREFLIGHT_MISSING = [
    t for t in ('claude', 'curl')
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

    ensure_plugin reads: .plugins | has("yas@yet-another-statusline")
    do_wire reads:       .plugins[key with "yas"][].installPath
    """
    data = {
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
    assert 'would update marketplace' in combined


@requires_full_preflight
def test_dry_run_would_install_when_plugin_absent(full_dry_env):
    config_dir, plugin_root, env = full_dry_env
    # ensure_plugin checks `.plugins | has("yas@yet-another-statusline")`.
    # do_wire scans `.plugins` for any key where ascii_downcase contains "yas".
    # Use a different key name so ensure_plugin sees absent (→ "Would install")
    # while do_wire can still resolve the renderer path via the "yas"-containing key.
    data = {
        'plugins': {
            'yas-cached@yet-another-statusline': [{'installPath': str(plugin_root)}],
        },
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


# ---------------------------------------------------------------------------
# Task 7.4 — uninstall reports it would remove the .uv dir (dry-run, hermetic)
# ---------------------------------------------------------------------------

def test_uninstall_dry_run_reports_uv_dir_removal(uninstall_env, tmp_path):
    config_dir, env = uninstall_env
    plugin_root = tmp_path / 'plugin_root'
    uv_dir = plugin_root / '.uv'
    uv_dir.mkdir(parents=True)
    (uv_dir / 'uv').write_text('# fake bootstrapped uv\n')
    env = {**env, 'CLAUDE_PLUGIN_ROOT': str(plugin_root)}
    result = run_install('--uninstall', '--dry-run', env_extra=env)
    assert result.returncode == 0, result.stderr
    assert 'Would remove bootstrapped uv dir' in result.stdout
    assert str(uv_dir) in result.stdout
    # Dry-run leaves the dir in place.
    assert uv_dir.exists()


def test_uninstall_removes_uv_dir(uninstall_env, tmp_path):
    config_dir, env = uninstall_env
    plugin_root = tmp_path / 'plugin_root'
    uv_dir = plugin_root / '.uv'
    uv_dir.mkdir(parents=True)
    (uv_dir / 'uv').write_text('# fake bootstrapped uv\n')
    env = {**env, 'CLAUDE_PLUGIN_ROOT': str(plugin_root)}
    result = run_install('--uninstall', env_extra=env)
    assert result.returncode == 0, result.stderr
    assert 'Removed bootstrapped uv dir' in result.stdout
    assert not uv_dir.exists()


# ---------------------------------------------------------------------------
# Interactive installer — Python version policy + TTY gating
#
# NOTE: the live interactive TTY render path is NOT CI-testable (no terminal).
# These tests exercise the non-interactive / --dry-run branches only. --dry-run
# is treated as non-interactive by install.sh (a non-mutating preview never
# prompts), so even on a developer's real terminal these stay deterministic.
# ---------------------------------------------------------------------------

def test_dry_run_default_provisions_3_13(wire_env):
    """Task 10.1 — the non-interactive default provisions the stable 3.13."""
    config_dir, plugin_root, env = wire_env
    result = run_install('--wire-only', '--dry-run', env_extra=env)
    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert 'CPython 3.13' in combined
    assert 'private uv-managed 3.13' in combined
    # The default must NOT silently provision the prerelease 3.15. (The preflight
    # line legitimately reports the *system* Python version, which may itself be
    # 3.15 on some machines — only the provisioning messages must avoid it.)
    assert 'uv-managed 3.15' not in combined
    assert 'CPython 3.15' not in combined


def test_yas_no_tty_forces_non_interactive(wire_env):
    """Task 10.2 — YAS_NO_TTY=1 issues no prompts, writes no yas.toml, completes."""
    config_dir, plugin_root, env = wire_env
    env = {**env, 'YAS_NO_TTY': '1'}
    result = run_install('--wire-only', '--dry-run', env_extra=env)
    assert result.returncode == 0, result.stderr
    # No prompt text leaked, and no yas.toml was written under the config dir.
    assert 'Use Python 3.15' not in (result.stdout + result.stderr)
    assert not (config_dir / 'yas.toml').exists()


def test_yas_python_3_15_overrides_version(wire_env):
    """Task 10.3 — YAS_PYTHON=3.15 overrides the dry-run preview version."""
    config_dir, plugin_root, env = wire_env
    env = {**env, 'YAS_PYTHON': '3.15'}
    result = run_install('--wire-only', '--dry-run', env_extra=env)
    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert 'CPython 3.15' in combined
    assert 'private uv-managed 3.15' in combined


def test_reconfigure_non_interactive_errors_cleanly(wire_env):
    """Task 10.4 — --reconfigure with no TTY errors out without touching plugins.

    Reconfigure has no useful non-interactive behaviour, so it must error rather
    than silently doing nothing — and must never attempt marketplace/plugin mgmt.
    """
    config_dir, plugin_root, env = wire_env
    env = {**env, 'YAS_NO_TTY': '1'}
    result = run_install('--reconfigure', env_extra=env)
    assert result.returncode != 0
    combined = (result.stdout + result.stderr).lower()
    assert 'interactive' in combined
    # No plugin management attempted.
    assert 'marketplace' not in combined
    assert 'installing yas plugin' not in combined
    assert 'updating yas plugin' not in combined
    # Reconfigure writes no yas.toml when it cannot run.
    assert not (config_dir / 'yas.toml').exists()


def _source_build_yas_toml() -> str:
    """Extract the build_yas_toml bash function body from install.sh.

    The live interactive wizard cannot be driven in CI (no tty), so we exercise
    the pure template builder directly by sourcing just this function.
    """
    lines = INSTALL_SH.read_text().splitlines()
    out: list[str] = []
    capturing = False
    for line in lines:
        if line.startswith('build_yas_toml() {'):
            capturing = True
        if capturing:
            out.append(line)
            if line == '}':
                break
    assert out and out[-1] == '}', 'build_yas_toml not found in install.sh'
    return '\n'.join(out)


def test_build_yas_toml_carries_four_values_and_parses():
    """Task 10.5 — the generated yas.toml carries the four chosen values and is
    valid TOML (parsed with tomllib)."""
    func = _source_build_yas_toml()
    script = f'{func}\nbuild_yas_toml "ascii" "true" "dracula" "500000"\n'
    result = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    data = tomllib.loads(result.stdout)
    assert data['appearance']['glyphs']['mode'] == 'ascii'
    assert data['layout']['labels'] is True
    assert data['appearance']['theme'] == 'dracula'
    assert data['tokens']['soft_limit'] == 500000


# ---------------------------------------------------------------------------
# ANSI colorization — gating + alignment safety
#
# The installer emits 16-color SGR for its messages, gated on:
#   color ON iff (stdout is a tty AND NO_COLOR unset AND TERM != dumb)
#               OR YAS_FORCE_COLOR=1   — and NO_COLOR set always wins (off).
#
# Under pytest stdout is captured (not a tty) and the suite never sets
# YAS_FORCE_COLOR, so color is OFF by default and every plain-text assertion
# above still holds. The tests below force color on the message paths (the
# "YAS!" logo is interactive-only and unreachable from these non-tty paths) and
# prove (a) the gate and (b) that color wrapping never splits a phrase.
# ---------------------------------------------------------------------------

def test_no_color_when_piped_by_default(uninstall_env):
    """Captured (non-tty) output with no YAS_FORCE_COLOR carries no ESC byte."""
    config_dir, env = uninstall_env
    result = run_install('--uninstall', '--dry-run', env_extra=env)
    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert '\x1b' not in combined


def test_no_color_respects_NO_COLOR_env(uninstall_env):
    """NO_COLOR wins even when YAS_FORCE_COLOR=1 is also set — output stays plain."""
    config_dir, env = uninstall_env
    env = {**env, 'YAS_FORCE_COLOR': '1', 'NO_COLOR': '1'}
    result = run_install('--uninstall', '--dry-run', env_extra=env)
    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert '\x1b' not in combined


def test_force_color_emits_ansi(uninstall_env):
    """YAS_FORCE_COLOR=1 emits an ESC byte on a message path, phrase intact."""
    config_dir, env = uninstall_env
    env = {**env, 'YAS_FORCE_COLOR': '1'}
    result = run_install('--uninstall', '--dry-run', env_extra=env)
    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert '\x1b' in combined
    # Color wrapping must not split the phrase apart.
    assert 'Would remove statusLine' in result.stdout


def test_force_color_failure_is_red(wire_env):
    """A forced-color failure path emits the red SGR code, error phrase intact.

    --reconfigure with no TTY is the most deterministic/hermetic failure path:
    it errors before any plugin/marketplace work and needs no claude/curl/uv.
    """
    config_dir, plugin_root, env = wire_env
    env = {**env, 'YAS_NO_TTY': '1', 'YAS_FORCE_COLOR': '1'}
    result = run_install('--reconfigure', env_extra=env)
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert '\x1b[31m' in combined
    # The error message survives color wrapping.
    assert 'interactive' in combined.lower()


def test_existing_phrases_survive_under_force_color(uninstall_env):
    """Existing dry-run substrings remain verbatim under YAS_FORCE_COLOR=1.

    Proves SGR escapes wrap whole messages and are never interleaved into the
    phrases the rest of the suite relies on. Covers both an uninstall dry-run
    phrase and a wire-only dry-run phrase (built in a sibling dir so the two
    runs stay hermetically separate).
    """
    config_dir, env = uninstall_env

    # Uninstall dry-run phrase.
    un_env = {**env, 'YAS_FORCE_COLOR': '1'}
    un_result = run_install('--uninstall', '--dry-run', env_extra=un_env)
    assert un_result.returncode == 0, un_result.stderr
    assert 'Would remove statusLine' in un_result.stdout

    # Wire-only dry-run phrase (default 3.13). Build a fresh plugin root + a
    # distinct config dir under the same tmp tree to avoid clobbering above.
    home        = Path(env['HOME'])
    wire_config = home / 'wire_config'
    wire_config.mkdir()
    plugin_root = home / 'wire_plugin_root'
    (plugin_root / 'claude').mkdir(parents=True)
    (plugin_root / 'claude' / 'statusline_command.py').write_text('# fake renderer\n')
    wire_env_extra = {
        'CLAUDE_CONFIG_DIR':  str(wire_config),
        'CLAUDE_PLUGIN_ROOT': str(plugin_root),
        'HOME':               str(home),
        'YAS_FORCE_COLOR':    '1',
    }
    wire_result = run_install('--wire-only', '--dry-run', env_extra=wire_env_extra)
    assert wire_result.returncode == 0, wire_result.stderr
    combined = wire_result.stdout + wire_result.stderr
    assert 'private uv-managed 3.13' in combined
    # Color codes must never inject the prerelease version into the default path.
    assert '3.15' not in combined
