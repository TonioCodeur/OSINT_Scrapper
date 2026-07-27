"""The gate every candidate must pass before it can become a fact (SPEC 8.3, 8.4).

Two independent rules apply. A validator decides whether a value is well-formed
for its field; the layer policy decides whether the field may be believed at all
from the layer that produced it.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from types import MappingProxyType

from osint_scrapper.application.ports import FieldValidator, ValidatedValue
from osint_scrapper.domain.attributes import ExtractionLayer, FieldName, RawField
from osint_scrapper.domain.errors import ValidationRejectedError

logger = logging.getLogger(__name__)

STRUCTURED_LAYERS = frozenset(
    {
        ExtractionLayer.WELL_KNOWN,
        ExtractionLayer.STRUCTURED_DATA,
        ExtractionLayer.SEMANTIC_HTML,
    }
)
"""Layers 1 to 3: the site labelled the value, rather than us guessing at prose."""

EVERY_LAYER = frozenset(ExtractionLayer)

ALLOWED_LAYERS: Mapping[FieldName, frozenset[ExtractionLayer]] = MappingProxyType(
    {
        # SPEC FR-23, mechanically. A value may come from free page text only if
        # an independent check can confirm it is well formed: an RFC-correct
        # email parse, libphonenumber validity, or a company-identifier checksum.
        # The other six fields have no such check, and a text-layer extractor for
        # them would not find facts — it would manufacture them, at volume, and
        # export them with a confidence number attached.
        FieldName.EMAIL: EVERY_LAYER,
        FieldName.PHONE: EVERY_LAYER,
        FieldName.COMPANY_IDENTIFIER: frozenset(
            {
                ExtractionLayer.STRUCTURED_DATA,
                ExtractionLayer.SEMANTIC_HTML,
                ExtractionLayer.TEXT_HEURISTIC,
            }
        ),
        FieldName.POSTAL_ADDRESS: STRUCTURED_LAYERS,
        FieldName.PERSON_NAME: STRUCTURED_LAYERS,
        FieldName.ORGANIZATION_NAME: STRUCTURED_LAYERS,
        FieldName.SOCIAL_PROFILE: STRUCTURED_LAYERS,
        FieldName.PGP_KEY_URL: frozenset(
            {ExtractionLayer.WELL_KNOWN, ExtractionLayer.SEMANTIC_HTML}
        ),
        FieldName.TECHNOLOGY: frozenset({ExtractionLayer.SEMANTIC_HTML}),
    }
)
"""Every field states its layers explicitly, so a new field cannot default open."""


def layer_is_allowed(field: FieldName, layer: ExtractionLayer) -> bool:
    """Whether ``field`` may be believed when it comes from ``layer``."""
    return layer in ALLOWED_LAYERS[field]


class ValidationPolicy:
    """Applies the validator registered for a field, plus the layer restriction."""

    def __init__(self, validators: Mapping[FieldName, FieldValidator]) -> None:
        self._validators = dict(validators)

    def accepts_field(self, field: FieldName) -> bool:
        """Whether any validator is registered for ``field``."""
        return field in self._validators

    def validate(self, candidate: RawField, region: str) -> ValidatedValue:
        """Return the canonical value for ``candidate``.

        Raises:
            ValidationRejectedError: the layer is not trusted for this field, no
                validator is registered, or the value itself is malformed.
        """
        if not layer_is_allowed(candidate.field, candidate.extraction_layer):
            raise ValidationRejectedError(
                f"{candidate.field} is not accepted from layer {candidate.extraction_layer}"
            )
        validator = self._validators.get(candidate.field)
        if validator is None:
            raise ValidationRejectedError(f"no validator registered for {candidate.field}")
        return validator.validate(candidate, region)
