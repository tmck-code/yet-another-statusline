"""Hermetic demo for statusline_command.py.

Materialises a synthetic ~/.claude/ and project tree under a tempfile, mutates
the canonical session-info fixture in memory, and pipes the result to the
production statusline script with $HOME pointed at the tempfile. Leaves no
residue on the developer's real filesystem.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = REPO_ROOT / 'ops' / 'session-info-example.json'
STATUSLINE_SCRIPT = REPO_ROOT / 'claude' / 'statusline_command.py'

# Mirrors yas.info.subagents._TERMINAL_STATUSES: only these <task-notification>
# status values are ever authoritative for "finished" — used by write_subagents
# to decide whether a synthesised notification pins the transcript mtime idle
# (terminal) or leaves it fresh (a resumed agent's non-terminal latest notif).
_TERMINAL_STATUSES_DEMO = frozenset(('completed', 'killed', 'failed', 'stopped'))


SKILLS_PROGRESSION: tuple[list[str], ...] = (
    [],
    ['grill-me'],
    ['grill-me', 'caveman'],
    ['grill-me', 'caveman', 'tdd'],
    ['grill-me', 'caveman', 'tdd', 'rocky:rocky'],
    ['grill-me', 'caveman', 'tdd', 'rocky:rocky', 'frontend-design:frontend-design'],
)

PLUGINS_PROGRESSION: tuple[list[str], ...] = (
    [],
    ['openspec@0.1.0'],
    ['openspec@0.1.0', 'frontend-design@0.3.2'],
    ['openspec@0.1.0', 'frontend-design@0.3.2', 'rocky@0.1.0'],
)

# [(name, done, total), ...] per animation stage. Both specs hit 100% before the
# final empty stage clears them.
OPENSPEC_PROGRESSION: tuple[list[tuple[str, int, int]], ...] = (
    [],
    [('port-statusline-to-python', 1, 8)],
    [('port-statusline-to-python', 3, 8), ('add-gradient-engine', 2, 8)],
    [('port-statusline-to-python', 6, 8), ('add-gradient-engine', 5, 8)],
    [('port-statusline-to-python', 8, 8), ('add-gradient-engine', 8, 8)],
    [],
)

# (agentType, description, billed_in, output_tokens, action) — empty list means no subagent active
# action is (tool_name, input_dict), ('text', snippet), a list of either, or
# None; omit to leave activity blank.  See write_subagents for the full vocabulary.
SUBAGENTS_PROGRESSION: tuple[list[tuple[object, ...]], ...] = (
    [],
    [('explore',         'Search codebase - looking for token tracking',  1_200,    80, ('Bash',  {'command': 'grep -rn "billed_in" claude/statusline_command.py'}))],
    [('explore',         'Search codebase - looking for token tracking',  3_100,   190, ('Read',  {'file_path': 'claude/statusline_command.py'}))],
    [('general-purpose', 'Fix sparkline - update bucket algorithm',       7_600,   680, ('Edit',  {'file_path': 'claude/statusline_command.py', 'old_string': 'old', 'new_string': 'new'}))],
    # Text-only latest message -> the GLYPH_REPLYING snippet continuation line.
    [('narrator',        'Narrate progress on the gradient fix',          9_400,   980, ('text',  'Tracing the off-by-one in the gradient border math'))],
    [('general-purpose', 'Fix sparkline - update bucket algorithm',      11_800, 1_350, None)],
    [],
)

# (subject, activeForm) for the TaskList progression row.
DEMO_TASKS = (
    ('Audit gradient palette',  'Auditing gradient palette'),
    ('Wire alert-mode pill',    'Wiring alert-mode pill'),
    ('Refactor border math',    'Refactoring border math'),
    ('Update CONTEXT.md',       'Updating CONTEXT.md'),
    ('Add sparkline buckets',   'Adding sparkline buckets'),
    ('Fix elbow column math',   'Fixing elbow column math'),
    ('Wire token tracker',      'Wiring token tracker'),
    ('Backfill renderer tests', 'Backfilling renderer tests'),
)

# Synthetic per-task durations (seconds), indexed by task position. Varied,
# realistic coding-task spans with at least one sub-minute and a couple of
# multi-minute entries so the right-aligned timer column is well exercised.
# Frozen for completed tasks; the in_progress task uses TASK_LIVE_SECONDS instead.
TASK_DURATIONS: tuple[int, ...] = (34, 152, 248, 95, 71, 188, 42, 133)
#                                  0:34 2:32 4:08 1:35 1:11 3:08 0:42 2:13

# How long ago the in_progress task started, in seconds (its live timer reads ~this).
TASK_LIVE_SECONDS = 67  # ~1:07

# pct below which no TaskList is shown (lets the demo open without it).
TASKS_START_PCT = 0.15
# pct at and above which tasks are cleared (wind-down state).
TASKS_END_PCT = 0.88


def task_state_for(pct: float) -> list[tuple[str, str, str]]:
    if pct < TASKS_START_PCT or pct >= TASKS_END_PCT:
        return []
    n = len(DEMO_TASKS)
    progress = (pct - TASKS_START_PCT) / (1.0 - TASKS_START_PCT)
    active = min(int(progress * n), n - 1)
    out: list[tuple[str, str, str]] = []
    for i, (subj, af) in enumerate(DEMO_TASKS):
        if pct >= 1.0 or i < active:
            status = 'completed'
        elif i == active:
            status = 'in_progress'
        else:
            status = 'pending'
        out.append((subj, af, status))
    return out


def _seed_yas_version(claude_dir: Path) -> None:
    """Pre-write yas/state/version.json so the renderer's lazy yas.migrate()
    sees an already-migrated layout and skips entirely — otherwise migrate()
    deletes the legacy statusline-token-rate.log (and would fold/relocate
    statusline-tokens.log) before the first render, dropping the sparkline
    data this demo seeds below. Schema mirrors yas.migrate.migrate()'s payload.
    """
    # Local import: only main()'s --snapshots path adds claude/ to sys.path,
    # and this is reached from other call sites (the animate path) too, so
    # import lazily and fall back to a hardcoded schema version if yas isn't
    # importable yet rather than hard-failing the demo.
    try:
        sys.path.insert(0, str(REPO_ROOT / 'claude'))
        from yas.constants import LAYOUT_SCHEMA_VERSION, VERSION
    except ImportError:
        LAYOUT_SCHEMA_VERSION, VERSION = 1, '0.0.0-demo'
    version_file = claude_dir / 'yas' / 'state' / 'version.json'
    version_file.parent.mkdir(parents=True, exist_ok=True)
    version_file.write_text(json.dumps({
        'schema_version': LAYOUT_SCHEMA_VERSION,
        'yas_version': VERSION,
        'migrated_at': time.time(),
    }))


def build_synthetic_env(tmpdir: Path, session_id: str) -> None:
    claude = tmpdir / '.claude'
    project = tmpdir / 'my-project'

    (claude / 'projects' / session_id).mkdir(parents=True)
    (project / 'src').mkdir(parents=True)

    (project / 'README.md').write_text('# my-project\n')
    (project / 'src' / 'main.py').write_text("print('hi')\n")
    (project / 'src' / 'utils.py').write_text("def add(a, b):\n    return a + b\n")

    git_env = {
        'GIT_AUTHOR_NAME':     'Demo',
        'GIT_AUTHOR_EMAIL':    'demo@example.com',
        'GIT_COMMITTER_NAME':  'Demo',
        'GIT_COMMITTER_EMAIL': 'demo@example.com',
        'HOME':                str(tmpdir),
        'PATH':                os.environ.get('PATH', ''),
    }
    def _git(*args: str) -> None:
        subprocess.run(['git', '-C', str(project), *args], env=git_env, check=True, capture_output=True)

    _git('init', '-q', '-b', 'demo')
    _git('add', 'README.md', 'src/main.py', 'src/utils.py')
    _git('commit', '-q', '-m', 'initial')

    (project / 'src' / 'main.py').write_text("print('hi, world')\n")
    (project / 'src' / 'utils.py').write_text("def add(a, b):\n    return a + b + 0\n")
    (project / 'README.md').write_text('# my-project\n\nDemo.\n')
    (project / 'src' / 'new_feature.py').write_text('# todo\n')
    (project / 'notes.txt').write_text('scratch\n')

    (project / '.git' / 'refs' / 'heads' / 'demo').write_text(
        '3219308b1c0d4f5a8e7b6c9d2f0a1e3b4c5d6e7f\n'
    )

    write_settings(claude, [])
    write_transcript(claude / 'projects' / session_id / f'{session_id}.jsonl', [], 0, 0, 0, 0)
    today = datetime.now().strftime('%Y-%m-%d')
    tokens_log = claude / 'yas' / 'state' / 'runtime' / 'tokens.log'
    tokens_log.parent.mkdir(parents=True, exist_ok=True)
    tokens_log.write_text(
        f'{today} demo-prior-session 8200000 215000000 1450000\n'
    )
    _seed_yas_version(claude)


def _subagent_content_block(spec: object) -> dict[str, object] | None:
    """Turn a demo action spec into a synthetic transcript content block.

    ('text', '<snippet>')   -> a text block   (renders `GLYPH_REPLYING <snippet>`)
    ('<Tool>', {..input..}) -> a tool_use block (renders `GLYPH_TASKS Tool[arg]`)

    The two forms are distinguished by the second element's type (str vs dict),
    which lets a scenario interleave them in a single message (e.g. the
    [text, tool_use, text] case the parser must collapse to the tool_use).
    """
    if isinstance(spec, tuple) and len(spec) == 2:
        head, body = spec
        if head == 'text' and isinstance(body, str):
            return {'type': 'text', 'text': body}
        if isinstance(body, dict):
            return {'type': 'tool_use', 'name': str(head), 'input': body}
    return None


def write_subagents(
    claude_dir:  Path,
    session_id:  str,
    project_dir: Path,
    subagents:   list[tuple[object, ...]],
    *,
    age_seconds:  float = 0.0,
    mtime_age:    float = 0.0,
) -> None:
    """Each subagent entry: (agentType, description, billed_in, output_tokens[, action[, done_seconds_ago[, parent[, notifications[, lines[, start_age]]]]]]).

    parent (7th element, int > 0) is the 1-based index of this agent's spawner
    within `subagents`; it writes parentAgentId/spawnDepth into the meta.json so
    the (always-on) tree view can nest it.

    action selects the latest assistant message's content blocks:
      - (tool_name, input_dict)  -> a tool_use block  -> `GLYPH_TASKS Tool[arg]`
      - ('text', '<snippet>')    -> a text block       -> `GLYPH_REPLYING <snippet>`
      - a list of either form    -> interleaved blocks (the last tool_use still
        wins over a trailing text narration, matching the production parser)
      - None / absent            -> content omitted.
    age_seconds shifts the recorded start timestamp into the past so that duration
    and t/m rate are non-zero when rendered.
    done_seconds_ago (6th element, float > 0) marks the agent as Done: appends an
    end_turn line with a timestamp done_seconds_ago in the past, and sets the file
    mtime to match.
    mtime_age shifts the mtime of every non-Done agent's jsonl into the past by
    that many seconds (used to simulate idle/dirty cohort agents).

    notifications (8th element) is the authoritative four-state lifecycle
    signal: a chronological list of ``(status, seconds_ago)`` pairs, each
    written as a ``<task-notification>`` record (RunningSubagents.from_session
    ignores done_seconds_ago/end_turn entirely for status — only these tags
    decide 'completed'/'killed'/'failed'/'stopped' vs 'running'). The LATEST
    pair's status wins for ``RunningSubagent.status``; an empty status string
    in the latest pair keeps the agent 'running' even with earlier terminal
    pairs, which is how a resumed-and-still-live agent is synthesised (see
    RESUME below). ``len(notifications) > 1`` (or a growing mtime past the
    last notification) sets ``resumed``/``run_count`` accordingly. When the
    latest status is terminal, the file mtime is pinned to that pair's
    timestamp (frozen/idle); otherwise mtime is left fresh (still active).

    lines (9th element, a ``(lines_read, lines_changed)`` int pair) drives
    ``ToolCounts.per_agent`` for this agent: synthesises a Read tool_use +
    matching cat-n-shaped tool_result (``lines_read`` newlines) and an Edit
    tool_use whose ``old_string`` carries exactly ``lines_changed`` newlines
    (``new_string`` carries none, so ``max(nl(old), nl(new))`` lands exactly
    on the target). Written as its own message.id, independent of the
    displayed `action` above, so a scenario can set line counts without
    changing what the row's activity column shows. Omit/``None`` for an
    agent that should render the field blank (no lines data).

    start_age (10th element, float seconds) overrides this agent's start
    timestamp directly (``now - start_age``) instead of the default
    ``age_seconds - i`` stagger, letting one cohort mix widely different
    elapsed durations (e.g. straddling the 10-minute ``fmt_dur`` width
    jump) without needing giant `age_seconds`/index gaps.
    """
    # Match Claude Code's projects/ dir convention (cross-platform).
    # See statusline_command.py:RunningSubagents.from_session for full notes.
    project_slug = re.sub(r'[^A-Za-z0-9]', '-', str(project_dir))
    subagents_dir = claude_dir / 'projects' / project_slug / session_id / 'subagents'
    subagents_dir.mkdir(parents=True, exist_ok=True)
    for f in subagents_dir.iterdir():
        if f.is_file():  # skip the workflows/ subdir (managed by write_workflows)
            f.unlink()
    now = time.time()
    _demo_models = ('claude-sonnet-4-6', 'claude-haiku-4-5-20251001', 'claude-sonnet-4-6[1m]')
    depths: dict[int, int] = {}  # 1-based entry index -> spawnDepth (tree view)
    for i, row in enumerate(subagents, 1):
        # Stagger start timestamps 1s apart so first_timestamp ordering (and
        # therefore sibling order in the tree view) follows entry order rather
        # than filesystem glob order on ties. `start_age` (10th element), when
        # given, overrides this stagger entirely so a scenario can pin a
        # specific elapsed duration per-agent (independent of list position) —
        # needed to straddle the 10-minute fmt_dur width boundary within one
        # cohort (see the `lines` field below for why this exists).
        start_age_raw = row[9] if len(row) > 9 else None
        if isinstance(start_age_raw, (int, float)):
            start_age = float(start_age_raw)
        else:
            start_age = max(0.0, age_seconds - i)
        ts = (datetime.now() - timedelta(seconds=start_age)).astimezone().isoformat()
        agent_type_raw, description_raw, billed_in_raw, output_tokens_raw = row[:4]
        action_raw    = row[4] if len(row) > 4 else None
        done_secs_raw = row[5] if len(row) > 5 else None
        done_secs     = float(done_secs_raw) if isinstance(done_secs_raw, (int, float)) and done_secs_raw > 0 else None
        parent_raw    = row[6] if len(row) > 6 else None
        parent_idx    = int(parent_raw) if isinstance(parent_raw, (int, float)) and parent_raw > 0 else None
        notifications = row[7] if len(row) > 7 else None
        lines_raw     = row[8] if len(row) > 8 else None
        lines_spec    = (
            (int(lines_raw[0]), int(lines_raw[1]))
            if isinstance(lines_raw, tuple) and len(lines_raw) == 2
            else None
        )
        agent_type    = str(agent_type_raw)
        description   = str(description_raw)
        billed_in     = int(billed_in_raw) if isinstance(billed_in_raw, (int, float)) else 0
        output_tokens = int(output_tokens_raw) if isinstance(output_tokens_raw, (int, float)) else 0
        model  = _demo_models[(i - 1) % len(_demo_models)]
        name = f'demo-subagent-{i}'
        depths[i] = (depths.get(parent_idx, 0) + 1) if parent_idx else 1
        meta_obj: dict[str, object] = {'agentType': agent_type, 'description': description}
        if parent_idx:
            meta_obj['parentAgentId'] = f'demo-subagent-{parent_idx}'
            meta_obj['spawnDepth']    = depths[i]
        (subagents_dir / f'{name}.meta.json').write_text(json.dumps(meta_obj))
        jsonl = subagents_dir / f'{name}.jsonl'
        file_lines: list[str] = []
        if lines_spec is not None:
            # Synthesise a Read+tool_result pair and an Edit whose old/new
            # newline counts drive ToolCounts.per_agent, independent of the
            # display `action` above. Written as their own message.id so they
            # don't collide with the activity message's last-write-wins dedup
            # (count_transcript.md: LAST occurrence per message.id). The Read
            # tool_use line MUST precede its tool_result line in the file
            # (count_transcript pairs by tool_use_id seen-so-far).
            read_n, changed_n = lines_spec
            lines_blocks: list[dict[str, object]] = []
            read_tool_use_id = f'tool_demo_lines_read_{i}'
            if read_n > 0:
                lines_blocks.append({
                    'type':  'tool_use',
                    'id':    read_tool_use_id,
                    'name':  'Read',
                    'input': {'file_path': f'demo/lines-coverage-{i}.py'},
                })
            if changed_n > 0:
                lines_blocks.append({
                    'type':  'tool_use',
                    'name':  'Edit',
                    'input': {
                        'file_path':  f'demo/lines-coverage-{i}.py',
                        # 'x\n' repeated changed_n times carries exactly
                        # changed_n newlines; new_string carries none, so
                        # max(nl(old), nl(new)) == changed_n exactly.
                        'old_string': 'x\n' * changed_n,
                        'new_string': 'y',
                    },
                })
            if lines_blocks:
                lines_entry: dict[str, object] = {
                    'type':      'assistant',
                    'timestamp': ts,
                    'message': {
                        'id':      f'msg_demo_lines_{i}',
                        'role':    'assistant',
                        'model':   model,
                        'usage': {
                            'input_tokens': 0, 'cache_creation_input_tokens': 0,
                            'cache_read_input_tokens': 0, 'output_tokens': 0,
                        },
                        'content': lines_blocks,
                    },
                }
                file_lines.append(json.dumps(lines_entry))
            if read_n > 0:
                # cat -n shaped tool_result: read_n numbered lines, read_n
                # trailing newlines total (count_transcript's lines_read sniff).
                content = '\n'.join(f'{n}\tline{n}' for n in range(1, read_n + 1)) + '\n'
                result_entry: dict[str, object] = {
                    'type':      'user',
                    'timestamp': ts,
                    'message': {
                        'role': 'user',
                        'content': [
                            {'type': 'tool_result', 'tool_use_id': read_tool_use_id, 'content': content},
                        ],
                    },
                }
                file_lines.append(json.dumps(result_entry))
        if billed_in or output_tokens or action_raw:
            # cache_creation carries the bulk; input_tokens gets the remainder
            cache_creation = int(billed_in * 0.7)
            input_tokens   = billed_in - cache_creation
            msg: dict[str, object] = {
                'id':    f'msg_demo_agent_{i}',
                'role':  'assistant',
                'model': model,
                'usage': {
                    'input_tokens':                input_tokens,
                    'cache_creation_input_tokens': cache_creation,
                    'cache_read_input_tokens':     0,
                    'output_tokens':               output_tokens,
                },
            }
            if isinstance(action_raw, list):
                specs: list[object] = list(action_raw)
            elif action_raw is not None:
                specs = [action_raw]
            else:
                specs = []
            blocks = [b for b in (_subagent_content_block(s) for s in specs) if b is not None]
            if blocks:
                msg['content'] = blocks
            entry: dict[str, object] = {
                'type':      'assistant',
                'timestamp': ts,
                'message':   msg,
            }
            file_lines.append(json.dumps(entry))
        if file_lines:
            jsonl.write_text('\n'.join(file_lines) + '\n')
        else:
            jsonl.write_text('')
        if done_secs is not None:
            # Append an end_turn line so _parse_transcript records end_ts.
            done_ts = (datetime.now() - timedelta(seconds=done_secs)).astimezone().isoformat()
            end_entry: dict[str, object] = {
                'type':      'assistant',
                'timestamp': done_ts,
                'message': {
                    'id':         f'msg_demo_done_{i}',
                    'stop_reason': 'end_turn',
                    'role':        'assistant',
                    'usage': {
                        'input_tokens':                0,
                        'cache_creation_input_tokens': 0,
                        'cache_read_input_tokens':     0,
                        'output_tokens':               0,
                    },
                },
            }
            jsonl.write_text(jsonl.read_text() + json.dumps(end_entry) + '\n')
            mtime_for_done = now - done_secs
            os.utime(jsonl, (mtime_for_done, mtime_for_done))
        else:
            file_mtime = now - mtime_age
            os.utime(jsonl, (file_mtime, file_mtime))

        if isinstance(notifications, list) and notifications:
            # Authoritative four-state signal: <task-notification> records,
            # keyed by task-id == this transcript's filename stem (no
            # "agent-" prefix on demo transcripts, so task_id == `name`).
            # _collect_task_notifications only globs subagents/agent-*.jsonl
            # (demo transcripts aren't agent-prefixed) so these are written to
            # the top-level session transcript instead, which it always scans
            # unconditionally. See RunningSubagents.from_session.
            lines = []
            last_status = ''
            last_ts = now
            for status_str, secs_ago in notifications:
                notif_ts = now - float(secs_ago)
                last_status, last_ts = str(status_str), notif_ts
                content = (
                    f'<task-notification><task-id>{name}</task-id>'
                    f'<tool-use-id>tool_{name}</tool-use-id>'
                    f'<status>{status_str}</status></task-notification>'
                )
                lines.append(json.dumps({
                    'type':      'user',
                    'timestamp': datetime.fromtimestamp(notif_ts).astimezone().isoformat(),
                    'message':   {'role': 'user', 'content': content},
                }))
            session_jsonl = claude_dir / 'projects' / project_slug / f'{session_id}.jsonl'
            session_jsonl.parent.mkdir(parents=True, exist_ok=True)
            prior = session_jsonl.read_text() if session_jsonl.is_file() else ''
            session_jsonl.write_text(prior + '\n'.join(lines) + '\n')
            if last_status in _TERMINAL_STATUSES_DEMO:
                # Terminal: transcript goes idle right at the last notification.
                os.utime(jsonl, (last_ts, last_ts))
            else:
                # Non-terminal latest status (e.g. '') keeps the agent
                # 'running' per from_session's TERMINAL_STATUSES gate even
                # after an earlier terminal notification — the resumed-and-
                # still-live case. Transcript stays fresh (still being written).
                os.utime(jsonl, (now, now))


def write_workflows(
    claude_dir:  Path,
    session_id:  str,
    project_dir: Path,
    runs:        list[dict[str, object]],
    *,
    age_seconds: float = 0.0,
) -> None:
    """Synthesise workflow-cohort runs on disk for the demo.

    Each run dict: {
        'run_id': str,
        'name':   str | None,   # workflowName -> enrichment JSON; None omits it
        'phase':  str | None,   # latest workflow_phase title (needs name to emit)
        'status': str,          # run-JSON status (default 'running')
        'agents': [ (label, billed_in, output[, action[, done_seconds_ago]]), ... ],
    }
    Mirrors write_subagents per agent — a first user prompt line (the fallback
    label source), an assistant token/activity line, an optional end_turn — but
    nests transcripts under subagents/workflows/<run_id>/ and writes the
    enrichment JSON at workflows/<run_id>.json. A Done agent's mtime settles in
    the past (done_seconds_ago); running agents are fresh so the run stays inside
    the workflow liveness window.
    """
    project_slug = re.sub(r'[^A-Za-z0-9]', '-', str(project_dir))
    session_root = claude_dir / 'projects' / project_slug / session_id
    runs_root    = session_root / 'subagents' / 'workflows'
    json_root    = session_root / 'workflows'
    # Clear prior demo runs so scenarios don't bleed into each other.
    for root in (runs_root, json_root):
        if root.exists():
            shutil.rmtree(root)
    now = time.time()
    ts  = (datetime.now() - timedelta(seconds=age_seconds)).astimezone().isoformat()
    _demo_models = ('claude-sonnet-4-6', 'claude-haiku-4-5-20251001', 'claude-sonnet-4-6[1m]')
    for run in runs:
        run_id  = str(run['run_id'])
        agents  = list(run.get('agents') or [])  # type: ignore[arg-type]
        run_dir = runs_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        progress: list[dict[str, object]] = []
        phase = run.get('phase')
        if phase:
            progress.append({'type': 'workflow_phase', 'index': 1, 'title': str(phase)})
        for i, row in enumerate(agents, 1):
            label         = str(row[0])
            billed_in     = int(row[1]) if len(row) > 1 and isinstance(row[1], (int, float)) else 0
            output_tokens = int(row[2]) if len(row) > 2 and isinstance(row[2], (int, float)) else 0
            action_raw    = row[3] if len(row) > 3 else None
            done_secs_raw = row[4] if len(row) > 4 else None
            done_secs     = float(done_secs_raw) if isinstance(done_secs_raw, (int, float)) and done_secs_raw > 0 else None
            agent_id      = f'a{i:016x}'  # deterministic transcript stem
            model         = _demo_models[(i - 1) % len(_demo_models)]
            (run_dir / f'agent-{agent_id}.meta.json').write_text(json.dumps({'agentType': 'workflow-subagent'}))
            jsonl = run_dir / f'agent-{agent_id}.jsonl'
            cache_creation = int(billed_in * 0.7)
            input_tokens   = billed_in - cache_creation
            msg: dict[str, object] = {
                'id':    f'msg_wf_{run_id}_{i}',
                'role':  'assistant',
                'model': model,
                'usage': {
                    'input_tokens':                input_tokens,
                    'cache_creation_input_tokens': cache_creation,
                    'cache_read_input_tokens':     0,
                    'output_tokens':               output_tokens,
                },
            }
            specs  = [action_raw] if action_raw is not None else []
            blocks = [b for b in (_subagent_content_block(s) for s in specs) if b is not None]
            if blocks:
                msg['content'] = blocks
            lines = [
                json.dumps({'type': 'user', 'timestamp': ts, 'message': {'role': 'user', 'content': label}}),
                json.dumps({'type': 'assistant', 'timestamp': ts, 'message': msg}),
            ]
            if done_secs is not None:
                done_ts = (datetime.now() - timedelta(seconds=done_secs)).astimezone().isoformat()
                lines.append(json.dumps({
                    'type':      'assistant',
                    'timestamp': done_ts,
                    'message': {
                        'id':          f'msg_wf_done_{run_id}_{i}',
                        'stop_reason': 'end_turn',
                        'role':        'assistant',
                        'usage': {'input_tokens': 0, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0, 'output_tokens': 0},
                    },
                }))
            jsonl.write_text('\n'.join(lines) + '\n')
            file_mtime = (now - done_secs) if done_secs is not None else now
            os.utime(jsonl, (file_mtime, file_mtime))
            progress.append({'type': 'workflow_agent', 'index': i, 'label': label, 'agentId': agent_id})
        # Enrichment JSON only when a name is supplied (simulates a known run);
        # totalTokens is deliberately bogus — the reader sums per-agent instead.
        name = run.get('name')
        if name:
            json_root.mkdir(parents=True, exist_ok=True)
            (json_root / f'{run_id}.json').write_text(json.dumps({
                'runId':            run_id,
                'workflowName':     str(name),
                'status':           str(run.get('status', 'running')),
                'workflowProgress': progress,
                'totalTokens':      999_999,
            }))


def write_settings(claude_dir: Path, plugins: list[str]) -> None:
    settings = {'enabledPlugins': {p: True for p in plugins}}
    (claude_dir / 'settings.json').write_text(json.dumps(settings, indent=2) + '\n')


def _iso(epoch: float) -> str:
    'Format an epoch as a local ISO-8601 string (matches the parser''s expectations).'
    return datetime.fromtimestamp(epoch).astimezone().isoformat()


def _task_timeline(
    tasks: list[tuple[str, str, str]],
    base_time: float,
) -> dict[int, tuple[float | None, float | None]]:
    """Lay a contiguous timeline ending at `base_time` ("now").

    Returns {task_index: (started_at, completed_at)}. The in_progress task (if
    any) starts TASK_LIVE_SECONDS before now; completed tasks are placed
    sequentially before it using their TASK_DURATIONS so the last completed
    task's completed_at meets the in_progress start (or now). Pending tasks get
    (None, None). Total Elapsed = sum(completed durations) + live.
    """
    has_active = any(status == 'in_progress' for _, _, status in tasks)
    # Where the chain of completed tasks ends: at the in_progress start if there
    # is one, otherwise at "now".
    chain_end = base_time - TASK_LIVE_SECONDS if has_active else base_time

    times: dict[int, tuple[float | None, float | None]] = {}
    cursor = chain_end
    # Walk completed tasks backwards so the last one ends at chain_end.
    for i in range(len(tasks) - 1, -1, -1):
        if tasks[i][2] != 'completed':
            continue
        dur = TASK_DURATIONS[i % len(TASK_DURATIONS)]
        completed_at = cursor
        started_at = completed_at - dur
        times[i] = (started_at, completed_at)
        cursor = started_at
    for i, (_, _, status) in enumerate(tasks):
        if status == 'in_progress':
            times[i] = (base_time - TASK_LIVE_SECONDS, None)
        elif status == 'pending':
            times[i] = (None, None)
    return times


def write_transcript(
    transcript: Path,
    skills: list[str],
    total_in: int,
    total_cc: int,
    total_cr: int,
    total_out: int,
    tasks: list[tuple[str, str, str]] | None = None,
    base_time: float | None = None,
    cache_anchor_secs_ago: float | None = None,
    cache_1h_tier: bool = False,
    bash_calls: list[tuple[str, bool]] | None = None,
) -> None:
    if base_time is None:
        base_time = time.time()
    msgs = []
    n = max(1, len(skills))
    for i, skill in enumerate(skills or ['']):
        last = (i == n - 1)
        share_in   = total_in   // n + (total_in   % n if last else 0)
        share_cc   = total_cc   // n + (total_cc   % n if last else 0)
        share_cr   = total_cr   // n + (total_cr   % n if last else 0)
        share_out  = total_out  // n + (total_out  % n if last else 0)
        msg: dict[str, object] = {
            'id': f'msg_demo_{i+1}',
            'role': 'assistant',
            'usage': {
                'input_tokens':                share_in,
                'cache_creation_input_tokens': share_cc,
                'cache_read_input_tokens':     share_cr,
                'output_tokens':               share_out,
            },
        }
        if skill:
            msg['content'] = [{'type': 'tool_use', 'name': 'Skill', 'input': {'skill': skill}}]
        entry: dict[str, object] = {'type': 'assistant', 'message': msg}
        if last and cache_anchor_secs_ago is not None and (share_cr > 0 or share_cc > 0):
            _base = base_time if base_time is not None else time.time()
            entry['timestamp'] = _iso(_base - cache_anchor_secs_ago)
            if cache_1h_tier:
                usage = msg['usage']
                if isinstance(usage, dict):
                    cc = usage.setdefault('cache_creation', {})
                    if isinstance(cc, dict):
                        cc['ephemeral_1h_input_tokens'] = max(1, share_cc)
        msgs.append(entry)
    if tasks:
        times = _task_timeline(tasks, base_time)
        # TaskCreate stamped at the earliest started_at (start of the span), so
        # the parser's Total Elapsed anchor lands at the timeline origin.
        starts = [st for st, _ in times.values() if st is not None]
        create_ts = min(starts) if starts else base_time
        msgs.append({
            'type': 'assistant',
            'timestamp': _iso(create_ts),
            'message': {
                'id': 'msg_task_create',
                'role': 'assistant',
                'content': [
                    {
                        'type': 'tool_use',
                        'name': 'TaskCreate',
                        'input': {'subject': subj, 'activeForm': af},
                    }
                    for subj, af, _ in tasks
                ],
            },
        })
        # Build one TaskUpdate message per transition, then emit ascending by
        # timestamp so the parser (which folds in file order, last write wins)
        # sees each task's in_progress before its completed.
        events: list[tuple[float, int, dict[str, object]]] = []
        for i, (_, af, status) in enumerate(tasks):
            if status == 'pending':
                continue
            started_at, completed_at = times[i]
            if started_at is not None:
                events.append((started_at, 0, {
                    'type': 'tool_use',
                    'name': 'TaskUpdate',
                    'input': {'taskId': str(i + 1), 'status': 'in_progress', 'activeForm': af},
                }))
            if status == 'completed' and completed_at is not None:
                events.append((completed_at, 1, {
                    'type': 'tool_use',
                    'name': 'TaskUpdate',
                    'input': {'taskId': str(i + 1), 'status': 'completed', 'activeForm': af},
                }))
        events.sort(key=lambda e: (e[0], e[1]))
        for seq, (ts, _kind, content) in enumerate(events):
            msgs.append({
                'type': 'assistant',
                'timestamp': _iso(ts),
                'message': {
                    'id': f'msg_task_update_{seq}',
                    'role': 'assistant',
                    'content': [content],
                },
            })
    for i, (command, background) in enumerate(bash_calls or []):
        msgs.append({
            'type': 'assistant',
            'timestamp': _iso(base_time),
            'message': {
                'id': f'msg_bash_{i}',
                'role': 'assistant',
                'content': [{
                    'type': 'tool_use',
                    'name': 'Bash',
                    'input': {'command': command, 'run_in_background': background},
                }],
            },
        })
    transcript.write_text('\n'.join(json.dumps(m) for m in msgs) + '\n')


def mutate_session_info(tmpdir: Path, session_id: str, raw: dict[str, object]) -> str:
    project = tmpdir / 'my-project'
    raw['cwd'] = str(project)
    workspace = raw.get('workspace')
    if not isinstance(workspace, dict):
        workspace = {}
        raw['workspace'] = workspace
    workspace['project_dir'] = str(project)
    raw['transcript_path'] = str(
        tmpdir / '.claude' / 'projects' / session_id / f'{session_id}.jsonl'
    )
    resets = int(time.time()) + 7200
    rate_limits = raw.get('rate_limits')
    if not isinstance(rate_limits, dict):
        rate_limits = {}
        raw['rate_limits'] = rate_limits
    five_hour = rate_limits.get('five_hour')
    if not isinstance(five_hour, dict):
        five_hour = {}
        rate_limits['five_hour'] = five_hour
    five_hour['resets_at'] = resets
    seven_day = rate_limits.get('seven_day')
    if not isinstance(seven_day, dict):
        seven_day = {}
        rate_limits['seven_day'] = seven_day
    seven_day['resets_at'] = resets
    raw['thinking'] = {'enabled': True}
    raw['effort'] = {'level': 'high'}
    return json.dumps(raw)


SOFT_LIMIT = 150_000


def render_once(env: dict[str, str], payload: str) -> str:
    result = subprocess.run(
        [sys.executable, str(STATUSLINE_SCRIPT)],
        input=payload,
        text=True,
        env=env,
        capture_output=True,
        check=True,
    )
    return result.stdout


DEMO_STEPS = 60
DEMO_DELAY = 0.10
DEMO_DURATION = DEMO_STEPS * DEMO_DELAY  # real seconds the demo runs
# history() uses window = WINDOW * 2, so set WINDOW = DEMO_DURATION / 2 so bars travel
# the full graph width over the course of the demo
DEMO_TOKEN_WINDOW = DEMO_DURATION / 2

# Sparkline shape: small baseline delta per step with isolated bursts so peaks
# of varying heights sit on a quiet floor instead of forming a dense ribbon.
RATE_BASE_DELTA = 250
RATE_PEAK_PROFILE = {
    8:  28_000,
    22: 82_000,
    37: 18_000,
    49: 56_000,
}


def _ensure_nested(d: dict[str, object], *keys: str) -> dict[str, object]:
    'Walk into nested dicts by key path, creating empty dicts as needed.'
    cur = d
    for k in keys:
        val = cur.get(k)
        if not isinstance(val, dict):
            val = {}
            cur[k] = val
        cur = val
    return cur


def animate(env: dict[str, str], raw: dict[str, object], tmpdir: Path, session_id: str, steps: int = DEMO_STEPS, delay: float = DEMO_DELAY) -> None:
    ctx_win   = _ensure_nested(raw, 'context_window')
    rate_lims = _ensure_nested(raw, 'rate_limits')
    five_hour = _ensure_nested(rate_lims, 'five_hour')
    seven_day = _ensure_nested(rate_lims, 'seven_day')
    cost      = _ensure_nested(raw, 'cost')
    base_duration_ms = int(cost.get('total_duration_ms', 0))

    claude       = tmpdir / '.claude'
    project      = tmpdir / 'my-project'
    transcript_p = claude / 'projects' / session_id / f'{session_id}.jsonl'
    rate_log     = claude / 'yas' / 'state' / 'runtime' / 'token-rate.log'
    rate_log.parent.mkdir(parents=True, exist_ok=True)

    KEEP = max(300.0, DEMO_TOKEN_WINDOW * 4)

    sys.stdout.write('\n\n')
    sys.stdout.write('\033[?25l')  # hide cursor to prevent it jumping during redraws
    sys.stdout.flush()
    last_lines = 0
    rate_cumul_in = 0

    # Fixed anchor for the task timeline so completed durations stay frozen and
    # the in_progress live timer (real now - started_at) advances across frames.
    task_base = time.time()

    try:
        for i in range(steps + 1):
            pct = i / steps

            total_in   = int(150_000 * pct * 1.25)
            total_cc   = int(total_in * 0.18)
            total_cr   = int(total_in * 12.0)
            total_out  = int(7_500 * pct + 120)

            skill_idx    = min(int(pct * len(SKILLS_PROGRESSION)),    len(SKILLS_PROGRESSION) - 1)
            plugin_idx   = min(int(pct * len(PLUGINS_PROGRESSION)),   len(PLUGINS_PROGRESSION) - 1)
            subagent_idx = min(int(pct * len(SUBAGENTS_PROGRESSION)), len(SUBAGENTS_PROGRESSION) - 1)
            openspec_idx = min(int(pct * len(OPENSPEC_PROGRESSION)),  len(OPENSPEC_PROGRESSION) - 1)
            skills_now   = SKILLS_PROGRESSION[skill_idx]
            plugins_now  = PLUGINS_PROGRESSION[plugin_idx]
            subagent_now = SUBAGENTS_PROGRESSION[subagent_idx]
            openspec_now = OPENSPEC_PROGRESSION[openspec_idx]

            tasks_now = task_state_for(pct)
            cache_offset = pct * 280.0  # ages anchor from 0 → 280s so countdown sweeps 300s → ~20s
            write_transcript(
                transcript_p, skills_now, total_in, total_cc, total_cr, total_out,
                tasks=tasks_now, base_time=task_base,
                cache_anchor_secs_ago=cache_offset,
            )
            write_settings(claude, plugins_now)
            write_subagents(claude, session_id, project, subagent_now, age_seconds=pct * 120)
            write_openspec_changes(project, openspec_now)

            now = time.time()
            rate_cumul_in += RATE_PEAK_PROFILE.get(i, RATE_BASE_DELTA)
            cumul_out = total_out

            existing = rate_log.read_text().splitlines() if rate_log.exists() else []
            kept = [ln for ln in existing if ln and now - float(ln.split()[0]) <= KEEP]
            kept.append(f'{now:.3f} {session_id} {rate_cumul_in} {cumul_out}')
            rate_log.write_text('\n'.join(kept) + '\n')

            cost['total_duration_ms']      = base_duration_ms + int(i * delay * 1000)

            ctx_win['total_input_tokens']  = total_in
            ctx_win['total_output_tokens'] = total_out
            ctx_win['used_percentage']     = round(pct * 100.0, 1)
            # five_hour ideal_pct ≈ 60% (resets_at=now+2h, window=5h → 3h elapsed / 5h = 60%)
            # sine arc: candle at start/end, flame at midpoint, hitting all colour thresholds
            burn_5h = 60.0 + 22.0 * math.sin(pct * 2 * math.pi - math.pi / 2)
            five_hour['used_percentage'] = round(burn_5h, 1)
            seven_day['used_percentage'] = round(35 + pct * 30, 1)

            out = render_once(env, json.dumps(raw))
            # Write cursor-up + new content + erase-below in one call so the
            # terminal never shows a blank frame between redraws.
            frame = ''
            if last_lines > 1:
                frame += f'\033[{last_lines - 1}A\r'
            frame += out
            frame += '\033[J'  # erase any leftover lines from a taller previous frame
            sys.stdout.write(frame)
            sys.stdout.flush()
            last_lines = out.count('\n') + 1
            time.sleep(delay)
    finally:
        sys.stdout.write('\033[?25h')  # always restore cursor
        sys.stdout.flush()

    sys.stdout.write('\n\n\n')


SNAPSHOT_COLS = 160    # wide layout shows every section
SNAP_WINDOW   = 60.0   # STATUSLINE_TOKEN_WINDOW for snapshots (production default)

# Per-scenario width tiers (see ScenarioConfig.columns). Chosen relative to the
# renderer's own breakpoints (claude/yas/constants.py: NARROW_WIDTH=55,
# MEDIUM_WIDTH=80): WIDE_COLS matches the existing SNAPSHOT_COLS default,
# MEDIUM_COLS sits comfortably above MEDIUM_WIDTH so the medium layout renders
# without falling to narrow, and NARROW_COLS sits below NARROW_WIDTH so the
# narrow/collapsed layout (and tree mode's model-only shed ladder) is reliably
# exercised.
WIDE_COLS   = SNAPSHOT_COLS
MEDIUM_COLS = 90
NARROW_COLS = 50


@dataclass
class ScenarioConfig:
    name:          str
    model_id:      str                       = 'claude-sonnet-4-6'
    model_name:    str                       = 'Sonnet 4.6'
    effort:        str                       = ''
    thinking:      bool                      = False
    context_pct:   float                     = 0.20
    skills:        list[str]                 = field(default_factory=list)
    plugins:       list[str]                 = field(default_factory=list)
    subagents:     list[tuple[object, ...]]         = field(default_factory=list)
    workflows:     list[dict[str, object]]   = field(default_factory=list)
    openspec:      list[tuple[str, int, int]]= field(default_factory=list)
    tasks:         list[tuple[str, str, str]]= field(default_factory=list)
    # None omits the bucket from `rate_limits` entirely (simulates a Claude
    # Code setup that doesn't supply that window at all), distinct from 0.0
    # which is a present-but-idle bucket (must still render `∞`).
    five_hour_pct: float | None               = 30.0
    seven_day_pct: float | None               = 20.0
    yas_toml:      str | None                = None
    # When set, render_scenario pre-seeds `rate-limit.log` with baseline
    # samples so the `[rate_limits]` config-driven synthesizer (rate_limits_sim.py)
    # has a real trailing-window history to diff against, instead of computing
    # 0% from a single (this-tick-only) sample.
    seed_rate_limit_log: bool                = False
    subagent_mtime_age: float                = 0.0
    cache_anchor_secs_ago: float | None      = None
    cache_1h_tier:         bool              = False
    columns:       int | None                = None
    # (command, rss_mb, cpu_seconds, elapsed_seconds, background) per running
    # shell command; rendered via the YAS_SHELL_COMMANDS_FIXTURE process table.
    shell_commands: list[tuple[str, int, float, float, bool]] = field(default_factory=list)


_SHELL_SUBAGENTS: list[tuple[object, ...]] = [
    ('explore',         'Search codebase - looking for token tracking', 3_200,   420, ('Bash', {'command': 'grep -rn "billed_in" claude/'})),
    ('general-purpose', 'Fix sparkline - update bucket algorithm',      8_700, 1_850, ('Read', {'file_path': 'claude/statusline_command.py'})),
]

_SHELL_COMMANDS: list[tuple[str, int, float, float, bool]] = [
    ('make demo/img',                                              600,  300.0,  120.0, False),
    ('tail -f /var/log/very/long/path/to/application/output/' * 2 + 'server.log', 40, 0.5, 3_600.0, True),
    ('uv run pytest -q',                                         3_072,   40.0,   95.0, False),
]

_SHELL_LONG_COMMANDS: list[tuple[str, int, float, float, bool]] = [
    ('cd /home/user/dev/project/.scratch/feat-section-taxonomy/reanalyse/w2 && '
     "jq -c '.[]' results.json | ./run.sh --tracks 54 --out /tmp/reanalysed.json | tail -3", 27, 12.0, 282.0, False),
    ('make demo/img', 600, 300.0, 120.0, False),
]

_SHELL_LONG_SUBAGENTS: list[tuple[object, ...]] = [
    ('explore', 'Search codebase - looking for token tracking', 3_200, 420,
     ('Bash', {'command': 'jq -c ".[]" results.json; ./run.sh | tail -3'})),
    ('general-purpose', 'Fix sparkline - update bucket algorithm', 8_700, 1_850, ('Read', {'file_path': 'claude/statusline_command.py'})),
]


_USAGE_SUBAGENTS: list[tuple[object, ...]] = [
    ('explore', 'Build the release binary', 4_100, 600, ('Bash', {'command': 'cargo build --release --workspace'})),
    ('general-purpose', 'Fix sparkline - update bucket algorithm', 8_700, 1_850, ('Read', {'file_path': 'claude/statusline_command.py'})),
]

# The first command is run by the first subagent above (matched by its text); the second by the main thread.
_USAGE_COMMANDS: list[tuple[str, int, float, float, bool]] = [
    ('cargo build --release --workspace', 900, 240.0, 95.0, False),
    ('make demo/img',                     600, 300.0, 120.0, False),
]


_SHELL_BADGE_TOML = '''
[shell_commands]
enabled = true
style = "badge"
position = "right"
cpu = { mode = "average", warn_percent = 150 }
memory = { warn_mb = 2048 }
'''

_SHELL_LIST_TOML = '''
[shell_commands]
enabled = true
style = "list"
position = "below"
max_items = 2
max_command_width = 40
elapsed = { enabled = true }
cpu = { enabled = true, mode = "average", warn_percent = 150 }
memory = { enabled = true, warn_mb = 2048 }
'''

_SHELL_SIDE_TOML = '''
[shell_commands]
enabled = true
style = "list"
position = "right"
max_items = 2
max_command_width = 40
elapsed = { enabled = true }
cpu = { enabled = true, mode = "average", warn_percent = 150 }
memory = { enabled = true, warn_mb = 2048 }
'''

# The -200 shell-commands scenarios fill the terminal instead of stopping at max_width.
_SHELL_WIDTHS = (('', None, ''), ('-80', 80, ''), ('-200', 200, '[layout]\nfull_width = true\nlabels = true\n'))


def _subagent_bash_commands(subagents: list[tuple[object, ...]]) -> set[str]:
    'Commands of the Bash tool_use actions in a scenario\'s subagents (their transcripts, not the main one, record them).'
    out: set[str] = set()
    for row in subagents:
        action = row[4] if len(row) > 4 else None
        if isinstance(action, tuple) and len(action) == 2 and action[0] == 'Bash' and isinstance(action[1], dict):
            out.add(str(action[1].get('command', '')))
    return out


def build_shell_fixture(commands: list[tuple[str, int, float, float, bool]]) -> dict[str, object]:
    """Process table: statusline -> sh -> claude -> wrapper bash -> child."""
    procs: list[dict[str, object]] = [
        {'pid': 10, 'ppid': 1,  'rss_kb': 300_000, 'cpu_s': 900.0, 'elapsed_s': 7_200.0, 'argv': '/usr/bin/claude'},
        {'pid': 20, 'ppid': 10, 'rss_kb': 2_000,   'cpu_s': 0.1,   'elapsed_s': 1.0,     'argv': '/bin/sh -c statusline'},
        {'pid': 30, 'ppid': 20, 'rss_kb': 30_000,  'cpu_s': 0.1,   'elapsed_s': 1.0,     'argv': 'python3 statusline_command.py'},
    ]
    for i, (command, rss_mb, cpu_s, elapsed_s, _bg) in enumerate(commands):
        pid = 100 + 10 * i
        argv = (
            '/bin/bash -c source /home/u/.claude/shell-snapshots/snapshot-bash-1.sh'
            f" && eval '{command}' < /dev/null && pwd -P >| /tmp/claude-{i:04x}-cwd"
        )
        procs.append({'pid': pid, 'ppid': 10, 'rss_kb': 4_000, 'cpu_s': 0.0, 'elapsed_s': elapsed_s, 'argv': argv})
        for j in range(2):
            procs.append({
                'pid': pid + 1 + j, 'ppid': pid,
                'rss_kb': (rss_mb * 1024 - 4_000) // 2,
                'cpu_s': cpu_s / 2, 'elapsed_s': elapsed_s,
                'argv': f'worker-{j} {command.split()[0]}',
            })
    return {'self_pid': 30, 'processes': procs}


SCENARIOS: list[ScenarioConfig] = [
    ScenarioConfig(
        name        = 'sonnet-thinking',
        model_id    = 'claude-sonnet-4-6',
        model_name  = 'Sonnet 4.6',
        effort      = 'medium',
        thinking    = True,
        context_pct = 0.20,
        skills      = ['grill-me', 'caveman'],
        plugins     = ['openspec@0.1.0'],
        five_hour_pct = 30.0,
        seven_day_pct = 20.0,
        cache_anchor_secs_ago = 30.0,
    ),
    ScenarioConfig(
        name        = 'opus-thinking',
        model_id    = 'claude-opus-4-7',
        model_name  = 'Opus 4.7',
        effort      = 'high',
        thinking    = True,
        context_pct = 0.45,
        skills      = ['grill-me', 'caveman', 'tdd'],
        plugins     = ['openspec@0.1.0', 'frontend-design@0.3.2'],
        five_hour_pct = 52.0,
        seven_day_pct = 41.0,
        cache_anchor_secs_ago = 150.0,
    ),
    ScenarioConfig(
        name        = 'tasks',
        effort      = 'high',
        thinking    = True,
        context_pct = 0.15,
        skills      = ['grill-me', 'caveman'],
        plugins     = ['openspec@0.1.0'],
        tasks       = [
            ('Audit gradient palette',  'Auditing gradient palette',  'completed'),
            ('Wire alert-mode pill',    'Wiring alert-mode pill',     'completed'),
            ('Refactor border math',    'Refactoring border math',    'completed'),
            ('Update CONTEXT.md',       'Updating CONTEXT.md',        'completed'),
            ('Add sparkline buckets',   'Adding sparkline buckets',   'completed'),
            ('Fix elbow column math',   'Fixing elbow column math',   'in_progress'),
            ('Wire token tracker',      'Wiring token tracker',       'pending'),
            ('Backfill renderer tests', 'Backfilling renderer tests', 'pending'),
        ],
        five_hour_pct = 22.0,
        seven_day_pct = 15.0,
        cache_anchor_secs_ago = 90.0,
    ),
    ScenarioConfig(
        name        = 'openspec',
        effort      = 'high',
        thinking    = True,
        context_pct = 0.48,
        skills      = ['grill-me', 'caveman', 'tdd'],
        plugins     = ['openspec@0.1.0', 'frontend-design@0.3.2'],
        openspec    = [
            ('add-gradient-engine',        6, 8),
            ('port-statusline-to-python',  3, 8),
            ('wire-alert-mode-pill',       1, 6),
        ],
        five_hour_pct = 46.0,
        seven_day_pct = 37.0,
        cache_anchor_secs_ago = 210.0,
    ),
    ScenarioConfig(
        name        = 'subagents',
        effort      = 'high',
        thinking    = True,
        context_pct = 0.48,
        skills      = ['grill-me', 'caveman', 'tdd'],
        plugins     = ['openspec@0.1.0', 'frontend-design@0.3.2'],
        subagents   = [
            ('explore',         'Search codebase - looking for token tracking', 3_200,   420, ('Bash', {'command': 'grep -rn "billed_in" claude/statusline_command.py'})),
            ('general-purpose', 'Fix sparkline - update bucket algorithm',      8_700, 1_850, ('Edit', {'file_path': 'claude/statusline_command.py', 'old_string': 'a', 'new_string': 'b'})),
            ('claude',          'Review border math implementation',            5_400,   980, ('Read', {'file_path': 'claude/statusline_command.py'})),
            # Text-only latest message -> the replying-snippet path. Medium
            # snippet (~50 cols) now shows in full past the old 36-col cap.
            ('narrator',        'Narrate progress on the gradient fix',         4_100,   610, ('text', 'Tracing the off-by-one in the gradient border math')),
            # Long snippet (>100 cols) -> exercises the 100-col ceiling + ellipsis.
            ('reviewer',        'Summarise the border-math review',             6_300, 1_120, ('text', 'Investigating why the gradient border shifts a column under load and patching the off-by-one before the snapshot diff settles')),
        ],
        five_hour_pct = 46.0,
        seven_day_pct = 37.0,
    ),
    ScenarioConfig(
        name        = 'workflows',
        effort      = 'high',
        thinking    = True,
        context_pct = 0.40,
        skills      = ['grill-me', 'caveman'],
        plugins     = ['openspec@0.1.0'],
        # One live workflow run: 2 agents Done (settled within the 120s liveness
        # window) + 2 still running. Wide shows header + 4 twoline agent rows +
        # summary; medium/narrow collapse to header + summary only.
        workflows   = [
            {
                'run_id': 'wf_d8212a1d-34a',
                'name':   'investigate-airship-timeout',
                'phase':  'Analyse',
                'status': 'running',
                'agents': [
                    ('fetch-notebook', 11_500, 1_200, ('Bash', {'command': 'curl -s -H "Authorization: Bearer ***" https://host/api/2.0/workspace/export'}), 40.0),
                    ('fetch-wrapper',   9_300,   980, ('Read', {'file_path': 'transforms/airship_enrichment.py'}), 25.0),
                    ('run-history',    14_200, 2_100, ('text', 'Building the run-history timeline across the last 30 days')),
                    ('synthesise',      6_800,   740, ('Edit', {'file_path': 'findings.md', 'old_string': 'a', 'new_string': 'b'})),
                ],
            },
        ],
        five_hour_pct = 44.0,
        seven_day_pct = 33.0,
        cache_anchor_secs_ago = 120.0,
    ),
    ScenarioConfig(
        name        = 'kitchen-sink',
        model_id    = 'claude-opus-4-7',
        model_name  = 'Opus 4.7',
        effort      = 'high',
        thinking    = True,
        context_pct = 0.75,
        skills      = ['grill-me', 'caveman', 'tdd', 'rocky:rocky'],
        plugins     = ['openspec@0.1.0', 'frontend-design@0.3.2', 'rocky@0.1.0'],
        subagents   = [
            ('explore',         'Search codebase - looking for token tracking', 3_200,   420, ('Bash', {'command': 'grep -rn "billed_in" claude/statusline_command.py'})),
            ('general-purpose', 'Fix sparkline - update bucket algorithm',      8_700, 1_850, ('Edit', {'file_path': 'claude/statusline_command.py', 'old_string': 'a', 'new_string': 'b'})),
            ('claude',          'Review border math implementation',            5_400,   980, ('Read', {'file_path': 'claude/statusline_command.py'})),
            # Text-only latest message -> replying snippet, shown even in the
            # narrower side-by-side right column.
            ('narrator',        'Narrate the gradient fix',                     4_100,   610, ('text', 'Patching the gradient border off-by-one')),
            # Interleaved [text, tool_use, text]: the trailing narration must not
            # mask the real tool call, so this still renders the tool_use verb.
            ('grep-bot',        'Confirm no stray callers remain',             2_900,   480, [
                ('text', 'Let me double-check there are no stragglers'),
                ('Grep', {'pattern': 'billed_in', 'path': 'claude/'}),
                ('text', 'Found them, wiring the fix now'),
            ]),
        ],
        openspec    = [
            ('add-gradient-engine',        6, 8),
            ('port-statusline-to-python',  3, 8),
            ('wire-alert-mode-pill',       1, 6),
        ],
        tasks       = [
            ('Audit gradient palette',  'Auditing gradient palette',  'completed'),
            ('Wire alert-mode pill',    'Wiring alert-mode pill',     'completed'),
            ('Refactor border math',    'Refactoring border math',    'completed'),
            ('Update CONTEXT.md',       'Updating CONTEXT.md',        'completed'),
            ('Add sparkline buckets',   'Adding sparkline buckets',   'completed'),
            ('Fix elbow column math',   'Fixing elbow column math',   'in_progress'),
            ('Wire token tracker',      'Wiring token tracker',       'pending'),
            ('Backfill renderer tests', 'Backfilling renderer tests', 'pending'),
        ],
        five_hour_pct = 58.0,
        seven_day_pct = 49.0,
        cache_anchor_secs_ago = 265.0,
    ),
    ScenarioConfig(
        name        = 'full-context',
        effort      = 'high',
        thinking    = True,
        context_pct = 0.97,
        skills      = ['grill-me', 'caveman', 'tdd', 'rocky:rocky'],
        plugins     = ['openspec@0.1.0', 'frontend-design@0.3.2'],
        five_hour_pct = 71.0,
        seven_day_pct = 62.0,
        cache_anchor_secs_ago = 240.0,
    ),
    ScenarioConfig(
        # Exercises the top-row shed ladder's last-resort rung
        # (model_form='short', see layout.py build_wide's `model_form` local):
        # a long display name + effort parenthetical ('Opus 5 1M (low)') is
        # wide enough that narrowing forces the pill down to 'O5-1m (l)'
        # before the 5h/7d stats would otherwise get dropped. See
        # render/gradient.py model_form_short()/thinking_form_short().
        name        = 'long-model-name',
        model_id    = 'claude-opus-5[1m]',
        model_name  = 'Opus 5 Extended Thinking Reasoning Deep Research Preview 1M',
        effort      = 'low',
        thinking    = True,
        context_pct = 0.30,
        skills      = ['grill-me', 'caveman'],
        plugins     = ['openspec@0.1.0'],
        five_hour_pct = 35.0,
        seven_day_pct = 24.0,
        cache_anchor_secs_ago = 60.0,
    ),
    ScenarioConfig(
        name        = 'config-error',
        model_id    = 'claude-opus-4-7',
        model_name  = 'Opus 4.7',
        effort      = 'high',
        thinking    = True,
        context_pct = 0.45,
        skills      = ['grill-me', 'caveman'],
        plugins     = ['openspec@0.1.0'],
        five_hour_pct = 46.0,
        seven_day_pct = 37.0,
        # Three rejected knobs → compact in-border error row. max_width is the
        # wrong type, soft_limit is out of range, bg_shift is an unknown enum;
        # each falls back to its default while the valid theme still applies.
        yas_toml    = (
            '[layout]\n'
            'max_width = "banana"\n'
            '[tokens]\n'
            'soft_limit = -5\n'
            '[appearance]\n'
            'theme = "catppuccin-mocha"\n'
            'bg_shift = "purple"\n'
        ),
    ),
    ScenarioConfig(
        name        = 'cohort-all-running',
        context_pct = 0.35,
        subagents   = [
            ('explore',         'Scan codebase for token tracking',   2_100,   180, ('Bash', {'command': 'grep -rn "billed_in" claude/'})),
            ('general-purpose', 'Analyse sparkline bucket algorithm',  5_600,   720, ('Read', {'file_path': 'claude/statusline_command.py'})),
            ('claude',          'Draft border-math refactor',          3_800,   540, ('Edit', {'file_path': 'claude/statusline_command.py', 'old_string': 'x', 'new_string': 'y'})),
            # Text-only latest message -> replying snippet alongside the cohort.
            ('narrator',        'Narrate the refactor plan',           2_400,   320, ('text', 'Walking the border helpers before touching the elbow math')),
        ],
        five_hour_pct = 30.0,
        seven_day_pct = 20.0,
    ),
    ScenarioConfig(
        name        = 'cohort-mixed',
        context_pct = 0.42,
        subagents   = [
            ('explore',         'Scan codebase for token tracking',   2_100,   180, ('Bash', {'command': 'grep -rn "billed_in" claude/'}), 45.0),
            ('general-purpose', 'Analyse sparkline bucket algorithm',  5_600,   720, ('Read', {'file_path': 'claude/statusline_command.py'})),
            ('claude',          'Draft border-math refactor',          3_800,   540, ('Edit', {'file_path': 'claude/statusline_command.py', 'old_string': 'x', 'new_string': 'y'}), 30.0),
        ],
        five_hour_pct = 30.0,
        seven_day_pct = 20.0,
    ),
    ScenarioConfig(
        name        = 'cohort-all-done-grace',
        context_pct = 0.38,
        subagents   = [
            ('explore',         'Scan codebase for token tracking',   2_100,   180, ('Bash', {'command': 'grep -rn "billed_in" claude/'}), 8.0),
            ('general-purpose', 'Analyse sparkline bucket algorithm',  5_600,   720, ('Read', {'file_path': 'claude/statusline_command.py'}), 12.0),
            ('claude',          'Draft border-math refactor',          3_800,   540, ('Edit', {'file_path': 'claude/statusline_command.py', 'old_string': 'x', 'new_string': 'y'}), 5.0),
        ],
        five_hour_pct = 30.0,
        seven_day_pct = 20.0,
    ),
    ScenarioConfig(
        name               = 'cohort-dirty-janitor',
        context_pct        = 0.33,
        subagents          = [
            ('explore',         'Scan codebase for token tracking',   2_100,   180, ('Bash', {'command': 'grep -rn "billed_in" claude/'})),
            ('general-purpose', 'Analyse sparkline bucket algorithm',  5_600,   720, ('Read', {'file_path': 'claude/statusline_command.py'})),
        ],
        five_hour_pct      = 30.0,
        seven_day_pct      = 20.0,
        subagent_mtime_age = 40.0,
    ),
    # --- Subagent tree-mode scenarios ---------------------------------
    # Five distinct configs, each rendered at wide/medium/narrow via the
    # per-scenario `columns` field (see WIDE_COLS/MEDIUM_COLS/NARROW_COLS).
    # Descriptions/activity snippets below are mined from real Claude Code
    # subagent transcripts on this machine (~/.claude/projects/**/*.jsonl and
    # sibling subagents/*.meta.json — the same method documented in
    # .scratch/session-analysis.md) with every real project name, file path,
    # and code fragment swapped for a fictional equivalent of the same shape;
    # nothing in the strings below identifies the source project or repo.

    # Config 1 — single subagent under the root.
    ScenarioConfig(
        name        = 'subagent-tree-wide-single',
        context_pct = 0.35,
        subagents   = [
            ('general-purpose',
             'Implement the window-based acceptance state machine with replay support in detector.py',
             61_000, 2_400,
             [('Edit', {'file_path': 'render/detector.py', 'old_string': 'a', 'new_string': 'b'}),
              ('text', 'Wiring the replay buffer through the state machine now that the acceptance windows are stable')],
             None, None, None, (340, 95)),
        ],
        five_hour_pct = 28.0,
        seven_day_pct = 18.0,
        columns     = WIDE_COLS,
    ),
    ScenarioConfig(
        name        = 'subagent-tree-medium-single',
        context_pct = 0.35,
        subagents   = [
            ('general-purpose',
             'Implement the window-based acceptance state machine with replay support in detector.py',
             61_000, 2_400,
             [('Edit', {'file_path': 'render/detector.py', 'old_string': 'a', 'new_string': 'b'}),
              ('text', 'Wiring the replay buffer through the state machine now that the acceptance windows are stable')],
             None, None, None, (340, 95)),
        ],
        five_hour_pct = 28.0,
        seven_day_pct = 18.0,
        columns     = MEDIUM_COLS,
    ),
    ScenarioConfig(
        name        = 'subagent-tree-narrow-single',
        context_pct = 0.35,
        subagents   = [
            ('general-purpose',
             'Implement the window-based acceptance state machine with replay support in detector.py',
             61_000, 2_400,
             [('Edit', {'file_path': 'render/detector.py', 'old_string': 'a', 'new_string': 'b'}),
              ('text', 'Wiring the replay buffer through the state machine now that the acceptance windows are stable')],
             None, None, None, (340, 95)),
        ],
        five_hour_pct = 28.0,
        seven_day_pct = 18.0,
        columns     = NARROW_COLS,
    ),

    # Config 2 — several flat siblings, each a different agentType (and,
    # since write_subagents round-robins 3 models by index, a different
    # model too — no per-agent model override needed).
    ScenarioConfig(
        name        = 'subagent-tree-wide-types',
        context_pct = 0.40,
        subagents   = [
            ('ui',      'Add a light/dark toggle to the report template',      18_400,  1_050, ('Edit', {'file_path': 'render/template.py', 'old_string': 'a', 'new_string': 'b'})),
            ('ops',     'Fix the backend build, lint, and test pipeline',       9_200,    480, ('Bash', {'command': 'make lint test'})),
            ('fractal', 'Add supersampling to the offline render pass',        26_700,  1_820, ('Edit', {'file_path': 'render/pipeline.py', 'old_string': 'a', 'new_string': 'b'})),
            ('api',     'Wire the v3 resolver into FramePipeline',             33_100,  1_400, ('Read', {'file_path': 'render/pipeline.py'})),
            ('explore', 'Explore the connections concept and its defaults',     7_600,    260, ('Grep', {'pattern': 'connections'})),
        ],
        five_hour_pct = 34.0,
        seven_day_pct = 22.0,
        columns     = WIDE_COLS,
    ),
    ScenarioConfig(
        name        = 'subagent-tree-medium-types',
        context_pct = 0.40,
        subagents   = [
            ('ui',      'Add a light/dark toggle to the report template',      18_400,  1_050, ('Edit', {'file_path': 'render/template.py', 'old_string': 'a', 'new_string': 'b'})),
            ('ops',     'Fix the backend build, lint, and test pipeline',       9_200,    480, ('Bash', {'command': 'make lint test'})),
            ('fractal', 'Add supersampling to the offline render pass',        26_700,  1_820, ('Edit', {'file_path': 'render/pipeline.py', 'old_string': 'a', 'new_string': 'b'})),
            ('api',     'Wire the v3 resolver into FramePipeline',             33_100,  1_400, ('Read', {'file_path': 'render/pipeline.py'})),
            ('explore', 'Explore the connections concept and its defaults',     7_600,    260, ('Grep', {'pattern': 'connections'})),
        ],
        five_hour_pct = 34.0,
        seven_day_pct = 22.0,
        columns     = MEDIUM_COLS,
    ),
    ScenarioConfig(
        name        = 'subagent-tree-narrow-types',
        context_pct = 0.40,
        subagents   = [
            ('ui',      'Add a light/dark toggle to the report template',      18_400,  1_050, ('Edit', {'file_path': 'render/template.py', 'old_string': 'a', 'new_string': 'b'})),
            ('ops',     'Fix the backend build, lint, and test pipeline',       9_200,    480, ('Bash', {'command': 'make lint test'})),
            ('fractal', 'Add supersampling to the offline render pass',        26_700,  1_820, ('Edit', {'file_path': 'render/pipeline.py', 'old_string': 'a', 'new_string': 'b'})),
            ('api',     'Wire the v3 resolver into FramePipeline',             33_100,  1_400, ('Read', {'file_path': 'render/pipeline.py'})),
            ('explore', 'Explore the connections concept and its defaults',     7_600,    260, ('Grep', {'pattern': 'connections'})),
        ],
        five_hour_pct = 34.0,
        seven_day_pct = 22.0,
        columns     = NARROW_COLS,
    ),

    # Config 3 — 2 parent subagents, 2 children each. Within each pair, one
    # child carries both lines-read and lines-changed (read+write), its
    # sibling carries lines-read only (lines=(read, 0) omits the Edit block
    # entirely per write_subagents, so the row renders read-only).
    ScenarioConfig(
        name        = 'subagent-tree-wide-nested',
        context_pct = 0.44,
        subagents   = [
            ('spec-implementer', 'Implement the backend-precomputed-spectrum change', 41_000_000, 12_600, ('Bash', {'command': 'openspec show backend-precomputed-spectrum --json'}), None, None, None, (410, 60)),
            ('general-purpose',  'Port the catalogue sweep render to the browser',      6_800_000,  9_400, ('Write', {'file_path': 'report-sweep-render.md'}), None, 1, None, (410, 95)),
            ('general-purpose',  'Explore the snare/notation/PSV detection code',       2_100_000,  1_800, ('Read', {'file_path': 'render/notation.py'}), None, 1, None, (220, 0)),
            ('spec-implementer', 'Implement the grid-to-drop realignment change',      37_500_000, 11_900, ('Bash', {'command': 'openspec show grid-to-drop-realignment --json'}), None, None, None, (380, 55)),
            ('ui',               'Wire NotationView into main.ts',                     5_200_000,  6_100, ('Write', {'file_path': 'render/main.ts'}), None, 4, None, (180, 60)),
            ('api',              'Find the fingerprinting design notes',                900_000,    420, ('Grep', {'pattern': 'fingerprint'}), None, 4, None, (75, 0)),
        ],
        five_hour_pct = 38.0,
        seven_day_pct = 24.0,
        columns     = WIDE_COLS,
    ),
    ScenarioConfig(
        name        = 'subagent-tree-medium-nested',
        context_pct = 0.44,
        subagents   = [
            ('spec-implementer', 'Implement the backend-precomputed-spectrum change', 41_000_000, 12_600, ('Bash', {'command': 'openspec show backend-precomputed-spectrum --json'}), None, None, None, (410, 60)),
            ('general-purpose',  'Port the catalogue sweep render to the browser',      6_800_000,  9_400, ('Write', {'file_path': 'report-sweep-render.md'}), None, 1, None, (410, 95)),
            ('general-purpose',  'Explore the snare/notation/PSV detection code',       2_100_000,  1_800, ('Read', {'file_path': 'render/notation.py'}), None, 1, None, (220, 0)),
            ('spec-implementer', 'Implement the grid-to-drop realignment change',      37_500_000, 11_900, ('Bash', {'command': 'openspec show grid-to-drop-realignment --json'}), None, None, None, (380, 55)),
            ('ui',               'Wire NotationView into main.ts',                     5_200_000,  6_100, ('Write', {'file_path': 'render/main.ts'}), None, 4, None, (180, 60)),
            ('api',              'Find the fingerprinting design notes',                900_000,    420, ('Grep', {'pattern': 'fingerprint'}), None, 4, None, (75, 0)),
        ],
        five_hour_pct = 38.0,
        seven_day_pct = 24.0,
        columns     = MEDIUM_COLS,
    ),
    ScenarioConfig(
        name        = 'subagent-tree-narrow-nested',
        context_pct = 0.44,
        subagents   = [
            ('spec-implementer', 'Implement the backend-precomputed-spectrum change', 41_000_000, 12_600, ('Bash', {'command': 'openspec show backend-precomputed-spectrum --json'}), None, None, None, (410, 60)),
            ('general-purpose',  'Port the catalogue sweep render to the browser',      6_800_000,  9_400, ('Write', {'file_path': 'report-sweep-render.md'}), None, 1, None, (410, 95)),
            ('general-purpose',  'Explore the snare/notation/PSV detection code',       2_100_000,  1_800, ('Read', {'file_path': 'render/notation.py'}), None, 1, None, (220, 0)),
            ('spec-implementer', 'Implement the grid-to-drop realignment change',      37_500_000, 11_900, ('Bash', {'command': 'openspec show grid-to-drop-realignment --json'}), None, None, None, (380, 55)),
            ('ui',               'Wire NotationView into main.ts',                     5_200_000,  6_100, ('Write', {'file_path': 'render/main.ts'}), None, 4, None, (180, 60)),
            ('api',              'Find the fingerprinting design notes',                900_000,    420, ('Grep', {'pattern': 'fingerprint'}), None, 4, None, (75, 0)),
        ],
        five_hour_pct = 38.0,
        seven_day_pct = 24.0,
        columns     = NARROW_COLS,
    ),

    # Config 3b — a genuine 3-level tree: one root spawning three children,
    # the middle child (not the last sibling) itself spawns a grandchild.
    # This is the only scenario that exercises spawnDepth==2, which is what
    # makes the tree view's `│` ancestor-continuation column and the
    # 2-column-per-level staircase indentation actually show up on screen —
    # every other subagent-tree-* scenario only nests one hop deep.
    ScenarioConfig(
        name        = 'subagent-tree-wide-deep',
        context_pct = 0.42,
        subagents   = [
            ('spec-implementer', 'Implement the ancestor-continuation column for the ops/demo.py tree view', 48_000_000, 13_400, ('Bash', {'command': 'openspec show tree-ancestor-column --json'}), None, None, None, (410, 60)),
            ('explore',          'Survey every subagent-tree-* scenario for existing nesting depth',           1_400_000,    980, ('Grep', {'pattern': 'parent_idx'}), None, 1, None, (140, 0)),
            ('general-purpose',  'Port the staircase indentation math into the grandchild row renderer',       7_600_000,  5_200, ('Edit', {'file_path': 'render/tree.py', 'old_string': 'a', 'new_string': 'b'}), None, 1, None, (260, 70)),
            ('ui',               'Wire the deep-tree scenario into demo/img output',                           3_100_000,  2_050, ('Write', {'file_path': 'ops/demo.py'}), None, 1, None, (95, 40)),
            ('general-purpose',  'Add pytest coverage for spawnDepth==2 rows',                                  2_900_000,  1_650, ('Edit', {'file_path': 'test/test_subagent_rows.py', 'old_string': 'a', 'new_string': 'b'}), None, 3, None, (110, 35)),
        ],
        five_hour_pct = 39.0,
        seven_day_pct = 25.0,
        columns     = WIDE_COLS,
    ),
    ScenarioConfig(
        name        = 'subagent-tree-medium-deep',
        context_pct = 0.42,
        subagents   = [
            ('spec-implementer', 'Implement the ancestor-continuation column for the ops/demo.py tree view', 48_000_000, 13_400, ('Bash', {'command': 'openspec show tree-ancestor-column --json'}), None, None, None, (410, 60)),
            ('explore',          'Survey every subagent-tree-* scenario for existing nesting depth',           1_400_000,    980, ('Grep', {'pattern': 'parent_idx'}), None, 1, None, (140, 0)),
            ('general-purpose',  'Port the staircase indentation math into the grandchild row renderer',       7_600_000,  5_200, ('Edit', {'file_path': 'render/tree.py', 'old_string': 'a', 'new_string': 'b'}), None, 1, None, (260, 70)),
            ('ui',               'Wire the deep-tree scenario into demo/img output',                           3_100_000,  2_050, ('Write', {'file_path': 'ops/demo.py'}), None, 1, None, (95, 40)),
            ('general-purpose',  'Add pytest coverage for spawnDepth==2 rows',                                  2_900_000,  1_650, ('Edit', {'file_path': 'test/test_subagent_rows.py', 'old_string': 'a', 'new_string': 'b'}), None, 3, None, (110, 35)),
        ],
        five_hour_pct = 39.0,
        seven_day_pct = 25.0,
        columns     = MEDIUM_COLS,
    ),
    ScenarioConfig(
        name        = 'subagent-tree-narrow-deep',
        context_pct = 0.42,
        subagents   = [
            ('spec-implementer', 'Implement the ancestor-continuation column for the ops/demo.py tree view', 48_000_000, 13_400, ('Bash', {'command': 'openspec show tree-ancestor-column --json'}), None, None, None, (410, 60)),
            ('explore',          'Survey every subagent-tree-* scenario for existing nesting depth',           1_400_000,    980, ('Grep', {'pattern': 'parent_idx'}), None, 1, None, (140, 0)),
            ('general-purpose',  'Port the staircase indentation math into the grandchild row renderer',       7_600_000,  5_200, ('Edit', {'file_path': 'render/tree.py', 'old_string': 'a', 'new_string': 'b'}), None, 1, None, (260, 70)),
            ('ui',               'Wire the deep-tree scenario into demo/img output',                           3_100_000,  2_050, ('Write', {'file_path': 'ops/demo.py'}), None, 1, None, (95, 40)),
            ('general-purpose',  'Add pytest coverage for spawnDepth==2 rows',                                  2_900_000,  1_650, ('Edit', {'file_path': 'test/test_subagent_rows.py', 'old_string': 'a', 'new_string': 'b'}), None, 3, None, (110, 35)),
        ],
        five_hour_pct = 39.0,
        seven_day_pct = 25.0,
        columns     = NARROW_COLS,
    ),

    # Config 4 — 4 subagents, one per lifecycle state (completed / killed /
    # stopped / resumed — a distinct 4-of-5 slice of the supported state set,
    # not repeating any state and not the old 5-agent-plus-root layout).
    ScenarioConfig(
        name        = 'subagent-tree-wide-states',
        context_pct = 0.36,
        subagents   = [
            ('general-purpose',
             'Implement the backend-precomputed-spectrum change: schema bump + codegen wave',
             58_000, 3_100,
             ('text', 'Writing the final verification report before handing back to the parent thread'),
             None, None, [('completed', 45)], (920, 310)),
            ('general-purpose', 'Killed mid-way through a runaway grep across the render/ tree', 14_700,    640, None, None, None, [('killed', 55)], (48, 4)),
            ('general-purpose', 'Stopped after the parent task already wrapped up the remaining work', 9_800, 410, None, None, None, [('stopped', 25)], (30, 0)),
            ('general-purpose', 'Re-opened to patch a follow-up review note in the border math', 26_500,  1_850, ('Edit', {'file_path': 'render/borders.py', 'old_string': 'a', 'new_string': 'b'}), None, None, [('', 5)], (95, 30)),
        ],
        five_hour_pct = 27.0,
        seven_day_pct = 17.0,
        columns     = WIDE_COLS,
    ),
    ScenarioConfig(
        name        = 'subagent-tree-medium-states',
        context_pct = 0.36,
        subagents   = [
            ('general-purpose',
             'Implement the backend-precomputed-spectrum change: schema bump + codegen wave',
             58_000, 3_100,
             ('text', 'Writing the final verification report before handing back to the parent thread'),
             None, None, [('completed', 45)], (920, 310)),
            ('general-purpose', 'Killed mid-way through a runaway grep across the render/ tree', 14_700,    640, None, None, None, [('killed', 55)], (48, 4)),
            ('general-purpose', 'Stopped after the parent task already wrapped up the remaining work', 9_800, 410, None, None, None, [('stopped', 25)], (30, 0)),
            ('general-purpose', 'Re-opened to patch a follow-up review note in the border math', 26_500,  1_850, ('Edit', {'file_path': 'render/borders.py', 'old_string': 'a', 'new_string': 'b'}), None, None, [('', 5)], (95, 30)),
        ],
        five_hour_pct = 27.0,
        seven_day_pct = 17.0,
        columns     = MEDIUM_COLS,
    ),
    ScenarioConfig(
        name        = 'subagent-tree-narrow-states',
        context_pct = 0.36,
        subagents   = [
            ('general-purpose',
             'Implement the backend-precomputed-spectrum change: schema bump + codegen wave',
             58_000, 3_100,
             ('text', 'Writing the final verification report before handing back to the parent thread'),
             None, None, [('completed', 45)], (920, 310)),
            ('general-purpose', 'Killed mid-way through a runaway grep across the render/ tree', 14_700,    640, None, None, None, [('killed', 55)], (48, 4)),
            ('general-purpose', 'Stopped after the parent task already wrapped up the remaining work', 9_800, 410, None, None, None, [('stopped', 25)], (30, 0)),
            ('general-purpose', 'Re-opened to patch a follow-up review note in the border math', 26_500,  1_850, ('Edit', {'file_path': 'render/borders.py', 'old_string': 'a', 'new_string': 'b'}), None, None, [('', 5)], (95, 30)),
        ],
        five_hour_pct = 27.0,
        seven_day_pct = 17.0,
        columns     = NARROW_COLS,
    ),

    # Config 5 — plan + tree together, shown midway through a spec-implementer
    # run: some tasks done, some not, and a mix of completed/still-running
    # subagents (not all done, not all running).
    ScenarioConfig(
        name        = 'subagent-tree-wide-plan',
        context_pct = 0.41,
        tasks       = [
            ('Schema bump + codegen wave',        'Bumping schema + running codegen',       'completed'),
            ('Port sweep render to browser',      'Porting sweep render to the browser',    'completed'),
            ('Wire NotationView into main.ts',    'Wiring NotationView into main.ts',       'in_progress'),
            ('Explore build-up zoom/moves system', 'Exploring build-up zoom/moves system',  'pending'),
            ('Find download popup UI code',       'Finding download popup UI code',         'pending'),
        ],
        subagents   = [
            ('spec-implementer', 'Implement the backend-precomputed-spectrum change', 41_000_000, 12_600, ('Bash', {'command': 'openspec show backend-precomputed-spectrum --json'}), None, None, None, (410, 60)),
            ('general-purpose',  'Port the catalogue sweep render to the browser',      6_800_000,  9_400, ('Write', {'file_path': 'report-sweep-render.md'}), None, 1, [('completed', 90)], (410, 120)),
            ('general-purpose',  'Explore the build-up zoom and moves system',          2_600_000,  2_100, ('Grep', {'pattern': 'buildUp'}), None, 1, None, (120, 0)),
            ('ui',               'Wire NotationView into main.ts',                     5_200_000,  6_100, ('Write', {'file_path': 'render/main.ts'}), None, 1, [('completed', 45)], (180, 60)),
            ('api',              'Find the download popup UI code',                     900_000,    380, ('Grep', {'pattern': 'downloadPopup'}), None, 1, None, (40, 0)),
        ],
        five_hour_pct = 36.0,
        seven_day_pct = 23.0,
        yas_toml    = '[layout]\nmax_width = 300\n',
        columns     = WIDE_COLS,
    ),
    ScenarioConfig(
        name        = 'subagent-tree-medium-plan',
        context_pct = 0.41,
        tasks       = [
            ('Schema bump + codegen wave',        'Bumping schema + running codegen',       'completed'),
            ('Port sweep render to browser',      'Porting sweep render to the browser',    'completed'),
            ('Wire NotationView into main.ts',    'Wiring NotationView into main.ts',       'in_progress'),
            ('Explore build-up zoom/moves system', 'Exploring build-up zoom/moves system',  'pending'),
            ('Find download popup UI code',       'Finding download popup UI code',         'pending'),
        ],
        subagents   = [
            ('spec-implementer', 'Implement the backend-precomputed-spectrum change', 41_000_000, 12_600, ('Bash', {'command': 'openspec show backend-precomputed-spectrum --json'}), None, None, None, (410, 60)),
            ('general-purpose',  'Port the catalogue sweep render to the browser',      6_800_000,  9_400, ('Write', {'file_path': 'report-sweep-render.md'}), None, 1, [('completed', 90)], (410, 120)),
            ('general-purpose',  'Explore the build-up zoom and moves system',          2_600_000,  2_100, ('Grep', {'pattern': 'buildUp'}), None, 1, None, (120, 0)),
            ('ui',               'Wire NotationView into main.ts',                     5_200_000,  6_100, ('Write', {'file_path': 'render/main.ts'}), None, 1, [('completed', 45)], (180, 60)),
            ('api',              'Find the download popup UI code',                     900_000,    380, ('Grep', {'pattern': 'downloadPopup'}), None, 1, None, (40, 0)),
        ],
        five_hour_pct = 36.0,
        seven_day_pct = 23.0,
        columns     = MEDIUM_COLS,
    ),
    ScenarioConfig(
        name        = 'subagent-tree-narrow-plan',
        context_pct = 0.41,
        tasks       = [
            ('Schema bump + codegen wave',        'Bumping schema + running codegen',       'completed'),
            ('Port sweep render to browser',      'Porting sweep render to the browser',    'completed'),
            ('Wire NotationView into main.ts',    'Wiring NotationView into main.ts',       'in_progress'),
            ('Explore build-up zoom/moves system', 'Exploring build-up zoom/moves system',  'pending'),
            ('Find download popup UI code',       'Finding download popup UI code',         'pending'),
        ],
        subagents   = [
            ('spec-implementer', 'Implement the backend-precomputed-spectrum change', 41_000_000, 12_600, ('Bash', {'command': 'openspec show backend-precomputed-spectrum --json'}), None, None, None, (410, 60)),
            ('general-purpose',  'Port the catalogue sweep render to the browser',      6_800_000,  9_400, ('Write', {'file_path': 'report-sweep-render.md'}), None, 1, [('completed', 90)], (410, 120)),
            ('general-purpose',  'Explore the build-up zoom and moves system',          2_600_000,  2_100, ('Grep', {'pattern': 'buildUp'}), None, 1, None, (120, 0)),
            ('ui',               'Wire NotationView into main.ts',                     5_200_000,  6_100, ('Write', {'file_path': 'render/main.ts'}), None, 1, [('completed', 45)], (180, 60)),
            ('api',              'Find the download popup UI code',                     900_000,    380, ('Grep', {'pattern': 'downloadPopup'}), None, 1, None, (40, 0)),
        ],
        five_hour_pct = 36.0,
        seven_day_pct = 23.0,
        columns     = NARROW_COLS,
    ),
    ScenarioConfig(
        name        = 'cohort-two-column',
        context_pct = 0.40,
        subagents   = [
            ('explore',         'Map the token-tracking call sites',        2_100,   180, ('Bash', {'command': 'grep -rn "billed_in" claude/'})),
            ('general-purpose', 'Refactor the sparkline bucket algorithm',  5_600,   720, ('Edit', {'file_path': 'claude/statusline_command.py', 'old_string': 'x', 'new_string': 'y'})),
            ('claude',          'Draft the border-math cleanup',            3_800,   540, ('Read', {'file_path': 'claude/statusline_command.py'})),
            ('reviewer',        'Audit the gradient elbow math',            4_400,   610, ('Read', {'file_path': 'claude/yas/renderer.py'})),
            # Text-only latest message -> replying snippet alongside the cohort.
            ('narrator',        'Narrate the layout refactor plan',         2_400,   320, ('text', 'Walking the border helpers before touching elbows')),
            ('tester',          'Run the layout regression suite',          6_100, 1_180, ('Bash', {'command': 'uv run pytest -q test/test_layout_seam.py'})),
        ],
        five_hour_pct = 30.0,
        seven_day_pct = 20.0,
    ),
    ScenarioConfig(
        # No rate_limits payload at all — Claude Code setups that don't
        # supply either window; both buckets must be omitted, not zeroed.
        name          = 'rate-limits-absent',
        context_pct   = 0.30,
        five_hour_pct = None,
        seven_day_pct = None,
    ),
    ScenarioConfig(
        # Present-but-idle 7d bucket (0% used) alongside a normal 5h bucket —
        # must render `∞`, not be dropped like the absent case above.
        name          = 'rate-limits-idle-7d',
        context_pct   = 0.30,
        five_hour_pct = 30.0,
        seven_day_pct = 0.0,
    ),
    ScenarioConfig(
        # PR #125 headline feature: no stdin `rate_limits` payload at all
        # (both buckets omitted, like `rate-limits-absent` above), but a
        # `[rate_limits]` config table is set — YAS must synthesize real
        # nonzero 5h/7d usage from local token history instead of falling
        # back to the unlimited/omitted defaults.
        name          = 'rate-limits-config-synthesized',
        context_pct   = 0.30,
        five_hour_pct = None,
        seven_day_pct = None,
        seed_rate_limit_log = True,
        yas_toml      = '''
[rate_limits]
five_hour = { budget = 90_000, window = "5h", anchor = "rolling" }
seven_day = { budget = 130_000, window = "7d", anchor = "fixed", epoch = "0 0 * * 0" }
''',
    ),
    *(
        ScenarioConfig(
            # Shell-commands badge on the right of the first subagent row.
            name           = f'shell-commands-badge{suffix}',
            subagents      = _SHELL_SUBAGENTS,
            shell_commands = _SHELL_COMMANDS,
            columns        = cols,
            yas_toml       = layout_toml + _SHELL_BADGE_TOML,
        )
        for suffix, cols, layout_toml in _SHELL_WIDTHS
    ),
    *(
        ScenarioConfig(
            # Shell-commands list below the rows, capped so `+1 more` shows.
            name           = f'shell-commands-list{suffix}',
            shell_commands = _SHELL_COMMANDS,
            columns        = cols,
            yas_toml       = layout_toml + _SHELL_LIST_TOML,
        )
        for suffix, cols, layout_toml in _SHELL_WIDTHS
    ),
    ScenarioConfig(
        # Subagents present, list below: the list block is closed by a divider like the no-subagent list.
        name           = 'shell-commands-list-subagents-200',
        subagents      = _SHELL_SUBAGENTS,
        shell_commands = _SHELL_COMMANDS,
        columns        = 200,
        yas_toml       = _SHELL_WIDTHS[2][2] + _SHELL_LIST_TOML,
    ),
    *(
        ScenarioConfig(
            # Shell-commands list as a side section right of the subagents; -80 falls back to below.
            name           = f'shell-commands-side{suffix}',
            subagents      = _SHELL_SUBAGENTS,
            shell_commands = _SHELL_COMMANDS,
            columns        = cols,
            yas_toml       = layout_toml + _SHELL_SIDE_TOML,
        )
        for suffix, cols, layout_toml in _SHELL_WIDTHS
    ),
    *(
        ScenarioConfig(
            # A running Bash command owned by a subagent shows on that subagent's row (cpu / mem / time);
            # the main-thread command stays in the shell commands section.
            name           = f'subagent-resource-usage{suffix}',
            subagents      = _USAGE_SUBAGENTS,
            shell_commands = _USAGE_COMMANDS,
            columns        = cols,
            yas_toml       = layout_toml + _SHELL_SIDE_TOML,
        )
        for suffix, cols, layout_toml in (_SHELL_WIDTHS[0], _SHELL_WIDTHS[2])
    ),
    ScenarioConfig(
        # Wide terminal: the command grows into the free space and the subagent side keeps its natural width.
        name           = 'shell-commands-side-300',
        subagents      = _SHELL_LONG_SUBAGENTS,
        shell_commands = _SHELL_LONG_COMMANDS,
        columns        = 300,
        yas_toml       = '[layout]\nfull_width = true\nlabels = true\n' + _SHELL_SIDE_TOML,
    ),
]


def write_openspec_changes(project_dir: Path, changes: list[tuple[str, int, int]]) -> None:
    """Replace openspec/changes/ with the given specs. changes = [(name, done, total)]."""
    changes_dir = project_dir / 'openspec' / 'changes'
    if changes_dir.exists():
        shutil.rmtree(changes_dir)
    changes_dir.mkdir(parents=True, exist_ok=True)
    for name, done, total in changes:
        spec_dir = changes_dir / name
        spec_dir.mkdir(parents=True)
        tasks_md = (
            ''.join(f'- [x] task {n}\n' for n in range(1, done + 1))
            + ''.join(f'- [ ] task {n}\n' for n in range(done + 1, total + 1))
        )
        (spec_dir / 'tasks.md').write_text(tasks_md)


def write_rate_log_with_peaks(
    rate_log: Path,
    session_id: str,
    combined_total: int,
    peak_steps: tuple[int, int] = (7, 19),
    n_steps: int = 25,
    span_secs: float = 120.0,
) -> None:
    """Write a synthetic rate log with two peaks so the sparkline has visible shape.

    All deltas are scaled so the cumulative total matches combined_total — this
    prevents the real final entry from dwarfing the peaks and flattening the graph.
    """
    now = time.time()
    p1, p2 = peak_steps
    raw_deltas = [
        80_000 if s == p1 else
        60_000 if s == p2 else
        800
        for s in range(n_steps)
    ]
    scale  = combined_total / sum(raw_deltas)
    cumul  = 0
    step_s = span_secs / (n_steps - 1)
    lines  = []
    for step, raw in enumerate(raw_deltas):
        cumul += int(raw * scale)
        ts = now - span_secs + step * step_s
        lines.append(f'{ts:.3f} {session_id} {cumul} 0')
    rate_log.write_text('\n'.join(lines) + '\n')


def write_rate_limit_log_seed(
    rate_limit_log: Path,
    session_id:     str,
    seed_samples:   tuple[tuple[float, int], ...],
) -> None:
    """Pre-populate `rate-limit.log` with baseline `(secs_ago, cumulative_tokens)`
    samples so `RateLimitLog.usage_since` has an earlier baseline to diff the
    live tick's cumulative total against.

    Without this, `[rate_limits]`-config-driven synthesis (rate_limits_sim.py)
    sees only the single sample recorded by this tick and computes 0% used —
    correct behaviour, but useless for demonstrating the feature. Row format
    matches `RateLimitLog.record`: `ts session_id cumulative_tokens`.
    """
    now   = time.time()
    lines = [f'{now - secs_ago:.3f} {session_id} {cumulative}' for secs_ago, cumulative in seed_samples]
    rate_limit_log.parent.mkdir(parents=True, exist_ok=True)
    rate_limit_log.write_text('\n'.join(lines) + '\n')


def render_scenario(
    env:        dict[str, str],
    fixture:    dict[str, object],
    tmpdir:     Path,
    session_id: str,
    cfg:        ScenarioConfig,
    out_dir:    Path,
    theme:      str | None = None,
) -> None:
    claude       = tmpdir / '.claude'
    project      = tmpdir / 'my-project'
    transcript_p = claude / 'projects' / session_id / f'{session_id}.jsonl'
    rate_log     = claude / 'yas' / 'state' / 'runtime' / 'token-rate.log'
    rate_limit_log_p = claude / 'yas' / 'state' / 'runtime' / 'rate-limit.log'
    rate_log.parent.mkdir(parents=True, exist_ok=True)
    _seed_yas_version(claude)

    ctx_size  = 200_000
    total_in  = int(ctx_size * cfg.context_pct * 0.88)
    total_cc  = int(total_in * 0.18)
    total_cr  = int(total_in * 12.0)
    total_out = int(ctx_size * cfg.context_pct * 0.12)

    write_transcript(
        transcript_p, cfg.skills, total_in, total_cc, total_cr, total_out,
        tasks=cfg.tasks or None,
        cache_anchor_secs_ago=cfg.cache_anchor_secs_ago,
        cache_1h_tier=cfg.cache_1h_tier,
        bash_calls=[(c[0], c[4]) for c in cfg.shell_commands if c[0] not in _subagent_bash_commands(cfg.subagents)] or None,
    )
    write_settings(claude, cfg.plugins)
    yas_toml_path = claude / 'yas.toml'
    if cfg.yas_toml is not None:
        yas_toml_path.write_text(cfg.yas_toml)
    elif yas_toml_path.exists():
        yas_toml_path.unlink()
    write_subagents(claude, session_id, project, cfg.subagents, age_seconds=90, mtime_age=cfg.subagent_mtime_age)
    write_workflows(claude, session_id, project, cfg.workflows, age_seconds=90)
    write_openspec_changes(project, cfg.openspec)
    write_rate_log_with_peaks(rate_log, session_id, total_in + total_cc + total_out)
    if cfg.seed_rate_limit_log:
        # Live cumulative for this tick, matching yas.app._apply_rate_limit_sim's
        # own computation (total_input_tokens + total_output_tokens) — the
        # baselines below are diffed against this same value at render time.
        live_cumulative = total_in + total_out
        write_rate_limit_log_seed(
            rate_limit_log_p, session_id,
            seed_samples = (
                (4 * 3600.0,       int(live_cumulative * 0.20)),   # 4h ago: inside the 5h window
                (6 * 86400.0,      int(live_cumulative * 0.05)),   # 6d ago: inside the 7d window, older than the 5h sample
            ),
        )

    raw: dict[str, object] = dict(fixture)
    raw['model']          = {'id': cfg.model_id, 'display_name': cfg.model_name}
    raw['effort']         = {'level': cfg.effort} if cfg.effort else {}
    raw['thinking']       = {'enabled': cfg.thinking}
    raw['cwd']            = str(project)
    workspace = _ensure_nested(raw, 'workspace')
    workspace['project_dir'] = str(project)
    raw['transcript_path'] = str(transcript_p)
    ctx_win = _ensure_nested(raw, 'context_window')
    ctx_win['total_input_tokens']  = total_in
    ctx_win['total_output_tokens'] = total_out
    ctx_win['used_percentage']     = round(cfg.context_pct * 100.0, 1)
    resets    = int(time.time()) + 7200
    rate_lims = _ensure_nested(raw, 'rate_limits')
    # A pct of None means "this Claude Code setup didn't supply this window at
    # all" — drop the key outright rather than defaulting it to a nonzero
    # value. `rate_lims` is a shared mutable dict pulled off the base fixture
    # (raw = dict(fixture) is only a shallow copy), so a bucket left over from
    # an earlier scenario must be explicitly popped, not just left unset.
    if cfg.five_hour_pct is None:
        rate_lims.pop('five_hour', None)
    else:
        five_hour = _ensure_nested(rate_lims, 'five_hour')
        # A genuinely idle window (0%) hasn't been touched yet, so the API
        # wouldn't hand back a resets_at either — omit it so the ∞ path
        # (idle + no resets_at) is exercised the same way as a real payload.
        five_hour['resets_at']       = resets if cfg.five_hour_pct else 0
        five_hour['used_percentage'] = cfg.five_hour_pct
    if cfg.seven_day_pct is None:
        rate_lims.pop('seven_day', None)
    else:
        seven_day = _ensure_nested(rate_lims, 'seven_day')
        seven_day['resets_at']       = resets if cfg.seven_day_pct else 0
        seven_day['used_percentage'] = cfg.seven_day_pct

    # Every YAS_* config knob already flows through `env` (a copy of os.environ)
    # to the statusline subprocess, so e.g. `YAS_SOFT_LIMIT=5000000 make demo/img`
    # just works. COLUMNS and the token window are the only values the demo pins,
    # and only as defaults: setdefault lets a user-provided value win so the demo
    # responds to those too (e.g. `COLUMNS=90 make demo/img` for the medium layout).
    snap_env = dict(env)
    # terminal_width() checks TMUX_PANE before COLUMNS (renderer.py's live-tmux
    # fast path), which would silently override the pinned/per-scenario width
    # whenever `make demo/img` itself runs inside tmux. Snapshots must be
    # deterministic regardless of the host terminal, so drop it here.
    snap_env.pop('TMUX_PANE', None)
    if cfg.columns is not None:
        # An explicit per-scenario width always wins over the ambient/inherited
        # COLUMNS (e.g. the real terminal width demo.py runs under) — that's
        # the whole point of the field (wide/medium/narrow tree-mode triples).
        snap_env['COLUMNS'] = str(cfg.columns)
    else:
        snap_env.setdefault('COLUMNS', str(SNAPSHOT_COLS))
    snap_env.setdefault('STATUSLINE_TOKEN_WINDOW', str(SNAP_WINDOW))
    if theme is not None:
        snap_env['YAS_THEME'] = theme
    if cfg.shell_commands:
        fixture_p = tmpdir / 'shell-commands-fixture.json'
        fixture_p.write_text(json.dumps(build_shell_fixture(cfg.shell_commands)))
        snap_env['YAS_SHELL_COMMANDS_FIXTURE'] = str(fixture_p)
    else:
        snap_env.pop('YAS_SHELL_COMMANDS_FIXTURE', None)
    out = render_once(snap_env, json.dumps(raw))
    stem = theme if theme is not None else cfg.name
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f'{stem}.txt'
    dest.write_text('\n\n'+out+'\n\n')
    # print(f'  wrote {dest}')


def scenario_out_dir(base_dir: Path, cfg: ScenarioConfig) -> Path:
    """Route subagent-tree scenarios into a `subagents/` subdir of `base_dir`.

    The 15 `subagent-tree-*` scenarios (wide/medium/narrow x single/types/
    nested/states/plan) would otherwise clutter the flat demo/ dir alongside
    every other scenario's .txt/.png; keep them grouped instead.
    """
    if cfg.name.startswith('subagent-tree-'):
        return base_dir / 'subagents'
    return base_dir


def _render_isolated(fixture: dict[str, object], cfg: ScenarioConfig, out_dir: Path, theme: str | None = None) -> None:
    """Render one scenario into its own throwaway $HOME so renders can run concurrently.

    Each task gets a fresh synthetic env (git repo, transcript, settings, ...),
    which is ~8ms to build, so the per-render subprocess (~68ms) stays the
    dominant cost and the tasks are fully independent on disk.
    """
    session_id = fixture['session_id']
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmpdir = Path(raw_tmp)
        build_synthetic_env(tmpdir, session_id)
        env = os.environ.copy()
        env['HOME'] = str(tmpdir)
        env['CLAUDE_CONFIG_DIR'] = str(tmpdir / '.claude')
        render_scenario(env, fixture, tmpdir, session_id, cfg, out_dir, theme=theme)


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshots', metavar='DIR', help='render scenario images into DIR instead of animating')
    args = parser.parse_args()

    fixture = json.loads(FIXTURE_PATH.read_text())
    session_id = fixture['session_id']

    if args.snapshots:
        out_dir = Path(args.snapshots)
        out_dir.mkdir(parents=True, exist_ok=True)

        # DEMO_ONLY=<scenario-name> renders just that one scenario's .txt and
        # skips the per-theme kitchen-sink renders, for a fast single-snapshot loop.
        only = os.environ.get('DEMO_ONLY')
        if only:
            scenarios = [c for c in SCENARIOS if c.name == only]
            if not scenarios:
                names = ', '.join(c.name for c in SCENARIOS)
                print(f'DEMO_ONLY={only!r}: no such scenario. Available: {names}', file=sys.stderr)
                return 1
            tasks: list[tuple[ScenarioConfig, Path, str | None]] = [
                (cfg, scenario_out_dir(out_dir, cfg), None) for cfg in scenarios
            ]
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=min(len(tasks), (os.cpu_count() or 4))) as pool:
                futures = [pool.submit(_render_isolated, fixture, cfg, dest, theme) for cfg, dest, theme in tasks]
                for fut in futures:
                    fut.result()
            return 0

        sys.path.insert(0, str(REPO_ROOT / 'claude'))
        from yas.themes import THEMES
        light_dir = out_dir / 'themes' / 'light'
        dark_dir  = out_dir / 'themes' / 'dark'
        light_dir.mkdir(parents=True, exist_ok=True)
        dark_dir.mkdir(parents=True, exist_ok=True)
        kitchen_sink = next(c for c in SCENARIOS if c.name == 'kitchen-sink')
        light_themes = {n for n in THEMES if THEMES[n].pill_fg_dark[0] <= 10}

        # (cfg, out_dir, theme) tasks: each is independent (own $HOME), so the
        # ~68ms-per-render subprocesses run concurrently instead of serially.
        tasks = [(cfg, scenario_out_dir(out_dir, cfg), None) for cfg in SCENARIOS]
        for theme_name in sorted(THEMES):
            theme_dir = light_dir if theme_name in light_themes else dark_dir
            tasks.append((kitchen_sink, theme_dir, theme_name))

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(len(tasks), (os.cpu_count() or 4))) as pool:
            futures = [pool.submit(_render_isolated, fixture, cfg, dest, theme) for cfg, dest, theme in tasks]
            for fut in futures:
                fut.result()

    else:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmpdir = Path(raw_tmp)
            build_synthetic_env(tmpdir, session_id)
            env = os.environ.copy()
            env['HOME'] = str(tmpdir)
            env['CLAUDE_CONFIG_DIR'] = str(tmpdir / '.claude')
            payload = mutate_session_info(tmpdir, session_id, fixture)
            raw = json.loads(payload)
            env['STATUSLINE_TOKEN_WINDOW'] = str(DEMO_TOKEN_WINDOW)
            env['YAS_FULL_WIDTH'] = '1'
            os.system('clear -x')
            animate(env, raw, tmpdir, session_id)
    return 0


if __name__ == '__main__':
    sys.exit(main())
