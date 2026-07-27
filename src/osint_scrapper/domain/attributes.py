"""Findings, their provenance, and the raw contract extractors emit."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType

from osint_scrapper.domain.errors import MissingProvenanceError, ProvenanceOverflowError

EMPTY_METADATA: Mapping[str, str] = MappingProxyType({})

MAXIMUM_RAW_VALUE_LENGTH = 200
"""SPEC FR-15: the only raw page text this product keeps, and only for an accepted value."""

MAXIMUM_PROVENANCE_ENTRIES = 10
"""SPEC 8.6: bounds a report where a footer email appears on four hundred pages."""


class FieldName(StrEnum):
    """The only fields this product ever extracts, stores or exports (SPEC 8.1).

    Declaration order is load-bearing: it is the primary sort key of every
    export (SPEC 9.1.1).
    """

    EMAIL = "email"
    PHONE = "phone"
    POSTAL_ADDRESS = "postal_address"
    PERSON_NAME = "person_name"
    ORGANIZATION_NAME = "organization_name"
    SOCIAL_PROFILE = "social_profile"
    PGP_KEY_URL = "pgp_key_url"
    COMPANY_IDENTIFIER = "company_identifier"
    TECHNOLOGY = "technology"


FIELD_ORDER = {field: index for index, field in enumerate(FieldName)}
"""Declaration order of :class:`FieldName`, which every export sorts by."""


class ExtractionLayer(StrEnum):
    """How a value was obtained, in decreasing order of authority (SPEC 8.2)."""

    WELL_KNOWN = "well_known"
    STRUCTURED_DATA = "structured_data"
    SEMANTIC_HTML = "semantic_html"
    TEXT_HEURISTIC = "text_heuristic"
    TEXT_HEURISTIC_DEOBFUSCATED = "text_heuristic_deobfuscated"


LAYER_ORDER = {layer: index for index, layer in enumerate(ExtractionLayer)}
"""Used only to break ties deterministically; the score lives in ``confidence.py``."""


@dataclass(frozen=True)
class RawField:
    """One unvalidated candidate produced by an extractor.

    This is the whole extractor-to-application contract. An extractor never
    builds a :class:`Finding`: validation, deduplication and counting are
    business rules that belong to the application layer.
    """

    field: FieldName
    raw_value: str
    source_url: str
    collected_at: datetime
    """When the document this value came from was retrieved (SPEC FR-16)."""

    extraction_layer: ExtractionLayer
    metadata: Mapping[str, str] = EMPTY_METADATA


@dataclass(frozen=True)
class Provenance:
    """Where and when a single accepted value was observed (SPEC FR-16)."""

    source_url: str
    collected_at: datetime
    extraction_layer: ExtractionLayer
    raw_value: str

    def __post_init__(self) -> None:
        """Refuse provenance that could not be audited, and cap the raw value.

        A blank source URL or a timestamp with no timezone would still export
        without error, producing a record that looks attributed and is not. The
        UTC requirement is what lets exports render an unambiguous ``Z`` suffix.
        The 200-character cap is data minimization made mechanical (SPEC FR-15):
        it is applied here, at the only place raw page text is ever retained, so
        no writer has to remember it.
        """
        if not self.source_url.strip():
            raise MissingProvenanceError(
                "provenance has no source URL; a record nobody can attribute is "
                "worthless in OSINT"
            )
        if self.collected_at.utcoffset() != timedelta(0):
            raise MissingProvenanceError(
                f"provenance from {self.source_url} has collected_at "
                f"{self.collected_at!r}, which is not an aware UTC timestamp"
            )
        if len(self.raw_value) > MAXIMUM_RAW_VALUE_LENGTH:
            object.__setattr__(self, "raw_value", self.raw_value[:MAXIMUM_RAW_VALUE_LENGTH])

    def sort_key(self) -> tuple[str, str, str]:
        """Deterministic ordering key for exports (SPEC 9.1.1)."""
        return (self.source_url, self.collected_at.isoformat(), str(self.extraction_layer))


@dataclass(frozen=True)
class Finding:
    """One deduplicated value the site publishes, with every place it was seen.

    The two numbers are deliberately not blended (SPEC 8.6):
    ``extraction_confidence`` says how the value was obtained, ``page_support``
    says on how many distinct pages of this site it appeared. Neither is a
    probability and no arithmetic combines them.
    """

    field: FieldName
    value: str
    extraction_confidence: float
    page_support: int
    occurrence_count: int
    first_seen_url: str
    provenance: tuple[Provenance, ...]
    metadata: Mapping[str, str] = EMPTY_METADATA

    def __post_init__(self) -> None:
        if not self.provenance:
            raise MissingProvenanceError(
                f"finding {self.field}={self.value!r} has no provenance; "
                "an unattributable result is worthless in OSINT"
            )
        if len(self.provenance) > MAXIMUM_PROVENANCE_ENTRIES:
            raise ProvenanceOverflowError(
                f"finding {self.field}={self.value!r} carries {len(self.provenance)} "
                f"provenance entries, above the cap of {MAXIMUM_PROVENANCE_ENTRIES}"
            )

    def sort_key(self) -> tuple[int, float, int, str]:
        """Field declaration order, confidence descending, support descending, value."""
        return (
            FIELD_ORDER[self.field],
            -self.extraction_confidence,
            -self.page_support,
            self.value,
        )
