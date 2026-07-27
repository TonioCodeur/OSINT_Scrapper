"""Turning a document into the text a human visitor actually sees."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Comment, Tag

NON_VISIBLE_ELEMENTS = ("script", "style", "noscript", "template")
"""Elements whose content is never shown, and whose text would be noise."""

HTML_PARSER = "html.parser"
"""The standard library backend: no compiled dependency, identical on every platform."""

_WHITESPACE_RUN = re.compile(r"\s+")


def parse_html(markup: str) -> BeautifulSoup:
    """Parse ``markup`` with the standard library backend."""
    return BeautifulSoup(markup, HTML_PARSER)


def visible_text(soup: BeautifulSoup) -> str:
    """Return the document text with invisible elements and comments removed.

    Operates on a copy, so callers can still walk the original tree afterwards.
    """
    working = BeautifulSoup(str(soup), HTML_PARSER)
    for element in working.find_all(NON_VISIBLE_ELEMENTS):
        element.decompose()
    for comment in working.find_all(string=lambda node: isinstance(node, Comment)):
        comment.extract()
    return collapse(working.get_text(" "))


def collapse(value: str) -> str:
    """Collapse whitespace runs to single spaces and trim the ends."""
    return _WHITESPACE_RUN.sub(" ", value).strip()


def attribute_value(tag: Tag, name: str) -> str | None:
    """Return a single attribute value, joining the multi-valued form."""
    raw = tag.get(name)
    if raw is None:
        return None
    if isinstance(raw, list):
        return " ".join(str(item) for item in raw)
    return str(raw)


def css_classes(tag: Tag) -> frozenset[str]:
    """Return the tag's class names, lower-cased."""
    raw = tag.get("class")
    if raw is None:
        return frozenset()
    if isinstance(raw, str):
        return frozenset({raw.lower()})
    return frozenset(str(item).lower() for item in raw)
