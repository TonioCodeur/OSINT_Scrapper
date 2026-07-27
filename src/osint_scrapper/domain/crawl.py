"""What the crawl did, page by page and as a whole (SPEC 5.9, 5.10)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PageStatus(StrEnum):
    """Machine-stable per-page outcome codes, exported verbatim (SPEC 5.9)."""

    OK = "ok"
    NO_FINDINGS = "no_findings"
    SKIPPED_ROBOTS = "skipped_robots"
    SKIPPED_EXTENSION = "skipped_extension"
    SKIPPED_CONTENT_TYPE = "skipped_content_type"
    SKIPPED_OFF_SCOPE = "skipped_off_scope"
    SKIPPED_BUDGET = "skipped_budget"
    SKIPPED_DEPTH = "skipped_depth"
    URL_REJECTED_SHAPE = "url_rejected_shape"
    CREDENTIALS_IN_URL = "credentials_in_url"
    OFF_SCOPE_REDIRECT = "off_scope_redirect"
    TOO_MANY_REDIRECTS = "too_many_redirects"
    TOO_LARGE = "too_large"
    RATE_LIMITED = "rate_limited"
    HTTP_ERROR = "http_error"
    TRANSPORT_ERROR = "transport_error"
    PARSE_ERROR = "parse_error"


FETCHED_STATUSES = frozenset({PageStatus.OK, PageStatus.NO_FINDINGS})
"""Pages that were retrieved and parsed. ``no_findings`` is a success, not a failure."""

SKIPPED_STATUSES = frozenset(
    {
        PageStatus.SKIPPED_ROBOTS,
        PageStatus.SKIPPED_EXTENSION,
        PageStatus.SKIPPED_CONTENT_TYPE,
        PageStatus.SKIPPED_OFF_SCOPE,
        PageStatus.SKIPPED_BUDGET,
        PageStatus.SKIPPED_DEPTH,
        PageStatus.URL_REJECTED_SHAPE,
        PageStatus.CREDENTIALS_IN_URL,
        PageStatus.OFF_SCOPE_REDIRECT,
    }
)
"""URLs the product decided not to use. Most of them were never requested at all."""

FAILED_STATUSES = frozenset(
    {
        PageStatus.TOO_MANY_REDIRECTS,
        PageStatus.TOO_LARGE,
        PageStatus.RATE_LIMITED,
        PageStatus.HTTP_ERROR,
        PageStatus.TRANSPORT_ERROR,
        PageStatus.PARSE_ERROR,
    }
)
"""Pages that were attempted and did not yield usable content."""

UNHEALTHY_STATUSES = frozenset({PageStatus.HTTP_ERROR, PageStatus.TRANSPORT_ERROR})
"""Failures that count towards the host-unhealthy threshold of SPEC 5.10."""

ATTEMPTED_STATUSES = FETCHED_STATUSES | FAILED_STATUSES
"""The only statuses the abort thresholds of SPEC 5.10 may reason about.

A *skip* is a decision this product made, never evidence that the host is
unhealthy. Counting ``skipped_robots`` as a failed fetch would mean that the
better a site protects itself with robots.txt, the sooner we declare it broken
and abort — punishing exactly the behaviour we exist to honour.
"""


class CrawlOutcome(StrEnum):
    """How the run ended. Every value produces a complete, exportable report."""

    COMPLETED = "completed"
    BUDGET_EXHAUSTED = "budget_exhausted"
    DEPTH_EXHAUSTED = "depth_exhausted"
    STOPPED_BY_OPERATOR = "stopped_by_operator"
    ABORTED_RATE_LIMITED = "aborted_rate_limited"
    ABORTED_HOST_UNHEALTHY = "aborted_host_unhealthy"
    ABORTED_ERROR_RATE = "aborted_error_rate"
    FAILED = "failed"


ABORTED_OUTCOMES = frozenset(
    {
        CrawlOutcome.ABORTED_RATE_LIMITED,
        CrawlOutcome.ABORTED_HOST_UNHEALTHY,
        CrawlOutcome.ABORTED_ERROR_RATE,
        CrawlOutcome.FAILED,
    }
)

CONSECUTIVE_RATE_LIMITS_BEFORE_ABORT = 3
"""SPEC 5.10: repeated 429 is the host telling us to stop, and we never escalate."""

MAXIMUM_RETRY_AFTER_SECONDS = 120.0
"""A longer ``Retry-After`` aborts rather than holding a run open doing nothing."""

CONSECUTIVE_FAILURES_BEFORE_ABORT = 10
MINIMUM_FETCHES_BEFORE_ERROR_RATE = 20
MAXIMUM_ERROR_RATE = 0.5


@dataclass(frozen=True)
class PageOutcome:
    """What the crawl did with one URL, whether or not it was ever requested."""

    url: str
    depth: int
    status: PageStatus
    detail: str | None = None
    http_status: int | None = None
    content_type: str | None = None
    findings_count: int = 0

    def sort_key(self) -> tuple[int, str]:
        """Depth then URL, never fetch order (SPEC 9.1.1)."""
        return (self.depth, self.url)
