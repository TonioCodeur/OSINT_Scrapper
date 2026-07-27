"""Shared fakes, and the proof that this suite never touches the network (NFR-6)."""

from __future__ import annotations

import socket
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from requests.structures import CaseInsensitiveDict

from osint_scrapper.application.errors import InfrastructureError, TransportError
from osint_scrapper.application.ports import (
    HTML_MEDIA_TYPES,
    FetchedPage,
    LedgerEntry,
    RobotsDecision,
)
from osint_scrapper.domain.attributes import Finding
from osint_scrapper.domain.crawl import PageOutcome
from osint_scrapper.domain.report import SiteReport
from osint_scrapper.domain.target import CrawlSettings, CrawlTarget
from osint_scrapper.infrastructure.http.robots import RobotsFile

FIXTURES = Path(__file__).parent / "fixtures"
SITE = FIXTURES / "site"
START_TIME = datetime(2026, 7, 27, 14, 2, 11, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make any accidental network call fail loudly instead of silently succeeding."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise RuntimeError("the test suite must not open a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def read_fixture(*parts: str) -> str:
    """Return the text of a committed fixture."""
    return FIXTURES.joinpath(*parts).read_text(encoding="utf-8")


def site_fixture(name: str) -> bytes:
    """Return one file of the committed mini-site as bytes."""
    return (SITE / name).read_bytes()


def make_page(
    text: str,
    url: str = "https://example.com/contact",
    content_type: str = "text/html; charset=utf-8",
    headers: Mapping[str, str] | None = None,
    fetched_at: datetime = START_TIME,
) -> FetchedPage:
    """Build a fetched page without going anywhere near a socket."""
    return FetchedPage(
        url=url,
        status_code=200,
        content_type=content_type,
        text=text,
        fetched_at=fetched_at,
        headers=dict(headers or {}),
    )


class FakeClock:
    """A wall clock that advances only when a test says so."""

    def __init__(self, start: datetime = START_TIME, step_seconds: float = 1.0) -> None:
        self._now = start
        self._step = timedelta(seconds=step_seconds)

    def now(self) -> datetime:
        """Return the current time and advance it, so timestamps stay distinguishable."""
        current = self._now
        self._now += self._step
        return current


class FrozenClock:
    """A wall clock that never moves, for cache-expiry and ordering tests."""

    def __init__(self, start: datetime = START_TIME) -> None:
        self.moment = start

    def now(self) -> datetime:
        """Return the moment the test set."""
        return self.moment


class FakeMonotonicClock:
    """A monotonic clock a test drives by hand."""

    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        """Return the value the test set."""
        return self.value


class FakeSleeper:
    """Records requested delays and applies them to a fake monotonic clock."""

    def __init__(self, clock: FakeMonotonicClock | None = None) -> None:
        self.slept: list[float] = []
        self._clock = clock

    def sleep(self, seconds: float) -> None:
        """Record the delay without ever blocking the test run."""
        self.slept.append(seconds)
        if self._clock is not None:
            self._clock.value += seconds


class FakeIdGenerator:
    """Deterministic run identifiers, so exports are byte-comparable."""

    def __init__(self, run_id: str = "r-testrun1") -> None:
        self._run_id = run_id

    def new_run_id(self) -> str:
        """Return the fixed identifier."""
        return self._run_id


class RecordingObserver:
    """A crawl observer that keeps everything it was told."""

    def __init__(self) -> None:
        self.started: list[tuple[CrawlTarget, CrawlSettings]] = []
        self.pages: list[PageOutcome] = []
        self.frontier: list[tuple[int, int]] = []
        self.findings: list[tuple[Finding, ...]] = []
        self.finished: list[SiteReport] = []

    def crawl_started(self, target: CrawlTarget, settings: CrawlSettings) -> None:
        """Record the announced target and limits."""
        self.started.append((target, settings))

    def page_finished(self, outcome: PageOutcome) -> None:
        """Record one page outcome."""
        self.pages.append(outcome)

    def frontier_changed(self, queued: int, deepest_depth: int) -> None:
        """Record the frontier size and the deepest depth reached."""
        self.frontier.append((queued, deepest_depth))

    def findings_updated(self, findings: tuple[Finding, ...]) -> None:
        """Record a findings batch."""
        self.findings.append(findings)

    def crawl_finished(self, report: SiteReport) -> None:
        """Record the terminal report."""
        self.finished.append(report)


class NeverCancelled:
    """A cancellation token the operator never sets."""

    def is_cancelled(self) -> bool:
        """Always False."""
        return False


class ManualCancellation:
    """A cancellation token a test flips, optionally after N checks."""

    def __init__(self, after_checks: int | None = None) -> None:
        self.cancelled = False
        self.checks = 0
        self._after_checks = after_checks

    def cancel(self) -> None:
        """Ask the crawl to stop."""
        self.cancelled = True

    def is_cancelled(self) -> bool:
        """Report whether the operator has stopped the crawl."""
        self.checks += 1
        if self._after_checks is not None and self.checks > self._after_checks:
            self.cancelled = True
        return self.cancelled


class FakeRobotsTransport:
    """Serves canned robots.txt responses, or raises the failure a test wants."""

    def __init__(
        self,
        responses: Mapping[str, RobotsFile | InfrastructureError] | None = None,
        default: RobotsFile | InfrastructureError | None = None,
    ) -> None:
        self._responses = dict(responses or {})
        self._default = default or RobotsFile(status_code=404, body=b"", final_url="")
        self.requested: list[str] = []

    def get(self, url: str) -> RobotsFile:
        """Return the canned response for ``url``."""
        self.requested.append(url)
        response = self._responses.get(url, self._default)
        if isinstance(response, InfrastructureError):
            raise response
        return response


class AllowAllRobotsPolicy:
    """A robots policy that allows everything, for tests about something else."""

    def __init__(
        self, crawl_delay: float | None = None, sitemaps: tuple[str, ...] = ()
    ) -> None:
        self.crawl_delay = crawl_delay
        self.declared_sitemaps = sitemaps
        self.evaluated: list[str] = []

    def evaluate(self, url: str, product_token: str) -> RobotsDecision:
        """Allow ``url``."""
        del product_token
        self.evaluated.append(url)
        return RobotsDecision(
            allowed=True,
            reason="robots_allow_rule",
            robots_url="https://example.com/robots.txt",
            crawl_delay=self.crawl_delay,
        )

    def sitemaps(self, url: str) -> tuple[str, ...]:
        """Return the sitemaps the test declared."""
        del url
        return self.declared_sitemaps


class DenyAllRobotsPolicy:
    """A robots policy that denies everything."""

    def __init__(self, reason: str = "robots_disallow") -> None:
        self.reason = reason

    def evaluate(self, url: str, product_token: str) -> RobotsDecision:
        """Deny ``url``."""
        del url, product_token
        return RobotsDecision(
            allowed=False, reason=self.reason, robots_url="https://example.com/robots.txt"
        )

    def sitemaps(self, url: str) -> tuple[str, ...]:
        """A denied host declares nothing."""
        del url
        return ()


class NoOpRateLimiter:
    """Records what would have been throttled without waiting."""

    def __init__(self) -> None:
        self.acquired: list[tuple[str, float]] = []

    def acquire(self, host: str, minimum_interval: float) -> None:
        """Record the call."""
        self.acquired.append((host, minimum_interval))


@dataclass(frozen=True)
class Route:
    """One canned HTTP response in the fake transport."""

    body: bytes = b""
    status: int = 200
    content_type: str = "text/html; charset=utf-8"
    location: str | None = None
    extra_headers: Mapping[str, str] = field(default_factory=dict)


class FakeResponse:
    """The slice of ``requests.Response`` this product actually uses."""

    def __init__(self, url: str, route: Route) -> None:
        self.url = url
        self.status_code = route.status
        self.headers: CaseInsensitiveDict[str] = CaseInsensitiveDict()
        if route.content_type:
            self.headers["Content-Type"] = route.content_type
        if route.location is not None:
            self.headers["Location"] = route.location
        for name, value in route.extra_headers.items():
            self.headers[name] = value
        self._body = route.body
        self.closed = False

    def iter_content(self, chunk_size: int = 8192) -> Iterator[bytes]:
        """Yield the body in chunks, exactly as ``requests`` does when streaming."""
        for start in range(0, len(self._body), chunk_size):
            yield self._body[start : start + chunk_size]

    def close(self) -> None:
        """Release the response."""
        self.closed = True

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class FakeHttpSession:
    """A ``requests.Session`` stand-in backed by a route table.

    Faking here rather than at the :class:`PageFetcher` port is deliberate: it
    keeps the real robots policy, the real rate limiter, the real per-hop
    redirect gating and the real body caps in the path under test. A fake
    fetcher would bypass every one of them.
    """

    def __init__(self, routes: Mapping[str, Route] | None = None) -> None:
        self.routes = dict(routes or {})
        self.requested: list[str] = []
        self.headers: dict[str, str] = {}
        self.max_redirects = 5

    @property
    def request_count(self) -> int:
        """How many HTTP requests were issued in total, robots.txt included."""
        return len(self.requested)

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        """Return the canned response for ``url``, or a 404."""
        del kwargs
        self.requested.append(url)
        route = self.routes.get(url)
        if route is None:
            return FakeResponse(url, Route(status=404, body=b"not found"))
        if isinstance(route, InfrastructureError):
            raise route
        return FakeResponse(url, route)


class RaisingHttpSession(FakeHttpSession):
    """A session that raises a transport failure for the URLs a test names."""

    def __init__(
        self, routes: Mapping[str, Route] | None = None, failing: frozenset[str] = frozenset()
    ) -> None:
        super().__init__(routes)
        self._failing = failing

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        """Raise for a named URL, otherwise behave normally."""
        if url in self._failing:
            self.requested.append(url)
            raise TransportError(f"{url}: connection reset by the test")
        return super().get(url, **kwargs)


class FakePageFetcher:
    """Serves canned pages and counts every request, so tests can assert on cost."""

    def __init__(
        self,
        pages: Mapping[str, FetchedPage | InfrastructureError] | None = None,
        declared_sitemaps: tuple[str, ...] = (),
    ) -> None:
        self._pages = dict(pages or {})
        self._declared_sitemaps = declared_sitemaps
        self.requested: list[str] = []
        self._requests_made = 0

    @property
    def requests_made(self) -> int:
        """How many fetches were attempted."""
        return self._requests_made

    def sitemaps(self, url: str) -> tuple[str, ...]:
        """Return the sitemaps the test declared."""
        del url
        return self._declared_sitemaps

    def fetch(
        self, url: str, accepted_media_types: frozenset[str] = HTML_MEDIA_TYPES
    ) -> FetchedPage:
        """Return the canned page for ``url``, or raise what the test registered."""
        del accepted_media_types
        self.requested.append(url)
        self._requests_made += 1
        page = self._pages.get(url)
        if page is None:
            raise TransportError(f"no canned response for {url}")
        if isinstance(page, InfrastructureError):
            raise page
        return page


class InMemoryLedger:
    """A run ledger held in a list."""

    def __init__(self) -> None:
        self.entries: list[LedgerEntry] = []

    def record(self, entry: LedgerEntry) -> None:
        """Append an entry."""
        self.entries.append(entry)

    def find(
        self, target_host: str | None = None, run_id: str | None = None
    ) -> list[LedgerEntry]:
        """Return matching entries."""
        return [
            entry
            for entry in self.entries
            if (target_host is None or entry.target_host == target_host)
            and (run_id is None or entry.run_id == run_id)
        ]

    def forget(self, run_ids: frozenset[str]) -> None:
        """Drop the given runs."""
        self.entries = [entry for entry in self.entries if entry.run_id not in run_ids]


class RecordingRemover:
    """A directory remover that records rather than deletes."""

    def __init__(self, sizes: Mapping[str, int] | None = None) -> None:
        self.removed: list[Path] = []
        self._sizes = dict(sizes or {})

    def remove_tree(self, path: Path) -> tuple[Path, ...]:
        """Record ``path`` as removed."""
        self.removed.append(path)
        return (path,)

    def size_of(self, path: Path) -> int:
        """Return the size the test declared, or zero."""
        return self._sizes.get(path.as_posix(), 0)


@pytest.fixture
def fixture_dir() -> Iterator[Path]:
    """The committed fixtures directory."""
    yield FIXTURES
