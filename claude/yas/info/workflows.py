"""RunningWorkflow / RunningWorkflows — Workflow-tool run discovery.

Workflow agents live at `subagents/workflows/<runId>/agent-*.jsonl`; runs are
discovered from the filesystem and opportunistically enriched from the
completion-only `workflows/<runId>.json` snapshot, with filesystem fallbacks
for a still-live run.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from yas.constants import (
    WORKFLOW_LIVENESS_SECONDS,
    _sanitize,
    projects_dir,
)
from yas.info.subagents import RunningSubagent, parse_transcript
from yas.render.text import _middle_ellipsis


# run-JSON statuses meaning "still going"; only a hint, real liveness signal is the filesystem
_NONTERMINAL_STATUSES = frozenset({'running', 'in-progress', 'in_progress', 'queued', 'pending'})

_LABEL_CAP = 48  # middle-ellipsis cap for the fallback prompt-line label


def _first_prompt_line(jsonl: Path) -> str:
    """First non-empty line of the first user message in a transcript, sanitised. Never raises."""
    try:
        with jsonl.open('r', errors='ignore') as fh:
            for ln in fh:
                if '"user"' not in ln:
                    continue
                try:
                    d = json.loads(ln)
                except (ValueError, TypeError):
                    continue
                if d.get('type') != 'user':
                    continue
                content = (d.get('message') or {}).get('content')
                text = ''
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get('type') == 'text':
                            text = str(item.get('text', '') or '')
                            if text:
                                break
                for line in text.splitlines():
                    stripped = line.strip()
                    if stripped:
                        return _sanitize(stripped)
                return ''
    except OSError:
        pass
    return ''


# phase titles live in a `meta.phases: [ {title: '...'}, ... ]` array in the workflow script
_PHASES_BLOCK_RE = re.compile(r'phases:\s*\[(.*?)\]', re.DOTALL)
_TITLE_RE        = re.compile(r"""title:\s*(['"])(.*?)\1""", re.DOTALL)


def _parse_script_phases(scripts_dir: Path, run_id: str) -> list[str]:
    """Phase titles for `run_id` from `workflows/scripts/*-<runId>.js`, in order. `[]` on any error."""
    try:
        scripts = sorted(scripts_dir.glob(f'*-{run_id}.js'))
        if not scripts:
            return []
        body  = scripts[0].read_text(errors='ignore')
        block = _PHASES_BLOCK_RE.search(body)
        if not block:
            return []
        return [m.group(2) for m in _TITLE_RE.finditer(block.group(1))]
    except OSError:
        return []


class RunningWorkflow:
    """One Workflow-tool run and the agents it spawned."""

    __slots__ = ('run_id', 'name', 'phase', 'agents', 'status', 'phases')

    def __init__(
        self,
        run_id: str,
        name:   str,
        phase:  str,
        agents: list[RunningSubagent] | None = None,
        status: str = '',  # raw run-JSON status ('' when no JSON); liveness hint only
        phases: list[str] | None = None,
    ) -> None:
        self.run_id = run_id
        self.name   = name
        self.phase  = phase
        self.agents = agents if agents is not None else []
        self.status = status
        self.phases = phases if phases is not None else []

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RunningWorkflow):
            return NotImplemented
        return (self.run_id, self.name, self.phase, self.agents, self.status, self.phases) == \
               (other.run_id, other.name, other.phase, other.agents, other.status, other.phases)

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return (f'RunningWorkflow(run_id={self.run_id!r}, name={self.name!r}, phase={self.phase!r}, '
                f'agents={self.agents!r}, status={self.status!r}, phases={self.phases!r})')

    @property
    def agent_count(self) -> int:
        return len(self.agents)

    @property
    def done_count(self) -> int:
        return sum(1 for a in self.agents if a.end_ts > 0)  # end_ts > 0 means an end_turn was seen

    @property
    def total_tokens(self) -> int:
        return sum(a.total_input + a.output for a in self.agents)  # per-agent parse, not run JSON's totalTokens

    @property
    def newest_mtime(self) -> float:
        return max((a.mtime for a in self.agents), default=0.0)

    @property
    def status_nonterminal(self) -> bool:
        return self.status.strip().lower() in _NONTERMINAL_STATUSES


class RunningWorkflows:
    __slots__ = ('workflows',)

    def __init__(self, workflows: list[RunningWorkflow] | None = None) -> None:
        self.workflows = workflows if workflows is not None else []

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RunningWorkflows):
            return NotImplemented
        return self.workflows == other.workflows

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return f'RunningWorkflows(workflows={self.workflows!r})'

    @classmethod
    def from_session(cls, session_id: str, project_dir: str) -> RunningWorkflows:
        if not session_id or not project_dir:
            return cls()
        project_slug = re.sub(r'[^A-Za-z0-9]', '-', project_dir)  # same projects/ slug convention as RunningSubagents
        session_dir  = projects_dir() / project_slug / session_id
        runs_dir     = session_dir / 'subagents' / 'workflows'
        if not runs_dir.is_dir():
            return cls()
        workflows: list[RunningWorkflow] = []
        try:
            for run_dir in sorted(runs_dir.iterdir()):
                if not run_dir.is_dir():
                    continue
                agents = cls._parse_agents(run_dir)
                if not agents:
                    continue
                wf = RunningWorkflow(run_id=run_dir.name, name=run_dir.name, phase='', agents=agents)
                cls._enrich(wf, session_dir)
                wf.phases = _parse_script_phases(session_dir / 'workflows' / 'scripts', wf.run_id)
                workflows.append(wf)
        except OSError:
            pass
        return cls(workflows=workflows)

    @staticmethod
    def _parse_agents(run_dir: Path) -> list[RunningSubagent]:
        agents: list[RunningSubagent] = []
        for jsonl in run_dir.glob('agent-*.jsonl'):
            try:
                mtime = jsonl.stat().st_mtime
            except OSError:
                continue
            agent_id = jsonl.stem[len('agent-'):]  # 'agent-<id>.jsonl' -> '<id>'
            billed_in, cache_read_in, output, first_ts, model, last_activity, end_ts, _ = parse_transcript(jsonl)
            # fallback label: first prompt line, in agent_type; run-JSON enrichment may override
            label = _middle_ellipsis(_first_prompt_line(jsonl), _LABEL_CAP)
            agents.append(RunningSubagent(
                agent_type      = label,
                description     = '',
                billed_in       = billed_in,
                output          = output,
                first_timestamp = first_ts,
                model           = model,
                cache_read_in   = cache_read_in,
                total_input     = billed_in + cache_read_in,
                last_activity   = last_activity,
                end_ts          = end_ts,
                mtime           = mtime,
                agent_id        = agent_id,
            ))
        agents.sort(key=lambda a: a.first_timestamp)
        return agents

    @staticmethod
    def _enrich(wf: RunningWorkflow, session_dir: Path) -> None:
        """Opportunistically upgrade a run's name/phase/status/agent labels from `workflows/<runId>.json`."""
        json_path = session_dir / 'workflows' / f'{wf.run_id}.json'
        try:
            data = json.loads(json_path.read_text())
        except Exception:
            return
        if not isinstance(data, dict):
            return

        status = data.get('status')
        if isinstance(status, str):
            wf.status = status

        name = data.get('workflowName')
        if isinstance(name, str) and name.strip():
            wf.name = _sanitize(name.strip())

        progress = data.get('workflowProgress')
        if not isinstance(progress, list):
            return
        labels: dict[str, str] = {}
        phase = ''
        for entry in progress:
            if not isinstance(entry, dict):
                continue
            etype = entry.get('type')
            if etype == 'workflow_phase':
                title = entry.get('title')
                if isinstance(title, str) and title.strip():
                    phase = _sanitize(title.strip())  # latest phase entry wins
            elif etype == 'workflow_agent':
                aid = entry.get('agentId')
                lbl = entry.get('label')
                if isinstance(aid, str) and isinstance(lbl, str) and lbl.strip():
                    labels[aid] = _sanitize(lbl.strip())
        if phase:
            wf.phase = phase
        for agent in wf.agents:
            lbl = labels.get(agent.agent_id)
            if lbl:
                agent.agent_type = _middle_ellipsis(lbl, _LABEL_CAP)

    def visible(self, now: float, last_prompt_ts: float | None) -> list[RunningWorkflow]:
        """Live workflow runs, most-recently-active first: within WORKFLOW_LIVENESS_SECONDS or non-terminal status.

        `last_prompt_ts` is unused (parity with `RunningSubagents.visible`).
        The WORKFLOW_RUN_CAP overflow cap is applied by the layout builders, not here.
        """
        live = [
            wf for wf in self.workflows
            if (now - wf.newest_mtime) <= WORKFLOW_LIVENESS_SECONDS
            or wf.status_nonterminal
        ]
        live.sort(key=lambda wf: wf.newest_mtime, reverse=True)
        return live
