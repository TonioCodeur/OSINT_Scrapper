"""PGP-key-URL validation (SPEC 8.4).

The URL is the useful OSINT fact. The key itself is never fetched and never
parsed: reading OpenPGP packets would mean a new dependency for a fingerprint
nobody asked for.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from osint_scrapper.application.ports import ValidatedValue
from osint_scrapper.domain.attributes import FieldName, RawField
from osint_scrapper.domain.errors import ValidationRejectedError
from osint_scrapper.domain.text import collapse_whitespace
from osint_scrapper.infrastructure.validators.organization import dedup_url

ALLOWED_SCHEMES = frozenset({"http", "https"})


class PgpKeyUrlValidator:
    """Accepts an absolute http(s) URL pointing at a published key."""

    @property
    def field(self) -> FieldName:
        """The field this validator is responsible for."""
        return FieldName.PGP_KEY_URL

    def validate(self, candidate: RawField, region: str) -> ValidatedValue:
        """Return the URL with a lower-cased host.

        Raises:
            ValidationRejectedError: the candidate is not an absolute web URL.
        """
        del region
        raw = collapse_whitespace(candidate.raw_value)
        parts = urlsplit(raw)
        if parts.scheme.lower() not in ALLOWED_SCHEMES or not parts.netloc:
            raise ValidationRejectedError(f"{raw!r} is not an absolute http(s) URL")
        normalized = parts._replace(
            scheme=parts.scheme.lower(), netloc=parts.netloc.lower()
        ).geturl()
        return ValidatedValue(value=normalized, dedup_value=dedup_url(normalized))
