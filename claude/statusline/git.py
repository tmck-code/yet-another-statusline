"""Git repo inspection: branch, commit, dirty counts.

`GitInfo.from_cwd` produces a snapshot for the cwd's repo. Branch + commit are
always read live (cheap file reads of `.git/HEAD` and the resolved ref) so a
branch switch shows immediately. The expensive `git status` dirty counts are
cached per session for `GIT_CACHE_TTL` seconds — the official statusline docs
recommend exactly this caching pattern. The cache is keyed by session id and
deliberately skipped when no session id is supplied (keeps it out of test fixtures
and any non-session caller).

Worktree / submodule / packed-refs handling: `_resolve_gitdir` follows the
`gitdir: <path>` pointer in a `.git` file, `_read_commit` checks the loose
ref *and* the worktree common dir *and* `packed-refs` so a commit resolves
correctly in normal repos, linked worktrees, and repos with packed refs.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from statusline import config
from statusline.models import _as_int
from statusline.textutil import _atomic_write_text, _sanitize


try:
    GIT_CACHE_TTL = float(os.environ.get('YAS_GIT_CACHE_TTL') or '4')  # seconds; per-session git-status freshness window
except ValueError:
    GIT_CACHE_TTL = 4.0


@dataclass
class GitInfo:
    branch: str = ''
    commit: str = ''
    modified: int = 0
    untracked: int = 0
    deleted: int = 0
    renamed: int = 0

    @classmethod
    def from_cwd(cls, cwd: str, session_id: str = '') -> GitInfo:
        repo, gitdir   = cls._find_repo(cwd)
        branch, commit = cls._read_head(gitdir)   # always live, so a branch switch shows immediately
        branch, commit = _sanitize(branch), _sanitize(commit)  # untrusted .git contents -> rendered line
        modified = untracked = deleted = renamed = 0
        if branch:
            modified, untracked, deleted, renamed = cls._dirty_cached(repo, cwd, session_id)
        return cls(
            branch    = branch,
            commit    = commit,
            modified  = modified,
            untracked = untracked,
            deleted   = deleted,
            renamed   = renamed,
        )

    @classmethod
    def _dirty_cached(cls, repo: str, cwd: str, session_id: str) -> tuple[int, int, int, int]:
        '''Cache the expensive `git status` dirty counts per session for
        GIT_CACHE_TTL seconds (the official statusline docs recommend exactly
        this). Only the counts are cached — branch/commit are re-read every
        render. Disabled without a session id, which keeps the cache out of the
        tmp_path-only git tests and out of any non-session caller.'''
        if not session_id:
            return cls._dirty(repo)
        cache_path = config.CLAUDE_DIR / 'statusline-git' / f'{session_id}.json'
        now = time.time()
        try:
            raw = cache_path.read_text()
        except OSError:
            raw = ''
        if raw:
            try:
                d = json.loads(raw)
            except ValueError:
                d = None
            if isinstance(d, dict):
                ts = d.get('ts')
                if (d.get('cwd') == cwd and isinstance(ts, (int, float))
                        and 0 <= now - ts <= GIT_CACHE_TTL):
                    return (_as_int(d.get('modified')), _as_int(d.get('untracked')),
                            _as_int(d.get('deleted')), _as_int(d.get('renamed')))
        modified, untracked, deleted, renamed = cls._dirty(repo)
        _atomic_write_text(cache_path, json.dumps({
            'v': 1, 'cwd': cwd, 'ts': now,
            'modified': modified, 'untracked': untracked, 'deleted': deleted, 'renamed': renamed,
        }))
        return modified, untracked, deleted, renamed

    @staticmethod
    def _find_repo(cwd: str) -> tuple[str, str]:
        curr = Path(cwd) if cwd else None
        while curr:
            dotgit = curr / '.git'
            if dotgit.exists():
                return str(curr), GitInfo._resolve_gitdir(dotgit)
            if curr == curr.parent:
                break
            curr = curr.parent
        return '', ''

    @staticmethod
    def _resolve_gitdir(dotgit: Path) -> str:
        '''Resolve a `.git` entry to the real git directory. `.git` is a
        directory in a normal clone, but a *file* containing `gitdir: <path>`
        in a linked worktree or submodule. Returns '' if unresolvable.'''
        if dotgit.is_dir():
            return str(dotgit)
        try:
            text = dotgit.read_text().strip()
        except OSError:
            return ''
        if text.startswith('gitdir:'):
            pointer = Path(text[len('gitdir:'):].strip())
            if not pointer.is_absolute():
                pointer = dotgit.parent / pointer
            try:
                return str(pointer.resolve())
            except OSError:
                return str(pointer)
        return ''

    @staticmethod
    def _read_head(gitdir: str) -> tuple[str, str]:
        if not gitdir:
            return '', ''
        gd = Path(gitdir)
        head_path = gd / 'HEAD'
        if not head_path.is_file():
            return '', ''
        try:
            head = head_path.read_text().strip()
        except OSError:
            return '', ''
        branch = ''
        if head.startswith('ref:'):
            target = head[4:].strip()
            prefix = 'refs/heads/'
            # Preserve the full branch namespace (e.g. 'feature/foo'); the old
            # rsplit('/', 1) collapsed it to 'foo'.
            branch = target[len(prefix):] if target.startswith(prefix) else target.rsplit('/', 1)[-1]
        elif head:
            branch = f'd:{head[:7]}'
        commit = ''
        if branch and not branch.startswith('d:'):
            commit = GitInfo._read_commit(gd, branch)
        if not commit:
            orig = gd / 'ORIG_HEAD'
            if orig.is_file():
                try:
                    commit = orig.read_text().strip()[:9]
                except OSError:
                    pass
        return branch, commit

    @staticmethod
    def _read_commit(gitdir: Path, branch: str) -> str:
        '''Resolve a branch's commit from a loose ref, the worktree common dir,
        or packed-refs — covering normal repos, linked worktrees (whose refs
        live in the common dir), and repos with packed refs.'''
        commondir = gitdir
        cd_file = gitdir / 'commondir'
        if cd_file.is_file():
            try:
                cd = Path(cd_file.read_text().strip())
                commondir = (cd if cd.is_absolute() else gitdir / cd).resolve()
            except OSError:
                commondir = gitdir
        for base in (gitdir, commondir):
            ref = base / 'refs' / 'heads' / branch
            if ref.is_file():
                try:
                    return ref.read_text().strip()[:9]
                except OSError:
                    pass
        packed = commondir / 'packed-refs'
        if packed.is_file():
            target = f'refs/heads/{branch}'
            try:
                for line in packed.read_text().splitlines():
                    line = line.strip()
                    if not line or line[0] in '#^':
                        continue
                    parts = line.split(' ', 1)
                    if len(parts) == 2 and parts[1] == target:
                        return parts[0][:9]
            except OSError:
                pass
        return ''

    @staticmethod
    def _dirty(repo: str) -> tuple[int, int, int, int]:
        modified = untracked = deleted = renamed = 0
        if not repo:
            return modified, untracked, deleted, renamed
        try:
            r = subprocess.run(
                ['git', '-C', repo, 'status', '--porcelain=v1', '-z',
                 '--untracked-files=normal'],
                capture_output=True, text=True, timeout=2,
            )
        except Exception:
            return modified, untracked, deleted, renamed
        entries = [e for e in r.stdout.split('\0') if e]
        i = 0
        while i < len(entries):
            entry = entries[i]
            if len(entry) < 2:
                i += 1
                continue
            x, y = entry[0], entry[1]
            if x == 'R' or y == 'R':
                renamed += 1
                i += 2  # rename consumes a second NUL-separated original-name field
                continue
            if x == '?' and y == '?':
                untracked += 1
            elif x == 'A' or y == 'A':
                untracked += 1
            elif x == 'D' or y == 'D':
                deleted += 1
            elif x == 'M' or y == 'M':
                modified += 1
            i += 1
        return modified, untracked, deleted, renamed
