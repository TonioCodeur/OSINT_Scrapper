"""The two pure modules of the application layer: the frontier and the aggregator."""

from __future__ import annotations

from datetime import timedelta

import pytest

from osint_scrapper.application.aggregate import FindingAggregator
from osint_scrapper.application.frontier import Frontier, VisitedSet
from osint_scrapper.application.validation import ALLOWED_LAYERS, layer_is_allowed
from osint_scrapper.domain.attributes import (
    MAXIMUM_PROVENANCE_ENTRIES,
    ExtractionLayer,
    FieldName,
    RawField,
)
from tests.conftest import START_TIME
from tests.wiring import build_validation_policy

EMAIL = "contact@example.com"


def candidate(
    layer: ExtractionLayer = ExtractionLayer.SEMANTIC_HTML,
    url: str = "https://example.com/",
    value: str = EMAIL,
    field: FieldName = FieldName.EMAIL,
    offset_seconds: int = 0,
) -> RawField:
    return RawField(
        field=field,
        raw_value=value,
        source_url=url,
        collected_at=START_TIME + timedelta(seconds=offset_seconds),
        extraction_layer=layer,
    )


def aggregator() -> FindingAggregator:
    return FindingAggregator(build_validation_policy())


def test_the_frontier_is_breadth_first_until_a_high_value_path_arrives() -> None:
    """AC-CRAWL-4: the SPEC 5.4 boost reorders, it never adds a request."""
    frontier = Frontier()
    for index in range(3):
        frontier.push(f"https://example.com/blog/post-{index}", 1)
    frontier.push("https://example.com/contact", 1)
    order = [frontier.pop().url for _ in range(4)]  # type: ignore[union-attr]
    assert order[0] == "https://example.com/contact"
    assert order[1:] == [f"https://example.com/blog/post-{index}" for index in range(3)]


def test_the_frontier_never_queues_the_same_url_twice() -> None:
    frontier = Frontier()
    assert frontier.push("https://example.com/a", 1)
    assert not frontier.push("https://example.com/a", 2)
    assert len(frontier) == 1


def test_draining_reports_what_was_never_reached() -> None:
    """SPEC FR-7: a budget-truncated run says which URLs it did not get to."""
    frontier = Frontier()
    frontier.push("https://example.com/a", 1)
    frontier.push("https://example.com/b", 2)
    assert [item.url for item in frontier.drain()] == [
        "https://example.com/a",
        "https://example.com/b",
    ]
    assert len(frontier) == 0


def test_only_one_claimer_wins_a_url() -> None:
    """SPEC 6.4: two workers dequeuing at once must not both take the same URL."""
    visited = VisitedSet()
    assert visited.claim("https://example.com/a")
    assert not visited.claim("https://example.com/a")
    assert "https://example.com/a" in visited


def test_three_layers_on_one_page_are_one_finding() -> None:
    """AC-EXTRACT-1: one finding, best layer, support 1, three occurrences."""
    accumulator = aggregator()
    accumulator.add(
        [
            candidate(ExtractionLayer.STRUCTURED_DATA),
            candidate(ExtractionLayer.SEMANTIC_HTML),
            candidate(ExtractionLayer.TEXT_HEURISTIC),
        ],
        "FR",
    )
    findings = accumulator.findings()
    assert len(findings) == 1
    assert findings[0].extraction_confidence == 0.90
    assert findings[0].page_support == 1
    assert findings[0].occurrence_count == 3


def test_a_footer_address_on_forty_pages_is_one_finding_with_ten_provenance() -> None:
    """AC-EXTRACT-2: support and occurrences stay true while provenance is bounded."""
    accumulator = aggregator()
    accumulator.add(
        [candidate(url=f"https://example.com/page-{index:03d}") for index in range(40)], "FR"
    )
    finding = accumulator.findings()[0]
    assert finding.page_support == 40
    assert finding.occurrence_count == 40
    assert len(finding.provenance) == MAXIMUM_PROVENANCE_ENTRIES
    assert finding.extraction_confidence == 0.75


def test_no_blended_score_exists_on_a_finding() -> None:
    """SPEC 8.6: the two numbers are separate and nothing multiplies them."""
    accumulator = aggregator()
    accumulator.add([candidate(url=f"https://example.com/{index}") for index in range(5)], "FR")
    finding = accumulator.findings()[0]
    assert finding.extraction_confidence == 0.75
    assert finding.page_support == 5
    assert not hasattr(finding, "confidence")
    assert not hasattr(finding, "disputed")


def test_provenance_and_first_seen_are_computed_from_sort_keys() -> None:
    """SPEC 9.1.1: ``first_seen_url`` is the lowest URL, never the chronological first."""
    accumulator = aggregator()
    accumulator.add(
        [
            candidate(url="https://example.com/zulu", offset_seconds=0),
            candidate(url="https://example.com/alpha", offset_seconds=60),
        ],
        "FR",
    )
    finding = accumulator.findings()[0]
    assert finding.first_seen_url == "https://example.com/alpha"
    assert [entry.source_url for entry in finding.provenance] == [
        "https://example.com/alpha",
        "https://example.com/zulu",
    ]


def test_the_exported_spelling_is_chosen_deterministically() -> None:
    """The best layer wins; ties break on the lowest URL, never on arrival order."""
    first = aggregator()
    first.add(
        [
            candidate(
                ExtractionLayer.SEMANTIC_HTML, "https://example.com/z", "Contact@Example.com"
            ),
            candidate(ExtractionLayer.STRUCTURED_DATA, "https://example.com/a"),
        ],
        "FR",
    )
    second = aggregator()
    second.add(
        [
            candidate(ExtractionLayer.STRUCTURED_DATA, "https://example.com/a"),
            candidate(
                ExtractionLayer.SEMANTIC_HTML, "https://example.com/z", "Contact@Example.com"
            ),
        ],
        "FR",
    )
    assert first.findings()[0].value == second.findings()[0].value == EMAIL


def test_findings_are_ordered_by_field_declaration_then_confidence_then_value() -> None:
    """SPEC 9.1.1."""
    accumulator = aggregator()
    accumulator.add(
        [
            candidate(field=FieldName.TECHNOLOGY, value="nginx"),
            candidate(field=FieldName.EMAIL, value="zulu@example.com"),
            candidate(field=FieldName.EMAIL, value="alpha@example.com"),
            candidate(
                field=FieldName.EMAIL,
                value="best@example.com",
                layer=ExtractionLayer.STRUCTURED_DATA,
            ),
        ],
        "FR",
    )
    assert [(str(item.field), item.value) for item in accumulator.findings()] == [
        ("email", "best@example.com"),
        ("email", "alpha@example.com"),
        ("email", "zulu@example.com"),
        ("technology", "nginx"),
    ]


def test_a_candidate_that_fails_validation_is_discarded_silently() -> None:
    """SPEC FR-22: never exported as fact, and never an exception either."""
    accumulator = aggregator()
    assert accumulator.add([candidate(value="not an address")], "FR") == 0
    assert accumulator.findings() == ()


TEXT_ONLY_FORBIDDEN = [
    FieldName.POSTAL_ADDRESS,
    FieldName.PERSON_NAME,
    FieldName.ORGANIZATION_NAME,
    FieldName.SOCIAL_PROFILE,
    FieldName.PGP_KEY_URL,
    FieldName.TECHNOLOGY,
]


@pytest.mark.parametrize("field", TEXT_ONLY_FORBIDDEN, ids=str)
@pytest.mark.parametrize(
    "layer",
    [ExtractionLayer.TEXT_HEURISTIC, ExtractionLayer.TEXT_HEURISTIC_DEOBFUSCATED],
    ids=str,
)
def test_the_self_validation_rule_is_mechanical(
    field: FieldName, layer: ExtractionLayer
) -> None:
    """AC-EXTRACT-5: six fields can never come from free text (SPEC FR-23)."""
    assert not layer_is_allowed(field, layer)
    accumulator = aggregator()
    assert accumulator.add([candidate(field=field, layer=layer, value="Example")], "FR") == 0


def test_every_field_states_its_layers_explicitly() -> None:
    """A new field must not be able to default open."""
    assert set(ALLOWED_LAYERS) == set(FieldName)
