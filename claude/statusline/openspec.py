"""OpenSpec change-set inspection.

Optional layer: if the workspace has an `openspec/` directory, this walks it
for `tasks.md` files (excluding `archive/`) and returns each change's name +
done/total task counts (computed from `- [ ]` / `- [x]` checkbox lines). Used
by build_wide to render per-change progress bars.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class OpenSpec:
    changes: list[tuple[str, int, int]] = field(default_factory=list)

    @classmethod
    def from_cwd(cls, cwd: str) -> OpenSpec:
        root = cls._find_root(cwd)
        if not root:
            return cls()
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
        return cls(changes=out)

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
