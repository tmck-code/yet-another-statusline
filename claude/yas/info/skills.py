"""Loaded skills reader — parses skill names from a Claude transcript."""

from __future__ import annotations

import re
from pathlib import Path

from yas.constants import _sanitize


class LoadedSkills:
    __slots__ = ('names',)

    def __init__(self, names: list[str] | None = None) -> None:
        self.names = names if names is not None else []

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, LoadedSkills):
            return NotImplemented
        return self.names == other.names

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return f'LoadedSkills(names={self.names!r})'

    @classmethod
    def from_transcript(cls, transcript_path: str) -> LoadedSkills:
        if not transcript_path:
            return cls()
        p = Path(transcript_path)
        if not p.is_file():
            return cls()
        skill_pat = re.compile(r'"name"\s*:\s*"Skill"[^}]*?"skill"\s*:\s*"([^"]+)"')
        read_pat = re.compile(r'"name"\s*:\s*"Read"[^}]*?"file_path"\s*:\s*"([^"]+)"')
        skill_path_pat = re.compile(r'/skills/([^/"]+)/SKILL\.md$')
        seen: dict[str, None] = {}
        try:
            with p.open('r', errors='ignore') as fh:
                for ln in fh:
                    if '"Skill"' in ln:
                        for m in skill_pat.finditer(ln):
                            name = _sanitize(m.group(1))
                            if name not in seen:
                                seen[name] = None
                    if '"Read"' in ln and 'SKILL.md' in ln:
                        for m in read_pat.finditer(ln):
                            sm = skill_path_pat.search(m.group(1))
                            if sm:
                                name = _sanitize(sm.group(1))
                                if name not in seen:
                                    seen[name] = None
        except OSError:
            return cls()
        return cls(names=list(seen.keys()))
