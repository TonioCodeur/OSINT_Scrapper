"""Layer 3: semantics the HTML itself carries — links, ``<address>``, h-card, meta."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from types import MappingProxyType

from bs4 import Tag

from osint_scrapper.domain.attributes import ExtractionLayer, FieldName, RawField
from osint_scrapper.infrastructure.extraction.pipeline import PageContent
from osint_scrapper.infrastructure.extraction.social import platform_of
from osint_scrapper.infrastructure.extraction.text import attribute_value, collapse, css_classes

logger = logging.getLogger(__name__)

MAILTO_PREFIX = "mailto:"
TEL_PREFIX = "tel:"

PGP_KEY_SUFFIXES = (".asc", ".gpg", ".pgp")
"""Where a site publishes a public key. The key is never fetched and never parsed."""

HCARD_CLASS_FIELDS: Mapping[str, FieldName] = MappingProxyType(
    {
        # microformats2
        "p-name": FieldName.PERSON_NAME,
        "u-email": FieldName.EMAIL,
        "p-tel": FieldName.PHONE,
        "p-adr": FieldName.POSTAL_ADDRESS,
        "p-org": FieldName.ORGANIZATION_NAME,
        # legacy hCard / vCard
        "fn": FieldName.PERSON_NAME,
        "email": FieldName.EMAIL,
        "tel": FieldName.PHONE,
        "adr": FieldName.POSTAL_ADDRESS,
        "org": FieldName.ORGANIZATION_NAME,
    }
)
"""Class names that name their content, in both microformats generations."""

LEGACY_HCARD_ROOT_CLASSES = frozenset({"vcard", "h-card"})
"""Legacy class names are only trusted inside an h-card root, where they mean something."""


class SemanticHtmlExtractor:
    """Reads values the markup labels explicitly, without guessing at prose."""

    @property
    def layer(self) -> ExtractionLayer:
        """Semantics the author encoded, one step below structured data."""
        return ExtractionLayer.SEMANTIC_HTML

    def extract(self, content: PageContent) -> tuple[RawField, ...]:
        """Return every labelled value the document exposes."""
        candidates: list[RawField] = []
        candidates.extend(self._scheme_links(content))
        candidates.extend(self._address_elements(content))
        candidates.extend(self._hcards(content))
        candidates.extend(self._authorship(content))
        candidates.extend(self._profiles(content))
        candidates.extend(self._pgp_keys(content))
        candidates.extend(self._site_name(content))
        return tuple(candidates)

    def _scheme_links(self, content: PageContent) -> list[RawField]:
        found: list[RawField] = []
        for anchor in content.soup.find_all("a", href=True):
            href = (attribute_value(anchor, "href") or "").strip()
            lowered = href.lower()
            if lowered.startswith(MAILTO_PREFIX):
                value, field = href[len(MAILTO_PREFIX) :], FieldName.EMAIL
            elif lowered.startswith(TEL_PREFIX):
                value, field = href[len(TEL_PREFIX) :], FieldName.PHONE
            else:
                continue
            cleaned = value.split("?", 1)[0].strip()
            if cleaned:
                found.append(content.raw_field(field, cleaned, self.layer))
        return found

    def _address_elements(self, content: PageContent) -> list[RawField]:
        found: list[RawField] = []
        for element in content.soup.find_all("address"):
            text = collapse(element.get_text(" "))
            if text:
                found.append(
                    content.raw_field(FieldName.POSTAL_ADDRESS, text, self.layer)
                )
        return found

    def _hcards(self, content: PageContent) -> list[RawField]:
        found: list[RawField] = []
        for root in content.soup.find_all(True):
            if not (css_classes(root) & LEGACY_HCARD_ROOT_CLASSES):
                continue
            for element in root.find_all(True):
                for class_name in css_classes(element):
                    field = HCARD_CLASS_FIELDS.get(class_name)
                    if field is None:
                        continue
                    value = _hcard_value(element)
                    if value:
                        found.append(content.raw_field(field, value, self.layer))
        return found

    def _authorship(self, content: PageContent) -> list[RawField]:
        found: list[RawField] = []
        for meta in _meta_named(content, "author"):
            value = collapse(attribute_value(meta, "content") or "")
            if value:
                found.append(content.raw_field(FieldName.PERSON_NAME, value, self.layer))

        for link in _links_with_rel(content, "author"):
            href = (attribute_value(link, "href") or "").strip()
            if href.lower().startswith(MAILTO_PREFIX):
                found.append(
                    content.raw_field(
                        FieldName.EMAIL,
                        href[len(MAILTO_PREFIX) :].split("?", 1)[0],
                        self.layer,
                    )
                )
        return found

    def _profiles(self, content: PageContent) -> list[RawField]:
        """``rel="me"`` links and anchors pointing at a known platform."""
        seen: set[str] = set()
        found: list[RawField] = []
        elements = list(_links_with_rel(content, "me")) + list(
            content.soup.find_all("a", href=True)
        )
        for element in elements:
            href = (attribute_value(element, "href") or "").strip()
            platform = platform_of(href)
            if platform is None or href in seen:
                continue
            seen.add(href)
            found.append(
                content.raw_field(
                    FieldName.SOCIAL_PROFILE, href, self.layer, {"platform": platform}
                )
            )
        return found

    def _pgp_keys(self, content: PageContent) -> list[RawField]:
        found: list[RawField] = []
        for link in _links_with_rel(content, "pgpkey"):
            href = (attribute_value(link, "href") or "").strip()
            if href:
                found.append(content.raw_field(FieldName.PGP_KEY_URL, href, self.layer))
        for anchor in content.soup.find_all("a", href=True):
            href = (attribute_value(anchor, "href") or "").strip()
            if href.lower().endswith(PGP_KEY_SUFFIXES):
                found.append(content.raw_field(FieldName.PGP_KEY_URL, href, self.layer))
        return found

    def _site_name(self, content: PageContent) -> list[RawField]:
        found: list[RawField] = []
        for meta in content.soup.find_all("meta", attrs={"property": True}):
            if (attribute_value(meta, "property") or "").strip().lower() != "og:site_name":
                continue
            value = collapse(attribute_value(meta, "content") or "")
            if value:
                found.append(
                    content.raw_field(FieldName.ORGANIZATION_NAME, value, self.layer)
                )
        return found


def _meta_named(content: PageContent, name: str) -> Iterator[Tag]:
    for meta in content.soup.find_all("meta", attrs={"name": True}):
        if (attribute_value(meta, "name") or "").strip().lower() == name:
            yield meta


def _links_with_rel(content: PageContent, relation: str) -> Iterator[Tag]:
    for element in content.soup.find_all(["link", "a"], attrs={"rel": True}):
        if relation in (attribute_value(element, "rel") or "").lower().split():
            yield element


def _hcard_value(element: Tag) -> str:
    """Return the value an h-card property carries, preferring explicit attributes."""
    href = (attribute_value(element, "href") or "").strip()
    for prefix in (MAILTO_PREFIX, TEL_PREFIX):
        if href.lower().startswith(prefix):
            return href[len(prefix) :].split("?", 1)[0].strip()
    content_attribute = collapse(attribute_value(element, "content") or "")
    if content_attribute:
        return content_attribute
    return collapse(element.get_text(" "))
