"""The JSONL export (SPEC 9.4).

One object per line, one finding-by-provenance pair per object. Numbers stay
numbers, values containing newlines need no quoting, and the file is appendable
and streamable — which is the reason it exists alongside CSV rather than instead
of it. No formula guard applies: JSONL is not a spreadsheet, and mangling values
with an apostrophe would corrupt a machine format.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from osint_scrapper.domain.report import SiteReport
from osint_scrapper.infrastructure.writers.rows import timestamp

FILE_NAME = "report.jsonl"


class JsonlReportWriter:
    """Writes ``report.jsonl``."""

    @property
    def format_name(self) -> str:
        """The export format this writer produces."""
        return "jsonl"

    def write(self, report: SiteReport, destination_dir: Path) -> tuple[Path, ...]:
        """Write one JSON object per finding-by-provenance pair, LF-terminated."""
        path = destination_dir / FILE_NAME
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for record in records(report):
                handle.write(json.dumps(record, ensure_ascii=False))
                handle.write("\n")
        return (path,)


def records(report: SiteReport) -> Iterator[dict[str, Any]]:
    """Yield the JSONL records in the deterministic order of SPEC 9.1.1."""
    for finding in report.findings:
        for entry in finding.provenance:
            yield {
                "run_id": report.run_id,
                "purpose_category": str(report.purpose.category),
                "purpose_note": report.purpose.note,
                "retention_days": report.settings.retention_days,
                "target_entered": report.target.entered_value,
                "target_url": report.target.target_url,
                "scope_host": report.target.scope_host,
                "field": str(finding.field),
                "value": finding.value,
                "extraction_confidence": finding.extraction_confidence,
                "page_support": finding.page_support,
                "occurrence_count": finding.occurrence_count,
                "first_seen_url": finding.first_seen_url,
                "metadata": dict(finding.metadata),
                "source_url": entry.source_url,
                "extraction_layer": str(entry.extraction_layer),
                "raw_value": entry.raw_value,
                "collected_at": timestamp(entry.collected_at),
                "tool_name": report.tool_name,
                "tool_version": report.tool_version,
            }
