"""Validate, deduplicate and count candidates into findings (SPEC 8.4 to 8.6).

This module is pure: it performs no I/O and needs no fakes to test. It is also
where the honest-numbers decision lands — two numbers, each meaning exactly one
thing, and no blended score anywhere.

Conflicts do not exist in this product. Every field is multi-valued: a site
legitimately publishes many emails, many people and many phone numbers. Nothing
is dropped and nothing is "resolved".
"""

from __future__ import annotations

import dataclasses
import logging
import threading
from collections.abc import Iterable
from dataclasses import dataclass

from osint_scrapper.application.validation import ValidationPolicy
from osint_scrapper.domain.attributes import (
    LAYER_ORDER,
    MAXIMUM_PROVENANCE_ENTRIES,
    FieldName,
    Finding,
    Provenance,
    RawField,
)
from osint_scrapper.domain.confidence import LAYER_BASE_CONFIDENCE
from osint_scrapper.domain.errors import ValidationRejectedError

logger = logging.getLogger(__name__)


@dataclass
class _Group:
    """Mutable working state for one ``(field, dedup_value)`` group."""

    field: FieldName
    dedup_value: str
    value: str
    preference: tuple[int, str, str]
    """Which spelling of the value is exported: best layer, lowest source URL, lowest value.

    SPEC 8.5 words this as "the first-seen highest-layer variant wins". "First
    seen" is not available under the concurrency of SPEC 6.4, where completion
    order is not deterministic, so the arrival tie-break is replaced by the
    lowest source URL. That keeps the intent — the best layer decides — while
    satisfying the harder promise of NFR-9 and AC-CRAWL-9: two runs at different
    concurrency produce byte-identical exports.
    """

    metadata: dict[str, str] = dataclasses.field(default_factory=dict)
    provenance: list[Provenance] = dataclasses.field(default_factory=list)
    source_urls: set[str] = dataclasses.field(default_factory=set)
    occurrence_count: int = 0


class FindingAggregator:
    """Accumulates candidates across pages and renders the current findings.

    Stateful on purpose: the interface shows findings live as the crawl runs, so
    the same accumulator answers "what do we have so far" and "what is the final
    report". It is guarded because the crawl of SPEC 6.4 is concurrent.
    """

    def __init__(self, policy: ValidationPolicy) -> None:
        self._policy = policy
        self._lock = threading.Lock()
        self._groups: dict[tuple[FieldName, str], _Group] = {}

    def add(self, candidates: Iterable[RawField], region: str) -> int:
        """Validate and absorb ``candidates``, returning how many were accepted.

        Candidates that fail validation are discarded and logged at debug level;
        they are never exported as fact (SPEC FR-22).
        """
        accepted = 0
        for candidate in candidates:
            absorbed = self._accept(candidate, region)
            if absorbed:
                accepted += 1
        return accepted

    def findings(self) -> tuple[Finding, ...]:
        """Return the deduplicated findings in the export order of SPEC 9.1.1."""
        with self._lock:
            groups = [_render(group) for group in self._groups.values()]
        return tuple(sorted(groups, key=Finding.sort_key))

    def _accept(self, candidate: RawField, region: str) -> bool:
        try:
            validated = self._policy.validate(candidate, region)
        except ValidationRejectedError as rejection:
            logger.debug("discarded %s candidate: %s", candidate.field, rejection)
            return False

        provenance = Provenance(
            source_url=candidate.source_url,
            collected_at=candidate.collected_at,
            extraction_layer=candidate.extraction_layer,
            raw_value=candidate.raw_value,
        )
        metadata = dict(candidate.metadata)
        metadata.update(validated.metadata)

        preference = (
            LAYER_ORDER[candidate.extraction_layer],
            candidate.source_url,
            validated.value,
        )
        key = (candidate.field, validated.dedup_value)
        with self._lock:
            group = self._groups.get(key)
            if group is None:
                group = _Group(
                    field=candidate.field,
                    dedup_value=validated.dedup_value,
                    value=validated.value,
                    preference=preference,
                )
                self._groups[key] = group
            group.provenance.append(provenance)
            group.source_urls.add(provenance.source_url)
            group.occurrence_count += 1
            for name, value in metadata.items():
                group.metadata.setdefault(name, value)
            if preference < group.preference:
                group.preference = preference
                group.value = validated.value
        return True


def _render(group: _Group) -> Finding:
    """Turn accumulated observations into one finding with two honest numbers."""
    ordered = sorted(group.provenance, key=Provenance.sort_key)
    confidence = max(LAYER_BASE_CONFIDENCE[entry.extraction_layer] for entry in ordered)
    return Finding(
        field=group.field,
        value=group.value,
        extraction_confidence=confidence,
        page_support=len(group.source_urls),
        occurrence_count=group.occurrence_count,
        first_seen_url=ordered[0].source_url,
        provenance=tuple(ordered[:MAXIMUM_PROVENANCE_ENTRIES]),
        metadata=dict(group.metadata),
    )
