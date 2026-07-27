"""What the operator asked for: a target, the limits, and a declared purpose."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from osint_scrapper.domain.errors import InvalidCrawlSettingsError, InvalidPurposeError
from osint_scrapper.domain.url import CrawlScope, normalize_target, scope_for, scope_host_of

DEFAULT_MAX_PAGES = 200
MINIMUM_MAX_PAGES = 1
MAXIMUM_MAX_PAGES = 2000

DEFAULT_MAX_DEPTH = 3
MINIMUM_MAX_DEPTH = 0
MAXIMUM_MAX_DEPTH = 10

DEFAULT_REQUEST_INTERVAL_SECONDS = 1.0
MINIMUM_REQUEST_INTERVAL_SECONDS = 0.5
MAXIMUM_REQUEST_INTERVAL_SECONDS = 60.0

DEFAULT_CONCURRENT_REQUESTS = 2
MINIMUM_CONCURRENT_REQUESTS = 1
MAXIMUM_CONCURRENT_REQUESTS = 4

DEFAULT_PHONE_REGION = "FR"

DEFAULT_RETENTION_DAYS = 30
MINIMUM_RETENTION_DAYS = 1
MAXIMUM_RETENTION_DAYS = 3650
"""A declared retention of zero days is not a declaration, and ten years is
already longer than any purpose in the vocabulary can justify. These are the
bounds the Settings spin box has always shown; naming them here is what lets
the configuration loader clamp to them instead of letting a hand-edited file
reach ``CrawlSettings`` and raise."""

MINIMUM_PURPOSE_NOTE_LENGTH = 16
"""SPEC 7.2.2: the v1.0 guard survives, aimed only at the category that needs it."""

_REGION_CODE = re.compile(r"^[A-Z]{2}$")


class PurposeCategory(StrEnum):
    """The controlled vocabulary a crawl must assert before it starts (SPEC 7.2.2).

    A required choice produces better records than a free-text box, because a
    vocabulary is analysable and comparable across runs while prose is not, and
    because a mandatory text box before every run reliably collects garbage.
    """

    SECURITY_ASSESSMENT = "security_assessment"
    DUE_DILIGENCE = "due_diligence"
    JOURNALISM = "journalism"
    SELF_AUDIT = "self_audit"
    ACADEMIC_RESEARCH = "academic_research"
    OTHER = "other"


@dataclass(frozen=True)
class Purpose:
    """The lawful basis the operator asserted, written into every export."""

    category: PurposeCategory
    note: str = ""

    def __post_init__(self) -> None:
        """Require a real note when the category explains nothing by itself.

        Raises:
            InvalidPurposeError: the category is ``other`` and the note is too short.
        """
        stripped = self.note.strip()
        object.__setattr__(self, "note", stripped)
        if self.category is PurposeCategory.OTHER and len(stripped) < MINIMUM_PURPOSE_NOTE_LENGTH:
            raise InvalidPurposeError(
                f"purpose {PurposeCategory.OTHER} requires a note of at least "
                f"{MINIMUM_PURPOSE_NOTE_LENGTH} characters, got {len(stripped)}"
            )


@dataclass(frozen=True)
class CrawlTarget:
    """The site the operator named, and the confinement it defines."""

    entered_value: str
    target_url: str
    scope_host: str
    include_subdomains: bool

    @property
    def scope(self) -> CrawlScope:
        """The confinement rule of SPEC 5.3 derived from this target."""
        return scope_for(self.target_url, self.include_subdomains)


def resolve_target(entered_value: str, *, include_subdomains: bool) -> CrawlTarget:
    """Turn what the operator typed into a target, or say why it cannot be one.

    Raises:
        InvalidTargetError: the value is empty or is not an HTTP(S) target.
    """
    target_url = normalize_target(entered_value)
    return CrawlTarget(
        entered_value=entered_value.strip(),
        target_url=target_url,
        scope_host=scope_host_of(target_url),
        include_subdomains=include_subdomains,
    )


@dataclass(frozen=True)
class CrawlSettings:
    """The bounds of one run, enforced here and not only in the widget (SPEC 5.5).

    The maxima exist because "the operator named this target, so it is their
    lawful basis" is a much heavier argument to carry at two thousand requests
    than at five, and because an unbounded control lets a slip of the keyboard
    become an incident.
    """

    max_pages: int = DEFAULT_MAX_PAGES
    max_depth: int = DEFAULT_MAX_DEPTH
    request_interval_seconds: float = DEFAULT_REQUEST_INTERVAL_SECONDS
    concurrent_requests: int = DEFAULT_CONCURRENT_REQUESTS
    include_subdomains: bool = True
    follow_sitemap: bool = True
    phone_region: str = DEFAULT_PHONE_REGION
    retention_days: int = DEFAULT_RETENTION_DAYS

    def __post_init__(self) -> None:
        """Refuse any value a configuration file could smuggle past the interface.

        Raises:
            InvalidCrawlSettingsError: a setting is outside the bounds of SPEC 5.5.
        """
        _require_range("max_pages", self.max_pages, MINIMUM_MAX_PAGES, MAXIMUM_MAX_PAGES)
        _require_range("max_depth", self.max_depth, MINIMUM_MAX_DEPTH, MAXIMUM_MAX_DEPTH)
        _require_range(
            "request_interval_seconds",
            self.request_interval_seconds,
            MINIMUM_REQUEST_INTERVAL_SECONDS,
            MAXIMUM_REQUEST_INTERVAL_SECONDS,
        )
        _require_range(
            "concurrent_requests",
            self.concurrent_requests,
            MINIMUM_CONCURRENT_REQUESTS,
            MAXIMUM_CONCURRENT_REQUESTS,
        )
        _require_range(
            "retention_days",
            self.retention_days,
            MINIMUM_RETENTION_DAYS,
            MAXIMUM_RETENTION_DAYS,
        )
        if not _REGION_CODE.match(self.phone_region):
            raise InvalidCrawlSettingsError(
                "phone_region must be an upper-case ISO 3166-1 alpha-2 code, "
                f"got {self.phone_region!r}"
            )


def clamp_to_bounds(name: str, value: float, minimum: float, maximum: float) -> float:
    """Return ``value`` pulled inside its documented bounds.

    Used by configuration loading, which reports the clamp rather than refusing
    the file; :class:`CrawlSettings` still raises for a value constructed
    directly, so the bound cannot be bypassed in code (SPEC 7.7, AC-UI-6).
    """
    del name
    return min(max(value, minimum), maximum)


def _require_range(name: str, value: float, minimum: float, maximum: float) -> None:
    if not minimum <= value <= maximum:
        raise InvalidCrawlSettingsError(
            f"{name} must be between {minimum} and {maximum}, got {value}"
        )
