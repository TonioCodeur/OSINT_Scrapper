"""Qt table models over the plain rows built in :mod:`view_models`.

These classes hold no presentation logic of their own: they translate rows into
Qt roles and nothing more. Two properties are deliberate and are what keep the
live tables usable while a crawl runs:

* the source models are **append-only and update in place** — they never reset,
  so the operator's scroll position and selection survive every update;
* every reorder and every filter happens in a proxy, which is what lets Qt
  maintain persistent indexes and keep that selection attached to the same row.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Final

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
)
from PySide6.QtGui import QColor, QPalette

from osint_scrapper.domain.attributes import Finding
from osint_scrapper.domain.crawl import PageStatus
from osint_scrapper.interfaces.view_models import (
    FIELD_ORDER,
    FINDING_HEADERS,
    LAYER_ORDER,
    PAGE_HEADERS,
    RUN_HEADERS,
    FindingRow,
    PageRow,
    RunRow,
    Severity,
    finding_rows,
)

SORT_ROLE: Final = int(Qt.ItemDataRole.UserRole) + 1
"""A role carrying a comparable value, so numbers sort as numbers."""

IDENTITY_ROLE: Final = int(Qt.ItemDataRole.UserRole) + 2
"""A role carrying a row's stable identity, used to restore a selection."""

ModelIndex = QModelIndex | QPersistentModelIndex

_DARK_SEVERITY_COLORS: Final[dict[Severity, QColor]] = {
    Severity.ERROR: QColor("#ff8a80"),
    Severity.WARNING: QColor("#ffcc80"),
}
_LIGHT_SEVERITY_COLORS: Final[dict[Severity, QColor]] = {
    Severity.ERROR: QColor("#b3261e"),
    Severity.WARNING: QColor("#8a5300"),
}


def severity_color(severity: Severity, palette: QPalette) -> QColor | None:
    """A foreground colour for ``severity`` that reads on the operator's theme.

    Only the two loud severities get a colour; everything else inherits the
    palette, which is how the tables stay legible under a light theme, a dark
    theme and a high-contrast theme without any of them being hardcoded.
    """
    window = palette.color(QPalette.ColorRole.Window)
    dark = window.lightness() < 128
    table = _DARK_SEVERITY_COLORS if dark else _LIGHT_SEVERITY_COLORS
    return table.get(severity)


class FindingsTableModel(QAbstractTableModel):
    """The live findings table: Field, Value, Extraction, Pages, First seen.

    Rows are keyed by ``(field, value)``. A finding whose ``page_support`` grows
    updates its existing row rather than adding a second one, which is the model
    counterpart of the deduplication rule in SPEC 8.5.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._rows: list[FindingRow] = []
        self._index_of: dict[tuple[str, str], int] = {}

    def rowCount(self, parent: ModelIndex | None = None) -> int:
        """The number of findings currently displayed."""
        if parent is not None and parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: ModelIndex | None = None) -> int:
        """The five columns of SPEC 7.3."""
        if parent is not None and parent.isValid():
            return 0
        return len(FINDING_HEADERS)

    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Return one cell in the requested role."""
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return row.cells()[column]
        if role == Qt.ItemDataRole.ToolTipRole:
            return row.tooltip()
        if role == SORT_ROLE:
            return _finding_sort_value(row, column)
        if role == IDENTITY_ROLE:
            return row.key
        if role == Qt.ItemDataRole.TextAlignmentRole and column == 3:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        """Column titles. Rows are not numbered: the findings table is a set."""
        if role != Qt.ItemDataRole.DisplayRole or orientation != Qt.Orientation.Horizontal:
            return None
        return FINDING_HEADERS[section]

    def apply_findings(self, findings: Iterable[Finding]) -> None:
        """Merge a fresh snapshot of the findings into the table.

        New findings are appended; known ones are updated where they already
        sit. Nothing is removed, because the aggregator never retracts a value.
        """
        for row in finding_rows(findings):
            position = self._index_of.get(row.key)
            if position is None:
                self._append(row)
            elif self._rows[position] != row:
                self._rows[position] = row
                changed = self.index(position, 0)
                self.dataChanged.emit(changed, self.index(position, self.columnCount() - 1))

    def row_at(self, position: int) -> FindingRow:
        """The row at ``position`` in the source model."""
        return self._rows[position]

    def clear(self) -> None:
        """Drop every row. Called only when a new run starts."""
        self.beginResetModel()
        self._rows.clear()
        self._index_of.clear()
        self.endResetModel()

    def _append(self, row: FindingRow) -> None:
        position = len(self._rows)
        self.beginInsertRows(QModelIndex(), position, position)
        self._rows.append(row)
        self._index_of[row.key] = position
        self.endInsertRows()


def _finding_sort_value(row: FindingRow, column: int) -> Any:
    if column == 0:
        return FIELD_ORDER[row.field]
    if column == 1:
        return row.value.casefold()
    if column == 2:
        return LAYER_ORDER[row.extraction_layer]
    if column == 3:
        return row.page_support
    return row.first_seen_url.casefold()


class PageLogTableModel(QAbstractTableModel):
    """The per-page log: #, Depth, Status, URL, Detail.

    Strictly append-only. A page that failed is a row with a status, never an
    absence (SPEC FR-7, 7.5 tier 1).
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._rows: list[PageRow] = []
        self._palette = QPalette()

    def set_palette(self, palette: QPalette) -> None:
        """Adopt the view's palette so severity colours follow the OS theme."""
        self._palette = palette

    def rowCount(self, parent: ModelIndex | None = None) -> int:
        """The number of logged pages."""
        if parent is not None and parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: ModelIndex | None = None) -> int:
        """The five columns of SPEC 7.3."""
        if parent is not None and parent.isValid():
            return 0
        return len(PAGE_HEADERS)

    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Return one cell in the requested role."""
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return row.cells()[column]
        if role == Qt.ItemDataRole.ToolTipRole:
            return row.tooltip()
        if role == Qt.ItemDataRole.ForegroundRole:
            return severity_color(row.severity, self._palette)
        if role == SORT_ROLE:
            return _page_sort_value(row, column)
        if role == IDENTITY_ROLE:
            return str(row.status)
        if role == Qt.ItemDataRole.TextAlignmentRole and column in {0, 1}:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        """Column titles."""
        if role != Qt.ItemDataRole.DisplayRole or orientation != Qt.Orientation.Horizontal:
            return None
        return PAGE_HEADERS[section]

    def add_rows(self, rows: Sequence[PageRow]) -> None:
        """Append a whole batch in one insertion, so the view repaints once."""
        if not rows:
            return
        first = len(self._rows)
        self.beginInsertRows(QModelIndex(), first, first + len(rows) - 1)
        self._rows.extend(rows)
        self.endInsertRows()

    def row_at(self, position: int) -> PageRow:
        """The row at ``position`` in the source model."""
        return self._rows[position]

    def known_statuses(self) -> tuple[PageStatus, ...]:
        """Every status actually seen, so the filter offers only useful choices."""
        return tuple(sorted({row.status for row in self._rows}, key=str))

    def clear(self) -> None:
        """Drop every row. Called only when a new run starts."""
        self.beginResetModel()
        self._rows.clear()
        self.endResetModel()


def _page_sort_value(row: PageRow, column: int) -> Any:
    if column == 0:
        return row.number
    if column == 1:
        return row.depth
    if column == 2:
        return str(row.status)
    if column == 3:
        return row.url.casefold()
    return row.detail.casefold()


class PageStatusFilterProxy(QSortFilterProxyModel):
    """Filters the page log down to one status (SPEC 7.3, region 3)."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._status: PageStatus | None = None
        self.setSortRole(SORT_ROLE)
        self.setDynamicSortFilter(True)

    def set_status(self, status: PageStatus | None) -> None:
        """Show only ``status``, or everything when it is ``None``.

        ``beginFilterChange`` before the criterion moves, then ``invalidate``:
        Qt 6.10 deprecated the ``invalidate*Filter`` family in favour of this
        pair, which is what lets the proxy keep persistent indexes — and with
        them the operator's selection — across the change.
        """
        if status == self._status:
            return
        self.beginFilterChange()
        self._status = status
        self.invalidate()

    def filterAcceptsRow(self, source_row: int, source_parent: ModelIndex) -> bool:
        """Accept a row when no status filter is active, or when it matches."""
        if self._status is None:
            return True
        model = self.sourceModel()
        index = model.index(source_row, 2, source_parent)
        return bool(model.data(index, Qt.ItemDataRole.DisplayRole) == str(self._status))


class SortedProxy(QSortFilterProxyModel):
    """A proxy that sorts on :data:`SORT_ROLE`, so numeric columns sort numerically."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.setSortRole(SORT_ROLE)
        self.setDynamicSortFilter(True)


class RunsTableModel(QAbstractTableModel):
    """The Runs pane's table (SPEC 7.4)."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._rows: list[RunRow] = []
        self._palette = QPalette()

    def set_palette(self, palette: QPalette) -> None:
        """Adopt the view's palette so expired runs stand out on any theme."""
        self._palette = palette

    def rowCount(self, parent: ModelIndex | None = None) -> int:
        """The number of recorded runs."""
        if parent is not None and parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: ModelIndex | None = None) -> int:
        """The seven columns of SPEC 7.4."""
        if parent is not None and parent.isValid():
            return 0
        return len(RUN_HEADERS)

    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Return one cell in the requested role."""
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return row.cells()[column]
        if role == Qt.ItemDataRole.ToolTipRole:
            return _run_tooltip(row)
        if role == Qt.ItemDataRole.ForegroundRole and row.expired:
            return severity_color(Severity.WARNING, self._palette)
        if role == SORT_ROLE:
            return _run_sort_value(row, column)
        if role == IDENTITY_ROLE:
            return row.run_id
        if role == Qt.ItemDataRole.TextAlignmentRole and column in {3, 4, 5}:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        """Column titles."""
        if role != Qt.ItemDataRole.DisplayRole or orientation != Qt.Orientation.Horizontal:
            return None
        return RUN_HEADERS[section]

    def set_rows(self, rows: Sequence[RunRow]) -> None:
        """Replace the whole table. The runs list is refreshed as a whole."""
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def row_at(self, position: int) -> RunRow:
        """The row at ``position`` in the source model."""
        return self._rows[position]

    def rows(self) -> tuple[RunRow, ...]:
        """Every row currently displayed."""
        return tuple(self._rows)


def _run_tooltip(row: RunRow) -> str:
    lines = [
        f"Run {row.run_id}",
        f"Target host: {row.target_host}",
        f"Purpose: {row.purpose_category}",
        f"Directory: {row.directory}",
        f"Retention: {row.retention_text()}",
    ]
    if row.purpose_note:
        lines.append(f"Note: {row.purpose_note}")
    return "\n".join(lines)


def _run_sort_value(row: RunRow, column: int) -> Any:
    if column == 0:
        return row.created_at.timestamp()
    if column == 1:
        return row.target_host.casefold()
    if column == 2:
        return row.purpose_category
    if column == 3:
        return row.pages_fetched
    if column == 4:
        return row.findings_count
    if column == 5:
        return row.size_bytes
    return row.days_remaining
