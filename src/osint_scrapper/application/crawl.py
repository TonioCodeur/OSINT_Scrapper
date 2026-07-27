"""The crawl use case: scope, frontier, discovery, extraction and the abort rules.

This is the seam that makes the whole product testable without Qt. It receives a
:class:`PageFetcher` and nothing else that can reach the network, an observer to
report through and a cancellation token to check between fetches, and it runs to
completion under ``pytest`` with no ``QApplication`` anywhere (SPEC 4, AC-ARCH-7).
"""

from __future__ import annotations

import logging
import random
import threading
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from osint_scrapper.application.aggregate import FindingAggregator
from osint_scrapper.application.errors import (
    HttpStatusError,
    OffScopeRedirectError,
    PageBudgetExhaustedError,
    RateLimitedError,
    ResponseTooLargeError,
    RobotsDeniedError,
    SelectorNotFoundError,
    TooManyRedirectsError,
    TransportError,
    UnsupportedContentTypeError,
)
from osint_scrapper.application.frontier import Frontier, FrontierItem, VisitedSet
from osint_scrapper.application.ports import (
    HTML_MEDIA_TYPES,
    PLAIN_TEXT_MEDIA_TYPES,
    SITEMAP_MEDIA_TYPES,
    CancellationToken,
    Clock,
    CrawlObserver,
    FetchedPage,
    IdGenerator,
    LinkExtractor,
    PageExtractionPipeline,
    PageFetcher,
    SecurityTxtReader,
    SitemapReader,
    Sleeper,
)
from osint_scrapper.application.validation import ValidationPolicy
from osint_scrapper.domain.attributes import RawField
from osint_scrapper.domain.crawl import (
    ATTEMPTED_STATUSES,
    CONSECUTIVE_FAILURES_BEFORE_ABORT,
    CONSECUTIVE_RATE_LIMITS_BEFORE_ABORT,
    FAILED_STATUSES,
    FETCHED_STATUSES,
    MAXIMUM_ERROR_RATE,
    MAXIMUM_RETRY_AFTER_SECONDS,
    MINIMUM_FETCHES_BEFORE_ERROR_RATE,
    UNHEALTHY_STATUSES,
    CrawlOutcome,
    PageOutcome,
    PageStatus,
)
from osint_scrapper.domain.errors import SeedRefusedError, UrlRejectedError
from osint_scrapper.domain.report import SiteReport
from osint_scrapper.domain.target import CrawlSettings, CrawlTarget, Purpose
from osint_scrapper.domain.url import CrawlScope, UrlRejection, canonicalize, has_skipped_extension

logger = logging.getLogger(__name__)

SECURITY_TXT_PATH = "/.well-known/security.txt"
DEFAULT_SITEMAP_PATH = "/sitemap.xml"

MAXIMUM_SITEMAP_DOCUMENTS = 5
"""SPEC 5.6. Stricter than sitemaps.org, deliberately."""

RATE_LIMIT_BACKOFF_SECONDS = (2.0, 4.0, 8.0)
"""Applied to consecutive 429s that carried no ``Retry-After`` (SPEC 5.10)."""

JITTER_FRACTION = 0.5

DISCOVERY_DEPTH = 1
"""URLs found through a sitemap or ``security.txt`` enter at depth 1 (SPEC 5.1)."""

SEED_REFUSAL_STATUSES = frozenset(
    {
        PageStatus.SKIPPED_ROBOTS,
        PageStatus.TRANSPORT_ERROR,
        PageStatus.HTTP_ERROR,
        PageStatus.RATE_LIMITED,
        PageStatus.TOO_MANY_REDIRECTS,
        PageStatus.OFF_SCOPE_REDIRECT,
    }
)
"""A target we cannot lawfully or physically reach is a refusal to start, not an abort."""

Jitter = Callable[[], float]
"""Returns a value in ``[0, 1)``. Injected so a test can make backoff exact."""

_REJECTION_STATUS = {
    UrlRejection.CREDENTIALS_IN_URL: PageStatus.CREDENTIALS_IN_URL,
    UrlRejection.REJECTED_SHAPE: PageStatus.URL_REJECTED_SHAPE,
}


class _RequestKind(StrEnum):
    """What a fetched document is for, which decides how it is parsed."""

    PAGE = "page"
    SITEMAP = "sitemap"
    SECURITY_TXT = "security_txt"


@dataclass
class _PageResult:
    """What one worker produced for one URL, before anything is aggregated."""

    url: str
    depth: int
    status: PageStatus
    detail: str | None = None
    http_status: int | None = None
    content_type: str | None = None
    final_url: str | None = None
    robots_url: str | None = None
    candidates: tuple[RawField, ...] = ()
    links: tuple[str, ...] = ()
    retry_after: float | None = None
    sitemap_locations: tuple[str, ...] = ()
    sitemap_is_index: bool = False


@dataclass
class _Health:
    """The abort thresholds of SPEC 5.10, counted in one place."""

    attempted: int = 0
    failed: int = 0
    consecutive_failures: int = 0
    consecutive_rate_limits: int = 0
    outcome: CrawlOutcome | None = None
    detail: str | None = None

    def record(self, status: PageStatus, retry_after: float | None) -> None:
        """Update the counters from one attempted fetch and arm an abort if due.

        Statuses outside :data:`ATTEMPTED_STATUSES` are ignored entirely rather
        than counted as failures. ``skipped_robots``, ``skipped_budget``,
        ``skipped_content_type`` and ``off_scope_redirect`` are this product
        declining to use a URL, not the host misbehaving, and none of them may
        move a threshold that exists to detect an unhealthy host.
        """
        if status not in ATTEMPTED_STATUSES:
            return
        self.attempted += 1
        self.consecutive_rate_limits = (
            self.consecutive_rate_limits + 1 if status is PageStatus.RATE_LIMITED else 0
        )
        self.consecutive_failures = (
            self.consecutive_failures + 1 if status in UNHEALTHY_STATUSES else 0
        )
        if status in FAILED_STATUSES:
            self.failed += 1

        if retry_after is not None and retry_after > MAXIMUM_RETRY_AFTER_SECONDS:
            self._arm(
                CrawlOutcome.ABORTED_RATE_LIMITED,
                f"the host asked us to wait {retry_after:.0f}s, above the "
                f"{MAXIMUM_RETRY_AFTER_SECONDS:.0f}s ceiling",
            )
        elif self.consecutive_rate_limits >= CONSECUTIVE_RATE_LIMITS_BEFORE_ABORT:
            self._arm(
                CrawlOutcome.ABORTED_RATE_LIMITED,
                f"{self.consecutive_rate_limits} consecutive 429 responses from the host",
            )
        elif self.consecutive_failures >= CONSECUTIVE_FAILURES_BEFORE_ABORT:
            self._arm(
                CrawlOutcome.ABORTED_HOST_UNHEALTHY,
                f"{self.consecutive_failures} consecutive fetch failures",
            )
        elif (
            self.attempted >= MINIMUM_FETCHES_BEFORE_ERROR_RATE
            and self.failed / self.attempted > MAXIMUM_ERROR_RATE
        ):
            self._arm(
                CrawlOutcome.ABORTED_ERROR_RATE,
                f"{self.failed} of {self.attempted} attempted fetches failed",
            )

    def _arm(self, outcome: CrawlOutcome, detail: str) -> None:
        if self.outcome is None:
            self.outcome = outcome
            self.detail = detail


@dataclass
class _RunState:
    """Everything one execution accumulates. A use case instance runs once."""

    frontier: Frontier = field(default_factory=Frontier)
    visited: VisitedSet = field(default_factory=VisitedSet)
    logged: set[str] = field(default_factory=set)
    outcomes: list[PageOutcome] = field(default_factory=list)
    health: _Health = field(default_factory=_Health)
    budget_used: int = 0
    deepest_depth: int = 0
    sitemap_documents: int = 0
    budget_exhausted: bool = False
    depth_limited: bool = False
    lock: threading.RLock = field(default_factory=threading.RLock)


class CrawlSiteUseCase:
    """Crawls one site within its scope, its budget, its depth and its manners.

    A fresh instance runs exactly one crawl: it holds the frontier, the visited
    set, the aggregator and the health counters for that run.
    """

    def __init__(
        self,
        fetcher: PageFetcher,
        pipeline: PageExtractionPipeline,
        validation: ValidationPolicy,
        link_extractor: LinkExtractor,
        sitemap_reader: SitemapReader,
        security_txt_reader: SecurityTxtReader,
        clock: Clock,
        sleeper: Sleeper,
        id_generator: IdGenerator,
        observer: CrawlObserver,
        cancellation: CancellationToken,
        tool_name: str,
        tool_version: str,
        user_agent: str,
        jitter: Jitter = random.random,
    ) -> None:
        self._fetcher = fetcher
        self._pipeline = pipeline
        self._link_extractor = link_extractor
        self._sitemap_reader = sitemap_reader
        self._security_txt_reader = security_txt_reader
        self._clock = clock
        self._sleeper = sleeper
        self._id_generator = id_generator
        self._observer = observer
        self._cancellation = cancellation
        self._tool_name = tool_name
        self._tool_version = tool_version
        self._user_agent = user_agent
        self._jitter = jitter
        self._aggregator = FindingAggregator(validation)

    def execute(
        self, target: CrawlTarget, settings: CrawlSettings, purpose: Purpose
    ) -> SiteReport:
        """Crawl ``target`` and return the report, whatever the terminal outcome.

        Writes nothing to disk: export and the ledger are a separate operator
        action, so a refused run leaves no trace at all.

        Raises:
            SeedRefusedError: ``robots.txt`` disallows the target itself, or the
                target is unreachable. The run never started (SPEC 5.10).
        """
        state = _RunState()
        scope = target.scope
        started_at = self._clock.now()
        run_id = self._id_generator.new_run_id()
        self._observer.crawl_started(target, settings)

        seed = self._fetch_seed(state, target, settings.phone_region)
        self._absorb(state, seed, target, settings, scope)
        self._discover(state, target, settings, scope)

        outcome, detail = self._crawl(state, target, settings, scope)
        return self._report(
            state, run_id, target, settings, purpose, started_at, outcome, detail
        )

    # -- start ------------------------------------------------------------------

    def _fetch_seed(
        self, state: _RunState, target: CrawlTarget, region: str
    ) -> _PageResult:
        """Fetch the target itself, or refuse the run before anything exists."""
        url = target.target_url
        state.visited.claim(url)
        state.budget_used = 1
        result = self._process(url, 0, HTML_MEDIA_TYPES, _RequestKind.PAGE, region)
        if result.status in SEED_REFUSAL_STATUSES:
            raise SeedRefusedError(
                url=url,
                reason=str(result.status),
                detail=result.detail or "the target could not be retrieved",
                robots_url=result.robots_url,
            )
        return result

    def _discover(
        self,
        state: _RunState,
        target: CrawlTarget,
        settings: CrawlSettings,
        scope: CrawlScope,
    ) -> None:
        """Run the three discovery sources of SPEC 5.6, once, at the start."""
        self._read_security_txt(state, target, settings, scope)
        if settings.follow_sitemap:
            self._read_sitemaps(state, target, settings, scope)

    def _read_security_txt(
        self,
        state: _RunState,
        target: CrawlTarget,
        settings: CrawlSettings,
        scope: CrawlScope,
    ) -> None:
        try:
            url = canonicalize(SECURITY_TXT_PATH, base=target.target_url)
        except UrlRejectedError:
            return
        if not state.visited.claim(url) or not self._spend_budget(state, settings):
            return
        result = self._process(
            url, 0, PLAIN_TEXT_MEDIA_TYPES, _RequestKind.SECURITY_TXT, settings.phone_region
        )
        self._absorb(state, result, target, settings, scope)

    def _read_sitemaps(
        self,
        state: _RunState,
        target: CrawlTarget,
        settings: CrawlSettings,
        scope: CrawlScope,
    ) -> None:
        """Read the declared sitemaps, or ``/sitemap.xml`` when none was declared.

        A sitemap index is followed exactly one level; the whole run reads at
        most five sitemap documents, whatever sitemaps.org permits.
        """
        declared = self._fetcher.sitemaps(target.target_url)
        pending: Sequence[str] = declared or (DEFAULT_SITEMAP_PATH,)
        for level in range(2):
            next_level: list[str] = []
            for raw in pending:
                if state.sitemap_documents >= MAXIMUM_SITEMAP_DOCUMENTS:
                    return
                result = self._read_one_sitemap(state, raw, target, settings, scope)
                if result is None:
                    continue
                if result.sitemap_is_index:
                    # Recursion is one level only. A second index's locations are
                    # dropped entirely rather than queued as pages, because they
                    # are sitemaps and this run has stopped following sitemaps.
                    if level == 0:
                        next_level.extend(result.sitemap_locations)
                else:
                    self._enqueue(
                        state,
                        result.sitemap_locations,
                        target.target_url,
                        DISCOVERY_DEPTH - 1,
                        settings,
                        scope,
                    )
            if not next_level:
                return
            pending = next_level

    def _read_one_sitemap(
        self,
        state: _RunState,
        raw: str,
        target: CrawlTarget,
        settings: CrawlSettings,
        scope: CrawlScope,
    ) -> _PageResult | None:
        try:
            url = canonicalize(raw, base=target.target_url)
        except UrlRejectedError:
            return None
        if not scope.contains(url):
            self._record(state, PageOutcome(url, 0, PageStatus.SKIPPED_OFF_SCOPE))
            return None
        if not state.visited.claim(url):
            return None
        if not self._spend_budget(state, settings):
            self._record(state, PageOutcome(url, 0, PageStatus.SKIPPED_BUDGET))
            return None
        state.sitemap_documents += 1
        result = self._process(
            url, 0, SITEMAP_MEDIA_TYPES, _RequestKind.SITEMAP, settings.phone_region
        )
        self._absorb(state, result, target, settings, scope, enqueue_links=False)
        return result

    # -- the loop ---------------------------------------------------------------

    def _crawl(
        self,
        state: _RunState,
        target: CrawlTarget,
        settings: CrawlSettings,
        scope: CrawlScope,
    ) -> tuple[CrawlOutcome, str | None]:
        """Drive the frontier to exhaustion, a limit, an abort or a stop.

        Results are consumed in *claim* order rather than completion order. That
        keeps real concurrency — several fetches are in flight — while making the
        crawl itself deterministic, which is what lets AC-CRAWL-9 hold: the same
        run at ``concurrent_requests=1`` and ``=2`` produces identical exports.
        """
        workers = settings.concurrent_requests
        pending: deque[Future[_PageResult]] = deque()
        outcome: CrawlOutcome | None = None

        with ThreadPoolExecutor(max_workers=workers) as pool:
            while True:
                outcome = outcome or self._terminal_outcome(state)
                if outcome is None:
                    while len(pending) < workers:
                        item = self._claim(state, settings)
                        if item is None:
                            break
                        pending.append(
                            pool.submit(
                                self._process,
                                item.url,
                                item.depth,
                                HTML_MEDIA_TYPES,
                                _RequestKind.PAGE,
                                settings.phone_region,
                            )
                        )
                    if not pending and state.budget_exhausted:
                        outcome = CrawlOutcome.BUDGET_EXHAUSTED
                if not pending:
                    break
                result = pending.popleft().result()
                self._absorb(state, result, target, settings, scope)
                if result.status is PageStatus.RATE_LIMITED and state.health.outcome is None:
                    self._back_off(state, result.retry_after)

        if outcome is None:
            outcome = (
                CrawlOutcome.DEPTH_EXHAUSTED if state.depth_limited else CrawlOutcome.COMPLETED
            )
        if outcome is CrawlOutcome.BUDGET_EXHAUSTED:
            self._drain_frontier(state)
        return outcome, state.health.detail if outcome is state.health.outcome else None

    def _terminal_outcome(self, state: _RunState) -> CrawlOutcome | None:
        """Whether the operator or a threshold has ended the run (SPEC 5.10, 7.6)."""
        if self._cancellation.is_cancelled():
            return CrawlOutcome.STOPPED_BY_OPERATOR
        return state.health.outcome

    def _claim(self, state: _RunState, settings: CrawlSettings) -> FrontierItem | None:
        """Take the next URL nobody else has taken, within the page budget."""
        with state.lock:
            if state.budget_used >= settings.max_pages:
                state.budget_exhausted = True
                return None
            while True:
                item = state.frontier.pop()
                if item is None:
                    return None
                if state.visited.claim(item.url):
                    break
            state.budget_used += 1
            state.deepest_depth = max(state.deepest_depth, item.depth)
            queued = len(state.frontier)
            deepest = state.deepest_depth
        self._observer.frontier_changed(queued, deepest)
        return item

    def _spend_budget(self, state: _RunState, settings: CrawlSettings) -> bool:
        """Reserve one content request, or report that the budget is gone."""
        with state.lock:
            if state.budget_used >= settings.max_pages:
                state.budget_exhausted = True
                return False
            state.budget_used += 1
            return True

    def _drain_frontier(self, state: _RunState) -> None:
        """Report the URLs the budget stopped us from reaching (SPEC FR-7)."""
        for item in state.frontier.drain():
            self._record(state, PageOutcome(item.url, item.depth, PageStatus.SKIPPED_BUDGET))

    def _back_off(self, state: _RunState, retry_after: float | None) -> None:
        """Wait as the host asked, or on the documented curve when it did not."""
        if retry_after is not None:
            self._sleeper.sleep(min(retry_after, MAXIMUM_RETRY_AFTER_SECONDS))
            return
        index = min(state.health.consecutive_rate_limits, len(RATE_LIMIT_BACKOFF_SECONDS)) - 1
        base = RATE_LIMIT_BACKOFF_SECONDS[max(index, 0)]
        self._sleeper.sleep(base * (1.0 + self._jitter() * JITTER_FRACTION))

    # -- one URL ----------------------------------------------------------------

    def _process(
        self,
        url: str,
        depth: int,
        accepted: frozenset[str],
        kind: _RequestKind,
        region: str,
    ) -> _PageResult:
        """Fetch and parse one URL. Runs on a worker thread; never raises.

        A failure here degrades this page and nothing else (SPEC FR-7).
        """
        try:
            page = self._fetcher.fetch(url, accepted)
        except RobotsDeniedError as denial:
            return _PageResult(
                url, depth, PageStatus.SKIPPED_ROBOTS, detail=str(denial),
                robots_url=denial.robots_url,
            )
        except OffScopeRedirectError as redirect:
            return _PageResult(url, depth, PageStatus.OFF_SCOPE_REDIRECT, detail=str(redirect))
        except TooManyRedirectsError as failure:
            return _PageResult(url, depth, PageStatus.TOO_MANY_REDIRECTS, detail=str(failure))
        except UnsupportedContentTypeError as wrong:
            return _PageResult(
                url, depth, PageStatus.SKIPPED_CONTENT_TYPE,
                detail=str(wrong), content_type=wrong.media_type,
            )
        except ResponseTooLargeError as oversized:
            return _PageResult(url, depth, PageStatus.TOO_LARGE, detail=str(oversized))
        except RateLimitedError as limited:
            return _PageResult(
                url, depth, PageStatus.RATE_LIMITED, detail=str(limited),
                http_status=limited.status_code, retry_after=limited.retry_after,
            )
        except HttpStatusError as failure:
            return _PageResult(
                url, depth, PageStatus.HTTP_ERROR, detail=str(failure),
                http_status=failure.status_code,
            )
        except PageBudgetExhaustedError as exhausted:
            return _PageResult(url, depth, PageStatus.SKIPPED_BUDGET, detail=str(exhausted))
        except TransportError as failure:
            return _PageResult(url, depth, PageStatus.TRANSPORT_ERROR, detail=str(failure))
        return self._parse(page, url, depth, kind, region)

    def _parse(
        self, page: FetchedPage, url: str, depth: int, kind: _RequestKind, region: str
    ) -> _PageResult:
        """Turn a retrieved document into candidates, links or sitemap locations."""
        base = _PageResult(
            url=url,
            depth=depth,
            status=PageStatus.OK,
            http_status=page.status_code,
            content_type=page.media_type or None,
            final_url=page.url,
        )
        try:
            if kind is _RequestKind.SITEMAP:
                base.sitemap_is_index = self._sitemap_reader.is_index(page)
                base.sitemap_locations = self._sitemap_reader.locations(page)
            elif kind is _RequestKind.SECURITY_TXT:
                base.candidates = self._security_txt_reader.findings(page)
            else:
                base.candidates = self._pipeline.extract(page, region)
                base.links = self._link_extractor.links(page)
        except SelectorNotFoundError as missing:
            return _PageResult(
                url, depth, PageStatus.PARSE_ERROR, detail=str(missing),
                http_status=page.status_code, content_type=page.media_type or None,
                final_url=page.url,
            )
        except ResponseTooLargeError as oversized:
            return _PageResult(
                url, depth, PageStatus.TOO_LARGE, detail=str(oversized),
                http_status=page.status_code, content_type=page.media_type or None,
                final_url=page.url,
            )
        return base

    def _absorb(
        self,
        state: _RunState,
        result: _PageResult,
        target: CrawlTarget,
        settings: CrawlSettings,
        scope: CrawlScope,
        enqueue_links: bool = True,
    ) -> None:
        """Fold one worker's result into the run: findings, log, frontier, health."""
        del target
        final_url = result.final_url or result.url
        with state.lock:
            seen_before = final_url in state.logged
            if final_url != result.url:
                state.visited.add(final_url)
                state.logged.add(result.url)
        if seen_before:
            # Two URLs that redirect to the same page are one page. The visited
            # set catches this before the fetch whenever the first result is in
            # before the second is claimed; when concurrency claims both at once
            # it cannot, so the page is counted here exactly once instead. That
            # is what keeps a concurrent run identical to a serial one (NFR-9).
            logger.debug("%s resolves to %s, which is already recorded", result.url, final_url)
            return

        accepted = self._aggregator.add(result.candidates, settings.phone_region)
        status = result.status
        if status is PageStatus.OK and accepted == 0:
            status = PageStatus.NO_FINDINGS

        self._record(
            state,
            PageOutcome(
                url=final_url,
                depth=result.depth,
                status=status,
                detail=result.detail,
                http_status=result.http_status,
                content_type=result.content_type,
                findings_count=accepted,
            ),
        )
        state.health.record(status, result.retry_after)
        if accepted:
            self._observer.findings_updated(self._aggregator.findings())
        if enqueue_links and result.links:
            self._enqueue(state, result.links, final_url, result.depth, settings, scope)

    def _enqueue(
        self,
        state: _RunState,
        raw_links: Iterable[str],
        base_url: str,
        depth: int,
        settings: CrawlSettings,
        scope: CrawlScope,
    ) -> None:
        """Canonicalize, gate and queue the URLs one document pointed at."""
        child_depth = depth + 1
        for raw in raw_links:
            try:
                url = canonicalize(raw, base=base_url)
            except UrlRejectedError as rejection:
                status = _REJECTION_STATUS.get(UrlRejection(rejection.reason))
                if status is not None:
                    self._record(
                        state, PageOutcome(rejection.url, child_depth, status, rejection.detail)
                    )
                continue
            if url in state.visited or url in state.frontier:
                continue
            if not scope.contains(url):
                # Off-site links are never fetched. The social-profile extractor
                # already saw this href on the page; anything else is discarded.
                self._record(state, PageOutcome(url, child_depth, PageStatus.SKIPPED_OFF_SCOPE))
                continue
            if has_skipped_extension(url):
                self._record(state, PageOutcome(url, child_depth, PageStatus.SKIPPED_EXTENSION))
                continue
            if child_depth > settings.max_depth:
                state.depth_limited = True
                self._record(state, PageOutcome(url, child_depth, PageStatus.SKIPPED_DEPTH))
                continue
            with state.lock:
                exhausted = state.budget_used >= settings.max_pages
            if exhausted:
                state.budget_exhausted = True
                self._record(state, PageOutcome(url, child_depth, PageStatus.SKIPPED_BUDGET))
                continue
            state.frontier.push(url, child_depth)

    def _record(self, state: _RunState, outcome: PageOutcome) -> None:
        """Add one row to the page log, at most once per URL."""
        with state.lock:
            if outcome.url in state.logged:
                return
            state.logged.add(outcome.url)
            state.outcomes.append(outcome)
        self._observer.page_finished(outcome)

    # -- the end ----------------------------------------------------------------

    def _report(
        self,
        state: _RunState,
        run_id: str,
        target: CrawlTarget,
        settings: CrawlSettings,
        purpose: Purpose,
        started_at: datetime,
        outcome: CrawlOutcome,
        detail: str | None,
    ) -> SiteReport:
        findings = self._aggregator.findings()
        pages = tuple(sorted(state.outcomes, key=PageOutcome.sort_key))
        report = SiteReport(
            run_id=run_id,
            target=target,
            settings=settings,
            purpose=purpose,
            started_at=started_at,
            finished_at=self._clock.now(),
            outcome=outcome,
            outcome_detail=detail,
            tool_name=self._tool_name,
            tool_version=self._tool_version,
            user_agent=self._user_agent,
            findings=findings,
            pages=pages,
            pages_fetched=sum(1 for page in pages if page.status in FETCHED_STATUSES),
            requests_made=self._fetcher.requests_made,
        )
        self._observer.findings_updated(findings)
        self._observer.crawl_finished(report)
        return report
