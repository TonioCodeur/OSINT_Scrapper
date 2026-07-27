"""The flat, one-row-per-provenance view shared by the tabular writers.

The column schema *is* the product's contract with whatever reads its output, so
it lives here once and every format derives from it (SPEC 9.2, 9.3, 9.4).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

from osint_scrapper.domain.report import SiteReport
from osint_scrapper.infrastructure.validators.email import EMAIL_KIND_KEY

FINDING_COLUMNS = (
    "run_id",
    "purpose_category",
    "purpose_note",
    "retention_days",
    "target_entered",
    "target_url",
    "scope_host",
    "field",
    "value",
    "email_kind",
    "extraction_confidence",
    "page_support",
    "occurrence_count",
    "first_seen_url",
    "source_url",
    "extraction_layer",
    "raw_value",
    "collected_at",
    "tool_name",
    "tool_version",
)
"""SPEC 9.2. ``email_kind`` is empty for every field but ``email``; the other
per-field metadata lives in JSON and JSONL rather than in a column each, which
would produce a wide sheet that is mostly empty."""

PAGE_COLUMNS = (
    "run_id",
    "url",
    "depth",
    "status",
    "detail",
    "http_status",
    "content_type",
    "findings_count",
)

RUN_KEYS = (
    "run_id",
    "started_at",
    "finished_at",
    "outcome",
    "outcome_detail",
    "purpose_category",
    "purpose_note",
    "retention_days",
    "tool_name",
    "tool_version",
    "user_agent",
    "target_entered",
    "target_url",
    "scope_host",
    "include_subdomains",
    "max_pages",
    "max_depth",
    "request_interval_seconds",
    "concurrent_requests",
    "follow_sitemap",
    "phone_region",
    "pages_fetched",
    "requests_made",
    "pages_skipped",
    "pages_failed",
    "findings_count",
)

COMPLIANCE_KEYS = (
    "user_agent",
    "robots_txt_honored",
    "robots_txt_url",
    "effective_interval_seconds",
    "hard_floor_seconds",
    "concurrent_requests",
    "pages_skipped_by_robots",
    "retention_days",
    "purpose_category",
    "purpose_note",
)
"""SPEC 9.3. This sheet exists so a run's compliance posture is a first-class
artifact an auditor can read without parsing JSON."""


def timestamp(moment: datetime) -> str:
    """Render an aware datetime as RFC 3339 UTC with a ``Z`` suffix."""
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def finding_rows(report: SiteReport) -> Iterator[tuple[object, ...]]:
    """Yield one row per provenance entry, so every row is fully attributed."""
    for finding in report.findings:
        for entry in finding.provenance:
            yield (
                report.run_id,
                str(report.purpose.category),
                report.purpose.note,
                report.settings.retention_days,
                report.target.entered_value,
                report.target.target_url,
                report.target.scope_host,
                str(finding.field),
                finding.value,
                finding.metadata.get(EMAIL_KIND_KEY, ""),
                finding.extraction_confidence,
                finding.page_support,
                finding.occurrence_count,
                finding.first_seen_url,
                entry.source_url,
                str(entry.extraction_layer),
                entry.raw_value,
                timestamp(entry.collected_at),
                report.tool_name,
                report.tool_version,
            )


def page_rows(report: SiteReport) -> Iterator[tuple[object, ...]]:
    """Yield one row per page-log entry."""
    for page in report.pages:
        yield (
            report.run_id,
            page.url,
            page.depth,
            str(page.status),
            page.detail or "",
            page.http_status if page.http_status is not None else "",
            page.content_type or "",
            page.findings_count,
        )


def run_rows(report: SiteReport) -> Iterator[tuple[str, object]]:
    """Yield the run's key/value summary, in the documented key order."""
    values = _run_values(report)
    for key in RUN_KEYS:
        yield key, values[key]


def compliance_rows(report: SiteReport, hard_floor_seconds: float) -> Iterator[tuple[str, object]]:
    """Yield the compliance summary, in the documented key order."""
    values: dict[str, object] = {
        "user_agent": report.user_agent,
        "robots_txt_honored": "true",
        "robots_txt_url": f"{_origin(report.target.target_url)}/robots.txt",
        "effective_interval_seconds": max(
            report.settings.request_interval_seconds, hard_floor_seconds
        ),
        "hard_floor_seconds": hard_floor_seconds,
        "concurrent_requests": report.settings.concurrent_requests,
        "pages_skipped_by_robots": report.pages_skipped_by_robots,
        "retention_days": report.settings.retention_days,
        "purpose_category": str(report.purpose.category),
        "purpose_note": report.purpose.note,
    }
    for key in COMPLIANCE_KEYS:
        yield key, values[key]


def _run_values(report: SiteReport) -> dict[str, object]:
    settings = report.settings
    return {
        "run_id": report.run_id,
        "started_at": timestamp(report.started_at),
        "finished_at": timestamp(report.finished_at),
        "outcome": str(report.outcome),
        "outcome_detail": report.outcome_detail or "",
        "purpose_category": str(report.purpose.category),
        "purpose_note": report.purpose.note,
        "retention_days": settings.retention_days,
        "tool_name": report.tool_name,
        "tool_version": report.tool_version,
        "user_agent": report.user_agent,
        "target_entered": report.target.entered_value,
        "target_url": report.target.target_url,
        "scope_host": report.target.scope_host,
        "include_subdomains": str(report.target.include_subdomains).lower(),
        "max_pages": settings.max_pages,
        "max_depth": settings.max_depth,
        "request_interval_seconds": settings.request_interval_seconds,
        "concurrent_requests": settings.concurrent_requests,
        "follow_sitemap": str(settings.follow_sitemap).lower(),
        "phone_region": settings.phone_region,
        "pages_fetched": report.pages_fetched,
        "requests_made": report.requests_made,
        "pages_skipped": report.pages_skipped,
        "pages_failed": report.pages_failed,
        "findings_count": report.findings_count,
    }


def _origin(url: str) -> str:
    scheme, _, rest = url.partition("://")
    return f"{scheme}://{rest.split('/', 1)[0]}"
