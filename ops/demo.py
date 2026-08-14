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

from synth import (
    REPO_ROOT,
    FIXTURE_PATH,
    STATUSLINE_SCRIPT,
    _TERMINAL_STATUSES_DEMO,
    build_synthetic_env,
    write_settings,
    write_subagents,
    _subagent_content_block,
    write_workflows,
    write_openspec_changes,
    write_rate_log_with_peaks,
    render_once,
    _ensure_nested,
    write_transcript as _write_transcript,
    rewire_paths,
)

# Re-export moved names for compatibility
__all__ = [
    'REPO_ROOT',
    'FIXTURE_PATH',
    'STATUSLINE_SCRIPT',
    '_TERMINAL_STATUSES_DEMO',
    'build_synthetic_env',
    'write_settings',
    'write_subagents',
    '_subagent_content_block',
    'write_workflows',
    'write_openspec_changes',
    'write_rate_log_with_peaks',
    'render_once',
    '_ensure_nested',
    'write_transcript',
    'rewire_paths',
]


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


# Wrapper to call synth.write_transcript with demo task params
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
) -> None:
    _write_transcript(
        transcript, skills, total_in, total_cc, total_cr, total_out,
        tasks=tasks, base_time=base_time,
        cache_anchor_secs_ago=cache_anchor_secs_ago,
        cache_1h_tier=cache_1h_tier,
        task_durations=TASK_DURATIONS,
        task_live_seconds=TASK_LIVE_SECONDS,
    )


def mutate_session_info(tmpdir: Path, session_id: str, raw: dict[str, object]) -> str:
    rewire_paths(raw, tmpdir, session_id)
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
    rate_log     = claude / 'statusline-token-rate.log'

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
    five_hour_pct: float                     = 30.0
    seven_day_pct: float                     = 20.0
    yas_toml:      str | None                = None
    subagent_mtime_age: float                = 0.0
    cache_anchor_secs_ago: float | None      = None
    cache_1h_tier:         bool              = False
    columns:       int | None                = None


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
    rate_log     = claude / 'statusline-token-rate.log'

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
    five_hour = _ensure_nested(rate_lims, 'five_hour')
    seven_day = _ensure_nested(rate_lims, 'seven_day')
    five_hour['resets_at']        = resets
    seven_day['resets_at']        = resets
    five_hour['used_percentage']  = cfg.five_hour_pct
    seven_day['used_percentage']  = cfg.seven_day_pct

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
