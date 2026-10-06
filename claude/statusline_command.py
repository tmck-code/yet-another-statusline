#!/usr/bin/env python3
import time

# Stamp the wall-clock start before importing the app so the bottom-border
# run-time annotation accounts for import cost (the dominant startup term).
_T0 = time.perf_counter()

from yas.app import arm_watchdog, main  # noqa: E402  (import deferred so _T0 captures import cost)
from yas.constants import WATCHDOG_SECONDS  # noqa: E402

if __name__ == '__main__':
    arm_watchdog(WATCHDOG_SECONDS)
    main(_T0)
