"""Current time in unix seconds. A separate module so tests can substitute it."""

from __future__ import annotations

import time


def now() -> int:
    return int(time.time())
