"""Spreadsheet formula-injection guard (FR-27).

These files carry text scraped from third-party pages straight into a
spreadsheet. A cell starting with ``=`` is a formula in Excel, LibreOffice and
Google Sheets alike, so any value that could be read as one is prefixed with an
apostrophe before it is written.
"""

from __future__ import annotations

FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")
"""First characters that make a spreadsheet treat a cell as an expression."""

GUARD_PREFIX = "'"


def guard(value: str) -> str:
    """Return ``value`` prefixed with an apostrophe if a spreadsheet would evaluate it."""
    if value.startswith(FORMULA_TRIGGERS):
        return f"{GUARD_PREFIX}{value}"
    return value
