"""Tests for the workflow cohort: RunningWorkflows discovery/enrichment/liveness
and the workflow header/summary/layout rendering."""
import json
import os
import time
from pathlib import Path

import yas.layout as layout
import yas.renderer as renderer_mod
import yas.session as session_mod
from yas.config import Config
from yas.constants import (
    GLYPH_WF_HEADER,
    GLYPH_WF_SUMMARY,
    WORKFLOW_LIVENESS_SECONDS,
)
from yas.info import SessionView
from yas.info.subagents import RunningSubagent, RunningSubagents
from yas.info.workflows import RunningWorkflow, RunningWorkflows
from yas.tokens import TickRecord, TokenLog

from test_running_subagents import (
    PROJECT_DIR,
    PROJECT_SLUG,
    SESSION_ID,
    _assistant_line,
    _assistant_line_with_stop_reason,
)


_r = renderer_mod.Renderer()
_SESSION = Path(__file__).parent.parent / 'ops' / 'session-info-example.json'


def _session() -> session_mod.SessionInfo:
    return session_mod.SessionInfo.from_dict(json.loads(_SESSION.read_text()))


def _view() -> SessionView:
    return SessionView(_session(), Config())


def _tick() -> TickRecord:
    return TickRecord(token_log=TokenLog(), day_cost=0.0, tok_rate=0)


def _session_root(tmp_home: Path) -> Path:
    return tmp_home / '.claude' / 'projects' / f'-{PROJECT_SLUG}' / SESSION_ID


def _write_workflow_agent(
    root: Path,
    run_id: str,
    agent_id: str,
    *,
    jsonl_lines: list[str] | None = None,
    mtime: float | None = None,
    with_meta: bool = True,
) -> Path:
    run_dir = root / 'subagents' / 'workflows' / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    if with_meta:
        meta = run_dir / f'agent-{agent_id}.meta.json'
        meta.write_text(json.dumps({'agentType': 'workflow-subagent'}))
    jsonl = run_dir / f'agent-{agent_id}.jsonl'
    lines = jsonl_lines if jsonl_lines is not None else ['{"event": "start"}\n']
    jsonl.write_text(''.join(lines))
    if mtime is not None:
        os.utime(jsonl, (mtime, mtime))
    return jsonl


def _write_run_json(root: Path, run_id: str, payload) -> Path:
    wf_dir = root / 'workflows'
    wf_dir.mkdir(parents=True, exist_ok=True)
    path = wf_dir / f'{run_id}.json'
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload))
    return path


def _write_ordinary_subagent(root: Path, agent_id: str, *, mtime: float) -> None:
    sdir = root / 'subagents'
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / f'{agent_id}.meta.json').write_text(
        json.dumps({'agentType': 'Explore', 'description': 'find X'}))
    jsonl = sdir / f'{agent_id}.jsonl'
    jsonl.write_text('{"event": "start"}\n')
    os.utime(jsonl, (mtime, mtime))


def _make_workflow_subagent(
    agent_id: str,
    *,
    total_input: int = 0,
    output: int = 0,
    end_ts: float = 0.0,
    mtime: float = 0.0,
    first_timestamp: float = 0.0,
    agent_type: str = 'label',
) -> RunningSubagent:
    return RunningSubagent(
        agent_type      = agent_type,
        description     = '',
        billed_in       = total_input,
        output          = output,
        first_timestamp = first_timestamp,
        total_input     = total_input,
        end_ts          = end_ts,
        mtime           = mtime,
        agent_id        = agent_id,
    )


class TestWorkflowDetection:

    def test_run_discovered_without_run_json(self, tmp_home):
        # setup
        now  = time.time()
        root = _session_root(tmp_home)
        _write_workflow_agent(
            root, 'wf_x', 'a1de7949b753bf883',
            jsonl_lines=[_assistant_line('m1', input_tokens=10, output_tokens=5)],
            mtime=now,
        )

        # run
        result = RunningWorkflows.from_session(SESSION_ID, PROJECT_DIR)

        # expected
        expected = RunningWorkflow(
            run_id = 'wf_x',
            name   = 'wf_x',
            phase  = '',
            agents = [_make_workflow_subagent(
                'a1de7949b753bf883', total_input=10, output=5, mtime=now, agent_type='')],
        )

        # assert
        assert result == RunningWorkflows(workflows=[expected])

    def test_agent_id_derived_from_filename_stem(self, tmp_home):
        # setup
        now  = time.time()
        root = _session_root(tmp_home)
        _write_workflow_agent(root, 'wf_x', 'a1de7949b753bf883', mtime=now)

        # run
        result = RunningWorkflows.from_session(SESSION_ID, PROJECT_DIR)

        # expected
        expected = 'a1de7949b753bf883'

        # assert
        assert result.workflows[0].agents[0].agent_id == expected

    def test_workflow_and_ordinary_subagents_do_not_cross_contaminate(self, tmp_home):
        # setup
        now  = time.time()
        root = _session_root(tmp_home)
        _write_ordinary_subagent(root, 'agent-plain', mtime=now)
        _write_workflow_agent(root, 'wf_x', 'a1de7949b753bf883', mtime=now)

        # run
        workflows = RunningWorkflows.from_session(SESSION_ID, PROJECT_DIR)
        subagents = RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)

        # expected
        expected_wf_ids  = ['a1de7949b753bf883']
        expected_sub_ids = ['']  # ordinary subagent carries no agent_id

        # assert
        assert [a.agent_id for w in workflows.workflows for a in w.agents] == expected_wf_ids
        assert [s.agent_id for s in subagents.subagents] == expected_sub_ids
        assert [s.agent_type for s in subagents.subagents] == ['Explore']


class TestWorkflowEnrichment:

    def test_run_json_sets_name_phase_and_agent_labels(self, tmp_home):
        # setup
        now  = time.time()
        root = _session_root(tmp_home)
        _write_workflow_agent(root, 'wf_x', 'a1', mtime=now)
        _write_run_json(root, 'wf_x', {
            'runId': 'wf_x',
            'workflowName': 'my-workflow',
            'status': 'completed',
            'workflowProgress': [
                {'type': 'workflow_phase', 'index': 1, 'title': 'Gather'},
                {'type': 'workflow_phase', 'index': 2, 'title': 'Analyse'},
                {'type': 'workflow_agent', 'index': 1, 'label': 'fetch-thing', 'agentId': 'a1'},
            ],
        })

        # run
        result = RunningWorkflows.from_session(SESSION_ID, PROJECT_DIR).workflows[0]

        # expected
        expected = ('my-workflow', 'Analyse', 'completed', 'fetch-thing')

        # assert
        assert (result.name, result.phase, result.status, result.agents[0].agent_type) == expected

    def test_fallback_label_from_string_prompt(self, tmp_home):
        # setup
        now  = time.time()
        root = _session_root(tmp_home)
        prompt = '{"type":"user","message":{"role":"user","content":"do the thing now"}}\n'
        _write_workflow_agent(root, 'wf_x', 'a1', jsonl_lines=[prompt], mtime=now)

        # run
        result = RunningWorkflows.from_session(SESSION_ID, PROJECT_DIR).workflows[0]

        # expected
        expected = ('wf_x', '', 'do the thing now')

        # assert
        assert (result.name, result.phase, result.agents[0].agent_type) == expected

    def test_fallback_label_from_block_list_prompt(self, tmp_home):
        # setup
        now  = time.time()
        root = _session_root(tmp_home)
        prompt = json.dumps({
            'type': 'user',
            'message': {'role': 'user', 'content': [{'type': 'text', 'text': 'analyse the data'}]},
        }) + '\n'
        _write_workflow_agent(root, 'wf_x', 'a1', jsonl_lines=[prompt], mtime=now)

        # run
        result = RunningWorkflows.from_session(SESSION_ID, PROJECT_DIR).workflows[0]

        # expected
        expected = ('wf_x', '', 'analyse the data')

        # assert
        assert (result.name, result.phase, result.agents[0].agent_type) == expected

    def test_malformed_run_json_degrades_to_fallback(self, tmp_home):
        # setup
        now  = time.time()
        root = _session_root(tmp_home)
        _write_workflow_agent(root, 'wf_x', 'a1', mtime=now)
        _write_run_json(root, 'wf_x', '{ not json')

        # run
        result = RunningWorkflows.from_session(SESSION_ID, PROJECT_DIR).workflows[0]

        # expected
        expected = ('wf_x', 'wf_x', '')

        # assert
        assert (result.run_id, result.name, result.phase) == expected


class TestWorkflowLiveness:

    def test_visible_during_between_phase_lull(self, tmp_home):
        # setup: all agents Done but newest mtime is fresh -> rides the lull
        now  = time.time()
        root = _session_root(tmp_home)
        _write_workflow_agent(
            root, 'wf_x', 'a1',
            jsonl_lines=[_assistant_line_with_stop_reason('m1', 'end_turn', timestamp='2026-05-22T18:00:00Z')],
            mtime=now - 10,
        )
        wfs = RunningWorkflows.from_session(SESSION_ID, PROJECT_DIR)

        # run
        result = wfs.visible(now, None)

        # assert
        assert [w.run_id for w in result] == ['wf_x']

    def test_settled_run_retires(self, tmp_home):
        # setup: terminal (Done) AND newest mtime older than the liveness window
        now  = time.time()
        root = _session_root(tmp_home)
        _write_workflow_agent(
            root, 'wf_x', 'a1',
            jsonl_lines=[_assistant_line_with_stop_reason('m1', 'end_turn', timestamp='2026-05-22T18:00:00Z')],
            mtime=now - WORKFLOW_LIVENESS_SECONDS - 1,
        )
        wfs = RunningWorkflows.from_session(SESSION_ID, PROJECT_DIR)

        # run
        result = wfs.visible(now, None)

        # assert
        assert result == []

    def test_stale_leftover_dir_retires(self, tmp_home):
        # setup: old mtime, no run JSON -> not visible
        now  = time.time()
        root = _session_root(tmp_home)
        _write_workflow_agent(root, 'wf_x', 'a1', mtime=now - WORKFLOW_LIVENESS_SECONDS - 1)
        wfs = RunningWorkflows.from_session(SESSION_ID, PROJECT_DIR)

        # run
        result = wfs.visible(now, None)

        # assert
        assert result == []

    def test_nonterminal_status_keeps_old_run_visible(self, tmp_home):
        # setup: stale mtime, but run JSON status 'running' pins it visible
        now  = time.time()
        root = _session_root(tmp_home)
        _write_workflow_agent(root, 'wf_x', 'a1', mtime=now - WORKFLOW_LIVENESS_SECONDS - 1)
        _write_run_json(root, 'wf_x', {'runId': 'wf_x', 'workflowName': 'wf', 'status': 'running'})
        wfs = RunningWorkflows.from_session(SESSION_ID, PROJECT_DIR)

        # run
        result = wfs.visible(now, None)

        # assert
        assert [w.run_id for w in result] == ['wf_x']

    def test_visible_sorted_most_recent_first(self, tmp_home):
        # setup
        now  = time.time()
        root = _session_root(tmp_home)
        _write_workflow_agent(root, 'wf_old', 'a1', mtime=now - 30)
        _write_workflow_agent(root, 'wf_new', 'a2', mtime=now - 5)
        wfs = RunningWorkflows.from_session(SESSION_ID, PROJECT_DIR)

        # run
        result = wfs.visible(now, None)

        # expected
        expected = ['wf_new', 'wf_old']

        # assert
        assert [w.run_id for w in result] == expected


class TestWorkflowMetrics:

    def test_done_count_counts_only_ended_agents(self):
        # setup
        run = RunningWorkflow(
            run_id = 'wf_x', name = 'wf_x', phase = '',
            agents = [
                _make_workflow_subagent('a1', end_ts=100.0),
                _make_workflow_subagent('a2', end_ts=0.0),
                _make_workflow_subagent('a3', end_ts=200.0),
            ],
        )

        # run
        result = run.done_count

        # expected
        expected = 2

        # assert
        assert result == expected

    def test_total_tokens_sums_per_agent_ignoring_run_json(self, tmp_home):
        # setup: per-agent transcripts carry real tokens; run JSON's totalTokens is bogus
        now  = time.time()
        root = _session_root(tmp_home)
        _write_workflow_agent(
            root, 'wf_x', 'a1',
            jsonl_lines=[_assistant_line('m1', input_tokens=10, cache_read=5, output_tokens=4)],
            mtime=now,
        )
        _write_workflow_agent(
            root, 'wf_x', 'a2',
            jsonl_lines=[_assistant_line('m2', input_tokens=20, output_tokens=6)],
            mtime=now,
        )
        _write_run_json(root, 'wf_x', {
            'runId': 'wf_x', 'workflowName': 'wf', 'totalTokens': 999999,
        })

        # run
        result = RunningWorkflows.from_session(SESSION_ID, PROJECT_DIR).workflows[0].total_tokens

        # expected
        expected = (10 + 5 + 4) + (20 + 6)

        # assert
        assert result == expected


class TestWorkflowHeaderSummary:

    def test_header_contains_glyph_name_and_phase(self, strip_ansi):
        # setup
        run = RunningWorkflow(run_id='wf_x', name='my-workflow', phase='Analyse')

        # run
        result = strip_ansi(_r.workflow_header(run, 80))

        # assert
        assert GLYPH_WF_HEADER in result
        assert 'my-workflow' in result
        assert '[Analyse]' in result

    def test_header_omits_phase_when_empty(self, strip_ansi):
        # setup
        run = RunningWorkflow(run_id='wf_x', name='my-workflow', phase='')

        # run
        result = strip_ansi(_r.workflow_header(run, 80))

        # assert
        assert GLYPH_WF_HEADER in result
        assert 'my-workflow' in result
        assert '[' not in result

    def test_summary_contains_counts_and_tokens(self, strip_ansi):
        # setup
        run = RunningWorkflow(
            run_id = 'wf_x', name = 'wf_x', phase = '',
            agents = [
                _make_workflow_subagent('a1', total_input=1000, output=200, end_ts=1.0),
                _make_workflow_subagent('a2', total_input=500, output=100),
            ],
        )

        # run
        result = strip_ansi(_r.workflow_summary(run, 80))

        # assert
        assert GLYPH_WF_SUMMARY in result
        assert '2 agents' in result
        assert '1 done' in result
        assert '1.8K' in result

    def test_summary_appends_hidden_agents(self, strip_ansi):
        # setup
        run = RunningWorkflow(
            run_id = 'wf_x', name = 'wf_x', phase = '',
            agents = [_make_workflow_subagent('a1')],
        )

        # run
        result = strip_ansi(_r.workflow_summary(run, 80, hidden_agents=3))

        # assert
        assert '+3 hidden' in result


class TestWorkflowLayout:

    def _inject(self, view, runs):
        # cached_property stores into the instance __dict__; bypass FS discovery
        view.__dict__['workflows'] = RunningWorkflows(workflows=runs)

    def test_narrow_collapse_yields_header_and_summary_only(self, strip_ansi):
        # setup
        now  = time.time()
        view = _view()
        run  = RunningWorkflow(
            run_id = 'wf_x', name = 'wf_x', phase = '',
            agents = [_make_workflow_subagent(f'a{i}', mtime=now) for i in range(3)],
        )
        self._inject(view, [run])

        # run
        rows = layout.build_workflow_rows(view, 80, _r, per_agent=False)
        texts = [strip_ansi(row.content) for row in rows]

        # expected: exactly one header and one summary, no per-agent rows
        header_rows  = [t for t in texts if GLYPH_WF_HEADER in t]
        summary_rows = [t for t in texts if GLYPH_WF_SUMMARY in t]

        # assert
        assert len(rows) == 2
        assert len(header_rows) == 1
        assert len(summary_rows) == 1

    def test_per_agent_yields_header_agent_rows_and_summary(self, strip_ansi):
        # setup
        now  = time.time()
        view = _view()
        run  = RunningWorkflow(
            run_id = 'wf_x', name = 'wf_x', phase = '',
            agents = [
                _make_workflow_subagent(f'a{i}', agent_type=f'agent-{i}', mtime=now)
                for i in range(3)
            ],
        )
        self._inject(view, [run])

        # run
        rows = layout.build_workflow_rows(view, 160, _r, per_agent=True)
        texts = [strip_ansi(row.content) for row in rows]

        # The summary glyph (└) is shared with the twoline subagent-row
        # continuation glyph, so the summary is identified by its 'agents'/'done'
        # text rather than the bare glyph.
        header_rows  = [t for t in texts if GLYPH_WF_HEADER in t]
        summary_rows = [t for t in texts if GLYPH_WF_SUMMARY in t and 'agents' in t and 'done' in t]
        agent_rows   = [t for t in texts if t not in header_rows and t not in summary_rows]

        # assert: header + summary present, plus per-agent content beyond them
        assert len(header_rows) == 1
        assert len(summary_rows) == 1
        assert any('agent-0' in t for t in agent_rows)
        assert any('agent-2' in t for t in agent_rows)

    def test_agent_cap_caps_rows_and_reports_hidden(self, strip_ansi):
        # setup: 9 agents, cap is 6 -> 3 hidden
        now  = time.time()
        view = _view()
        run  = RunningWorkflow(
            run_id = 'wf_x', name = 'wf_x', phase = '',
            agents = [
                _make_workflow_subagent(f'a{i}', agent_type=f'agent-{i}', first_timestamp=now + i, mtime=now)
                for i in range(9)
            ],
        )
        self._inject(view, [run])

        # run
        rows  = layout.build_workflow_rows(view, 160, _r, per_agent=True)
        texts = [strip_ansi(row.content) for row in rows]

        # assert: the first 6 agents render (sorted by first_timestamp), agents
        # 6-8 do not, hidden count is 3. The summary is matched by its text since
        # its glyph (└) collides with the twoline subagent continuation glyph.
        shown_agent_labels = [i for i in range(9) if any(f'agent-{i}' in t for t in texts)]
        assert shown_agent_labels == [0, 1, 2, 3, 4, 5]
        assert any('+3 hidden' in t for t in texts)
        assert sum(1 for t in texts if GLYPH_WF_HEADER in t) == 1
        assert sum(1 for t in texts if GLYPH_WF_SUMMARY in t and 'agents' in t and 'done' in t) == 1

    def test_run_cap_emits_two_blocks_and_more_workflows(self, strip_ansi):
        # setup: 3 visible runs; cap is 2 -> one '+1 more workflows' row
        now  = time.time()
        view = _view()
        runs = [
            RunningWorkflow(
                run_id = f'wf_{i}', name = f'wf_{i}', phase = '',
                agents = [_make_workflow_subagent(f'a{i}', mtime=now - i)],
            )
            for i in range(3)
        ]
        self._inject(view, runs)

        # run
        rows  = layout.build_workflow_rows(view, 80, _r, per_agent=False)
        texts = [strip_ansi(row.content) for row in rows]

        # assert: two run blocks (header+summary each), ordered newest first, + overflow row
        header_rows  = [t for t in texts if GLYPH_WF_HEADER in t]
        summary_rows = [t for t in texts if GLYPH_WF_SUMMARY in t and 'agents' in t and 'done' in t]
        assert len(header_rows) == 2
        assert len(summary_rows) == 2
        assert any('+1 more workflows' in t for t in texts)
        # wf_0 is newest (mtime now - 0), wf_1 next; wf_2 overflows.
        assert 'wf_0' in header_rows[0]
        assert 'wf_1' in header_rows[1]
