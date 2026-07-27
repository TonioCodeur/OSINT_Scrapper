"""The application shell: one window, three panes, one menu bar (SPEC 7.1).

Switching panes never interrupts a running crawl, because the panes are alive
side by side and only one of them is visible. Window geometry, the splitter and
the column widths are persisted with ``QSettings``; every *product* setting
lives in the configuration file instead, which is the whole of the two-store
split.
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Final

from PySide6.QtCore import QByteArray, QSettings, Qt, Slot
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from osint_scrapper.domain.report import SiteReport
from osint_scrapper.infrastructure.config import AppConfig
from osint_scrapper.interfaces.about_dialog import AboutDialog
from osint_scrapper.interfaces.crawl_pane import CrawlPane
from osint_scrapper.interfaces.export_dialog import ExportDialog, ExportJob, open_path
from osint_scrapper.interfaces.runs_pane import RunsPane
from osint_scrapper.interfaces.settings_pane import SettingsPane
from osint_scrapper.interfaces.view_models import ExportSelection, report_summary
from osint_scrapper.interfaces.worker import CrawlController

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_SIZE: Final = (1180, 820)
MINIMUM_WINDOW_SIZE: Final = (900, 620)

GEOMETRY_KEY: Final = "window/geometry"
STATE_KEY: Final = "window/state"
SPLITTER_KEY: Final = "window/crawl_splitter"


class CrashDialog(QDialog):
    """The third error tier: a defect, shown loudly and copyably (SPEC 7.5).

    This is the only modal in the product that the operator did not ask for. A
    stack trace belongs here and nowhere else — never in a page log row, never
    in a banner, and never silently in a log file the operator will not read.
    """

    def __init__(self, failure: BaseException, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Unexpected error")
        self.setModal(True)
        self.setMinimumWidth(620)
        self._details = _format_failure(failure)

        headline = QLabel(
            f"<b>{type(failure).__name__}</b><br>{failure}<br><br>"
            "This is a defect in the application, not something you did. The run is "
            "marked failed, and everything collected before the failure is still "
            "exportable.",
            self,
        )
        headline.setWordWrap(True)
        headline.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        detail_view = QPlainTextEdit(self._details, self)
        detail_view.setReadOnly(True)
        detail_view.setMinimumHeight(220)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        self._copy = QPushButton("Copy details", self)
        buttons.addButton(self._copy, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)
        self._copy.clicked.connect(self.copy_details)

        layout = QVBoxLayout(self)
        layout.addWidget(headline)
        layout.addWidget(detail_view)
        layout.addWidget(buttons)

    def details(self) -> str:
        """The full text the Copy details button puts on the clipboard."""
        return self._details

    @Slot()
    def copy_details(self) -> None:
        """Put the exception type, message and traceback on the clipboard."""
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._details)


def _format_failure(failure: BaseException) -> str:
    return "".join(
        traceback.format_exception(type(failure), failure, failure.__traceback__)
    ).strip()


class MainWindow(QMainWindow):
    """One window holding the Crawl, Runs and Settings panes."""

    def __init__(
        self,
        crawl_pane: CrawlPane,
        runs_pane: RunsPane,
        settings_pane: SettingsPane,
        crawl_controller: CrawlController,
        export_job_for_report: Callable[[SiteReport], ExportJob],
        user_agent_for: Callable[[AppConfig], str],
        default_selection: ExportSelection,
        output_directory: Path,
        tool_name: str,
        version: str,
        licenses_path: Path,
        readme_path: Path,
        settings: QSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._crawl_pane = crawl_pane
        self._runs_pane = runs_pane
        self._settings_pane = settings_pane
        self._crawl_controller = crawl_controller
        self._export_job_for_report = export_job_for_report
        self._user_agent_for = user_agent_for
        self._default_selection = default_selection
        self._output_directory = output_directory
        self._tool_name = tool_name
        self._version = version
        self._licenses_path = licenses_path
        self._readme_path = readme_path
        self._settings = settings

        self.setWindowTitle(f"{tool_name} {version}")
        self.setMinimumSize(*MINIMUM_WINDOW_SIZE)
        self.resize(*DEFAULT_WINDOW_SIZE)

        self._tabs = QTabWidget(self)
        self._tabs.addTab(crawl_pane, "&Crawl")
        self._tabs.addTab(runs_pane, "&Runs")
        self._tabs.addTab(settings_pane, "&Settings")
        self.setCentralWidget(self._tabs)

        self._build_menus()
        status = self.statusBar()
        if status is not None:
            status.showMessage("Idle")

        crawl_pane.state_changed.connect(self.show_status)
        crawl_pane.run_finished.connect(self._on_run_finished)
        crawl_pane.crashed.connect(self.show_crash)
        runs_pane.status_message.connect(self.show_status)
        settings_pane.status_message.connect(self.show_status)
        settings_pane.config_saved.connect(self._on_config_saved)

        self.restore_layout()

    def _build_menus(self) -> None:
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")
        settings_action = QAction("&Settings…", self)
        settings_action.setShortcut(QKeySequence.StandardKey.Preferences)
        settings_action.triggered.connect(self.show_settings)
        file_menu.addAction(settings_action)

        open_output = QAction("&Open output folder", self)
        open_output.triggered.connect(self.open_output_folder)
        file_menu.addAction(open_output)
        file_menu.addSeparator()

        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.setMenuRole(QAction.MenuRole.QuitRole)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        run_menu = menu_bar.addMenu("&Run")
        self._start_action = QAction("&Start crawl", self)
        self._start_action.setShortcut(QKeySequence("Ctrl+Return"))
        self._start_action.triggered.connect(self.start_crawl)
        run_menu.addAction(self._start_action)

        self._stop_action = QAction("S&top crawl", self)
        self._stop_action.setShortcut(QKeySequence("Ctrl+."))
        self._stop_action.triggered.connect(self.stop_crawl)
        run_menu.addAction(self._stop_action)
        run_menu.addSeparator()

        self._export_action = QAction("&Export…", self)
        self._export_action.setShortcut(QKeySequence.StandardKey.Save)
        self._export_action.setEnabled(False)
        self._export_action.triggered.connect(self.export_last_run)
        run_menu.addAction(self._export_action)

        help_menu = menu_bar.addMenu("&Help")
        legal = QAction("&Legal use", self)
        legal.triggered.connect(self.show_legal_use)
        help_menu.addAction(legal)

        about = QAction("&About", self)
        about.setMenuRole(QAction.MenuRole.AboutRole)
        about.triggered.connect(self.show_about)
        help_menu.addAction(about)

    # ----------------------------------------------------------------- slots

    @Slot(str)
    def show_status(self, message: str) -> None:
        """Put one line in the status bar (SPEC 7.1)."""
        status = self.statusBar()
        if status is not None:
            status.showMessage(message)

    @Slot()
    def show_settings(self) -> None:
        """Bring the Settings pane forward."""
        self._tabs.setCurrentWidget(self._settings_pane)

    @Slot()
    def show_crawl(self) -> None:
        """Bring the Crawl pane forward."""
        self._tabs.setCurrentWidget(self._crawl_pane)

    @Slot()
    def start_crawl(self) -> None:
        """Start a crawl from the menu, under exactly the button's preconditions."""
        self.show_crawl()
        self._crawl_pane.start()

    @Slot()
    def stop_crawl(self) -> None:
        """Stop a running crawl from the menu."""
        self._crawl_pane.stop()

    @Slot(object)
    def _on_run_finished(self, report: SiteReport) -> None:
        self._export_action.setEnabled(True)
        self.show_status(report_summary(report))
        self._runs_pane.refresh()

    @Slot()
    def export_last_run(self) -> None:
        """Open the export dialog for the run that just finished."""
        report = self._crawl_pane.last_report()
        if report is None:
            self.show_status("Nothing to export yet: no run has finished.")
            return
        dialog = ExportDialog(
            self._export_job_for_report(report), self._default_selection, parent=self
        )
        dialog.exec()
        self._runs_pane.refresh()

    @Slot()
    def open_output_folder(self) -> None:
        """Open the directory runs are written into."""
        if not open_path(self._output_directory):
            self.show_status(f"Could not open {self._output_directory}")

    @Slot()
    def show_about(self) -> None:
        """Show the About dialog, which carries the LGPLv3 notice (FR-19)."""
        AboutDialog(self._tool_name, self._version, self._licenses_path, self).exec()

    @Slot()
    def show_legal_use(self) -> None:
        """Open the README, whose Legal use section states the operator's duties."""
        if not open_path(self._readme_path):
            self.show_status(f"Could not open {self._readme_path}")

    @Slot(object)
    def show_crash(self, failure: BaseException) -> None:
        """Show the one modal the operator did not ask for (SPEC 7.5, tier 3)."""
        CrashDialog(failure, self).exec()

    @Slot(object)
    def _on_config_saved(self, config: AppConfig) -> None:
        self._crawl_pane.set_identity(config.contact_email, self._user_agent_for(config))

    # ------------------------------------------------------------- geometry

    def restore_layout(self) -> None:
        """Restore window geometry, splitter position and column widths."""
        geometry = self._settings.value(GEOMETRY_KEY)
        if isinstance(geometry, QByteArray):
            self.restoreGeometry(geometry)
        state = self._settings.value(STATE_KEY)
        if isinstance(state, QByteArray):
            self.restoreState(state)
        splitter_state = self._settings.value(SPLITTER_KEY)
        if isinstance(splitter_state, QByteArray):
            self._crawl_pane.splitter().restoreState(splitter_state)

    @Slot()
    def shutdown_crawl(self) -> None:
        """Cancel and join the crawl thread. Connected to the application's quit.

        ``QThread.terminate`` is never called: a run that is stopped at quit must
        leave the same consistent, exportable state as one stopped by the button.
        """
        self._crawl_controller.shutdown()

    @Slot()
    def save_layout(self) -> None:
        """Persist window geometry, splitter position and column widths."""
        self._settings.setValue(GEOMETRY_KEY, self.saveGeometry())
        self._settings.setValue(STATE_KEY, self.saveState())
        self._settings.setValue(SPLITTER_KEY, self._crawl_pane.splitter().saveState())
