from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime

from yas.config import Config
from yas.constants import (
    MIN_WIDTH, NARROW_WIDTH, MEDIUM_WIDTH, VERSION,
    config_path, session_payload_path, sessions_dir, version_file,
)
from yas.info import SessionView
from yas.info.parsecache import TranscriptCache
from yas.layout import build_narrow, build_medium, build_wide, render_layout
from yas.renderer import Renderer
from yas.session import RateLimits, SessionInfo, _as_str
from yas.render.text import terminal_width, apply_glyphs
from yas.themes import CLAUDE_DARK, THEMES, Theme
from yas.tokens import RenderTiming, TickRecord, TokenLog, TokenRate, compute_day_cost
from yas.info.transcript import TranscriptUsage


def _apply_rate_limit_sim(info: dict[str, object], cfg: Config, usage: TranscriptUsage) -> RateLimits:
    """Overwrite info['rate_limits'] with synthesised buckets per cfg.rate_limit_rules,
    and return the same buckets as a `RateLimits` so the caller can also thread them
    onto the `SessionInfo` the renderer actually reads.

    Mutates `info` in place, before it is written to the per-session payload
    (see `main`), so the statusline and the `mon` TUI read the same
    already-synthesised values rather than deriving them independently. Returning
    the `RateLimits` (rather than making the caller re-derive it from `info`) keeps
    there being exactly one synthesis call per render.

    `usage` is the session's lifetime transcript totals (input,
    cache_creation, cache_read, output), summed once by `TranscriptUsage.
    from_session` (main thread + every subagent transcript -- see that
    method's docstring) and threaded in by the caller -- NOT re-derived from
    the raw payload's context_window totals, which are only the most recent
    request's composition (a context-size gauge, not a lifetime sum; see
    RateLimitLog's docstring for why that distinction matters). The caller
    is responsible for parsing the transcript exactly once per render and
    handing the result here as well as into SessionView, rather than this
    function parsing it again.

    NOTE: switching this call site from `from_transcript` (main-only) to
    `from_session` (main + subagents) raises every session's reported
    cumulative usage several-fold on coordinator-heavy sessions (measured
    3-4x billed-input on one real session) -- any `budget`/threshold already
    tuned against the old main-only numbers in `[rate_limits]` config needs
    recalibrating after this change.
    """
    from yas.rate_limits_sim import simulate_rate_limits
    session_id = _as_str(info.get('session_id')) or 'unknown'
    rl_raw = info.get('rate_limits')
    real   = RateLimits.from_dict(rl_raw if isinstance(rl_raw, dict) else {})
    synth  = simulate_rate_limits(
        session_id, cfg.rate_limit_rules, real,
        usage.input_tokens, usage.cache_creation_input_tokens, usage.cache_read_input_tokens, usage.output_tokens,
        weights=cfg.rate_limit_weights,
    )
    info['rate_limits'] = {
        'five_hour': {'used_percentage': synth.five_hour.used_percentage, 'resets_at': synth.five_hour.resets_at},
        'seven_day': {'used_percentage': synth.seven_day.used_percentage, 'resets_at': synth.seven_day.resets_at},
    }
    return synth


def record_tick(session: SessionInfo, usage: TranscriptUsage) -> TickRecord:
    today     = datetime.now().strftime('%Y-%m-%d')
    token_log = TokenLog.update(session.session_id, today, usage.billed_in, usage.cache_read, usage.out)
    tok_rate  = TokenRate.update(session.session_id, usage.billed_in, usage.out)
    day_cost  = compute_day_cost(session.model, token_log)
    return TickRecord(token_log=token_log, day_cost=day_cost, tok_rate=tok_rate)


def resolve_theme(cli_name: str | None) -> Theme:
    """Layered theme selection: CLI -> YAS_THEME -> CLAUDE_STATUSLINE_THEME
    -> [appearance].theme -> CLAUDE_DARK.

    Resolves live (fresh Config.load) so callers see the current environment and
    CLAUDE_DIR; the import-time CONFIG singleton is for the module constants."""
    if cli_name and cli_name in THEMES:
        return THEMES[cli_name]
    return THEMES.get(Config.load().theme, CLAUDE_DARK)


def render(session_info: dict[str, object], width: int, *, bg_shift: str = 'warm', theme: Theme | None = None, glyph_mode: str | None = None, single_width: bool | None = None, timing: str = '', view: SessionView | None = None) -> str:
    """`view`, when supplied, is an already-constructed SessionView -- used by
    `main` so the transcript it lazily parses (`view.transcript_usage`) is
    reused rather than parsed again here; external callers (tests, `mon`)
    leave it None and get a fresh SessionInfo/Config/SessionView built from
    `session_info` as before."""
    if width < MIN_WIDTH:
        return ''
    session     = view.session if view is not None else SessionInfo.from_dict(session_info)
    r           = Renderer(bg_shift=bg_shift, theme=theme)
    cfg         = view.cfg if view is not None else Config.load()
    parse_cache = view.parse_cache if view is not None else (TranscriptCache.load(session.session_id) if cfg.transcript_cache else None)
    if glyph_mode is None:
        glyph_mode = cfg.glyph_mode
    if single_width is None:
        single_width = cfg.single_width
    soft_limit = cfg.soft_limit_for(session.model.id, session.model.display_name)
    if view is None:
        view = SessionView(session, cfg, cache=parse_cache)
    if width < NARROW_WIDTH:
        spec = build_narrow(view, width, r, soft_limit)
    elif width < MEDIUM_WIDTH:
        spec = build_medium(view, width, r, soft_limit)
    else:
        tick = record_tick(session, view.transcript_usage)
        spec = build_wide(view, tick, width, r, soft_limit)
    # The bottom-right border annotation: the version tag always (bold,
    # grey→muted-grey gradient), preceded by the previous run's wall-clock
    # when the show_render_time knob supplies it (`…47.2ms v0.6.2──╯`).
    out = '\n'.join(render_layout(spec, r, timing, f'v{VERSION}'))
    if parse_cache is not None:
        parse_cache.save()
    return apply_glyphs(out, glyph_mode, single_width)


def arm_watchdog(seconds: float) -> None:
    '''Hard-exit the process after `seconds`, even while blocked reading stdin.'''
    # os._exit, not sys.exit: it must work from a non-main thread and must not
    # flush a half-built render onto stdout. Never call from `main` itself --
    # tests call `main` in-process and the timer would kill pytest.
    timer = threading.Timer(seconds, os._exit, args=(0,))
    timer.daemon = True
    timer.start()


def main(t0: float | None = None) -> None:
    # Wall-clock start for the bottom-border run-time annotation. The entry
    # shim passes a perf_counter() stamped before importing the app so the
    # measured duration covers import cost too; a None default keeps `main`
    # callable bare (tests) by stamping here instead.
    if t0 is None:
        t0 = time.perf_counter()
    # Force UTF-8 on stdout so the script renders correctly on Windows
    # (cp1252 default codec can't encode box-drawing or Nerd Font glyphs,
    # crashes with UnicodeEncodeError on the first border char). Python's
    # PEP 540 UTF-8 mode and PYTHONIOENCODING env var both fix this from
    # the outside; reconfiguring stdout here removes the requirement that
    # callers set either. No-op on platforms whose default codec is
    # already UTF-8 (most Unix systems since Python 3.7).
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    # Lazy one-time migration to the yas/{cache,state}/ layout. The `stat()`
    # here is the whole steady-state cost once migrated; the import stays
    # inside the guard so it's never paid on the hot path after that.
    # REMOVE AFTER 0.11.0
    if not version_file().exists():
        from yas.migrate import migrate
        migrate()
    # Resolve config live so a freshly-set env var (e.g. YAS_FULL_WIDTH) or an
    # edited yas.toml takes effect on this invocation; CLI flags are top priority.
    cfg      = Config.load(argv=sys.argv[1:], config_dir=config_path().parent)
    bg_shift = cfg.bg_shift
    theme    = THEMES.get(cfg.theme, CLAUDE_DARK)

    info = json.loads(sys.stdin.read())
    # A SessionView is only built here (ahead of `render`) when the rate-limit
    # simulator needs its transcript_usage -- building it unconditionally
    # would force a transcript parse on every render, including narrow/medium
    # layouts that otherwise never touch the transcript. When built, it's
    # threaded into `render` below (`view=view`) so that one parse -- paid by
    # `view.transcript_usage` here -- is reused for both the simulator and
    # the normal session view, instead of `render` parsing the transcript
    # again from scratch. `_apply_rate_limit_sim` only mutates `info` (the raw
    # dict written to the payload below); the synthesised buckets it returns
    # are reattached to `view.session` here too, since `view.session` was
    # already snapshotted from the pre-synthesis `info` and `render` reads
    # `view.session.rate_limits` directly -- without this, the renderer would
    # see the all-zero real buckets and draw the "unlimited" glyph instead of
    # the synthesised percentage.
    view: SessionView | None = None
    if cfg.rate_limit_rules:
        session     = SessionInfo.from_dict(info)
        parse_cache = TranscriptCache.load(session.session_id) if cfg.transcript_cache else None
        view        = SessionView(session, cfg, cache=parse_cache)
        session.rate_limits = _apply_rate_limit_sim(info, cfg, view.rate_limit_usage)

    # Write payload so the multi-session observer can index it. Keyed by
    # session_id and overwritten in place under yas/state/sessions/, so the
    # dir holds one file per session rather than one per render tick. The
    # observer already collapses to the newest payload per session
    # (mon/discovery.index_payloads_by_session), so the old timestamped
    # filenames only ever accumulated dead weight.
    session_id = _as_str(info.get('session_id')) or 'unknown'
    try:
        sessions_dir().mkdir(parents=True, exist_ok=True)
        session_payload_path(session_id).write_text(json.dumps(info))
    except OSError:
        pass

    # Previous run's wall-clock, shown in the bottom-right border when the
    # show_render_time knob is on (off by default). A run can't know its own
    # total before it has drawn, so each run displays the last one's value
    # (absent on the very first render of a session). When off, the cache is
    # never touched and `timing` stays empty — i.e. as if the feature did not
    # exist.
    timing = ''
    if cfg.show_render_time:
        prev_ms = RenderTiming.read(session_id)
        timing  = f'{prev_ms:.1f}ms' if prev_ms is not None else ''

    raw_tw = terminal_width()
    if raw_tw < MIN_WIDTH:
        return
    if cfg.full_width:
        width = max(MIN_WIDTH, raw_tw - 6)
    else:
        width = max(MIN_WIDTH, min(cfg.max_width, raw_tw - 6))

    sys.stdout.write(render(info, width, bg_shift=bg_shift, theme=theme, glyph_mode=cfg.glyph_mode, single_width=cfg.single_width, timing=timing, view=view))
    if cfg.show_render_time:
        RenderTiming.write(session_id, (time.perf_counter() - t0) * 1000.0)
