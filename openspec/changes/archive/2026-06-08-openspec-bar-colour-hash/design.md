## Context

`Renderer.openspec_bar(name, done, total, box_width, title_w, idx)`
(`claude/yas/renderer.py:1102`) calls `spec_gradient_bar(filled, bar_w, idx)`,
which indexes `SPEC_GRADIENTS[idx % len(SPEC_GRADIENTS)]` (12 gradients). The
caller `layout.py:270` passes `idx` as the `enumerate` position:
`[r.openspec_bar(name, d, t, width, title_w, i) for i, (name, d, t) in enumerate(changes)]`.
So colour is positional and reshuffles on reorder.

The statusline renders as a fresh subprocess every tick, so any per-render
randomness source must be derived from stable inputs.

## Goals / Non-Goals

**Goals:**
- Tie each bar's colour to its change name, stably across ticks and list order.
- Keep the 12-entry `SPEC_GRADIENTS` palette and `spec_gradient_bar` math
  unchanged.

**Non-Goals:**
- Changing the gradient palette or the bar geometry.
- Persisting colour state to disk.
- Guaranteeing uniqueness (collisions across `% 12` are acceptable).

## Decisions

- **Stable hash:** compute `idx = zlib.crc32(name.encode()) % len(SPEC_GRADIENTS)`.
  `zlib.crc32` is in the stdlib, fast, and process-stable (unlike builtin
  `hash()` which is `PYTHONHASHSEED`-salted). `hashlib` would also work but
  `crc32` is lighter and sufficient for a 12-way bucket.
- **Where to compute:** derive `idx` inside `openspec_bar` from `name`, so the
  caller no longer needs to thread a colour index. `layout.py` may drop the
  `enumerate` index from the colour argument (it can still enumerate for other
  needs, but the colour no longer depends on it).
- **Signature:** keep `openspec_bar`'s parameters backward-compatible where
  practical; if `idx` is removed, update the single call site and any tests that
  pass it positionally.

## Risks / Trade-offs

- **Collisions:** with 12 gradients, distinct names can share a colour. Accepted
  — the goal is variety and stability, not uniqueness.
- **Builtin-hash trap:** the whole point is avoiding `hash()`; the spec and a
  cross-invocation test guard against a regression to salted hashing.
- **Signature churn:** removing the positional `idx` touches the call site and
  existing `test_openspec_bar.py` cases; mitigated by updating them in the same
  change.
