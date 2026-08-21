# KNOWN_ISSUES.md

Findings that outlived the work that found them. Two kinds: a refactor that
must not be re-attempted, and bugs that are known but not yet fixed.

## Do not convert classes to `@dataclass`

`@dataclass` is a net loss in this repo. Not a style preference — a measured
regression.

**The cost is class-*definition* time, not per-instance time.** The decorator
runs `dataclasses._process_class` when the module is imported, which introspects
annotations and code-generates `__init__`/`__repr__`/`__eq__`. That work happens
once per decorated class per process.

For a long-running process that is free — amortised over the process lifetime.
The statusline is the opposite: a cold-start CLI, forked fresh on every prompt,
whose entire job takes ~45ms. **Import time is runtime here.** Nothing is
amortised, because nothing lives long enough to amortise it.

Measured on `refactor/reduce-loc` (PR #123), converting 16 classes
(`Theme`, `ModelColors`, `Pill`, `RowSpec`, `LayoutSpec`, `WindowSlice`,
`SessionView`, and related):

| | `main` | with `@dataclass` |
|---|---:|---:|
| mean | 44.9 ms | 54.3 ms |
| `_process_class` calls | 1 | 16 |
| `_process_class` time | ~0 ms | ~11 ms (~24% of total) |

That is **1.13-1.18x slower**, minima non-overlapping across independent runs.
Roughly 0.7ms per decorated class, paid on every single statusline render, in
exchange for ~25 lines of source saved once.

No `@dataclass` option avoids this — `slots=True`, `eq=False` and friends change
what gets generated, not that generation happens. **Hand-written `__slots__`
classes are the idiom here.** They cost more source lines; that is the accepted
trade.

### Why "actively harmful" and not merely "not worth it"

Three reasons this earns a standing rule rather than a case-by-case judgement:

1. **It is invisible to every gate.** pytest, ruff, mypy and the demo visual
   gate all stayed green across the entire regression. Only `make bench` caught
   it, and only because it is step 6 of the `yas-pr` flow. A change that
   degrades the product while every check reports success will ship.
2. **It is attractive.** `@dataclass` is the obvious modern answer to
   "this class is boilerplate", and it genuinely does reduce line count. Anyone
   optimising for readability or LOC will reach for it and be rewarded on the
   metric they are watching.
3. **It scales the wrong way.** The cost is per-decorated-class, so it grows as
   the codebase gets tidier. Each individual conversion looks negligible
   (~0.7ms); sixteen of them cost a quarter of total runtime.

Before adding any import-time machinery to `claude/yas/**` — dataclasses,
enums, ABCs, pydantic, module-level regex compilation, eager imports of heavy
stdlib modules — run `make bench` and `python -X importtime`.

## Known bugs

### 1. Unreachable recovery code in `claude/yas/info/subagents.py`

The mispredict re-parse block in `RunningSubagents.visible()` (~lines 1081-1122)
can never execute.

`_conclusively_retired` requires end_ts staleness of
`max(FINISHED_LINGER_SECONDS, COHORT_GRACE_SECONDS) + TERMINAL_SKEW_SECONDS`
= `max(120, 120) + 5` = **125s**. But `visible()`'s own `_retired()` check uses
`COHORT_GRACE_SECONDS if all_done else FINISHED_LINGER_SECONDS` — **120s** on
either branch.

Since 125 > 120, any agent for which `_conclusively_retired` is genuinely true
at a given `now` has already been dropped by `visible()`'s own retirement check
at that same `now`. Verified empirically across every candidacy path:

```python
_conclusively_retired(NOW, 'completed', NOW - 126, NOW - 1806)  # True
cohort.visible(NOW, last_prompt_ts=None)                        # [] - never present
```

Found because a test had stubbed `_conclusively_retired` to a constant `True`,
which hid it. The test now runs the real predicate and is pinned
`xfail(strict=True)` in `test/test_cohort_visibility.py`.

**Fix is a product decision**: either align the constants so the recovery path
can run, or delete the block as dead. Which is right depends on whether the
mispredict case is still reachable by some other route — the block exists
because someone hit it.

### 2. `claude/mon/layout.py::_visible_len` mishandles wide characters

Counts code points rather than display columns, so CJK and emoji are undercounted
in `mon`'s layout math. Same class of bug as the PUA glyph width hazards the
`tmck-code-statusline` skill documents for the main renderer.
