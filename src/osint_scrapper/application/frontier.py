"""The crawl frontier and visited set (SPEC 5.4, 5.8).

Pure, standard library, and guarded so the concurrent workers of SPEC 6.4 can
never take the same URL twice.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass

from osint_scrapper.domain.url import is_high_value_path


@dataclass(frozen=True)
class FrontierItem:
    """One canonical URL not yet fetched, with the depth it was discovered at."""

    url: str
    depth: int


class VisitedSet:
    """Canonical URLs already claimed. Membership is checked before every fetch."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._urls: set[str] = set()

    def claim(self, url: str) -> bool:
        """Add ``url`` and return whether this caller is the one that added it.

        Atomic on purpose: two workers dequeuing at the same moment must not both
        conclude that the URL is theirs.
        """
        with self._lock:
            if url in self._urls:
                return False
            self._urls.add(url)
            return True

    def add(self, url: str) -> None:
        """Record ``url`` as seen, without caring whether it already was.

        Used for the final URL after redirects, so a page reachable at three URLs
        that all redirect to one is fetched once and counted once (SPEC 5.8).
        """
        with self._lock:
            self._urls.add(url)

    def __contains__(self, url: object) -> bool:
        with self._lock:
            return url in self._urls

    def __len__(self) -> int:
        with self._lock:
            return len(self._urls)


class Frontier:
    """Breadth-first queue with the priority boost of SPEC 5.4.

    A URL whose path matches the high-value list is pushed to the front. This
    never adds a request — it only reorders a queue that already contains the
    URL — so a budget-truncated crawl still returns the pages that matter.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: deque[FrontierItem] = deque()
        self._queued: set[str] = set()

    def push(self, url: str, depth: int) -> bool:
        """Enqueue ``url``, returning whether it was new to the frontier."""
        item = FrontierItem(url=url, depth=depth)
        with self._lock:
            if url in self._queued:
                return False
            self._queued.add(url)
            if is_high_value_path(url):
                self._items.appendleft(item)
            else:
                self._items.append(item)
            return True

    def pop(self) -> FrontierItem | None:
        """Dequeue the next URL, or return ``None`` when the frontier is empty."""
        with self._lock:
            if not self._items:
                return None
            item = self._items.popleft()
            self._queued.discard(item.url)
            return item

    def drain(self) -> tuple[FrontierItem, ...]:
        """Remove and return everything still queued, in queue order.

        Used when a run ends early: the URLs that were discovered but never
        reached are reported rather than silently dropped (SPEC FR-7).
        """
        with self._lock:
            remaining = tuple(self._items)
            self._items.clear()
            self._queued.clear()
            return remaining

    def __contains__(self, url: object) -> bool:
        with self._lock:
            return url in self._queued

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)
