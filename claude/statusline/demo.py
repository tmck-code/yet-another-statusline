"""Hermetic demo for statusline-command.py.

Materialises a synthetic ~/.claude/ and project tree under a tempfile, mutates
the canonical session-info fixture in memory, and pipes the result to the
production statusline script with $HOME pointed at the tempfile. Leaves no
residue on the developer's real filesystem.
"""

from __future__ import annotations

import json
import math
import os
import random
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

WRAPPER_DIR = Path(__file__).resolve().parent
FIXTURE_PATH = WRAPPER_DIR / 'session-info-example.json'
STATUSLINE_SCRIPT = WRAPPER_DIR.parent / 'statusline-command.py'


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


def build_synthetic_env(tmpdir: Path, session_id: str) -> None:
    claude = tmpdir / '.claude'
    project = tmpdir / 'my-project'

    (claude / 'projects' / session_id).mkdir(parents=True)
    (project / '.git' / 'refs' / 'heads').mkdir(parents=True)
    (project / 'openspec' / 'changes' / 'add-skills-row').mkdir(parents=True)
    (project / 'openspec' / 'changes' / 'port-statusline-to-python').mkdir(parents=True)

    (project / '.git' / 'HEAD').write_text('ref: refs/heads/demo\n')
    (project / '.git' / 'refs' / 'heads' / 'demo').write_text('3219308b1c0d4f5a8e7b6c9d2f0a1e3b4c5d6e7f\n')

    (project / 'openspec' / 'changes' / 'add-skills-row' / 'tasks.md').write_text(
        '- [x] one\n- [x] two\n- [x] three\n- [ ] four\n'
    )
    (project / 'openspec' / 'changes' / 'port-statusline-to-python' / 'tasks.md').write_text(
        '- [x] one\n- [ ] two\n- [ ] three\n- [ ] four\n'
    )

    write_settings(claude, [])
    write_transcript(claude / 'projects' / session_id / f'{session_id}.jsonl', [], 0, 0, 0, 0)
    today = datetime.now().strftime('%Y-%m-%d')
    (claude / 'statusline-tokens.log').write_text(
        f'{today} demo-prior-session 8200000 215000000 1450000\n'
    )


def write_settings(claude_dir: Path, plugins: list[str]) -> None:
    settings = {'enabledPlugins': {p: True for p in plugins}}
    (claude_dir / 'settings.json').write_text(json.dumps(settings, indent=2) + '\n')


def write_transcript(transcript: Path, skills: list[str], total_in: int, total_cc: int, total_cr: int, total_out: int) -> None:
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


def animate(env: dict, raw: dict, tmpdir: Path, session_id: str, steps: int = 60, delay: float = 0.10) -> None:
    raw.setdefault('context_window', {})
    raw.setdefault('rate_limits', {}).setdefault('five_hour', {})
    raw['rate_limits'].setdefault('seven_day', {})

    claude       = tmpdir / '.claude'
    project      = tmpdir / 'my-project'
    transcript_p = claude / 'projects' / session_id / f'{session_id}.jsonl'
    rate_log     = claude / 'statusline-token-rate.log'
    moving_spec  = project / 'openspec' / 'changes' / 'port-statusline-to-python' / 'tasks.md'
    spec_total   = 8

    rng = random.Random(42)

    sys.stdout.write('\n\n')
    last_lines = 0

    for i in range(steps + 1):
        pct = i / steps

        total_in   = int(150_000 * pct * 1.05)
        total_cc   = int(total_in * 0.18)
        total_cr   = int(total_in * 12.0)
        total_out  = int(7_500 * pct + 120)

        skill_idx  = min(int(pct * len(SKILLS_PROGRESSION)),  len(SKILLS_PROGRESSION) - 1)
        plugin_idx = min(int(pct * len(PLUGINS_PROGRESSION)), len(PLUGINS_PROGRESSION) - 1)
        skills_now  = SKILLS_PROGRESSION[skill_idx]
        plugins_now = PLUGINS_PROGRESSION[plugin_idx]

        spec_done = min(spec_total, int(pct * spec_total) + 1)
        moving_spec.write_text(
            ''.join(f'- [x] task {n}\n' for n in range(1, spec_done + 1))
            + ''.join(f'- [ ] task {n}\n' for n in range(spec_done + 1, spec_total + 1))
        )

        write_transcript(transcript_p, skills_now, total_in, total_cc, total_cr, total_out)
        write_settings(claude, plugins_now)

        now = time.time()
        cumul_in = total_in + total_cc
        cumul_out = total_out
        n_history = 30
        entries = []
        for j in range(n_history + 1):
            t = now - 60.0 + (60.0 * j / n_history)
            progress = (j / n_history) * pct
            hist_in = int(150_000 * progress * 1.05 * 1.18) + int(rng.random() * 800)
            hist_out = int(7_500 * progress + 120) + int(rng.random() * 200)
            entries.append(f'{t:.3f} {session_id} {hist_in} {hist_out}')
        entries.append(f'{now:.3f} {session_id} {cumul_in} {cumul_out}')
        rate_log.write_text('\n'.join(entries) + '\n')

        raw['context_window']['total_input_tokens']  = total_in
        raw['context_window']['total_output_tokens'] = total_out
        raw['rate_limits']['five_hour']['used_percentage'] = round(15 + pct * 70, 1)
        raw['rate_limits']['seven_day']['used_percentage'] = round(35 + pct * 55, 1)

        out = render_once(env, json.dumps(raw))
        if last_lines > 1:
            sys.stdout.write(f'\033[{last_lines - 1}A\r')
        sys.stdout.write(out)
        sys.stdout.flush()
        last_lines = out.count('\n') + 1
        time.sleep(delay)

    sys.stdout.write('\n\n\n')


def main() -> int:
    fixture = json.loads(FIXTURE_PATH.read_text())
    session_id = fixture['session_id']

    with tempfile.TemporaryDirectory() as raw_tmp:
        tmpdir = Path(raw_tmp)
        build_synthetic_env(tmpdir, session_id)
        payload = mutate_session_info(tmpdir, session_id, fixture)
        raw = json.loads(payload)

        env = os.environ.copy()
        env['HOME'] = str(tmpdir)

        animate(env, raw, tmpdir, session_id)
    return 0


if __name__ == '__main__':
    sys.exit(main())
