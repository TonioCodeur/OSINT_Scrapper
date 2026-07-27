"""Layers 4 and 5: patterns over the visible text, and published de-obfuscation.

These layers read only what the site chose to display to every visitor. Layer 5
reverses the ``name [at] domain [dot] com`` spelling that defeats naive address
harvesters; it is not an access control, and the rewrite is kept only when the
result validates as an address. It never guesses a domain.

Only three fields may be read from free text, and only because each one is
self-validating (SPEC FR-23): an email parses or it does not, a phone number is
valid per libphonenumber or it is not, and a company identifier carries a
checksum. Names and postal addresses are deliberately absent: a crawl of two
hundred pages of prose produces hundreds of capitalized word pairs and dozens of
number-and-street patterns, and a text extractor for those would not find facts,
it would manufacture them at volume.
"""

from __future__ import annotations

import logging
import re

import phonenumbers

from osint_scrapper.domain.attributes import ExtractionLayer, FieldName, RawField
from osint_scrapper.infrastructure.extraction.pipeline import PageContent

logger = logging.getLogger(__name__)

_LOCAL_PART = r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+"
_DOMAIN_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"

EMAIL_PATTERN = re.compile(rf"{_LOCAL_PART}@{_DOMAIN_LABEL}(?:\.{_DOMAIN_LABEL})+")
"""A permissive candidate pattern. ``email-validator`` makes the real decision."""

# The bracketed and parenthesised spellings are matched case-insensitively; the
# bare-word spellings are not. "Meet Paul at Example.com" is an English sentence,
# whereas "paul AT example DOT com" is a deliberately obfuscated address, and
# only the second should become a candidate.
_AT_SEPARATOR = r"(?:(?i:\[\s*at\s*\])|(?i:\(\s*at\s*\))|\s+AT\s+|＠|﹫)"
_SPELLED_DOT = r"(?:(?i:\[\s*dot\s*\])|(?i:\(\s*dot\s*\))|\s+DOT\s+)"

AT_PATTERN = re.compile(rf"\s*{_AT_SEPARATOR}\s*")
DOT_PATTERN = re.compile(rf"\s*{_SPELLED_DOT}\s*")

# A literal dot is only a label separator when nothing separates it from the
# labels: "com. This" ends a sentence, and treating its period as a separator
# would swallow the next word into the address.
_DOT_SEPARATOR = rf"(?:\s*{_SPELLED_DOT}\s*|\.)"

_OBFUSCATED_CANDIDATE = re.compile(
    rf"{_LOCAL_PART}\s*{_AT_SEPARATOR}\s*{_DOMAIN_LABEL}"
    rf"(?:{_DOT_SEPARATOR}{_DOMAIN_LABEL})+"
)

_SEPARATOR = r"[ \u00a0.\u2011-]?"

SIRET_PATTERN = re.compile(
    rf"\b\d{{3}}{_SEPARATOR}\d{{3}}{_SEPARATOR}\d{{3}}{_SEPARATOR}\d{{5}}\b"
)
SIREN_PATTERN = re.compile(rf"\b\d{{3}}{_SEPARATOR}\d{{3}}{_SEPARATOR}\d{{3}}\b")
RCS_PATTERN = re.compile(
    rf"RCS\s+[^\d\n]{{0,40}}?(\d{{3}}{_SEPARATOR}\d{{3}}{_SEPARATOR}\d{{3}})",
    re.IGNORECASE,
)
VAT_PATTERN = re.compile(
    r"\b(?:AT|BE|BG|CY|CZ|DE|DK|EE|EL|ES|FI|FR|HR|HU|IE|IT|LT|LU|LV|MT|NL|PL|PT|RO|SE|SI|SK|XI)"
    r"[ \u00a0]?[A-Z0-9]{2,13}\b"
)
"""Candidate patterns only. Every one of them is discarded unless its checksum
or its country format validates, which is the whole reason SPEC FR-23 lets this
field come from text at all."""


class TextHeuristicExtractor:
    """Layer 4: self-validating values found in the page's visible text."""

    @property
    def layer(self) -> ExtractionLayer:
        """The weakest layer that still reads a literal, published value."""
        return ExtractionLayer.TEXT_HEURISTIC

    def extract(self, content: PageContent) -> tuple[RawField, ...]:
        """Return email, phone and company-identifier candidates."""
        candidates: list[RawField] = [
            content.raw_field(FieldName.EMAIL, match.group(0), self.layer)
            for match in EMAIL_PATTERN.finditer(content.text)
        ]
        candidates.extend(
            content.raw_field(FieldName.PHONE, match.raw_string, self.layer)
            for match in phonenumbers.PhoneNumberMatcher(content.text, content.region)
        )
        candidates.extend(self._company_identifiers(content))
        return tuple(candidates)

    def _company_identifiers(self, content: PageContent) -> list[RawField]:
        found: list[RawField] = []
        for match in RCS_PATTERN.finditer(content.text):
            found.append(
                content.raw_field(
                    FieldName.COMPANY_IDENTIFIER, match.group(1), self.layer, {"scheme": "rcs"}
                )
            )
        for pattern in (SIRET_PATTERN, SIREN_PATTERN, VAT_PATTERN):
            found.extend(
                content.raw_field(FieldName.COMPANY_IDENTIFIER, match.group(0), self.layer)
                for match in pattern.finditer(content.text)
            )
        return found


class DeobfuscatedTextExtractor:
    """Layer 5: contacts the site published in a harvester-resistant spelling."""

    @property
    def layer(self) -> ExtractionLayer:
        """The lowest-confidence layer, reserved for rewritten spellings."""
        return ExtractionLayer.TEXT_HEURISTIC_DEOBFUSCATED

    def extract(self, content: PageContent) -> tuple[RawField, ...]:
        """Return de-obfuscated email candidates.

        Only the documented separators are rewritten, and only when the result
        looks like an address. The email validator downstream has the final say.
        """
        candidates: list[RawField] = []
        for match in _OBFUSCATED_CANDIDATE.finditer(content.text):
            rewritten = deobfuscate(match.group(0))
            if rewritten is None:
                continue
            candidates.append(
                content.raw_field(
                    FieldName.EMAIL,
                    rewritten,
                    self.layer,
                    metadata={"obfuscated_as": match.group(0).strip()},
                )
            )
        return tuple(candidates)


def deobfuscate(candidate: str) -> str | None:
    """Rewrite the published separators, or return ``None`` if nothing is gained.

    A candidate that already contains a literal ``@`` is left to layer 4, so the
    same address is never reported twice at two different confidences.
    """
    if "@" in candidate:
        return None
    rewritten = DOT_PATTERN.sub(".", AT_PATTERN.sub("@", candidate)).strip(" .")
    if rewritten.count("@") != 1:
        return None
    if not EMAIL_PATTERN.fullmatch(rewritten):
        return None
    return rewritten
