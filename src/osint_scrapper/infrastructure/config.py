"""Configuration loading and writing (SPEC 7.7).

Precedence is interface control > environment > config file > built-in default.
A value outside the bounds of SPEC 5.5 is clamped rather than refused, and every
clamp is reported as data so the Settings pane can show it — a clamp the operator
cannot see is a silent change to what the application is about to do.
"""

from __future__ import annotations

import logging
import os
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from email_validator import EmailNotValidError, validate_email

from osint_scrapper.application.errors import ConfigurationError
from osint_scrapper.domain.target import (
    DEFAULT_CONCURRENT_REQUESTS,
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_PAGES,
    DEFAULT_PHONE_REGION,
    DEFAULT_REQUEST_INTERVAL_SECONDS,
    DEFAULT_RETENTION_DAYS,
    MAXIMUM_CONCURRENT_REQUESTS,
    MAXIMUM_MAX_DEPTH,
    MAXIMUM_MAX_PAGES,
    MAXIMUM_REQUEST_INTERVAL_SECONDS,
    MAXIMUM_RETENTION_DAYS,
    MINIMUM_CONCURRENT_REQUESTS,
    MINIMUM_MAX_DEPTH,
    MINIMUM_MAX_PAGES,
    MINIMUM_REQUEST_INTERVAL_SECONDS,
    MINIMUM_RETENTION_DAYS,
    CrawlSettings,
    PurposeCategory,
)

logger = logging.getLogger(__name__)

CONFIG_FILE_NAME = "osint-scrapper.toml"
USER_CONFIG_RELATIVE_PATH = Path("osint-scrapper") / "config.toml"

ENV_CONTACT_EMAIL = "OSINT_SCRAPPER_CONTACT_EMAIL"
ENV_PROJECT_URL = "OSINT_SCRAPPER_PROJECT_URL"
ENV_OUTPUT_DIR = "OSINT_SCRAPPER_OUTPUT_DIR"

DEFAULT_PROJECT_URL = "https://github.com/TonioCodeur/OSINT_Scrapper"
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_OUTPUT_DIRECTORY = "runs"
DEFAULT_FORMATS = ("json", "csv", "xlsx")


@dataclass(frozen=True)
class ClampReport:
    """One value the configuration file asked for and did not get."""

    key: str
    requested: str
    applied: str

    def __str__(self) -> str:
        return f"{self.key}: {self.requested} is out of range, using {self.applied}"


@dataclass(frozen=True)
class AppConfig:
    """Everything a run needs that is not a per-run argument."""

    contact_email: str | None = None
    project_url: str = DEFAULT_PROJECT_URL
    request_interval_seconds: float = DEFAULT_REQUEST_INTERVAL_SECONDS
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_MAX_RETRIES
    concurrent_requests: int = DEFAULT_CONCURRENT_REQUESTS
    max_pages: int = DEFAULT_MAX_PAGES
    max_depth: int = DEFAULT_MAX_DEPTH
    include_subdomains: bool = True
    follow_sitemap: bool = True
    phone_region: str = DEFAULT_PHONE_REGION
    purpose_category: PurposeCategory = PurposeCategory.DUE_DILIGENCE
    purpose_note: str = ""
    output_directory: Path = Path(DEFAULT_OUTPUT_DIRECTORY)
    retention_days: int = DEFAULT_RETENTION_DAYS
    formats: tuple[str, ...] = DEFAULT_FORMATS
    clamps: tuple[ClampReport, ...] = field(default_factory=tuple)
    """What the file asked for and did not get. Rendered by the Settings pane."""

    def require_contact_email(self) -> str:
        """Return the contact email, refusing the run if there is none (SPEC FR-20).

        The tool will not put a User-Agent on the wire that nobody can answer.

        Raises:
            ConfigurationError: no contact email was configured, or it is invalid.
        """
        if not self.contact_email:
            raise ConfigurationError(
                f"no contact email configured: set {ENV_CONTACT_EMAIL}, "
                f"or [http].contact_email in {CONFIG_FILE_NAME}"
            )
        try:
            validated = validate_email(self.contact_email, check_deliverability=False)
        except EmailNotValidError as invalid:
            raise ConfigurationError(
                f"contact email {self.contact_email!r} is invalid: {invalid}"
            ) from invalid
        return validated.normalized

    def crawl_settings(self) -> CrawlSettings:
        """Build the domain settings this configuration implies.

        Every value is already inside its bounds, because loading clamped them;
        ``CrawlSettings`` still raises for anything constructed directly, so the
        bound cannot be bypassed in code (AC-UI-6).
        """
        return CrawlSettings(
            max_pages=self.max_pages,
            max_depth=self.max_depth,
            request_interval_seconds=self.request_interval_seconds,
            concurrent_requests=self.concurrent_requests,
            include_subdomains=self.include_subdomains,
            follow_sitemap=self.follow_sitemap,
            phone_region=self.phone_region,
            retention_days=self.retention_days,
        )


def default_config_paths(explicit: Path | None = None) -> tuple[Path, ...]:
    """Return the candidate configuration files in precedence order (SPEC 7.7)."""
    if explicit is not None:
        return (explicit,)
    xdg = os.environ.get("XDG_CONFIG_HOME")
    user_base = Path(xdg) if xdg else Path.home() / ".config"
    return (Path.cwd() / CONFIG_FILE_NAME, user_base / USER_CONFIG_RELATIVE_PATH)


def load_config(explicit_path: Path | None = None) -> AppConfig:
    """Load the first configuration file that exists, then apply environment overrides.

    Raises:
        ConfigurationError: an explicitly requested file is missing or malformed.
    """
    return _apply_environment(_from_file(explicit_path))


def writable_config_path(explicit: Path | None = None) -> Path:
    """Return the first candidate path this process could write (SPEC 7.7)."""
    candidates = default_config_paths(explicit)
    for candidate in candidates:
        parent = candidate.parent
        if candidate.is_file() and os.access(candidate, os.W_OK):
            return candidate
        if parent.is_dir() and os.access(parent, os.W_OK):
            return candidate
    return candidates[-1]


def save_config(config: AppConfig, path: Path) -> Path:
    """Write ``config`` as TOML and return the path written.

    Raises:
        ConfigurationError: the file could not be written.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(as_toml(config), encoding="utf-8")
    except OSError as failure:
        raise ConfigurationError(f"cannot write config {path}: {failure}") from failure
    return path


def as_toml(config: AppConfig) -> str:
    """Render the configuration in the documented file shape (SPEC 7.7)."""
    formats = ", ".join(f'"{name}"' for name in config.formats)
    return "\n".join(
        (
            "[http]",
            f'contact_email = "{config.contact_email or ""}"',
            f'project_url = "{config.project_url}"',
            f"request_interval_seconds = {config.request_interval_seconds}",
            f"timeout_seconds = {config.timeout_seconds}",
            f"max_retries = {config.max_retries}",
            f"concurrent_requests = {config.concurrent_requests}",
            "",
            "[crawl]",
            f"max_pages = {config.max_pages}",
            f"max_depth = {config.max_depth}",
            f"include_subdomains = {str(config.include_subdomains).lower()}",
            f"follow_sitemap = {str(config.follow_sitemap).lower()}",
            f'phone_region = "{config.phone_region}"',
            "",
            "[purpose]",
            f'category = "{config.purpose_category}"',
            f'note = "{config.purpose_note}"',
            "",
            "[output]",
            f'directory = "{config.output_directory.as_posix()}"',
            f"retention_days = {config.retention_days}",
            f"formats = [{formats}]",
            "",
        )
    )


def _from_file(explicit_path: Path | None) -> AppConfig:
    for candidate in default_config_paths(explicit_path):
        if not candidate.is_file():
            continue
        try:
            document = tomllib.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as failure:
            raise ConfigurationError(f"cannot read config {candidate}: {failure}") from failure
        logger.debug("loaded configuration from %s", candidate)
        return _from_document(document)

    if explicit_path is not None:
        raise ConfigurationError(f"config file not found: {explicit_path}")
    return AppConfig()


def _from_document(document: dict[str, Any]) -> AppConfig:
    http = _section(document, "http")
    crawl = _section(document, "crawl")
    purpose = _section(document, "purpose")
    output = _section(document, "output")
    clamps: list[ClampReport] = []

    directory = output.get("directory")
    return AppConfig(
        contact_email=_optional_str(http, "contact_email"),
        project_url=_optional_str(http, "project_url") or DEFAULT_PROJECT_URL,
        request_interval_seconds=_clamped(
            clamps,
            "request_interval_seconds",
            _number(http, "request_interval_seconds", DEFAULT_REQUEST_INTERVAL_SECONDS),
            MINIMUM_REQUEST_INTERVAL_SECONDS,
            MAXIMUM_REQUEST_INTERVAL_SECONDS,
        ),
        timeout_seconds=_number(http, "timeout_seconds", DEFAULT_TIMEOUT_SECONDS),
        max_retries=int(_number(http, "max_retries", DEFAULT_MAX_RETRIES)),
        concurrent_requests=int(
            _clamped(
                clamps,
                "concurrent_requests",
                _number(http, "concurrent_requests", DEFAULT_CONCURRENT_REQUESTS),
                MINIMUM_CONCURRENT_REQUESTS,
                MAXIMUM_CONCURRENT_REQUESTS,
            )
        ),
        max_pages=int(
            _clamped(
                clamps,
                "max_pages",
                _number(crawl, "max_pages", DEFAULT_MAX_PAGES),
                MINIMUM_MAX_PAGES,
                MAXIMUM_MAX_PAGES,
            )
        ),
        max_depth=int(
            _clamped(
                clamps,
                "max_depth",
                _number(crawl, "max_depth", DEFAULT_MAX_DEPTH),
                MINIMUM_MAX_DEPTH,
                MAXIMUM_MAX_DEPTH,
            )
        ),
        include_subdomains=_boolean(crawl, "include_subdomains", True),
        follow_sitemap=_boolean(crawl, "follow_sitemap", True),
        phone_region=(_optional_str(crawl, "phone_region") or DEFAULT_PHONE_REGION).upper(),
        purpose_category=_purpose_category(purpose, clamps),
        purpose_note=_optional_str(purpose, "note") or "",
        output_directory=(
            Path(directory) if isinstance(directory, str) else Path(DEFAULT_OUTPUT_DIRECTORY)
        ),
        retention_days=int(
            _clamped(
                clamps,
                "retention_days",
                _number(output, "retention_days", DEFAULT_RETENTION_DAYS),
                MINIMUM_RETENTION_DAYS,
                MAXIMUM_RETENTION_DAYS,
            )
        ),
        formats=_formats(output),
        clamps=tuple(clamps),
    )


def _apply_environment(config: AppConfig) -> AppConfig:
    contact = os.environ.get(ENV_CONTACT_EMAIL)
    project_url = os.environ.get(ENV_PROJECT_URL)
    output_directory = os.environ.get(ENV_OUTPUT_DIR)
    return replace(
        config,
        contact_email=contact or config.contact_email,
        project_url=project_url or config.project_url,
        output_directory=Path(output_directory) if output_directory else config.output_directory,
    )


def _clamped(
    clamps: list[ClampReport], key: str, value: float, minimum: float, maximum: float
) -> float:
    applied = min(max(value, minimum), maximum)
    if applied != value:
        clamps.append(ClampReport(key=key, requested=str(value), applied=str(applied)))
    return applied


def _purpose_category(section: dict[str, Any], clamps: list[ClampReport]) -> PurposeCategory:
    raw = _optional_str(section, "category")
    if raw is None:
        return PurposeCategory.DUE_DILIGENCE
    try:
        return PurposeCategory(raw)
    except ValueError:
        clamps.append(
            ClampReport(
                key="purpose.category",
                requested=raw,
                applied=str(PurposeCategory.DUE_DILIGENCE),
            )
        )
        return PurposeCategory.DUE_DILIGENCE


def _formats(section: dict[str, Any]) -> tuple[str, ...]:
    raw = section.get("formats")
    if raw is None:
        return DEFAULT_FORMATS
    if not isinstance(raw, Sequence) or isinstance(raw, str):
        raise ConfigurationError("formats must be an array of strings")
    return tuple(str(name).lower() for name in raw)


def _section(document: dict[str, Any], name: str) -> dict[str, Any]:
    section = document.get(name, {})
    if not isinstance(section, dict):
        raise ConfigurationError(f"[{name}] must be a table")
    return section


def _optional_str(section: dict[str, Any], key: str) -> str | None:
    value = section.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigurationError(f"{key} must be a string")
    return value


def _boolean(section: dict[str, Any], key: str, default: bool) -> bool:
    value = section.get(key, default)
    if not isinstance(value, bool):
        raise ConfigurationError(f"{key} must be a boolean")
    return value


def _number(section: dict[str, Any], key: str, default: float) -> float:
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigurationError(f"{key} must be a number")
    return float(value)
