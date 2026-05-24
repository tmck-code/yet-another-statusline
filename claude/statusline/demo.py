"""Hermetic demo for statusline_command.py.

Materialises a synthetic ~/.claude/ and project tree under a tempfile, mutates
the canonical session-info fixture in memory, and pipes the result to the
production statusline script with $HOME pointed at the tempfile. Leaves no
residue on the developer's real filesystem.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

WRAPPER_DIR = Path(__file__).resolve().parent
FIXTURE_PATH = WRAPPER_DIR / 'session-info-example.json'
STATUSLINE_SCRIPT = WRAPPER_DIR.parent / 'statusline_command.py'


SKILLS_PROGRESSION = (
    [],
    ['grill-me'],
    ['grill-me', 'caveman'],
    ['grill-me', 'caveman', 'tdd'],
    ['grill-me', 'caveman', 'tdd', 'rocky:rocky'],
    ['grill-me', 'caveman', 'tdd', 'rocky:rocky', 'frontend-design:frontend-design'],
)

PLUGINS_PROGRESSION = (
    [],
    ['openspec@0.1.0'],
    ['openspec@0.1.0', 'frontend-design@0.3.2'],
    ['openspec@0.1.0', 'frontend-design@0.3.2', 'rocky@0.1.0'],
)

# [(name, done, total), ...] per animation stage. Both specs hit 100% before the
# final empty stage clears them.
OPENSPEC_PROGRESSION = (
    [],
    [('port-statusline-to-python', 1, 8)],
    [('port-statusline-to-python', 3, 8), ('add-gradient-engine', 2, 8)],
    [('port-statusline-to-python', 6, 8), ('add-gradient-engine', 5, 8)],
    [('port-statusline-to-python', 8, 8), ('add-gradient-engine', 8, 8)],
    [],
)

# (agentType, description, billed_in, output_tokens, action) — empty list means no subagent active
# action is (tool_name, input_dict) or None; omit to leave activity blank.
SUBAGENTS_PROGRESSION = (
    [],
    [('explore',         'Search codebase - looking for token tracking', 0, 0, ('Bash',  {'command': 'grep -rn "billed_in" claude/statusline_command.py'}))],
    [('explore',         'Search codebase - looking for token tracking', 0, 0, ('Read',  {'file_path': 'claude/statusline_command.py'}))],
    [('general-purpose', 'Fix sparkline - update bucket algorithm',      0, 0, ('Edit',  {'file_path': 'claude/statusline_command.py', 'old_string': 'old', 'new_string': 'new'}))],
    [('general-purpose', 'Fix sparkline - update bucket algorithm',      0, 0, None)],
    [],
)

# (subject, activeForm) for the TaskList progression row.
DEMO_TASKS = (
    ('Audit gradient palette', 'Auditing gradient palette'),
    ('Wire alert-mode pill',   'Wiring alert-mode pill'),
    ('Refactor border math',   'Refactoring border math'),
    ('Update CONTEXT.md',      'Updating CONTEXT.md'),
)

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


def write_subagents(
    claude_dir:  Path,
    session_id:  str,
    project_dir: Path,
    subagents:   list[tuple],
) -> None:
    """Each subagent entry: (agentType, description, billed_in, output_tokens[, action]).

    action is (tool_name, input_dict) or None; if absent or None, content is omitted.
    """
    project_slug = str(project_dir).replace('/', '-').lstrip('-')
    subagents_dir = claude_dir / 'projects' / f'-{project_slug}' / session_id / 'subagents'
    subagents_dir.mkdir(parents=True, exist_ok=True)
    for f in subagents_dir.iterdir():
        f.unlink()
    now = time.time()
    ts  = datetime.now().astimezone().isoformat()
    for i, row in enumerate(subagents, 1):
        agent_type, description, billed_in, output_tokens = row[:4]
        action = row[4] if len(row) > 4 else None
        name = f'demo-subagent-{i}'
        (subagents_dir / f'{name}.meta.json').write_text(
            json.dumps({'agentType': agent_type, 'description': description})
        )
        jsonl = subagents_dir / f'{name}.jsonl'
        if billed_in or output_tokens or action:
            # cache_creation carries the bulk; input_tokens gets the remainder
            cache_creation = int(billed_in * 0.7)
            input_tokens   = billed_in - cache_creation
            entry = {
                'type':      'assistant',
                'timestamp': ts,
                'message': {
                    'id':   f'msg_demo_agent_{i}',
                    'role': 'assistant',
                    'usage': {
                        'input_tokens':                input_tokens,
                        'cache_creation_input_tokens': cache_creation,
                        'cache_read_input_tokens':     0,
                        'output_tokens':               output_tokens,
                    },
                },
            }
            if action is not None:
                tool_name, input_dict = action
                entry['message']['content'] = [
                    {'type': 'tool_use', 'name': tool_name, 'input': input_dict}
                ]
            jsonl.write_text(json.dumps(entry) + '\n')
        else:
            jsonl.write_text('')
        os.utime(jsonl, (now, now))


def write_settings(claude_dir: Path, plugins: list[str]) -> None:
    settings = {'enabledPlugins': {p: True for p in plugins}}
    (claude_dir / 'settings.json').write_text(json.dumps(settings, indent=2) + '\n')


def write_transcript(
    transcript: Path,
    skills: list[str],
    total_in: int,
    total_cc: int,
    total_cr: int,
    total_out: int,
    tasks: list[tuple[str, str, str]] | None = None,
) -> None:
    msgs = []
    n = max(1, len(skills))
    for i, skill in enumerate(skills or ['']):
        last = (i == n - 1)
        share_in   = total_in   // n + (total_in   % n if last else 0)
        share_cc   = total_cc   // n + (total_cc   % n if last else 0)
        share_cr   = total_cr   // n + (total_cr   % n if last else 0)
        share_out  = total_out  // n + (total_out  % n if last else 0)
        msg: dict = {
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
        msgs.append({'type': 'assistant', 'message': msg})
    if tasks:
        ts_now = datetime.now().astimezone().isoformat()
        msgs.append({
            'type': 'assistant',
            'timestamp': ts_now,
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
        updates = [
            {
                'type': 'tool_use',
                'name': 'TaskUpdate',
                'input': {'taskId': str(i + 1), 'status': status, 'activeForm': af},
            }
            for i, (_, af, status) in enumerate(tasks)
            if status != 'pending'
        ]
        if updates:
            msgs.append({
                'type': 'assistant',
                'timestamp': ts_now,
                'message': {
                    'id': 'msg_task_update',
                    'role': 'assistant',
                    'content': updates,
                },
            })
    transcript.write_text('\n'.join(json.dumps(m) for m in msgs) + '\n')


def mutate_session_info(tmpdir: Path, session_id: str, raw: dict) -> str:
    project = tmpdir / 'my-project'
    raw['cwd'] = str(project)
    raw.setdefault('workspace', {})['project_dir'] = str(project)
    raw['transcript_path'] = str(
        tmpdir / '.claude' / 'projects' / session_id / f'{session_id}.jsonl'
    )
    resets = int(time.time()) + 7200
    raw.setdefault('rate_limits', {}).setdefault('five_hour', {})['resets_at'] = resets
    raw['rate_limits'].setdefault('seven_day', {})['resets_at'] = resets
    raw['thinking'] = {'enabled': True}
    raw['effort'] = {'level': 'high'}
    return json.dumps(raw)


SOFT_LIMIT = 150_000


def render_once(env: dict, payload: str) -> str:
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


def animate(env: dict, raw: dict, tmpdir: Path, session_id: str, steps: int = DEMO_STEPS, delay: float = DEMO_DELAY) -> None:
    raw.setdefault('context_window', {})
    raw.setdefault('rate_limits', {}).setdefault('five_hour', {})
    raw['rate_limits'].setdefault('seven_day', {})

    claude       = tmpdir / '.claude'
    project      = tmpdir / 'my-project'
    transcript_p = claude / 'projects' / session_id / f'{session_id}.jsonl'
    rate_log     = claude / 'statusline-token-rate.log'

    rng = random.Random(42)
    KEEP = max(300.0, DEMO_TOKEN_WINDOW * 4)

    sys.stdout.write('\n\n')
    sys.stdout.write('\033[?25l')  # hide cursor to prevent it jumping during redraws
    sys.stdout.flush()
    last_lines = 0
    rate_cumul_in = 0

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
            write_transcript(transcript_p, skills_now, total_in, total_cc, total_cr, total_out, tasks=tasks_now)
            write_settings(claude, plugins_now)
            write_subagents(claude, session_id, project, subagent_now)
            write_openspec_changes(project, openspec_now)

            now = time.time()
            rate_cumul_in += RATE_PEAK_PROFILE.get(i, RATE_BASE_DELTA)
            cumul_out = total_out

            existing = rate_log.read_text().splitlines() if rate_log.exists() else []
            kept = [ln for ln in existing if ln and now - float(ln.split()[0]) <= KEEP]
            kept.append(f'{now:.3f} {session_id} {rate_cumul_in} {cumul_out}')
            rate_log.write_text('\n'.join(kept) + '\n')

            raw['context_window']['total_input_tokens']  = total_in
            raw['context_window']['total_output_tokens'] = total_out
            raw['rate_limits']['five_hour']['used_percentage'] = round(15 + pct * 70, 1)
            raw['rate_limits']['seven_day']['used_percentage'] = round(35 + pct * 55, 1)

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
    subagents:     list[tuple]                     = field(default_factory=list)
    openspec:      list[tuple[str, int, int]]= field(default_factory=list)
    tasks:         list[tuple[str, str, str]]= field(default_factory=list)
    five_hour_pct: float                     = 30.0
    seven_day_pct: float                     = 20.0


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
    ),
    ScenarioConfig(
        name        = 'tasks',
        effort      = 'high',
        thinking    = True,
        context_pct = 0.15,
        skills      = ['grill-me', 'caveman'],
        plugins     = ['openspec@0.1.0'],
        tasks       = [
            ('Audit gradient palette', 'Auditing gradient palette', 'completed'),
            ('Wire alert-mode pill',   'Wiring alert-mode pill',    'completed'),
            ('Refactor border math',   'Refactoring border math',   'in_progress'),
            ('Update CONTEXT.md',      'Updating CONTEXT.md',       'pending'),
        ],
        five_hour_pct = 22.0,
        seven_day_pct = 15.0,
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
        ],
        five_hour_pct = 46.0,
        seven_day_pct = 37.0,
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
        ],
        openspec    = [
            ('add-gradient-engine',        6, 8),
            ('port-statusline-to-python',  3, 8),
            ('wire-alert-mode-pill',       1, 6),
        ],
        tasks       = [
            ('Audit gradient palette', 'Auditing gradient palette', 'completed'),
            ('Wire alert-mode pill',   'Wiring alert-mode pill',    'completed'),
            ('Refactor border math',   'Refactoring border math',   'in_progress'),
            ('Update CONTEXT.md',      'Updating CONTEXT.md',       'pending'),
        ],
        five_hour_pct = 58.0,
        seven_day_pct = 49.0,
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


def render_scenario(
    env:        dict,
    fixture:    dict,
    tmpdir:     Path,
    session_id: str,
    cfg:        ScenarioConfig,
    out_dir:    Path,
) -> None:
    claude       = tmpdir / '.claude'
    project      = tmpdir / 'my-project'
    transcript_p = claude / 'projects' / session_id / f'{session_id}.jsonl'
    rate_log     = claude / 'statusline-token-rate.log'

    ctx_size  = 200_000
    total_in  = int(ctx_size * cfg.context_pct * 0.88)
    total_cc  = int(total_in * 0.18)
    total_cr  = int(total_in * 12.0)
    total_out = int(ctx_size * cfg.context_pct * 0.12)

    write_transcript(transcript_p, cfg.skills, total_in, total_cc, total_cr, total_out, tasks=cfg.tasks or None)
    write_settings(claude, cfg.plugins)
    write_subagents(claude, session_id, project, cfg.subagents)
    write_openspec_changes(project, cfg.openspec)
    write_rate_log_with_peaks(rate_log, session_id, total_in + total_cc + total_out)

    raw = dict(fixture)
    raw['model']          = {'id': cfg.model_id, 'display_name': cfg.model_name}
    raw['effort']         = {'level': cfg.effort} if cfg.effort else {}
    raw['thinking']       = {'enabled': cfg.thinking}
    raw['cwd']            = str(project)
    raw.setdefault('workspace', {})['project_dir'] = str(project)
    raw['transcript_path'] = str(transcript_p)
    raw['context_window']['total_input_tokens']  = total_in
    raw['context_window']['total_output_tokens'] = total_out
    resets = int(time.time()) + 7200
    raw.setdefault('rate_limits', {}).setdefault('five_hour', {})['resets_at']        = resets
    raw['rate_limits'].setdefault('seven_day', {})['resets_at']                        = resets
    raw['rate_limits']['five_hour']['used_percentage'] = cfg.five_hour_pct
    raw['rate_limits']['seven_day']['used_percentage'] = cfg.seven_day_pct

    snap_env = {**env, 'COLUMNS': str(SNAPSHOT_COLS), 'STATUSLINE_TOKEN_WINDOW': str(SNAP_WINDOW)}
    out = render_once(snap_env, json.dumps(raw))
    dest = out_dir / f'{cfg.name}.txt'
    dest.write_text('\n\n'+out+'\n\n')
    print(f'  wrote {dest}')


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshots', metavar='DIR', help='render scenario images into DIR instead of animating')
    args = parser.parse_args()

    fixture = json.loads(FIXTURE_PATH.read_text())
    session_id = fixture['session_id']

    with tempfile.TemporaryDirectory() as raw_tmp:
        tmpdir = Path(raw_tmp)
        build_synthetic_env(tmpdir, session_id)

        env = os.environ.copy()
        env['HOME'] = str(tmpdir)

        if args.snapshots:
            out_dir = Path(args.snapshots)
            out_dir.mkdir(parents=True, exist_ok=True)
            for cfg in SCENARIOS:
                render_scenario(env, fixture, tmpdir, session_id, cfg, out_dir)
        else:
            payload = mutate_session_info(tmpdir, session_id, fixture)
            raw = json.loads(payload)
            env['STATUSLINE_TOKEN_WINDOW'] = str(DEMO_TOKEN_WINDOW)
            os.system('clear -x')
            animate(env, raw, tmpdir, session_id)
    return 0


if __name__ == '__main__':
    sys.exit(main())
