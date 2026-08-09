from __future__ import annotations

import re
from pathlib import Path


# Module-level regexes for parsing capabilities and deltas.
_capabilities_heading_re = re.compile(r'^## Capabilities')
_capability_bullet_re = re.compile(r'^\s*-\s+`[a-z0-9-]+`')
_heading_re = re.compile(r'^## ')


def _parse_delta_total(proposal_path: Path) -> int:
    """Parse the total number of capabilities in a proposal's ## Capabilities section.

    Reads proposal_path, finds the line matching `^## Capabilities`, then counts
    lines matching `^\\s*-\\s+`[a-z0-9-]+`` until the next level-2 heading or EOF.
    Returns 0 on OSError or if the heading is never found.
    """
    try:
        text = proposal_path.read_text()
    except OSError:
        return 0

    lines = text.splitlines()
    capabilities_idx = -1
    for i, line in enumerate(lines):
        if _capabilities_heading_re.match(line):
            capabilities_idx = i
            break

    if capabilities_idx == -1:
        return 0

    count = 0
    for i in range(capabilities_idx + 1, len(lines)):
        line = lines[i]
        if _heading_re.match(line):
            break
        if _capability_bullet_re.match(line):
            count += 1

    return count


class AuthoringChange:
    __slots__ = ('name', 'has_proposal', 'has_design', 'delta_count', 'delta_total')

    def __init__(self, name: str, has_proposal: bool, has_design: bool, delta_count: int, delta_total: int) -> None:
        self.name = name
        self.has_proposal = has_proposal
        self.has_design = has_design
        self.delta_count = delta_count
        self.delta_total = delta_total

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AuthoringChange):
            return NotImplemented
        return (self.name, self.has_proposal, self.has_design, self.delta_count, self.delta_total) == \
               (other.name, other.has_proposal, other.has_design, other.delta_count, other.delta_total)

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return (f'AuthoringChange(name={self.name!r}, has_proposal={self.has_proposal!r}, '
                f'has_design={self.has_design!r}, delta_count={self.delta_count!r}, delta_total={self.delta_total!r})')


class OpenSpec:
    __slots__ = ('changes', 'authoring')

    def __init__(self, changes: list[tuple[str, int, int]] | None = None, authoring: list[AuthoringChange] | None = None) -> None:
        self.changes = changes if changes is not None else []
        self.authoring = authoring if authoring is not None else []

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, OpenSpec):
            return NotImplemented
        return self.changes == other.changes and self.authoring == other.authoring

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return f'OpenSpec(changes={self.changes!r}, authoring={self.authoring!r})'

    @classmethod
    def from_cwd(cls, cwd: str) -> OpenSpec:
        root = cls._find_root(cwd)
        if not root:
            return cls()
        out: list[tuple[str, int, int]] = []
        authoring: list[AuthoringChange] = []
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

        # Second, disjoint pass: a change directory without tasks.md is not yet
        # eligible for a task-progress bar (the loop above only emits one for
        # directories that HAVE tasks.md with >=1 checkbox), so it is otherwise
        # structurally invisible. This pass makes it visible as an authoring row
        # instead. The two passes are mutually exclusive by construction: a dir
        # with tasks.md is only ever handled above, never here. Also note: a
        # tasks.md with zero checkboxes is skipped by BOTH passes (the loop above
        # `continue`s on total==0, and this pass skips any dir where tasks.md
        # exists at all) -- that is existing, deliberate behaviour, not an
        # oversight (design.md Decision 1, add-openspec-authoring-row).
        changes_dir = Path(root) / 'changes'
        if changes_dir.is_dir():
            try:
                entries = sorted(changes_dir.iterdir())
            except OSError:
                entries = []
            for change_dir in entries:
                if (
                    not change_dir.is_dir()
                    or change_dir.name.startswith('.')
                    or change_dir.name == 'archive'
                ):
                    continue
                if (change_dir / 'tasks.md').is_file():
                    continue
                authoring.append(AuthoringChange(
                    name=change_dir.name,
                    has_proposal=(change_dir / 'proposal.md').is_file(),
                    has_design=(change_dir / 'design.md').is_file(),
                    delta_count=len(list(change_dir.glob('specs/*/spec.md'))),
                    delta_total=_parse_delta_total(change_dir / 'proposal.md'),
                ))

        return cls(changes=out, authoring=authoring)

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
