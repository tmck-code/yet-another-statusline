#!/usr/bin/env python3
'''PreToolUse(Bash) nudge: keep the gates off the main thread.

When the MAIN thread tries to run the test/lint/demo gates directly, inject a
non-blocking reminder to delegate to the `verifier` subagent instead (see
CLAUDE.md). The call is still allowed — this only nudges.

It must NOT nag subagents: `verifier` legitimately runs these gates. Claude Code
populates `agent_id`/`agent_type` in the hook stdin ONLY for subagent-originated
tool calls, so their presence means "not the main thread" -> stay silent.
'''
import json
import re
import sys

# Gate commands that belong in `verifier`, not on the main thread.
GATE = re.compile(r'\b(pytest|make\s+test|make\s+demo|ruff\s+check)\b')

NUDGE = (
    'Context-discipline reminder (CLAUDE.md): the test/lint/demo gates belong in '
    "the `verifier` subagent, not the main thread. Unless this is a throwaway "
    'one-off check, delegate it to `verifier` — and if it reports a failure, hand '
    'the fix to `yas-editor`/`spec-implementer` and re-verify rather than '
    'debugging inline.'
)


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # never block on a parse hiccup

    # Subagent-originated call -> these fields are present -> stay silent.
    if data.get('agent_id') or data.get('agent_type'):
        return 0

    command = (data.get('tool_input') or {}).get('command', '')
    if not GATE.search(command):
        return 0

    json.dump(
        {
            'hookSpecificOutput': {
                'hookEventName':     'PreToolUse',
                'permissionDecision': 'allow',
                'additionalContext':  NUDGE,
            }
        },
        sys.stdout,
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
