"""Tests for RunningSubagents.from_session."""
import json
import os
import time

import statusline_command as sl


SESSION_ID = 'sess-abc'
PROJECT_DIR = '/home/user/myproject'
# slug: '/home/user/myproject' → '-home-user-myproject' → 'home-user-myproject'
PROJECT_SLUG = 'home-user-myproject'


def _subagents_dir(tmp_home):
    return tmp_home / '.claude' / 'projects' / f'-{PROJECT_SLUG}' / SESSION_ID / 'subagents'


def _write_agent(subagents_dir, agent_id, agent_type='Explore', description='find X', mtime=None):
    subagents_dir.mkdir(parents=True, exist_ok=True)
    meta = subagents_dir / f'{agent_id}.meta.json'
    meta.write_text(json.dumps({'agentType': agent_type, 'description': description}))
    jsonl = subagents_dir / f'{agent_id}.jsonl'
    jsonl.write_text('{"event": "start"}\n')
    if mtime is not None:
        os.utime(jsonl, (mtime, mtime))
    return meta, jsonl


def test_missing_directory_returns_empty(tmp_home):
    """9.2 Missing subagents directory returns empty RunningSubagents."""
    result = sl.RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    assert result == sl.RunningSubagents(subagents=[])


def test_fresh_entry_included(tmp_home, monkeypatch):
    """9.3 Fresh meta + jsonl entry is included in the result."""
    now = time.time()
    sdir = _subagents_dir(tmp_home)
    _write_agent(sdir, 'agent-1', agent_type='Explore', description='find X', mtime=now)

    result = sl.RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    assert ('Explore', 'find X') in result.subagents


def test_stale_entry_excluded(tmp_home):
    """9.4 Stale jsonl (mtime > STALE_SECONDS ago) is excluded."""
    now = time.time()
    stale_mtime = now - sl.RunningSubagents.STALE_SECONDS - 1
    sdir = _subagents_dir(tmp_home)
    _write_agent(sdir, 'agent-stale', mtime=stale_mtime)

    result = sl.RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    assert result.subagents == []


def test_project_dir_with_leading_slash_produces_correct_slug(tmp_home):
    """9.5 project_dir with leading '/' produces the right -<slug> prefix."""
    now = time.time()
    # '/home/user/myproject' → replace '/' with '-' → '-home-user-myproject'
    # strip leading '-' → 'home-user-myproject'
    # stored under .claude/projects/-home-user-myproject/
    sdir = _subagents_dir(tmp_home)
    _write_agent(sdir, 'agent-2', mtime=now)

    result = sl.RunningSubagents.from_session(SESSION_ID, PROJECT_DIR)
    assert len(result.subagents) == 1
