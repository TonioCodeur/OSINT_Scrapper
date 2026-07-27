"""Technology validation (SPEC 8.4). The one non-personal field."""

from __future__ import annotations

from osint_scrapper.application.ports import ValidatedValue
from osint_scrapper.domain.attributes import FieldName, RawField
from osint_scrapper.domain.errors import ValidationRejectedError
from osint_scrapper.domain.text import collapse_whitespace

MAXIMUM_TECHNOLOGY_LENGTH = 100


class TechnologyValidator:
    """Accepts a short, non-empty technology string as the site announced it."""

    @property
    def field(self) -> FieldName:
        """The field this validator is responsible for."""
        return FieldName.TECHNOLOGY

    def validate(self, candidate: RawField, region: str) -> ValidatedValue:
        """Return the collapsed technology name.

        Raises:
            ValidationRejectedError: the candidate is empty or implausibly long.
        """
        del region
        value = collapse_whitespace(candidate.raw_value)
        if not value:
            raise ValidationRejectedError("empty technology")
        if len(value) > MAXIMUM_TECHNOLOGY_LENGTH:
            raise ValidationRejectedError(
                f"technology of {len(value)} characters exceeds {MAXIMUM_TECHNOLOGY_LENGTH}"
            )
        return ValidatedValue(value=value, dedup_value=value.lower())
