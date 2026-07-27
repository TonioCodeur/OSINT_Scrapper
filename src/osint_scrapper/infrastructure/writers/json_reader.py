"""Reading a canonical ``report.json`` back, so a run can be re-exported.

Re-exporting from the Runs pane must produce the same files without issuing a
single HTTP request (AC-EXPORT-6), which means the canonical record has to be
loadable, not only writable.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from osint_scrapper import SCHEMA_VERSION
from osint_scrapper.application.errors import ConfigurationError
from osint_scrapper.domain.attributes import ExtractionLayer, FieldName, Finding, Provenance
from osint_scrapper.domain.crawl import CrawlOutcome, PageOutcome, PageStatus
from osint_scrapper.domain.report import SiteReport
from osint_scrapper.domain.target import CrawlSettings, CrawlTarget, Purpose, PurposeCategory


class JsonReportLoader:
    """Rebuilds a :class:`SiteReport` from the canonical export."""

    def load(self, path: Path) -> SiteReport:
        """Return the report stored at ``path``.

        Raises:
            ConfigurationError: the file is missing, malformed, or written by a
                schema version this build does not understand.
        """
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as failure:
            raise ConfigurationError(f"cannot read report {path}: {failure}") from failure
        if not isinstance(document, dict):
            raise ConfigurationError(f"{path} is not a report document")
        version = document.get("schema_version")
        if version != SCHEMA_VERSION:
            raise ConfigurationError(
                f"{path} declares schema_version {version!r}, and this build writes "
                f"{SCHEMA_VERSION!r}"
            )
        try:
            return _report(document)
        except (KeyError, TypeError, ValueError) as failure:
            raise ConfigurationError(f"{path} is not a usable report: {failure}") from failure


def _report(document: dict[str, Any]) -> SiteReport:
    run = document["run"]
    target = document["target"]
    settings = document["settings"]
    statistics = document["statistics"]
    return SiteReport(
        run_id=str(run["run_id"]),
        target=CrawlTarget(
            entered_value=str(target["entered_value"]),
            target_url=str(target["target_url"]),
            scope_host=str(target["scope_host"]),
            include_subdomains=bool(target["include_subdomains"]),
        ),
        settings=CrawlSettings(
            max_pages=int(settings["max_pages"]),
            max_depth=int(settings["max_depth"]),
            request_interval_seconds=float(settings["request_interval_seconds"]),
            concurrent_requests=int(settings["concurrent_requests"]),
            include_subdomains=bool(target["include_subdomains"]),
            follow_sitemap=bool(settings["follow_sitemap"]),
            phone_region=str(settings["phone_region"]),
            retention_days=int(run["retention_days"]),
        ),
        purpose=Purpose(
            category=PurposeCategory(run["purpose_category"]), note=str(run["purpose_note"])
        ),
        started_at=_moment(run["started_at"]),
        finished_at=_moment(run["finished_at"]),
        outcome=CrawlOutcome(run["outcome"]),
        outcome_detail=run["outcome_detail"],
        tool_name=str(run["tool"]["name"]),
        tool_version=str(run["tool"]["version"]),
        user_agent=str(run["tool"]["user_agent"]),
        findings=tuple(_finding(item) for item in document["findings"]),
        pages=tuple(_page(item) for item in document["pages"]),
        pages_fetched=int(statistics["pages_fetched"]),
        requests_made=int(statistics["requests_made"]),
    )


def _finding(document: dict[str, Any]) -> Finding:
    return Finding(
        field=FieldName(document["field"]),
        value=str(document["value"]),
        extraction_confidence=float(document["extraction_confidence"]),
        page_support=int(document["page_support"]),
        occurrence_count=int(document["occurrence_count"]),
        first_seen_url=str(document["first_seen_url"]),
        metadata={str(key): str(value) for key, value in document["metadata"].items()},
        provenance=tuple(
            Provenance(
                source_url=str(entry["source_url"]),
                collected_at=_moment(entry["collected_at"]),
                extraction_layer=ExtractionLayer(entry["extraction_layer"]),
                raw_value=str(entry["raw_value"]),
            )
            for entry in document["provenance"]
        ),
    )


def _page(document: dict[str, Any]) -> PageOutcome:
    return PageOutcome(
        url=str(document["url"]),
        depth=int(document["depth"]),
        status=PageStatus(document["status"]),
        detail=document["detail"],
        http_status=document["http_status"],
        content_type=document["content_type"],
        findings_count=int(document["findings_count"]),
    )


def _moment(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
