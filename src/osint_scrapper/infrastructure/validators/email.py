"""Email validation and role-account classification (SPEC 8.4).

With no subject there is no name to match against, so classification is the
role-account list alone. That is a simplification rather than a loss: the
person/organization split was never reliable, whereas "is this a role mailbox"
is a question the local part actually answers, and it is what an operator wants
to filter on.
"""

from __future__ import annotations

import re

from email_validator import EmailNotValidError, validate_email

from osint_scrapper.application.ports import ValidatedValue
from osint_scrapper.domain.attributes import FieldName, RawField
from osint_scrapper.domain.errors import ValidationRejectedError
from osint_scrapper.domain.text import fold

EMAIL_KIND_KEY = "email_kind"
ROLE_KIND = "role"
OTHER_KIND = "other"

ROLE_LOCAL_PARTS = frozenset(
    {
        "contact",
        "info",
        "information",
        "admin",
        "administrator",
        "webmaster",
        "hello",
        "bonjour",
        "accueil",
        "dpo",
        "rgpd",
        "privacy",
        "legal",
        "sales",
        "commercial",
        "support",
        "help",
        "service",
        "press",
        "presse",
        "media",
        "jobs",
        "recrutement",
        "recruitment",
        "noreply",
        "no-reply",
        "donotreply",
        "postmaster",
        "abuse",
        "security",
        "securite",
        "mail",
    }
)
"""Mailboxes that belong to an organization rather than to a person."""

_PUNCTUATION = re.compile(r"[^a-z0-9]+")


class EmailValidator:
    """Validates an address and records whether it is a role mailbox."""

    @property
    def field(self) -> FieldName:
        """The field this validator is responsible for."""
        return FieldName.EMAIL

    def validate(self, candidate: RawField, region: str) -> ValidatedValue:
        """Return the normalized, lower-cased address.

        Deliverability is never checked: a DNS lookup would make the test suite
        touch the network, and probing MX records is outside this tool's purpose.

        Raises:
            ValidationRejectedError: the candidate is not a syntactically valid address.
        """
        del region
        raw = candidate.raw_value.strip()
        try:
            validated = validate_email(raw, check_deliverability=False)
        except EmailNotValidError as rejection:
            raise ValidationRejectedError(
                f"{raw!r} is not a valid email: {rejection}"
            ) from rejection

        normalized = validated.normalized.lower()
        local_part = normalized.rsplit("@", 1)[0]
        return ValidatedValue(
            value=normalized,
            dedup_value=normalized,
            metadata={EMAIL_KIND_KEY: classify_local_part(local_part)},
        )


def classify_local_part(local_part: str) -> str:
    """Return ``role`` for a known organizational mailbox, ``other`` otherwise."""
    folded = fold(local_part)
    tokens = {token for token in _PUNCTUATION.split(folded) if token}
    if folded in ROLE_LOCAL_PARTS or tokens & ROLE_LOCAL_PARTS:
        return ROLE_KIND
    return OTHER_KIND
