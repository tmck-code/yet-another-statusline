"""Context-state word: map a context-fill percentage to a named state label.

Ported from Dumbometer (https://github.com/MaximoCorrea1/dumbometer), MIT, (c) Maximo Correa Rosas.
Fed with YAS's soft-limit fill ratio (same basis as the context bar), not the raw full-window percentage.
"""

from __future__ import annotations

from collections.abc import Sequence


def context_state(pct: float, labels: Sequence[str], thresholds: Sequence[int]) -> str:
    """State label whose band contains `pct`. `thresholds` (N ascending ints) are band start percentages,
    `labels` the N+1 band names; boundaries inclusive on the lower edge. `pct` clamped to [0, 100]."""
    if not labels:
        return ''
    p = max(0.0, min(100.0, pct))
    idx = 0
    for t in thresholds:
        if p >= t:
            idx += 1
        else:
            break
    if idx >= len(labels):
        idx = len(labels) - 1
    return labels[idx]
