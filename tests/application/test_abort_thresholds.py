"""What the abort thresholds of SPEC 5.10 are allowed to count.

The thresholds exist to detect a host that is unwell and to stop bothering it.
They must therefore be driven only by fetches the host actually answered. A
*skip* is this product declining to use a URL — nobody was bothered and nothing
failed — and the difference is not cosmetic: counting skips made a site with a
restrictive ``robots.txt`` abort its own crawl and be reported as broken, which
is the exact inversion of what a politeness mechanism should produce.
"""

from __future__ import annotations

import pytest

from osint_scrapper.application.crawl import _Health
from osint_scrapper.domain.crawl import (
    ATTEMPTED_STATUSES,
    CONSECUTIVE_FAILURES_BEFORE_ABORT,
    FAILED_STATUSES,
    FETCHED_STATUSES,
    MAXIMUM_ERROR_RATE,
    MINIMUM_FETCHES_BEFORE_ERROR_RATE,
    CrawlOutcome,
    PageStatus,
)

SKIPS_THAT_ARE_NOT_FAILURES = [
    PageStatus.SKIPPED_ROBOTS,
    PageStatus.SKIPPED_BUDGET,
    PageStatus.SKIPPED_CONTENT_TYPE,
    PageStatus.OFF_SCOPE_REDIRECT,
    PageStatus.SKIPPED_EXTENSION,
    PageStatus.SKIPPED_OFF_SCOPE,
    PageStatus.SKIPPED_DEPTH,
]


def test_the_attempted_set_is_exactly_fetched_plus_failed() -> None:
    """An attempt is a request that went out and whose outcome the host decided."""
    assert ATTEMPTED_STATUSES == FETCHED_STATUSES | FAILED_STATUSES


@pytest.mark.parametrize("status", SKIPS_THAT_ARE_NOT_FAILURES)
def test_a_skip_moves_no_threshold_counter(status: PageStatus) -> None:
    """A URL we declined to use is neither an attempt nor a failure."""
    health = _Health()

    for _ in range(50):
        health.record(status, None)

    assert health.attempted == 0
    assert health.failed == 0
    assert health.outcome is None


def test_a_site_that_disallows_most_of_itself_is_not_declared_broken() -> None:
    """The regression this module exists for.

    Twenty-five URLs, twenty of them refused by ``robots.txt`` and five fetched
    cleanly. Every request the host answered succeeded, so nothing here is
    evidence of an unhealthy host and the crawl must run to its natural end.
    Counting the robots skips as failed fetches produced ``aborted_error_rate``
    at a 0.8 "failure rate" against a site that never failed once.
    """
    health = _Health()

    for index in range(25):
        health.record(
            PageStatus.OK if index % 5 == 0 else PageStatus.SKIPPED_ROBOTS, None
        )

    assert health.attempted == 5
    assert health.failed == 0
    assert health.outcome is None


def test_a_skip_does_not_break_a_run_of_real_failures() -> None:
    """A skipped URL between two transport errors must not reset the streak.

    The host is failing consecutively whether or not we declined a URL in the
    middle; resetting on a skip would let an unhealthy host escape the
    ten-failure threshold indefinitely.
    """
    health = _Health()

    for index in range(CONSECUTIVE_FAILURES_BEFORE_ABORT):
        health.record(PageStatus.TRANSPORT_ERROR, None)
        health.record(PageStatus.SKIPPED_ROBOTS, None)
        if index < CONSECUTIVE_FAILURES_BEFORE_ABORT - 1:
            assert health.outcome is None

    assert health.outcome is CrawlOutcome.ABORTED_HOST_UNHEALTHY
    assert health.detail is not None
    assert health.detail.startswith(f"{CONSECUTIVE_FAILURES_BEFORE_ABORT} ")


def test_real_failures_still_abort_on_the_documented_rate() -> None:
    """The fix must not have disarmed the threshold it corrected."""
    health = _Health()

    for index in range(MINIMUM_FETCHES_BEFORE_ERROR_RATE):
        health.record(
            PageStatus.HTTP_ERROR if index % 3 else PageStatus.OK, None
        )

    assert health.attempted == MINIMUM_FETCHES_BEFORE_ERROR_RATE
    assert health.failed / health.attempted > MAXIMUM_ERROR_RATE
    assert health.outcome is CrawlOutcome.ABORTED_ERROR_RATE
