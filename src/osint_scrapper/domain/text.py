"""Text folding, the one primitive the deduplication keys of SPEC 8.5 share."""

from __future__ import annotations

import re
import unicodedata

_WHITESPACE_RUN = re.compile(r"\s+")


def collapse_whitespace(value: str) -> str:
    """Collapse runs of whitespace to single spaces and trim the ends."""
    return _WHITESPACE_RUN.sub(" ", value).strip()


def fold(value: str) -> str:
    """Return an accent-, case- and whitespace-insensitive form of ``value``.

    Used only to build deduplication keys. The folded form is never exported:
    stored values keep their diacritics and their casing (SPEC 8.5).
    """
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return collapse_whitespace(without_marks).lower()
