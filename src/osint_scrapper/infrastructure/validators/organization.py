"""Organization-name validation (SPEC 8.4)."""

from __future__ import annotations

from urllib.parse import urlsplit

from osint_scrapper.application.ports import ValidatedValue
from osint_scrapper.domain.attributes import FieldName, RawField
from osint_scrapper.domain.errors import ValidationRejectedError
from osint_scrapper.domain.text import collapse_whitespace, fold

MAXIMUM_ORGANIZATION_LENGTH = 200
_WWW_PREFIX = "www."


class OrganizationValidator:
    """Accepts the name of whoever publishes this site."""

    @property
    def field(self) -> FieldName:
        """The field this validator is responsible for."""
        return FieldName.ORGANIZATION_NAME

    def validate(self, candidate: RawField, region: str) -> ValidatedValue:
        """Return the collapsed organization name.

        Raises:
            ValidationRejectedError: the candidate is empty or implausibly long.
        """
        del region
        name = collapse_whitespace(candidate.raw_value)
        if not name:
            raise ValidationRejectedError("empty organization name")
        if len(name) > MAXIMUM_ORGANIZATION_LENGTH:
            raise ValidationRejectedError(
                f"organization of {len(name)} characters exceeds {MAXIMUM_ORGANIZATION_LENGTH}"
            )
        return ValidatedValue(value=name, dedup_value=fold(name))


def dedup_url(value: str) -> str:
    """Strip scheme, ``www.`` and any trailing slash so variants collapse to one key.

    Shared by the PGP-key-URL and social-profile validators, which both key on a
    URL and both need the same variants to meet.
    """
    parts = urlsplit(value)
    host = parts.netloc.lower().removeprefix(_WWW_PREFIX)
    return f"{host}{parts.path.rstrip('/')}".lower()
