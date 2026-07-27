"""The layering rules of NFR-1 to NFR-3, enforced instead of documented."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

import osint_scrapper
from osint_scrapper.application.ports import PageFetcher

SOURCE_ROOT = Path(osint_scrapper.__file__).parent

FORBIDDEN_THIRD_PARTY = {"requests", "bs4", "openpyxl", "phonenumbers", "email_validator"}

QT_PACKAGES = {"PySide6", "PyQt6", "PyQt5", "PySide2"}
"""NFR-2: Qt lives in ``interfaces/`` and nowhere else. This is what keeps the
whole product testable without a ``QApplication``."""

RETIRED_VOCABULARY = (
    "SourceDescriptor",
    "SourceAdapter",
    "SourceRegistry",
    "source_id",
    "match_basis",
    "MatchBasis",
    "ValueType",
    "subject_key",
    "PersonProfile",
    "identity_unconfirmed",
    "InvestigationReport",
)
"""AC-ARCH-4: the person-search product is withdrawn, and none of its vocabulary
may survive in a name, a field or a string anywhere under ``src/``."""

COMPOSITION_ROOT = "interfaces/app.py"
SINGLE_INSTANTIATION = {
    "RequestsPageFetcher(": "requests_fetcher.py",
    "RobotsTxtPolicy(": "robots.py",
    "PerHostRateLimiter(": "rate_limit.py",
    "CrawlSiteUseCase(": "crawl.py",
}
"""AC-ARCH-5: wiring happens exactly once, and a review can grep for it.

The value is the module that declares the class, which naturally contains its
own name and is therefore not a second wiring site.
"""


def _modules(package: str) -> list[Path]:
    found = sorted((SOURCE_ROOT / package).rglob("*.py"))
    assert found, f"no module found under {package}: the boundary rule would go unenforced"
    return found


def _all_modules() -> list[Path]:
    return sorted(SOURCE_ROOT.rglob("*.py"))


def _absolute_module(path: Path, node: ast.ImportFrom) -> str:
    """Resolve a relative import against the importing module's own package.

    ``from ..infrastructure.http import robots`` inside ``domain/`` must be seen
    as ``osint_scrapper.infrastructure.http.robots``, otherwise the very
    upward-pointing import NFR-1 forbids is the one the test cannot see.
    """
    package_parts = ("osint_scrapper", *path.relative_to(SOURCE_ROOT).parts[:-1])
    ascended = package_parts[: len(package_parts) - (node.level - 1)]
    return ".".join((*ascended, node.module)) if node.module else ".".join(ascended)


def _imported_roots(path: Path) -> set[str]:
    """Every module this file imports, with relative imports resolved to absolute."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            absolute = node.module if node.level == 0 else _absolute_module(path, node)
            if absolute:
                roots.add(absolute)
    return roots


def _string_constants(path: Path) -> set[str]:
    """Every string literal in the file, so a dynamic import cannot hide a name."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _is_allowed(module: str, allowed_internal: tuple[str, ...]) -> bool:
    if module.split(".")[0] in sys.stdlib_module_names:
        return True
    return any(module == prefix or module.startswith(f"{prefix}.") for prefix in allowed_internal)


@pytest.mark.parametrize("path", _modules("domain"), ids=lambda item: item.name)
def test_domain_imports_only_the_standard_library(path: Path) -> None:
    """AC-ARCH-1: the domain layer has zero external dependencies."""
    offenders = {
        module
        for module in _imported_roots(path)
        if not _is_allowed(module, ("osint_scrapper.domain",))
    }
    assert not offenders, f"{path.name} imports {sorted(offenders)}"


@pytest.mark.parametrize("path", _modules("application"), ids=lambda item: item.name)
def test_application_imports_only_stdlib_and_inner_layers(path: Path) -> None:
    """AC-ARCH-2: the application layer knows the domain and nothing outside it."""
    offenders = {
        module
        for module in _imported_roots(path)
        if not _is_allowed(module, ("osint_scrapper.domain", "osint_scrapper.application"))
    }
    assert not offenders, f"{path.name} imports {sorted(offenders)}"


@pytest.mark.parametrize("package", ["domain", "application"])
def test_inner_layers_never_import_a_scraping_library(package: str) -> None:
    """The specific packages NFR-1 names must not appear in the inner layers."""
    for path in _modules(package):
        roots = {module.split(".")[0] for module in _imported_roots(path)}
        assert not roots & FORBIDDEN_THIRD_PARTY, f"{path} imports a third-party package"


@pytest.mark.parametrize("path", _all_modules(), ids=lambda item: item.name)
def test_qt_is_confined_to_the_interfaces_package(path: Path) -> None:
    """AC-ARCH-3: no module outside ``interfaces/`` may import PySide6 in any form.

    Both spellings are covered — ``import PySide6…`` and ``from PySide6…`` — and
    so is a dynamic ``importlib`` reference, because a string is all it takes to
    reintroduce the coupling this rule exists to prevent.
    """
    if path.relative_to(SOURCE_ROOT).parts[0] == "interfaces":
        return
    imported = {module.split(".")[0] for module in _imported_roots(path)}
    assert not imported & QT_PACKAGES, f"{path} imports Qt outside interfaces/"
    named = {value.split(".")[0] for value in _string_constants(path)}
    assert not named & QT_PACKAGES, f"{path} names Qt in a string outside interfaces/"


@pytest.mark.parametrize("path", _all_modules(), ids=lambda item: item.name)
def test_no_person_search_vocabulary_survives(path: Path) -> None:
    """AC-ARCH-4: v0.1.0's subject-and-sources model is withdrawn, not renamed."""
    text = path.read_text(encoding="utf-8")
    offenders = [name for name in RETIRED_VOCABULARY if name in text]
    assert not offenders, f"{path} still mentions {offenders}"


def test_the_composition_root_is_unique() -> None:
    """AC-ARCH-5: exactly one module wires the adapters together."""
    for symbol, declaring_module in SINGLE_INSTANTIATION.items():
        callers = sorted(
            path.relative_to(SOURCE_ROOT).as_posix()
            for path in _all_modules()
            if symbol in path.read_text(encoding="utf-8") and path.name != declaring_module
        )
        assert callers in ([], [COMPOSITION_ROOT]), f"{symbol} is instantiated in {callers}"


def test_the_fetcher_is_the_only_thing_that_composes_robots_and_rate_limiting() -> None:
    """SPEC 6.1: robots and rate limiting live inside the fetcher, not in callers."""
    import inspect

    from osint_scrapper.infrastructure.http.requests_fetcher import RequestsPageFetcher

    parameters = inspect.signature(RequestsPageFetcher.__init__).parameters
    assert "robots_policy" in parameters
    assert "rate_limiter" in parameters
    assert hasattr(PageFetcher, "fetch")


def test_the_crawl_receives_a_fetcher_and_nothing_else_that_reaches_the_network() -> None:
    """SPEC 6.1: never a session, never a robots policy, never a rate limiter."""
    import inspect

    from osint_scrapper.application.crawl import CrawlSiteUseCase

    parameters = inspect.signature(CrawlSiteUseCase.__init__).parameters
    annotations = {str(parameter.annotation) for parameter in parameters.values()}
    forbidden = {"Session", "RobotsPolicy", "RateLimiter", "RobotsTxtPolicy", "PerHostRateLimiter"}
    assert not any(name in annotation for annotation in annotations for name in forbidden)
    assert "fetcher" in parameters


NETWORK_MODULES = {
    "requests",
    "urllib3",
    "urllib.request",
    "http.client",
    "socket",
    "osint_scrapper.infrastructure.http.robots",
    "osint_scrapper.infrastructure.http.rate_limit",
    "osint_scrapper.infrastructure.http.requests_fetcher",
}
"""Anything that could reach the network without passing the fetcher's gates."""


@pytest.mark.parametrize(
    "path",
    _modules("infrastructure/extraction") + _modules("infrastructure/discovery"),
    ids=lambda item: item.name,
)
def test_no_parser_can_reach_the_network_itself(path: Path) -> None:
    """A parser reads a document it was handed; it never goes and gets one.

    Denying the import is what makes bypassing robots.txt and the rate limiter
    impossible, rather than merely discouraged.
    """
    offenders = _imported_roots(path) & NETWORK_MODULES
    assert not offenders, f"{path.name} can reach the network directly via {sorted(offenders)}"


def test_thread_termination_is_never_used() -> None:
    """AC-UI-3: ``QThread.terminate`` can leave a half-written file, so it is banned."""
    pattern = re.compile(r"\.terminate\s*\(")
    offenders = [
        path.relative_to(SOURCE_ROOT).as_posix()
        for path in _all_modules()
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"{offenders} call terminate(), which breaks the stop guarantee"


def test_the_boundary_check_sees_through_a_relative_import() -> None:
    """The resolver itself must not be the hole: a relative import is a real import.

    ``from ..infrastructure import robots`` inside ``domain/`` is precisely the
    violation NFR-1 forbids, and it is invisible to a checker that only reads
    absolute imports.
    """
    module = ast.parse("from ..infrastructure.http import robots").body[0]
    assert isinstance(module, ast.ImportFrom)
    resolved = _absolute_module(SOURCE_ROOT / "domain" / "report.py", module)
    assert resolved == "osint_scrapper.infrastructure.http"
    assert not _is_allowed(resolved, ("osint_scrapper.domain",))


def test_the_qt_rule_would_catch_a_dynamic_import(tmp_path: Path) -> None:
    """The rule must not be satisfiable by ``importlib.import_module("PySide6")``.

    The real helper is what is exercised here, on a real file: re-implementing
    the scan inside the test would let the shipped helper be gutted without
    anything going red.
    """
    module = tmp_path / "smuggled_qt.py"
    module.write_text(
        'import importlib\nimportlib.import_module("PySide6.QtWidgets")\n', encoding="utf-8"
    )
    assert not _imported_roots(module) & QT_PACKAGES, (
        "the import half of the rule cannot see this, which is why the string scan exists"
    )
    named = {value.split(".")[0] for value in _string_constants(module)}
    assert named & QT_PACKAGES
