"""Two ways a disallowed URL could still be fetched, and the gates that stop them.

Both of these were live defects. They share a shape worth naming, because it is
the shape that survives a green suite: the rule was implemented and unit-tested,
but the *seam* between the component that produced the input and the component
that judged it quietly guaranteed the rule could never fire. A test that builds
the judged object by hand cannot see that. Every test in this module therefore
drives the real transport, the real policy and the real fetcher together, and
fakes nothing above the HTTP session.
"""

from __future__ import annotations

import pytest

from osint_scrapper import PRODUCT_TOKEN
from osint_scrapper.application.errors import RobotsDeniedError
from osint_scrapper.application.ports import HTML_MEDIA_TYPES
from osint_scrapper.domain.url import CrawlScope
from osint_scrapper.infrastructure.http.rate_limit import PerHostRateLimiter
from osint_scrapper.infrastructure.http.requests_fetcher import (
    FetchPolicy,
    RequestsPageFetcher,
    RequestsRobotsTransport,
)
from osint_scrapper.infrastructure.http.robots import (
    MAXIMUM_ROBOTS_BODY_BYTES,
    RobotsReason,
    RobotsTxtPolicy,
)
from tests.conftest import (
    FakeHttpSession,
    FakeMonotonicClock,
    FakeSleeper,
    FrozenClock,
    Route,
)

ORIGIN = "https://example.com"
ROBOTS_URL = f"{ORIGIN}/robots.txt"
DISALLOWED = f"{ORIGIN}/private/secret"
SCOPE = CrawlScope(scope_host="example.com", port=None, include_subdomains=True)


def build_fetcher(session: FakeHttpSession) -> RequestsPageFetcher:
    """The real fetcher over the real robots policy and the real transport."""
    clock = FrozenClock()
    monotonic = FakeMonotonicClock()
    return RequestsPageFetcher(
        session=session,  # type: ignore[arg-type]
        robots_policy=RobotsTxtPolicy(
            RequestsRobotsTransport(session),  # type: ignore[arg-type]
            clock,
        ),
        rate_limiter=PerHostRateLimiter(monotonic, FakeSleeper(monotonic)),
        clock=clock,
        policy=FetchPolicy(
            product_token=PRODUCT_TOKEN,
            configured_interval_seconds=1.0,
            scope=SCOPE,
        ),
    )


# -- an oversized robots.txt must deny, not be truncated and obeyed in part ------


def oversized_robots_body() -> bytes:
    """A robots.txt above the cap whose rules live *past* the cap.

    The padding is a multiple of the 8 KiB streaming chunk size on purpose: that
    is the case where a reader that stops at ``>= limit`` returns a body of
    exactly ``limit`` bytes, which is never ``> limit``.
    """
    padding = b"# padding\n" * ((MAXIMUM_ROBOTS_BODY_BYTES // 10) + 2000)
    return b"User-agent: *\n" + padding + b"Disallow: /private/\n"


def test_the_documented_robots_size_cap_is_the_value_the_spec_names() -> None:
    """SPEC 6.2.2 fixes the parse limit at 512 KiB. Pin it, do not derive it."""
    assert MAXIMUM_ROBOTS_BODY_BYTES == 512 * 1024


def test_an_oversized_robots_file_denies_rather_than_being_silently_truncated() -> None:
    """SPEC 6.2.2: a body above the cap is ambiguous, and ambiguous denies.

    The bug this pins: the transport read exactly ``MAXIMUM_ROBOTS_BODY_BYTES``
    bytes, so the policy's ``len(body) > maximum`` test could never be true. The
    oversized file was cut short and parsed as if complete, every rule past the
    cut was dropped, and the crawler fetched what the host had disallowed.
    """
    session = FakeHttpSession({ROBOTS_URL: Route(body=oversized_robots_body())})
    policy = RobotsTxtPolicy(
        RequestsRobotsTransport(session),  # type: ignore[arg-type]
        FrozenClock(),
    )

    decision = policy.evaluate(DISALLOWED, PRODUCT_TOKEN)

    assert not decision.allowed
    assert decision.reason == RobotsReason.BODY_TOO_LARGE


def test_the_transport_hands_the_policy_a_body_it_can_recognize_as_oversized() -> None:
    """The seam itself: the read must overshoot the cap, not stop level with it."""
    session = FakeHttpSession({ROBOTS_URL: Route(body=oversized_robots_body())})

    robots_file = RequestsRobotsTransport(session).get(ROBOTS_URL)  # type: ignore[arg-type]

    assert len(robots_file.body) > MAXIMUM_ROBOTS_BODY_BYTES


def test_an_oversized_robots_file_stops_the_fetch_of_a_disallowed_page() -> None:
    """The consequence that matters: no request goes out for the denied URL."""
    session = FakeHttpSession(
        {
            ROBOTS_URL: Route(body=oversized_robots_body()),
            DISALLOWED: Route(body=b"<html><body>secret</body></html>"),
        }
    )
    fetcher = build_fetcher(session)

    with pytest.raises(RobotsDeniedError):
        fetcher.fetch(DISALLOWED, HTML_MEDIA_TYPES)

    assert DISALLOWED not in session.requested


# -- a redirect must be judged on the URL that will actually be requested --------


NORMALIZING_LOCATIONS = [
    pytest.param(f"{ORIGIN}//private/secret", id="doubled slash"),
    pytest.param(f"{ORIGIN}/./private/secret", id="dot segment"),
    pytest.param(f"{ORIGIN}/public/../private/secret", id="parent segment"),
]


@pytest.mark.parametrize("location", NORMALIZING_LOCATIONS)
def test_a_redirect_cannot_dodge_robots_with_an_unnormalized_path(location: str) -> None:
    """SPEC 6.2.1: robots is re-evaluated for the target of every redirect hop.

    ``urljoin`` normalizes only relative references, so an absolute ``Location``
    header arrives verbatim, and ``RobotFileParser`` resolves neither ``..`` nor
    a doubled ``//``. Following the raw location would ask robots about a path
    the server never serves, get an allow, and then request the disallowed
    resource. The hop is canonicalized first so all three are the same string.
    """
    session = FakeHttpSession(
        {
            ROBOTS_URL: Route(body=b"User-agent: *\nDisallow: /private/\n"),
            f"{ORIGIN}/go": Route(status=302, location=location),
            DISALLOWED: Route(body=b"<html><body>secret</body></html>"),
        }
    )
    fetcher = build_fetcher(session)

    with pytest.raises(RobotsDeniedError):
        fetcher.fetch(f"{ORIGIN}/go", HTML_MEDIA_TYPES)

    assert session.requested == [ROBOTS_URL, f"{ORIGIN}/go"]


def test_a_redirect_to_an_allowed_path_is_still_followed() -> None:
    """Canonicalizing the hop must not turn a legitimate redirect into a refusal."""
    session = FakeHttpSession(
        {
            ROBOTS_URL: Route(body=b"User-agent: *\nDisallow: /private/\n"),
            f"{ORIGIN}/go": Route(status=302, location=f"{ORIGIN}/public/./page"),
            f"{ORIGIN}/public/page": Route(body=b"<html><body>ok</body></html>"),
        }
    )

    page = build_fetcher(session).fetch(f"{ORIGIN}/go", HTML_MEDIA_TYPES)

    assert page.url == f"{ORIGIN}/public/page"
    assert page.status_code == 200
