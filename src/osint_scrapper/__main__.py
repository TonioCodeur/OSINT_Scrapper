"""Allows ``python -m osint_scrapper``, which launches the graphical application."""

from __future__ import annotations

import sys

from osint_scrapper.interfaces.launcher import main

if __name__ == "__main__":
    sys.exit(main())
