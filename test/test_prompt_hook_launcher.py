'''hooks/yas-prompt-hook.sh picks the interpreter for the plugin's prompt hook.'''
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_LAUNCHER = Path(__file__).resolve().parent.parent / 'hooks' / 'yas-prompt-hook.sh'

pytestmark = pytest.mark.skipif(shutil.which('sh') is None, reason='needs a POSIX sh')


def _fake_python(path: Path, tag: str) -> None:
    '''A stand-in interpreter that prints its tag and the script it was given.'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'#!/bin/sh\necho "{tag} $1"\n', newline='\n')
    path.chmod(0o755)


def _run(root: Path, path_dir: Path) -> str:
    (root / 'hooks').mkdir(parents=True, exist_ok=True)
    launcher = root / 'hooks' / 'yas-prompt-hook.sh'
    shutil.copy(_LAUNCHER, launcher)
    env = {**os.environ, 'PATH': f'{path_dir}{os.pathsep}{os.environ["PATH"]}'}
    proc = subprocess.run(['sh', str(launcher)], capture_output=True, text=True, env=env, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_prefers_provisioned_python(tmp_path):
    root = tmp_path / 'plugin'
    _fake_python(root / '.python' / 'cpython-3.13-test' / 'bin' / 'python3', 'provisioned')
    _fake_python(tmp_path / 'bin' / 'python3', 'path')

    out = _run(root, tmp_path / 'bin')

    tag, script = out.split(' ', 1)
    assert tag == 'provisioned'
    assert script.endswith('hooks/yas-prompt-hook.py')


def test_falls_back_to_python3_on_path(tmp_path):
    root = tmp_path / 'plugin'
    _fake_python(tmp_path / 'bin' / 'python3', 'path')

    out = _run(root, tmp_path / 'bin')

    assert out.split(' ', 1)[0] == 'path'
