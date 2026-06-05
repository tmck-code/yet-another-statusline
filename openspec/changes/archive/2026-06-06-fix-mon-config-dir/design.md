## Context

`mon/discovery.py` defines two path constants as default arguments:

```python
projects_root: Path = Path.home() / '.claude' / 'projects'   # line 21
payloads_root: Path = Path.home() / '.claude' / 'statusline-output'  # line 43
```

`CLAUDE_DIR` in `yas.constants` already resolves this path correctly (honoring `CLAUDE_CONFIG_DIR`), and is used by `yas.app`, `yas.config`, `yas.session`, and `yas.info.subagents`. The `mon` module simply missed the abstraction.

## Goals / Non-Goals

**Goals:**
- Replace both hardcoded `Path.home() / '.claude'` prefixes with `CLAUDE_DIR` from `yas.constants`
- Zero behaviour change for users with the default `~/.claude` directory

**Non-Goals:**
- Restructuring `mon/discovery.py` beyond the two literal replacements
- Changing how `CLAUDE_DIR` itself is resolved (already correct in `constants.py`)

## Decisions

**Import `CLAUDE_DIR` from `yas.constants`**: Same import that `yas.app` already uses. No new dependency.

**Replace default argument literals**: Default arguments are evaluated once at import time, so replacing the literal with `CLAUDE_DIR` (also a module-level constant) is safe and equivalent.

## Risks / Trade-offs

None — purely mechanical substitution of a hardcoded value with the existing abstraction.
