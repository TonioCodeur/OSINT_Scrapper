"""The fetcher: per-hop gating, scope-aware redirects, body caps and 429 handling."""

from __future__ import annotations

import pytest

from osint_scrapper import PRODUCT_TOKEN
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
from osint_scrapper.application.ports import HTML_MEDIA_TYPES, SITEMAP_MEDIA_TYPES
from osint_scrapper.domain.url import CrawlScope
from osint_scrapper.infrastructure.http.rate_limit import HARD_FLOOR_SECONDS
from osint_scrapper.infrastructure.http.requests_fetcher import (
    MAXIMUM_BODY_BYTES,
    FetchPolicy,
    RequestsPageFetcher,
    build_retry,
)
from tests.conftest import (
    AllowAllRobotsPolicy,
    DenyAllRobotsPolicy,
    FakeHttpSession,
    FrozenClock,
    NoOpRateLimiter,
    RaisingHttpSession,
    Route,
)

ORIGIN = "https://example.com"
SCOPE = CrawlScope(scope_host="example.com", port=None, include_subdomains=True)


def build(
    session: FakeHttpSession,
    robots: object | None = None,
    limiter: NoOpRateLimiter | None = None,
    max_pages: int = 200,
    interval: float = 1.0,
    scope: CrawlScope | None = SCOPE,
) -> RequestsPageFetcher:
    return RequestsPageFetcher(
        session=session,  # type: ignore[arg-type]
        robots_policy=robots or AllowAllRobotsPolicy(),  # type: ignore[arg-type]
        rate_limiter=limiter or NoOpRateLimiter(),
        clock=FrozenClock(),
        policy=FetchPolicy(
            product_token=PRODUCT_TOKEN,
            configured_interval_seconds=interval,
            max_pages=max_pages,
            scope=scope,
        ),
    )


def test_a_page_is_returned_with_its_headers_lower_cased() -> None:
    """SPEC 8.7: ``headers`` is what the technology extractor reads."""
    route = Route(b"<html><body>ok</body></html>", extra_headers={"X-Powered-By": "PHP"})
    session = FakeHttpSession({f"{ORIGIN}/": route})
    page = build(session).fetch(f"{ORIGIN}/")
    assert page.headers["x-powered-by"] == "PHP"
    assert page.url == f"{ORIGIN}/"
    assert page.media_type == "text/html"


def test_robots_is_evaluated_before_every_request() -> None:
    """SPEC FR-10: per URL, in code, with no way to turn it off."""
    session = FakeHttpSession({f"{ORIGIN}/a": Route(b"<html></html>")})
    with pytest.raises(RobotsDeniedError):
        build(session, robots=DenyAllRobotsPolicy()).fetch(f"{ORIGIN}/a")
    assert session.requested == []


def test_robots_is_evaluated_again_on_every_redirect_hop() -> None:
    """AC-NET-3: an allowed URL that redirects into a disallowed path is not fetched."""

    class DenySecond:
        def __init__(self) -> None:
            self.seen: list[str] = []

        def evaluate(self, url: str, product_token: str):
            from osint_scrapper.application.ports import RobotsDecision

            del product_token
            self.seen.append(url)
            allowed = "/private/" not in url
            return RobotsDecision(
                allowed=allowed,
                reason="robots_allow_rule" if allowed else "robots_disallow",
                robots_url=f"{ORIGIN}/robots.txt",
            )

        def sitemaps(self, url: str) -> tuple[str, ...]:
            del url
            return ()

    robots = DenySecond()
    session = FakeHttpSession(
        {
            f"{ORIGIN}/go": Route(status=302, content_type="", location=f"{ORIGIN}/private/x"),
            f"{ORIGIN}/private/x": Route(b"<html>secret</html>"),
        }
    )
    with pytest.raises(RobotsDeniedError):
        build(session, robots=robots).fetch(f"{ORIGIN}/go")
    assert robots.seen == [f"{ORIGIN}/go", f"{ORIGIN}/private/x"]
    assert session.requested == [f"{ORIGIN}/go"]


def test_a_redirect_leaving_the_scope_is_refused_before_robots_is_even_asked() -> None:
    """SPEC 5.3: not followed even if robots would allow it.

    The recording policy proves the ordering: only the in-scope URL is ever
    submitted to robots. Asking about the off-scope target would mean fetching
    a third party's robots.txt to decide something scope has already decided.
    """
    robots = AllowAllRobotsPolicy()
    session = FakeHttpSession(
        {f"{ORIGIN}/leaving": Route(status=302, content_type="", location="https://other.example/")}
    )
    with pytest.raises(OffScopeRedirectError) as refusal:
        build(session, robots=robots).fetch(f"{ORIGIN}/leaving")
    assert refusal.value.location == "https://other.example/"
    assert session.requested == [f"{ORIGIN}/leaving"]
    assert robots.evaluated == [f"{ORIGIN}/leaving"]


def test_more_hops_than_the_limit_raise() -> None:
    routes = {
        f"{ORIGIN}/hop-{index}": Route(
            status=302, content_type="", location=f"{ORIGIN}/hop-{index + 1}"
        )
        for index in range(10)
    }
    with pytest.raises(TooManyRedirectsError):
        build(FakeHttpSession(routes)).fetch(f"{ORIGIN}/hop-0")


def test_a_redirect_without_a_location_is_a_transport_failure() -> None:
    session = FakeHttpSession({f"{ORIGIN}/a": Route(status=302, content_type="")})
    with pytest.raises(TransportError):
        build(session).fetch(f"{ORIGIN}/a")


def test_an_unparseable_media_type_is_refused_without_reading_the_body() -> None:
    """SPEC 5.7: the body is not read past the header and the connection is released."""
    session = FakeHttpSession(
        {f"{ORIGIN}/data.xml": Route(b"<dataset/>", content_type="application/xml")}
    )
    with pytest.raises(UnsupportedContentTypeError) as refusal:
        build(session).fetch(f"{ORIGIN}/data.xml", HTML_MEDIA_TYPES)
    assert refusal.value.media_type == "application/xml"


def test_the_accepted_media_types_are_per_request() -> None:
    """A sitemap is XML on purpose; a page is not."""
    session = FakeHttpSession(
        {f"{ORIGIN}/s.xml": Route(b"<urlset></urlset>", content_type="application/xml")}
    )
    assert build(session).fetch(f"{ORIGIN}/s.xml", SITEMAP_MEDIA_TYPES).status_code == 200


def test_a_response_without_a_media_type_is_tolerated() -> None:
    """Some hosts omit Content-Type, and guessing wrong would break real pages."""
    session = FakeHttpSession({f"{ORIGIN}/a": Route(b"<html></html>", content_type="")})
    assert build(session).fetch(f"{ORIGIN}/a").text == "<html></html>"


def test_a_body_above_the_cap_is_abandoned_and_nothing_partial_is_parsed() -> None:
    """AC-CRAWL-8: a 6 MiB body produces ``too_large``.

    The oversized body is built from the constant, so the cap's value is pinned
    here too: otherwise lowering it to a byte would keep this test green.
    """
    assert MAXIMUM_BODY_BYTES == 5 * 1024 * 1024
    oversized = b"x" * (MAXIMUM_BODY_BYTES + 1024)
    session = FakeHttpSession({f"{ORIGIN}/big": Route(oversized)})
    with pytest.raises(ResponseTooLargeError):
        build(session).fetch(f"{ORIGIN}/big")


def test_a_429_carries_its_retry_after_to_the_caller() -> None:
    """SPEC 5.10: the crawl decides between backing off and aborting, not the transport."""
    session = FakeHttpSession(
        {f"{ORIGIN}/a": Route(status=429, body=b"slow", extra_headers={"Retry-After": "30"})}
    )
    with pytest.raises(RateLimitedError) as limited:
        build(session).fetch(f"{ORIGIN}/a")
    assert limited.value.retry_after == 30.0


def test_a_retry_after_http_date_is_converted_to_seconds() -> None:
    """RFC 9110 allows both spellings and the fetcher must read both."""
    session = FakeHttpSession(
        {
            f"{ORIGIN}/a": Route(
                status=429,
                body=b"slow",
                extra_headers={"Retry-After": "Mon, 27 Jul 2026 14:04:11 GMT"},
            )
        }
    )
    with pytest.raises(RateLimitedError) as limited:
        build(session).fetch(f"{ORIGIN}/a")
    assert limited.value.retry_after == pytest.approx(120.0)


def test_another_bad_status_raises_with_its_code() -> None:
    session = FakeHttpSession({f"{ORIGIN}/a": Route(status=404, body=b"gone")})
    with pytest.raises(HttpStatusError) as failure:
        build(session).fetch(f"{ORIGIN}/a")
    assert failure.value.status_code == 404


def test_a_transport_failure_is_typed() -> None:
    session = RaisingHttpSession({}, failing=frozenset({f"{ORIGIN}/a"}))
    with pytest.raises(TransportError):
        build(session).fetch(f"{ORIGIN}/a")


def test_the_run_ceiling_stops_the_fetcher() -> None:
    """SPEC NFR-12: a run issues at most ``max_pages`` content requests."""
    session = FakeHttpSession({f"{ORIGIN}/a": Route(b"<html></html>")})
    fetcher = build(session, max_pages=1)
    fetcher.fetch(f"{ORIGIN}/a")
    with pytest.raises(PageBudgetExhaustedError):
        fetcher.fetch(f"{ORIGIN}/a")


def test_the_limiter_receives_the_floored_interval() -> None:
    """SPEC 6.3: the fetcher is where the floor is applied, once."""
    limiter = NoOpRateLimiter()
    session = FakeHttpSession({f"{ORIGIN}/a": Route(b"<html></html>")})
    build(
        session, robots=AllowAllRobotsPolicy(crawl_delay=7.0), limiter=limiter, interval=0.1
    ).fetch(f"{ORIGIN}/a")
    assert limiter.acquired == [("example.com", 7.0)]

    floor_limiter = NoOpRateLimiter()
    build(session, limiter=floor_limiter, interval=0.1).fetch(f"{ORIGIN}/a")
    assert floor_limiter.acquired == [("example.com", HARD_FLOOR_SECONDS)]


def test_429_is_not_in_the_transport_retry_list() -> None:
    """SPEC 5.10: repeated 429 must abort the crawl, not be retried quietly."""
    assert 429 not in build_retry(3).status_forcelist  # type: ignore[operator]
    assert set(build_retry(3).status_forcelist or ()) == {500, 502, 503, 504}


def test_a_redirect_hop_is_canonicalized_before_it_is_requested() -> None:
    """SPEC 5.2: the URL requested, judged and exported is one canonical string.

    The hop is canonicalized rather than followed verbatim, so the tracking
    parameter and the fragment are gone from the wire, not merely from the
    reported ``source_url``. That is what keeps the robots evaluation, the
    visited-set key and the exported provenance talking about the same URL.
    """
    session = FakeHttpSession(
        {
            f"{ORIGIN}/go": Route(
                status=302, content_type="", location=f"{ORIGIN}/arrived?utm_source=x#f"
            ),
            f"{ORIGIN}/arrived": Route(b"<html></html>"),
        }
    )

    assert build(session).fetch(f"{ORIGIN}/go").url == f"{ORIGIN}/arrived"
    assert session.requested == [f"{ORIGIN}/go", f"{ORIGIN}/arrived"]


def test_sitemaps_are_read_through_the_fetcher_not_a_separate_policy() -> None:
    """SPEC 6.1: the crawl receives a fetcher and nothing else."""
    robots = AllowAllRobotsPolicy(sitemaps=("https://example.com/s.xml",))
    fetcher = build(FakeHttpSession({}), robots=robots)
    assert fetcher.sitemaps(f"{ORIGIN}/") == ("https://example.com/s.xml",)
