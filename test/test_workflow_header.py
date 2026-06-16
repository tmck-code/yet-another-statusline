"""Tests for the workflow run-header phase-trail rendering (Section 5 of the
``improve-workflow-display`` change): the inline dot-separated phase trail with
the current phase highlighted, the all-dimmed live-run form, and the fallback to
the ``[<phase>]`` bracket style when no phase list is known."""
import yas.renderer as renderer_mod
from yas.constants import GLYPH_WF_CURRENT, GLYPH_WF_HEADER
from yas.info.workflows import RunningWorkflow


_r = renderer_mod.Renderer()


class TestWorkflowHeaderPhaseTrail:

    def test_phase_list_highlights_current_dims_rest(self, strip_ansi):
        # 5.6 — a known phase list renders the trail inline, current phase
        # highlighted (SKILLS colour + ❯ marker), the rest in CTX_DIM.
        # setup
        run = RunningWorkflow(
            run_id = 'wf_x',
            name   = 'my-workflow',
            phase  = 'Scan',
            phases = ['Discover', 'Scan', 'Verify'],
        )

        # run
        raw   = _r.workflow_header(run, 120)
        plain = strip_ansi(raw)

        # assert — plain trail and marker placement
        assert GLYPH_WF_HEADER in plain
        assert 'my-workflow' in plain
        assert 'Discover' in plain and 'Scan' in plain and 'Verify' in plain
        assert f'{GLYPH_WF_CURRENT}Scan' in plain        # marker prefixes the current phase
        assert f'{GLYPH_WF_CURRENT}Discover' not in plain  # not the inactive ones
        assert f'{GLYPH_WF_CURRENT}Verify' not in plain

        # assert — current phase carries the SKILLS colour, others CTX_DIM
        assert f'{_r.SKILLS}{GLYPH_WF_CURRENT}Scan{_r.R}' in raw
        assert f'{_r.CTX_DIM}Discover{_r.R}' in raw
        assert f'{_r.CTX_DIM}Verify{_r.R}' in raw

    def test_empty_phase_dims_all_with_no_marker(self, strip_ansi):
        # 5.3 — a live run (empty run.phase) dims every phase, no ❯ marker.
        # setup
        run = RunningWorkflow(
            run_id = 'wf_x',
            name   = 'my-workflow',
            phase  = '',
            phases = ['Discover', 'Scan', 'Verify'],
        )

        # run
        raw   = _r.workflow_header(run, 120)
        plain = strip_ansi(raw)

        # assert
        assert GLYPH_WF_CURRENT not in plain
        for title in ('Discover', 'Scan', 'Verify'):
            assert f'{_r.CTX_DIM}{title}{_r.R}' in raw
        # nothing should be painted in the SKILLS colour except the run name
        assert f'{_r.SKILLS}{GLYPH_WF_CURRENT}' not in raw

    def test_no_phase_list_falls_back_to_bracket_style(self, strip_ansi):
        # 5.7 — empty phases but a set phase keeps the legacy [<phase>] form.
        # setup
        run = RunningWorkflow(
            run_id = 'wf_x',
            name   = 'my-workflow',
            phase  = 'Analyse',
            phases = [],
        )

        # run
        plain = strip_ansi(_r.workflow_header(run, 80))

        # assert
        assert GLYPH_WF_HEADER in plain
        assert 'my-workflow' in plain
        assert '[Analyse]' in plain
        assert GLYPH_WF_CURRENT not in plain
