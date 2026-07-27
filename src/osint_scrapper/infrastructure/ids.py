"""Run identifiers."""

from __future__ import annotations

import uuid

RUN_ID_PREFIX = "r-"
_RANDOM_CHARACTERS = 8


class UuidRunIdGenerator:
    """Short, collision-resistant run identifiers derived from a random UUID."""

    def new_run_id(self) -> str:
        """Return a fresh identifier such as ``r-8f3a2c19``."""
        return f"{RUN_ID_PREFIX}{uuid.uuid4().hex[:_RANDOM_CHARACTERS]}"
