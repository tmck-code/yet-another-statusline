from datetime import timedelta
from typing import Literal

Tier = Literal['bright', 'dim', 'removed']


def classify(
    jsonl_mtime: float,
    now: float,
    idle_after: timedelta,
    remove_after: timedelta,
) -> Tier:
    age = now - jsonl_mtime
    if age <= idle_after.total_seconds():
        return 'bright'
    if age <= remove_after.total_seconds():
        return 'dim'
    return 'removed'


def validate_thresholds(
    include: timedelta,
    idle: timedelta,
    remove: timedelta,
) -> None:
    if remove < idle:
        raise ValueError(
            f'remove_after ({remove}) must be >= idle_after ({idle})'
        )


def apply_dim(rendered_box: str) -> str:
    return rendered_box.replace('\x1b[0m', '\x1b[0;2m')
