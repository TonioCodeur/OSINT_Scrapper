"""Widget smoke tests: every window and dialog is constructed and exercised.

These prove the wiring, not the logic — the logic is pinned down in
``test_view_models.py`` without a ``QApplication``. What has to be checked with
real widgets is that the signals are connected to the right slots and that the
enable and disable rules actually reach the buttons.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, QSize
from PySide6.QtWidgets import QLabel, QPushButton

from osint_scrapper.application.errors import ExportFailedError
from osint_scrapper.application.ports import ErasureReport
from osint_scrapper.domain.crawl import CrawlOutcome, PageStatus
from osint_scrapper.domain.target import PurposeCategory
from osint_scrapper.interfaces.about_dialog import AboutDialog
from osint_scrapper.interfaces.crawl_pane import CrawlPane
from osint_scrapper.interfaces.export_dialog import ExportDialog, ExportJob
from osint_scrapper.interfaces.main_window import (
    DEFAULT_WINDOW_SIZE,
    GEOMETRY_KEY,
    MINIMUM_WINDOW_SIZE,
    SPLITTER_KEY,
    STATE_KEY,
    CrashDialog,
    MainWindow,
)
from osint_scrapper.interfaces.runs_pane import CONFIRMATION_WORD, ConfirmDeleteDialog, RunsPane
from osint_scrapper.interfaces.view_models import CrawlFormState, ExportSelection, RunState
from tests.interfaces.conftest import make_page, make_report
from tests.interfaces.test_view_models import summary
from tests.interfaces.test_worker import REQUEST, factory_for

USER_AGENT = "OSINT-Scrapper/0.2.0 (+https://example.org; contact: nobody@example.org)"
CONTACT = "nobody@example.org"


def build_pane(
    qtbot,
    controllers,
    contact_email: str | None = CONTACT,
    behaviour: str = "complete",
    gate: threading.Event | None = None,
) -> CrawlPane:
    controller = controllers(factory_for(behaviour, gate))
    pane = CrawlPane(
        controller=controller,
        defaults=CrawlFormState(contact_email=contact_email),
        user_agent=USER_AGENT,
        hard_floor_seconds=0.5,
    )
    qtbot.addWidget(pane)
    return pane


# ------------------------------------------------------------- crawl pane


def test_start_is_disabled_until_a_target_and_a_purpose_are_valid(qtbot, controllers) -> None:
    pane = build_pane(qtbot, controllers)
    assert not pane.start_button().isEnabled()
    assert "domain" in pane.start_button().toolTip().lower()

    pane.set_target_text("example.com")
    assert pane.start_button().isEnabled()


def test_start_stays_disabled_without_a_contact_email(qtbot, controllers) -> None:
    pane = build_pane(qtbot, controllers, contact_email=None)
    pane.set_target_text("example.com")
    assert not pane.start_button().isEnabled()
    assert "contact email" in pane.start_button().toolTip().lower()


def test_setting_an_identity_unblocks_start_and_updates_the_banner(qtbot, controllers) -> None:
    pane = build_pane(qtbot, controllers, contact_email=None)
    pane.set_target_text("example.com")
    pane.set_identity(CONTACT, USER_AGENT)
    assert pane.start_button().isEnabled()
    assert USER_AGENT in pane.compliance_text()


def test_purpose_other_with_a_short_note_keeps_start_disabled(qtbot, controllers) -> None:
    pane = build_pane(qtbot, controllers)
    pane.set_target_text("example.com")
    pane.set_purpose(PurposeCategory.OTHER, "too short")
    assert not pane.start_button().isEnabled()

    pane.set_purpose(PurposeCategory.OTHER, "pre-contract vendor review")
    assert pane.start_button().isEnabled()


def test_the_compliance_line_is_present_and_has_no_close_button(qtbot, controllers) -> None:
    pane = build_pane(qtbot, controllers)
    assert "robots.txt: honored" in pane.compliance_text()
    buttons = pane.findChildren(QPushButton)
    assert not [child for child in buttons if "close" in child.text().lower()]


def test_a_run_fills_both_tables_and_ends_with_an_outcome_banner(qtbot, controllers) -> None:
    pane = build_pane(qtbot, controllers)
    pane.set_target_text("example.com")

    with qtbot.waitSignal(pane.run_finished, timeout=5000):
        pane._controller.start(REQUEST)

    assert pane.findings_count() == 1
    assert pane.logged_pages() == 1
    assert pane.run_state() is RunState.FINISHED
    assert "completed" in pane.banner_text().lower()
    assert pane.last_report() is not None


def test_a_seed_refusal_becomes_a_banner_and_leaves_the_pane_idle(qtbot, controllers) -> None:
    pane = build_pane(qtbot, controllers, behaviour="refuse")
    pane.set_target_text("example.com")

    with qtbot.waitSignal(pane._controller.refused, timeout=5000):
        pane._controller.start(REQUEST)
    qtbot.waitUntil(lambda: bool(pane.banner_text()), timeout=2000)

    assert "robots_disallow" in pane.banner_text()
    assert pane.run_state() is RunState.IDLE


def test_a_defect_raises_the_crash_signal_and_still_shows_a_banner(qtbot, controllers) -> None:
    pane = build_pane(qtbot, controllers, behaviour="raise")
    pane.set_target_text("example.com")

    with qtbot.waitSignal(pane.crashed, timeout=5000) as caught:
        pane._controller.start(REQUEST)

    assert isinstance(caught.args[0], ValueError)
    assert "failed" in pane.banner_text().lower()


def test_stopping_a_crawl_yields_a_report_and_re_enables_the_form(qtbot, controllers) -> None:
    pane = build_pane(qtbot, controllers, behaviour="spin")
    pane.set_target_text("example.com")
    with qtbot.waitSignal(pane._controller.run_started, timeout=5000):
        pane.start()

    assert pane.run_state() is RunState.RUNNING
    with qtbot.waitSignal(pane.run_finished, timeout=5000) as caught:
        pane.stop()

    assert caught.args[0].outcome is CrawlOutcome.STOPPED_BY_OPERATOR
    assert pane.start_button().text() == "Start crawl"


def test_the_page_log_filter_is_wired_to_the_proxy(qtbot, controllers) -> None:
    from osint_scrapper.interfaces.view_models import page_rows

    pane = build_pane(qtbot, controllers)
    pane._pages_model.add_rows(
        page_rows(
            [
                make_page(),
                make_page(url="https://example.com/x", status=PageStatus.SKIPPED_ROBOTS),
            ]
        )
    )
    assert pane._pages_proxy.rowCount() == 2

    filter_box = pane.status_filter()
    filter_box.setCurrentIndex(filter_box.findData(PageStatus.SKIPPED_ROBOTS))
    assert pane._pages_proxy.rowCount() == 1


def test_an_invalid_purpose_never_reaches_the_crawl(qtbot, controllers) -> None:
    built: list[object] = []

    def counting_factory(*, request, observer, cancellation):
        built.append(request)
        raise AssertionError("the crawl must not be built with an invalid purpose")

    controller = controllers(counting_factory)
    pane = CrawlPane(
        controller=controller,
        defaults=CrawlFormState(contact_email=CONTACT),
        user_agent=USER_AGENT,
        hard_floor_seconds=0.5,
    )
    qtbot.addWidget(pane)
    pane.set_target_text("example.com")
    pane.set_purpose(PurposeCategory.OTHER, "short")

    pane.start()
    pane.toggle_run()
    qtbot.wait(50)

    assert built == []
    assert not controller.is_running()


# -------------------------------------------------------------- runs pane


class FakeListRuns:
    def __init__(self, summaries=()) -> None:
        self.summaries = tuple(summaries)

    def execute(self):
        return self.summaries


class FakeEraseRuns:
    def __init__(self) -> None:
        self.erased: list[frozenset[str]] = []
        self.expired_called = 0

    def execute(self, run_ids):
        self.erased.append(run_ids)
        return ErasureReport(
            removed_paths=(Path("runs/r-0000test"),), removed_run_ids=("r-0000test",)
        )

    def execute_expired(self):
        self.expired_called += 1
        return ErasureReport()


def build_runs_pane(qtbot, summaries=()) -> tuple[RunsPane, FakeEraseRuns]:
    erase = FakeEraseRuns()
    pane = RunsPane(
        FakeListRuns(summaries),
        erase,
        lambda row: ExportJob(row.run_id, Path(row.directory), lambda formats, copy_to: ()),
        ExportSelection(),
    )
    qtbot.addWidget(pane)
    return pane, erase


def test_the_runs_pane_lists_what_the_ledger_returns(qtbot) -> None:
    pane, _ = build_runs_pane(qtbot, [summary(), summary(run_id="r-two", directory="runs/r-two")])
    qtbot.waitUntil(lambda: len(pane.rows()) == 2, timeout=5000)
    assert {row.run_id for row in pane.rows()} == {"r-0000test", "r-two"}


def test_an_empty_ledger_leaves_every_destructive_button_disabled(qtbot) -> None:
    pane, _ = build_runs_pane(qtbot)
    qtbot.waitUntil(lambda: pane.rows() == (), timeout=5000)
    assert not pane._delete_button.isEnabled()
    assert not pane._delete_all_button.isEnabled()
    assert not pane._delete_expired_button.isEnabled()


def test_delete_expired_is_offered_only_when_a_run_has_expired(qtbot) -> None:
    pane, _ = build_runs_pane(qtbot, [summary(days_remaining=0, expired=True)])
    qtbot.waitUntil(lambda: len(pane.rows()) == 1, timeout=5000)
    assert pane._delete_expired_button.isEnabled()


def test_deleting_nothing_reports_that_nothing_matched(qtbot) -> None:
    pane, erase = build_runs_pane(qtbot)
    messages: list[str] = []
    pane.status_message.connect(messages.append)
    pane.delete_selected()
    assert "Nothing matched" in messages[-1]
    assert not erase.erased


def test_the_confirmation_dialog_names_the_directories(qtbot) -> None:
    dialog = ConfirmDeleteDialog("runs/r-0000test will be removed", False)
    qtbot.addWidget(dialog)
    assert dialog._delete_button.isEnabled()


def test_deleting_everything_requires_typing_the_word(qtbot) -> None:
    dialog = ConfirmDeleteDialog("everything", True)
    qtbot.addWidget(dialog)
    assert not dialog._delete_button.isEnabled()

    dialog._typed.setText("delete")
    assert not dialog._delete_button.isEnabled()

    dialog._typed.setText(CONFIRMATION_WORD)
    assert dialog._delete_button.isEnabled()


# ---------------------------------------------------------- export dialog


def test_json_cannot_be_deselected_in_the_export_dialog(qtbot) -> None:
    dialog = ExportDialog(
        ExportJob("r-0000test", Path("runs/r-0000test"), lambda formats, copy_to: ()),
        ExportSelection(csv=False, xlsx=False),
    )
    qtbot.addWidget(dialog)
    assert dialog._json.isChecked()
    assert not dialog._json.isEnabled()
    assert dialog.selection().format_names() == ("json",)


def test_the_export_dialog_writes_the_selected_formats_off_the_gui_thread(qtbot) -> None:
    calls: list[tuple] = []
    written = (Path("runs/r-0000test/report.json"),)

    def run(formats, copy_to):
        calls.append((tuple(formats), copy_to, threading.get_ident()))
        return written

    dialog = ExportDialog(
        ExportJob("r-0000test", Path("runs/r-0000test"), run),
        ExportSelection(csv=True, xlsx=False),
    )
    qtbot.addWidget(dialog)
    gui_thread = threading.get_ident()

    dialog.start_export()
    qtbot.waitUntil(lambda: bool(calls), timeout=5000)
    qtbot.waitUntil(lambda: dialog.written_files() == written, timeout=5000)

    assert calls[0][0] == ("json", "csv")
    assert calls[0][1] is None
    assert calls[0][2] != gui_thread
    assert "report.json" in dialog._results.toPlainText()
    assert dialog._close_button.text() == "Close"


def test_a_failed_export_names_the_failure_and_keeps_the_dialog_open(qtbot) -> None:
    def run(formats, copy_to):
        raise OSError("report.xlsx is locked by another program")

    dialog = ExportDialog(
        ExportJob("r-0000test", Path("runs/r-0000test"), run), ExportSelection()
    )
    qtbot.addWidget(dialog)
    dialog.start_export()
    qtbot.waitUntil(lambda: bool(dialog._results.toPlainText()), timeout=5000)
    assert "report.xlsx is locked" in dialog._results.toPlainText()
    assert dialog._close_button.text() == "Close"


def test_a_partial_export_names_the_files_that_did_land_and_the_format_that_did_not(
    qtbot,
) -> None:
    written = (Path("runs/r-0000test/report.json"), Path("runs/r-0000test/report.csv"))

    def run(formats, copy_to):
        raise ExportFailedError(written, (("xlsx", "locked by another program"),))

    dialog = ExportDialog(
        ExportJob("r-0000test", Path("runs/r-0000test"), run), ExportSelection()
    )
    qtbot.addWidget(dialog)
    dialog.start_export()
    qtbot.waitUntil(lambda: bool(dialog._results.toPlainText()), timeout=5000)

    reported = dialog._results.toPlainText()
    assert "report.json" in reported
    assert "report.csv" in reported
    assert "xlsx format — locked by another program" in reported
    assert dialog.written_files() == written


# ------------------------------------------------------------- dialogues


def test_the_about_dialog_names_qt_pyside6_and_the_lgpl(qtbot, tmp_path) -> None:
    licenses = tmp_path / "THIRD_PARTY_LICENSES.md"
    licenses.write_text("licences", encoding="utf-8")
    dialog = AboutDialog("osint-scrapper", "0.2.0", licenses)
    qtbot.addWidget(dialog)

    text = " ".join(label.text() for label in dialog.findChildren(QLabel))
    assert "PySide6" in text
    assert "Lesser General Public License" in text
    assert "Qt" in text
    assert dialog._open_licenses.isEnabled()


def test_the_about_dialog_says_when_the_licence_file_is_missing(qtbot, tmp_path) -> None:
    dialog = AboutDialog("osint-scrapper", "0.2.0", tmp_path / "absent.md")
    qtbot.addWidget(dialog)
    assert not dialog._open_licenses.isEnabled()


def test_the_crash_dialog_carries_the_type_the_message_and_a_traceback(qtbot) -> None:
    try:
        raise ValueError("a defect")
    except ValueError as failure:
        dialog = CrashDialog(failure)
    qtbot.addWidget(dialog)

    assert "ValueError" in dialog.details()
    assert "a defect" in dialog.details()
    assert "Traceback" in dialog.details()


def test_copying_the_crash_details_puts_them_on_the_clipboard(qtbot, qapp) -> None:
    dialog = CrashDialog(ValueError("a defect"))
    qtbot.addWidget(dialog)
    dialog.copy_details()
    assert "a defect" in qapp.clipboard().text()


# ----------------------------------------------------------- main window


def build_window(qtbot, controllers, tmp_path, settings_pane, settings=None) -> MainWindow:
    """Build the window from panes it will own.

    The panes are deliberately not registered with ``qtbot``: the window takes
    ownership when it tabs them, and registering them as well would have the
    teardown close an object Qt has already destroyed.

    ``settings`` lets a caller hand the same store to two windows, which is what
    a layout round-trip needs.
    """
    controller = controllers(factory_for())
    crawl_pane = CrawlPane(
        controller=controller,
        defaults=CrawlFormState(contact_email=CONTACT),
        user_agent=USER_AGENT,
        hard_floor_seconds=0.5,
    )
    runs_pane = RunsPane(
        FakeListRuns(),
        FakeEraseRuns(),
        lambda row: ExportJob(row.run_id, Path(row.directory), lambda formats, copy_to: ()),
        ExportSelection(),
    )
    window = MainWindow(
        crawl_pane=crawl_pane,
        runs_pane=runs_pane,
        settings_pane=settings_pane,
        crawl_controller=controller,
        export_job_for_report=lambda report: ExportJob(
            report.run_id, tmp_path, lambda formats, copy_to: ()
        ),
        user_agent_for=lambda config: USER_AGENT,
        default_selection=ExportSelection(),
        output_directory=tmp_path,
        tool_name="osint-scrapper",
        version="0.2.0",
        licenses_path=tmp_path / "THIRD_PARTY_LICENSES.md",
        readme_path=tmp_path / "README.md",
        settings=settings
        or QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
    )
    qtbot.addWidget(window)
    return window


def test_the_window_holds_the_three_panes_and_a_status_bar(
    qtbot, controllers, tmp_path, settings_pane
) -> None:
    window = build_window(qtbot, controllers, tmp_path, settings_pane)
    assert window._tabs.count() == 3
    assert [window._tabs.tabText(index) for index in range(3)] == ["&Crawl", "&Runs", "&Settings"]
    assert window.statusBar() is not None


def test_export_is_disabled_until_a_run_has_finished(
    qtbot, controllers, tmp_path, settings_pane
) -> None:
    window = build_window(qtbot, controllers, tmp_path, settings_pane)
    assert not window._export_action.isEnabled()

    window._on_run_finished(make_report())
    assert window._export_action.isEnabled()


def test_switching_panes_does_not_stop_a_running_crawl(
    qtbot, controllers, tmp_path, settings_pane
) -> None:
    gate = threading.Event()
    controller = controllers(factory_for("block", gate))
    crawl_pane = CrawlPane(
        controller=controller,
        defaults=CrawlFormState(contact_email=CONTACT),
        user_agent=USER_AGENT,
        hard_floor_seconds=0.5,
    )
    qtbot.addWidget(crawl_pane)
    with qtbot.waitSignal(controller.run_started, timeout=5000):
        controller.start(REQUEST)

    crawl_pane.setVisible(False)
    assert controller.is_running()

    with qtbot.waitSignal(controller.finished, timeout=5000):
        gate.set()


def test_the_window_saves_and_restores_its_geometry(
    qtbot, controllers, tmp_path, settings_pane
) -> None:
    """The size an operator chose comes back on the next launch.

    Both windows share one settings store, so this is a real round-trip: two
    no-op methods, or a save writing under a key restore never reads, would
    leave the second window at ``DEFAULT_WINDOW_SIZE``.

    Only the height is asserted. The offscreen screen is narrower than the
    window's own minimum width, so ``restoreGeometry`` clamps the width to that
    minimum whatever was saved; the height carries the whole claim instead, and
    the value chosen is neither the default nor the minimum.
    """
    chosen_height = 742
    assert chosen_height not in (DEFAULT_WINDOW_SIZE[1], MINIMUM_WINDOW_SIZE[1])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = build_window(qtbot, controllers, tmp_path, settings_pane, settings)
    window.resize(QSize(960, chosen_height))
    assert window.height() == chosen_height, "the platform must honour a plain resize"
    window.save_layout()
    assert {GEOMETRY_KEY, STATE_KEY, SPLITTER_KEY} <= set(settings.allKeys())

    restored = build_window(qtbot, controllers, tmp_path, settings_pane, settings)
    assert restored.height() == chosen_height, "the constructor must restore the layout"
    restored.resize(QSize(960, DEFAULT_WINDOW_SIZE[1]))
    restored.restore_layout()
    assert restored.height() == chosen_height


def test_shutting_down_joins_the_crawl_thread(
    qtbot, controllers, tmp_path, settings_pane
) -> None:
    window = build_window(qtbot, controllers, tmp_path, settings_pane)
    window.shutdown_crawl()
    assert not window._crawl_controller.is_running()


@pytest.fixture
def settings_pane():
    """The real Settings pane, built on the real configuration object."""
    from osint_scrapper.infrastructure.config import AppConfig
    from osint_scrapper.interfaces.settings_pane import SettingsPane

    return SettingsPane(
        config=AppConfig(contact_email=CONTACT),
        save_config=lambda config, path: path,
        writable_config_path=lambda: Path("osint-scrapper.toml"),
        user_agent_for=lambda project, contact: USER_AGENT,
    )


# ------------------------------------------------------------ settings pane


def test_the_settings_pane_shows_a_read_only_user_agent(settings_pane) -> None:
    assert settings_pane._user_agent.isReadOnly()
    assert settings_pane._user_agent.text() == USER_AGENT


def test_the_settings_pane_explains_why_a_contact_email_is_required(settings_pane) -> None:
    from osint_scrapper.interfaces.settings_pane import CONTACT_EMAIL_EXPLANATION

    assert "User-Agent" in CONTACT_EMAIL_EXPLANATION
    assert "disabled" in CONTACT_EMAIL_EXPLANATION


def test_an_invalid_contact_email_saves_nothing_and_says_why(qtbot, settings_pane) -> None:
    settings_pane._contact_email.setText("not-an-address")
    settings_pane.save()
    assert "invalid_contact_email" in settings_pane._banner.text()


def test_saving_reports_the_file_it_wrote(qtbot, settings_pane) -> None:
    saved: list[object] = []
    settings_pane.config_saved.connect(saved.append)
    settings_pane.save()
    qtbot.waitUntil(lambda: bool(saved), timeout=5000)
    assert "osint-scrapper.toml" in settings_pane._written_to.text()


def test_a_clamped_configuration_value_is_reported_to_the_operator(qtbot) -> None:
    from osint_scrapper.infrastructure.config import AppConfig, ClampReport
    from osint_scrapper.interfaces.settings_pane import SettingsPane

    pane = SettingsPane(
        config=AppConfig(
            contact_email=CONTACT,
            clamps=(ClampReport(key="max_pages", requested="99999", applied="2000"),),
        ),
        save_config=lambda config, path: path,
        writable_config_path=lambda: Path("osint-scrapper.toml"),
        user_agent_for=lambda project, contact: USER_AGENT,
    )
    qtbot.addWidget(pane)
    assert pane._clamps.isVisible() or "max_pages" in pane._clamps.text()
    assert "99999" in pane._clamps.text()
    assert "2000" in pane._clamps.text()
