## 1. Branch-only render path

- [ ] 1.1 Add a way to render the git glyph + arrow + branch with no cwd segment (a new thin helper in `renderer.py`, or a `show_path=False` flag on the existing path renderer), reusing existing colour constants.
- [ ] 1.2 Ensure a glyph-only form (presence indicator, 1–2 visible columns) is available as the terminal fallback.

## 2. Rewrite the fit_path ladder

- [ ] 2.1 In `Renderer.fit_path`, replace the candidate list with: full → drop commit → drop commit+dirty → branch-only (path omitted) → glyph-only.
- [ ] 2.2 Remove the two middle-ellipsis tail stages (`short_pwd` ellipsis and `short_pwd`+branch ellipsis).
- [ ] 2.3 Preserve `compact_only=True` semantics: skip the full `path_git` stages and enter at the compact/branch-only rungs.
- [ ] 2.4 Select the first candidate whose `_visible_width` is `<= target_w`; guarantee the glyph-only floor always fits.

## 3. Tests

- [ ] 3.1 Add a test module asserting `fit_path` returns the full form at wide widths and drops commit then dirty as width shrinks.
- [ ] 3.2 Assert that at a width too small for path+branch, the path is omitted whole (no ellipsis fragment) and the branch remains.
- [ ] 3.3 Assert that at a width too small for the branch alone, only the glyph remains and `_visible_width(result) <= target_w` (overflow-safe floor).
- [ ] 3.4 Assert no result at any tested width contains a middle-ellipsis path fragment.

## 4. Verification

- [ ] 4.1 Run `make test` — green.
- [ ] 4.2 Run `make demo` and resize across narrow/medium/wide; confirm the path appears/disappears as a whole and the border stays aligned at every width.
