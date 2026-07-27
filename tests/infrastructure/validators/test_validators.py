"""Every field validator, including the checksums that make FR-23 defensible."""

from __future__ import annotations

import pytest

from osint_scrapper.application.ports import ValidatedValue
from osint_scrapper.domain.attributes import ExtractionLayer, FieldName, RawField
from osint_scrapper.domain.errors import ValidationRejectedError
from osint_scrapper.infrastructure.validators.address import PostalAddressValidator
from osint_scrapper.infrastructure.validators.company_id import (
    CompanyIdentifierValidator,
    luhn_holds,
)
from osint_scrapper.infrastructure.validators.email import EmailValidator
from osint_scrapper.infrastructure.validators.names import PersonNameValidator
from osint_scrapper.infrastructure.validators.organization import OrganizationValidator
from osint_scrapper.infrastructure.validators.pgp import PgpKeyUrlValidator
from osint_scrapper.infrastructure.validators.phone import PhoneValidator
from osint_scrapper.infrastructure.validators.social import SocialProfileValidator
from osint_scrapper.infrastructure.validators.technology import TechnologyValidator
from tests.conftest import START_TIME

REGION = "FR"
SIREN = "999000003"
SIRET = "99900000300007"
VAT = "FR42999000003"


def candidate(
    value: str,
    field: FieldName = FieldName.EMAIL,
    metadata: dict[str, str] | None = None,
    layer: ExtractionLayer = ExtractionLayer.SEMANTIC_HTML,
) -> RawField:
    return RawField(
        field=field,
        raw_value=value,
        source_url="https://example.com/",
        collected_at=START_TIME,
        extraction_layer=layer,
        metadata=metadata or {},
    )


def validate(validator: object, value: str, **kwargs) -> ValidatedValue:
    return validator.validate(candidate(value, **kwargs), REGION)  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("local", "kind"),
    [
        ("contact", "role"),
        ("dpo", "role"),
        ("presse", "role"),
        ("no-reply", "role"),
        ("j.martin", "other"),
        ("camille.ferrand", "other"),
    ],
)
def test_email_kind_separates_role_mailboxes_from_the_rest(local: str, kind: str) -> None:
    """AC-EXTRACT-6: a role mailbox is organizational and must be filterable."""
    result = validate(EmailValidator(), f"{local}@Example.com")
    assert result.value == f"{local}@example.com"
    assert result.metadata["email_kind"] == kind


def test_an_invalid_address_never_becomes_a_fact() -> None:
    with pytest.raises(ValidationRejectedError):
        validate(EmailValidator(), "not an address")


def test_a_valid_number_is_stored_as_e164_with_its_type() -> None:
    """AC-EXTRACT-4."""
    result = validate(PhoneValidator(), "+33 1 23 45 67 89", field=FieldName.PHONE)
    assert result.value == "+33123456789"
    assert result.metadata["number_type"] == "FIXED_LINE"


def test_an_incomplete_number_is_rejected() -> None:
    """AC-EXTRACT-4: ``+33 1 23`` must be absent from every export."""
    with pytest.raises(ValidationRejectedError):
        validate(PhoneValidator(), "+33 1 23", field=FieldName.PHONE)


def test_an_address_keeps_its_diacritics_and_folds_only_its_key() -> None:
    result = validate(
        PostalAddressValidator(), "  12 rue des Lilas,  75011 Paris ",
        field=FieldName.POSTAL_ADDRESS,
    )
    assert result.value == "12 rue des Lilas, 75011 Paris"
    assert result.dedup_value == "12 rue des lilas 75011 paris"


@pytest.mark.parametrize("bad", ["a", "1234567", "x" * 400])
def test_an_implausible_address_is_rejected(bad: str) -> None:
    with pytest.raises(ValidationRejectedError):
        validate(PostalAddressValidator(), bad, field=FieldName.POSTAL_ADDRESS)


def test_a_name_keeps_its_casing_and_diacritics() -> None:
    result = validate(PersonNameValidator(), "  Noé   Lambert ", field=FieldName.PERSON_NAME)
    assert result.value == "Noé Lambert"
    assert result.dedup_value == "noe lambert"


@pytest.mark.parametrize("bad", ["Agent 47", "", "x" * 90, "-- --"])
def test_a_name_that_is_not_a_name_is_rejected(bad: str) -> None:
    with pytest.raises(ValidationRejectedError):
        validate(PersonNameValidator(), bad, field=FieldName.PERSON_NAME)


def test_an_organization_name_is_collapsed_and_bounded() -> None:
    result = validate(
        OrganizationValidator(), " Example  Association ", field=FieldName.ORGANIZATION_NAME
    )
    assert result.value == "Example Association"
    with pytest.raises(ValidationRejectedError):
        validate(OrganizationValidator(), "x" * 300, field=FieldName.ORGANIZATION_NAME)


def test_a_profile_url_is_normalized_and_carries_its_platform() -> None:
    """AC-EXTRACT-8."""
    result = validate(
        SocialProfileValidator(),
        "https://www.GitHub.com/example-association/?utm_source=x",
        field=FieldName.SOCIAL_PROFILE,
    )
    assert result.value == "https://github.com/example-association"
    assert result.metadata["platform"] == "github"


@pytest.mark.parametrize(
    "bad",
    [
        "https://github.com/",
        "https://example.net/someone",
        "@exampleorg",
        "github.com/exampleorg",
    ],
)
def test_anything_that_is_not_a_full_profile_url_is_rejected(bad: str) -> None:
    """AC-EXTRACT-8: a platform root is a website, and a handle is ambiguous."""
    with pytest.raises(ValidationRejectedError):
        validate(SocialProfileValidator(), bad, field=FieldName.SOCIAL_PROFILE)


def test_a_pgp_key_url_is_accepted_and_never_fetched() -> None:
    result = validate(
        PgpKeyUrlValidator(), "https://Example.com/pgp-key.asc", field=FieldName.PGP_KEY_URL
    )
    assert result.value == "https://example.com/pgp-key.asc"
    with pytest.raises(ValidationRejectedError):
        validate(PgpKeyUrlValidator(), "/pgp-key.asc", field=FieldName.PGP_KEY_URL)


def test_a_technology_is_short_and_non_empty() -> None:
    result = validate(TechnologyValidator(), " nginx ", field=FieldName.TECHNOLOGY)
    assert result.value == "nginx"
    with pytest.raises(ValidationRejectedError):
        validate(TechnologyValidator(), "   ", field=FieldName.TECHNOLOGY)


def test_the_luhn_checksum_is_what_makes_text_extraction_defensible() -> None:
    assert luhn_holds(SIREN)
    assert luhn_holds(SIRET)
    assert not luhn_holds("999000004")


@pytest.mark.parametrize(
    ("raw", "scheme", "value"),
    [
        ("999 000 003", "siren", SIREN),
        ("999.000.003.00007", "siret", SIRET),
        (VAT, "vat_eu", VAT),
        ("DE123456789", "vat_eu", "DE123456789"),
    ],
)
def test_a_valid_identifier_records_its_scheme(raw: str, scheme: str, value: str) -> None:
    """AC-EXTRACT-7."""
    result = validate(
        CompanyIdentifierValidator(), raw, field=FieldName.COMPANY_IDENTIFIER
    )
    assert result.value == value
    assert result.metadata["scheme"] == scheme


def test_an_rcs_hint_survives_when_the_digits_hold() -> None:
    result = validate(
        CompanyIdentifierValidator(),
        "999 000 003",
        field=FieldName.COMPANY_IDENTIFIER,
        metadata={"scheme": "rcs"},
    )
    assert result.metadata["scheme"] == "rcs"


@pytest.mark.parametrize(
    "bad",
    [
        "999 000 004",
        "99900000300008",
        "FR43999000003",
        "DE12345",
        "ZZ123456789",
        "12345",
        "not-an-identifier",
    ],
)
def test_an_identifier_that_fails_its_check_is_discarded_not_downgraded(bad: str) -> None:
    """AC-EXTRACT-7: never exported with a lower score — discarded entirely."""
    with pytest.raises(ValidationRejectedError):
        validate(CompanyIdentifierValidator(), bad, field=FieldName.COMPANY_IDENTIFIER)


def test_every_validator_declares_the_field_it_answers_for() -> None:
    """The registry is keyed by field, so a mismatch would be a silent bug."""
    pairs = [
        (EmailValidator(), FieldName.EMAIL),
        (PhoneValidator(), FieldName.PHONE),
        (PostalAddressValidator(), FieldName.POSTAL_ADDRESS),
        (PersonNameValidator(), FieldName.PERSON_NAME),
        (OrganizationValidator(), FieldName.ORGANIZATION_NAME),
        (SocialProfileValidator(), FieldName.SOCIAL_PROFILE),
        (PgpKeyUrlValidator(), FieldName.PGP_KEY_URL),
        (CompanyIdentifierValidator(), FieldName.COMPANY_IDENTIFIER),
        (TechnologyValidator(), FieldName.TECHNOLOGY),
    ]
    assert [validator.field for validator, _ in pairs] == [field for _, field in pairs]
