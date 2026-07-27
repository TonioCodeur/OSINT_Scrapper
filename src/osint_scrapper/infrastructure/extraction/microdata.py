"""Layer 2b: schema.org microdata expressed as ``itemscope`` / ``itemprop`` attributes."""

from __future__ import annotations

import logging

from bs4 import Tag

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
from osint_scrapper.infrastructure.extraction.text import attribute_value, collapse

logger = logging.getLogger(__name__)

VALUE_ATTRIBUTES = ("content", "href", "src", "datetime")
"""Attributes that carry an itemprop's value instead of the element's text."""

ITEMSCOPE_SELECTOR = "[itemscope]"
ITEMPROP_SELECTOR = "[itemprop]"


class MicrodataExtractor:
    """Reads schema.org microdata items."""

    @property
    def layer(self) -> ExtractionLayer:
        """Structured markup published by the site itself."""
        return ExtractionLayer.STRUCTURED_DATA

    def extract(self, content: PageContent) -> tuple[RawField, ...]:
        """Return every supported microdata value found in the page."""
        candidates: list[RawField] = []
        for item in content.soup.select(ITEMSCOPE_SELECTOR):
            candidates.extend(self._from_item(item, content))
        return tuple(candidates)

    def _from_item(self, item: Tag, content: PageContent) -> list[RawField]:
        item_type = attribute_value(item, "itemtype") or ""
        properties = _own_properties(item)

        if normalize_property(item_type) in ADDRESS_TYPES:
            joined = join_address(properties)
            if not joined:
                return []
            return [
                content.raw_field(
                    field=FieldName.POSTAL_ADDRESS, raw_value=joined, layer=self.layer
                )
            ]

        property_map = properties_for(item_type)
        if property_map is None:
            return []

        role = properties.get(JOB_TITLE_PROPERTY, "")
        metadata = {"role": role} if role and is_person_type(item_type) else None

        found: list[RawField] = []
        for name, value in properties.items():
            if name == SAME_AS_PROPERTY:
                found.extend(self._profile(content, value))
                continue
            field = property_map.get(name)
            if field is None or not value:
                continue
            found.append(
                content.raw_field(
                    field=field,
                    raw_value=strip_scheme(value),
                    layer=self.layer,
                    metadata=metadata if field is FieldName.PERSON_NAME else None,
                )
            )
        return found

    def _profile(self, content: PageContent, value: str) -> list[RawField]:
        platform = platform_of(value)
        if platform is None:
            return []
        return [
            content.raw_field(
                field=FieldName.SOCIAL_PROFILE,
                raw_value=value,
                layer=self.layer,
                metadata={"platform": platform},
            )
        ]


def _own_properties(item: Tag) -> dict[str, str]:
    """Return the item's own ``itemprop`` values, excluding nested items'.

    A property belongs to the nearest enclosing ``itemscope``; walking into a
    nested item would attribute a company's phone number to a person.
    """
    properties: dict[str, str] = {}
    for element in item.select(ITEMPROP_SELECTOR):
        if _nearest_scope(element, item) is not item:
            continue
        name = normalize_property(attribute_value(element, "itemprop") or "")
        if not name or name in properties:
            continue
        value = _value_of(element)
        if value:
            properties[name] = value
    return properties


def _nearest_scope(element: Tag, root: Tag) -> Tag | None:
    parent = element.parent
    while isinstance(parent, Tag):
        if parent.has_attr("itemscope"):
            return parent
        if parent is root:
            return root
        parent = parent.parent
    return None


def _value_of(element: Tag) -> str:
    for attribute in VALUE_ATTRIBUTES:
        value = attribute_value(element, attribute)
        if value:
            return collapse(value)
    return collapse(element.get_text(" "))
