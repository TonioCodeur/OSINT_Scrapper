"""The About dialog (SPEC 7.9, FR-19).

The LGPLv3 statement here is not chrome. This application links Qt dynamically
through PySide6 under the LGPLv3, and clause 4 of that licence requires a
prominent notice that the library is used and a copy of its terms. This dialog
is that notice; ``THIRD_PARTY_LICENSES.md`` is that copy.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from osint_scrapper.interfaces.export_dialog import open_path

LGPL_STATEMENT = (
    "This application uses the Qt toolkit through <b>PySide6</b>, which is used here "
    "under the <b>GNU Lesser General Public License version 3</b>. Qt is linked "
    "dynamically, exactly as installed by pip, and you are free to replace those "
    "libraries with your own build. The full licence text and one entry per "
    "third-party component are in THIRD_PARTY_LICENSES.md."
)

DESCRIPTION = (
    "Crawls one website you name and exports the contact and identity information "
    "that site publishes, fully attributed, within the limits you set."
)


class AboutDialog(QDialog):
    """Name, version, description and the licence obligations this project accepts."""

    def __init__(
        self,
        tool_name: str,
        version: str,
        licenses_path: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._licenses_path = licenses_path
        self.setWindowTitle(f"About {tool_name}")
        self.setModal(True)
        self.setMinimumWidth(520)

        title = QLabel(f"<h2>{tool_name} {version}</h2>", self)
        description = QLabel(DESCRIPTION, self)
        description.setWordWrap(True)
        licence = QLabel(LGPL_STATEMENT, self)
        licence.setWordWrap(True)
        licence.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self._path_label = QLabel(str(licenses_path), self)
        self._path_label.setWordWrap(True)
        self._path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self._open_licenses = QPushButton("Open THIRD_PARTY_LICENSES.md", self)
        self._open_licenses.setEnabled(licenses_path.exists())
        if not licenses_path.exists():
            self._open_licenses.setToolTip(f"Not found at {licenses_path}")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(licence)
        layout.addWidget(self._path_label)
        layout.addWidget(self._open_licenses)
        layout.addWidget(buttons)

        self._open_licenses.clicked.connect(self.open_licenses)

    @Slot()
    def open_licenses(self) -> bool:
        """Open the third-party licence file in the operator's default application."""
        return open_path(self._licenses_path)
