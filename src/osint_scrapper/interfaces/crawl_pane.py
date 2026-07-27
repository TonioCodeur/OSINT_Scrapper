"""The Crawl pane: the screen the operator spends the run looking at (SPEC 7.2, 7.3).

It holds no business rule. Every question it asks — is the target valid, may the
crawl start, what does this outcome mean in plain English — is answered by
:mod:`view_models`, and every answer is applied here to a widget.
"""

from __future__ import annotations

import logging
from html import escape
from typing import Final

from PySide6.QtCore import QAbstractItemModel, QRegularExpression, Qt, QTimer, Signal, Slot
from PySide6.QtGui import (
    QGuiApplication,
    QKeySequence,
    QPalette,
    QRegularExpressionValidator,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from osint_scrapper.domain.attributes import Finding
from osint_scrapper.domain.crawl import PageOutcome, PageStatus
from osint_scrapper.domain.errors import DomainError, SeedRefusedError
from osint_scrapper.domain.report import SiteReport
from osint_scrapper.domain.target import CrawlSettings, CrawlTarget, PurposeCategory
from osint_scrapper.interfaces.models import (
    FindingsTableModel,
    PageLogTableModel,
    PageStatusFilterProxy,
    SortedProxy,
    severity_color,
)
from osint_scrapper.interfaces.view_models import (
    FINDING_HEADERS,
    PAGE_HEADERS,
    PURPOSE_LABELS,
    Banner,
    CrawlFormState,
    CrawlProgressTracker,
    ProgressView,
    RunState,
    Severity,
    compliance_banner_text,
    outcome_banner,
    page_rows,
    rows_to_tsv,
    seed_refusal_banner,
    status_bar_text,
)
from osint_scrapper.interfaces.worker import CrawlController, CrawlRequest

logger = logging.getLogger(__name__)

ELAPSED_TICK_MILLISECONDS: Final = 500
ALL_STATUSES_LABEL: Final = "All statuses"


def tint(widget: QLabel, severity: Severity, reference: QWidget) -> None:
    """Colour ``widget``'s text by severity, or restore the theme's own colour.

    The colour comes from the live palette, so a light theme, a dark theme and a
    high-contrast theme each get a legible answer and none of them is hardcoded.
    """
    colour = severity_color(severity, reference.palette())
    palette = QPalette(reference.palette())
    if colour is not None:
        palette.setColor(QPalette.ColorRole.WindowText, colour)
    widget.setPalette(palette)


class BannerLabel(QFrame):
    """The run-level message strip of SPEC 7.5 tier 2.

    It is inline and never modal: the moment a run fails is the moment the
    operator most needs to read the page log, so nothing may cover it.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setVisible(False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        self._label = QLabel(self)
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._label)

    def show_banner(self, banner: Banner) -> None:
        """Display one message, styled by its severity.

        Every part is HTML-escaped. A banner detail can carry a URL or an error
        string that originated on a crawled page, and rich text is a rendering
        engine: nothing a third-party site published gets to reach it as markup.
        """
        detail = (
            f"<br><span style='font-family: monospace;'>{escape(banner.detail)}</span>"
            if banner.detail
            else ""
        )
        self._label.setText(
            f"<b>{escape(banner.title)}</b><br>{escape(banner.message)}{detail}"
        )
        tint(self._label, banner.severity, self)
        self.setVisible(True)

    def clear_banner(self) -> None:
        """Hide the strip. Called when a new run starts."""
        self._label.clear()
        self.setVisible(False)

    def text(self) -> str:
        """The message currently displayed, empty when the strip is hidden."""
        return self._label.text()


class CrawlPane(QWidget):
    """Target, purpose, limits, progress, findings and the page log."""

    state_changed = Signal(str)
    """The status-bar line, recomputed whenever the run state moves."""

    run_finished = Signal(object)
    """``SiteReport`` — a run ended and is now exportable."""

    crashed = Signal(object)
    """``BaseException`` — a defect that must become a modal (SPEC 7.5 tier 3)."""

    def __init__(
        self,
        controller: CrawlController,
        defaults: CrawlFormState,
        user_agent: str,
        hard_floor_seconds: float,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._user_agent = user_agent
        self._hard_floor_seconds = hard_floor_seconds
        self._contact_email = defaults.contact_email
        self._retention_days = defaults.retention_days
        self._state = RunState.IDLE
        self._tracker = CrawlProgressTracker(defaults.max_pages)
        self._elapsed = QTimer(self)
        self._elapsed.setInterval(ELAPSED_TICK_MILLISECONDS)
        self._elapsed_seconds = 0.0
        self._last_report: SiteReport | None = None

        self._build_widgets()
        self._build_layout()
        self._apply_defaults(defaults)
        self._connect()
        self.refresh_state()

    # ------------------------------------------------------------------ build

    def _build_widgets(self) -> None:
        self._target_edit = QLineEdit(self)
        self._target_edit.setPlaceholderText("example.com   or   https://example.com/about")
        self._target_edit.setClearButtonEnabled(True)
        self._target_hint = QLabel(self)
        self._target_hint.setWordWrap(True)

        self._purpose_combo = QComboBox(self)
        for category in PurposeCategory:
            self._purpose_combo.addItem(PURPOSE_LABELS[category], category)
        self._purpose_note = QLineEdit(self)
        self._purpose_note.setPlaceholderText("Optional note — required for 'Other'")
        self._purpose_hint = QLabel(self)
        self._purpose_hint.setWordWrap(True)

        self._max_pages = QSpinBox(self)
        self._max_pages.setRange(1, 2000)
        self._max_pages.setToolTip("Hard ceiling: 2000 pages. Every content request counts.")
        self._max_depth = QSpinBox(self)
        self._max_depth.setRange(0, 10)
        self._max_depth.setToolTip("0 crawls the target page alone. Hard ceiling: 10.")
        self._interval = QDoubleSpinBox(self)
        self._interval.setRange(0.5, 60.0)
        self._interval.setSingleStep(0.5)
        self._interval.setDecimals(1)
        self._interval.setSuffix(" s")
        self._interval.setToolTip(
            "Minimum seconds between two requests. 0.5 s is a hard floor; a host's "
            "Crawl-delay always wins when it is larger."
        )
        self._concurrency = QSpinBox(self)
        self._concurrency.setRange(1, 4)
        self._concurrency.setToolTip(
            "Requests in flight. The rate limiter still governs throughput, so this "
            "hides latency and never increases the load on the site."
        )

        self._include_subdomains = QCheckBox("Include subdomains (down, never up)", self)
        self._include_subdomains.setToolTip(
            "On: a target of example.com also reaches blog.example.com. Scope never "
            "widens upwards: a target of docs.example.com never reaches example.com."
        )
        self._follow_sitemap = QCheckBox("Follow sitemap", self)
        self._follow_sitemap.setToolTip(
            "Read Sitemap: directives from robots.txt, and /sitemap.xml when it declares none."
        )
        self._phone_region = QComboBox(self)
        self._phone_region.setEditable(True)
        self._phone_region.addItems(
            ["FR", "BE", "CH", "LU", "DE", "ES", "IT", "GB", "IE", "NL", "PT", "US", "CA"]
        )
        self._phone_region.setToolTip("ISO 3166-1 alpha-2 region libphonenumber parses against.")
        line_edit = self._phone_region.lineEdit()
        if line_edit is not None:
            line_edit.setValidator(
                QRegularExpressionValidator(QRegularExpression("[A-Za-z]{2}"), self)
            )
            line_edit.setMaxLength(2)

        self._start_button = QPushButton("Start crawl", self)
        self._start_button.setDefault(True)
        self._start_button.setMinimumWidth(140)

        self._banner = BannerLabel(self)

        self._progress_bar = QProgressBar(self)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setTextVisible(False)
        self._progress_label = QLabel(self)
        self._progress_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self._compliance_label = QLabel(self)
        self._compliance_label.setWordWrap(True)
        self._compliance_label.setObjectName("complianceBanner")
        self._compliance_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._compliance_label.setToolTip(
            "This line is always on screen while traffic is going out. It has no close button."
        )

        self._findings_model = FindingsTableModel(self)
        self._findings_proxy = SortedProxy(self)
        self._findings_proxy.setSourceModel(self._findings_model)
        self._findings_view = build_table_view(self._findings_proxy)
        self._findings_view.setToolTip("Ctrl+C copies the selected rows as TSV.")

        self._pages_model = PageLogTableModel(self)
        self._pages_model.set_palette(self.palette())
        self._pages_proxy = PageStatusFilterProxy(self)
        self._pages_proxy.setSourceModel(self._pages_model)
        self._pages_view = build_table_view(self._pages_proxy)

        self._status_filter = QComboBox(self)
        self._status_filter.addItem(ALL_STATUSES_LABEL, None)
        for status in PageStatus:
            self._status_filter.addItem(str(status), status)

    def _build_layout(self) -> None:
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.addRow("&Target", self._target_edit)
        form.addRow("", self._target_hint)
        form.addRow("&Purpose", self._purpose_combo)
        form.addRow("&Note", self._purpose_note)
        form.addRow("", self._purpose_hint)

        limits = QGroupBox("Crawl limits", self)
        limits.setToolTip(
            "These are compliance controls, not advanced options: they bound exactly "
            "how much traffic this run sends."
        )
        grid = QGridLayout(limits)
        grid.addWidget(QLabel("Max pages", limits), 0, 0)
        grid.addWidget(self._max_pages, 0, 1)
        grid.addWidget(QLabel("Max depth", limits), 0, 2)
        grid.addWidget(self._max_depth, 0, 3)
        grid.addWidget(QLabel("Request interval", limits), 1, 0)
        grid.addWidget(self._interval, 1, 1)
        grid.addWidget(QLabel("Concurrent requests", limits), 1, 2)
        grid.addWidget(self._concurrency, 1, 3)
        grid.addWidget(QLabel("Phone region", limits), 2, 0)
        grid.addWidget(self._phone_region, 2, 1)
        grid.addWidget(self._include_subdomains, 3, 0, 1, 4)
        grid.addWidget(self._follow_sitemap, 4, 0, 1, 4)
        grid.setColumnStretch(4, 1)

        start_row = QHBoxLayout()
        start_row.addWidget(self._progress_bar, 1)
        start_row.addWidget(self._start_button)

        header = QVBoxLayout()
        header.addLayout(form)
        header.addWidget(limits)
        header.addLayout(start_row)
        header.addWidget(self._progress_label)
        header.addWidget(self._banner)

        findings_box = QGroupBox("Findings", self)
        findings_layout = QVBoxLayout(findings_box)
        findings_layout.setContentsMargins(6, 6, 6, 6)
        findings_layout.addWidget(self._findings_view)

        log_box = QGroupBox("Page log", self)
        log_box.setToolTip(
            "Every URL the crawl considered, with the machine-readable status it "
            "ended in.\n"
            "A page reached through a redirect is listed once, at the URL it "
            "finally lives at — the URL that redirected does not appear.\n"
            "The exception is off_scope_redirect, listed at the URL that "
            "redirected, because its target was never fetched."
        )
        log_layout = QVBoxLayout(log_box)
        log_layout.setContentsMargins(6, 6, 6, 6)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter", log_box))
        filter_row.addWidget(self._status_filter)
        filter_row.addStretch(1)
        log_layout.addLayout(filter_row)
        log_layout.addWidget(self._compliance_label)
        log_layout.addWidget(self._pages_view)

        splitter = QSplitter(Qt.Orientation.Vertical, self)
        splitter.setObjectName("crawlSplitter")
        splitter.addWidget(findings_box)
        splitter.addWidget(log_box)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        self._splitter = splitter

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(splitter, 1)

        self.setTabOrder(self._target_edit, self._purpose_combo)
        self.setTabOrder(self._purpose_combo, self._purpose_note)
        self.setTabOrder(self._purpose_note, self._max_pages)
        self.setTabOrder(self._max_pages, self._max_depth)
        self.setTabOrder(self._max_depth, self._interval)
        self.setTabOrder(self._interval, self._concurrency)
        self.setTabOrder(self._concurrency, self._phone_region)
        self.setTabOrder(self._phone_region, self._include_subdomains)
        self.setTabOrder(self._include_subdomains, self._follow_sitemap)
        self.setTabOrder(self._follow_sitemap, self._start_button)

    def _apply_defaults(self, defaults: CrawlFormState) -> None:
        self._target_edit.setText(defaults.target_text)
        index = self._purpose_combo.findData(defaults.purpose_category)
        self._purpose_combo.setCurrentIndex(max(0, index))
        self._purpose_note.setText(defaults.purpose_note)
        self._max_pages.setValue(defaults.max_pages)
        self._max_depth.setValue(defaults.max_depth)
        self._interval.setValue(defaults.request_interval_seconds)
        self._concurrency.setValue(defaults.concurrent_requests)
        self._include_subdomains.setChecked(defaults.include_subdomains)
        self._follow_sitemap.setChecked(defaults.follow_sitemap)
        self._phone_region.setCurrentText(defaults.phone_region)
        self._compliance_label.setText(
            compliance_banner_text(
                self._user_agent,
                defaults.request_interval_seconds,
                self._hard_floor_seconds,
                "no target yet",
                defaults.include_subdomains,
            )
        )

    def _connect(self) -> None:
        self._target_edit.textChanged.connect(self.refresh_state)
        self._purpose_combo.currentIndexChanged.connect(self.refresh_state)
        self._purpose_note.textChanged.connect(self.refresh_state)
        self._include_subdomains.toggled.connect(self.refresh_state)
        self._interval.valueChanged.connect(self.refresh_state)
        self._max_pages.valueChanged.connect(self.refresh_state)
        self._start_button.clicked.connect(self.toggle_run)
        self._status_filter.currentIndexChanged.connect(self._apply_status_filter)
        self._elapsed.timeout.connect(self._tick)

        self._controller.run_started.connect(self._on_crawl_started)
        self._controller.pages_batched.connect(self._on_pages)
        self._controller.findings_snapshot.connect(self._on_findings)
        self._controller.frontier_sized.connect(self._on_frontier)
        self._controller.finished.connect(self._on_finished)
        self._controller.refused.connect(self._on_refused)
        self._controller.failed.connect(self._on_failed)

        copy = QShortcut(QKeySequence(QKeySequence.StandardKey.Copy), self._findings_view)
        copy.activated.connect(self._copy_findings)
        copy_pages = QShortcut(QKeySequence(QKeySequence.StandardKey.Copy), self._pages_view)
        copy_pages.activated.connect(self._copy_pages)

    # ------------------------------------------------------------------ state

    def form_state(self) -> CrawlFormState:
        """Read every control into the plain state object the view model uses."""
        return CrawlFormState(
            target_text=self._target_edit.text(),
            purpose_category=PurposeCategory(self._purpose_combo.currentData()),
            purpose_note=self._purpose_note.text(),
            max_pages=self._max_pages.value(),
            max_depth=self._max_depth.value(),
            request_interval_seconds=self._interval.value(),
            concurrent_requests=self._concurrency.value(),
            include_subdomains=self._include_subdomains.isChecked(),
            follow_sitemap=self._follow_sitemap.isChecked(),
            phone_region=self._phone_region.currentText(),
            retention_days=self._retention_days,
            contact_email=self._contact_email,
        )

    def set_identity(self, contact_email: str | None, user_agent: str) -> None:
        """Adopt an identity saved in Settings, unblocking Start (FR-20).

        The User-Agent shown in the compliance banner is recomputed with it, so
        the banner never displays an address the tool would no longer send.
        """
        self._contact_email = contact_email
        self._user_agent = user_agent
        self.refresh_state()

    def last_report(self) -> SiteReport | None:
        """The most recent finished run, or ``None`` if none has finished."""
        return self._last_report

    def splitter(self) -> QSplitter:
        """The findings/log splitter, whose position the window persists."""
        return self._splitter

    def compliance_text(self) -> str:
        """The pinned compliance line. It has no close button and never hides."""
        return self._compliance_label.text()

    def banner_text(self) -> str:
        """The run-level banner's current message, empty when there is none."""
        return self._banner.text()

    def findings_count(self) -> int:
        """How many distinct findings the table currently holds."""
        return self._findings_model.rowCount()

    def logged_pages(self) -> int:
        """How many rows the page log currently holds."""
        return self._pages_model.rowCount()

    def run_state(self) -> RunState:
        """Where the run state machine currently sits."""
        return self._state

    def set_target_text(self, text: str) -> None:
        """Set the target box, as typing into it would."""
        self._target_edit.setText(text)

    def set_purpose(self, category: PurposeCategory, note: str = "") -> None:
        """Set the purpose controls, as choosing and typing would."""
        self._purpose_combo.setCurrentIndex(max(0, self._purpose_combo.findData(category)))
        self._purpose_note.setText(note)

    def start_button(self) -> QPushButton:
        """The primary button, so a test can press exactly what an operator presses."""
        return self._start_button

    def status_filter(self) -> QComboBox:
        """The page-log status filter."""
        return self._status_filter

    @Slot()
    def refresh_state(self) -> None:
        """Recompute every derived label and the Start button, from one state object."""
        state = self.form_state()
        hint = state.target_hint()
        self._target_hint.setText(hint.message)
        tint(self._target_hint, hint.severity, self)
        problem = state.purpose_problem()
        self._purpose_hint.setText(problem or "")
        tint(self._purpose_hint, Severity.WARNING, self)
        self._purpose_hint.setVisible(problem is not None)

        button = state.start_button_state(self._state)
        self._start_button.setEnabled(button.enabled)
        self._start_button.setText(button.text)
        self._start_button.setToolTip(button.tooltip)

        editable = not self._state.is_busy
        for widget in self._editable_widgets():
            widget.setEnabled(editable)
        self.state_changed.emit(self._status_text())

    def _editable_widgets(self) -> tuple[QWidget, ...]:
        return (
            self._target_edit,
            self._purpose_combo,
            self._purpose_note,
            self._max_pages,
            self._max_depth,
            self._interval,
            self._concurrency,
            self._include_subdomains,
            self._follow_sitemap,
            self._phone_region,
        )

    def _status_text(self) -> str:
        return status_bar_text(
            self._state,
            self._tracker.view(self._elapsed_seconds),
            self._findings_model.rowCount(),
        )

    # ------------------------------------------------------------------- run

    @Slot()
    def toggle_run(self) -> None:
        """Start a crawl, or stop the one that is running. The button's own slot."""
        if self._state.is_busy:
            self.stop()
        else:
            self.start()

    @Slot()
    def start(self) -> None:
        """Start a crawl if every precondition holds. Does nothing otherwise."""
        if self._state.is_busy:
            return
        if not self.form_state().start_button_state(self._state).enabled:
            return
        self._start()

    @Slot()
    def stop(self) -> None:
        """Ask a running crawl to stop. Cooperative: nothing is killed mid-write."""
        if not self._state.is_busy or self._state is RunState.STOPPING:
            return
        self._state = RunState.STOPPING
        self._controller.stop()
        self.refresh_state()

    def _start(self) -> None:
        state = self.form_state()
        try:
            request = CrawlRequest(
                target=state.to_target(),
                settings=state.to_settings(),
                purpose=state.to_purpose(),
            )
        except DomainError as invalid:
            self._banner.show_banner(
                Banner(
                    Severity.ERROR,
                    "invalid_request",
                    "The crawl was refused before any request was made.",
                    str(invalid),
                )
            )
            return

        self._banner.clear_banner()
        self._findings_model.clear()
        self._pages_model.clear()
        self._tracker = CrawlProgressTracker(request.settings.max_pages)
        self._elapsed_seconds = 0.0
        self._last_report = None
        self._state = RunState.STARTING
        self.refresh_state()
        self._controller.start(request)
        self._elapsed.start()

    @Slot(object, object)
    def _on_crawl_started(self, target: CrawlTarget, settings: CrawlSettings) -> None:
        self._state = RunState.RUNNING
        self._compliance_label.setText(
            compliance_banner_text(
                self._user_agent,
                settings.request_interval_seconds,
                self._hard_floor_seconds,
                target.scope_host,
                target.include_subdomains,
            )
        )
        self._render_progress()
        self.refresh_state()

    @Slot(object)
    def _on_pages(self, batch: tuple[PageOutcome, ...]) -> None:
        self._tracker.record(batch)
        self._pages_model.add_rows(page_rows(batch, self._pages_model.rowCount() + 1))
        self._render_progress()

    @Slot(object)
    def _on_findings(self, findings: tuple[Finding, ...]) -> None:
        self._findings_model.apply_findings(findings)
        self.state_changed.emit(self._status_text())

    @Slot(int, int)
    def _on_frontier(self, queued: int, deepest_depth: int) -> None:
        del deepest_depth
        self._tracker.set_queued(queued)
        self._render_progress()

    @Slot(object)
    def _on_finished(self, report: SiteReport) -> None:
        self._elapsed.stop()
        self._state = RunState.FINISHED
        self._last_report = report
        self._banner.show_banner(outcome_banner(report.outcome, report.outcome_detail))
        self._render_progress()
        self.refresh_state()
        self.run_finished.emit(report)

    @Slot(object)
    def _on_refused(self, refusal: SeedRefusedError) -> None:
        self._elapsed.stop()
        self._state = RunState.IDLE
        self._banner.show_banner(
            seed_refusal_banner(
                refusal.reason,
                f"{refusal.url} — {refusal.detail}"
                + (f" (see {refusal.robots_url})" if refusal.robots_url else ""),
            )
        )
        self.refresh_state()

    @Slot(object)
    def _on_failed(self, failure: BaseException) -> None:
        self._elapsed.stop()
        self._state = RunState.FINISHED
        self._banner.show_banner(
            Banner(
                Severity.ERROR,
                "failed",
                "The run failed with an unexpected error. Whatever was collected before "
                "the failure is still exportable.",
                f"{type(failure).__name__}: {failure}",
            )
        )
        self.refresh_state()
        self.crashed.emit(failure)

    @Slot()
    def _tick(self) -> None:
        self._elapsed_seconds += ELAPSED_TICK_MILLISECONDS / 1000.0
        self._render_progress()

    def _render_progress(self) -> None:
        view = self._tracker.view(self._elapsed_seconds)
        self._progress_label.setText(view.text())
        self._progress_bar.setValue(view.percent())
        self.state_changed.emit(self._status_text())

    def progress_view(self) -> ProgressView:
        """The current progress numbers, exposed for tests and the status bar."""
        return self._tracker.view(self._elapsed_seconds)

    # ---------------------------------------------------------------- tables

    @Slot()
    def _apply_status_filter(self) -> None:
        self._pages_proxy.set_status(self._status_filter.currentData())

    @Slot()
    def _copy_findings(self) -> None:
        self._copy(self._findings_view, FINDING_HEADERS)

    @Slot()
    def _copy_pages(self) -> None:
        self._copy(self._pages_view, PAGE_HEADERS)

    def _copy(self, view: QTableView, headers: tuple[str, ...]) -> None:
        model = view.model()
        rows = sorted({index.row() for index in view.selectionModel().selectedIndexes()})
        if not rows:
            return
        payload = rows_to_tsv(
            headers,
            [
                [
                    str(model.data(model.index(row, column), Qt.ItemDataRole.DisplayRole) or "")
                    for column in range(model.columnCount())
                ]
                for row in rows
            ],
        )
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(payload)


def build_table_view(model: QAbstractItemModel) -> QTableView:
    """A table configured the same way everywhere: sortable, readable, keyboard-usable."""
    view = QTableView()
    view.setModel(model)
    view.setSortingEnabled(True)
    view.setAlternatingRowColors(True)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.setWordWrap(False)
    view.setTextElideMode(Qt.TextElideMode.ElideRight)
    view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    vertical = view.verticalHeader()
    if vertical is not None:
        vertical.setVisible(False)
        vertical.setDefaultSectionSize(22)
    horizontal = view.horizontalHeader()
    if horizontal is not None:
        horizontal.setStretchLastSection(True)
        horizontal.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        horizontal.setHighlightSections(False)
    return view
