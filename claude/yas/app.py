from __future__ import annotations

import json
import sys
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
from yas.session import SessionInfo, _as_str
from yas.render.text import terminal_width, apply_glyphs
from yas.themes import CLAUDE_DARK, THEMES, Theme
from yas.tokens import RenderTiming, TickRecord, TokenLog, TokenRate, compute_day_cost
from yas.info.transcript import TranscriptUsage


def record_tick(session: SessionInfo, usage: TranscriptUsage) -> TickRecord:
    today     = datetime.now().strftime('%Y-%m-%d')
    token_log = TokenLog.update(session.session_id, today, usage.billed_in, usage.cache_read, usage.out)
    tok_rate  = TokenRate.update(session.session_id, usage.billed_in, usage.out)
    day_cost  = compute_day_cost(session.model, token_log)
    return TickRecord(token_log=token_log, day_cost=day_cost, tok_rate=tok_rate)


def resolve_theme(cli_name: str | None) -> Theme:
    """Layered theme selection: CLI -> YAS_THEME -> CLAUDE_STATUSLINE_THEME -> [appearance].theme -> CLAUDE_DARK."""
    if cli_name and cli_name in THEMES:
        return THEMES[cli_name]
    return THEMES.get(Config.load().theme, CLAUDE_DARK)


def render(session_info: dict[str, object], width: int, *, bg_shift: str = 'warm', theme: Theme | None = None, glyph_mode: str | None = None, single_width: bool | None = None, timing: str = '') -> str:
    if width < MIN_WIDTH:
        return ''
    session     = SessionInfo.from_dict(session_info)
    r           = Renderer(bg_shift=bg_shift, theme=theme)
    cfg         = Config.load()
    parse_cache = TranscriptCache.load(session.session_id) if cfg.transcript_cache else None
    if glyph_mode is None:
        glyph_mode = cfg.glyph_mode
    if single_width is None:
        single_width = cfg.single_width
    soft_limit = cfg.soft_limit_for(session.model.id, session.model.display_name)
    view       = SessionView(session, cfg, cache=parse_cache)
    if width < NARROW_WIDTH:
        spec = build_narrow(view, width, r, soft_limit)
    elif width < MEDIUM_WIDTH:
        spec = build_medium(view, width, r, soft_limit)
    else:
        tick = record_tick(session, view.transcript_usage)
        spec = build_wide(view, tick, width, r, soft_limit)
    out = '\n'.join(render_layout(spec, r, timing, f'v{VERSION}'))
    if parse_cache is not None:
        parse_cache.save()
    return apply_glyphs(out, glyph_mode, single_width)


def main(t0: float | None = None) -> None:
    if t0 is None:
        t0 = time.perf_counter()  # entry shim normally passes this, stamped before import
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')  # cp1252 default on Windows can't encode box/Nerd Font glyphs
    if not version_file().exists():
        from yas.migrate import migrate  # lazy one-time migration to the yas/{cache,state}/ layout
        migrate()
    cfg      = Config.load(argv=sys.argv[1:], config_dir=config_path().parent)
    bg_shift = cfg.bg_shift
    theme    = THEMES.get(cfg.theme, CLAUDE_DARK)

    info = json.loads(sys.stdin.read())

    # write payload for the multi-session observer, keyed by session_id and overwritten in place
    session_id = _as_str(info.get('session_id')) or 'unknown'
    try:
        sessions_dir().mkdir(parents=True, exist_ok=True)
        session_payload_path(session_id).write_text(json.dumps(info))
    except OSError:
        pass

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

    sys.stdout.write(render(info, width, bg_shift=bg_shift, theme=theme, glyph_mode=cfg.glyph_mode, single_width=cfg.single_width, timing=timing))
    if cfg.show_render_time:
        RenderTiming.write(session_id, (time.perf_counter() - t0) * 1000.0)
