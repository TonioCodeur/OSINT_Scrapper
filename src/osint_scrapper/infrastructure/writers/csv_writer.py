"""The flat CSV exports (SPEC 9.2).

The BOM is a deliberate deviation from plain UTF-8: without it Excel misreads
accented values, and these files exist to be opened in a spreadsheet.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Sequence
from pathlib import Path

from osint_scrapper.domain.report import SiteReport
from osint_scrapper.infrastructure.writers.rows import (
    FINDING_COLUMNS,
    PAGE_COLUMNS,
    finding_rows,
    page_rows,
)
from osint_scrapper.infrastructure.writers.sanitize import guard

FINDINGS_FILE_NAME = "report.csv"
PAGES_FILE_NAME = "report_pages.csv"
ENCODING = "utf-8-sig"
LINE_TERMINATOR = "\r\n"


class CsvReportWriter:
    """Writes ``report.csv`` and ``report_pages.csv``."""

    @property
    def format_name(self) -> str:
        """The export format this writer produces."""
        return "csv"

    def write(self, report: SiteReport, destination_dir: Path) -> tuple[Path, ...]:
        """Write both CSV files and return the paths created."""
        findings_path = destination_dir / FINDINGS_FILE_NAME
        pages_path = destination_dir / PAGES_FILE_NAME
        _write(findings_path, FINDING_COLUMNS, finding_rows(report))
        _write(pages_path, PAGE_COLUMNS, page_rows(report))
        return (findings_path, pages_path)


def _write(path: Path, columns: Sequence[str], rows: Iterable[tuple[object, ...]]) -> None:
    with path.open("w", newline="", encoding=ENCODING) as handle:
        writer = csv.writer(handle, lineterminator=LINE_TERMINATOR, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([_cell(value) for value in row])


def _cell(value: object) -> object:
    """Numbers stay numbers; every string is guarded against formula injection."""
    if isinstance(value, bool) or not isinstance(value, str):
        return value
    return guard(value)
