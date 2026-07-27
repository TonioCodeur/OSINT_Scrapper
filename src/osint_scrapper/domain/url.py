"""URL canonicalization, scope confinement and the spider-trap guard (SPEC 5.2, 5.3).

Pure, standard library only. The canonical form is the frontier key, the visited
key and the exported ``source_url``, so every rule here is load-bearing for the
promise that the same resource is never fetched twice in one run.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import (
    SplitResult,
    parse_qsl,
    quote,
    unquote,
    urlencode,
    urljoin,
    urlsplit,
    urlunsplit,
)

from osint_scrapper.domain.errors import InvalidTargetError, UrlRejectedError
from osint_scrapper.domain.text import fold

CRAWLABLE_SCHEMES = frozenset({"http", "https"})
"""``mailto:``, ``tel:``, ``javascript:``, ``data:`` and ``ftp:`` are extraction
inputs or noise, never crawl targets (SPEC 5.2 rule 1)."""

DEFAULT_PORTS = {"http": 80, "https": 443}

TRACKING_PARAMETERS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "gclid",
        "dclid",
        "fbclid",
        "msclkid",
        "mc_cid",
        "mc_eid",
        "igshid",
        "_ga",
        "_gl",
        "yclid",
        "wbraid",
        "gbraid",
    }
)

SESSION_PARAMETERS = frozenset(
    {
        "sid",
        "sessionid",
        "session_id",
        "phpsessid",
        "jsessionid",
        "aspsessionid",
        "cfid",
        "cftoken",
        "zenid",
    }
)

DROPPED_PARAMETERS = TRACKING_PARAMETERS | SESSION_PARAMETERS

MAXIMUM_PATH_SEGMENTS = 20
MAXIMUM_SEGMENT_REPEATS = 4
MAXIMUM_QUERY_PARAMETERS = 10
MAXIMUM_URL_LENGTH = 2048

_UNRESERVED_SAFE = "!$&'()*+,;=:@"
"""Sub-delimiters plus ``:`` and ``@``: legal in a path segment, so kept literal."""

_WWW_PREFIX = "www."


class UrlRejection(StrEnum):
    """Why a URL never became a frontier key."""

    UNSUPPORTED_SCHEME = "unsupported_scheme"
    """Not an HTTP(S) URL. Dropped silently: it was never a crawl candidate."""

    CREDENTIALS_IN_URL = "credentials_in_url"
    """The URL carried userinfo. A URL needing credentials is not public data."""

    REJECTED_SHAPE = "url_rejected_shape"
    """The spider-trap guard, or a host that is not encodable."""


SKIPPED_EXTENSIONS = frozenset(
    {
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp", ".rtf",
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".svg", ".ico", ".bmp", ".tif", ".tiff",
        ".mp3", ".mp4", ".m4a", ".m4v", ".avi", ".mov", ".wmv", ".webm", ".ogg", ".ogv", ".wav",
        ".flac",
        ".zip", ".gz", ".tar", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".dmg", ".exe", ".msi",
        ".iso", ".apk",
        ".css", ".js", ".mjs", ".map", ".woff", ".woff2", ".ttf", ".otf", ".eot",
    }
)  # fmt: skip
"""Extensions never requested at all, rejected on the URL before any HTTP call (SPEC 5.7)."""

HIGH_VALUE_PATH_PATTERN = re.compile(
    r"mentions?-?legales?"
    r"|legal(-notice)?"
    r"|impressum"
    r"|imprint"
    r"|cgu"
    r"|cgv"
    r"|terms"
    r"|contact"
    r"|nous-?contacter"
    r"|contactez"
    r"|about"
    r"|a-?propos"
    r"|qui-?sommes-?nous"
    r"|team"
    r"|equipe"
    r"|staff"
    r"|people"
    r"|direction"
    r"|management"
    r"|leadership"
    r"|privacy"
    r"|confidentialite"
    r"|rgpd"
    r"|gdpr"
    r"|donnees-?personnelles"
    r"|security"
    r"|securite"
    r"|press(e)?"
    r"|media"
    r"|investors?"
    r"|relations-?investisseurs"
)
"""SPEC 5.4. Matched against the accent-folded, lower-cased path only.

This is the candidate-path list v1.0's legal-notice source adapter carried,
demoted from "guess this URL exists" to "if this URL was discovered, fetch it
first". It never adds a request; it only reorders a queue.
"""


def canonicalize(url: str, base: str | None = None) -> str:
    """Return the frontier key for ``url``, resolved against ``base``.

    Raises:
        UrlRejectedError: the URL is not an HTTP(S) URL, carries credentials, or
            is rejected by the spider-trap guard.
    """
    raw = url.strip()
    if not raw:
        raise UrlRejectedError(UrlRejection.REJECTED_SHAPE, url, "empty URL")

    joined = urljoin(base, raw) if base else raw
    parts = urlsplit(joined)
    scheme = parts.scheme.lower()
    if scheme not in CRAWLABLE_SCHEMES:
        raise UrlRejectedError(
            UrlRejection.UNSUPPORTED_SCHEME, joined, f"scheme {scheme or '(none)'!r} is not crawled"
        )
    if parts.username or parts.password:
        # The credentials are dropped before the URL is reported, so a password
        # a site published in an href never reaches the page log or an export.
        raise UrlRejectedError(
            UrlRejection.CREDENTIALS_IN_URL,
            _without_userinfo(parts, scheme),
            "the URL carries userinfo, so it is not public data",
        )

    host = _encode_host(joined, parts.hostname or "")
    port = _explicit_port(joined, scheme)
    netloc = host if port is None else f"{host}:{port}"

    path = _normalize_path(parts.path)
    query = _clean_query(parts.query)
    canonical = urlunsplit((scheme, netloc, path, query, ""))
    _assert_shape(canonical, path, query)
    return canonical


def normalize_target(entered_value: str) -> str:
    """Return the canonical target URL for what the operator typed (SPEC FR-1).

    A bare domain becomes ``https://<domain>/``. There is deliberately no
    fallback to ``http``: an operator who needs plain HTTP types the full URL.

    Raises:
        InvalidTargetError: the value is empty or is not an HTTP(S) target.
    """
    value = entered_value.strip()
    if not value:
        raise InvalidTargetError("a target is required: type a domain or a page URL")
    candidate = value if "//" in value else f"https://{value}"
    try:
        return canonicalize(candidate)
    except UrlRejectedError as rejection:
        raise InvalidTargetError(
            f"{value!r} is not a crawlable target: {rejection.detail}"
        ) from rejection


def scope_host_of(url: str) -> str:
    """Return the scope host of ``url``: its host with one leading ``www.`` removed."""
    host = urlsplit(url).hostname or ""
    return host.lower().removeprefix(_WWW_PREFIX)


def has_skipped_extension(url: str) -> bool:
    """Whether the URL's path ends in an extension this product never requests."""
    path = urlsplit(url).path.lower()
    dot = path.rfind(".")
    slash = path.rfind("/")
    return dot > slash and path[dot:] in SKIPPED_EXTENSIONS


def is_high_value_path(url: str) -> bool:
    """Whether the URL's path matches the priority list of SPEC 5.4."""
    return HIGH_VALUE_PATH_PATTERN.search(fold(urlsplit(url).path)) is not None


@dataclass(frozen=True)
class CrawlScope:
    """The confinement rule of SPEC 5.3, derived from the target the operator named.

    Confinement goes down, never up: seed ``docs.example.com`` does not reach
    ``example.com``. No public suffix list is consulted, which is why there is no
    runtime download, no cache and no registrable-domain bug class here.
    """

    scope_host: str
    port: int | None
    include_subdomains: bool

    def contains(self, canonical_url: str) -> bool:
        """Whether ``canonical_url`` may be fetched under this scope."""
        parts = urlsplit(canonical_url)
        if parts.scheme.lower() not in CRAWLABLE_SCHEMES:
            return False
        try:
            port = parts.port
        except ValueError:
            return False
        if port != self.port:
            return False
        host = (parts.hostname or "").lower()
        if host == self.scope_host:
            return True
        if self.include_subdomains:
            return host.endswith(f".{self.scope_host}")
        return host == f"{_WWW_PREFIX}{self.scope_host}"


def scope_for(target_url: str, include_subdomains: bool) -> CrawlScope:
    """Build the scope a canonical target URL defines."""
    parts = urlsplit(target_url)
    return CrawlScope(
        scope_host=scope_host_of(target_url),
        port=parts.port,
        include_subdomains=include_subdomains,
    )


def _without_userinfo(parts: SplitResult, scheme: str) -> str:
    """Return the URL with any ``user:pass@`` removed, for reporting only."""
    host = (parts.hostname or "").lower()
    try:
        port = parts.port
    except ValueError:
        port = None
    netloc = host if port is None or port == DEFAULT_PORTS.get(scheme) else f"{host}:{port}"
    return urlunsplit((scheme, netloc, parts.path, parts.query, ""))


def _encode_host(url: str, host: str) -> str:
    """Return the host as a lower-cased IDNA A-label."""
    stripped = host.rstrip(".")
    if not stripped:
        raise UrlRejectedError(UrlRejection.REJECTED_SHAPE, url, "the URL names no host")
    if stripped.isascii():
        return stripped.lower()
    try:
        return stripped.encode("idna").decode("ascii")
    except UnicodeError as failure:
        raise UrlRejectedError(
            UrlRejection.REJECTED_SHAPE, url, f"host {stripped!r} is not IDNA-encodable"
        ) from failure


def _explicit_port(url: str, scheme: str) -> int | None:
    """Return the port, dropping the scheme's default so it never splits a key."""
    try:
        port = urlsplit(url).port
    except ValueError as failure:
        raise UrlRejectedError(
            UrlRejection.REJECTED_SHAPE, url, "the URL carries an unusable port"
        ) from failure
    return None if port == DEFAULT_PORTS[scheme] else port


def _normalize_path(path: str) -> str:
    """Resolve dot segments, collapse slash runs and re-encode consistently.

    Path case is preserved: paths are case-sensitive on most servers, and folding
    them would merge distinct resources. A trailing slash is significant and is
    preserved, because ``/a`` and ``/a/`` are different resources until the
    server says otherwise with a redirect.
    """
    if not path:
        return "/"
    trailing = path.endswith("/")
    resolved: list[str] = []
    for segment in path.split("/"):
        if segment in {"", "."}:
            continue
        if segment == "..":
            if resolved:
                resolved.pop()
            continue
        resolved.append(_requote(segment))
    normalized = "/" + "/".join(resolved)
    if trailing and not normalized.endswith("/"):
        normalized += "/"
    return normalized


def _requote(segment: str) -> str:
    """Percent-decode unreserved characters and re-encode the rest in upper-case hex."""
    decoded = unquote(segment, encoding="utf-8", errors="surrogateescape")
    return quote(decoded, safe=_UNRESERVED_SAFE, encoding="utf-8", errors="surrogateescape")


def _clean_query(query: str) -> str:
    """Drop tracking and session parameters, then sort what remains.

    Sorting is what stops ``?a=1&b=2`` and ``?b=2&a=1`` from doubling the frontier.
    """
    if not query:
        return ""
    kept = [
        (name, value)
        for name, value in parse_qsl(query, keep_blank_values=True)
        if name.lower() not in DROPPED_PARAMETERS
    ]
    if not kept:
        return ""
    kept.sort()
    return urlencode(kept, quote_via=quote)


def _assert_shape(canonical: str, path: str, query: str) -> None:
    """Apply the spider-trap guard of SPEC 5.2."""
    segments = [segment for segment in path.split("/") if segment]
    if len(segments) > MAXIMUM_PATH_SEGMENTS:
        raise UrlRejectedError(
            UrlRejection.REJECTED_SHAPE,
            canonical,
            f"{len(segments)} path segments exceeds {MAXIMUM_PATH_SEGMENTS}",
        )
    repeats = Counter(segments)
    if repeats and max(repeats.values()) > MAXIMUM_SEGMENT_REPEATS:
        raise UrlRejectedError(
            UrlRejection.REJECTED_SHAPE,
            canonical,
            f"a path segment repeats more than {MAXIMUM_SEGMENT_REPEATS} times",
        )
    if query and len(query.split("&")) > MAXIMUM_QUERY_PARAMETERS:
        raise UrlRejectedError(
            UrlRejection.REJECTED_SHAPE,
            canonical,
            f"more than {MAXIMUM_QUERY_PARAMETERS} query parameters after cleaning",
        )
    if len(canonical) > MAXIMUM_URL_LENGTH:
        raise UrlRejectedError(
            UrlRejection.REJECTED_SHAPE,
            canonical,
            f"canonical length {len(canonical)} exceeds {MAXIMUM_URL_LENGTH}",
        )
