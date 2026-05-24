from __future__ import annotations

from .discovery import ActiveSession

# ANSI escape helpers
_RESET  = '\033[0m'
_DIM    = '\033[38;5;244m'   # dim grey for separators / labels
_BRIGHT = '\033[1m'          # bold/bright for values


def _visible_len(s: str) -> int:
    """Return the printable (visible) length of a string by stripping ANSI escapes."""
    import re
    return len(re.sub(r'\033\[[0-9;]*m', '', s))


def _pad_or_clip(s: str, width: int) -> str:
    """Pad a string with trailing spaces or clip it so its visible width equals width."""
    vis = _visible_len(s)
    if vis < width:
        return s + ' ' * (width - vis)
    if vis > width:
        # Clip: remove characters from the raw string until visible width == width
        # Walk the raw string, skipping escape sequences.
        import re
        _ESC = re.compile(r'\033\[[0-9;]*m')
        result = []
        current_width = 0
        pos = 0
        while pos < len(s) and current_width < width:
            m = _ESC.match(s, pos)
            if m:
                result.append(m.group())
                pos = m.end()
            else:
                result.append(s[pos])
                current_width += 1
                pos += 1
        return ''.join(result) + _RESET
    return s


def format_header(
    n_sessions: int,
    five_h_pct: int | None,
    seven_d_pct: int | None,
    day_cost_usd: float,
    width: int,
) -> str:
    """Return a single ANSI-decorated header line padded/clipped to width."""
    sep = f'{_DIM} · {_RESET}'

    five_h_str  = f'{_BRIGHT}{five_h_pct}%{_RESET}'  if five_h_pct  is not None else f'{_DIM}–{_RESET}'
    seven_d_str = f'{_BRIGHT}{seven_d_pct}%{_RESET}' if seven_d_pct is not None else f'{_DIM}–{_RESET}'

    line = (
        f'{_BRIGHT}{n_sessions}{_RESET}'
        f'{_DIM} session{"s" if n_sessions != 1 else ""}{_RESET}'
        f'{sep}'
        f'{_DIM}5h: {_RESET}{five_h_str}'
        f'{sep}'
        f'{_DIM}7d: {_RESET}{seven_d_str}'
        f'{sep}'
        f'{_DIM}day: {_RESET}{_BRIGHT}${day_cost_usd:.2f}{_RESET}'
    )
    return _pad_or_clip(line, width)


def format_footer(
    refresh_age_seconds: int,
    n_sessions: int,
    hidden_count: int,
    width: int,
) -> str:
    """Return a single ANSI-decorated footer line padded/clipped to width."""
    sep = f'{_DIM} · {_RESET}'

    line = (
        f'{_DIM}refreshed {_RESET}{_BRIGHT}{refresh_age_seconds}s{_RESET}{_DIM} ago{_RESET}'
        f'{sep}'
        f'{_BRIGHT}{n_sessions}{_RESET}'
        f'{_DIM} session{"s" if n_sessions != 1 else ""}{_RESET}'
    )
    if hidden_count > 0:
        line += f'{sep}{_DIM}+{hidden_count} hidden{_RESET}'

    return _pad_or_clip(line, width)


def _centre_line(text: str, width: int) -> str:
    """Centre text within width columns (plain spaces either side)."""
    text_len = len(text)
    if text_len >= width:
        return text[:width]
    pad_left = (width - text_len) // 2
    pad_right = width - text_len - pad_left
    return ' ' * pad_left + text + ' ' * pad_right


def format_empty_body(width: int, height: int) -> str:
    """Return a multi-line string of exactly height lines with (no active sessions) centred."""
    if height <= 0:
        return ''
    blank = ' ' * width
    msg_line = _centre_line('(no active sessions)', width)
    if height == 1:
        return msg_line
    mid = height // 2
    lines = [blank] * height
    lines[mid] = msg_line
    return '\n'.join(lines)


def format_narrow_body(width: int, height: int) -> str:
    """Return a multi-line string of exactly height lines with (terminal too narrow) centred."""
    if height <= 0:
        return ''
    blank = ' ' * width
    msg_line = _centre_line('(terminal too narrow)', width)
    if height == 1:
        return msg_line
    mid = height // 2
    lines = [blank] * height
    lines[mid] = msg_line
    return '\n'.join(lines)


def clip_to_height(
    rendered_boxes: list[str],
    available_height: int,
) -> tuple[list[str], int]:
    """Greedily include boxes from the front until cumulative line count exceeds available_height.

    Returns (visible_boxes, hidden_count).
    """
    visible: list[str] = []
    used = 0
    for box in rendered_boxes:
        n_lines = box.count('\n') + 1
        if used + n_lines > available_height:
            # This box doesn't fit; all remaining boxes are hidden.
            break
        visible.append(box)
        used += n_lines
    hidden_count = len(rendered_boxes) - len(visible)
    return visible, hidden_count


def aggregate_rate_limits(
    sessions: list[ActiveSession],
) -> tuple[int | None, int | None]:
    """Return (five_h_pct, seven_d_pct) from the session with the highest payload_mtime."""
    if not sessions:
        return (None, None)
    latest = max(sessions, key=lambda s: s.payload_mtime)
    rl = latest.payload.get('rate_limits', {})
    five_h  = rl.get('five_hour',  {}).get('used_percentage')
    seven_d = rl.get('seven_day',  {}).get('used_percentage')
    try:
        five_h  = int(five_h)  if five_h  is not None else None
    except (TypeError, ValueError):
        five_h = None
    try:
        seven_d = int(seven_d) if seven_d is not None else None
    except (TypeError, ValueError):
        seven_d = None
    return (five_h, seven_d)


def aggregate_day_cost(sessions: list[ActiveSession]) -> float:
    """Sum total_cost_usd across all sessions."""
    return sum(
        s.payload.get('cost', {}).get('total_cost_usd', 0.0)
        for s in sessions
    )
