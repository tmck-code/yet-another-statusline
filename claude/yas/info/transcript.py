"""Transcript usage reader — parses token usage from a JSONL conversation file."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from yas.constants import CACHE_TTL_1H_SECONDS, CACHE_TTL_SECONDS


@dataclass
class TranscriptUsage:
    input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    output_tokens: int = 0
    cache_anchor_epoch: float = 0.0
    cache_ttl: int = 0

    @classmethod
    def from_transcript(cls, transcript_path: str) -> TranscriptUsage:
        if not transcript_path:
            return cls()
        p = Path(transcript_path)
        if not p.is_file():
            return cls()
        seen: set[str] = set()
        ti = cc = cr = to = 0
        _cache_anchor_ts: str  = ''
        _cache_1h:        bool = False
        try:
            with p.open('r', errors='ignore') as fh:
                for ln in fh:
                    if '"usage"' not in ln or '"assistant"' not in ln:
                        continue
                    try:
                        d = json.loads(ln)
                    except (ValueError, TypeError):
                        continue
                    msg = d.get('message') or {}
                    mid = msg.get('id')
                    if not mid or mid in seen:
                        continue
                    seen.add(mid)
                    u = msg.get('usage') or {}
                    ti += u.get('input_tokens', 0) or 0
                    cc += u.get('cache_creation_input_tokens', 0) or 0
                    cr += u.get('cache_read_input_tokens', 0) or 0
                    to += u.get('output_tokens', 0) or 0
                    if (u.get('cache_read_input_tokens', 0) or 0) > 0 or \
                            (u.get('cache_creation_input_tokens', 0) or 0) > 0:
                        _cache_anchor_ts = d.get('timestamp', '') or ''
                        _cache_1h        = bool(
                            (u.get('cache_creation') or {})
                            .get('ephemeral_1h_input_tokens', 0)
                        )
        except OSError:
            return cls()
        cache_anchor_epoch = 0.0
        if _cache_anchor_ts:
            try:
                ts = _cache_anchor_ts
                if ts.endswith('Z'):
                    ts = ts[:-1] + '+00:00'
                cache_anchor_epoch = datetime.fromisoformat(ts).timestamp()
            except (ValueError, TypeError):
                cache_anchor_epoch = 0.0
        cache_ttl = (
            CACHE_TTL_1H_SECONDS if _cache_1h
            else (CACHE_TTL_SECONDS if _cache_anchor_ts else 0)
        )
        return cls(
            input_tokens                = ti,
            cache_creation_input_tokens = cc,
            cache_read_input_tokens     = cr,
            output_tokens               = to,
            cache_anchor_epoch          = cache_anchor_epoch,
            cache_ttl                   = cache_ttl,
        )

    @property
    def billed_in(self) -> int:
        return self.input_tokens + self.cache_creation_input_tokens

    @property
    def cache_read(self) -> int:
        return self.cache_read_input_tokens

    @property
    def out(self) -> int:
        return self.output_tokens
