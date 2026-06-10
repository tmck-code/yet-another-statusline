## 1. Name-derived colour selection

- [x] 1.1 In `Renderer.openspec_bar` (`claude/yas/renderer.py`), compute `idx = zlib.crc32(name.encode()) % len(self.SPEC_GRADIENTS)` and pass it to `spec_gradient_bar` instead of the caller-supplied positional index.
- [x] 1.2 Add `import zlib` (module top) if not already present.
- [x] 1.3 Update the call site in `claude/yas/layout.py:270` so the colour no longer depends on the `enumerate` index (drop the `i` colour argument or stop passing it).

## 2. Tests

- [x] 2.1 In `test/test_openspec_bar.py`, assert the same name yields the same gradient when rendered at different list positions.
- [x] 2.2 Assert the selected index equals `zlib.crc32(name.encode()) % len(SPEC_GRADIENTS)` (locks the stable-hash contract; guards against a regression to builtin `hash()`).
- [x] 2.3 Assert several distinct names do not all collapse to one gradient (spread check).

## 3. Verification

- [x] 3.1 Run `make test` — green.
- [x] 3.2 Run `make demo` with multiple OpenSpec changes present; confirm bar colours are varied and stable across frames (no strobing).
