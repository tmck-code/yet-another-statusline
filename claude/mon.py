#!/usr/bin/env python3
'Multi-session Claude Code observer — aggregates statuslines from all active sessions.'

from __future__ import annotations

import os
import select
import shutil
import signal
import sys
import traceback
from datetime import datetime
from pathlib import Path

# Add claude/ dir to sys.path so sibling modules are importable.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mon.discovery import discover
from mon.lifecycle import classify, validate_thresholds, apply_dim
from mon.layout import (
    format_header,
    format_footer,
    format_empty_body,
    format_narrow_body,
    clip_to_height,
    aggregate_rate_limits,
    aggregate_day_cost,
)
from mon.tui import parse_args, enter_alt_screen, exit_alt_screen
from statusline_command import render, resolve_theme, MIN_WIDTH

_CURSOR_HOME = '\x1b[H'
_DIM  = '\033[38;5;240m'
_RESET = '\033[0m'


def _fmt_age(secs: int) -> str:
    if secs < 60:
        return f'{secs}s'
    if secs < 3600:
        m, s = divmod(secs, 60)
        return f'{m}m{s:02d}s' if s else f'{m}m'
    h, rem = divmod(secs, 3600)
    m = rem // 60
    return f'{h}h{m:02d}m' if m else f'{h}h'


def _age_label(age_secs: int, width: int) -> str:
    text  = f' ─ {_fmt_age(age_secs)} ago '
    fill  = max(0, width - len(text))
    return f'{_DIM}{text}{"─" * fill}{_RESET}'


def tick(args) -> None:
    sz = shutil.get_terminal_size(fallback=(120, 40))
    cols, rows = sz.columns, sz.lines

    now = datetime.now()
    now_ts = now.timestamp()

    sessions = discover(args.include_after, now)
    theme    = resolve_theme(args.theme)

    # Filter to bright/dim only (remove 'removed' sessions).
    active = []
    for s in sessions:
        tier = classify(s.jsonl_mtime, now_ts, args.idle_after, args.remove_after)
        if tier != 'removed':
            active.append((s, tier))

    # Header and footer each take 1 row.
    available_body = max(0, rows - 2)

    if cols < MIN_WIDTH:
        header = format_header(0, None, None, 0.0, cols)
        body   = format_narrow_body(cols, available_body)
        footer = format_footer(0, 0, 0, cols)
        frame  = '\n'.join([header, body, footer])
        sys.stdout.write(_CURSOR_HOME + frame)
        sys.stdout.flush()
        return

    # Render each session box; prepend an age label; apply dim post-processing.
    width = max(MIN_WIDTH, min(160, cols - 6))
    rendered_boxes: list[str] = []
    for s, tier in active:
        box = render(s.payload, width, bg_shift=args.bg_shift, theme=theme)
        if box:
            age_secs = max(0, int(now_ts - s.jsonl_mtime))
            label = _age_label(age_secs, width)
            box = label + '\n' + box
            if tier == 'dim':
                box = apply_dim(box)
            rendered_boxes.append(box)

    # Clip to available body height.
    visible_boxes, hidden_count = clip_to_height(rendered_boxes, available_body)
    n_sessions = len(visible_boxes)

    # Aggregate header data.
    visible_sessions = [s for (s, _), box in zip(active, rendered_boxes) if box in visible_boxes]
    five_h, seven_d = aggregate_rate_limits(visible_sessions)
    day_cost        = aggregate_day_cost(visible_sessions)

    header = format_header(n_sessions, five_h, seven_d, day_cost, cols)
    footer = format_footer(0, n_sessions, hidden_count, cols)

    if not visible_boxes:
        body = format_empty_body(cols, available_body)
        frame = '\n'.join([header, body, footer])
    else:
        frame = '\n'.join([header] + visible_boxes + [footer])

    sys.stdout.write(_CURSOR_HOME + frame)
    sys.stdout.flush()


def main() -> None:
    args = parse_args(sys.argv[1:])

    try:
        validate_thresholds(args.include_after, args.idle_after, args.remove_after)
    except ValueError as exc:
        sys.stderr.write(f'error: {exc}\n')
        sys.exit(1)

    refresh_seconds = args.refresh.total_seconds()

    # Self-pipe: SIGWINCH handler writes a byte; select() wakes immediately.
    pipe_r, pipe_w = os.pipe()

    def _sigwinch(signum: int, frame: object) -> None:
        try:
            os.write(pipe_w, b'\x00')
        except OSError:
            pass

    if hasattr(signal, 'SIGWINCH'):
        signal.signal(signal.SIGWINCH, _sigwinch)

    enter_alt_screen()
    try:
        while True:
            tick(args)
            # Sleep for refresh_seconds, waking early on SIGWINCH.
            rlist, _, _ = select.select([pipe_r], [], [], refresh_seconds)
            if rlist:
                os.read(pipe_r, 64)  # drain
    except KeyboardInterrupt:
        pass
    except Exception:
        exit_alt_screen()
        traceback.print_exc()
        return
    finally:
        exit_alt_screen()


if __name__ == '__main__':
    main()
