"""The extraction-confidence table (SPEC 8.6).

``extraction_confidence`` is a discrete label answering one question: how was
this value obtained. It is not a probability, no arithmetic is performed on it,
and it is deliberately not blended with ``page_support`` — the same site
repeating itself is one publisher speaking once, loudly, and a formula that
rewarded repetition would manufacture a number that looks like corroboration.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType

from osint_scrapper.domain.attributes import ExtractionLayer

LAYER_BASE_CONFIDENCE: Mapping[ExtractionLayer, float] = MappingProxyType(
    {
        ExtractionLayer.WELL_KNOWN: 0.95,
        ExtractionLayer.STRUCTURED_DATA: 0.90,
        ExtractionLayer.SEMANTIC_HTML: 0.75,
        ExtractionLayer.TEXT_HEURISTIC: 0.50,
        ExtractionLayer.TEXT_HEURISTIC_DEOBFUSCATED: 0.40,
    }
)
"""Measures the reliability of the extraction mechanism, not of the product."""


def extraction_confidence(layers: Iterable[ExtractionLayer]) -> float:
    """Return the best layer's base score.

    Raises:
        ValueError: no layer was observed, which means no provenance existed.
    """
    scores = [LAYER_BASE_CONFIDENCE[layer] for layer in layers]
    if not scores:
        raise ValueError("cannot score a finding with no extraction layer")
    return max(scores)
