# Rule 1 — Clean Code, Clean Architecture, SOLID

## Layering

Keep the dependency rule absolute: **source code dependencies point inward only**. Outer layers know about inner layers, never the reverse.

```
domain/          entities, value objects, business rules — zero external imports
application/     use cases orchestrating the domain; declares the ports (interfaces) it needs
infrastructure/  adapters implementing those ports (HTTP clients, parsers, storage, config)
interfaces/      entry points (CLI, API) — wiring and I/O only
```

Concretely for this project: a `domain` module must not import `httpx`, `bs4`, or any scraping library. Fetching a page is a port (`PageFetcher`) declared by the application layer and implemented in `infrastructure`. This is what makes the scraper testable without network access and lets a source be swapped without touching business rules.

## SOLID

- **S** — one reason to change per class/module. A scraper that fetches, parses, *and* persists is three responsibilities; split them.
- **O** — adding a new site must mean adding a new adapter, never editing a `if source == "...":` chain. Register implementations, don't branch on type.
- **L** — every implementation of a port must honor its contract, including error behavior. An adapter that raises where the port promises `None` breaks callers.
- **I** — narrow ports. A consumer that only reads should not depend on an interface exposing writes.
- **D** — depend on abstractions. Inject collaborators through the constructor; do not instantiate concrete adapters inside use cases, and do not reach for module-level singletons.

## Clean code

- Names state intent: `fetch_public_profile`, not `get_data`. No abbreviations that are not domain terms.
- Small functions, single level of abstraction per function. If a function mixes orchestration and byte-level parsing, extract.
- Comments explain *why*, never *what* — restating the code is noise that rots.
- No dead code, no commented-out blocks, no speculative generality: build what the current requirement needs.
- Errors are explicit: raise typed domain exceptions, never return sentinel values or swallow exceptions with a bare `except`.
- Type hints on every public function signature; they are part of the contract.
- Composition over inheritance. Inherit only for genuine substitutability.
