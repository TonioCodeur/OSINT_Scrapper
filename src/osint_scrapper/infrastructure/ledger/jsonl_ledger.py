"""JSONL run ledger (SPEC 9.7).

The ledger stores ``target_host`` in plaintext. v1.0 hashed its subject, and that
was right there: the subject was a person's name. Here the target is a hostname,
generally not personal data, the report in the very same directory contains it in
full, and the Runs screen must be able to show what was crawled without opening
every report on disk. Hashing it would buy nothing and cost the feature. Where a
hostname *is* personal data, the remedy is the one GDPR actually asks for:
delete the run, which is one click away in the same screen.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from osint_scrapper.application.errors import ConfigurationError
from osint_scrapper.application.ports import LedgerEntry

logger = logging.getLogger(__name__)

LEDGER_FILE_NAME = "index.jsonl"


class JsonlRunLedger:
    """One JSON object per line, appended, rewritten only by an erasure."""

    def __init__(self, directory: Path) -> None:
        self._path = directory / LEDGER_FILE_NAME

    @property
    def path(self) -> Path:
        """Where the ledger is stored."""
        return self._path

    def record(self, entry: LedgerEntry) -> None:
        """Append one entry, creating the ledger if needed."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(_as_document(entry), ensure_ascii=False)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(f"{line}\n")

    def find(
        self, target_host: str | None = None, run_id: str | None = None
    ) -> Sequence[LedgerEntry]:
        """Return entries matching the given filters, in the order they were written."""
        return [
            entry
            for entry in self._read_all()
            if (target_host is None or entry.target_host == target_host)
            and (run_id is None or entry.run_id == run_id)
        ]

    def forget(self, run_ids: frozenset[str]) -> None:
        """Rewrite the ledger without the given runs."""
        if not self._path.exists():
            return
        remaining = [entry for entry in self._read_all() if entry.run_id not in run_ids]
        lines = [json.dumps(_as_document(entry), ensure_ascii=False) for entry in remaining]
        self._path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")

    def _read_all(self) -> list[LedgerEntry]:
        if not self._path.is_file():
            return []
        entries: list[LedgerEntry] = []
        for number, line in enumerate(self._path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                entries.append(_from_document(json.loads(line)))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as failure:
                raise ConfigurationError(
                    f"ledger {self._path} is corrupt at line {number}: {failure}"
                ) from failure
        return entries


def _as_document(entry: LedgerEntry) -> dict[str, Any]:
    return {
        "run_id": entry.run_id,
        "target_host": entry.target_host,
        "target_url": entry.target_url,
        "purpose_category": entry.purpose_category,
        "purpose_note": entry.purpose_note,
        "created_at": entry.created_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "retention_days": entry.retention_days,
        "directory": entry.directory,
        "pages_fetched": entry.pages_fetched,
        "findings_count": entry.findings_count,
        "files": list(entry.files),
    }


def _from_document(document: dict[str, Any]) -> LedgerEntry:
    created_at = datetime.fromisoformat(str(document["created_at"]).replace("Z", "+00:00"))
    return LedgerEntry(
        run_id=str(document["run_id"]),
        target_host=str(document["target_host"]),
        target_url=str(document["target_url"]),
        purpose_category=str(document["purpose_category"]),
        purpose_note=str(document["purpose_note"]),
        created_at=created_at.astimezone(UTC),
        retention_days=int(document["retention_days"]),
        directory=str(document["directory"]),
        pages_fetched=int(document["pages_fetched"]),
        findings_count=int(document["findings_count"]),
        files=tuple(str(name) for name in document["files"]),
    )


class FilesystemDirectoryRemover:
    """Deletes a run directory and reports every path it removed."""

    def remove_tree(self, path: Path) -> tuple[Path, ...]:
        """Delete ``path`` recursively, returning the files and directories removed."""
        if not path.exists():
            return ()
        removed: list[Path] = []
        for child in sorted(path.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if child.is_file() or child.is_symlink():
                child.unlink()
            else:
                child.rmdir()
            removed.append(child)
        path.rmdir()
        removed.append(path)
        return tuple(removed)

    def size_of(self, path: Path) -> int:
        """Return the total size of ``path`` in bytes, or 0 when it is gone."""
        if not path.is_dir():
            return 0
        return sum(child.stat().st_size for child in path.rglob("*") if child.is_file())
