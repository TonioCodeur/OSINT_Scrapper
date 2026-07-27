"""Reading the outbound links of one page.

Resolution, canonicalization and the scope decision belong to the domain and the
crawl; this adapter only reports what the markup says, in document order.
"""

from __future__ import annotations

from osint_scrapper.application.ports import FetchedPage
from osint_scrapper.infrastructure.extraction.text import attribute_value, parse_html


class HtmlLinkExtractor:
    """Returns every ``href`` an anchor carries, unresolved."""

    def links(self, page: FetchedPage) -> tuple[str, ...]:
        """Return the document's anchor targets, duplicates included."""
        soup = parse_html(page.text)
        found = [
            (attribute_value(anchor, "href") or "").strip()
            for anchor in soup.find_all("a", href=True)
        ]
        return tuple(href for href in found if href)
