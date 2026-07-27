"""The canonical JSON export (SPEC 9.1).

Key order is written deliberately rather than sorted, and it is the documented
schema: a test asserts that no key outside it ever appears, which is how data
minimization stays verifiable (AC-EXPORT-4).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from osint_scrapper import SCHEMA_VERSION
from osint_scrapper.domain.attributes import Finding
from osint_scrapper.domain.report import SiteReport
from osint_scrapper.infrastructure.writers.rows import timestamp

REPORT_FILE_NAME = "report.json"


class JsonReportWriter:
    """Writes ``report.json``, the record every other format is a subset of."""

    @property
    def format_name(self) -> str:
        """The export format this writer produces."""
        return "json"

    def write(self, report: SiteReport, destination_dir: Path) -> tuple[Path, ...]:
        """Write the canonical document and return the file created."""
        path = destination_dir / REPORT_FILE_NAME
        payload = json.dumps(as_document(report), ensure_ascii=False, indent=2)
        path.write_text(f"{payload}\n", encoding="utf-8")
        return (path,)


def as_document(report: SiteReport) -> dict[str, Any]:
    """Return the report as the documented JSON structure."""
    settings = report.settings
    return {
        "schema_version": SCHEMA_VERSION,
        "run": {
            "run_id": report.run_id,
            "started_at": timestamp(report.started_at),
            "finished_at": timestamp(report.finished_at),
            "outcome": str(report.outcome),
            "outcome_detail": report.outcome_detail,
            "purpose_category": str(report.purpose.category),
            "purpose_note": report.purpose.note,
            "retention_days": settings.retention_days,
            "tool": {
                "name": report.tool_name,
                "version": report.tool_version,
                "user_agent": report.user_agent,
            },
        },
        "target": {
            "entered_value": report.target.entered_value,
            "target_url": report.target.target_url,
            "scope_host": report.target.scope_host,
            "include_subdomains": report.target.include_subdomains,
        },
        "settings": {
            "max_pages": settings.max_pages,
            "max_depth": settings.max_depth,
            "request_interval_seconds": settings.request_interval_seconds,
            "concurrent_requests": settings.concurrent_requests,
            "follow_sitemap": settings.follow_sitemap,
            "phone_region": settings.phone_region,
        },
        "statistics": {
            "pages_fetched": report.pages_fetched,
            "requests_made": report.requests_made,
            "pages_skipped": report.pages_skipped,
            "pages_failed": report.pages_failed,
            "findings_count": report.findings_count,
        },
        "findings": [_finding(item) for item in report.findings],
        "pages": [
            {
                "url": page.url,
                "depth": page.depth,
                "status": str(page.status),
                "detail": page.detail,
                "http_status": page.http_status,
                "content_type": page.content_type,
                "findings_count": page.findings_count,
            }
            for page in report.pages
        ],
    }


def _finding(finding: Finding) -> dict[str, Any]:
    return {
        "field": str(finding.field),
        "value": finding.value,
        "extraction_confidence": finding.extraction_confidence,
        "page_support": finding.page_support,
        "occurrence_count": finding.occurrence_count,
        "first_seen_url": finding.first_seen_url,
        "metadata": dict(finding.metadata),
        "provenance": [
            {
                "source_url": entry.source_url,
                "collected_at": timestamp(entry.collected_at),
                "extraction_layer": str(entry.extraction_layer),
                "raw_value": entry.raw_value,
            }
            for entry in finding.provenance
        ],
    }
