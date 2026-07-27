"""Links, sitemaps and ``security.txt`` (SPEC 5.6)."""

from __future__ import annotations

import pytest

from osint_scrapper.application.errors import ResponseTooLargeError, SelectorNotFoundError
from osint_scrapper.domain.attributes import ExtractionLayer, FieldName
from osint_scrapper.infrastructure.discovery.links import HtmlLinkExtractor
from osint_scrapper.infrastructure.discovery.security_txt import (
    MAXIMUM_DOCUMENT_BYTES,
    MAXIMUM_FIELD_LENGTH,
    MAXIMUM_LINES,
    RfcSecurityTxtReader,
)
from osint_scrapper.infrastructure.discovery.sitemap import (
    MAXIMUM_LOCATIONS,
    BeautifulSoupSitemapReader,
)
from tests.conftest import make_page, read_fixture

SITEMAP_URL = "https://example.com/sitemap.xml"


def sitemap(body: str):
    return make_page(body, url=SITEMAP_URL, content_type="application/xml")


def test_links_are_reported_unresolved_and_in_document_order() -> None:
    """Resolution and the scope decision belong to the domain, not to this adapter."""
    page = make_page(read_fixture("site", "index.html"), url="https://example.com/")
    links = HtmlLinkExtractor().links(page)
    assert links[0] == "/contact"
    assert "https://example.org/partner" in links
    assert "mailto:contact@example.com" in links, "the crawl decides what is not a URL"


def test_a_urlset_yields_its_locations() -> None:
    locations = BeautifulSoupSitemapReader().locations(sitemap(read_fixture("site", "sitemap.xml")))
    assert locations == ("https://example.com/sitemap-listed", "https://example.org/not-ours")


def test_an_index_is_recognised_as_one() -> None:
    """SPEC 5.6: an index's locations are sitemaps, a urlset's are pages."""
    document = sitemap(
        "<sitemapindex><sitemap><loc>https://example.com/a.xml</loc></sitemap></sitemapindex>"
    )
    reader = BeautifulSoupSitemapReader()
    assert reader.is_index(document)
    assert reader.locations(document) == ("https://example.com/a.xml",)
    assert not reader.is_index(sitemap("<urlset></urlset>"))


def test_a_document_contributes_at_most_five_hundred_locations() -> None:
    """AC-CRAWL-6: 900 entries contribute exactly 500."""
    entries = "".join(f"<url><loc>https://example.com/{index}</loc></url>" for index in range(900))
    locations = BeautifulSoupSitemapReader().locations(sitemap(f"<urlset>{entries}</urlset>"))
    assert len(locations) == MAXIMUM_LOCATIONS


def test_an_oversized_document_is_abandoned() -> None:
    """AC-CRAWL-6: recorded ``too_large`` and contributing nothing."""
    reader = BeautifulSoupSitemapReader(maximum_document_bytes=64)
    with pytest.raises(ResponseTooLargeError):
        reader.locations(sitemap("<urlset>" + "<url><loc>x</loc></url>" * 40 + "</urlset>"))


def test_a_document_that_is_not_a_sitemap_raises() -> None:
    """SPEC NFR-8: loud and specific, never a silent empty list."""
    with pytest.raises(SelectorNotFoundError) as failure:
        BeautifulSoupSitemapReader().locations(sitemap("<html><body>nope</body></html>"))
    assert "urlset" in str(failure.value)


def security_txt(body: str):
    return make_page(
        body, url="https://example.com/.well-known/security.txt", content_type="text/plain"
    )


def test_security_txt_maps_its_fields_onto_the_documented_findings() -> None:
    """AC-CRAWL-7, all at layer ``well_known``."""
    found = RfcSecurityTxtReader().findings(security_txt(read_fixture("site", "security.txt")))
    by_field = {item.field: item.raw_value for item in found}
    assert by_field[FieldName.EMAIL] == "security@example.com"
    assert by_field[FieldName.PHONE] == "+33123456789"
    assert by_field[FieldName.PGP_KEY_URL] == "https://example.com/pgp-key.asc"
    assert by_field[FieldName.SOCIAL_PROFILE] == "https://github.com/example-association"
    assert {item.extraction_layer for item in found} == {ExtractionLayer.WELL_KNOWN}


def test_an_https_contact_that_is_not_a_platform_is_ignored() -> None:
    """A contact form on the site's own domain is a page, not a finding."""
    found = RfcSecurityTxtReader().findings(
        security_txt("Contact: https://example.com/report\nExpires: 2027-01-01T00:00:00Z\n")
    )
    assert found == ()


def test_a_file_with_no_contact_field_raises() -> None:
    """RFC 9116 requires ``Contact``; without it this is not the document we parsed for."""
    with pytest.raises(SelectorNotFoundError):
        RfcSecurityTxtReader().findings(security_txt("Expires: 2027-01-01T00:00:00Z\n"))


_PADDING_LINE = "# " + "p" * (MAXIMUM_FIELD_LENGTH // 8) + "\n"
_OVERSIZED_DOCUMENT = "Contact: mailto:a@example.com\n" + _PADDING_LINE * (
    MAXIMUM_DOCUMENT_BYTES // len(_PADDING_LINE) + 1
)
"""Over the byte cap in a shape that trips neither the line nor the field limit."""


@pytest.mark.parametrize(
    "body",
    [
        "Contact: mailto:a@example.com\n" + "# padding\n" * (MAXIMUM_LINES + 200),
        "Contact: mailto:" + "a" * (MAXIMUM_FIELD_LENGTH + 100) + "@example.com\n",
        _OVERSIZED_DOCUMENT,
    ],
    ids=["too many lines", "field too long", "document too large"],
)
def test_the_rfc_9116_limits_a_parser_may_decline_are_declined(body: str) -> None:
    """SPEC 5.6: exactly the three limits RFC 9116 names, all three exercised."""
    with pytest.raises(ResponseTooLargeError):
        RfcSecurityTxtReader().findings(security_txt(body))


def test_the_rfc_9116_limits_have_the_values_the_specification_names() -> None:
    """The bodies above are built from these constants, so the values are pinned here."""
    assert MAXIMUM_DOCUMENT_BYTES == 32 * 1024
    assert MAXIMUM_LINES == 1000
    assert MAXIMUM_FIELD_LENGTH == 2048
    assert len(_OVERSIZED_DOCUMENT.encode("utf-8")) > MAXIMUM_DOCUMENT_BYTES
    assert len(_OVERSIZED_DOCUMENT.splitlines()) <= MAXIMUM_LINES
    assert max(len(line) for line in _OVERSIZED_DOCUMENT.splitlines()) <= MAXIMUM_FIELD_LENGTH
