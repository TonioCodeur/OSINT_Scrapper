"""Social-profile validation (SPEC 8.4).

Only a full profile URL on a known platform is accepted. A platform root with no
profile path is a link to a website, not to anybody, and a bare ``@handle`` is
ambiguous across platforms — neither becomes a finding.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from osint_scrapper.application.ports import ValidatedValue
from osint_scrapper.domain.attributes import FieldName, RawField
from osint_scrapper.domain.errors import ValidationRejectedError
from osint_scrapper.domain.text import collapse_whitespace
from osint_scrapper.infrastructure.extraction.social import normalize_profile, platform_of

PLATFORM_KEY = "platform"
ALLOWED_SCHEMES = frozenset({"http", "https"})


class SocialProfileValidator:
    """Accepts a profile URL on a listed platform and normalizes it."""

    @property
    def field(self) -> FieldName:
        """The field this validator is responsible for."""
        return FieldName.SOCIAL_PROFILE

    def validate(self, candidate: RawField, region: str) -> ValidatedValue:
        """Return the normalized profile URL.

        Raises:
            ValidationRejectedError: the candidate is not an absolute URL on a
                known platform, or names a platform root with no profile path.
        """
        del region
        raw = collapse_whitespace(candidate.raw_value)
        if urlsplit(raw).scheme.lower() not in ALLOWED_SCHEMES:
            raise ValidationRejectedError(f"{raw!r} is not an absolute http(s) profile URL")
        platform = platform_of(raw)
        if platform is None:
            raise ValidationRejectedError(
                f"{raw!r} is not a profile on a known platform, or has no profile path"
            )
        normalized = normalize_profile(raw)
        return ValidatedValue(
            value=normalized,
            dedup_value=normalized.lower(),
            metadata={PLATFORM_KEY: platform},
        )
