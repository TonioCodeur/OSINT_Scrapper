"""AC-NET-1: every row of the fail-closed decision table of SPEC 6.2.2."""

from __future__ import annotations

import pytest

from osint_scrapper.application.errors import TooManyRedirectsError, TransportError
from osint_scrapper.infrastructure.http.robots import (
    MAXIMUM_ROBOTS_BODY_BYTES,
    RobotsFile,
    RobotsReason,
    RobotsTxtPolicy,
    host_key,
    robots_url_for,
)
from tests.conftest import FakeRobotsTransport, FrozenClock, read_fixture

PRODUCT_TOKEN = "OSINT-Scrapper"
ROBOTS_URL = "https://example.com/robots.txt"
TARGET = "https://example.com/contact"


def policy(response: object) -> RobotsTxtPolicy:
    return RobotsTxtPolicy(FakeRobotsTransport({ROBOTS_URL: response}), FrozenClock())  # type: ignore[arg-type]


def ok(body: bytes) -> RobotsFile:
    return RobotsFile(status_code=200, body=body, final_url=ROBOTS_URL)


DECISION_TABLE = [
    (ok(b"User-agent: *\nAllow: /\n"), True, RobotsReason.ALLOW_RULE, "2xx, allowed"),
    (ok(b"User-agent: *\nDisallow: /contact\n"), False, RobotsReason.DISALLOW, "2xx, disallowed"),
    (RobotsFile(401, b"", ROBOTS_URL), False, RobotsReason.REFUSED_401, "401 refuses us"),
    (RobotsFile(403, b"", ROBOTS_URL), False, RobotsReason.REFUSED_403, "403 refuses us"),
    (RobotsFile(404, b"", ROBOTS_URL), True, RobotsReason.ABSENT_404, "404 is a definitive answer"),
    (RobotsFile(410, b"", ROBOTS_URL), True, RobotsReason.ABSENT_4XX, "other 4xx allow"),
    (RobotsFile(500, b"", ROBOTS_URL), False, RobotsReason.UNREACHABLE_5XX, "5xx must disallow"),
    (
        ok(b"x" * (MAXIMUM_ROBOTS_BODY_BYTES + 1)),
        False,
        RobotsReason.BODY_TOO_LARGE,
        "an oversized body is ambiguous",
    ),
    (ok(b"\xff\xfe\x00bad"), False, RobotsReason.UNDECODABLE, "an undecodable body is ambiguous"),
    (
        TransportError("timeout"),
        False,
        RobotsReason.UNREACHABLE_TRANSPORT,
        "no answer is not permission",
    ),
    (
        TooManyRedirectsError("loop"),
        False,
        RobotsReason.TOO_MANY_REDIRECTS,
        "a redirect loop is ambiguous",
    ),
]


def test_the_robots_body_cap_is_the_value_rfc_9309_requires() -> None:
    """RFC 9309 section 2.5: at least 500 KiB must be parsed, so the cap is 512 KiB.

    The oversized row of the decision table is built from this constant, so
    without this assertion lowering the cap to a byte would keep that row green.
    """
    assert MAXIMUM_ROBOTS_BODY_BYTES == 512 * 1024


@pytest.mark.parametrize(("response", "allowed", "reason", "why"), DECISION_TABLE)
def test_each_row_of_the_decision_table(response, allowed, reason, why) -> None:
    """AC-NET-1: the decision *and* the machine-stable reason code."""
    decision = policy(response).evaluate(TARGET, PRODUCT_TOKEN)
    assert decision.allowed is allowed, why
    assert decision.reason == reason
    assert decision.robots_url == ROBOTS_URL


def test_a_redirected_robots_file_is_followed_by_the_transport() -> None:
    """SPEC 6.2.2 row 2: up to five hops, then the final body decides."""
    transport = FakeRobotsTransport(
        {ROBOTS_URL: RobotsFile(200, b"User-agent: *\nDisallow: /contact\n", "https://x/robots.txt")}
    )
    decision = RobotsTxtPolicy(transport, FrozenClock()).evaluate(TARGET, PRODUCT_TOKEN)
    assert not decision.allowed


def test_the_body_is_fetched_once_per_host_key() -> None:
    """SPEC 6.2.1: path-level rules mean per-URL evaluation, not per-URL fetching."""
    body = read_fixture("robots", "allow_all.txt").encode()
    transport = FakeRobotsTransport({ROBOTS_URL: ok(body)})
    subject = RobotsTxtPolicy(transport, FrozenClock())
    subject.evaluate("https://example.com/a", PRODUCT_TOKEN)
    subject.evaluate("https://example.com/b", PRODUCT_TOKEN)
    assert transport.requested == [ROBOTS_URL]


def test_a_subdomain_is_a_different_host_key() -> None:
    """SPEC 6.2.1: a subdomain gets its own fetch and its own decision."""
    transport = FakeRobotsTransport(default=ok(b"User-agent: *\nAllow: /\n"))
    subject = RobotsTxtPolicy(transport, FrozenClock())
    subject.evaluate("https://example.com/a", PRODUCT_TOKEN)
    subject.evaluate("https://blog.example.com/a", PRODUCT_TOKEN)
    assert transport.requested == [ROBOTS_URL, "https://blog.example.com/robots.txt"]


def test_the_product_token_is_what_is_matched() -> None:
    """SPEC 6.2.1: the group is matched on the token, not the full User-Agent."""
    body = read_fixture("robots", "disallow_product_token.txt").encode()
    denied = "https://example.com/mentions-legales"
    assert not policy(ok(body)).evaluate(denied, PRODUCT_TOKEN).allowed
    assert policy(ok(body)).evaluate(denied, "SomeoneElse").allowed


def test_crawl_delay_and_request_rate_both_reach_the_limiter() -> None:
    """SPEC 6.3: whichever the host used, the limiter sees a number."""
    delay = policy(ok(read_fixture("robots", "crawl_delay.txt").encode()))
    assert delay.evaluate(TARGET, PRODUCT_TOKEN).crawl_delay == 5.0
    rate = policy(ok(read_fixture("robots", "request_rate.txt").encode()))
    assert rate.evaluate(TARGET, PRODUCT_TOKEN).crawl_delay == 10.0


def test_sitemap_directives_are_read_from_the_body_already_fetched() -> None:
    """SPEC 5.6: discovery costs no extra request."""
    transport = FakeRobotsTransport(
        {
            ROBOTS_URL: ok(
                b"Sitemap: https://example.com/a.xml\n"
                b"Sitemap: https://example.com/b.xml\n"
                b"User-agent: *\nAllow: /\n"
            )
        }
    )
    subject = RobotsTxtPolicy(transport, FrozenClock())
    subject.evaluate(TARGET, PRODUCT_TOKEN)
    assert subject.sitemaps(TARGET) == (
        "https://example.com/a.xml",
        "https://example.com/b.xml",
    )
    assert transport.requested == [ROBOTS_URL]


SITEMAP_BODY = b"Sitemap: https://example.com/a.xml\nUser-agent: *\nDisallow: /\n"
"""A body that really does declare a sitemap, so the status is the only variable."""


def test_a_denied_host_declares_no_sitemap() -> None:
    """A host we may not read is a host whose directives we do not act on.

    The same body served with a 200 does yield the directive, which is what
    makes this an assertion about the refusing status rather than about an
    empty response.
    """
    assert policy(RobotsFile(403, SITEMAP_BODY, ROBOTS_URL)).sitemaps(TARGET) == ()
    assert policy(ok(SITEMAP_BODY)).sitemaps(TARGET) == ("https://example.com/a.xml",)


def test_the_robots_url_and_host_key_are_derived_from_the_target() -> None:
    assert robots_url_for("https://example.com:8443/a?b=1") == "https://example.com:8443/robots.txt"
    assert host_key("https://EXAMPLE.com/a") == ("https", "example.com")
