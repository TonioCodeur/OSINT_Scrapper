"""The Qt table models.

The properties under test are the ones that make a live table usable: rows are
appended rather than reset, a finding that grows updates the row it already
occupies, and a batch of pages costs one insertion rather than one per row.
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QColor, QPalette

from osint_scrapper.domain.attributes import FieldName
from osint_scrapper.domain.crawl import PageStatus
from osint_scrapper.interfaces.models import (
    IDENTITY_ROLE,
    SORT_ROLE,
    FindingsTableModel,
    PageLogTableModel,
    PageStatusFilterProxy,
    RunsTableModel,
    SortedProxy,
    severity_color,
)
from osint_scrapper.interfaces.view_models import (
    FINDING_HEADERS,
    PAGE_HEADERS,
    RUN_HEADERS,
    Severity,
    page_rows,
    run_rows,
)
from tests.interfaces.conftest import make_finding, make_page
from tests.interfaces.test_view_models import summary


def display(model, row: int, column: int) -> str:
    return str(model.data(model.index(row, column), Qt.ItemDataRole.DisplayRole))


# ------------------------------------------------------------------ findings


def test_the_findings_model_exposes_the_five_specified_columns(qapp) -> None:
    model = FindingsTableModel()
    assert model.columnCount() == len(FINDING_HEADERS)
    for column, title in enumerate(FINDING_HEADERS):
        header = model.headerData(column, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
        assert header == title


def test_findings_are_appended_in_the_canonical_order(qapp) -> None:
    model = FindingsTableModel()
    model.apply_findings(
        [
            make_finding(field=FieldName.TECHNOLOGY, value="WordPress 6.5", confidence=0.75),
            make_finding(value="contact@example.com"),
        ]
    )
    assert model.rowCount() == 2
    assert display(model, 0, 1) == "contact@example.com"
    assert display(model, 1, 1) == "WordPress 6.5"


def test_a_growing_finding_updates_its_row_instead_of_adding_a_second(qapp) -> None:
    model = FindingsTableModel()
    model.apply_findings([make_finding(page_support=1)])
    inserted: list[object] = []
    changed: list[object] = []
    model.rowsInserted.connect(lambda *args: inserted.append(args))
    model.dataChanged.connect(lambda *args: changed.append(args))

    model.apply_findings([make_finding(page_support=40, occurrence_count=40)])

    assert model.rowCount() == 1
    assert not inserted
    assert changed
    assert display(model, 0, 3) == "40"


def test_an_unchanged_snapshot_does_not_repaint_anything(qapp) -> None:
    model = FindingsTableModel()
    model.apply_findings([make_finding()])
    changed: list[object] = []
    model.dataChanged.connect(lambda *args: changed.append(args))
    model.apply_findings([make_finding()])
    assert not changed


def test_the_page_count_sorts_as_a_number_and_not_as_a_string(qapp) -> None:
    model = FindingsTableModel()
    model.apply_findings([make_finding(page_support=9)])
    assert model.data(model.index(0, 3), SORT_ROLE) == 9


def test_a_finding_row_carries_its_identity_for_selection_restoration(qapp) -> None:
    model = FindingsTableModel()
    model.apply_findings([make_finding()])
    assert model.data(model.index(0, 0), IDENTITY_ROLE) == ("email", "contact@example.com")


def test_clearing_the_findings_empties_the_table(qapp) -> None:
    model = FindingsTableModel()
    model.apply_findings([make_finding()])
    model.clear()
    assert model.rowCount() == 0


def test_the_findings_proxy_sorts_on_the_dedicated_role(qapp) -> None:
    model = FindingsTableModel()
    model.apply_findings(
        [make_finding(value="b@example.com"), make_finding(value="a@example.com")]
    )
    proxy = SortedProxy()
    proxy.setSourceModel(model)
    proxy.sort(1, Qt.SortOrder.AscendingOrder)
    assert display(proxy, 0, 1) == "a@example.com"


# --------------------------------------------------------------- page log


def test_the_page_log_exposes_the_five_specified_columns(qapp) -> None:
    model = PageLogTableModel()
    assert model.columnCount() == len(PAGE_HEADERS)
    assert model.headerData(2, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == "Status"


def test_a_batch_of_pages_costs_exactly_one_insertion(qapp) -> None:
    model = PageLogTableModel()
    insertions: list[object] = []
    model.rowsInserted.connect(lambda *args: insertions.append(args))
    model.add_rows(page_rows([make_page(url=f"https://example.com/{n}") for n in range(30)]))
    assert model.rowCount() == 30
    assert len(insertions) == 1


def test_an_empty_batch_does_not_touch_the_model(qapp) -> None:
    model = PageLogTableModel()
    insertions: list[object] = []
    model.rowsInserted.connect(lambda *args: insertions.append(args))
    model.add_rows(())
    assert not insertions


def test_a_failed_page_is_a_row_with_a_status_not_an_absence(qapp) -> None:
    model = PageLogTableModel()
    model.add_rows(page_rows([make_page(status=PageStatus.TRANSPORT_ERROR, detail="timeout")]))
    assert model.rowCount() == 1
    assert display(model, 0, 2) == "transport_error"
    assert display(model, 0, 4) == "timeout"


def test_the_page_log_can_be_filtered_down_to_one_status(qapp) -> None:
    model = PageLogTableModel()
    model.add_rows(
        page_rows(
            [
                make_page(status=PageStatus.OK),
                make_page(url="https://example.com/x", status=PageStatus.SKIPPED_ROBOTS),
            ]
        )
    )
    proxy = PageStatusFilterProxy()
    proxy.setSourceModel(model)
    assert proxy.rowCount() == 2

    proxy.set_status(PageStatus.SKIPPED_ROBOTS)
    assert proxy.rowCount() == 1
    assert display(proxy, 0, 2) == "skipped_robots"

    proxy.set_status(None)
    assert proxy.rowCount() == 2


def test_the_log_reports_only_the_statuses_it_has_actually_seen(qapp) -> None:
    model = PageLogTableModel()
    model.add_rows(page_rows([make_page(), make_page(url="https://example.com/a")]))
    assert model.known_statuses() == (PageStatus.OK,)


# -------------------------------------------------------------------- runs


def test_the_runs_model_exposes_the_seven_specified_columns(qapp) -> None:
    model = RunsTableModel()
    assert model.columnCount() == len(RUN_HEADERS)
    model.set_rows(run_rows([summary()]))
    assert display(model, 0, 1) == "example.com"
    assert model.data(model.index(0, 0), IDENTITY_ROLE) == "r-0000test"


def test_a_run_sorts_by_size_as_a_number(qapp) -> None:
    model = RunsTableModel()
    model.set_rows(run_rows([summary(size_bytes=2048)]))
    assert model.data(model.index(0, 5), SORT_ROLE) == 2048


def test_an_expired_run_is_visually_distinguished(qapp) -> None:
    """Only an expired run is repainted; a live one keeps the theme's own colour.

    Without the negative case, dropping the ``expired`` guard in the model —
    which would repaint every row as a warning — would go unnoticed.
    """
    model = RunsTableModel()
    model.set_rows(run_rows([summary(days_remaining=0, expired=True)]))
    assert model.data(model.index(0, 0), Qt.ItemDataRole.ForegroundRole) == severity_color(
        Severity.WARNING, QPalette()
    )

    model.set_rows(run_rows([summary(days_remaining=23, expired=False)]))
    assert model.data(model.index(0, 0), Qt.ItemDataRole.ForegroundRole) is None


# ------------------------------------------------------------------ colour


def test_only_the_loud_severities_override_the_theme(qapp) -> None:
    palette = QPalette()
    assert severity_color(Severity.ERROR, palette) is not None
    assert severity_color(Severity.WARNING, palette) is not None
    assert severity_color(Severity.INFO, palette) is None
    assert severity_color(Severity.SUCCESS, palette) is None


def test_the_error_colour_differs_between_a_light_and_a_dark_theme(qapp) -> None:
    light = QPalette()
    light.setColor(QPalette.ColorRole.Window, QColor("#ffffff"))
    dark = QPalette()
    dark.setColor(QPalette.ColorRole.Window, QColor("#101010"))
    assert severity_color(Severity.ERROR, light) != severity_color(Severity.ERROR, dark)


def test_a_root_index_holds_no_rows(qapp) -> None:
    model = FindingsTableModel()
    model.apply_findings([make_finding()])
    parent = model.index(0, 0)
    assert model.rowCount(parent) == 0
    assert model.columnCount(parent) == 0
    assert model.data(QModelIndex()) is None
