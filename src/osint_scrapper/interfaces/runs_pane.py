"""The Runs pane: the home of the right to erasure (SPEC 7.4, FR-17, FR-18).

In a command line these were a subcommand and a number in a JSON file. Here
they are a screen an operator actually looks at, which is the point: a deletion
capability nobody can find is a deletion capability nobody uses.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from osint_scrapper.application.ports import ErasureReport
from osint_scrapper.application.runs import EraseRunsUseCase, ListRunsUseCase, RunSummary
from osint_scrapper.interfaces.crawl_pane import BannerLabel, build_table_view
from osint_scrapper.interfaces.export_dialog import ExportDialog, ExportJob, open_path
from osint_scrapper.interfaces.models import RunsTableModel, SortedProxy
from osint_scrapper.interfaces.view_models import (
    Banner,
    ExportSelection,
    RunRow,
    Severity,
    delete_confirmation,
    run_rows,
)
from osint_scrapper.interfaces.worker import run_in_background

logger = logging.getLogger(__name__)

CONFIRMATION_WORD = "DELETE"


class ConfirmDeleteDialog(QDialog):
    """Names every directory a deletion will remove, before it removes it."""

    def __init__(
        self, message: str, requires_typed_word: bool, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Delete runs")
        self.setModal(True)
        self.setMinimumWidth(560)
        self._requires_typed_word = requires_typed_word

        details = QPlainTextEdit(message, self)
        details.setReadOnly(True)
        details.setMinimumHeight(180)

        self._typed = QLineEdit(self)
        self._typed.setPlaceholderText(CONFIRMATION_WORD)
        self._typed.setVisible(requires_typed_word)

        self._buttons = QDialogButtonBox(self)
        self._delete_button = self._buttons.addButton(
            "Delete", QDialogButtonBox.ButtonRole.DestructiveRole
        )
        self._buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self._delete_button.setEnabled(not requires_typed_word)

        layout = QVBoxLayout(self)
        layout.addWidget(details)
        layout.addWidget(self._typed)
        layout.addWidget(self._buttons)

        self._typed.textChanged.connect(self._check_word)
        self._delete_button.clicked.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

    @Slot()
    def _check_word(self) -> None:
        self._delete_button.setEnabled(
            not self._requires_typed_word or self._typed.text().strip() == CONFIRMATION_WORD
        )


class RunsPane(QWidget):
    """Lists every recorded run and deletes runs on demand."""

    status_message = Signal(str)

    def __init__(
        self,
        list_runs: ListRunsUseCase,
        erase_runs: EraseRunsUseCase,
        export_job_for: Callable[[RunRow], ExportJob],
        default_selection: ExportSelection,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._list_runs = list_runs
        self._erase_runs = erase_runs
        self._export_job_for = export_job_for
        self._default_selection = default_selection

        self._model = RunsTableModel(self)
        self._model.set_palette(self.palette())
        self._proxy = SortedProxy(self)
        self._proxy.setSourceModel(self._model)
        self._view = build_table_view(self._proxy)
        self._view.sortByColumn(0, Qt.SortOrder.DescendingOrder)

        self._banner = BannerLabel(self)
        self._refresh_button = QPushButton("&Refresh", self)
        self._open_button = QPushButton("&Open folder", self)
        self._reexport_button = QPushButton("Re-&export…", self)
        self._delete_button = QPushButton("&Delete", self)
        self._delete_expired_button = QPushButton("Delete e&xpired", self)
        self._delete_all_button = QPushButton("Delete &all…", self)
        self._delete_all_button.setToolTip(
            f"Deletes every recorded run. Requires typing {CONFIRMATION_WORD} to confirm."
        )

        self._build_layout()
        self._connect()
        self.refresh()

    def _build_layout(self) -> None:
        explanation = QLabel(
            "Nothing is ever deleted automatically. Retention is declared in every export "
            "and shown here; deleting is always your decision.",
            self,
        )
        explanation.setWordWrap(True)

        buttons = QHBoxLayout()
        buttons.addWidget(self._refresh_button)
        buttons.addWidget(self._open_button)
        buttons.addWidget(self._reexport_button)
        buttons.addStretch(1)
        buttons.addWidget(self._delete_button)
        buttons.addWidget(self._delete_expired_button)
        buttons.addWidget(self._delete_all_button)

        layout = QVBoxLayout(self)
        layout.addWidget(explanation)
        layout.addWidget(self._banner)
        layout.addWidget(self._view, 1)
        layout.addLayout(buttons)

    def _connect(self) -> None:
        self._refresh_button.clicked.connect(self.refresh)
        self._open_button.clicked.connect(self.open_selected)
        self._reexport_button.clicked.connect(self.re_export_selected)
        self._delete_button.clicked.connect(self.delete_selected)
        self._delete_expired_button.clicked.connect(self.delete_expired)
        self._delete_all_button.clicked.connect(self.delete_all)
        self._view.selectionModel().selectionChanged.connect(self._update_buttons)
        self._update_buttons()

    # --------------------------------------------------------------- reading

    @Slot()
    def refresh(self) -> None:
        """Reload the ledger off the GUI thread."""
        run_in_background(self, self._list_runs.execute, self._on_runs, self._on_failure)

    @Slot(object)
    def _on_runs(self, summaries: Sequence[RunSummary]) -> None:
        self._model.set_rows(run_rows(summaries))
        self._update_buttons()
        plural = "" if len(summaries) == 1 else "s"
        self.status_message.emit(f"{len(summaries)} recorded run{plural}")

    @Slot(object)
    def _on_failure(self, failure: BaseException) -> None:
        self._banner.show_banner(
            Banner(
                Severity.ERROR,
                type(failure).__name__,
                "The run ledger could not be read. The runs directory may have moved "
                "or may not be readable.",
                str(failure),
            )
        )

    def rows(self) -> tuple[RunRow, ...]:
        """Every row currently displayed."""
        return self._model.rows()

    def selected_rows(self) -> tuple[RunRow, ...]:
        """The rows the operator has selected, in display order."""
        positions = sorted(
            {index.row() for index in self._view.selectionModel().selectedRows()}
        )
        return tuple(
            self._model.row_at(self._proxy.mapToSource(self._proxy.index(row, 0)).row())
            for row in positions
        )

    @Slot()
    def _update_buttons(self) -> None:
        selected = bool(self.selected_rows())
        self._open_button.setEnabled(selected)
        self._delete_button.setEnabled(selected)
        self._reexport_button.setEnabled(len(self.selected_rows()) == 1)
        self._delete_expired_button.setEnabled(any(row.expired for row in self.rows()))
        self._delete_all_button.setEnabled(bool(self.rows()))

    # --------------------------------------------------------------- actions

    @Slot()
    def open_selected(self) -> None:
        """Open the selected run's directory in the file manager."""
        for row in self.selected_rows()[:1]:
            if not open_path(Path(row.directory)):
                self.status_message.emit(f"Could not open {row.directory}")

    @Slot()
    def re_export_selected(self) -> None:
        """Re-export a completed run without crawling anything again."""
        rows = self.selected_rows()
        if len(rows) != 1:
            return
        dialog = ExportDialog(self._export_job_for(rows[0]), self._default_selection, parent=self)
        dialog.exec()

    @Slot()
    def delete_selected(self) -> None:
        """Delete the selected runs, after naming exactly what will be removed."""
        self._delete(self.selected_rows(), deleting_all=False)

    @Slot()
    def delete_all(self) -> None:
        """Delete every recorded run. Requires typing the confirmation word."""
        self._delete(self.rows(), deleting_all=True)

    @Slot()
    def delete_expired(self) -> None:
        """Delete every run past its declared retention (SPEC FR-18)."""
        expired = tuple(row for row in self.rows() if row.expired)
        if not expired:
            self.status_message.emit("No run is past its declared retention")
            return
        if not self._confirm(expired, deleting_all=False):
            return
        run_in_background(
            self, self._erase_runs.execute_expired, self._on_erased, self._on_erase_failed
        )

    def _delete(self, rows: Sequence[RunRow], deleting_all: bool) -> None:
        if not rows:
            self.status_message.emit("Nothing matched. No run was deleted.")
            return
        if not self._confirm(rows, deleting_all):
            return
        run_ids = frozenset(row.run_id for row in rows)
        run_in_background(
            self,
            lambda: self._erase_runs.execute(run_ids),
            self._on_erased,
            self._on_erase_failed,
        )

    def _confirm(self, rows: Sequence[RunRow], deleting_all: bool) -> bool:
        confirmation = delete_confirmation(rows, deleting_all)
        dialog = ConfirmDeleteDialog(
            confirmation.message(), confirmation.requires_typed_word, self
        )
        return dialog.exec() == QDialog.DialogCode.Accepted

    @Slot(object)
    def _on_erased(self, report: ErasureReport) -> None:
        removed = report.removed_run_ids
        if not removed:
            self.status_message.emit("Nothing matched. No run was deleted.")
        else:
            plural = "" if len(removed) == 1 else "s"
            self.status_message.emit(f"Deleted {len(removed)} run{plural}")
        self.refresh()

    @Slot(object)
    def _on_erase_failed(self, failure: BaseException) -> None:
        self._banner.show_banner(
            Banner(
                Severity.ERROR,
                type(failure).__name__,
                "The runs could not be deleted. Check that the directory is not open "
                "in another program.",
                str(failure),
            )
        )
        self.refresh()
