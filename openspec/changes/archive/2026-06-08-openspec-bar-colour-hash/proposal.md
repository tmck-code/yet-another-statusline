## Why

OpenSpec change bars are coloured by their **row position** (`idx` is the
`enumerate` index in `layout.py`), so the same gradient palette entries always
appear in the same order and a change's colour shifts whenever the list
reorders. The colours should feel varied and be tied to the change itself, not
to where it happens to sit in the list.

## What Changes

- Colour each OpenSpec bar by a **stable hash of the change name** rather than
  its list position: `idx = stable_hash(name) % len(SPEC_GRADIENTS)`.
- A given change keeps a consistent gradient across renders and regardless of
  list order; different changes scatter across the palette.
- **Must use a process-stable hash** (e.g. `zlib.crc32` / `hashlib`), **not**
  Python's builtin `hash()` — builtin `str` hashing is salted per process
  (`PYTHONHASHSEED`), and since the statusline runs as a fresh subprocess each
  render tick, builtin `hash()` would re-roll the colour every tick (strobing).

## Capabilities

### New Capabilities
- `openspec-bar-colour`: how an OpenSpec change bar selects its gradient — a
  deterministic, name-derived, render-stable mapping.

### Modified Capabilities
<!-- none -->

## Impact

- `claude/yas/renderer.py` — `Renderer.openspec_bar` (derive `idx` from a stable
  hash of `name`).
- `claude/yas/layout.py` — the call site no longer needs to pass the
  `enumerate` index for colour purposes.
- Tests: `test/test_openspec_bar.py` (stable mapping; same name → same gradient
  across calls; distinct names spread).
- No change to bar geometry, width math, or border alignment.
