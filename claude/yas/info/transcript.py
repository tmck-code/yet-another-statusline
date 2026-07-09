"""Transcript usage reader — parses token usage from a JSONL conversation file."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from yas.constants import CACHE_TTL_1H_SECONDS, CACHE_TTL_SECONDS


class TranscriptUsage:
    __slots__ = (
        'input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens',
        'output_tokens', 'cache_anchor_epoch', 'cache_ttl',
    )

    def __init__(
        self,
        input_tokens:                int   = 0,
        cache_creation_input_tokens: int   = 0,
        cache_read_input_tokens:     int   = 0,
        output_tokens:               int   = 0,
        cache_anchor_epoch:          float = 0.0,
        cache_ttl:                   int   = 0,
    ) -> None:
        self.input_tokens                = input_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens
        self.cache_read_input_tokens     = cache_read_input_tokens
        self.output_tokens               = output_tokens
        self.cache_anchor_epoch          = cache_anchor_epoch
        self.cache_ttl                   = cache_ttl

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TranscriptUsage):
            return NotImplemented
        return (self.input_tokens, self.cache_creation_input_tokens, self.cache_read_input_tokens,
                self.output_tokens, self.cache_anchor_epoch, self.cache_ttl) == \
               (other.input_tokens, other.cache_creation_input_tokens, other.cache_read_input_tokens,
                other.output_tokens, other.cache_anchor_epoch, other.cache_ttl)

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return (f'TranscriptUsage(input_tokens={self.input_tokens}, '
                f'cache_creation_input_tokens={self.cache_creation_input_tokens}, '
                f'cache_read_input_tokens={self.cache_read_input_tokens}, '
                f'output_tokens={self.output_tokens}, '
                f'cache_anchor_epoch={self.cache_anchor_epoch}, cache_ttl={self.cache_ttl})')

    @classmethod
    def from_transcript(cls, transcript_path: str) -> TranscriptUsage:
        if not transcript_path:
            return cls()
        p = Path(transcript_path)
        if not p.is_file():
            return cls()
        # Usage is keyed by message id with last-line-wins: streaming re-writes
        # the same id as it appends content blocks, and the usage counters GROW
        # across those writes — the final one carries the message's real totals.
        # A first-write dedup freezes usage at the first partial snapshot and
        # undercounts output tokens.
        usage_by_id: dict[str, tuple[int, int, int, int]] = {}
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
                    if not mid:
                        continue
                    u = msg.get('usage') or {}
                    usage_by_id[mid] = (
                        u.get('input_tokens', 0) or 0,
                        u.get('cache_creation_input_tokens', 0) or 0,
                        u.get('cache_read_input_tokens', 0) or 0,
                        u.get('output_tokens', 0) or 0,
                    )
                    if (u.get('cache_read_input_tokens', 0) or 0) > 0 or \
                            (u.get('cache_creation_input_tokens', 0) or 0) > 0:
                        _cache_anchor_ts = d.get('timestamp', '') or ''
                        _cache_1h        = bool(
                            (u.get('cache_creation') or {})
                            .get('ephemeral_1h_input_tokens', 0)
                        )
        except OSError:
            return cls()
        ti = sum(vals[0] for vals in usage_by_id.values())
        cc = sum(vals[1] for vals in usage_by_id.values())
        cr = sum(vals[2] for vals in usage_by_id.values())
        to = sum(vals[3] for vals in usage_by_id.values())
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
