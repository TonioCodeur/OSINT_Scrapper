"""The process entry point (SPEC 4).

There is no CLI product. This parses exactly three arguments, configures
logging, and launches the graphical application. There is no ``--target``, no
``--purpose`` and no headless run flag: a second fully-supported surface would
mean a second set of exit codes, a second rendering path and a second set of
acceptance criteria to keep honest.

Logs go to stderr and never into the interface's data views.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from osint_scrapper import TOOL_NAME, __version__

LOG_LEVELS: Final = ("debug", "info", "warning", "error")

EXIT_OK: Final = 0
EXIT_USAGE: Final = 2
EXIT_ENVIRONMENT: Final = 3


def build_parser() -> argparse.ArgumentParser:
    """Return the parser for the three arguments the application accepts."""
    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description=(
            "Crawl one website you name and export the contact and identity "
            "information it publishes. Launches the graphical application."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="configuration file to load instead of the default search order",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=LOG_LEVELS,
        help="log verbosity; logs go to stderr (default: info)",
    )
    parser.add_argument(
        "--version", action="store_true", help="print the version and exit"
    )
    return parser


def configure_logging(level_name: str) -> None:
    """Send every log record to stderr."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level_name.upper()))


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and start the application. Returns the process exit code."""
    parser = build_parser()
    arguments = parser.parse_args(argv)

    if arguments.version:
        print(f"{TOOL_NAME} {__version__}")
        return EXIT_OK

    configure_logging(arguments.log_level)

    from osint_scrapper.application.errors import ConfigurationError
    from osint_scrapper.interfaces.app import run

    try:
        return run(sys.argv[:1], arguments.config)
    except ConfigurationError as failure:
        # The configuration is read before any window exists, so this is the one
        # failure that has nowhere in the interface to appear.
        logging.getLogger(TOOL_NAME).error("configuration error: %s", failure)
        return EXIT_ENVIRONMENT


if __name__ == "__main__":  # pragma: no cover - exercised through the console script
    sys.exit(main())
