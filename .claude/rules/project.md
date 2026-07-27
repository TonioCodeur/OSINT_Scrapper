# Rule 0 — What this application is

## One-line definition

A Python application for conducting OSINT research by scraping websites for publicly available information.

## What that means concretely

The user supplies a **research target** (a term, a name, a domain, an identifier). The application queries a set of **public web sources**, extracts structured data from their pages, and returns consolidated, traceable results.

The core loop is:

```
target → source selection → fetch → parse → normalize → deduplicate → report
```

Each stage is a distinct responsibility and must stay separable (see [architecture.md](architecture.md)):

- **Source selection** — which sites can answer this kind of query. Adding a source must not require editing the pipeline.
- **Fetch** — HTTP retrieval, subject to rate limiting, retry/backoff, `robots.txt` checks, and an honest `User-Agent`. This is a port; the network is never called from business logic.
- **Parse** — turning a page into raw fields. Site-specific and the most fragile part of the system: parsers break when sites change their markup, so they are isolated per source and independently testable against saved fixtures.
- **Normalize** — mapping heterogeneous source fields onto the project's own domain entities. Downstream code sees one vocabulary, not per-site shapes.
- **Deduplicate** — the same fact arriving from several sources is one record with several sources, not several records.
- **Report** — output for a human or a downstream tool.

## Non-negotiable properties

- **Traceability.** Every emitted record carries its source URL and a collection timestamp. A result no one can attribute is worthless in OSINT.
- **Partial failure is normal.** A source being down, rate-limiting, or having changed its markup must degrade that source only — never abort the whole run. Report which sources failed rather than silently returning less.
- **Scraping is best-effort by nature.** Parsers must fail loudly and specifically ("selector X not found on source Y") rather than returning empty or half-filled records that look like real answers.
- **Legality is a design constraint, not a disclaimer.** Public data only, terms of service honored, targets never degraded. The full list is in `CLAUDE.md`.

## Open decisions

Not yet chosen — do not assume any of these; confirm with the user before building on one:

- HTTP client and parsing stack, and whether a scraping framework is warranted over a plain client (governed by [dependencies.md](dependencies.md)).
- Synchronous or asynchronous fetching.
- Entry point: CLI, API, or library.
- Persistence: whether results are stored at all, and in what format.
- The initial set of sources.
