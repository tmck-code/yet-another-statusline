"""Synthetic environment and transcript writers for session replay.

Extracts the world-building primitives from demo.py: environment builder,
transcript and subagent cohort writers, plus helper utilities. Shared between
demo scenarios and replay ingestion so both emit byte-identical session fixtures.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
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


def _iso(epoch: float) -> str:
    'Format an epoch as a local ISO-8601 string (matches the parser''s expectations).'
    return datetime.fromtimestamp(epoch).astimezone().isoformat()


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


def _task_timeline(
    tasks: list[tuple[str, str, str]],
    base_time: float,
    task_durations: tuple[float, ...],
    task_live_seconds: float,
) -> dict[int, tuple[float | None, float | None]]:
    """Lay a contiguous timeline ending at `base_time` ("now").

    Returns {task_index: (started_at, completed_at)}. The in_progress task (if
    any) starts task_live_seconds before now; completed tasks are placed
    sequentially before it using their task_durations so the last completed
    task's completed_at meets the in_progress start (or now). Pending tasks get
    (None, None). Total Elapsed = sum(completed durations) + live.
    """
    has_active = any(status == 'in_progress' for _, _, status in tasks)
    # Where the chain of completed tasks ends: at the in_progress start if there
    # is one, otherwise at "now".
    chain_end = base_time - task_live_seconds if has_active else base_time

    times: dict[int, tuple[float | None, float | None]] = {}
    cursor = chain_end
    # Walk completed tasks backwards so the last one ends at chain_end.
    for i in range(len(tasks) - 1, -1, -1):
        if tasks[i][2] != 'completed':
            continue
        dur = task_durations[i % len(task_durations)]
        completed_at = cursor
        started_at = completed_at - dur
        times[i] = (started_at, completed_at)
        cursor = started_at
    for i, (_, _, status) in enumerate(tasks):
        if status == 'in_progress':
            times[i] = (base_time - task_live_seconds, None)
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
    task_durations: tuple[float, ...] | None = None,
    task_live_seconds: float = 0.0,
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
    if tasks and task_durations is not None:
        times = _task_timeline(tasks, base_time, task_durations, task_live_seconds)
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
    transcript.write_text('\n'.join(json.dumps(m) for m in msgs) + '\n')


def rewire_paths(raw: dict[str, object], tmpdir: Path, session_id: str) -> None:
    """Redirect session info paths to the synthetic tmpdir environment.

    Only handles cwd, workspace.project_dir, and transcript_path redirection.
    Other editorial mutations (thinking.enabled, effort.level, rate_limits.resets_at)
    are left to the caller.
    """
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


def write_settings(claude_dir: Path, plugins: list[str]) -> None:
    settings = {'enabledPlugins': {p: True for p in plugins}}
    (claude_dir / 'settings.json').write_text(json.dumps(settings, indent=2) + '\n')


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
    (claude / 'statusline-tokens.log').write_text(
        f'{today} demo-prior-session 8200000 215000000 1450000\n'
    )
