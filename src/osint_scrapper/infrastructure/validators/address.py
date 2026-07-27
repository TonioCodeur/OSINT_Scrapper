"""Postal address validation (SPEC 8.4).

Only structured layers ever reach this validator: the application's layer policy
refuses a postal address read out of free text, because a wrong address exported
as fact is the failure mode Rule 0 forbids.
"""

from __future__ import annotations

import re

from osint_scrapper.application.ports import ValidatedValue
from osint_scrapper.domain.attributes import FieldName, RawField
from osint_scrapper.domain.errors import ValidationRejectedError
from osint_scrapper.domain.text import collapse_whitespace

MINIMUM_ADDRESS_LENGTH = 6
MAXIMUM_ADDRESS_LENGTH = 300

_NON_ALPHANUMERIC_RUN = re.compile(r"[^a-z0-9]+")


class PostalAddressValidator:
    """Accepts an already-assembled address string and normalizes its shape."""

    @property
    def field(self) -> FieldName:
        """The field this validator is responsible for."""
        return FieldName.POSTAL_ADDRESS

    def validate(self, candidate: RawField, region: str) -> ValidatedValue:
        """Return the collapsed address.

        Raises:
            ValidationRejectedError: the candidate is too short or too long to be
                an address, or carries no letter.
        """
        del region
        address = collapse_whitespace(candidate.raw_value)
        if len(address) < MINIMUM_ADDRESS_LENGTH:
            raise ValidationRejectedError(f"{address!r} is too short to be a postal address")
        if len(address) > MAXIMUM_ADDRESS_LENGTH:
            raise ValidationRejectedError(
                f"address of {len(address)} characters exceeds {MAXIMUM_ADDRESS_LENGTH}"
            )
        if not any(character.isalpha() for character in address):
            raise ValidationRejectedError(f"{address!r} contains no letter")
        return ValidatedValue(value=address, dedup_value=dedup_address(address))


def dedup_address(value: str) -> str:
    """Collapse everything but letters and digits, so punctuation cannot split a match."""
    return _NON_ALPHANUMERIC_RUN.sub(" ", value.lower()).strip()
