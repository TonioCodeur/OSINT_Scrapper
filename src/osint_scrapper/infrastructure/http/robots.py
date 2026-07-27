"""robots.txt evaluation, fail-closed (SPEC 6.2.2).

Only a definitive answer from the host can allow a fetch. Everything ambiguous —
unreachable, refused, oversized, undecodable — denies. The one deliberate
divergence from a maximally paranoid reading is that a 404 allows: it is a
definitive "there is no robots.txt", it is what RFC 9309 section 2.3.1.3
prescribes, and it is what the standard library implements. That divergence is
unchanged at two hundred requests, precisely because the reasoning never
depended on volume.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from osint_scrapper.application.errors import TooManyRedirectsError, TransportError
from osint_scrapper.application.ports import Clock, RobotsDecision

logger = logging.getLogger(__name__)

MAXIMUM_ROBOTS_BODY_BYTES = 512 * 1024
"""RFC 9309 requires parsing at least 500 KiB; anything larger is treated as ambiguous."""

MAXIMUM_REDIRECTS = 5
CACHE_TTL_SECONDS = 24 * 60 * 60
"""RFC 9309 caps robots.txt caching at 24 hours."""


class RobotsReason:
    """Machine-stable reason codes. Tests and exports assert on these strings."""

    ALLOW_RULE = "robots_allow_rule"
    DISALLOW = "robots_disallow"
    ABSENT_404 = "robots_absent_404"
    ABSENT_4XX = "robots_absent_4xx"
    REFUSED_401 = "robots_refused_401"
    REFUSED_403 = "robots_refused_403"
    UNREACHABLE_5XX = "robots_unreachable_5xx"
    UNREACHABLE_TRANSPORT = "robots_unreachable_transport"
    BODY_TOO_LARGE = "robots_body_too_large"
    UNDECODABLE = "robots_undecodable"
    TOO_MANY_REDIRECTS = "robots_too_many_redirects"


@dataclass(frozen=True)
class RobotsFile:
    """A raw robots.txt response, before any decision is made about it."""

    status_code: int
    body: bytes
    final_url: str


class RobotsTransport(Protocol):
    """Retrieves robots.txt with the project's own User-Agent and timeout.

    Deliberately not the :class:`PageFetcher` port: fetching robots.txt must not
    itself be gated by robots.txt.
    """

    def get(self, url: str) -> RobotsFile:
        """Retrieve ``url``.

        Raises:
            TransportError: no usable response, including too many redirects.
        """
        ...


@dataclass(frozen=True)
class _CacheEntry:
    parser: RobotFileParser | None
    decision_reason: str
    allowed_by_default: bool
    robots_url: str
    stored_at: float
    sitemaps: tuple[str, ...] = ()


def robots_url_for(url: str) -> str:
    """Return the robots.txt URL governing ``url``."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))


def host_key(url: str) -> tuple[str, str]:
    """Return the ``(scheme, netloc)`` cache key for ``url``."""
    parts = urlsplit(url)
    return (parts.scheme.lower(), parts.netloc.lower())


class RobotsTxtPolicy:
    """Evaluates robots.txt per host, caching each answer for the run.

    Evaluation happens per URL, not once per host: path-level rules mean a
    host-level decision is meaningless. The cache is what keeps that from
    costing a request each time, and it is guarded because SPEC 6.4 lets several
    workers ask at once.
    """

    def __init__(
        self,
        transport: RobotsTransport,
        clock: Clock,
        ttl_seconds: float = CACHE_TTL_SECONDS,
        maximum_body_bytes: int = MAXIMUM_ROBOTS_BODY_BYTES,
    ) -> None:
        self._transport = transport
        self._clock = clock
        self._ttl_seconds = ttl_seconds
        self._maximum_body_bytes = maximum_body_bytes
        self._lock = threading.Lock()
        self._cache: dict[tuple[str, str], _CacheEntry] = {}

    def evaluate(self, url: str, product_token: str) -> RobotsDecision:
        """Decide whether ``product_token`` may fetch ``url``."""
        entry = self._entry_for(url)
        if entry.parser is None:
            return RobotsDecision(
                allowed=entry.allowed_by_default,
                reason=entry.decision_reason,
                robots_url=entry.robots_url,
            )

        allowed = entry.parser.can_fetch(product_token, url)
        return RobotsDecision(
            allowed=allowed,
            reason=RobotsReason.ALLOW_RULE if allowed else RobotsReason.DISALLOW,
            robots_url=entry.robots_url,
            crawl_delay=_crawl_delay(entry.parser, product_token),
        )

    def sitemaps(self, url: str) -> tuple[str, ...]:
        """Return the ``Sitemap:`` directives of the host's robots.txt (SPEC 5.6).

        Read from the body already fetched for the robots decision, so discovery
        costs no extra request. The directive is independent of any
        ``User-agent`` group and may appear several times.
        """
        return self._entry_for(url).sitemaps

    def _entry_for(self, url: str) -> _CacheEntry:
        key = host_key(url)
        now = self._clock.now().timestamp()
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and now - cached.stored_at < self._ttl_seconds:
                return cached
        entry = self._load(robots_url_for(url), now)
        with self._lock:
            self._cache[key] = entry
        return entry

    def _load(self, robots_url: str, now: float) -> _CacheEntry:
        try:
            response = self._transport.get(robots_url)
        except TooManyRedirectsError:
            return _deny(RobotsReason.TOO_MANY_REDIRECTS, robots_url, now)
        except TransportError as failure:
            logger.debug("robots.txt unreachable at %s: %s", robots_url, failure)
            return _deny(RobotsReason.UNREACHABLE_TRANSPORT, robots_url, now)

        outcome = _classify_status(response.status_code)
        if outcome is not None:
            reason, allowed = outcome
            return _CacheEntry(None, reason, allowed, robots_url, now)

        if len(response.body) > self._maximum_body_bytes:
            return _deny(RobotsReason.BODY_TOO_LARGE, robots_url, now)
        try:
            text = response.body.decode("utf-8")
        except UnicodeDecodeError:
            return _deny(RobotsReason.UNDECODABLE, robots_url, now)

        parser = RobotFileParser()
        parser.set_url(robots_url)
        # parse() calls modified() internally, so crawl_delay(), request_rate()
        # and site_maps() are usable immediately. read() is never called: it
        # would issue an unthrottled request with no User-Agent and no timeout.
        parser.parse(text.splitlines())
        declared = parser.site_maps() or []
        return _CacheEntry(
            parser, RobotsReason.ALLOW_RULE, True, robots_url, now, tuple(declared)
        )


def _classify_status(status_code: int) -> tuple[str, bool] | None:
    """Map a status to a decision, or ``None`` when the body must be parsed."""
    if 200 <= status_code < 300:
        return None
    if status_code == 401:
        return (RobotsReason.REFUSED_401, False)
    if status_code == 403:
        return (RobotsReason.REFUSED_403, False)
    if status_code == 404:
        return (RobotsReason.ABSENT_404, True)
    if 400 <= status_code < 500:
        return (RobotsReason.ABSENT_4XX, True)
    if status_code >= 500:
        return (RobotsReason.UNREACHABLE_5XX, False)
    return (RobotsReason.UNREACHABLE_TRANSPORT, False)


def _deny(reason: str, robots_url: str, now: float) -> _CacheEntry:
    return _CacheEntry(None, reason, False, robots_url, now)


def _crawl_delay(parser: RobotFileParser, product_token: str) -> float | None:
    """Return the host's requested delay, from ``Crawl-delay`` or ``Request-rate``."""
    delay = parser.crawl_delay(product_token)
    if delay is not None:
        return float(delay)
    rate = parser.request_rate(product_token)
    if rate is not None and rate.requests > 0:
        return float(rate.seconds) / float(rate.requests)
    return None
