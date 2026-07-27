"""The export dialog (SPEC 7.8).

It knows how to ask which formats to write and where to put them. It does not
know how to write them: the caller hands it an :class:`ExportJob` whose ``run``
closes over the export use case built in ``interfaces/app.py``. That is what
lets the same dialog serve a run that has just finished and a run being
re-exported from the Runs pane, without a branch on which one it is.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from osint_scrapper.application.errors import ExportFailedError
from osint_scrapper.interfaces.view_models import ExportSelection
from osint_scrapper.interfaces.worker import run_in_background

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExportJob:
    """One export the dialog can perform, as a closure over the use case."""

    run_id: str
    default_directory: Path
    run: Callable[[Sequence[str], Path | None], tuple[Path, ...]]
    """``(formats, copy_to) -> written files``. Runs off the GUI thread."""


class ExportDialog(QDialog):
    """Choose formats and a destination, then write off the GUI thread."""

    def __init__(
        self,
        job: ExportJob,
        selection: ExportSelection,
        open_folder_when_done: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._job = job
        self._written: tuple[Path, ...] = ()
        self.setWindowTitle(f"Export run {job.run_id}")
        self.setModal(True)
        self.setMinimumWidth(560)

        self._json = QCheckBox("JSON — report.json", self)
        self._json.setChecked(True)
        self._json.setEnabled(False)
        self._json.setToolTip(
            "JSON is the canonical record and a superset of every other format, "
            "so it is always written."
        )
        self._csv = QCheckBox("CSV — report.csv and report_pages.csv", self)
        self._csv.setChecked(selection.csv)
        self._xlsx = QCheckBox("XLSX — report.xlsx", self)
        self._xlsx.setChecked(selection.xlsx)
        self._jsonl = QCheckBox("JSONL — report.jsonl", self)
        self._jsonl.setChecked(selection.jsonl)
        self._markdown = QCheckBox("Markdown — report.md", self)
        self._markdown.setChecked(selection.markdown)

        self._destination = QLineEdit(str(job.default_directory), self)
        self._destination.setToolTip(
            "The run directory always keeps its own canonical copy. Choosing another "
            "directory copies the exports there as well."
        )
        self._browse = QPushButton("Browse…", self)
        self._open_when_done = QCheckBox("Open the folder when done", self)
        self._open_when_done.setChecked(open_folder_when_done)

        self._results = QPlainTextEdit(self)
        self._results.setReadOnly(True)
        self._results.setVisible(False)
        self._results.setMaximumHeight(160)

        self._buttons = QDialogButtonBox(self)
        self._export_button = self._buttons.addButton(
            "Export", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._close_button = self._buttons.addButton(QDialogButtonBox.StandardButton.Cancel)

        self._build_layout()
        self._browse.clicked.connect(self._choose_directory)
        self._export_button.clicked.connect(self.start_export)
        self._buttons.rejected.connect(self.reject)

    def _build_layout(self) -> None:
        formats = QGroupBox("Formats", self)
        formats_layout = QVBoxLayout(formats)
        for box in (self._json, self._csv, self._xlsx, self._jsonl, self._markdown):
            formats_layout.addWidget(box)

        destination_row = QHBoxLayout()
        destination_row.addWidget(self._destination, 1)
        destination_row.addWidget(self._browse)

        layout = QVBoxLayout(self)
        layout.addWidget(formats)
        layout.addWidget(QLabel("Destination", self))
        layout.addLayout(destination_row)
        layout.addWidget(self._open_when_done)
        layout.addWidget(self._results)
        layout.addWidget(self._buttons)

    def selection(self) -> ExportSelection:
        """Which formats are currently ticked. JSON is not part of the choice."""
        return ExportSelection(
            csv=self._csv.isChecked(),
            xlsx=self._xlsx.isChecked(),
            jsonl=self._jsonl.isChecked(),
            markdown=self._markdown.isChecked(),
        )

    def written_files(self) -> tuple[Path, ...]:
        """Every file the last export actually produced."""
        return self._written

    def destination(self) -> Path | None:
        """The extra directory to copy into, or ``None`` for the run directory alone."""
        chosen = Path(self._destination.text().strip())
        if chosen == self._job.default_directory:
            return None
        return chosen

    @Slot()
    def _choose_directory(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose an export destination", self._destination.text()
        )
        if chosen:
            self._destination.setText(chosen)

    @Slot()
    def start_export(self) -> None:
        """Write the selected formats off the GUI thread."""
        formats = self.selection().format_names()
        copy_to = self.destination()
        self._set_busy(True)
        run_in_background(
            self,
            lambda: self._job.run(formats, copy_to),
            self._on_written,
            self._on_failed,
        )

    def _set_busy(self, busy: bool) -> None:
        self._export_button.setEnabled(not busy)
        for box in (self._csv, self._xlsx, self._jsonl, self._markdown):
            box.setEnabled(not busy)
        self._destination.setEnabled(not busy)
        self._browse.setEnabled(not busy)
        self.setCursor(Qt.CursorShape.BusyCursor if busy else Qt.CursorShape.ArrowCursor)

    @Slot(object)
    def _on_written(self, written: tuple[Path, ...]) -> None:
        """Report every file that was written, and stay open while it is read.

        SPEC 7.8 asks for per-file success *in the dialog, before it closes*; a
        dialog that vanishes the moment the last file lands reports nothing.
        """
        self._written = written
        self._report(["Written:", *(f"  {path}" for path in written)])
        self._set_busy(False)
        self._close_button.setText("Close")
        if self._open_when_done.isChecked() and written:
            open_path(written[0].parent)

    @Slot(object)
    def _on_failed(self, failure: BaseException) -> None:
        """Report what was written, and what was not, and why.

        A partial export is the normal shape of this failure — one locked
        spreadsheet must not hide the four files that did land (SPEC 7.8).

        Successes are named per *file* and failures per *format*, because that
        is what each side of ``ExportFailedError`` actually carries: one writer
        can emit several files, so ``csv`` failing is one entry covering both
        ``report.csv`` and ``report_pages.csv``.
        """
        self._set_busy(False)
        lines: list[str] = []
        if isinstance(failure, ExportFailedError):
            self._written = failure.written
            lines.append("Written:")
            lines.extend(f"  {path}" for path in failure.written)
            lines.append("")
            lines.append("Not written:")
            lines.extend(f"  {name} format — {reason}" for name, reason in failure.failures)
        else:
            lines.append(f"Failed: {type(failure).__name__}: {failure}")
        self._report(lines)
        self._close_button.setText("Close")

    def _report(self, lines: Sequence[str]) -> None:
        self._results.setPlainText("\n".join(lines))
        self._results.setVisible(True)


def open_path(target: Path) -> bool:
    """Open a file or a directory with the operator's default application.

    The path is made absolute first. The run ledger stores directories relative
    to the output directory, and ``QUrl.fromLocalFile`` on a relative path
    yields ``file:runs/r-…`` — a URL with no authority that no file manager
    opens. Resolving against the working directory is the same interpretation
    the ledger itself already implies.
    """
    return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(_absolute(target)))))


def _absolute(target: Path) -> Path:
    """Return ``target`` as an absolute path, even if it does not exist yet."""
    return target if target.is_absolute() else Path.cwd() / target
