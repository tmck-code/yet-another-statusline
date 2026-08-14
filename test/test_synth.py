"""Tests for ops/synth.py — world-building primitives for synthetic session fixtures."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'ops'))

from synth import (
    build_synthetic_env,
    write_transcript,
    write_subagents,
)


class TestBuildSyntheticEnv:
    """Environment builder creates expected tree and git repo."""

    def test_creates_expected_directory_structure(self):
        """build_synthetic_env creates .claude/ and my-project/ dirs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            session_id = 'test-session-123'

            build_synthetic_env(tmpdir_path, session_id)

            # Check .claude structure
            claude_dir = tmpdir_path / '.claude'
            assert (claude_dir / 'projects' / session_id).exists()
            assert (claude_dir / 'settings.json').exists()
            assert (claude_dir / 'statusline-tokens.log').exists()

            # Check my-project structure
            project_dir = tmpdir_path / 'my-project'
            assert (project_dir / 'README.md').exists()
            assert (project_dir / 'src' / 'main.py').exists()
            assert (project_dir / 'src' / 'utils.py').exists()

    def test_initializes_git_repo(self):
        """build_synthetic_env creates a git repo on 'demo' branch."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            session_id = 'test-session-456'

            build_synthetic_env(tmpdir_path, session_id)

            project_dir = tmpdir_path / 'my-project'
            # Check for .git directory
            assert (project_dir / '.git').is_dir()
            # Check for demo branch head
            assert (project_dir / '.git' / 'refs' / 'heads' / 'demo').exists()


class TestWriteTranscript:
    """Transcript writer parses into expected usage totals."""

    def test_write_transcript_without_tasks(self):
        """write_transcript without tasks produces valid JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            transcript_path = Path(tmpdir) / 'test.jsonl'

            write_transcript(
                transcript_path,
                skills=['skill1', 'skill2'],
                total_in=1000,
                total_cc=200,
                total_cr=3000,
                total_out=500,
            )

            # Parse the output
            lines = transcript_path.read_text().strip().split('\n')
            assert len(lines) == 2  # Two skill entries

            entries = [json.loads(line) for line in lines]
            for entry in entries:
                assert entry['type'] == 'assistant'
                assert 'message' in entry
                assert 'usage' in entry['message']

    def test_write_transcript_with_task_durations(self):
        """write_transcript with tasks and task_durations produces task messages."""
        with tempfile.TemporaryDirectory() as tmpdir:
            transcript_path = Path(tmpdir) / 'test.jsonl'
            tasks = [
                ('First task', 'Doing first task', 'completed'),
                ('Second task', 'Doing second task', 'in_progress'),
            ]

            write_transcript(
                transcript_path,
                skills=[],
                total_in=1000,
                total_cc=200,
                total_cr=3000,
                total_out=500,
                tasks=tasks,
                task_durations=(30.0, 60.0),
                task_live_seconds=45.0,
            )

            lines = transcript_path.read_text().strip().split('\n')
            entries = [json.loads(line) for line in lines]

            # Should have: empty skills entry (n=1 with no skills), TaskCreate, TaskUpdates
            assert len(entries) > 1
            # Check for TaskCreate
            task_creates = [e for e in entries if 'content' in e.get('message', {})
                           for c in e['message'].get('content', [])
                           if c.get('name') == 'TaskCreate']
            assert len(task_creates) > 0


class TestWriteSubagents:
    """Subagent writer clears stale files and emits recognized records."""

    def test_write_subagents_clears_stale_files(self):
        """write_subagents clears stale regular files before writing."""
        import re
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            session_id = 'test-session-789'
            project_dir = tmpdir_path / 'my-project'
            claude_dir = tmpdir_path / '.claude'

            # Create the structure
            build_synthetic_env(tmpdir_path, session_id)

            # Compute the actual project slug like write_subagents does
            project_slug = re.sub(r'[^A-Za-z0-9]', '-', str(project_dir))
            subagents_dir = claude_dir / 'projects' / project_slug / session_id / 'subagents'
            subagents_dir.mkdir(parents=True, exist_ok=True)
            stale_file = subagents_dir / 'old-stale-agent.jsonl'
            stale_file.write_text('stale content\n')

            # Write new subagents
            write_subagents(
                claude_dir,
                session_id,
                project_dir,
                [('claude', 'Test agent', 1000, 100)],
            )

            # Stale file should be gone
            assert not stale_file.exists()
            # New file should exist
            new_files = list(subagents_dir.glob('*.jsonl'))
            assert len(new_files) > 0

    def test_write_subagents_creates_meta_and_jsonl(self):
        """write_subagents emits meta.json and .jsonl pairs recognized by cohort reader."""
        import re
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            session_id = 'test-session-999'
            project_dir = tmpdir_path / 'my-project'
            claude_dir = tmpdir_path / '.claude'

            build_synthetic_env(tmpdir_path, session_id)

            write_subagents(
                claude_dir,
                session_id,
                project_dir,
                [
                    ('claude', 'First agent', 2000, 200),
                    ('general-purpose', 'Second agent', 1500, 150),
                ],
            )

            project_slug = re.sub(r'[^A-Za-z0-9]', '-', str(project_dir))
            subagents_dir = claude_dir / 'projects' / project_slug / session_id / 'subagents'

            # Check for meta + jsonl pairs
            meta_files = list(subagents_dir.glob('*.meta.json'))
            jsonl_files = list(subagents_dir.glob('*.jsonl'))

            assert len(meta_files) == 2
            assert len(jsonl_files) == 2

            # Verify meta files are valid JSON
            for meta_file in meta_files:
                data = json.loads(meta_file.read_text())
                assert 'agentType' in data
                assert 'description' in data
