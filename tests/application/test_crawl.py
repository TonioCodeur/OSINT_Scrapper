"""The crawl use case, driven with no Qt anywhere (AC-ARCH-7).

The transport is faked; the frontier, the canonicalization, the robots policy,
the rate limiter, the extraction pipeline and the aggregator are all real, which
is what makes these assertions worth anything.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

import pytest

from osint_scrapper.domain.crawl import (
    CONSECUTIVE_FAILURES_BEFORE_ABORT,
    CONSECUTIVE_RATE_LIMITS_BEFORE_ABORT,
    MAXIMUM_ERROR_RATE,
    MAXIMUM_RETRY_AFTER_SECONDS,
    MINIMUM_FETCHES_BEFORE_ERROR_RATE,
    CrawlOutcome,
    PageStatus,
)
from osint_scrapper.domain.errors import SeedRefusedError
from osint_scrapper.domain.report import SiteReport
from osint_scrapper.domain.target import CrawlSettings, Purpose, PurposeCategory, resolve_target
from tests.conftest import (
    FakeHttpSession,
    FakeSleeper,
    FrozenClock,
    ManualCancellation,
    RaisingHttpSession,
    RecordingObserver,
    Route,
)
from tests.site_fixture import (
    CREDENTIALS_LINK,
    OFF_SCOPE_HOST,
    OFF_SCOPE_REDIRECT,
    ORIGIN,
    PARSE_ERROR_PAGE,
    REDIRECT_ENTRY,
    SECURITY_TXT,
    SITEMAP,
    SITEMAP_LISTED,
    SPIDER_TRAP,
    WRONG_CONTENT_TYPE,
    never_requested_urls,
    routes_without,
    site_routes,
)
from tests.wiring import build_crawl, build_fetcher

PURPOSE = Purpose(category=PurposeCategory.DUE_DILIGENCE)


def run_crawl(
    session: FakeHttpSession,
    settings: CrawlSettings | None = None,
    cancellation: ManualCancellation | None = None,
    entered: str = "example.com",
) -> tuple[SiteReport, RecordingObserver, FakeSleeper]:
    """Run the real chain over ``session`` and return everything a test asserts on."""
    used = settings or CrawlSettings()
    target = resolve_target(entered, include_subdomains=used.include_subdomains)
    clock = FrozenClock()
    sleeper = FakeSleeper()
    observer = RecordingObserver()
    fetcher = build_fetcher(session, target, clock, sleeper, max_pages=used.max_pages)
    use_case = build_crawl(fetcher, observer, clock, sleeper, cancellation)
    return use_case.execute(target, used, PURPOSE), observer, sleeper


def statuses(report: SiteReport) -> Mapping[str, str]:
    return {page.url: str(page.status) for page in report.pages}


def test_the_whole_mini_site_crawls_without_a_qapplication() -> None:
    """AC-ARCH-7: the seam works, and no Qt object is constructed anywhere."""
    report, observer, _ = run_crawl(FakeHttpSession(site_routes()))
    assert report.outcome is CrawlOutcome.COMPLETED
    assert report.findings
    assert observer.started and observer.finished
    assert observer.frontier, "the interface cannot render 'queued' without this call"


def test_every_url_the_product_must_not_request_is_never_requested() -> None:
    """AC-CRAWL-8, AC-NET-2, AC-NET-3 and AC-EXTRACT-8, on one counting session.

    The table of forbidden URLs is the one declared beside the mini-site that
    produces them, so a link added to a fixture cannot quietly lose the
    expectation that exists to police it.
    """
    session = FakeHttpSession(site_routes())
    report, _, _ = run_crawl(session)
    seen = statuses(report)
    forbidden = never_requested_urls()
    assert forbidden, "an empty table would make this test prove nothing"

    for url, reason in forbidden.items():
        assert url not in session.requested, f"{url} must never be requested"
        assert reason in seen.values(), f"no page was reported as {reason}"
        if url in seen:
            assert seen[url] == reason, url
    assert seen[OFF_SCOPE_REDIRECT] == "off_scope_redirect"
    assert CREDENTIALS_LINK not in session.requested
    assert "https://github.com/example-association" not in session.requested


def test_the_spider_trap_and_the_credentials_url_are_reported_with_their_codes() -> None:
    """SPEC 5.9: an operator must be able to see why a URL was dropped."""
    report, _, _ = run_crawl(FakeHttpSession(site_routes()))
    seen = statuses(report)
    assert seen[SPIDER_TRAP] == "url_rejected_shape"
    assert seen["https://example.com/private-area"] == "credentials_in_url"


def test_a_wrong_content_type_is_skipped_with_the_media_type_recorded() -> None:
    """AC-CRAWL-8: requested, header read, body never parsed."""
    report, _, _ = run_crawl(FakeHttpSession(site_routes()))
    page = next(item for item in report.pages if item.url == WRONG_CONTENT_TYPE)
    assert page.status is PageStatus.SKIPPED_CONTENT_TYPE
    assert page.content_type == "application/xml"
    assert page.findings_count == 0


def test_a_page_that_is_not_a_document_raises_and_costs_only_itself() -> None:
    """AC-EXTRACT-10: loud, specific, and the crawl continues."""
    report, _, _ = run_crawl(FakeHttpSession(site_routes()))
    page = next(item for item in report.pages if item.url == PARSE_ERROR_PAGE)
    assert page.status is PageStatus.PARSE_ERROR
    assert "any HTML element" in (page.detail or "")
    assert page.findings_count == 0
    assert report.outcome is CrawlOutcome.COMPLETED


def test_a_redirect_chain_collapses_to_one_page_at_its_final_url() -> None:
    """AC-CRAWL-5, and the per-hop gating of AC-NET-3 on the way."""
    session = FakeHttpSession(site_routes())
    report, _, _ = run_crawl(session)
    urls = [page.url for page in report.pages]
    assert f"{ORIGIN}/nouvelle-adresse" in urls
    assert REDIRECT_ENTRY not in urls
    assert urls.count(f"{ORIGIN}/nouvelle-adresse") == 1


def test_a_redirect_leaving_the_scope_is_recorded_and_not_followed() -> None:
    """SPEC 5.3: this is the rule that stops a site crawl becoming an internet crawl."""
    session = FakeHttpSession(site_routes())
    report, _, _ = run_crawl(session)
    page = next(item for item in report.pages if item.url == OFF_SCOPE_REDIRECT)
    assert page.status is PageStatus.OFF_SCOPE_REDIRECT
    assert OFF_SCOPE_HOST not in session.requested


def test_a_redirect_loop_stops_at_the_hop_limit() -> None:
    """AC-NET-3: six hops record ``too_many_redirects``."""
    routes = site_routes()
    for index in range(8):
        routes[f"{ORIGIN}/loop-{index}"] = Route(
            status=302, content_type="", location=f"{ORIGIN}/loop-{index + 1}"
        )
    routes[f"{ORIGIN}/"] = Route(
        b"<html><body><a href='/loop-0'>go</a></body></html>", content_type="text/html"
    )
    report, _, _ = run_crawl(FakeHttpSession(routes))
    page = next(item for item in report.pages if item.url == f"{ORIGIN}/loop-0")
    assert page.status is PageStatus.TOO_MANY_REDIRECTS


def test_the_sitemap_is_read_from_the_robots_body_and_its_urls_are_gated() -> None:
    """AC-CRAWL-6 and SPEC 5.6: one robots fetch, and off-site locations dropped."""
    session = FakeHttpSession(site_routes())
    report, _, _ = run_crawl(session)
    assert session.requested.count(f"{ORIGIN}/robots.txt") == 1
    assert SITEMAP in session.requested
    assert SITEMAP_LISTED in session.requested
    assert "https://example.org/not-ours" not in session.requested
    assert statuses(report)["https://example.org/not-ours"] == "skipped_off_scope"


def test_security_txt_yields_findings_and_never_a_frontier_entry() -> None:
    """AC-CRAWL-7: contacts are contacts, not crawl targets."""
    session = FakeHttpSession(site_routes())
    report, _, _ = run_crawl(session)
    assert SECURITY_TXT in session.requested
    values = {(str(item.field), item.value) for item in report.findings}
    assert ("email", "security@example.com") in values
    assert ("phone", "+33123456789") in values
    assert ("pgp_key_url", "https://example.com/pgp-key.asc") in values
    assert "https://example.com/report-a-problem" not in session.requested
    well_known = [
        entry
        for finding in report.findings
        for entry in finding.provenance
        if str(entry.extraction_layer) == "well_known"
    ]
    assert well_known, "security.txt findings must carry the well_known layer"


def test_the_page_budget_stops_the_crawl_and_names_what_was_left() -> None:
    """AC-CRAWL-3: exactly ``max_pages`` requests, the rest marked ``skipped_budget``."""
    session = FakeHttpSession(site_routes())
    report, _, _ = run_crawl(session, CrawlSettings(max_pages=5))
    content_requests = [url for url in session.requested if not url.endswith("/robots.txt")]
    assert len(content_requests) == 5
    assert report.outcome is CrawlOutcome.BUDGET_EXHAUSTED
    assert any(page.status is PageStatus.SKIPPED_BUDGET for page in report.pages)


def test_the_depth_limit_keeps_deeper_urls_out_of_the_frontier() -> None:
    """AC-CRAWL-3: no depth-2 URL is fetched, and each is reported."""
    session = FakeHttpSession(site_routes())
    report, _, _ = run_crawl(session, CrawlSettings(max_depth=1))
    deep = [page for page in report.pages if page.status is PageStatus.SKIPPED_DEPTH]
    assert deep, "a depth-limited crawl must say which URLs it refused"
    assert all(page.depth > 1 for page in deep)
    assert f"{ORIGIN}/deeper/archive" not in session.requested


def test_a_high_value_path_is_fetched_before_the_ordinary_ones() -> None:
    """AC-CRAWL-4: the priority boost, proved on request order."""
    posts = "".join(f"<a href='/blog/post-{index}'>p</a>" for index in range(40))
    routes = {
        f"{ORIGIN}/robots.txt": Route(b"User-agent: *\nAllow: /\n", content_type="text/plain"),
        f"{ORIGIN}/": Route(
            f"<html><body>{posts}<a href='/contact'>c</a></body></html>".encode(),
            content_type="text/html",
        ),
    }
    for index in range(40):
        routes[f"{ORIGIN}/blog/post-{index}"] = Route(b"<html><body>post</body></html>")
    routes[f"{ORIGIN}/contact"] = Route(b"<html><body>contact</body></html>")
    session = FakeHttpSession(routes)
    run_crawl(session, CrawlSettings(max_pages=6))
    content = [url for url in session.requested if "/blog/" in url or url.endswith("/contact")]
    assert content[0] == f"{ORIGIN}/contact"


def test_a_concurrent_crawl_produces_the_same_report_as_a_serial_one() -> None:
    """AC-CRAWL-9: the proof that NFR-9 survives SPEC 6.4."""
    serial, _, _ = run_crawl(FakeHttpSession(site_routes()), CrawlSettings(concurrent_requests=1))
    parallel, _, _ = run_crawl(FakeHttpSession(site_routes()), CrawlSettings(concurrent_requests=2))
    assert [(page.url, str(page.status), page.depth) for page in serial.pages] == [
        (page.url, str(page.status), page.depth) for page in parallel.pages
    ]
    assert [
        (str(item.field), item.value, item.page_support, item.occurrence_count)
        for item in serial.findings
    ] == [
        (str(item.field), item.value, item.page_support, item.occurrence_count)
        for item in parallel.findings
    ]


def test_stopping_returns_a_report_rather_than_raising() -> None:
    """AC-UI-3: stop always yields a consistent, exportable partial report."""
    cancellation = ManualCancellation(after_checks=1)
    report, _, _ = run_crawl(FakeHttpSession(site_routes()), cancellation=cancellation)
    assert report.outcome is CrawlOutcome.STOPPED_BY_OPERATOR
    assert report.pages


def test_robots_denying_the_target_refuses_the_run_before_anything_exists() -> None:
    """AC-NET-7: no run directory, no ledger entry, zero content requests."""
    routes = site_routes()
    routes[f"{ORIGIN}/robots.txt"] = Route(
        b"User-agent: *\nDisallow: /\n", content_type="text/plain"
    )
    session = FakeHttpSession(routes)
    with pytest.raises(SeedRefusedError) as refusal:
        run_crawl(session)
    assert refusal.value.robots_url == f"{ORIGIN}/robots.txt"
    assert refusal.value.reason == "skipped_robots"
    assert [url for url in session.requested if not url.endswith("/robots.txt")] == []


def test_an_unreachable_target_refuses_the_run() -> None:
    """SPEC 5.10: seed refusal covers unreachable as well as disallowed."""
    session = RaisingHttpSession(site_routes(), failing=frozenset({f"{ORIGIN}/"}))
    with pytest.raises(SeedRefusedError):
        run_crawl(session)


def test_three_consecutive_rate_limits_abort_the_crawl() -> None:
    """AC-NET-6: repeated 429 is the host telling us to stop, and we never escalate.

    The number is part of the promise, not an implementation detail: the
    outcome enum alone would stay green if the threshold drifted to thirty.
    """
    assert CONSECUTIVE_RATE_LIMITS_BEFORE_ABORT == 3
    report = _run_with_failing_pages(
        Route(status=429, content_type="text/html", body=b"slow down"), count=6
    )
    assert report.outcome is CrawlOutcome.ABORTED_RATE_LIMITED
    detail = report.outcome_detail or ""
    assert "consecutive 429" in detail
    assert detail.startswith(f"{CONSECUTIVE_RATE_LIMITS_BEFORE_ABORT} "), detail


def test_a_retry_after_above_the_ceiling_aborts_immediately() -> None:
    """AC-NET-6: better to stop than to hold a run open doing nothing."""
    assert MAXIMUM_RETRY_AFTER_SECONDS == 120.0
    report = _run_with_failing_pages(
        Route(
            status=429,
            content_type="text/html",
            body=b"slow down",
            extra_headers={"Retry-After": "600"},
        ),
        count=2,
    )
    assert report.outcome is CrawlOutcome.ABORTED_RATE_LIMITED
    detail = report.outcome_detail or ""
    assert "600" in detail
    assert f"{MAXIMUM_RETRY_AFTER_SECONDS:.0f}s ceiling" in detail, detail


def test_ten_consecutive_failures_abort_as_an_unhealthy_host() -> None:
    """AC-NET-6, with the documented threshold pinned to its SPEC value."""
    assert CONSECUTIVE_FAILURES_BEFORE_ABORT == 10
    report = _run_with_failing_pages(
        Route(status=503, content_type="text/html", body=b"down"), count=14
    )
    assert report.outcome is CrawlOutcome.ABORTED_HOST_UNHEALTHY
    detail = report.outcome_detail or ""
    assert "consecutive fetch failures" in detail
    assert detail.startswith(f"{CONSECUTIVE_FAILURES_BEFORE_ABORT} "), detail


def test_an_aborted_run_still_exports_what_it_collected() -> None:
    """AC-NET-6: an abort produces a complete report of everything before it."""
    report = _run_with_failing_pages(
        Route(status=503, content_type="text/html", body=b"down"), count=14
    )
    assert report.findings, "the seed's findings must survive the abort"
    assert report.pages_fetched >= 1


def _run_with_failing_pages(failure: Route, count: int) -> SiteReport:
    """Build a site whose seed is fine and whose every child fails the same way."""
    links = "".join(f"<a href='/page-{index}'>p</a>" for index in range(count))
    routes = {
        f"{ORIGIN}/robots.txt": Route(b"User-agent: *\nAllow: /\n", content_type="text/plain"),
        f"{ORIGIN}/": Route(
            (
                "<html><body><a href='mailto:contact@example.com'>c</a>"
                f"{links}</body></html>"
            ).encode(),
            content_type="text/html",
        ),
    }
    for index in range(count):
        routes[f"{ORIGIN}/page-{index}"] = failure
    report, _, _ = run_crawl(FakeHttpSession(routes), CrawlSettings(concurrent_requests=1))
    return report


def test_a_missing_sitemap_and_missing_security_txt_cost_one_request_each() -> None:
    """SPEC NFR-12: the politeness ceiling holds even when discovery finds nothing."""
    session = FakeHttpSession(routes_without(SITEMAP, SECURITY_TXT))
    run_crawl(session, CrawlSettings(max_pages=50))
    assert session.requested.count(SITEMAP) == 1
    assert session.requested.count(SECURITY_TXT) == 1


def test_a_high_failure_rate_aborts_once_enough_fetches_have_been_attempted() -> None:
    """AC-NET-6: after at least 20 attempts, above 50 % failure ends the run.

    Both halves of the rule are pinned: the sample size below which no error
    rate is trusted, and the rate above which the run ends. The detail line is
    then read back to prove the abort really honoured both.
    """
    assert MINIMUM_FETCHES_BEFORE_ERROR_RATE == 20
    assert MAXIMUM_ERROR_RATE == 0.5
    links = "".join(f"<a href='/page-{index}'>p</a>" for index in range(30))
    routes = {
        f"{ORIGIN}/robots.txt": Route(b"User-agent: *\nAllow: /\n", content_type="text/plain"),
        f"{ORIGIN}/": Route(
            f"<html><body><a href='mailto:a@example.com'>c</a>{links}</body></html>".encode(),
            content_type="text/html",
        ),
    }
    for index in range(30):
        # Alternating 404 and a page with nothing on it keeps the consecutive-failure
        # and consecutive-429 thresholds from firing first, so the error rate is
        # unambiguously what ends this run.
        routes[f"{ORIGIN}/page-{index}"] = (
            Route(status=404, content_type="text/html", body=b"gone")
            if index % 3
            else Route(b"<html><body>nothing here</body></html>")
        )
    report, _, _ = run_crawl(FakeHttpSession(routes), CrawlSettings(concurrent_requests=1))
    assert report.outcome is CrawlOutcome.ABORTED_ERROR_RATE
    detail = report.outcome_detail or ""
    counted = re.search(r"(\d+) of (\d+) attempted fetches failed", detail)
    assert counted is not None, detail
    failed, attempted = int(counted.group(1)), int(counted.group(2))
    assert attempted >= MINIMUM_FETCHES_BEFORE_ERROR_RATE, detail
    assert failed / attempted > MAXIMUM_ERROR_RATE, detail


def test_a_sitemap_index_is_followed_exactly_one_level() -> None:
    """AC-CRAWL-6: one level only, whatever the index points at."""
    routes = site_routes()
    routes[f"{ORIGIN}/robots.txt"] = Route(
        b"Sitemap: https://example.com/index.xml\nUser-agent: *\nAllow: /\n",
        content_type="text/plain",
    )
    routes[f"{ORIGIN}/index.xml"] = Route(
        b"<sitemapindex><sitemap><loc>https://example.com/level-1.xml</loc></sitemap>"
        b"</sitemapindex>",
        content_type="application/xml",
    )
    routes[f"{ORIGIN}/level-1.xml"] = Route(
        b"<sitemapindex><sitemap><loc>https://example.com/level-2.xml</loc></sitemap>"
        b"</sitemapindex>",
        content_type="application/xml",
    )
    routes[f"{ORIGIN}/level-2.xml"] = Route(
        b"<urlset><url><loc>https://example.com/too-deep</loc></url></urlset>",
        content_type="application/xml",
    )
    session = FakeHttpSession(routes)
    run_crawl(session, CrawlSettings(max_pages=40))
    assert f"{ORIGIN}/index.xml" in session.requested
    assert f"{ORIGIN}/level-1.xml" in session.requested
    assert f"{ORIGIN}/level-2.xml" not in session.requested
    assert f"{ORIGIN}/too-deep" not in session.requested


def test_an_oversized_body_is_recorded_and_never_parsed() -> None:
    """AC-CRAWL-8: nothing partial is parsed, and one page pays for it alone."""
    from osint_scrapper.infrastructure.http.requests_fetcher import MAXIMUM_BODY_BYTES

    routes = {
        f"{ORIGIN}/robots.txt": Route(b"User-agent: *\nAllow: /\n", content_type="text/plain"),
        f"{ORIGIN}/": Route(
            b"<html><body><a href='/huge'>huge</a>"
            b"<a href='mailto:contact@example.com'>c</a></body></html>",
            content_type="text/html",
        ),
        f"{ORIGIN}/huge": Route(b"x" * (MAXIMUM_BODY_BYTES + 1024), content_type="text/html"),
    }
    report, _, _ = run_crawl(FakeHttpSession(routes))
    page = next(item for item in report.pages if item.url == f"{ORIGIN}/huge")
    assert page.status is PageStatus.TOO_LARGE
    assert report.outcome is CrawlOutcome.COMPLETED
    assert report.findings


def test_a_rate_limited_page_backs_off_before_the_next_one() -> None:
    """SPEC 5.10: the documented curve, with the injected sleeper proving it."""
    links = "".join(f"<a href='/page-{index}'>p</a>" for index in range(2))
    routes = {
        f"{ORIGIN}/robots.txt": Route(b"User-agent: *\nAllow: /\n", content_type="text/plain"),
        f"{ORIGIN}/": Route(
            f"<html><body>{links}</body></html>".encode(), content_type="text/html"
        ),
        f"{ORIGIN}/page-0": Route(status=429, content_type="text/html", body=b"slow"),
        f"{ORIGIN}/page-1": Route(status=429, content_type="text/html", body=b"slow"),
    }
    _, _, sleeper = run_crawl(FakeHttpSession(routes), CrawlSettings(concurrent_requests=1))
    assert sleeper.slept[-2:] == [2.0, 4.0]


def test_two_urls_that_resolve_to_one_page_are_counted_once_at_any_concurrency() -> None:
    """SPEC 5.8, and the concurrency-hardened half of AC-CRAWL-9.

    A serial run never fetches the second URL, because the first result adds the
    final URL to the visited set before the next claim. A concurrent run claims
    both before either answers, so the duplicate is collapsed when the second
    result comes back instead. The page log and the findings are identical
    either way; only ``requests_made`` differs, by exactly the extra request the
    second worker had already issued.
    """
    routes = {
        f"{ORIGIN}/robots.txt": Route(b"User-agent: *\nAllow: /\n", content_type="text/plain"),
        f"{ORIGIN}/": Route(
            b"<html><body><a href='/a'>x</a><a href='/a/'>y</a>"
            b"<a href='/a?utm_source=news'>z</a></body></html>",
            content_type="text/html",
        ),
        f"{ORIGIN}/a": Route(status=302, content_type="", location=f"{ORIGIN}/a/"),
        f"{ORIGIN}/a/": Route(
            b"<html><body><a href='mailto:one@example.com'>c</a></body></html>",
            content_type="text/html",
        ),
    }
    serial, _, _ = run_crawl(FakeHttpSession(routes), CrawlSettings(concurrent_requests=1))
    parallel, _, _ = run_crawl(FakeHttpSession(routes), CrawlSettings(concurrent_requests=2))

    for report in (serial, parallel):
        rows = [page for page in report.pages if page.url == f"{ORIGIN}/a/"]
        assert len(rows) == 1
        assert f"{ORIGIN}/a" not in {page.url for page in report.pages}
    assert [(page.url, str(page.status)) for page in serial.pages] == [
        (page.url, str(page.status)) for page in parallel.pages
    ]
    assert [(item.value, item.occurrence_count) for item in serial.findings] == [
        (item.value, item.occurrence_count) for item in parallel.findings
    ]
