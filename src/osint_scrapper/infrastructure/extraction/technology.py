"""The one non-personal field: what software serves this site (SPEC 8.1).

Exactly three sources: ``<meta name="generator">``, the ``X-Powered-By``
response header and the ``Server`` response header. No signature database, no
JavaScript analysis, no version probing — that is a different product, and this
extractor must be kept small on purpose.
"""

from __future__ import annotations

from osint_scrapper.domain.attributes import ExtractionLayer, FieldName, RawField
from osint_scrapper.infrastructure.extraction.pipeline import PageContent
from osint_scrapper.infrastructure.extraction.text import attribute_value, collapse

GENERATOR_META = "generator"
TECHNOLOGY_HEADERS = ("x-powered-by", "server")


class TechnologyExtractor:
    """Reads the generator meta tag and two response headers, and nothing else."""

    @property
    def layer(self) -> ExtractionLayer:
        """Semantics the site declared about itself."""
        return ExtractionLayer.SEMANTIC_HTML

    def extract(self, content: PageContent) -> tuple[RawField, ...]:
        """Return the technologies this page announces."""
        found: list[RawField] = []
        for meta in content.soup.find_all("meta", attrs={"name": True}):
            if (attribute_value(meta, "name") or "").strip().lower() != GENERATOR_META:
                continue
            value = collapse(attribute_value(meta, "content") or "")
            if value:
                found.append(
                    content.raw_field(
                        FieldName.TECHNOLOGY, value, self.layer, {"source": GENERATOR_META}
                    )
                )
        for header in TECHNOLOGY_HEADERS:
            value = collapse(content.headers.get(header, ""))
            if value:
                found.append(
                    content.raw_field(
                        FieldName.TECHNOLOGY, value, self.layer, {"source": header}
                    )
                )
        return tuple(found)
