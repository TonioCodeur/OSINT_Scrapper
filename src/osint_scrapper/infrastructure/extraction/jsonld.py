"""Layer 2a: schema.org JSON-LD embedded in ``<script type="application/ld+json">``."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

from osint_scrapper.domain.attributes import ExtractionLayer, FieldName, RawField
from osint_scrapper.infrastructure.extraction.pipeline import PageContent
from osint_scrapper.infrastructure.extraction.schema_org import (
    ADDRESS_TYPES,
    JOB_TITLE_PROPERTY,
    SAME_AS_PROPERTY,
    is_person_type,
    join_address,
    normalize_property,
    properties_for,
    strip_scheme,
)
from osint_scrapper.infrastructure.extraction.social import platform_of
from osint_scrapper.infrastructure.extraction.text import collapse

logger = logging.getLogger(__name__)

JSON_LD_SELECTOR = 'script[type="application/ld+json"]'
_MAXIMUM_DEPTH = 12
"""Guards against a hand-crafted document with pathological nesting."""

_NESTED_KEYS = frozenset({"@graph", "employee", "founder", "author", "publisher", "member"})


class JsonLdExtractor:
    """Reads schema.org objects out of JSON-LD blocks."""

    @property
    def layer(self) -> ExtractionLayer:
        """Structured markup published by the site itself."""
        return ExtractionLayer.STRUCTURED_DATA

    def extract(self, content: PageContent) -> tuple[RawField, ...]:
        """Return every supported schema.org value found in the page's JSON-LD.

        A malformed block is skipped rather than fatal: sites frequently ship one
        broken block alongside several valid ones, and refusing the whole page
        would lose data the site deliberately published.
        """
        candidates: list[RawField] = []
        for script in content.soup.select(JSON_LD_SELECTOR):
            payload = script.get_text()
            if not payload.strip():
                continue
            try:
                document = json.loads(payload)
            except json.JSONDecodeError as failure:
                logger.debug("skipping malformed JSON-LD on %s: %s", content.url, failure)
                continue
            for node in _walk(document, depth=0):
                candidates.extend(self._from_node(node, content))
        return tuple(candidates)

    def _from_node(self, node: dict[str, Any], content: PageContent) -> list[RawField]:
        type_name = _type_of(node) or ""
        properties = properties_for(type_name)
        if properties is None:
            return []

        role = collapse(_scalar(node.get(JOB_TITLE_PROPERTY) or node.get("jobtitle")))
        metadata = {"role": role} if role and is_person_type(type_name) else None

        found: list[RawField] = []
        for key, value in node.items():
            field = properties.get(normalize_property(key))
            text = _scalar(value)
            if field is None or not text:
                continue
            found.append(
                content.raw_field(
                    field=field,
                    raw_value=strip_scheme(text),
                    layer=self.layer,
                    metadata=metadata if field is FieldName.PERSON_NAME else None,
                )
            )

        found.extend(self._address_of(node, content))
        found.extend(self._profiles_of(node, content))
        return found

    def _address_of(self, node: dict[str, Any], content: PageContent) -> list[RawField]:
        joined = _address_text(node.get("address"))
        if not joined:
            return []
        return [
            content.raw_field(
                field=FieldName.POSTAL_ADDRESS, raw_value=joined, layer=self.layer
            )
        ]

    def _profiles_of(self, node: dict[str, Any], content: PageContent) -> list[RawField]:
        """Turn ``sameAs`` into social profiles, keeping only known platforms."""
        found: list[RawField] = []
        for key, value in node.items():
            if normalize_property(key) != SAME_AS_PROPERTY:
                continue
            for url in _scalars(value):
                platform = platform_of(url)
                if platform is None:
                    continue
                found.append(
                    content.raw_field(
                        field=FieldName.SOCIAL_PROFILE,
                        raw_value=url,
                        layer=self.layer,
                        metadata={"platform": platform},
                    )
                )
        return found


def _walk(document: Any, depth: int) -> Iterator[dict[str, Any]]:
    """Yield every object in a JSON-LD document, following ``@graph`` and lists."""
    if depth > _MAXIMUM_DEPTH:
        return
    if isinstance(document, list):
        for item in document:
            yield from _walk(item, depth + 1)
        return
    if not isinstance(document, dict):
        return
    yield document
    for key, value in document.items():
        if key in _NESTED_KEYS:
            yield from _walk(value, depth + 1)


def _type_of(node: dict[str, Any]) -> str | None:
    raw = node.get("@type") or node.get("type")
    if isinstance(raw, list):
        return next((str(item) for item in raw if item), None)
    return str(raw) if raw else None


def _scalar(value: Any) -> str:
    """Return a usable string for a JSON-LD value, or an empty string."""
    if isinstance(value, str):
        return collapse(value)
    if isinstance(value, list):
        return next((_scalar(item) for item in value if _scalar(item)), "")
    return ""


def _scalars(value: Any) -> list[str]:
    """Return every string a JSON-LD value carries, flattened."""
    if isinstance(value, str):
        collapsed = collapse(value)
        return [collapsed] if collapsed else []
    if isinstance(value, list):
        return [item for entry in value for item in _scalars(entry)]
    return []


def _address_text(address: Any) -> str:
    """Render a schema.org address, whether it is a string or a PostalAddress."""
    if isinstance(address, str):
        return collapse(address)
    if isinstance(address, list):
        return next((_address_text(item) for item in address if _address_text(item)), "")
    if not isinstance(address, dict):
        return ""
    if normalize_property(_type_of(address) or "postaladdress") not in ADDRESS_TYPES:
        return ""
    components = {
        normalize_property(key): _scalar(value)
        for key, value in address.items()
        if not key.startswith("@")
    }
    return join_address(components)
