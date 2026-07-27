"""Exporting a report, which is now an operator action of its own (SPEC 7.8).

A completed run can be re-exported to further formats from the Runs pane without
re-crawling, so export is a use case rather than the tail of the crawl.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Sequence
from pathlib import Path

from osint_scrapper.application.errors import ExportFailedError
from osint_scrapper.application.ports import LedgerEntry, ReportLoader, ResultWriter, RunLedger
from osint_scrapper.domain.report import SiteReport
from osint_scrapper.domain.url import scope_host_of

logger = logging.getLogger(__name__)

CANONICAL_FORMAT = "json"
"""JSON is always written and cannot be deselected: it is the canonical record."""

CANONICAL_FILE_NAME = "report.json"


class ExportRunUseCase:
    """Writes a report in the chosen formats and records the run in the ledger."""

    def __init__(
        self, writers: Sequence[ResultWriter], ledger: RunLedger, loader: ReportLoader
    ) -> None:
        self._writers = tuple(writers)
        self._ledger = ledger
        self._loader = loader

    @property
    def available_formats(self) -> tuple[str, ...]:
        """Every format this build can write, in writer order."""
        return tuple(writer.format_name for writer in self._writers)

    def execute(
        self,
        report: SiteReport,
        formats: Sequence[str],
        output_directory: Path,
        copy_to: Path | None = None,
    ) -> tuple[Path, ...]:
        """Write ``report`` under ``<output_directory>/<run_id>/`` and index it.

        ``json`` is written whatever ``formats`` says. ``copy_to`` copies the
        results to a second directory; the run directory always keeps its own
        canonical copy.

        Raises:
            ExportFailedError: at least one writer failed. Every other writer
                still ran and its files are on disk.
        """
        destination = output_directory / report.run_id
        destination.mkdir(parents=True, exist_ok=True)
        written, failures = self._run_writers(report, destination, formats)
        self._ledger.record(_ledger_entry(report, destination, written))
        copied = _copy_all(written, copy_to)
        if failures:
            raise ExportFailedError(written=written + copied, failures=failures)
        return written + copied

    def re_export(
        self,
        run_id: str,
        formats: Sequence[str],
        output_directory: Path,
        copy_to: Path | None = None,
    ) -> tuple[Path, ...]:
        """Rewrite the exports of a completed run, issuing no HTTP request.

        The ledger is not appended to a second time: the run was already indexed
        when it was first exported.

        Raises:
            ConfigurationError: the run's canonical report is missing or unreadable.
            ExportFailedError: at least one writer failed.
        """
        destination = output_directory / run_id
        report = self._loader.load(destination / CANONICAL_FILE_NAME)
        written, failures = self._run_writers(report, destination, formats)
        copied = _copy_all(written, copy_to)
        if failures:
            raise ExportFailedError(written=written + copied, failures=failures)
        return written + copied

    def _run_writers(
        self, report: SiteReport, destination: Path, formats: Sequence[str]
    ) -> tuple[tuple[Path, ...], tuple[tuple[str, str], ...]]:
        """Run every selected writer, letting one failure cost only its own file."""
        selected = {name.lower() for name in formats} | {CANONICAL_FORMAT}
        written: list[Path] = []
        failures: list[tuple[str, str]] = []
        for writer in self._writers:
            if writer.format_name not in selected:
                continue
            try:
                written.extend(writer.write(report, destination))
            except OSError as failure:
                logger.warning("the %s export failed: %s", writer.format_name, failure)
                failures.append((writer.format_name, str(failure)))
        return tuple(written), tuple(failures)


def _copy_all(written: Sequence[Path], copy_to: Path | None) -> tuple[Path, ...]:
    """Copy the exported files to the operator's chosen directory, if any."""
    if copy_to is None:
        return ()
    copy_to.mkdir(parents=True, exist_ok=True)
    return tuple(Path(shutil.copy2(path, copy_to / path.name)) for path in written)


def _ledger_entry(report: SiteReport, destination: Path, written: Sequence[Path]) -> LedgerEntry:
    return LedgerEntry(
        run_id=report.run_id,
        target_host=scope_host_of(report.target.target_url),
        target_url=report.target.target_url,
        purpose_category=str(report.purpose.category),
        purpose_note=report.purpose.note,
        created_at=report.finished_at,
        retention_days=report.settings.retention_days,
        directory=destination.as_posix(),
        pages_fetched=report.pages_fetched,
        findings_count=report.findings_count,
        files=tuple(path.name for path in written),
    )
