"""Headless Qt, and the builders the interface tests share.

``QT_QPA_PLATFORM=offscreen`` is set here rather than only in the documented
command line, so that a test run started from an IDE is headless too. It must
happen before any PySide6 module is imported, which is why it is at module level
in a conftest.

No fixture in this file contains a real person's data (SPEC NFR-7).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import UTC, datetime  # noqa: E402

import pytest  # noqa: E402

from osint_scrapper.domain.attributes import (  # noqa: E402
    ExtractionLayer,
    FieldName,
    Finding,
    Provenance,
)
from osint_scrapper.domain.crawl import CrawlOutcome, PageOutcome, PageStatus  # noqa: E402
from osint_scrapper.domain.report import SiteReport  # noqa: E402
from osint_scrapper.domain.target import (  # noqa: E402
    CrawlSettings,
    CrawlTarget,
    Purpose,
    PurposeCategory,
)

MOMENT = datetime(2026, 7, 27, 14, 2, 11, tzinfo=UTC)


def make_provenance(
    url: str = "https://example.com/",
    layer: ExtractionLayer = ExtractionLayer.STRUCTURED_DATA,
    raw_value: str = "contact@example.com",
    collected_at: datetime | None = None,
) -> Provenance:
    """One provenance entry on an example domain."""
    return Provenance(
        source_url=url,
        collected_at=collected_at or MOMENT,
        extraction_layer=layer,
        raw_value=raw_value,
    )


def make_finding(
    field: FieldName = FieldName.EMAIL,
    value: str = "contact@example.com",
    confidence: float = 0.90,
    page_support: int = 1,
    occurrence_count: int = 1,
    layer: ExtractionLayer = ExtractionLayer.STRUCTURED_DATA,
    metadata: dict[str, str] | None = None,
) -> Finding:
    """One finding, invented, on ``example.com``."""
    return Finding(
        field=field,
        value=value,
        extraction_confidence=confidence,
        page_support=page_support,
        occurrence_count=occurrence_count,
        first_seen_url="https://example.com/",
        metadata=metadata or {},
        provenance=(make_provenance(layer=layer, raw_value=value),),
    )


def make_page(
    url: str = "https://example.com/",
    depth: int = 0,
    status: PageStatus = PageStatus.OK,
    detail: str | None = None,
    findings_count: int = 1,
) -> PageOutcome:
    """One page log row."""
    return PageOutcome(
        url=url,
        depth=depth,
        status=status,
        detail=detail,
        http_status=200 if status in {PageStatus.OK, PageStatus.NO_FINDINGS} else None,
        content_type="text/html" if status is PageStatus.OK else None,
        findings_count=findings_count,
    )


def make_target(entered: str = "example.com") -> CrawlTarget:
    """A resolved target on the example domain."""
    return CrawlTarget(
        entered_value=entered,
        target_url="https://example.com/",
        scope_host="example.com",
        include_subdomains=True,
    )


def make_report(
    outcome: CrawlOutcome = CrawlOutcome.COMPLETED,
    findings: tuple[Finding, ...] = (),
    pages: tuple[PageOutcome, ...] = (),
) -> SiteReport:
    """A finished run over the example domain."""
    return SiteReport(
        run_id="r-0000test",
        target=make_target(),
        settings=CrawlSettings(),
        purpose=Purpose(category=PurposeCategory.SELF_AUDIT, note=""),
        started_at=MOMENT,
        finished_at=MOMENT,
        outcome=outcome,
        outcome_detail=None,
        tool_name="osint-scrapper",
        tool_version="0.2.0",
        user_agent="OSINT-Scrapper/0.2.0 (+https://example.org; contact: nobody@example.org)",
        findings=findings or (make_finding(),),
        pages=pages or (make_page(),),
        pages_fetched=1,
        requests_made=1,
    )


@pytest.fixture(autouse=True)
def _drain_background_tasks():
    """Let every background task finish before the next test tears Qt down.

    A pool thread still holding a Python callable while the interpreter unwinds
    is a crash at exit, not a test failure — so it has to be prevented rather
    than asserted on.
    """
    yield
    from osint_scrapper.interfaces.worker import drain_background_tasks

    drain_background_tasks(5_000)


@pytest.fixture
def finished_report() -> SiteReport:
    """A completed report, for the panes that render one."""
    return make_report()


@pytest.fixture
def controllers():
    """Hands out crawl controllers and joins every thread at teardown.

    A ``QThread`` whose owner is garbage-collected while it is still running
    aborts the process. The application joins its thread on quit; a test has to
    do the same, and doing it here means no test has to remember.
    """
    from osint_scrapper.interfaces.worker import CrawlController

    made = []

    def make(factory):
        controller = CrawlController(factory)
        made.append(controller)
        return controller

    yield make

    for controller in made:
        controller.shutdown()
