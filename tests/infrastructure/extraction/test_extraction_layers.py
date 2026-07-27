"""Each extraction layer against the committed mini-site (SPEC 8.2)."""

from __future__ import annotations

import pytest

from osint_scrapper.application.errors import SelectorNotFoundError
from osint_scrapper.domain.attributes import ExtractionLayer, FieldName, RawField
from tests.conftest import make_page, read_fixture
from tests.wiring import build_pipeline

REGION = "FR"


def extract(name: str, url: str = "https://example.com/contact", **kwargs) -> tuple[RawField, ...]:
    page = make_page(read_fixture("site", name), url=url, **kwargs)
    return build_pipeline().extract(page, REGION)


def values(candidates: tuple[RawField, ...], field: FieldName) -> set[str]:
    return {item.raw_value for item in candidates if item.field is field}


def layers(candidates: tuple[RawField, ...], field: FieldName) -> set[ExtractionLayer]:
    return {item.extraction_layer for item in candidates if item.field is field}


def test_json_ld_yields_the_organization_block() -> None:
    """Layer 2: schema.org in a ``<script type="application/ld+json">``."""
    found = extract("contact.html")
    structured = [
        item for item in found if item.extraction_layer is ExtractionLayer.STRUCTURED_DATA
    ]
    assert "contact@example.com" in {item.raw_value for item in structured}
    assert "Example Association" in {item.raw_value for item in structured}
    assert "12 rue des Lilas, 75011, Paris, France" in {item.raw_value for item in structured}
    assert "FR42999000003" in {item.raw_value for item in structured}


def test_same_as_becomes_a_social_profile_only_for_known_platforms() -> None:
    """SPEC 8.1: never a link dump of the open web."""
    found = extract("contact.html")
    profiles = values(found, FieldName.SOCIAL_PROFILE)
    assert "https://github.com/example-association" in profiles
    assert "https://example.net/not-a-platform" not in profiles


def test_microdata_yields_a_person_with_a_role_in_metadata() -> None:
    """SPEC 8.1: a job title hangs off the name rather than becoming a field."""
    found = extract("team.html", url="https://example.com/equipe/")
    person = next(
        item
        for item in found
        if item.field is FieldName.PERSON_NAME and item.raw_value == "Noé Lambert"
    )
    assert person.metadata["role"] == "Treasurer"


def test_a_nested_address_belongs_to_its_own_item() -> None:
    """The nesting-scope rule, kept from v1.0."""
    found = extract("legal_notice.html", url="https://example.com/mentions-legales")
    assert "12 rue des Lilas, 75011, Paris, France" in values(found, FieldName.POSTAL_ADDRESS)


def test_semantic_html_reads_mailto_tel_address_and_hcard() -> None:
    """Layer 3, the most valuable part of the old extractor, unchanged."""
    found = extract("team.html", url="https://example.com/equipe/")
    assert "c.ferrand@example.com" in values(found, FieldName.EMAIL)
    assert "Camille Ferrand" in values(found, FieldName.PERSON_NAME)
    assert "Example Association" in values(found, FieldName.ORGANIZATION_NAME)
    assert "12 rue des Lilas, 75011 Paris, France" in values(found, FieldName.POSTAL_ADDRESS)


def test_rel_me_becomes_a_social_profile() -> None:
    found = extract("team.html", url="https://example.com/equipe/")
    assert "https://mastodon.social/@example-association" in values(
        found, FieldName.SOCIAL_PROFILE
    )


def test_a_key_link_becomes_a_pgp_key_url() -> None:
    """SPEC 8.1: the URL is the fact; the key is never fetched."""
    found = extract("legal_notice.html", url="https://example.com/mentions-legales")
    assert "/pgp-key.asc" in values(found, FieldName.PGP_KEY_URL)


def test_og_site_name_becomes_the_organization() -> None:
    found = extract("index.html", url="https://example.com/")
    assert "Example Association" in values(found, FieldName.ORGANIZATION_NAME)


def test_technology_comes_from_the_generator_and_two_headers_and_nothing_else() -> None:
    """AC-EXTRACT-9."""
    found = extract(
        "index.html",
        url="https://example.com/",
        headers={"server": "nginx", "x-powered-by": "PHP/8.3", "x-frame-options": "DENY"},
    )
    assert values(found, FieldName.TECHNOLOGY) == {"ExampleCMS 3.2", "nginx", "PHP/8.3"}
    assert layers(found, FieldName.TECHNOLOGY) == {ExtractionLayer.SEMANTIC_HTML}


def test_text_heuristics_find_only_self_validating_values() -> None:
    """SPEC FR-23: email, phone and company identifiers, and nothing else."""
    found = extract("contact.html")
    text_layer = {
        item.field for item in found if item.extraction_layer is ExtractionLayer.TEXT_HEURISTIC
    }
    assert text_layer <= {FieldName.EMAIL, FieldName.PHONE, FieldName.COMPANY_IDENTIFIER}
    assert "dpo@example.com" in values(found, FieldName.EMAIL)


def test_company_identifier_candidates_are_offered_from_text() -> None:
    """AC-EXTRACT-7: the checksum is what makes this legal to read from prose."""
    found = extract("legal_notice.html", url="https://example.com/mentions-legales")
    raw = values(found, FieldName.COMPANY_IDENTIFIER)
    assert any("999 000 003" in item for item in raw)
    assert any("FR42999000003" in item for item in raw)
    assert any(
        item.metadata.get("scheme") == "rcs"
        for item in found
        if item.field is FieldName.COMPANY_IDENTIFIER
    )


def test_a_published_obfuscated_address_is_rewritten_at_the_lowest_layer() -> None:
    """AC-EXTRACT-3."""
    found = extract("obfuscated.html", url="https://example.com/obfuscated")
    deobfuscated = [
        item
        for item in found
        if item.extraction_layer is ExtractionLayer.TEXT_HEURISTIC_DEOBFUSCATED
    ]
    assert {item.raw_value for item in deobfuscated} == {"jean@example.com"}
    assert deobfuscated[0].metadata["obfuscated_as"].startswith("jean")


def test_a_response_that_is_not_a_document_raises_and_names_what_was_missing() -> None:
    """AC-EXTRACT-10: loud and specific, never a half-filled record."""
    with pytest.raises(SelectorNotFoundError) as failure:
        extract("broken.html", url="https://example.com/broken")
    assert "any HTML element" in str(failure.value)
    assert failure.value.url == "https://example.com/broken"


def test_a_non_html_media_type_raises_rather_than_returning_nothing() -> None:
    """A silent empty answer would read as "this page publishes nothing"."""
    page = make_page("<dataset/>", url="https://example.com/d.xml", content_type="application/xml")
    with pytest.raises(SelectorNotFoundError):
        build_pipeline().extract(page, REGION)


def test_every_candidate_is_stamped_with_its_page_and_moment() -> None:
    """SPEC FR-16: provenance is built at the point of extraction, not later."""
    found = extract("contact.html")
    assert found
    assert all(item.source_url == "https://example.com/contact" for item in found)
    assert all(item.collected_at.tzinfo is not None for item in found)
