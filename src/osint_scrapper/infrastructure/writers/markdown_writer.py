"""The human-readable Markdown export (SPEC 9.5).

No raw HTML is ever emitted, so a Markdown renderer cannot be made to execute
anything a crawled site published. Cell values have ``|``, backticks and
backslashes escaped, ``<`` and ``>`` entity-escaped, ``[`` and ``]`` escaped so
no value can render as a link, and newlines replaced by a space.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from osint_scrapper.domain.attributes import FieldName
from osint_scrapper.domain.report import SiteReport
from osint_scrapper.infrastructure.http.rate_limit import HARD_FLOOR_SECONDS
from osint_scrapper.infrastructure.writers.rows import timestamp

FILE_NAME = "report.md"
_ESCAPES = {
    "\\": "\\\\",
    "|": "\\|",
    "`": "\\`",
    # Markdown renderers pass raw HTML through. Values here came from third-party
    # pages, so the angle brackets are entity-escaped rather than trusted: this
    # file must not be a way for a crawled site to run anything in a reader.
    "<": "&lt;",
    ">": "&gt;",
    # Brackets are escaped for the same reason one step further out: an
    # organization name of `[Annual report](https://phish.example)` would
    # otherwise render as a working link the operator never chose to include.
    # A report about untrusted text must not become a way to publish links.
    "[": "\\[",
    "]": "\\]",
}


class MarkdownReportWriter:
    """Writes ``report.md``, the deliverable a person reads."""

    def __init__(self, hard_floor_seconds: float = HARD_FLOOR_SECONDS) -> None:
        self._hard_floor_seconds = hard_floor_seconds

    @property
    def format_name(self) -> str:
        """The export format this writer produces."""
        return "md"

    def write(self, report: SiteReport, destination_dir: Path) -> tuple[Path, ...]:
        """Write the Markdown report and return the file created."""
        path = destination_dir / FILE_NAME
        path.write_text("\n".join(self._lines(report)) + "\n", encoding="utf-8")
        return (path,)

    def _lines(self, report: SiteReport) -> Iterator[str]:
        yield f"# OSINT report — {cell(report.target.scope_host)}"
        yield ""
        yield from _summary(report)
        yield ""
        yield "## Findings"
        yield ""
        yield from _findings(report)
        yield "## Pages"
        yield ""
        yield from _pages(report)
        yield ""
        yield "## Compliance"
        yield ""
        yield from _compliance(report, self._hard_floor_seconds)


def cell(value: str) -> str:
    """Escape a value so it cannot break the table or carry active content."""
    escaped = value
    for character, replacement in _ESCAPES.items():
        escaped = escaped.replace(character, replacement)
    return " ".join(escaped.splitlines())


def _summary(report: SiteReport) -> Iterator[str]:
    subdomains = "subdomains included" if report.target.include_subdomains else "this host only"
    yield "| Field | Value |"
    yield "| --- | --- |"
    yield f"| Run | {cell(report.run_id)} |"
    yield (
        f"| Target | {cell(report.target.target_url)} "
        f"(scope: {cell(report.target.scope_host)}, {subdomains}) |"
    )
    yield f"| Purpose | {cell(str(report.purpose.category))} |"
    if report.purpose.note:
        yield f"| Purpose note | {cell(report.purpose.note)} |"
    yield (
        f"| Started / finished | {timestamp(report.started_at)} "
        f"→ {timestamp(report.finished_at)} |"
    )
    yield f"| Outcome | {cell(str(report.outcome))} |"
    if report.outcome_detail:
        yield f"| Outcome detail | {cell(report.outcome_detail)} |"
    yield (
        f"| Pages fetched | {report.pages_fetched} of a {report.settings.max_pages}-page "
        f"budget, depth {report.settings.max_depth} |"
    )
    yield f"| Findings | {report.findings_count} |"


def _findings(report: SiteReport) -> Iterator[str]:
    for field in FieldName:
        rows = [finding for finding in report.findings if finding.field is field]
        if not rows:
            continue
        yield f"### {field}"
        yield ""
        yield "| Value | Extraction | Pages | First seen |"
        yield "| --- | --- | --- | --- |"
        for finding in rows:
            layer = max(entry.extraction_layer for entry in finding.provenance)
            yield (
                f"| {cell(finding.value)} | {cell(str(layer))} "
                f"({finding.extraction_confidence}) | {finding.page_support} "
                f"| {cell(finding.first_seen_url)} |"
            )
        yield ""


def _pages(report: SiteReport) -> Iterator[str]:
    yield "| Depth | Status | URL | Detail |"
    yield "| --- | --- | --- | --- |"
    for page in report.pages:
        yield (
            f"| {page.depth} | {cell(str(page.status))} | {cell(page.url)} "
            f"| {cell(page.detail or '')} |"
        )


def _compliance(report: SiteReport, hard_floor_seconds: float) -> Iterator[str]:
    interval = max(report.settings.request_interval_seconds, hard_floor_seconds)
    yield f"- User-Agent: {cell(report.user_agent)}"
    yield (
        "- robots.txt honored on every request and every redirect hop; "
        f"{report.pages_skipped_by_robots} pages skipped by robots"
    )
    yield f"- Effective request interval: {interval} s (hard floor {hard_floor_seconds} s)"
    yield f"- Concurrent requests: {report.settings.concurrent_requests}"
    yield f"- Retention declared: {report.settings.retention_days} days"
