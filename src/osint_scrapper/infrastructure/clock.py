"""Real time. Injected everywhere so tests can be deterministic and never sleep."""

from __future__ import annotations

import time
from datetime import UTC, datetime


class SystemClock:
    """Wall-clock time in UTC."""

    def now(self) -> datetime:
        """Return the current time as an aware UTC datetime."""
        return datetime.now(UTC)


class SystemMonotonicClock:
    """A clock that cannot go backwards, used to space requests to a host."""

    def monotonic(self) -> float:
        """Return a monotonically increasing number of seconds."""
        return time.monotonic()


class SystemSleeper:
    """Blocks the calling thread."""

    def sleep(self, seconds: float) -> None:
        """Block for ``seconds``, ignoring non-positive durations."""
        if seconds > 0:
            time.sleep(seconds)
