"""Errors that belong to a port's contract.

These describe how the outside world can fail, so an adapter raises them and a
use case catches them. They are declared here rather than in ``infrastructure``
because the application layer must be able to name them without importing any
adapter (Rule 1: dependencies point inward).
"""

from __future__ import annotations

from pathlib import Path


class InfrastructureError(Exception):
    """Base class for a failure of an adapter, not of a business rule."""


class TransportError(InfrastructureError):
    """The request never produced an HTTP response: DNS, TLS, timeout, reset."""


class TooManyRedirectsError(TransportError):
    """More than the permitted number of hops, or a redirect loop."""


class HttpStatusError(InfrastructureError):
    """The server answered with a status the caller cannot use."""

    def __init__(self, url: str, status_code: int) -> None:
        super().__init__(f"{url} returned HTTP {status_code}")
        self.url = url
        self.status_code = status_code


class RateLimitedError(HttpStatusError):
    """The server asked us to slow down.

    ``retry_after`` is the parsed ``Retry-After`` value in seconds when the host
    sent one. The crawl uses it to decide between backing off and aborting: a
    ``Retry-After`` longer than the documented ceiling means stopping is more
    honest than holding a run open doing nothing (SPEC 5.10).
    """

    def __init__(self, url: str, status_code: int, retry_after: float | None = None) -> None:
        super().__init__(url, status_code)
        self.retry_after = retry_after


class RobotsDeniedError(InfrastructureError):
    """The host's robots.txt does not allow this path for our product token."""

    def __init__(self, url: str, reason: str, robots_url: str) -> None:
        super().__init__(f"robots.txt denies {url}: {reason} ({robots_url})")
        self.url = url
        self.reason = reason
        self.robots_url = robots_url


class OffScopeRedirectError(InfrastructureError):
    """A redirect hop left the crawl scope and was not followed (SPEC 5.3).

    This is the rule that stops one misconfigured redirect from turning a site
    crawl into an internet crawl.
    """

    def __init__(self, url: str, location: str) -> None:
        super().__init__(f"{url} redirects out of scope to {location}; not following")
        self.url = url
        self.location = location


class ResponseTooLargeError(InfrastructureError):
    """A body or document exceeded its documented cap. Nothing partial is parsed."""

    def __init__(self, url: str, limit_bytes: int) -> None:
        super().__init__(f"{url} exceeds the {limit_bytes} byte cap and was abandoned")
        self.url = url
        self.limit_bytes = limit_bytes


class UnsupportedContentTypeError(InfrastructureError):
    """The response announced a media type this product does not parse (SPEC 5.7).

    The body is not read past the header and the connection is released.
    """

    def __init__(self, url: str, media_type: str) -> None:
        super().__init__(f"{url} served {media_type or '(no media type)'}, which is not parsed")
        self.url = url
        self.media_type = media_type


class PageBudgetExhaustedError(InfrastructureError):
    """The run's request ceiling was reached (SPEC NFR-12)."""


class SelectorNotFoundError(InfrastructureError):
    """A parser could not find the structure it was written against.

    Raised loudly and specifically rather than returning a half-filled record:
    a scraper that silently degrades produces answers nobody can trust (NFR-8).
    """

    def __init__(self, selector: str, url: str) -> None:
        super().__init__(f"selector {selector!r} not found at {url}")
        self.selector = selector
        self.url = url


class ConfigurationError(InfrastructureError):
    """The environment or configuration file cannot support a run."""


class ExportFailedError(InfrastructureError):
    """At least one export file could not be written (SPEC 7.8).

    Every other writer still ran, and ``written`` names the files that did
    succeed, so the interface can report per-file rather than declaring the
    whole export lost.
    """

    def __init__(
        self, written: tuple[Path, ...], failures: tuple[tuple[str, str], ...]
    ) -> None:
        listed = "; ".join(f"{name}: {reason}" for name, reason in failures)
        super().__init__(f"{len(failures)} export file(s) could not be written — {listed}")
        self.written = written
        self.failures = failures
