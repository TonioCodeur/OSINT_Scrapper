"""The honest User-Agent, and the mechanical ban on impersonating a browser (FR-12).

There is no CLI flag and no configuration key that sets an arbitrary User-Agent.
The only way to build one is this function, and it refuses browser tokens.
"""

from __future__ import annotations

import re

from osint_scrapper.application.errors import InfrastructureError

BROWSER_TOKENS = (
    "Mozilla",
    "AppleWebKit",
    "Chrome",
    "Chromium",
    "Safari",
    "Firefox",
    "Gecko",
    "Edg",
)
"""Substrings whose presence means the string is pretending to be a browser."""

_BROWSER_PATTERN = re.compile("|".join(re.escape(token) for token in BROWSER_TOKENS), re.IGNORECASE)


class DishonestUserAgentError(InfrastructureError):
    """A User-Agent candidate impersonated a browser and was refused."""


def assert_honest(candidate: str) -> str:
    """Return ``candidate`` unchanged, or refuse it.

    Raises:
        DishonestUserAgentError: the string contains a browser token.
    """
    match = _BROWSER_PATTERN.search(candidate)
    if match is not None:
        raise DishonestUserAgentError(
            f"User-Agent {candidate!r} contains the browser token {match.group(0)!r}; "
            "this tool identifies itself honestly and does not defeat bot detection"
        )
    return candidate


def build_user_agent(
    product_token: str, version: str, project_url: str, contact_email: str
) -> str:
    """Build the project's User-Agent, e.g.
    ``OSINT-Scrapper/0.1.0 (+https://example.org/repo; contact: you@example.org)``.

    Raises:
        DishonestUserAgentError: any component would make the result look like a browser.
    """
    return assert_honest(f"{product_token}/{version} (+{project_url}; contact: {contact_email})")
