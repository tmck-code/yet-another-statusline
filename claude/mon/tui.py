"""TUI loop module — alt-screen lifecycle, refresh cadence, SIGWINCH handling, CLI args."""

import argparse
import shutil
import signal
import sys
import threading
from datetime import timedelta
from typing import Callable
from argparse import Namespace


def enter_alt_screen() -> None:
    sys.stdout.write('\x1b[?1049h')
    sys.stdout.flush()


def exit_alt_screen() -> None:
    sys.stdout.write('\x1b[?1049l')
    sys.stdout.flush()


class RefreshClock:
    def __init__(self) -> None:
        self._event = threading.Event()

    def wait(self, seconds: float) -> None:
        self._event.wait(timeout=seconds)
        self._event.clear()

    def wake(self) -> None:
        self._event.set()


def install_sigwinch_handler(
    clock: RefreshClock,
    on_resize: Callable[[int, int], None],
) -> None:
    sigwinch = getattr(signal, 'SIGWINCH', None)
    if sigwinch is None:
        return

    def _handler(signum: int, frame: object) -> None:
        size = shutil.get_terminal_size()
        on_resize(size.columns, size.lines)
        clock.wake()

    signal.signal(sigwinch, _handler)


def _parse_duration(s: str) -> timedelta:
    if s.endswith('h'):
        try:
            return timedelta(hours=float(s[:-1]))
        except ValueError:
            pass
    elif s.endswith('m'):
        try:
            return timedelta(minutes=float(s[:-1]))
        except ValueError:
            pass
    elif s.endswith('s'):
        try:
            return timedelta(seconds=float(s[:-1]))
        except ValueError:
            pass
    raise argparse.ArgumentTypeError(
        f'Invalid duration {s!r}: expected a number followed by s, m, or h'
    )


def parse_args(argv: list[str]) -> Namespace:
    parser = argparse.ArgumentParser(
        description='Multi-session Claude Code observer',
    )
    parser.add_argument(
        '--include-after',
        type=_parse_duration,
        default=timedelta(minutes=10),
        metavar='DURATION',
        help='Include sessions active within this window (default: 10m)',
    )
    parser.add_argument(
        '--idle-after',
        type=_parse_duration,
        default=timedelta(minutes=2),
        metavar='DURATION',
        help='Dim sessions idle longer than this (default: 2m)',
    )
    parser.add_argument(
        '--remove-after',
        type=_parse_duration,
        default=timedelta(minutes=15),
        metavar='DURATION',
        help='Remove sessions idle longer than this (default: 15m)',
    )
    parser.add_argument(
        '--refresh',
        type=_parse_duration,
        default=timedelta(seconds=2),
        metavar='DURATION',
        help='Refresh interval (default: 2s)',
    )
    parser.add_argument(
        '--bg-shift',
        default='warm',
        choices=['warm', 'cool'],
        help='Background colour shift (default: warm)',
    )
    parser.add_argument(
        '--theme',
        default=None,
        metavar='NAME',
        help='Theme name (default: none)',
    )
    return parser.parse_args(argv)
