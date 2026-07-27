"""Sitemap and sitemap-index reading (SPEC 5.6).

Verified 2026-07-27 against sitemaps.org: a sitemap file has root ``<urlset>``,
entries ``<url>`` and location ``<loc>``; an index has root ``<sitemapindex>``,
entries ``<sitemap>`` and location ``<loc>``. The published limits are 50 000
URLs and 50 MB per file; this product is deliberately stricter and does not
honour them.

``<loc>`` values are pulled with the BeautifulSoup + ``html.parser`` stack that
is already a dependency. No XML entity resolution happens at any point, which is
why no hardened XML library is needed: there is nothing for one to harden.
"""

from __future__ import annotations

import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from osint_scrapper.application.errors import ResponseTooLargeError, SelectorNotFoundError
from osint_scrapper.application.ports import FetchedPage
from osint_scrapper.infrastructure.extraction.text import collapse, parse_html

MAXIMUM_DOCUMENT_BYTES = 10 * 1024 * 1024
MAXIMUM_LOCATIONS = 500
"""At most this many ``<loc>`` values are taken from any one document."""

URLSET_ROOT = "urlset"
SITEMAP_INDEX_ROOT = "sitemapindex"
LOCATION_SELECTOR = "loc"


class BeautifulSoupSitemapReader:
    """Reads ``<loc>`` values out of a sitemap or a sitemap index."""

    def __init__(
        self,
        maximum_document_bytes: int = MAXIMUM_DOCUMENT_BYTES,
        maximum_locations: int = MAXIMUM_LOCATIONS,
    ) -> None:
        self._maximum_document_bytes = maximum_document_bytes
        self._maximum_locations = maximum_locations

    def is_index(self, document: FetchedPage) -> bool:
        """Whether the document is an index, whose locations are further sitemaps."""
        self._assert_size(document)
        return _parse(document.text).find(SITEMAP_INDEX_ROOT) is not None

    def locations(self, document: FetchedPage) -> tuple[str, ...]:
        """Return the ``<loc>`` values, capped at the documented maximum.

        Raises:
            ResponseTooLargeError: the document exceeds the size cap.
            SelectorNotFoundError: the document is neither a urlset nor an index.
        """
        self._assert_size(document)
        soup = _parse(document.text)
        if soup.find(URLSET_ROOT) is None and soup.find(SITEMAP_INDEX_ROOT) is None:
            raise SelectorNotFoundError(
                f"<{URLSET_ROOT}> or <{SITEMAP_INDEX_ROOT}>", document.url
            )
        found = [collapse(element.get_text()) for element in soup.find_all(LOCATION_SELECTOR)]
        return tuple(value for value in found if value)[: self._maximum_locations]

    def _assert_size(self, document: FetchedPage) -> None:
        if len(document.text.encode("utf-8")) > self._maximum_document_bytes:
            raise ResponseTooLargeError(document.url, self._maximum_document_bytes)


def _parse(markup: str) -> BeautifulSoup:
    """Parse a sitemap with the HTML backend, which is the whole point here.

    BeautifulSoup warns that an XML document is being read by an HTML parser.
    That is deliberate and documented in this module's own docstring: pulling
    ``<loc>`` text needs no XML engine, and using one would mean a second parser
    and an entity-resolution surface this product has no use for.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        return parse_html(markup)
