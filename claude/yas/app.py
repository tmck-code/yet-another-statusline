from __future__ import annotations

import json
import sys
import time
from datetime import datetime

from yas.config import Config
from yas.constants import CLAUDE_DIR, MIN_WIDTH, NARROW_WIDTH, MEDIUM_WIDTH
from yas.info import SessionView
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
    """Layered theme selection: CLI -> YAS_THEME -> CLAUDE_STATUSLINE_THEME
    -> [appearance].theme -> statusline-theme file -> CLAUDE_DARK.

    Resolves live (fresh Config.load) so callers see the current environment and
    CLAUDE_DIR; the import-time CONFIG singleton is for the module constants."""
    if cli_name and cli_name in THEMES:
        return THEMES[cli_name]
    return THEMES.get(Config.load().theme, CLAUDE_DARK)


def render(session_info: dict[str, object], width: int, *, bg_shift: str = 'warm', theme: Theme | None = None, glyph_mode: str | None = None, single_width: bool | None = None, timing: str = '') -> str:
    if width < MIN_WIDTH:
        return ''
    session    = SessionInfo.from_dict(session_info)
    r          = Renderer(bg_shift=bg_shift, theme=theme)
    cfg        = Config.load()
    if glyph_mode is None:
        glyph_mode = cfg.glyph_mode
    if single_width is None:
        single_width = cfg.single_width
    soft_limit = cfg.soft_limit_for(session.model.id, session.model.display_name)
    view       = SessionView(session, cfg)
    if width < NARROW_WIDTH:
        spec = build_narrow(view, width, r, soft_limit)
    elif width < MEDIUM_WIDTH:
        spec = build_medium(view, width, r, soft_limit)
    else:
        tick = record_tick(session, view.transcript_usage)
        spec = build_wide(view, tick, width, r, soft_limit)
    out = '\n'.join(render_layout(spec, r, timing))
    return apply_glyphs(out, glyph_mode, single_width)


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
    # Resolve config live so a freshly-set env var (e.g. YAS_FULL_WIDTH) or an
    # edited yas.toml takes effect on this invocation; CLI flags are top priority.
    cfg      = Config.load(argv=sys.argv[1:], config_dir=CLAUDE_DIR)
    bg_shift = cfg.bg_shift
    theme    = THEMES.get(cfg.theme, CLAUDE_DARK)

    info = json.loads(sys.stdin.read())

    # Write payload so the multi-session observer can index it. Keyed by
    # session_id and overwritten in place, so the dir holds one file per
    # session rather than one per render tick. The observer already collapses
    # to the newest payload per session (mon/discovery.index_payloads_by_session),
    # so the old timestamped filenames only ever accumulated dead weight.
    session_id = _as_str(info.get('session_id')) or 'unknown'
    try:
        out_dir    = CLAUDE_DIR / 'statusline-output'
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f'statusline.{session_id}.json').write_text(json.dumps(info))
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

    sys.stdout.write(render(info, width, bg_shift=bg_shift, theme=theme, glyph_mode=cfg.glyph_mode, single_width=cfg.single_width, timing=timing))
    if cfg.show_render_time:
        RenderTiming.write(session_id, (time.perf_counter() - t0) * 1000.0)
