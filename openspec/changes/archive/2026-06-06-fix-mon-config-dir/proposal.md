## Why

The multi-session observer (`mon`) hardcodes `Path.home() / '.claude'` for both the projects root and the statusline-output payloads root. Users who set `CLAUDE_CONFIG_DIR` (a Claude Code supported env var) store their data elsewhere and see "(no active sessions)" even while sessions are running. The single source of truth for this path is `config.CLAUDE_DIR`, which the rest of the statusline already honours.

## What Changes

- `mon/discovery.py` will replace both `Path.home() / '.claude' / 'projects'` and `Path.home() / '.claude' / 'statusline-output'` with `CLAUDE_DIR / 'projects'` and `CLAUDE_DIR / 'statusline-output'`.
- `CLAUDE_DIR` will be imported from `yas.constants` (already available there).
- No behavioural change for users with the default `~/.claude` location.

## Capabilities

### New Capabilities

- `mon-config-dir`: The `mon` observer resolves session and payload roots from `CLAUDE_DIR`, honouring `CLAUDE_CONFIG_DIR`.

### Modified Capabilities

*(none — correctness fix, same observable contract for default-config users)*

## Impact

- `claude/mon/discovery.py`: the two default-argument path literals
- Tests: `test_mon_discovery.py` — any test that relies on the hardcoded `~/.claude` path will need to patch or use the `tmp_home` fixture instead
