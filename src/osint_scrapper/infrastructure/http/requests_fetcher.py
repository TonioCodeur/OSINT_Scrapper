"""The only adapter in this product that touches the network.

It composes the robots policy and the rate limiter internally. The crawl use
case receives a :class:`PageFetcher` and nothing else — never a session, never a
robots policy, never a rate limiter — which is what makes robots.txt, scope
confinement and rate limiting impossible for future code to forget (SPEC 6.1).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from osint_scrapper.application.errors import (
    HttpStatusError,
    OffScopeRedirectError,
    PageBudgetExhaustedError,
    RateLimitedError,
    ResponseTooLargeError,
    RobotsDeniedError,
    TooManyRedirectsError,
    TransportError,
    UnsupportedContentTypeError,
)
from osint_scrapper.application.ports import (
    HTML_MEDIA_TYPES,
    Clock,
    FetchedPage,
    RateLimiter,
    RobotsPolicy,
)
from osint_scrapper.domain.errors import UrlRejectedError
from osint_scrapper.domain.url import CrawlScope, canonicalize
from osint_scrapper.infrastructure.http.rate_limit import HARD_FLOOR_SECONDS, effective_interval
from osint_scrapper.infrastructure.http.robots import (
    MAXIMUM_REDIRECTS,
    MAXIMUM_ROBOTS_BODY_BYTES,
    RobotsFile,
)

logger = logging.getLogger(__name__)

RETRYABLE_STATUSES = (500, 502, 503, 504)
"""429 is deliberately absent: SPEC 5.10 makes it a crawl-level decision, because
repeated 429 must abort the run rather than be retried quietly by the transport."""

TOO_MANY_REQUESTS = 429
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
MAXIMUM_BODY_BYTES = 5 * 1024 * 1024
"""SPEC 5.7. Read in chunks and abandoned past the cap; nothing partial is parsed."""

DEFAULT_TIMEOUT_SECONDS = 10.0
_CHUNK_SIZE = 8192
_FALLBACK_ENCODING = "iso-8859-1"


@dataclass(frozen=True)
class FetchPolicy:
    """Everything the fetcher needs to be polite, bounded and confined (SPEC 6.1)."""

    product_token: str
    configured_interval_seconds: float
    hard_floor_seconds: float = HARD_FLOOR_SECONDS
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_pages: int = 200
    max_body_bytes: int = MAXIMUM_BODY_BYTES
    max_redirects: int = MAXIMUM_REDIRECTS
    scope: CrawlScope | None = None
    """When set, a redirect leaving it is refused rather than followed."""


def build_retry(total: int) -> Retry:
    """Return the 5xx retry policy of SPEC 5.10.

    ``raise_on_status`` is False so the exhausted response reaches this module
    with its real status code, which is what decides the page's status.
    """
    return Retry(
        total=total,
        status_forcelist=RETRYABLE_STATUSES,
        allowed_methods=frozenset({"GET"}),
        backoff_factor=1.0,
        backoff_jitter=0.5,
        backoff_max=30.0,
        respect_retry_after_header=True,
        raise_on_status=False,
    )


def build_session(user_agent: str, max_retries: int) -> requests.Session:
    """Return a session that identifies itself honestly and retries politely."""
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})
    session.max_redirects = MAXIMUM_REDIRECTS
    adapter = HTTPAdapter(max_retries=build_retry(max_retries))
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


class RequestsRobotsTransport:
    """Fetches robots.txt itself, bounded in size and never gated by robots.txt."""

    def __init__(
        self,
        session: requests.Session,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        maximum_body_bytes: int = MAXIMUM_ROBOTS_BODY_BYTES,
    ) -> None:
        self._session = session
        self._timeout_seconds = timeout_seconds
        self._maximum_body_bytes = maximum_body_bytes

    def get(self, url: str) -> RobotsFile:
        """Retrieve ``url``, reading one byte past the size limit.

        The ``+ 1`` is load-bearing and mirrors :meth:`RequestsPageFetcher._page_from`.
        Reading only ``maximum_body_bytes`` would hand the policy a body that is
        truncated to exactly the limit, never *above* it, so the ``DENY`` row of
        the SPEC 6.2.2 decision table for an oversized robots.txt could not fire
        and an oversized file would instead be silently cut short and parsed —
        dropping every rule past the cut and fetching what the host disallowed.
        """
        try:
            with self._session.get(
                url, timeout=self._timeout_seconds, stream=True, allow_redirects=True
            ) as response:
                body = _read_bounded(response, self._maximum_body_bytes + 1)
                return RobotsFile(
                    status_code=response.status_code, body=body, final_url=response.url
                )
        except requests.TooManyRedirects as failure:
            raise TooManyRedirectsError(f"{url}: {failure}") from failure
        except requests.RequestException as failure:
            raise TransportError(f"{url}: {failure}") from failure


class RequestsPageFetcher:
    """Fetches content pages under the run's robots, scope, rate and size rules.

    Redirects are followed one hop at a time rather than by ``requests``, because
    every hop must be gated again: a redirect must never become a way to reach a
    path, a host, or a whole other site whose robots.txt refuses us or whose name
    is outside the crawl scope. This manual loop is the most load-bearing thing
    in the file and must not be replaced by ``allow_redirects=True``.

    Shared across the concurrent workers of SPEC 6.4. The only mutable state it
    owns is the request counter, which is guarded; the session's own mutable
    state is its cookie jar, which ``http.cookiejar`` already locks, and this
    product issues nothing but ``GET``.
    """

    def __init__(
        self,
        session: requests.Session,
        robots_policy: RobotsPolicy,
        rate_limiter: RateLimiter,
        clock: Clock,
        policy: FetchPolicy,
    ) -> None:
        self._session = session
        self._robots_policy = robots_policy
        self._rate_limiter = rate_limiter
        self._clock = clock
        self._policy = policy
        self._lock = threading.Lock()
        self._requests_made = 0

    @property
    def requests_made(self) -> int:
        """Content requests issued so far, robots.txt excluded (SPEC NFR-12)."""
        with self._lock:
            return self._requests_made

    def sitemaps(self, url: str) -> tuple[str, ...]:
        """Return the ``Sitemap:`` directives governing ``url`` (SPEC 5.6)."""
        return self._robots_policy.sitemaps(url)

    def fetch(
        self, url: str, accepted_media_types: frozenset[str] = HTML_MEDIA_TYPES
    ) -> FetchedPage:
        """Retrieve ``url``, re-gating robots and scope on every redirect hop."""
        target = url
        for _ in range(self._policy.max_redirects + 1):
            response = self._request_once(target)
            location = _redirect_target(response, target)
            if location is None:
                return self._page_from(response, accepted_media_types)
            response.close()
            hop = self._next_hop(target, location)
            logger.debug("%s redirected to %s; re-evaluating robots there", target, hop)
            target = hop
        raise TooManyRedirectsError(
            f"{url}: more than {self._policy.max_redirects} redirects"
        )

    def _request_once(self, url: str) -> requests.Response:
        """Apply the budget, robots and rate-limit gates, then issue exactly one GET."""
        with self._lock:
            if self._requests_made >= self._policy.max_pages:
                raise PageBudgetExhaustedError(
                    f"the run reached its ceiling of {self._policy.max_pages} requests"
                )
            self._requests_made += 1

        crawl_delay = self._enforce_robots(url)
        self._rate_limiter.acquire(
            _host_of(url),
            effective_interval(
                self._policy.configured_interval_seconds,
                self._policy.hard_floor_seconds,
                crawl_delay,
            ),
        )
        return self._get(url)

    def _enforce_robots(self, url: str) -> float | None:
        """Return the host's crawl delay, or refuse the fetch (SPEC FR-10)."""
        decision = self._robots_policy.evaluate(url, self._policy.product_token)
        logger.debug("robots decision for %s: %s (%s)", url, decision.allowed, decision.reason)
        if not decision.allowed:
            raise RobotsDeniedError(url, decision.reason, decision.robots_url)
        return decision.crawl_delay

    def _next_hop(self, url: str, location: str) -> str:
        """Return the canonical URL of a redirect target, or refuse the hop.

        Canonicalizing here is load-bearing, not tidiness. ``urljoin`` normalizes
        only *relative* references, so an absolute ``Location:`` header reaches
        us verbatim — and ``RobotFileParser`` resolves neither ``/a/../b`` nor a
        doubled ``//``. Following the raw location would therefore evaluate
        robots.txt against ``/public/../private/x`` (allowed) while the server
        serves ``/private/x`` (disallowed). The hop we scope-check, the hop we
        ask robots about and the hop we actually request are now the same
        string.

        Scope is checked before and independently of the hop's robots
        evaluation: an off-scope redirect is not followed even when robots
        would allow it (SPEC 5.3).
        """
        try:
            canonical = canonicalize(location)
        except UrlRejectedError as rejection:
            raise OffScopeRedirectError(url, location) from rejection
        scope = self._policy.scope
        if scope is not None and not scope.contains(canonical):
            raise OffScopeRedirectError(url, canonical)
        return canonical

    def _get(self, url: str) -> requests.Response:
        try:
            return self._session.get(
                url,
                timeout=self._policy.timeout_seconds,
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException as failure:
            raise TransportError(f"{url}: {failure}") from failure

    def _page_from(
        self, response: requests.Response, accepted_media_types: frozenset[str]
    ) -> FetchedPage:
        """Turn a final response into a page, or refuse it before reading a body."""
        with response:
            if response.status_code == TOO_MANY_REQUESTS:
                raise RateLimitedError(
                    response.url, response.status_code, self._retry_after(response)
                )
            if response.status_code >= 400:
                raise HttpStatusError(response.url, response.status_code)

            media_type = _media_type(response)
            if media_type and media_type not in accepted_media_types:
                # The body is not read past the header and the connection is
                # released: an unparseable document costs us one set of headers.
                raise UnsupportedContentTypeError(response.url, media_type)

            body = _read_bounded(response, self._policy.max_body_bytes + 1)
            if len(body) > self._policy.max_body_bytes:
                raise ResponseTooLargeError(response.url, self._policy.max_body_bytes)

            return FetchedPage(
                url=_canonical_or_raw(response.url),
                status_code=response.status_code,
                content_type=response.headers.get("Content-Type", ""),
                text=_decode(body, response),
                fetched_at=self._clock.now(),
                headers={name.lower(): value for name, value in response.headers.items()},
            )


    def _retry_after(self, response: requests.Response) -> float | None:
        """Parse ``Retry-After``, which RFC 9110 allows as seconds or an HTTP date."""
        raw = response.headers.get("Retry-After", "").strip()
        if not raw:
            return None
        try:
            return float(int(raw))
        except ValueError:
            pass
        try:
            moment = parsedate_to_datetime(raw)
        except (TypeError, ValueError, IndexError):
            return None
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        return max((moment - self._clock.now()).total_seconds(), 0.0)


def _read_bounded(response: requests.Response, limit_bytes: int) -> bytes:
    """Read at most ``limit_bytes``, abandoning the rest."""
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_content(chunk_size=_CHUNK_SIZE):
        chunks.append(chunk)
        size += len(chunk)
        if size >= limit_bytes:
            break
    return b"".join(chunks)


def _decode(body: bytes, response: requests.Response) -> str:
    """Decode a body, preferring UTF-8 over the header's legacy default.

    ``requests`` reports ``ISO-8859-1`` for any ``text/*`` response that declares
    no charset, which is the RFC 2616 default and is wrong for most of the modern
    web. Trying UTF-8 strictly first and falling back is safe in both directions:
    text that decodes as UTF-8 essentially always is UTF-8.
    """
    declared = requests.utils.get_encoding_from_headers(response.headers)
    if declared and declared.lower() != _FALLBACK_ENCODING:
        return body.decode(declared, errors="replace")
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return body.decode(_FALLBACK_ENCODING, errors="replace")


def _media_type(response: requests.Response) -> str:
    return response.headers.get("Content-Type", "").split(";")[0].strip().lower()


def _canonical_or_raw(url: str) -> str:
    """Return the canonical form of the final URL, or the URL itself if it resists."""
    try:
        return canonicalize(url)
    except UrlRejectedError:
        return url


def _redirect_target(response: requests.Response, requested_url: str) -> str | None:
    """Return the absolute URL this response redirects to, or ``None``.

    Raises:
        TransportError: the status announced a redirect but named no location.
    """
    if response.status_code not in REDIRECT_STATUSES:
        return None
    location = response.headers.get("Location", "").strip()
    if not location:
        raise TransportError(
            f"{requested_url}: HTTP {response.status_code} without a Location header"
        )
    return urljoin(requested_url, location)


def _host_of(url: str) -> str:
    return urlsplit(url).netloc.lower()
