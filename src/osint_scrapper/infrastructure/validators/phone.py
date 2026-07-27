"""Phone validation through libphonenumber (SPEC 8.4).

A hand-written regex is never used: on a field this sensitive, a false positive
exported as fact is exactly the failure Rule 0 forbids.
"""

from __future__ import annotations

import phonenumbers

from osint_scrapper.application.ports import ValidatedValue
from osint_scrapper.domain.attributes import FieldName, RawField
from osint_scrapper.domain.errors import ValidationRejectedError

NUMBER_TYPE_KEY = "number_type"


class PhoneValidator:
    """Parses a candidate in the crawl's region and stores it as E.164."""

    @property
    def field(self) -> FieldName:
        """The field this validator is responsible for."""
        return FieldName.PHONE

    def validate(self, candidate: RawField, region: str) -> ValidatedValue:
        """Return the E.164 form of a valid number.

        Raises:
            ValidationRejectedError: the candidate does not parse, or is not a
                valid number for the crawl's region.
        """
        raw = candidate.raw_value.strip()
        try:
            number = phonenumbers.parse(raw, region)
        except phonenumbers.NumberParseException as rejection:
            raise ValidationRejectedError(
                f"{raw!r} is not a parseable phone number: {rejection}"
            ) from rejection

        if not phonenumbers.is_valid_number(number):
            raise ValidationRejectedError(
                f"{raw!r} parses but is not a valid number in region {region}"
            )

        formatted = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
        return ValidatedValue(
            value=formatted,
            dedup_value=formatted,
            metadata={
                NUMBER_TYPE_KEY: phonenumbers.PhoneNumberType.to_string(
                    phonenumbers.number_type(number)
                )
            },
        )
