"""Listing and erasing stored runs (SPEC FR-17, FR-18, 7.4).

Nothing is ever deleted automatically. Retention is declared and displayed; the
deletion itself is always one deliberate operator action.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from osint_scrapper.application.ports import (
    Clock,
    DirectoryRemover,
    ErasureReport,
    LedgerEntry,
    RunLedger,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunSummary:
    """One row of the Runs pane, flat so the view has nothing to compute."""

    run_id: str
    target_host: str
    target_url: str
    purpose_category: str
    purpose_note: str
    created_at: datetime
    retention_days: int
    directory: str
    pages_fetched: int
    findings_count: int
    files: tuple[str, ...]
    size_bytes: int
    days_remaining: int
    expired: bool


class ListRunsUseCase:
    """Reads the ledger and measures what each run occupies on disk."""

    def __init__(self, ledger: RunLedger, remover: DirectoryRemover, clock: Clock) -> None:
        self._ledger = ledger
        self._remover = remover
        self._clock = clock

    def execute(self) -> tuple[RunSummary, ...]:
        """Return every recorded run, newest first."""
        now = self._clock.now()
        summaries = [self._summarize(entry, now) for entry in self._ledger.find()]
        summaries.sort(key=lambda summary: (summary.created_at, summary.run_id), reverse=True)
        return tuple(summaries)

    def _summarize(self, entry: LedgerEntry, now: datetime) -> RunSummary:
        expires_at = entry.created_at + timedelta(days=entry.retention_days)
        remaining = (expires_at - now).days
        return RunSummary(
            run_id=entry.run_id,
            target_host=entry.target_host,
            target_url=entry.target_url,
            purpose_category=entry.purpose_category,
            purpose_note=entry.purpose_note,
            created_at=entry.created_at,
            retention_days=entry.retention_days,
            directory=entry.directory,
            pages_fetched=entry.pages_fetched,
            findings_count=entry.findings_count,
            files=entry.files,
            size_bytes=self._remover.size_of(Path(entry.directory)),
            days_remaining=remaining,
            expired=expires_at <= now,
        )


class EraseRunsUseCase:
    """Removes run directories and the ledger lines that pointed at them."""

    def __init__(self, ledger: RunLedger, remover: DirectoryRemover, clock: Clock) -> None:
        self._ledger = ledger
        self._remover = remover
        self._clock = clock

    def execute(self, run_ids: frozenset[str]) -> ErasureReport:
        """Delete the named runs.

        Matching nothing is a success, not an error: the operator asked for the
        data to be gone and it is gone.
        """
        entries = [entry for entry in self._ledger.find() if entry.run_id in run_ids]
        return self._erase(entries)

    def execute_expired(self) -> ErasureReport:
        """Delete every run past its declared retention (SPEC FR-18)."""
        now = self._clock.now()
        entries = [
            entry
            for entry in self._ledger.find()
            if entry.created_at + timedelta(days=entry.retention_days) <= now
        ]
        return self._erase(entries)

    def _erase(self, entries: list[LedgerEntry]) -> ErasureReport:
        if not entries:
            return ErasureReport()
        removed_paths: list[Path] = []
        removed_run_ids: list[str] = []
        for entry in entries:
            removed_paths.extend(self._remover.remove_tree(Path(entry.directory)))
            removed_run_ids.append(entry.run_id)
            logger.info("erased run %s", entry.run_id)
        self._ledger.forget(frozenset(removed_run_ids))
        return ErasureReport(
            removed_paths=tuple(removed_paths), removed_run_ids=tuple(removed_run_ids)
        )
