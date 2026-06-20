"""Context-state word: map a context-fill percentage to a named state label.

Ported from Dumbometer (https://github.com/MaximoCorrea1/dumbometer), MIT,
(c) Maximo Correa Rosas — specifically the level model in ``src/config.js`` and
the label-selection logic (``computeState``) in ``src/state.js``. The mapping is
reproduced here in Python.

One deliberate difference from upstream Dumbometer: the percentage fed in is
YAS's *soft-limit fill ratio* (the same basis as the context bar), not the
full-window percentage. This keeps the word and the bar in agreement — the word
turns "Dumb" exactly as the bar fills — at the cost of using YAS's compaction
threshold rather than the raw model window. See the README for the trade-off.
"""

from __future__ import annotations

from collections.abc import Sequence


def context_state(pct: float, labels: Sequence[str], thresholds: Sequence[int]) -> str:
    """Return the state label whose band contains ``pct``.

    ``thresholds`` is N ascending ints — the *start* percentage of each band
    after the first; ``labels`` is the N+1 band names. With YAS's defaults
    (thresholds ``25, 50, 70, 90`` and labels ``Smart, Coasting, Foggy, Cooked,
    Dumb``): ``pct < 25`` -> ``Smart``, ``25 <= pct < 50`` -> ``Coasting``, ...,
    ``pct >= 90`` -> ``Dumb``. Boundaries are inclusive on the lower edge
    (``>=``), matching Dumbometer's ``computeState``.

    ``pct`` is clamped to ``[0, 100]``. An empty ``labels`` returns ``''``. The
    selected index is clamped to the last label, so a malformed
    labels/thresholds pairing (more thresholds than labels-1) can never index
    out of range.
    """
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
