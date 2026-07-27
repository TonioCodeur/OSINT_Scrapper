"""The per-run report: what the site published, and what the crawl did."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from osint_scrapper.domain.attributes import Finding
from osint_scrapper.domain.crawl import (
    FAILED_STATUSES,
    FETCHED_STATUSES,
    SKIPPED_STATUSES,
    CrawlOutcome,
    PageOutcome,
    PageStatus,
)
from osint_scrapper.domain.target import CrawlSettings, CrawlTarget, Purpose


@dataclass(frozen=True)
class SiteReport:
    """The canonical, exportable record of one crawl.

    Produced for every terminal outcome, including the four aborts and an
    operator stop: a run that ended early still exports everything it collected
    before it ended (SPEC FR-7, FR-8).
    """

    run_id: str
    target: CrawlTarget
    settings: CrawlSettings
    purpose: Purpose
    started_at: datetime
    finished_at: datetime
    outcome: CrawlOutcome
    outcome_detail: str | None
    tool_name: str
    tool_version: str
    user_agent: str
    findings: tuple[Finding, ...]
    pages: tuple[PageOutcome, ...]
    pages_fetched: int
    requests_made: int

    @property
    def pages_skipped(self) -> int:
        """URLs the crawl decided not to use, most of them never requested."""
        return sum(1 for page in self.pages if page.status in SKIPPED_STATUSES)

    @property
    def pages_failed(self) -> int:
        """Pages that were attempted and did not yield usable content."""
        return sum(1 for page in self.pages if page.status in FAILED_STATUSES)

    @property
    def pages_parsed(self) -> int:
        """Pages retrieved and parsed, whether or not they yielded a finding."""
        return sum(1 for page in self.pages if page.status in FETCHED_STATUSES)

    @property
    def pages_skipped_by_robots(self) -> int:
        """How many URLs ``robots.txt`` kept us away from, reported for audit."""
        return sum(1 for page in self.pages if page.status is PageStatus.SKIPPED_ROBOTS)

    @property
    def findings_count(self) -> int:
        """How many deduplicated values the site published."""
        return len(self.findings)
