"""Every boundary the application crosses, declared as a narrow Protocol.

Nothing here imports a third-party package, and nothing here imports Qt. Adapters
live in ``infrastructure`` or ``interfaces`` and are injected through
constructors by the single composition root in ``interfaces/app.py``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from osint_scrapper.domain.attributes import FieldName, Finding, RawField
from osint_scrapper.domain.crawl import PageOutcome
from osint_scrapper.domain.report import SiteReport
from osint_scrapper.domain.target import CrawlSettings, CrawlTarget

HTML_MEDIA_TYPES = frozenset({"text/html", "application/xhtml+xml"})
"""What the HTML extraction layers are written against (SPEC 5.7)."""

SITEMAP_MEDIA_TYPES = frozenset({"application/xml", "text/xml", "application/rss+xml"})
"""Accepted for sitemap documents only."""

PLAIN_TEXT_MEDIA_TYPES = frozenset({"text/plain"})
"""Accepted for ``/.well-known/security.txt`` only (RFC 9116)."""

EMPTY_HEADERS: Mapping[str, str] = MappingProxyType({})


@dataclass(frozen=True)
class FetchedPage:
    """One successfully retrieved document. The body is never persisted (FR-15)."""

    url: str
    """The final URL after redirects, canonicalized, which is what provenance records."""

    status_code: int
    content_type: str
    text: str
    fetched_at: datetime
    headers: Mapping[str, str] = EMPTY_HEADERS
    """Response headers with lower-cased keys, required by the technology extractor."""

    @property
    def media_type(self) -> str:
        """The ``Content-Type`` media type, lower-cased and without parameters."""
        return self.content_type.split(";")[0].strip().lower()


@dataclass(frozen=True)
class RobotsDecision:
    """The outcome of evaluating one host's robots.txt for one URL."""

    allowed: bool
    reason: str
    """A short machine-stable code, e.g. ``robots_disallow``, ``robots_absent_404``."""

    robots_url: str
    crawl_delay: float | None = None


@dataclass(frozen=True)
class LedgerEntry:
    """One line of the append-only run ledger (SPEC 9.7).

    ``target_host`` is plaintext, deliberately: the target is a hostname, the
    report in the same directory contains it in full, and the Runs screen must
    be able to show what was crawled without opening every report on disk.
    """

    run_id: str
    target_host: str
    target_url: str
    purpose_category: str
    purpose_note: str
    created_at: datetime
    retention_days: int
    directory: str
    pages_fetched: int
    findings_count: int
    files: tuple[str, ...]


@dataclass(frozen=True)
class ErasureReport:
    """What an erasure removed. Shown verbatim so the operator can verify it."""

    removed_paths: tuple[Path, ...] = ()
    removed_run_ids: tuple[str, ...] = ()

    def is_empty(self) -> bool:
        """Whether nothing matched, which is a success, not an error."""
        return not self.removed_run_ids


@dataclass(frozen=True)
class ValidatedValue:
    """A candidate that passed its validator and may become a finding."""

    value: str
    """What is stored and exported, diacritics and casing preserved."""

    dedup_value: str
    """The folded form used only as a deduplication key (SPEC 8.5)."""

    metadata: Mapping[str, str] = field(default_factory=dict)


class Clock(Protocol):
    """Wall-clock time, injected so exports are testable and deterministic."""

    def now(self) -> datetime:
        """Return the current time as an aware UTC datetime."""
        ...


class MonotonicClock(Protocol):
    """A clock that never goes backwards, used to space requests."""

    def monotonic(self) -> float:
        """Return a monotonically increasing number of seconds."""
        ...


class Sleeper(Protocol):
    """Blocking delay, injected so the test suite never actually waits."""

    def sleep(self, seconds: float) -> None:
        """Block for ``seconds``."""
        ...


class IdGenerator(Protocol):
    """Run identifiers."""

    def new_run_id(self) -> str:
        """Return a fresh, unique run identifier."""
        ...


class RobotsPolicy(Protocol):
    """Evaluates a host's robots.txt. Cannot fetch pages (Rule 1, interface segregation)."""

    def evaluate(self, url: str, product_token: str) -> RobotsDecision:
        """Decide whether ``product_token`` may fetch ``url``. Fail-closed (SPEC 6.2.2)."""
        ...

    def sitemaps(self, url: str) -> tuple[str, ...]:
        """Return the ``Sitemap:`` directives of the host's robots.txt (SPEC 5.6).

        Read from the body already fetched for the robots decision, so discovery
        costs no extra request.
        """
        ...


class RateLimiter(Protocol):
    """Enforces a minimum interval between requests to the same host."""

    def acquire(self, host: str, minimum_interval: float) -> None:
        """Block until ``host`` may be requested again."""
        ...


class PageFetcher(Protocol):
    """The only way anything in this product reaches the network.

    An implementation is responsible for robots.txt evaluation on every URL and
    every redirect hop, scope confinement of redirects, rate limiting, the body
    size cap and the honest User-Agent. The crawl use case receives one of these
    and nothing else — never a session, never a robots policy, never a rate
    limiter — which is what makes all of it unforgettable (SPEC 6.1).
    """

    def fetch(
        self, url: str, accepted_media_types: frozenset[str] = HTML_MEDIA_TYPES
    ) -> FetchedPage:
        """Retrieve ``url``.

        Raises:
            RobotsDeniedError: the host's robots.txt disallows the path, on the
                URL itself or on any redirect hop.
            OffScopeRedirectError: a redirect hop left the crawl scope.
            TooManyRedirectsError: more hops than the limit, or a loop.
            UnsupportedContentTypeError: the media type is not in
                ``accepted_media_types``; the body was not read.
            ResponseTooLargeError: the body exceeded the size cap.
            RateLimitedError: the host answered 429.
            HttpStatusError: any other unusable status.
            TransportError: no response at all.
            PageBudgetExhaustedError: the run's request ceiling was reached.
        """
        ...

    def sitemaps(self, url: str) -> tuple[str, ...]:
        """Return the ``Sitemap:`` directives governing ``url`` (SPEC 5.6)."""
        ...

    @property
    def requests_made(self) -> int:
        """How many content requests this fetcher has issued, robots.txt excluded."""
        ...


class PageExtractionPipeline(Protocol):
    """Runs every extraction layer over one fetched page."""

    def extract(self, page: FetchedPage, region: str) -> tuple[RawField, ...]:
        """Return every candidate the configured layers can read from ``page``.

        Raises:
            SelectorNotFoundError: the response is not the document this parser
                was written against.
        """
        ...


class LinkExtractor(Protocol):
    """Reads the outbound links of one page, unresolved and uncanonicalized."""

    def links(self, page: FetchedPage) -> tuple[str, ...]:
        """Return every ``href`` the document carries, in document order."""
        ...


class SitemapReader(Protocol):
    """Reads ``<loc>`` values out of a sitemap or a sitemap index (SPEC 5.6)."""

    def locations(self, document: FetchedPage) -> tuple[str, ...]:
        """Return the ``<loc>`` values, capped at the documented maximum.

        Raises:
            SelectorNotFoundError: the document is neither a urlset nor an index.
        """
        ...

    def is_index(self, document: FetchedPage) -> bool:
        """Whether the document is a sitemap index, whose locations are sitemaps."""
        ...


class SecurityTxtReader(Protocol):
    """Parses ``/.well-known/security.txt`` per RFC 9116 (SPEC 5.6)."""

    def findings(self, document: FetchedPage) -> tuple[RawField, ...]:
        """Return the contact and encryption values the file publishes.

        Raises:
            ResponseTooLargeError: the file exceeds one of the RFC 9116 limits
                a parser may decline.
            SelectorNotFoundError: the file carries none of the required fields.
        """
        ...


class CrawlObserver(Protocol):
    """Where the crawl reports what it is doing (SPEC 7.6).

    The crawl knows nothing about Qt: the adapter that turns these calls into
    signals lives in ``interfaces``. Every method must be cheap and must not
    raise; an observer that fails is a bug in the observer, not in the crawl.
    """

    def crawl_started(self, target: CrawlTarget, settings: CrawlSettings) -> None:
        """Announce the target and the limits, before any content request."""
        ...

    def page_finished(self, outcome: PageOutcome) -> None:
        """Report one URL's outcome, whether or not it was ever requested."""
        ...

    def frontier_changed(self, queued: int, deepest_depth: int) -> None:
        """Report the frontier size and the deepest depth reached so far.

        Called once per dequeue rather than per discovered URL, so the interface
        can render the authoritative progress label of SPEC 7.3 without a signal
        per row (NFR-11).
        """
        ...

    def findings_updated(self, findings: tuple[Finding, ...]) -> None:
        """Report the current deduplicated findings, in export order."""
        ...

    def crawl_finished(self, report: SiteReport) -> None:
        """Report the terminal outcome and the complete report."""
        ...


class CancellationToken(Protocol):
    """Cooperative cancellation, checked between fetches and never inside one."""

    def is_cancelled(self) -> bool:
        """Whether the operator has asked the crawl to stop."""
        ...


class ResultWriter(Protocol):
    """Serializes a report. Cannot read anything back (Rule 1, interface segregation)."""

    @property
    def format_name(self) -> str:
        """The export format this writer produces."""
        ...

    def write(self, report: SiteReport, destination_dir: Path) -> tuple[Path, ...]:
        """Write the report into ``destination_dir`` and return the files created."""
        ...


class ReportLoader(Protocol):
    """Reads a canonical ``report.json`` back, so a run can be re-exported."""

    def load(self, path: Path) -> SiteReport:
        """Return the report stored at ``path``.

        Raises:
            ConfigurationError: the file is missing or is not a report of a
                schema version this build understands.
        """
        ...


class RunLedger(Protocol):
    """Append-only index of runs, so the Runs pane works without a database."""

    def record(self, entry: LedgerEntry) -> None:
        """Append one entry."""
        ...

    def find(
        self, target_host: str | None = None, run_id: str | None = None
    ) -> Sequence[LedgerEntry]:
        """Return entries matching the given filters."""
        ...

    def forget(self, run_ids: frozenset[str]) -> None:
        """Rewrite the ledger without the given runs."""
        ...


class DirectoryRemover(Protocol):
    """Filesystem deletion, injected so erasure is testable without real files."""

    def remove_tree(self, path: Path) -> tuple[Path, ...]:
        """Delete ``path`` recursively and return what was removed."""
        ...

    def size_of(self, path: Path) -> int:
        """Return the total size in bytes of ``path``, or 0 when it is gone."""
        ...


@runtime_checkable
class FieldValidator(Protocol):
    """Turns one raw candidate into a storable value, or rejects it."""

    @property
    def field(self) -> FieldName:
        """The field this validator is responsible for."""
        ...

    def validate(self, candidate: RawField, region: str) -> ValidatedValue:
        """Return the canonical value.

        Raises:
            ValidationRejectedError: the candidate must never be exported as fact.
        """
        ...
