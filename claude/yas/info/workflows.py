"""RunningWorkflow / RunningWorkflows — Workflow-tool run discovery.

Workflow agents live one directory deeper than ordinary subagents
(``subagents/workflows/<runId>/agent-*.jsonl``) and their ``meta.json`` carries
no usable label (just ``{"agentType":"workflow-subagent"}``). This reader
discovers runs from the filesystem — the detection spine — parses each agent
with the shared transcript parser, and opportunistically enriches a run from the
*completion-only* ``workflows/<runId>.json`` snapshot. Detection never depends
on that JSON existing; during a live run the per-field fallbacks (run id for the
name, the first prompt line for each agent label, no phase) are the primary path.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from yas.constants import (
    CLAUDE_DIR,
    WORKFLOW_LIVENESS_SECONDS,
    _sanitize,
)
from yas.info.subagents import RunningSubagent, parse_transcript
from yas.render.text import _middle_ellipsis


# Run-JSON statuses that mean "still going". Anything else (``completed``,
# ``failed``, ``cancelled``, or empty) is treated as terminal. This is only a
# liveness *hint*: the real signal during a live run is the filesystem (agents
# actively writing keep newest_mtime within the liveness window), because the
# run JSON is written at completion only.
_NONTERMINAL_STATUSES = frozenset({'running', 'in-progress', 'in_progress', 'queued', 'pending'})

# Middle-ellipsis cap for the fallback prompt-line label, so a long first prompt
# never blows out a one-line agent row. subagent_row fits it further per width.
_LABEL_CAP = 48


def _first_prompt_line(jsonl: Path) -> str:
    """First non-empty line of the first user message in a transcript, sanitised.

    A user message's ``content`` may be a plain string or a list of blocks;
    both are handled. Returns '' when no user text is found. Never raises.
    """
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


# The phases live in a ``meta.phases: [ ... ]`` array inside the workflow
# script. Each phase object carries a ``title: '...'`` (single or double
# quoted). We match the bracketed block narrowly, then pull each title in order.
_PHASES_BLOCK_RE = re.compile(r'phases:\s*\[(.*?)\]', re.DOTALL)
_TITLE_RE        = re.compile(r"""title:\s*(['"])(.*?)\1""", re.DOTALL)


def _parse_script_phases(scripts_dir: Path, run_id: str) -> list[str]:
    """Phase titles for ``run_id`` from its workflow script, in order.

    The script is written to ``workflows/scripts/<name>-<runId>.js`` at run
    start and is the only on-disk source of phase titles during a live run.
    Locates it by the ``*-<runId>.js`` suffix, regex-parses the ``phases:[...]``
    block, and extracts each ``title:`` string. Returns ``[]`` on ANY error
    (missing dir, no matching script, unreadable file, no parseable block).
    """
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


@dataclass
class RunningWorkflow:
    """One Workflow-tool run and the agents it spawned."""

    run_id: str
    name:   str
    phase:  str
    agents: list[RunningSubagent] = field(default_factory=list)
    status: str = ''  # raw run-JSON status ('' when no JSON); liveness hint only
    phases: list[str] = field(default_factory=list)

    @property
    def agent_count(self) -> int:
        return len(self.agents)

    @property
    def done_count(self) -> int:
        # Done reuses the subagent rule: end_ts > 0 (an end_turn was seen).
        return sum(1 for a in self.agents if a.end_ts > 0)

    @property
    def total_tokens(self) -> int:
        # Summed from the per-agent transcript parse, never the run JSON's
        # reported totalTokens (which only exists once the run completes).
        return sum(a.total_input + a.output for a in self.agents)

    @property
    def newest_mtime(self) -> float:
        return max((a.mtime for a in self.agents), default=0.0)

    @property
    def status_nonterminal(self) -> bool:
        return self.status.strip().lower() in _NONTERMINAL_STATUSES


@dataclass
class RunningWorkflows:
    workflows: list[RunningWorkflow] = field(default_factory=list)

    @classmethod
    def from_session(cls, session_id: str, project_dir: str) -> RunningWorkflows:
        if not session_id or not project_dir:
            return cls()
        # Same projects/ dir convention as RunningSubagents.from_session: every
        # non-alphanumeric char becomes '-' (Unix and Windows safe).
        project_slug = re.sub(r'[^A-Za-z0-9]', '-', project_dir)
        session_dir  = CLAUDE_DIR / 'projects' / project_slug / session_id
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
            billed_in, cache_read_in, output, first_ts, model, last_activity, end_ts = parse_transcript(jsonl)
            # Fallback identity: the label defaults to the first prompt line and
            # lives in agent_type so subagent_row renders it as the primary
            # identity at every width. run-JSON enrichment may override it.
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
        """Opportunistically upgrade a run from ``workflows/<runId>.json``.

        Sets the run name from ``workflowName``, maps ``workflowProgress``
        ``agentId -> label`` onto each agent, derives the current phase from the
        latest ``workflow_phase`` entry, and records the raw status. Never raises
        on a missing or malformed JSON — the run keeps its filesystem fallbacks.
        """
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
        """Live workflow runs, most-recently-active first.

        A run stays visible while any agent transcript was written within
        WORKFLOW_LIVENESS_SECONDS (longer than the subagent cohort's windows so a
        run rides through a between-phase lull), OR while its run JSON reports a
        non-terminal status. A settled run — terminal status or all agents Done,
        with its newest transcript older than that window — falls out of the
        liveness window and retires.

        ``last_prompt_ts`` is accepted for parity with
        ``RunningSubagents.visible``; workflow liveness is purely window/status
        based and does not consult the prompt boundary.

        The concurrent-run cap (WORKFLOW_RUN_CAP) is applied by the layout
        builders, which own the ``+N more workflows`` overflow text; this method
        only supplies the liveness filter and recency ordering they slice.
        """
        live = [
            wf for wf in self.workflows
            if (now - wf.newest_mtime) <= WORKFLOW_LIVENESS_SECONDS
            or wf.status_nonterminal
        ]
        live.sort(key=lambda wf: wf.newest_mtime, reverse=True)
        return live
