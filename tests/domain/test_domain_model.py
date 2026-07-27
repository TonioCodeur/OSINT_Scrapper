"""The invariants the domain refuses to be built without."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from osint_scrapper.domain.attributes import (
    MAXIMUM_PROVENANCE_ENTRIES,
    MAXIMUM_RAW_VALUE_LENGTH,
    ExtractionLayer,
    FieldName,
    Finding,
    Provenance,
)
from osint_scrapper.domain.confidence import LAYER_BASE_CONFIDENCE, extraction_confidence
from osint_scrapper.domain.errors import (
    InvalidCrawlSettingsError,
    InvalidPurposeError,
    MissingProvenanceError,
    ProvenanceOverflowError,
)
from osint_scrapper.domain.target import (
    CrawlSettings,
    Purpose,
    PurposeCategory,
    resolve_target,
)
from tests.conftest import START_TIME


def make_provenance(url: str = "https://example.com/", raw: str = "contact@example.com"):
    return Provenance(
        source_url=url,
        collected_at=START_TIME,
        extraction_layer=ExtractionLayer.STRUCTURED_DATA,
        raw_value=raw,
    )


def test_provenance_refuses_a_blank_source_url() -> None:
    """SPEC FR-16: a record nobody can attribute is worthless in OSINT."""
    with pytest.raises(MissingProvenanceError):
        make_provenance(url="   ")


def test_provenance_refuses_a_naive_timestamp() -> None:
    """A naive timestamp would export as an unambiguous ``Z`` it has not earned."""
    with pytest.raises(MissingProvenanceError):
        Provenance(
            source_url="https://example.com/",
            collected_at=datetime(2026, 7, 27, 14, 0, 0),  # noqa: DTZ001
            extraction_layer=ExtractionLayer.SEMANTIC_HTML,
            raw_value="x",
        )


def test_provenance_refuses_a_non_utc_timestamp() -> None:
    """Aware is not enough: the export renders UTC and must not lie about it."""
    with pytest.raises(MissingProvenanceError):
        Provenance(
            source_url="https://example.com/",
            collected_at=datetime(2026, 7, 27, 14, 0, 0, tzinfo=timezone(timedelta(hours=2))),
            extraction_layer=ExtractionLayer.SEMANTIC_HTML,
            raw_value="x",
        )


def test_a_raw_value_is_capped_where_it_is_stored() -> None:
    """AC-LEGAL-3: the cap is applied at the only place raw page text is retained."""
    entry = make_provenance(raw="x" * (MAXIMUM_RAW_VALUE_LENGTH + 50))
    assert len(entry.raw_value) == MAXIMUM_RAW_VALUE_LENGTH


def test_a_finding_with_no_provenance_raises() -> None:
    """AC-LEGAL-2."""
    with pytest.raises(MissingProvenanceError):
        Finding(
            field=FieldName.EMAIL,
            value="contact@example.com",
            extraction_confidence=0.9,
            page_support=1,
            occurrence_count=1,
            first_seen_url="https://example.com/",
            provenance=(),
        )


def test_a_finding_with_too_much_provenance_raises() -> None:
    """AC-LEGAL-2: the cap is enforced rather than silently applied."""
    entries = tuple(
        make_provenance(url=f"https://example.com/{index}")
        for index in range(MAXIMUM_PROVENANCE_ENTRIES + 1)
    )
    with pytest.raises(ProvenanceOverflowError):
        Finding(
            field=FieldName.EMAIL,
            value="contact@example.com",
            extraction_confidence=0.9,
            page_support=11,
            occurrence_count=11,
            first_seen_url="https://example.com/0",
            provenance=entries,
        )


def test_confidence_is_the_best_layer_and_nothing_else() -> None:
    """SPEC 8.6: a discrete label, never a blend, never arithmetic."""
    assert extraction_confidence(
        [ExtractionLayer.TEXT_HEURISTIC, ExtractionLayer.STRUCTURED_DATA]
    ) == LAYER_BASE_CONFIDENCE[ExtractionLayer.STRUCTURED_DATA]


def test_every_layer_has_exactly_the_documented_base() -> None:
    """The five values of SPEC 8.2, unchanged by the refactor."""
    assert dict(LAYER_BASE_CONFIDENCE) == {
        ExtractionLayer.WELL_KNOWN: 0.95,
        ExtractionLayer.STRUCTURED_DATA: 0.90,
        ExtractionLayer.SEMANTIC_HTML: 0.75,
        ExtractionLayer.TEXT_HEURISTIC: 0.50,
        ExtractionLayer.TEXT_HEURISTIC_DEOBFUSCATED: 0.40,
    }


def test_field_declaration_order_is_the_export_order() -> None:
    """SPEC 8.1: this order is load-bearing and is asserted, not assumed."""
    assert [str(field) for field in FieldName] == [
        "email",
        "phone",
        "postal_address",
        "person_name",
        "organization_name",
        "social_profile",
        "pgp_key_url",
        "company_identifier",
        "technology",
    ]


def test_purpose_other_requires_a_real_note() -> None:
    """SPEC 7.2.2: the v1.0 guard survives, aimed at the case that needs it."""
    with pytest.raises(InvalidPurposeError):
        Purpose(category=PurposeCategory.OTHER, note="too short")
    assert Purpose(category=PurposeCategory.OTHER, note="a genuinely stated reason").note


def test_a_named_purpose_needs_no_note() -> None:
    """Five categories explain themselves; one does not."""
    assert Purpose(category=PurposeCategory.DUE_DILIGENCE).note == ""


BAD_SETTINGS = [
    {"max_pages": 99999},
    {"max_pages": 0},
    {"max_depth": 11},
    {"max_depth": -1},
    {"request_interval_seconds": 0.1},
    {"request_interval_seconds": 61.0},
    {"concurrent_requests": 0},
    {"concurrent_requests": 5},
    {"phone_region": "fr"},
]


@pytest.mark.parametrize("overrides", BAD_SETTINGS, ids=lambda item: str(item))
def test_settings_enforce_their_bounds_in_the_domain(overrides: dict[str, object]) -> None:
    """AC-UI-6: a config file cannot smuggle a larger budget past the widgets."""
    with pytest.raises(InvalidCrawlSettingsError):
        CrawlSettings(**overrides)  # type: ignore[arg-type]


def test_default_settings_are_the_documented_ones() -> None:
    """SPEC 5.5, asserted so a change to a default is a change to a test."""
    settings = CrawlSettings()
    assert (settings.max_pages, settings.max_depth) == (200, 3)
    assert (settings.request_interval_seconds, settings.concurrent_requests) == (1.0, 2)
    assert settings.retention_days == 30


def test_a_target_carries_its_own_scope() -> None:
    """The interface reads this to render its live hint line."""
    target = resolve_target(" www.Example.com ", include_subdomains=True)
    assert target.target_url == "https://www.example.com/"
    assert target.scope_host == "example.com"
    assert target.scope.contains("https://blog.example.com/a")
    assert target.entered_value == "www.Example.com"


def test_the_collected_at_of_a_provenance_stays_utc() -> None:
    """Exports render ``Z``; the entity is what guarantees they may."""
    assert make_provenance().collected_at.tzinfo is UTC
