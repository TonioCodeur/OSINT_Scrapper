# Rule 2 — Prefer widely adopted libraries

## Principle

When a dependency is needed, choose the option with the largest, most active adoption in the Python ecosystem for that job. Popularity here is a proxy for what actually matters: maintained releases, documented behavior, answered edge cases, and a low chance of the project being abandoned mid-life.

Do **not** pick a library because it is clever, newer, or benchmarks marginally faster. That trade is rarely worth the maintenance risk on a project meant to run against third-party sites for a long time.

## How to decide

Before adding any dependency, check in this order:

1. **Standard library first.** No dependency beats no dependency. `pathlib`, `dataclasses`, `datetime`, `json`, `csv`, `sqlite3`, `logging`, `argparse` cover more than expected.
2. **Is it already in the project?** Do not add a second HTTP client, a second parser, or a second validation library. Reuse what is declared.
3. **Adoption signals**, in this order: download volume, release cadence over the last 12 months, open-issue responsiveness, presence of type hints and a real changelog.
4. **License compatibility** with the project.

State the reasoning in the PR/commit when a dependency is added — one line on what it replaces and why the standard library was not enough.

## Verification, not assumption

Library popularity shifts and my training data has a cutoff. Do not assert "X is the standard choice" from memory. Confirm the current state before committing to a dependency — see [documentation.md](documentation.md).

## Pinning

Pin direct dependencies with a lockfile. Unpinned scraping dependencies break silently when a parser changes its behavior between minor versions.
