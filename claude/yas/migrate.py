"""One-shot migration from the pre-0.9 flat ~/.claude layout to the yas/cache+state layout in yas.constants."""

from __future__ import annotations
import json
import os
import re
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from yas import constants
from yas.constants import (
    LAYOUT_SCHEMA_VERSION,
    VERSION,
    cache_dir,
    last_prompt_path,
    runtime_dir,
    sessions_dir,
    signals_dir,
    state_dir,
    terminal_width_path,
    tokens_log,
    version_file,
)

# legacy basename -> new-path callable, resolved at call time so a patched CLAUDE_DIR is honoured
_MOVES: tuple[tuple[str, Callable[[], Path]], ...] = (
    ('statusline-tokens.log', tokens_log),
    ('yas-last-prompt.json', last_prompt_path),
    ('terminal-width', terminal_width_path),
)

# legacy files with no new-layout home, deleted outright ('statusline-theme' is handled separately below)
_DELETE_FILES: tuple[str, ...] = (
    'statusline-token-rate.log',
    'statusline-render.log',
    'yas.toml.cache',
)

_DELETE_DIRS: tuple[str, ...] = (
    'statusline-output',
)


def _move(src: Path, dst: Path, *, verbose: bool = False) -> None:
    """Move src to dst; never clobbers an existing dst."""
    if dst.exists():
        return
    if not src.exists():
        return
    os.rename(src, dst)
    if verbose:
        try:
            rel_dst = dst.relative_to(constants.CLAUDE_DIR)
        except ValueError:
            rel_dst = dst
        print(f'  moved {src.name} -> {rel_dst}')


def migrate(verbose: bool = False) -> bool:
    """Convert a pre-0.9 flat ~/.claude layout into the yas/cache, yas/state tree; every step is idempotent.
    Returns True only if every step succeeded; on any OSError, version.json is left unwritten so the next run retries.
    """
    ok = True

    for d in (cache_dir(), state_dir(),
              runtime_dir(), signals_dir(), sessions_dir()):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            ok = False

    for name, dst_fn in _MOVES:
        try:
            _move(constants.CLAUDE_DIR / name, dst_fn(), verbose=verbose)
        except OSError:
            ok = False

    for name in _DELETE_FILES:
        src = constants.CLAUDE_DIR / name
        try:
            existed = src.exists()
            src.unlink(missing_ok=True)
            if verbose and existed:
                print(f'  removed {name}')
        except OSError:
            ok = False

    for name in _DELETE_DIRS:
        src = constants.CLAUDE_DIR / name
        try:
            existed = src.exists()
            shutil.rmtree(src, ignore_errors=True)
            if verbose and existed:
                print(f'  removed {name}')
        except OSError:
            ok = False

    # only retire statusline-theme once yas.toml already carries a `theme =` line (installer folds it first)
    toml_path = constants.CLAUDE_DIR / 'yas.toml'
    try:
        has_theme = toml_path.exists() and bool(
            re.search(r'(?m)^[ \t]*theme[ \t]*=', toml_path.read_text())
        )
    except OSError:
        has_theme = False
    if has_theme:
        theme_path = constants.CLAUDE_DIR / 'statusline-theme'
        try:
            existed = theme_path.exists()
            theme_path.unlink(missing_ok=True)
            if verbose and existed:
                print('  removed statusline-theme')
        except OSError:
            ok = False

    if ok:
        payload = json.dumps({
            'schema_version': LAYOUT_SCHEMA_VERSION,
            'yas_version': VERSION,
            'migrated_at': time.time(),
        })
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(dir=state_dir(), prefix='.version-', suffix='.tmp')
            with os.fdopen(fd, 'w') as f:
                f.write(payload)
            os.replace(tmp_path, version_file())
        except OSError:
            ok = False
            if tmp_path is not None:
                Path(tmp_path).unlink(missing_ok=True)

    return ok


if __name__ == '__main__':
    _verbose = '--verbose' in sys.argv[1:] or os.environ.get('YAS_MIGRATE_VERBOSE') == '1'
    raise SystemExit(0 if migrate(verbose=_verbose) else 1)
