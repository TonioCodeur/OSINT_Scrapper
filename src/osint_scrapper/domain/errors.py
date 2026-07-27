"""Typed domain exceptions.

Every failure that a business rule can produce is one of these. Sentinel return
values and bare ``except`` clauses are forbidden by the project rules, so callers
discriminate on the exception type instead.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for every violation of a business rule."""


class InvalidTargetError(DomainError):
    """The operator named a target that cannot be crawled (SPEC FR-1)."""


class InvalidCrawlSettingsError(DomainError):
    """A crawl setting is outside the bounds of SPEC 5.5.

    Raised by ``CrawlSettings.__post_init__`` so a configuration file cannot
    smuggle a larger budget past the interface's spin boxes.
    """


class UrlRejectedError(DomainError):
    """A URL was refused before it could enter the frontier (SPEC 5.2).

    ``reason`` is a machine-stable code the crawl maps onto a ``PageStatus``.
    """

    def __init__(self, reason: str, url: str, detail: str) -> None:
        super().__init__(f"{url}: {detail}")
        self.reason = reason
        self.url = url
        self.detail = detail


class MissingPurposeError(DomainError):
    """No purpose was declared for the crawl."""


class InvalidPurposeError(DomainError):
    """The declared purpose does not carry the note its category requires."""


class ValidationRejectedError(DomainError):
    """A candidate value failed its field validator and must not become a fact."""


class MissingProvenanceError(DomainError):
    """A value was built without provenance anyone could audit.

    Covers a finding with no provenance at all, and provenance whose source URL
    or collection timestamp would not survive scrutiny (SPEC FR-16).
    """


class ProvenanceOverflowError(DomainError):
    """A finding was built with more provenance entries than SPEC 8.6 permits.

    The cap is enforced rather than silently applied, because truncating inside
    the entity would hide the fact that ``page_support`` and the retained
    entries had stopped agreeing.
    """


class SeedRefusedError(DomainError):
    """The run must not start at all (SPEC 5.10).

    Raised when ``robots.txt`` disallows the target itself or the target is
    unreachable. No run directory is created and no ledger line is written, so
    this is a refusal to start rather than an aborted run.
    """

    def __init__(self, url: str, reason: str, detail: str, robots_url: str | None = None) -> None:
        super().__init__(f"refusing to crawl {url}: {reason} - {detail}")
        self.url = url
        self.reason = reason
        self.detail = detail
        self.robots_url = robots_url
