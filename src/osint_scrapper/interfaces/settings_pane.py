"""The Settings pane (SPEC 7.7).

Every product setting lives in ``osint-scrapper.toml`` and is edited here.
``QSettings`` holds nothing but window geometry and column widths, which is the
whole of the two-store split and is deliberate: those are facts about this
machine's window manager, not about the product.

Two things this pane must say out loud, because the application refuses to work
without them: why a contact email is mandatory (FR-20), and which value from the
configuration file was clamped to a bound and what it became (AC-UI-6).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from osint_scrapper.application.errors import ConfigurationError
from osint_scrapper.domain.target import PurposeCategory
from osint_scrapper.infrastructure.config import AppConfig
from osint_scrapper.interfaces.crawl_pane import BannerLabel, tint
from osint_scrapper.interfaces.view_models import (
    PURPOSE_LABELS,
    Banner,
    ExportSelection,
    Severity,
)
from osint_scrapper.interfaces.worker import run_in_background

logger = logging.getLogger(__name__)

CONTACT_EMAIL_EXPLANATION = (
    "Required. The User-Agent this tool sends carries this address so that a site "
    "owner who wants the crawling to stop has someone to write to. Without it the "
    "Start button stays disabled — there is no flag, key or environment variable "
    "that removes this requirement."
)


class SettingsPane(QWidget):
    """Edits the configuration file and reports exactly which file it wrote."""

    config_saved = Signal(object)
    """``AppConfig`` — the saved configuration, for the panes that depend on it."""

    status_message = Signal(str)

    def __init__(
        self,
        config: AppConfig,
        save_config: Callable[[AppConfig, Path], Path],
        writable_config_path: Callable[[], Path],
        user_agent_for: Callable[[str, str], str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._save_config = save_config
        self._writable_config_path = writable_config_path
        self._user_agent_for = user_agent_for

        self._build_widgets()
        self._build_layout()
        self._apply(config)
        self._connect()
        self.refresh_user_agent()

    def _build_widgets(self) -> None:
        self._contact_email = QLineEdit(self)
        self._contact_email.setPlaceholderText("you@example.org")
        self._project_url = QLineEdit(self)
        self._user_agent = QLineEdit(self)
        self._user_agent.setReadOnly(True)
        self._user_agent.setToolTip(
            "Computed, never typed. Browser impersonation is refused by the builder, "
            "and no setting can override it."
        )

        self._output_directory = QLineEdit(self)
        self._browse_output = QPushButton("Browse…", self)
        self._retention_days = QSpinBox(self)
        self._retention_days.setRange(1, 3650)
        self._retention_days.setSuffix(" days")
        self._retention_days.setToolTip(
            "Declared in every export and shown in the Runs pane. Nothing is ever "
            "deleted automatically."
        )

        self._interval = QDoubleSpinBox(self)
        self._interval.setRange(0.5, 60.0)
        self._interval.setSingleStep(0.5)
        self._interval.setDecimals(1)
        self._interval.setSuffix(" s")
        self._timeout = QDoubleSpinBox(self)
        self._timeout.setRange(1.0, 120.0)
        self._timeout.setSuffix(" s")
        self._max_retries = QSpinBox(self)
        self._max_retries.setRange(0, 10)
        self._concurrency = QSpinBox(self)
        self._concurrency.setRange(1, 4)

        self._max_pages = QSpinBox(self)
        self._max_pages.setRange(1, 2000)
        self._max_depth = QSpinBox(self)
        self._max_depth.setRange(0, 10)
        self._include_subdomains = QCheckBox("Include subdomains by default", self)
        self._follow_sitemap = QCheckBox("Follow sitemap by default", self)
        self._phone_region = QLineEdit(self)
        self._phone_region.setMaxLength(2)

        self._purpose = QComboBox(self)
        for category in PurposeCategory:
            self._purpose.addItem(PURPOSE_LABELS[category], category)
        self._purpose_note = QLineEdit(self)

        self._csv = QCheckBox("CSV", self)
        self._xlsx = QCheckBox("XLSX", self)
        self._jsonl = QCheckBox("JSONL", self)
        self._markdown = QCheckBox("Markdown", self)

        self._clamps = QLabel(self)
        self._clamps.setWordWrap(True)
        self._banner = BannerLabel(self)
        self._save_button = QPushButton("&Save settings", self)
        self._written_to = QLabel(self)
        self._written_to.setWordWrap(True)

    def _build_layout(self) -> None:
        identity = QGroupBox("Identity — who the site owner sees", self)
        identity_form = QFormLayout(identity)
        explanation = QLabel(CONTACT_EMAIL_EXPLANATION, identity)
        explanation.setWordWrap(True)
        identity_form.addRow("Contact e&mail", self._contact_email)
        identity_form.addRow("", explanation)
        identity_form.addRow("&Project URL", self._project_url)
        identity_form.addRow("User-Agent", self._user_agent)

        output = QGroupBox("Output", self)
        output_form = QFormLayout(output)
        directory_row = QHBoxLayout()
        directory_row.addWidget(self._output_directory, 1)
        directory_row.addWidget(self._browse_output)
        output_form.addRow("&Output directory", directory_row)
        output_form.addRow("&Retention", self._retention_days)
        formats_row = QHBoxLayout()
        formats_row.addWidget(QLabel("JSON (always)", output))
        for box in (self._csv, self._xlsx, self._jsonl, self._markdown):
            formats_row.addWidget(box)
        formats_row.addStretch(1)
        output_form.addRow("Default formats", formats_row)

        network = QGroupBox("Network", self)
        network_form = QFormLayout(network)
        network_form.addRow("Request &interval", self._interval)
        network_form.addRow("&Timeout", self._timeout)
        network_form.addRow("Max retries", self._max_retries)
        network_form.addRow("Concurrent requests", self._concurrency)

        crawl = QGroupBox("Crawl defaults", self)
        crawl_form = QFormLayout(crawl)
        crawl_form.addRow("Max pages", self._max_pages)
        crawl_form.addRow("Max depth", self._max_depth)
        crawl_form.addRow("Phone region", self._phone_region)
        crawl_form.addRow("", self._include_subdomains)
        crawl_form.addRow("", self._follow_sitemap)
        crawl_form.addRow("Default purpose", self._purpose)
        crawl_form.addRow("Default note", self._purpose_note)

        inner = QWidget(self)
        inner_layout = QVBoxLayout(inner)
        inner_layout.addWidget(self._banner)
        inner_layout.addWidget(self._clamps)
        inner_layout.addWidget(identity)
        inner_layout.addWidget(output)
        inner_layout.addWidget(network)
        inner_layout.addWidget(crawl)
        inner_layout.addStretch(1)

        area = QScrollArea(self)
        area.setWidgetResizable(True)
        area.setWidget(inner)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self._save_button)

        layout = QVBoxLayout(self)
        layout.addWidget(area, 1)
        layout.addWidget(self._written_to)
        layout.addLayout(buttons)

    def _apply(self, config: AppConfig) -> None:
        self._contact_email.setText(config.contact_email or "")
        self._project_url.setText(config.project_url)
        self._output_directory.setText(str(config.output_directory))
        self._retention_days.setValue(config.retention_days)
        self._interval.setValue(config.request_interval_seconds)
        self._timeout.setValue(config.timeout_seconds)
        self._max_retries.setValue(config.max_retries)
        self._concurrency.setValue(config.concurrent_requests)
        self._max_pages.setValue(config.max_pages)
        self._max_depth.setValue(config.max_depth)
        self._include_subdomains.setChecked(config.include_subdomains)
        self._follow_sitemap.setChecked(config.follow_sitemap)
        self._phone_region.setText(config.phone_region)
        self._purpose.setCurrentIndex(max(0, self._purpose.findData(config.purpose_category)))
        self._purpose_note.setText(config.purpose_note)
        selection = ExportSelection.from_names(config.formats)
        self._csv.setChecked(selection.csv)
        self._xlsx.setChecked(selection.xlsx)
        self._jsonl.setChecked(selection.jsonl)
        self._markdown.setChecked(selection.markdown)
        self._render_clamps(config)

    def _render_clamps(self, config: AppConfig) -> None:
        if not config.clamps:
            self._clamps.setVisible(False)
            return
        lines = [
            "Values in the configuration file were outside their permitted bounds "
            "and were clamped:"
        ]
        lines.extend(
            f"  {clamp.key}: {clamp.requested} → {clamp.applied}" for clamp in config.clamps
        )
        self._clamps.setText("\n".join(lines))
        tint(self._clamps, Severity.WARNING, self)
        self._clamps.setVisible(True)

    def _connect(self) -> None:
        self._contact_email.textChanged.connect(self.refresh_user_agent)
        self._project_url.textChanged.connect(self.refresh_user_agent)
        self._browse_output.clicked.connect(self._choose_output_directory)
        self._save_button.clicked.connect(self.save)

    # ------------------------------------------------------------------ state

    def current_config(self) -> AppConfig:
        """Read every control back into a configuration object."""
        return replace(
            self._config,
            contact_email=self._contact_email.text().strip() or None,
            project_url=self._project_url.text().strip(),
            output_directory=Path(self._output_directory.text().strip() or "runs"),
            retention_days=self._retention_days.value(),
            request_interval_seconds=self._interval.value(),
            timeout_seconds=self._timeout.value(),
            max_retries=self._max_retries.value(),
            concurrent_requests=self._concurrency.value(),
            max_pages=self._max_pages.value(),
            max_depth=self._max_depth.value(),
            include_subdomains=self._include_subdomains.isChecked(),
            follow_sitemap=self._follow_sitemap.isChecked(),
            phone_region=self._phone_region.text().strip().upper() or "FR",
            purpose_category=PurposeCategory(self._purpose.currentData()),
            purpose_note=self._purpose_note.text().strip(),
            formats=ExportSelection(
                csv=self._csv.isChecked(),
                xlsx=self._xlsx.isChecked(),
                jsonl=self._jsonl.isChecked(),
                markdown=self._markdown.isChecked(),
            ).format_names(),
            clamps=(),
        )

    @Slot()
    def refresh_user_agent(self) -> None:
        """Recompute the read-only User-Agent preview from the identity fields."""
        contact = self._contact_email.text().strip()
        project = self._project_url.text().strip()
        if not contact:
            self._user_agent.setText("")
            self._user_agent.setPlaceholderText("Set a contact email to compute the User-Agent")
            return
        self._user_agent.setText(self._user_agent_for(project, contact))

    @Slot()
    def _choose_output_directory(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose an output directory", self._output_directory.text()
        )
        if chosen:
            self._output_directory.setText(chosen)

    @Slot()
    def save(self) -> None:
        """Validate, then write the configuration file off the GUI thread."""
        config = self.current_config()
        try:
            config.require_contact_email()
        except ConfigurationError as invalid:
            self._banner.show_banner(
                Banner(
                    Severity.ERROR,
                    "invalid_contact_email",
                    "Nothing was saved. The contact email must be a valid address, "
                    "because it goes out on every request.",
                    str(invalid),
                )
            )
            return

        self._banner.clear_banner()
        self._save_button.setEnabled(False)
        run_in_background(
            self,
            lambda: self._save_config(config, self._writable_config_path()),
            lambda path: self._on_saved(config, path),
            self._on_save_failed,
        )

    def _on_saved(self, config: AppConfig, path: Path) -> None:
        self._config = config
        self._save_button.setEnabled(True)
        self._written_to.setText(f"Saved to {path}")
        self.status_message.emit(f"Settings saved to {path}")
        self.config_saved.emit(config)

    @Slot(object)
    def _on_save_failed(self, failure: BaseException) -> None:
        self._save_button.setEnabled(True)
        self._banner.show_banner(
            Banner(
                Severity.ERROR,
                type(failure).__name__,
                "The configuration file could not be written. None of the candidate "
                "locations was writable.",
                str(failure),
            )
        )
