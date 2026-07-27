"""Person-name validation (SPEC 8.4). Casing and diacritics are preserved as published."""

from __future__ import annotations

from osint_scrapper.application.ports import ValidatedValue
from osint_scrapper.domain.attributes import FieldName, RawField
from osint_scrapper.domain.errors import ValidationRejectedError
from osint_scrapper.domain.text import collapse_whitespace, fold

MAXIMUM_NAME_LENGTH = 80
"""Longer than any real name: a match this long is a sentence, not a person."""


class PersonNameValidator:
    """Validates a name the site published as a name."""

    @property
    def field(self) -> FieldName:
        """The field this validator is responsible for."""
        return FieldName.PERSON_NAME

    def validate(self, candidate: RawField, region: str) -> ValidatedValue:
        """Return the collapsed name as published.

        Raises:
            ValidationRejectedError: the candidate is too long, contains a digit,
                or contains no letter at all.
        """
        del region
        name = collapse_whitespace(candidate.raw_value)
        if not name:
            raise ValidationRejectedError("empty name")
        if len(name) > MAXIMUM_NAME_LENGTH:
            raise ValidationRejectedError(
                f"name of {len(name)} characters exceeds {MAXIMUM_NAME_LENGTH}"
            )
        if any(character.isdigit() for character in name):
            raise ValidationRejectedError(f"{name!r} contains a digit")
        if not any(character.isalpha() for character in name):
            raise ValidationRejectedError(f"{name!r} contains no letter")
        return ValidatedValue(value=name, dedup_value=fold(name))
