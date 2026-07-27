"""The social-platform list and profile-URL normalization (SPEC 8.1, 8.4).

Only full profile URLs on a known platform become findings. A bare ``@handle``
in body text never does: it is ambiguous across platforms, and guessing which
one it belongs to would manufacture a fact rather than read one.

These URLs are recorded and never fetched. The crawl does not leave its scope.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from osint_scrapper.domain.url import DROPPED_PARAMETERS

PLATFORM_HOSTS: Mapping[str, str] = MappingProxyType(
    {
        "github.com": "github",
        "gitlab.com": "gitlab",
        "linkedin.com": "linkedin",
        "x.com": "x",
        "twitter.com": "twitter",
        "facebook.com": "facebook",
        "instagram.com": "instagram",
        "youtube.com": "youtube",
        "tiktok.com": "tiktok",
        "bsky.app": "bluesky",
        "mastodon.social": "mastodon",
        "t.me": "telegram",
        "wa.me": "whatsapp",
        "discord.gg": "discord",
        "reddit.com": "reddit",
        "medium.com": "medium",
        "stackoverflow.com": "stackoverflow",
    }
)
"""Host to platform name. A subdomain of a listed host counts as that platform."""

_WWW_PREFIX = "www."


def platform_of(url: str) -> str | None:
    """Return the platform a profile URL belongs to, or ``None``.

    A platform root with no profile path is not a profile: ``https://x.com/`` is
    a link to a website, not to anybody.
    """
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in {"http", "https"}:
        return None
    host = (parts.hostname or "").lower().removeprefix(_WWW_PREFIX)
    if not host:
        return None
    if parts.path.strip("/") == "":
        return None
    for candidate, platform in PLATFORM_HOSTS.items():
        if host == candidate or host.endswith(f".{candidate}"):
            return platform
    return None


def normalize_profile(url: str) -> str:
    """Return the comparable form of a profile URL (SPEC 8.4).

    Lower-cases the host, strips ``www.``, drops tracking parameters and removes
    a trailing slash. The path keeps its case, because handles are often
    case-sensitive in display even when the platform folds them.
    """
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix(_WWW_PREFIX)
    netloc = host if parts.port is None else f"{host}:{parts.port}"
    kept = [
        (name, value)
        for name, value in parse_qsl(parts.query, keep_blank_values=True)
        if name.lower() not in DROPPED_PARAMETERS
    ]
    kept.sort()
    return urlunsplit(
        (parts.scheme.lower(), netloc, parts.path.rstrip("/"), urlencode(kept), "")
    )
