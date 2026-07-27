"""Company-identifier validation: SIREN, SIRET, EU VAT and RCS (SPEC 8.4).

This is the one field SPEC FR-23 lets through from free page text, and the only
reason it does is this module: every candidate must pass a checksum or a
documented per-country format. **A candidate that fails is discarded**, never
exported with a lower score — a wrong legal identifier attached to a website is
worse than no identifier at all.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from types import MappingProxyType

from osint_scrapper.application.ports import ValidatedValue
from osint_scrapper.domain.attributes import FieldName, RawField
from osint_scrapper.domain.errors import ValidationRejectedError

SCHEME_KEY = "scheme"
SIREN_SCHEME = "siren"
SIRET_SCHEME = "siret"
VAT_SCHEME = "vat_eu"
RCS_SCHEME = "rcs"

SIREN_LENGTH = 9
SIRET_LENGTH = 14

_NOISE = re.compile(r"[\s. ‑-]+")
_DIGITS = re.compile(r"^\d+$")
_VAT = re.compile(r"^([A-Z]{2})([A-Z0-9]{2,13})$")

VAT_FORMATS: Mapping[str, re.Pattern[str]] = MappingProxyType(
    {
        # Verified against the European Commission's published VAT number formats.
        "AT": re.compile(r"^U\d{8}$"),
        "BE": re.compile(r"^[01]\d{9}$"),
        "BG": re.compile(r"^\d{9,10}$"),
        "CY": re.compile(r"^\d{8}[A-Z]$"),
        "CZ": re.compile(r"^\d{8,10}$"),
        "DE": re.compile(r"^\d{9}$"),
        "DK": re.compile(r"^\d{8}$"),
        "EE": re.compile(r"^\d{9}$"),
        "EL": re.compile(r"^\d{9}$"),
        "ES": re.compile(r"^[A-Z0-9]\d{7}[A-Z0-9]$"),
        "FI": re.compile(r"^\d{8}$"),
        "FR": re.compile(r"^[A-Z0-9]{2}\d{9}$"),
        "HR": re.compile(r"^\d{11}$"),
        "HU": re.compile(r"^\d{8}$"),
        "IE": re.compile(r"^(\d{7}[A-Z]{1,2}|\d[A-Z0-9+*]\d{5}[A-Z])$"),
        "IT": re.compile(r"^\d{11}$"),
        "LT": re.compile(r"^(\d{9}|\d{12})$"),
        "LU": re.compile(r"^\d{8}$"),
        "LV": re.compile(r"^\d{11}$"),
        "MT": re.compile(r"^\d{8}$"),
        "NL": re.compile(r"^\d{9}B\d{2}$"),
        "PL": re.compile(r"^\d{10}$"),
        "PT": re.compile(r"^\d{9}$"),
        "RO": re.compile(r"^\d{2,10}$"),
        "SE": re.compile(r"^\d{12}$"),
        "SI": re.compile(r"^\d{8}$"),
        "SK": re.compile(r"^\d{10}$"),
        "XI": re.compile(r"^(\d{9}|\d{12}|(GD|HA)\d{3})$"),
    }
)

_FRENCH_VAT_MODULUS = 97
_FRENCH_VAT_OFFSET = 12


class CompanyIdentifierValidator:
    """Accepts an identifier only when its checksum or its country format holds."""

    @property
    def field(self) -> FieldName:
        """The field this validator is responsible for."""
        return FieldName.COMPANY_IDENTIFIER

    def validate(self, candidate: RawField, region: str) -> ValidatedValue:
        """Return the compact identifier and the scheme it belongs to.

        Raises:
            ValidationRejectedError: the candidate belongs to no known scheme, or
                fails the checksum or format that scheme requires.
        """
        del region
        compact = _NOISE.sub("", candidate.raw_value).upper()
        if not compact:
            raise ValidationRejectedError("empty company identifier")

        vat = _VAT.match(compact)
        if vat is not None and vat.group(1) in VAT_FORMATS:
            return _accept_vat(compact, vat.group(1), vat.group(2))
        if _DIGITS.match(compact):
            return _accept_french(compact, candidate.metadata.get(SCHEME_KEY))
        raise ValidationRejectedError(
            f"{compact!r} is not a SIREN, a SIRET, an EU VAT number or an RCS entry"
        )


def _accept_vat(compact: str, country: str, body: str) -> ValidatedValue:
    if not VAT_FORMATS[country].match(body):
        raise ValidationRejectedError(
            f"{compact!r} does not match the documented VAT format for {country}"
        )
    if country == "FR" and not _french_vat_key_holds(body):
        raise ValidationRejectedError(f"{compact!r} has an invalid French VAT key")
    return ValidatedValue(
        value=compact,
        dedup_value=f"{VAT_SCHEME}:{compact}",
        metadata={SCHEME_KEY: VAT_SCHEME},
    )


def _accept_french(compact: str, hinted_scheme: str | None) -> ValidatedValue:
    """Accept a SIREN or a SIRET, keeping an ``rcs`` hint when the digits hold."""
    if len(compact) == SIRET_LENGTH:
        scheme = SIRET_SCHEME
    elif len(compact) == SIREN_LENGTH:
        scheme = RCS_SCHEME if hinted_scheme == RCS_SCHEME else SIREN_SCHEME
    else:
        raise ValidationRejectedError(
            f"{compact!r} is {len(compact)} digits, which is neither a SIREN nor a SIRET"
        )
    if not luhn_holds(compact):
        raise ValidationRejectedError(f"{compact!r} fails its Luhn checksum")
    return ValidatedValue(
        value=compact,
        dedup_value=f"{scheme}:{compact}",
        metadata={SCHEME_KEY: scheme},
    )


def luhn_holds(digits: str) -> bool:
    """Whether ``digits`` satisfies the Luhn checksum SIREN and SIRET carry."""
    total = 0
    for index, character in enumerate(reversed(digits)):
        value = int(character)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _french_vat_key_holds(body: str) -> bool:
    """Check the two-character French VAT key when it is numeric.

    The key is ``(12 + 3 * (SIREN mod 97)) mod 97``. Alphabetic keys exist and
    are computed differently, so they are accepted on format alone.
    """
    key, siren = body[:2], body[2:]
    if not key.isdigit():
        return True
    expected = (_FRENCH_VAT_OFFSET + 3 * (int(siren) % _FRENCH_VAT_MODULUS)) % _FRENCH_VAT_MODULUS
    return int(key) == expected
