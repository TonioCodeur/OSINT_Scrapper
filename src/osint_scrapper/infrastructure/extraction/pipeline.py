"""Runs the extraction layers over one page and returns raw candidates.

The pipeline knows nothing about which layers exist: they are injected. Adding a
layer means writing an extractor and wiring it in the composition root.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from bs4 import BeautifulSoup

from osint_scrapper.application.errors import SelectorNotFoundError
from osint_scrapper.application.ports import HTML_MEDIA_TYPES, FetchedPage
from osint_scrapper.domain.attributes import ExtractionLayer, FieldName, RawField
from osint_scrapper.infrastructure.extraction.text import parse_html, visible_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PageContent:
    """One page, parsed once and shared by every layer."""

    url: str
    soup: BeautifulSoup
    text: str
    fetched_at: datetime
    headers: Mapping[str, str]
    region: str
    """The region libphonenumber parses against, from the crawl settings."""

    def raw_field(
        self,
        field: FieldName,
        raw_value: str,
        layer: ExtractionLayer,
        metadata: Mapping[str, str] | None = None,
    ) -> RawField:
        """Build a candidate already stamped with this page's URL and timestamp."""
        return RawField(
            field=field,
            raw_value=raw_value,
            source_url=self.url,
            collected_at=self.fetched_at,
            extraction_layer=layer,
            metadata=dict(metadata or {}),
        )


class PageExtractor(Protocol):
    """One extraction layer applied to one page."""

    @property
    def layer(self) -> ExtractionLayer:
        """The layer this extractor tags its candidates with."""
        ...

    def extract(self, content: PageContent) -> tuple[RawField, ...]:
        """Return every candidate this layer can read from ``content``."""
        ...


def page_content(page: FetchedPage, region: str) -> PageContent:
    """Parse a fetched page once, for every layer to share."""
    soup = parse_html(page.text)
    return PageContent(
        url=page.url,
        soup=soup,
        text=visible_text(soup),
        fetched_at=page.fetched_at,
        headers=page.headers,
        region=region,
    )


def assert_html(page: FetchedPage) -> None:
    """Refuse a response that is not an HTML document, loudly (SPEC NFR-8).

    A JSON error envelope or a binary blob served with HTTP 200 and a
    ``text/html`` header parses into an empty soup and yields no candidates,
    which would be reported as "this page publishes nothing" — a silent
    degradation dressed up as an answer. A missing Content-Type is tolerated:
    some hosts omit it, and guessing wrong there would break real pages.

    Raises:
        SelectorNotFoundError: the response is not an HTML document.
    """
    if page.media_type and page.media_type not in HTML_MEDIA_TYPES:
        raise SelectorNotFoundError(
            f"an HTML document (Content-Type was {page.media_type!r})", page.url
        )
    if parse_html(page.text).find(True) is None:
        raise SelectorNotFoundError("any HTML element", page.url)


class ExtractionPipeline:
    """Applies every configured layer to a page and concatenates the candidates."""

    def __init__(self, extractors: Sequence[PageExtractor]) -> None:
        self._extractors = tuple(extractors)

    def extract(self, page: FetchedPage, region: str) -> tuple[RawField, ...]:
        """Run every layer over ``page``.

        A layer that finds nothing is normal and silent; a response that is not
        a page at all raises, and the crawl records ``parse_error`` for that URL
        alone rather than an empty success.
        """
        assert_html(page)
        content = page_content(page, region)
        candidates: list[RawField] = []
        for extractor in self._extractors:
            found = extractor.extract(content)
            logger.debug("%s produced %d candidate(s) on %s", extractor.layer, len(found), page.url)
            candidates.extend(found)
        return tuple(candidates)
