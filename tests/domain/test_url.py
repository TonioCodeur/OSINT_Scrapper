"""AC-CRAWL-1 and AC-CRAWL-2: canonicalization and scope, rule by rule (SPEC 5.2, 5.3)."""

from __future__ import annotations

import pytest

from osint_scrapper.domain.errors import InvalidTargetError, UrlRejectedError
from osint_scrapper.domain.url import (
    MAXIMUM_URL_LENGTH,
    CrawlScope,
    UrlRejection,
    canonicalize,
    has_skipped_extension,
    is_high_value_path,
    normalize_target,
    scope_for,
    scope_host_of,
)

CANONICAL_CASES = [
    ("https://example.com", "https://example.com/", "an empty path becomes /"),
    ("https://EXAMPLE.com/A", "https://example.com/A", "host folds, path case is preserved"),
    ("https://example.com/a#section", "https://example.com/a", "the fragment is dropped"),
    ("https://example.com:443/a", "https://example.com/a", "the default https port is dropped"),
    ("http://example.com:80/a", "http://example.com/a", "the default http port is dropped"),
    ("https://example.com:8443/a", "https://example.com:8443/a", "another port is kept"),
    ("https://example.com/a/./b/../c", "https://example.com/a/c", "dot segments resolve"),
    ("https://example.com//a///b", "https://example.com/a/b", "slash runs collapse"),
    ("https://example.com/a/", "https://example.com/a/", "a trailing slash is significant"),
    ("https://example.com/a", "https://example.com/a", "and its absence is too"),
    (
        "https://example.com/a?utm_source=x&b=2",
        "https://example.com/a?b=2",
        "tracking parameters are removed",
    ),
    (
        "https://example.com/a?PHPSESSID=x",
        "https://example.com/a",
        "session parameters are removed, and an empty query drops the ?",
    ),
    (
        "https://example.com/a?b=2&a=1",
        "https://example.com/a?a=1&b=2",
        "remaining parameters are sorted",
    ),
    ("https://exämple.com/", "https://xn--exmple-cua.com/", "the host is IDNA-encoded"),
    ("https://example.com/%7Euser", "https://example.com/~user", "unreserved bytes are decoded"),
    ("https://example.com/a b", "https://example.com/a%20b", "reserved bytes are re-encoded"),
]


@pytest.mark.parametrize(("raw", "expected", "why"), CANONICAL_CASES, ids=lambda item: str(item))
def test_canonicalization_applies_every_documented_rule(raw, expected, why) -> None:
    """AC-CRAWL-1: each row of SPEC 5.2, asserted separately."""
    assert canonicalize(raw) == expected, why


def test_a_relative_link_resolves_against_its_page() -> None:
    """Links are resolved before anything else happens to them."""
    assert canonicalize("../c", base="https://example.com/a/b") == "https://example.com/c"


@pytest.mark.parametrize(
    "scheme", ["mailto:someone@example.com", "tel:+33123456789", "javascript:void(0)", "data:,x"]
)
def test_a_non_http_scheme_is_never_a_crawl_target(scheme: str) -> None:
    """SPEC 5.2 rule 1: these are extraction inputs or noise, not URLs to fetch."""
    with pytest.raises(UrlRejectedError) as rejection:
        canonicalize(scheme)
    assert rejection.value.reason == UrlRejection.UNSUPPORTED_SCHEME


def test_a_url_carrying_credentials_is_refused() -> None:
    """SPEC 5.2 rule 9: a URL needing credentials is not public data."""
    with pytest.raises(UrlRejectedError) as rejection:
        canonicalize("https://user:pass@example.com/a")
    assert rejection.value.reason == UrlRejection.CREDENTIALS_IN_URL


SPIDER_TRAPS = [
    ("https://example.com/" + "/".join(f"s{index}" for index in range(21)), "too many segments"),
    ("https://example.com/a/a/a/a/a/a", "a segment repeats too often"),
    (
        "https://example.com/a?" + "&".join(f"p{index}={index}" for index in range(11)),
        "too many query parameters",
    ),
    ("https://example.com/" + "x" * (MAXIMUM_URL_LENGTH + 1), "the URL is too long"),
]


@pytest.mark.parametrize(("raw", "why"), SPIDER_TRAPS, ids=lambda item: str(item))
def test_the_spider_trap_guard_rejects_each_documented_shape(raw: str, why: str) -> None:
    """AC-CRAWL-1: all four rejections of the spider-trap guard."""
    with pytest.raises(UrlRejectedError) as rejection:
        canonicalize(raw)
    assert rejection.value.reason == UrlRejection.REJECTED_SHAPE, why


def test_a_bare_domain_becomes_https_and_never_falls_back() -> None:
    """SPEC FR-1: an operator who needs plain HTTP types the full URL."""
    assert normalize_target("example.com") == "https://example.com/"
    assert normalize_target(" http://example.com/about ") == "http://example.com/about"


def test_an_unusable_target_says_why() -> None:
    """The interface renders this message in its live hint line."""
    with pytest.raises(InvalidTargetError):
        normalize_target("ftp://example.com/")
    with pytest.raises(InvalidTargetError):
        normalize_target("   ")


def test_the_scope_host_drops_one_leading_www() -> None:
    """SPEC 5.3: the scope host is what the operator named, minus ``www.``."""
    assert scope_host_of("https://www.example.com/") == "example.com"
    assert scope_host_of("https://docs.example.com/") == "docs.example.com"


SCOPE_CASES = [
    ("https://www.example.com/", True, "https://blog.example.com/a", True),
    ("https://www.example.com/", False, "https://blog.example.com/a", False),
    ("https://www.example.com/", False, "https://www.example.com/a", True),
    ("https://www.example.com/", True, "https://example.org/a", False),
    ("https://www.example.com/", True, "https://notexample.com/a", False),
    ("https://docs.example.com/", True, "https://example.com/a", False),
    ("https://example.com/", True, "https://example.com:8443/a", False),
]


@pytest.mark.parametrize(("seed", "subdomains", "candidate", "expected"), SCOPE_CASES)
def test_scope_confinement_goes_down_and_never_up(
    seed: str, subdomains: bool, candidate: str, expected: bool
) -> None:
    """AC-CRAWL-2, including the suffix test that a label-boundary test must fail."""
    assert scope_for(seed, subdomains).contains(candidate) is expected


def test_a_suffix_match_is_not_a_label_match() -> None:
    """``notexample.com`` ends with ``example.com`` and is emphatically not in scope."""
    scope = CrawlScope(scope_host="example.com", port=None, include_subdomains=True)
    assert not scope.contains("https://notexample.com/")
    assert scope.contains("https://a.example.com/")


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com/rapport.pdf", True),
        ("https://example.com/style.css", True),
        ("https://example.com/data.xml", False),
        ("https://example.com/contact", False),
    ],
)
def test_binary_extensions_are_recognised_on_the_url(url: str, expected: bool) -> None:
    """SPEC 5.7: rejected on the URL, before any HTTP call is considered."""
    assert has_skipped_extension(url) is expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com/mentions-legales", True),
        ("https://example.com/MENTIONS-LEGALES", True),
        ("https://example.com/qui-sommes-nous", True),
        ("https://example.com/a-propos", True),
        ("https://example.com/blog/post-12", False),
    ],
)
def test_the_priority_list_is_accent_and_case_insensitive(url: str, expected: bool) -> None:
    """SPEC 5.4: it reorders a queue, so a near miss costs nothing but ordering."""
    assert is_high_value_path(url) is expected
