"""Per-host rate limiting (SPEC FR-11, 6.3).

The effective interval is a floor built from independent sources and can only
ever go up: the hard floor, the operator's setting, and the host's own
``Crawl-delay`` or ``Request-rate``. Nothing in the configuration file, the
interface, the environment or an argument lowers it, and the concurrency of
SPEC 6.4 does not either — the limiter is shared by every worker and gates
request *starts*, so it stays the single throughput governor.
"""

from __future__ import annotations

import logging
import threading

from osint_scrapper.application.ports import MonotonicClock, Sleeper

logger = logging.getLogger(__name__)

HARD_FLOOR_SECONDS = 0.5
"""SPEC FR-11. A permanent candidate of every interval computation."""


def effective_interval(*candidates: float | None) -> float:
    """Return the largest of the given intervals, never below the hard floor.

    The floor is added here rather than at the call sites so that a future
    caller cannot forget it, which is the same reasoning that puts robots.txt
    inside the fetcher.
    """
    present = [candidate for candidate in candidates if candidate is not None]
    present.append(HARD_FLOOR_SECONDS)
    return max(present)


class PerHostRateLimiter:
    """Spaces the *starts* of two requests to the same host.

    Safe to share across the concurrent workers of SPEC 6.4: the wait is decided
    and the start recorded under one lock, so two workers cannot both conclude
    that the host is free.
    """

    def __init__(self, clock: MonotonicClock, sleeper: Sleeper) -> None:
        self._clock = clock
        self._sleeper = sleeper
        self._lock = threading.Lock()
        self._last_start: dict[str, float] = {}

    def acquire(self, host: str, minimum_interval: float) -> None:
        """Block until ``host`` may be requested again, then record the start."""
        with self._lock:
            now = self._clock.monotonic()
            previous = self._last_start.get(host)
            wait = 0.0 if previous is None else previous + minimum_interval - now
            start = now if wait <= 0 else now + wait
            self._last_start[host] = start
        if wait > 0:
            logger.debug("waiting %.2fs before the next request to %s", wait, host)
            self._sleeper.sleep(wait)
