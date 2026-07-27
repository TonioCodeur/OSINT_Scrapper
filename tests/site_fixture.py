"""The committed mini-site, wired as a route table (SPEC 10, AC-E2E-1).

Every branch the acceptance criteria name is present here: robots allow and
disallow, a redirect chain, an off-scope redirect, an off-scope link, a sitemap,
a ``security.txt``, a binary-extension link, a wrong-content-type response, a
spider trap, an obfuscated email, a URL carrying credentials, and a page that
makes the parser raise ``SelectorNotFoundError``.

No real person's data appears anywhere: every name is invented and every host is
``example.com`` or ``example.org``.
"""

from __future__ import annotations

from collections.abc import Mapping

from tests.conftest import Route, site_fixture

ORIGIN = "https://example.com"
OFF_SCOPE_HOST = "https://elsewhere.example/"

HTML = "text/html; charset=utf-8"
PLAIN = "text/plain; charset=utf-8"
XML = "application/xml"

REDIRECT_ENTRY = f"{ORIGIN}/go"
REDIRECT_HOP = f"{ORIGIN}/hop"
REDIRECT_TARGET = f"{ORIGIN}/nouvelle-adresse"
OFF_SCOPE_REDIRECT = f"{ORIGIN}/leaving"
ROBOTS_DENIED = f"{ORIGIN}/private/secret"
BINARY_LINK = f"{ORIGIN}/brochure.pdf"
SPIDER_TRAP = f"{ORIGIN}/trap/a/a/a/a/a/a/"
OFF_SCOPE_LINK = "https://example.org/partner"
CREDENTIALS_LINK = "https://user:pass@example.com/private-area"
WRONG_CONTENT_TYPE = f"{ORIGIN}/data.xml"
PARSE_ERROR_PAGE = f"{ORIGIN}/broken"
SITEMAP = f"{ORIGIN}/sitemap.xml"
SITEMAP_LISTED = f"{ORIGIN}/sitemap-listed"
SECURITY_TXT = f"{ORIGIN}/.well-known/security.txt"

_SERVER_HEADERS = {"Server": "nginx", "X-Powered-By": "PHP/8.3"}

_DEEP_PAGE = (
    b"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
    b"<title>1998</title></head><body><h1>1998</h1>"
    b"<p><a href='mailto:1998@example.com'>1998@example.com</a></p></body></html>"
)


def site_routes() -> dict[str, Route]:
    """Return the mini-site as a URL-to-response table."""
    return {
        f"{ORIGIN}/robots.txt": Route(site_fixture("robots.txt"), content_type=PLAIN),
        f"{ORIGIN}/": Route(
            site_fixture("index.html"), content_type=HTML, extra_headers=_SERVER_HEADERS
        ),
        f"{ORIGIN}/contact": Route(site_fixture("contact.html"), content_type=HTML),
        f"{ORIGIN}/mentions-legales": Route(
            site_fixture("legal_notice.html"), content_type=HTML
        ),
        f"{ORIGIN}/equipe/": Route(site_fixture("team.html"), content_type=HTML),
        f"{ORIGIN}/obfuscated": Route(site_fixture("obfuscated.html"), content_type=HTML),
        PARSE_ERROR_PAGE: Route(site_fixture("broken.html"), content_type=HTML),
        WRONG_CONTENT_TYPE: Route(site_fixture("open_data.xml"), content_type=XML),
        REDIRECT_ENTRY: Route(status=302, content_type="", location=REDIRECT_HOP),
        REDIRECT_HOP: Route(status=302, content_type="", location=REDIRECT_TARGET),
        REDIRECT_TARGET: Route(site_fixture("redirected.html"), content_type=HTML),
        OFF_SCOPE_REDIRECT: Route(status=302, content_type="", location=OFF_SCOPE_HOST),
        ROBOTS_DENIED: Route(b"<html><body>members</body></html>", content_type=HTML),
        SITEMAP: Route(site_fixture("sitemap.xml"), content_type=XML),
        SITEMAP_LISTED: Route(site_fixture("sitemap_listed.html"), content_type=HTML),
        SECURITY_TXT: Route(site_fixture("security.txt"), content_type=PLAIN),
        f"{ORIGIN}/deeper/archive": Route(site_fixture("archive.html"), content_type=HTML),
        f"{ORIGIN}/deeper/archive/1998": Route(_DEEP_PAGE, content_type=HTML),
    }


def routes_without(*urls: str) -> dict[str, Route]:
    """Return the mini-site with the named URLs removed, so they answer 404."""
    routes = site_routes()
    for url in urls:
        routes.pop(url, None)
    return routes


def never_requested_urls() -> Mapping[str, str]:
    """URLs the crawl must never issue a request for, with the reason it must not."""
    return {
        ROBOTS_DENIED: "skipped_robots",
        BINARY_LINK: "skipped_extension",
        SPIDER_TRAP: "url_rejected_shape",
        OFF_SCOPE_LINK: "skipped_off_scope",
        OFF_SCOPE_HOST: "off_scope_redirect",
        "https://example.com/private-area": "credentials_in_url",
    }
