"""``/.well-known/security.txt`` reading (RFC 9116, SPEC 5.6).

Verified 2026-07-27 against RFC 9116: the well-known path is exactly
``/.well-known/security.txt``; the media type is ``text/plain`` with
``charset=utf-8``; the required fields are ``Contact`` and ``Expires``; the
optional fields are ``Acknowledgments``, ``Canonical``, ``Encryption``,
``Hiring``, ``Policy`` and ``Preferred-Languages``; and the RFC itself says a
parser may decline a file larger than 32 KB, with fields longer than 2048
characters, or with more than 1000 lines. This product applies exactly those
three limits.

``Contact:`` values are contacts, not crawl targets: the crawl never adds them
to the frontier.
"""

from __future__ import annotations

from osint_scrapper.application.errors import ResponseTooLargeError, SelectorNotFoundError
from osint_scrapper.application.ports import FetchedPage
from osint_scrapper.domain.attributes import EMPTY_METADATA, ExtractionLayer, FieldName, RawField
from osint_scrapper.infrastructure.extraction.social import platform_of

MAXIMUM_DOCUMENT_BYTES = 32 * 1024
MAXIMUM_FIELD_LENGTH = 2048
MAXIMUM_LINES = 1000

CONTACT_FIELD = "contact"
ENCRYPTION_FIELD = "encryption"
_MAILTO = "mailto:"
_TEL = "tel:"


class RfcSecurityTxtReader:
    """Turns the file's ``Contact`` and ``Encryption`` fields into candidates."""

    def findings(self, document: FetchedPage) -> tuple[RawField, ...]:
        """Return the contact and encryption values the file publishes.

        Raises:
            ResponseTooLargeError: the file exceeds one of the RFC 9116 limits.
            SelectorNotFoundError: the file carries no ``Contact`` field, which
                RFC 9116 requires, so it is not the document we parsed for.
        """
        text = document.text
        if len(text.encode("utf-8")) > MAXIMUM_DOCUMENT_BYTES:
            raise ResponseTooLargeError(document.url, MAXIMUM_DOCUMENT_BYTES)
        lines = text.splitlines()
        if len(lines) > MAXIMUM_LINES:
            raise ResponseTooLargeError(document.url, MAXIMUM_DOCUMENT_BYTES)

        candidates: list[RawField] = []
        seen_contact = False
        for line in lines:
            name, _, raw = line.partition(":")
            key = name.strip().lower()
            value = raw.strip()
            if not value or key not in {CONTACT_FIELD, ENCRYPTION_FIELD}:
                continue
            if len(line) > MAXIMUM_FIELD_LENGTH:
                raise ResponseTooLargeError(document.url, MAXIMUM_FIELD_LENGTH)
            if key == CONTACT_FIELD:
                seen_contact = True
                candidates.extend(_contact(document, value))
            else:
                candidates.append(_candidate(document, FieldName.PGP_KEY_URL, value))

        if not seen_contact:
            raise SelectorNotFoundError("a Contact: field (RFC 9116)", document.url)
        return tuple(candidates)


def _contact(document: FetchedPage, value: str) -> list[RawField]:
    """Map one ``Contact:`` value onto a field, or ignore it.

    An ``https:`` contact becomes a social profile only when it is on the known
    platform list; a contact form on the site's own domain is a page, not a
    finding, and inventing a field for it would be gold-plating.
    """
    lowered = value.lower()
    if lowered.startswith(_MAILTO):
        return [_candidate(document, FieldName.EMAIL, value[len(_MAILTO) :])]
    if lowered.startswith(_TEL):
        return [_candidate(document, FieldName.PHONE, value[len(_TEL) :])]
    platform = platform_of(value)
    if platform is not None:
        return [
            _candidate(document, FieldName.SOCIAL_PROFILE, value, {"platform": platform})
        ]
    return []


def _candidate(
    document: FetchedPage,
    field: FieldName,
    value: str,
    metadata: dict[str, str] | None = None,
) -> RawField:
    return RawField(
        field=field,
        raw_value=value.strip(),
        source_url=document.url,
        collected_at=document.fetched_at,
        extraction_layer=ExtractionLayer.WELL_KNOWN,
        metadata=metadata or EMPTY_METADATA,
    )
