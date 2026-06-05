"""Regression tests for the untrusted-input hardening change (SEC-1/SEC-2).

SEC-1 strips terminal control characters from every host-/repo-supplied string
at capture time (the OSC/CSI introducer ESC 0x1b and terminator BEL 0x07, all
of C0/C1, and DEL), so no untrusted escape can reach stdout. SEC-2 stops
reading a cloned repo's project_dir/.claude/settings.json for the plugins list.

Mirrors PR #35's test_security_hardening.py. Capture-layer assertions are the
primary guard (robust against layout/width changes); a handful of end-to-end
render() assertions confirm no OSC sequence survives into the rendered line.
"""
from __future__ import annotations

import json
from pathlib import Path

import yas.session as session
from yas.app import render
from yas.constants import _sanitize
from yas.info.git import GitInfo
from yas.info.skills import LoadedSkills
from yas.info.subagents import RunningSubagents
from yas.info.tasks import TaskList


# Attack payloads exactly as reproduced by the audit.
OSC52 = '\x1b]52;c;cGF5bG9hZA==\x07'   # clipboard-write hijack
OSC0  = '\x1b]0;PWNED\x07'              # window-title spoof


# ---------------------------------------------------------------------------
# 1.2 — focused unit tests for _sanitize
# ---------------------------------------------------------------------------

def test_sanitize_strips_esc_and_bel() -> None:
    """ESC (0x1b) and BEL (0x07) — the OSC/CSI delimiters — are removed."""
    assert _sanitize(OSC52) == ']52;c;cGF5bG9hZA=='
    assert _sanitize(OSC0) == ']0;PWNED'
    out = _sanitize('a\x1bb\x07c')
    assert '\x1b' not in out and '\x07' not in out
    assert out == 'abc'


def test_sanitize_strips_c0_c1_del() -> None:
    """Every C0 (sans TAB/LF), DEL (0x7f), and C1 (0x80-0x9f) byte is removed."""
    c0 = ''.join(chr(c) for c in range(0x00, 0x09)) + ''.join(chr(c) for c in range(0x0b, 0x20))
    c1 = ''.join(chr(c) for c in range(0x80, 0xa0))
    payload = f'x{c0}\x7f{c1}y'
    out = _sanitize(payload)
    assert out == 'xy'
    # Spot-check the bytes the spec calls out by name.
    for bad in ('\x00', '\x07', '\x1b', '\x7f', '\x9f'):
        assert bad not in out


def test_sanitize_preserves_tab_and_lf() -> None:
    """TAB (0x09) and LF (0x0a) are deliberately preserved."""
    assert _sanitize('a\tb\nc') == 'a\tb\nc'


def test_sanitize_leaves_printable_and_cjk_unchanged() -> None:
    """Printable ASCII and non-ASCII/CJK text pass through byte-for-byte."""
    for s in ('hello world', 'café', '世界', 'main', 'feature/x-1', '日本語テスト'):
        assert _sanitize(s) == s


# ---------------------------------------------------------------------------
# 4.1 — SEC-1 sinks: model display_name (OSC-52) and git branch (OSC-0)
# ---------------------------------------------------------------------------

def test_model_display_name_osc52_neutralized() -> None:
    """An OSC-52 payload in a model display_name is stripped at capture."""
    model = session.Model.from_dict({'id': 'claude-x', 'display_name': OSC52})
    assert '\x1b' not in model.display_name
    assert '\x07' not in model.display_name
    # The inert base64 text survives as plain characters; the escapes do not.
    assert model.display_name == ']52;c;cGF5bG9hZA=='


def _write_head(repo: Path, payload_branch: str) -> None:
    gitdir = repo / '.git'
    gitdir.mkdir(parents=True, exist_ok=True)
    (gitdir / 'HEAD').write_text(f'ref: refs/heads/{payload_branch}')


def test_git_branch_osc0_neutralized(tmp_path: Path) -> None:
    """An OSC-0 payload in a repo's .git/HEAD branch is stripped at capture."""
    repo = tmp_path / 'repo'
    repo.mkdir()
    _write_head(repo, OSC0)
    gi = GitInfo.from_cwd(str(repo))
    assert '\x1b' not in gi.branch
    assert '\x07' not in gi.branch
    assert gi.branch == ']0;PWNED'


def test_render_emits_no_osc_for_model_and_branch(tmp_home: Path, tmp_path: Path) -> None:
    """End-to-end: neither sink lets an OSC introducer/terminator reach stdout.

    Legitimate SGR uses the CSI form ESC '[' which is expected in the output;
    the attack uses the OSC form ESC ']' plus BEL, neither of which may survive.
    """
    repo = tmp_path / 'work'
    repo.mkdir()
    _write_head(repo, OSC0)
    payload = {
        'session_id': 'sec-1',
        'cwd': str(repo),
        'model': {'id': 'claude-x', 'display_name': OSC52},
        'workspace': {'current_dir': str(repo), 'project_dir': str(repo)},
    }
    out = render(payload, 160)
    assert '\x07' not in out          # BEL never legitimately appears
    assert '\x1b]' not in out         # no OSC introducer (SGR is ESC '[')
    assert '\x1b]52' not in out
    assert '\x1b]0;' not in out


# ---------------------------------------------------------------------------
# 4.2 — SEC-1 transcript sinks: task subject, subagent desc/tool-input, skill
# ---------------------------------------------------------------------------

def test_task_subject_control_bytes_stripped(tmp_path: Path) -> None:
    """Control bytes in a TaskCreate subject/activeForm are stripped."""
    transcript = tmp_path / 'transcript.jsonl'
    line = json.dumps({
        'timestamp': '2026-01-01T00:00:00Z',
        'message': {'content': [{
            'type': 'tool_use',
            'name': 'TaskCreate',
            # json.dumps escapes these to /; json.loads in the
            # reader turns them back into real control bytes before _sanitize.
            'input': {'subject': 'clean\x1bup\x07', 'activeForm': 'cleaning\x07'},
        }]},
    })
    transcript.write_text(line + '\n')
    tl = TaskList.from_session(str(transcript))
    assert len(tl.tasks) == 1
    t = tl.tasks[0]
    assert t.subject == 'cleanup'
    assert t.active_form == 'cleaning'
    assert '\x1b' not in t.subject and '\x07' not in t.subject
    assert '\x07' not in t.active_form


def test_subagent_desc_and_tool_input_control_bytes_stripped(tmp_home: Path) -> None:
    """Control bytes in a subagent's meta + tool-input are stripped at capture."""
    session_id = 'sec-2'
    project_dir = '/home/user/proj'
    # RunningSubagents slugs project_dir by replacing every non-alnum with '-'.
    slug = '-home-user-proj'
    sub_dir = tmp_home / '.claude' / 'projects' / slug / session_id / 'subagents'
    sub_dir.mkdir(parents=True, exist_ok=True)

    (sub_dir / 'a.meta.json').write_text(json.dumps({
        'agentType': 'explore\x07',
        'description': 'do \x1b]0;x\x07 stuff',
    }))
    (sub_dir / 'a.jsonl').write_text(json.dumps({
        'type': 'assistant',
        'timestamp': '2026-01-01T00:00:00Z',
        'message': {
            'id': 'm1',
            'model': 'claude-sonnet-4-6',
            'usage': {'input_tokens': 10, 'output_tokens': 2},
            'content': [{
                'type': 'tool_use',
                'name': 'Ba\x07sh',
                'input': {'command': 'echo \x1b]0;pwn\x07'},
            }],
        },
    }) + '\n')

    subs = RunningSubagents.from_session(session_id, project_dir)
    assert len(subs.subagents) == 1
    s = subs.subagents[0]
    assert s.agent_type == 'explore'
    assert s.description == 'do ]0;x stuff'
    assert '\x1b' not in s.description and '\x07' not in s.description
    kind, name, inp = s.last_activity
    assert kind == 'tool_use'
    assert name == 'Bash'
    assert inp['command'] == 'echo ]0;pwn'
    assert '\x1b' not in inp['command'] and '\x07' not in inp['command']


def test_skill_name_control_bytes_stripped(tmp_path: Path) -> None:
    """Control bytes in a captured skill name are stripped.

    The skills reader scans the raw transcript text with a regex (no JSON
    decode), so the line carries a literal control byte in the skill value.
    """
    transcript = tmp_path / 'transcript.jsonl'
    transcript.write_text('{"name":"Skill","input":{"skill":"my\x07sk\x1bill"}}\n')
    ls = LoadedSkills.from_transcript(str(transcript))
    assert ls.names == ['myskill']
    assert all('\x1b' not in n and '\x07' not in n for n in ls.names)


# ---------------------------------------------------------------------------
# 4.3 — SEC-1 no-op: legitimate plain/CJK values survive end-to-end
# ---------------------------------------------------------------------------

def test_legitimate_cjk_model_name_unchanged() -> None:
    """A CJK/non-ASCII display name is captured byte-for-byte (no over-strip)."""
    model = session.Model.from_dict({'id': 'claude-x', 'display_name': '世界 café'})
    assert model.display_name == '世界 café'


def test_render_preserves_legitimate_cjk(tmp_home: Path) -> None:
    """Legitimate non-ASCII text survives into the rendered line."""
    payload = {
        'session_id': 'noop-1',
        'cwd': '/home/user/proj',
        'model': {'id': 'claude-x', 'display_name': '世界café'},
        'workspace': {'current_dir': '/home/user/proj', 'project_dir': '/home/user/proj'},
    }
    out = render(payload, 160)
    assert '世界café' in out


# ---------------------------------------------------------------------------
# 4.4 — SEC-2: project_dir settings are ignored; the user's own still drive it
# ---------------------------------------------------------------------------

def test_sec2_project_settings_ignored_via_session(tmp_home: Path, tmp_path: Path) -> None:
    """A cloned repo's settings contribute nothing; the user's own still do.

    Exercised through SessionInfo.from_dict -> Workspace.plugins (the full
    capture path), distinct from test_workspace_plugins.py's direct-Workspace
    construction.
    """
    home_settings = tmp_home / '.claude' / 'settings.json'
    home_settings.parent.mkdir(parents=True, exist_ok=True)
    home_settings.write_text(json.dumps({'enabledPlugins': {'trusted@1.0': True}}))

    project_dir = tmp_path / 'cloned-repo'
    proj_settings = project_dir / '.claude' / 'settings.json'
    proj_settings.parent.mkdir(parents=True, exist_ok=True)
    proj_settings.write_text(json.dumps({'enabledPlugins': {'malicious@9.9': True}}))

    info = session.SessionInfo.from_dict({
        'workspace': {'current_dir': str(project_dir), 'project_dir': str(project_dir)},
    })
    names = info.plugin_names
    assert 'trusted' in names      # user's own config is read
    assert 'malicious' not in names  # cloned repo's config is not
