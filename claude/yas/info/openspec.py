from __future__ import annotations

import re
from pathlib import Path

# dirs skipped during the downward recursive scan for nested openspec/ roots
_IGNORED_DIRS = frozenset((
    '.git', 'node_modules', 'venv', '.venv', '__pycache__',
    '.tox', '.mypy_cache', '.pytest_cache', '.ruff_cache',
))
# repo-levels below the scan root the downward walk descends (yas.toml [openspec] scan_depth);
# _scan_downward converts this to path segments as max_depth + 1 (openspec/ is one segment deeper)
_MAX_SCAN_DEPTH = 1


class OpenSpec:
    __slots__ = ('changes',)

    def __init__(self, changes: list[tuple[str, int, int]] | None = None) -> None:
        self.changes = changes if changes is not None else []

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, OpenSpec):
            return NotImplemented
        return self.changes == other.changes

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return f'OpenSpec(changes={self.changes!r})'

    @classmethod
    def from_cwd(cls, cwd: str, max_depth: int = _MAX_SCAN_DEPTH) -> OpenSpec:
        """``max_depth`` is repo-levels below cwd, not raw path segments."""
        roots = cls._find_roots(cwd, max_depth)
        if not roots:
            return cls()
        # multiple roots: prefix each entry with its repo dir to disambiguate colliding change names
        multi = len(roots) > 1
        out: list[tuple[str, int, int]] = []
        for root in roots:
            prefix = f'{Path(root).parent.name}/' if multi else ''
            for name, d, t in cls._changes_in_root(root):
                out.append((f'{prefix}{name}', d, t))
        return cls(changes=out)

    @staticmethod
    def _changes_in_root(root: str) -> list[tuple[str, int, int]]:
        out: list[tuple[str, int, int]] = []
        open_re = re.compile(r'^\s*- \[ \]')
        done_re = re.compile(r'^\s*- \[x\]')
        for tasks in sorted(Path(root).rglob('tasks.md')):
            if '/archive/' in str(tasks):
                continue
            try:
                text = tasks.read_text()
            except OSError:
                continue
            t = sum(1 for ln in text.splitlines() if open_re.match(ln))
            d = sum(1 for ln in text.splitlines() if done_re.match(ln))
            total = t + d
            if total == 0:
                continue
            out.append((tasks.parent.name, d, total))
        return out

    @staticmethod
    def _find_root(cwd: str) -> str:
        curr = Path(cwd) if cwd else None
        while curr:
            if (curr / 'openspec').is_dir():
                return str(curr / 'openspec')
            if curr == curr.parent:
                break
            curr = curr.parent
        return ''

    @classmethod
    def _find_roots(cls, cwd: str, max_depth: int = _MAX_SCAN_DEPTH) -> list[str]:
        """Nearest ancestor openspec/ plus every openspec/ found walking down from cwd; max_depth=0 disables the downward scan."""
        if not cwd:
            return []
        seen: set[str] = set()
        roots: list[str] = []

        upward = cls._find_root(cwd)
        if upward:
            seen.add(upward)
            roots.append(upward)

        base = Path(cwd)
        if base.is_dir() and max_depth > 0:
            for found in cls._scan_downward(base, max_depth + 1):  # +1: openspec/ is one segment deeper than its repo dir
                if found not in seen:
                    seen.add(found)
                    roots.append(found)
        return roots

    @classmethod
    def _scan_downward(cls, base: Path, max_depth: int) -> list[str]:
        found: list[str] = []
        base_depth = len(base.parts)
        stack = [base]
        while stack:
            curr = stack.pop()
            if len(curr.parts) - base_depth >= max_depth:
                continue
            try:
                entries = sorted(curr.iterdir())
            except OSError:
                continue
            for entry in entries:
                if not entry.is_dir() or entry.name in _IGNORED_DIRS or entry.name.startswith('.'):
                    continue
                if entry.name == 'openspec':
                    found.append(str(entry))
                    continue  # no changes/specs live below openspec/ worth descending into
                stack.append(entry)
        return sorted(found)
