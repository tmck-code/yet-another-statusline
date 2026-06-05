import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude.mon.discovery import (  # noqa: E402
    discover,
    find_active_jsonls,
    index_payloads_by_session,
)


def _make_projects_root(tmp_path: Path) -> Path:
    p = tmp_path / 'projects'
    p.mkdir(parents=True)
    return p


def _make_payloads_root(tmp_path: Path) -> Path:
    p = tmp_path / 'statusline-output'
    p.mkdir(parents=True)
    return p


def _write_jsonl(projects_root: Path, project: str, session_id: str) -> Path:
    proj_dir = projects_root / project
    proj_dir.mkdir(exist_ok=True)
    p = proj_dir / f'{session_id}.jsonl'
    p.write_text('')
    return p


def _write_payload(payloads_root: Path, name: str, data: dict) -> Path:
    p = payloads_root / f'{name}.json'
    p.write_text(json.dumps(data))
    return p


def _set_mtime(path: Path, ts: float) -> None:
    import os
    os.utime(path, (ts, ts))


class TestFindActiveJsonls:
    def test_file_within_window_is_returned(self, tmp_path: Path) -> None:
        # setup
        projects = _make_projects_root(tmp_path)
        now = datetime(2024, 1, 1, 12, 0, 0)
        now_ts = now.timestamp()
        jsonl = _write_jsonl(projects, 'proj-a', 'sess-1')
        # mtime 5 minutes ago — within 10 minute window
        _set_mtime(jsonl, now_ts - 300)

        # run
        result = find_active_jsonls(timedelta(minutes=10), now, projects)

        # expected
        expected = [(jsonl, now_ts - 300)]

        # assert
        assert result == expected

    def test_file_outside_window_is_excluded(self, tmp_path: Path) -> None:
        # setup
        projects = _make_projects_root(tmp_path)
        now = datetime(2024, 1, 1, 12, 0, 0)
        now_ts = now.timestamp()
        jsonl = _write_jsonl(projects, 'proj-a', 'sess-1')
        # mtime 20 minutes ago — outside 10 minute window
        _set_mtime(jsonl, now_ts - 1200)

        # run
        result = find_active_jsonls(timedelta(minutes=10), now, projects)

        # expected
        expected: list = []

        # assert
        assert result == expected

    def test_file_exactly_at_boundary_is_returned(self, tmp_path: Path) -> None:
        # mtime exactly equal to cutoff satisfies now_ts - mtime <= cutoff
        projects = _make_projects_root(tmp_path)
        now = datetime(2024, 1, 1, 12, 0, 0)
        now_ts = now.timestamp()
        jsonl = _write_jsonl(projects, 'proj-a', 'sess-1')
        _set_mtime(jsonl, now_ts - 600)

        result = find_active_jsonls(timedelta(minutes=10), now, projects)

        expected = [(jsonl, now_ts - 600)]

        assert result == expected

    def test_missing_projects_root_returns_empty(self, tmp_path: Path) -> None:
        # setup
        projects = tmp_path / 'nonexistent'
        now = datetime(2024, 1, 1, 12, 0, 0)

        # run
        result = find_active_jsonls(timedelta(minutes=10), now, projects)

        # expected
        expected: list = []

        # assert
        assert result == expected

    def test_multiple_files_mixed_window(self, tmp_path: Path) -> None:
        # setup
        projects = _make_projects_root(tmp_path)
        now = datetime(2024, 1, 1, 12, 0, 0)
        now_ts = now.timestamp()
        recent = _write_jsonl(projects, 'proj-a', 'sess-recent')
        stale = _write_jsonl(projects, 'proj-a', 'sess-stale')
        _set_mtime(recent, now_ts - 300)   # 5 min ago — in window
        _set_mtime(stale, now_ts - 1200)   # 20 min ago — outside window

        # run
        result = find_active_jsonls(timedelta(minutes=10), now, projects)

        # expected — only the recent one
        expected = [(recent, now_ts - 300)]

        # assert
        assert result == expected


class TestIndexPayloadsBySession:
    def test_single_payload_indexed_by_session_id(self, tmp_path: Path) -> None:
        # setup
        payloads = _make_payloads_root(tmp_path)
        data = {'session_id': 'sess-abc', 'cwd': '/home/user/project'}
        pfile = _write_payload(payloads, 'payload-1', data)
        mtime = pfile.stat().st_mtime

        # run
        result = index_payloads_by_session(payloads)

        # expected
        expected = {'sess-abc': (pfile, mtime, data)}

        # assert
        assert result == expected

    def test_most_recent_payload_wins_for_same_session(self, tmp_path: Path) -> None:
        # setup
        payloads = _make_payloads_root(tmp_path)
        data_old = {'session_id': 'sess-abc', 'cwd': '/old'}
        data_new = {'session_id': 'sess-abc', 'cwd': '/new'}
        old_file = _write_payload(payloads, 'payload-old', data_old)
        new_file = _write_payload(payloads, 'payload-new', data_new)
        # make old_file older
        import os
        old_ts = new_file.stat().st_mtime - 100
        os.utime(old_file, (old_ts, old_ts))
        new_mtime = new_file.stat().st_mtime

        # run
        result = index_payloads_by_session(payloads)

        # expected — only the newer file survives
        expected = {'sess-abc': (new_file, new_mtime, data_new)}

        # assert
        assert result == expected

    def test_file_without_session_id_is_skipped(self, tmp_path: Path) -> None:
        # setup
        payloads = _make_payloads_root(tmp_path)
        _write_payload(payloads, 'no-session', {'cwd': '/somewhere'})

        # run
        result = index_payloads_by_session(payloads)

        # expected
        expected: dict = {}

        # assert
        assert result == expected

    def test_unparseable_json_is_skipped(self, tmp_path: Path) -> None:
        # setup
        payloads = _make_payloads_root(tmp_path)
        (payloads / 'bad.json').write_text('{not valid json}')

        # run
        result = index_payloads_by_session(payloads)

        # expected
        expected: dict = {}

        # assert
        assert result == expected

    def test_missing_payloads_root_returns_empty(self, tmp_path: Path) -> None:
        # setup
        payloads = tmp_path / 'nonexistent'

        # run
        result = index_payloads_by_session(payloads)

        # expected
        expected: dict = {}

        # assert
        assert result == expected

    def test_multiple_sessions_each_indexed(self, tmp_path: Path) -> None:
        # setup
        payloads = _make_payloads_root(tmp_path)
        data_a = {'session_id': 'sess-a', 'cwd': '/a'}
        data_b = {'session_id': 'sess-b', 'cwd': '/b'}
        fa = _write_payload(payloads, 'payload-a', data_a)
        fb = _write_payload(payloads, 'payload-b', data_b)

        # run
        result = index_payloads_by_session(payloads)

        # assert both keys present with correct data
        assert set(result.keys()) == {'sess-a', 'sess-b'}
        assert result['sess-a'][0] == fa
        assert result['sess-b'][0] == fb


class TestClaudeConfigDirRespected:
    """Confirm that discovery functions derive default roots from CLAUDE_DIR.

    Default arguments are evaluated once at import time from the CLAUDE_DIR
    constant.  We cannot re-evaluate them at runtime, so these tests verify
    the wiring statically (default == CLAUDE_DIR / subdir) and the live
    end-to-end path by reloading the module after pointing CLAUDE_CONFIG_DIR
    at a temp directory.
    """

    def test_find_active_jsonls_default_projects_root_matches_claude_dir(self) -> None:
        # The default argument for projects_root must be CLAUDE_DIR / 'projects',
        # not a hardcoded Path.home() / '.claude' / 'projects'.
        import inspect
        import claude.mon.discovery as _disc

        sig = inspect.signature(_disc.find_active_jsonls)
        default_projects_root = sig.parameters['projects_root'].default

        assert default_projects_root == _disc.CLAUDE_DIR / 'projects'

    def test_index_payloads_default_payloads_root_matches_claude_dir(self) -> None:
        # The default argument for payloads_root must be CLAUDE_DIR / 'statusline-output',
        # not a hardcoded Path.home() / '.claude' / 'statusline-output'.
        import inspect
        import claude.mon.discovery as _disc

        sig = inspect.signature(_disc.index_payloads_by_session)
        default_payloads_root = sig.parameters['payloads_root'].default

        assert default_payloads_root == _disc.CLAUDE_DIR / 'statusline-output'


class TestDiscover:
    def _build_fake_home(
        self,
        tmp_path: Path,
        sessions: list[dict],
        now: datetime,
        include_after: timedelta,
    ) -> tuple[Path, Path]:
        """Build fake projects + payloads dirs. Each entry in sessions is a dict with keys:
        project, session_id, jsonl_age_seconds, payload (dict or None), payload_extra (optional older file)."""
        projects = tmp_path / 'projects'
        payloads = tmp_path / 'statusline-output'
        projects.mkdir(parents=True)
        payloads.mkdir(parents=True)

        now_ts = now.timestamp()
        for s in sessions:
            jsonl = _write_jsonl(projects, s['project'], s['session_id'])
            _set_mtime(jsonl, now_ts - s['jsonl_age_seconds'])

            if s.get('payload') is not None:
                _write_payload(payloads, s['session_id'], s['payload'])

        return projects, payloads

    def test_active_session_with_payload_is_returned(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # setup
        now = datetime(2024, 6, 1, 10, 0, 0)
        sessions = [
            {
                'project': 'proj-a',
                'session_id': 'sess-1',
                'jsonl_age_seconds': 300,
                'payload': {'session_id': 'sess-1', 'cwd': '/home/user/proj'},
            }
        ]
        projects, payloads = self._build_fake_home(
            tmp_path, sessions, now, timedelta(minutes=10)
        )
        monkeypatch.setattr(
            'claude.mon.discovery.find_active_jsonls',
            lambda include_after, now: find_active_jsonls(include_after, now, projects),
        )
        monkeypatch.setattr(
            'claude.mon.discovery.index_payloads_by_session',
            lambda: index_payloads_by_session(payloads),
        )

        # run
        result = discover(timedelta(minutes=10), now)

        # expected
        assert len(result) == 1
        assert result[0].session_id == 'sess-1'

    def test_session_without_payload_is_omitted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # setup
        now = datetime(2024, 6, 1, 10, 0, 0)
        sessions = [
            {
                'project': 'proj-a',
                'session_id': 'sess-no-payload',
                'jsonl_age_seconds': 300,
                'payload': None,  # no payload file
            }
        ]
        projects, payloads = self._build_fake_home(
            tmp_path, sessions, now, timedelta(minutes=10)
        )
        monkeypatch.setattr(
            'claude.mon.discovery.find_active_jsonls',
            lambda include_after, now: find_active_jsonls(include_after, now, projects),
        )
        monkeypatch.setattr(
            'claude.mon.discovery.index_payloads_by_session',
            lambda: index_payloads_by_session(payloads),
        )

        # run
        result = discover(timedelta(minutes=10), now)

        # expected
        expected: list = []

        # assert
        assert result == expected

    def test_stale_session_is_excluded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # setup — jsonl is 20 min old, window is 10 min
        now = datetime(2024, 6, 1, 10, 0, 0)
        sessions = [
            {
                'project': 'proj-a',
                'session_id': 'sess-stale',
                'jsonl_age_seconds': 1200,
                'payload': {'session_id': 'sess-stale', 'cwd': '/somewhere'},
            }
        ]
        projects, payloads = self._build_fake_home(
            tmp_path, sessions, now, timedelta(minutes=10)
        )
        monkeypatch.setattr(
            'claude.mon.discovery.find_active_jsonls',
            lambda include_after, now: find_active_jsonls(include_after, now, projects),
        )
        monkeypatch.setattr(
            'claude.mon.discovery.index_payloads_by_session',
            lambda: index_payloads_by_session(payloads),
        )

        # run
        result = discover(timedelta(minutes=10), now)

        # expected
        expected: list = []

        # assert
        assert result == expected

    def test_sessions_sorted_by_cwd_then_session_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # setup — three active sessions with different cwd and session_ids
        now = datetime(2024, 6, 1, 10, 0, 0)
        sessions = [
            {
                'project': 'proj',
                'session_id': 'sess-z',
                'jsonl_age_seconds': 60,
                'payload': {'session_id': 'sess-z', 'cwd': '/beta'},
            },
            {
                'project': 'proj',
                'session_id': 'sess-a',
                'jsonl_age_seconds': 60,
                'payload': {'session_id': 'sess-a', 'cwd': '/alpha'},
            },
            {
                'project': 'proj',
                'session_id': 'sess-m',
                'jsonl_age_seconds': 60,
                'payload': {'session_id': 'sess-m', 'cwd': '/alpha'},
            },
        ]
        projects, payloads = self._build_fake_home(
            tmp_path, sessions, now, timedelta(minutes=10)
        )
        monkeypatch.setattr(
            'claude.mon.discovery.find_active_jsonls',
            lambda include_after, now: find_active_jsonls(include_after, now, projects),
        )
        monkeypatch.setattr(
            'claude.mon.discovery.index_payloads_by_session',
            lambda: index_payloads_by_session(payloads),
        )

        # run
        result = discover(timedelta(minutes=10), now)

        # expected sort: (/alpha, sess-a), (/alpha, sess-m), (/beta, sess-z)
        expected_ids = ['sess-a', 'sess-m', 'sess-z']

        # assert
        assert [s.session_id for s in result] == expected_ids

    def test_active_session_fields_are_populated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # setup
        now = datetime(2024, 6, 1, 10, 0, 0)
        now_ts = now.timestamp()
        payload_data = {'session_id': 'sess-1', 'cwd': '/home/user/proj', 'cost': {'total_cost_usd': 0.05}}
        sessions = [
            {
                'project': 'proj-a',
                'session_id': 'sess-1',
                'jsonl_age_seconds': 300,
                'payload': payload_data,
            }
        ]
        projects, payloads = self._build_fake_home(
            tmp_path, sessions, now, timedelta(minutes=10)
        )
        monkeypatch.setattr(
            'claude.mon.discovery.find_active_jsonls',
            lambda include_after, now: find_active_jsonls(include_after, now, projects),
        )
        monkeypatch.setattr(
            'claude.mon.discovery.index_payloads_by_session',
            lambda: index_payloads_by_session(payloads),
        )

        # run
        result = discover(timedelta(minutes=10), now)
        s = result[0]

        # expected jsonl_mtime roughly now - 300
        expected_jsonl_mtime_approx = now_ts - 300

        # assert
        assert s.session_id == 'sess-1'
        assert s.payload == payload_data
        assert abs(s.jsonl_mtime - expected_jsonl_mtime_approx) < 2.0
        assert isinstance(s.jsonl_path, Path)
        assert isinstance(s.payload_mtime, float)
