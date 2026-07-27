"""OSINT_scrapper: crawls one website and exports the OSINT information it publishes.

The package is layered as mandated by ``.claude/rules/architecture.md``:
``domain`` (stdlib only) <- ``application`` <- ``infrastructure`` / ``interfaces``.
Qt lives in ``interfaces`` and nowhere else (SPEC NFR-2).
"""

__version__ = "0.2.0"

TOOL_NAME = "osint-scrapper"
PRODUCT_TOKEN = "OSINT-Scrapper"
SCHEMA_VERSION = "2.0"
