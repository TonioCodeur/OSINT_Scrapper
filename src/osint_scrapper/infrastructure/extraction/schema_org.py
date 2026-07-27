"""Mapping schema.org vocabulary onto this product's field names.

Shared by the two structured-data layers: JSON-LD and microdata express the same
vocabulary in different syntaxes, so the property mapping belongs in one place.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from osint_scrapper.domain.attributes import FieldName
from osint_scrapper.infrastructure.extraction.text import collapse

PERSON_TYPES = frozenset({"person"})
ORGANIZATION_TYPES = frozenset(
    {
        "organization",
        "localbusiness",
        "corporation",
        "ngo",
        "educationalorganization",
        "governmentorganization",
        "nonprofit",
    }
)
ADDRESS_TYPES = frozenset({"postaladdress"})
CONTACT_TYPES = frozenset({"contactpoint"})

PERSON_PROPERTIES: Mapping[str, FieldName] = MappingProxyType(
    {
        "name": FieldName.PERSON_NAME,
        "email": FieldName.EMAIL,
        "telephone": FieldName.PHONE,
    }
)
"""``givenName``/``familyName`` are gone with the person-search product: one field
holds the name as the site published it, because splitting names is a locale
minefield this product gains nothing from."""

ORGANIZATION_PROPERTIES: Mapping[str, FieldName] = MappingProxyType(
    {
        "name": FieldName.ORGANIZATION_NAME,
        "legalname": FieldName.ORGANIZATION_NAME,
        "email": FieldName.EMAIL,
        "telephone": FieldName.PHONE,
        "vatid": FieldName.COMPANY_IDENTIFIER,
        "taxid": FieldName.COMPANY_IDENTIFIER,
        "leicode": FieldName.COMPANY_IDENTIFIER,
    }
)

CONTACT_PROPERTIES: Mapping[str, FieldName] = MappingProxyType(
    {
        "email": FieldName.EMAIL,
        "telephone": FieldName.PHONE,
    }
)

SAME_AS_PROPERTY = "sameas"
"""``sameAs`` is where a site declares its own profiles; it becomes ``social_profile``."""

JOB_TITLE_PROPERTY = "jobtitle"
"""Carried as ``metadata["role"]`` on the person's name, never as a field of its own:
an orphan row reading "CEO" attached to nobody is noise."""

ADDRESS_COMPONENT_ORDER = (
    "streetaddress",
    "postalcode",
    "addresslocality",
    "addressregion",
    "addresscountry",
)
"""Order of SPEC 8.4: street, postal code, locality, region, country."""


def normalize_property(name: str) -> str:
    """Return the comparable form of a schema.org property or type name."""
    return name.rsplit("/", 1)[-1].rsplit("#", 1)[-1].strip().lower()


def properties_for(type_name: str) -> Mapping[str, FieldName] | None:
    """Return the property map for a schema.org type, if this product supports it."""
    normalized = normalize_property(type_name)
    if normalized in PERSON_TYPES:
        return PERSON_PROPERTIES
    if normalized in ORGANIZATION_TYPES:
        return ORGANIZATION_PROPERTIES
    if normalized in CONTACT_TYPES:
        return CONTACT_PROPERTIES
    return None


def is_person_type(type_name: str) -> bool:
    """Whether the node describes a natural person."""
    return normalize_property(type_name) in PERSON_TYPES


def join_address(components: Mapping[str, str]) -> str:
    """Join address components in the documented order, skipping empty ones."""
    parts = [
        collapse(components[key])
        for key in ADDRESS_COMPONENT_ORDER
        if collapse(components.get(key, ""))
    ]
    return ", ".join(parts)


def strip_scheme(value: str) -> str:
    """Drop a ``mailto:`` or ``tel:`` prefix from a schema.org contact value."""
    lowered = value.strip().lower()
    for prefix in ("mailto:", "tel:"):
        if lowered.startswith(prefix):
            return value.strip()[len(prefix) :]
    return value.strip()
