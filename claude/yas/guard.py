"""Failure containment for optional statusline sections.

One failing optional gather (or section builder) must never blank the whole
statusline. `guarded` wraps a `SessionView` cached property so a raise falls
back to the field's empty value; `record_failure` writes the exception to a
bounded log. Both stay cheap on the normal path: `traceback` is imported and
formatted only once an exception has actually happened.
"""

from __future__ import annotations

from functools import cached_property, wraps
from typing import Callable, Protocol, TypeVar

from yas.constants import ERRORS_LOG_MAX_BYTES, ERRORS_LOG_ENTRY_MARK, errors_log

T = TypeVar('T')


class _Guarded(Protocol):
    failed:  list[str]
    minimal: bool


G = TypeVar('G', bound=_Guarded)


def record_failure(section: str, exc: BaseException) -> None:
    'Append one entry (section, type, message, traceback) to errors.log; never raises.'
    import time
    import traceback
    from yas.filelock import atomic_write_text, file_lock
    log   = errors_log()
    stamp = time.strftime('%Y-%m-%dT%H:%M:%S')
    tb    = ''.join(traceback.format_exception(exc))
    entry = f'{ERRORS_LOG_ENTRY_MARK} {stamp} {section} {type(exc).__name__}: {exc}\n{tb}'
    try:
        with file_lock(log):
            old  = log.read_text(errors='replace') if log.exists() else ''
            text = old + entry
            if len(text) > ERRORS_LOG_MAX_BYTES:
                # Drop whole oldest entries; keep the newest entry even if oversized.
                cut = text.find(f'\n{ERRORS_LOG_ENTRY_MARK}', len(text) - ERRORS_LOG_MAX_BYTES)
                text = text[cut + 1:] if cut >= 0 else entry
            atomic_write_text(log, text)
    except OSError:
        pass


def note_failure(failed: list[str], section: str, exc: BaseException) -> None:
    'Remember `section` as failed (once) for the visible marker, and log it.'
    if section not in failed:
        failed.append(section)
    record_failure(section, exc)


def guarded(default: Callable[[], T]) -> Callable[[Callable[[G], T]], cached_property[T]]:
    """Cached-property decorator: on any exception (or in `minimal` mode) return `default()`.

    A raise is logged and the field name is added to `view.failed`; `minimal`
    mode (the render retry) skips the gather entirely and is not a failure.
    """
    def deco(fn: Callable[[G], T]) -> cached_property[T]:
        @wraps(fn)
        def wrapper(self: G) -> T:
            if self.minimal:
                return default()
            try:
                return fn(self)
            except Exception as exc:
                note_failure(self.failed, fn.__name__, exc)
                return default()
        return cached_property(wrapper)
    return deco
