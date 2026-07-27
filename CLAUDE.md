# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Repository: <https://github.com/TonioCodeur/OSINT_Scrapper>

## Language rule — non-negotiable

**Every file in this repository is written in English.** Specification, README, code, comments,
docstrings, log messages, exception messages, and every label, tooltip and message in the graphical
interface. The user writes in French; the files stay English. The sole exception is `README.fr.md`, whose
*prose* is French and whose filenames, code blocks, config keys and column names are not.

## Repository state

**v0.2.0 is a full refactor and a change of product.** v0.1.0 was a CLI that searched for a named natural
person across four legally-vetted sources; that product is withdrawn. v0.2.0 is a **Qt desktop application
that crawls one website and extracts the OSINT information it publishes**.

- `docs/SPEC.md` (v2.0) is authoritative and binding. It supersedes the v1.0 specification in full.
- `docs/MIGRATION.md` is the demolition plan: what is kept, reworked, rewritten or deleted, and why.
- `README.md` / `README.fr.md` document the shipped behavior for users.
- `THIRD_PARTY_LICENSES.md` is a licence obligation, not documentation — see [Licensing](#licensing).

If the specification and the code disagree, that is a defect in one of them; raise it rather than picking
a side silently.

## Purpose

The operator supplies a **target** — a domain (`example.com`) or a page URL. The application crawls that
site, breadth-first and politely, within a hard page budget and depth limit, extracts published contact
and identity information, and exports it fully attributed to JSON, CSV, XLSX, JSONL and Markdown.

```
target → scope → crawl (frontier · robots · rate limit) → extract → validate → aggregate → export
```

**There is no subject, no person input and no source registry.** If you find `Subject`, `PersonProfile`,
`SourceDescriptor`, `SourceAdapter`, `match_basis`, `subject_key` or `identity_unconfirmed` anywhere in
`src/`, it is v0.1.0 residue and a boundary test is supposed to be failing.

## Build, lint, run and test

The virtual environment is `.venv`. `pyproject.toml` requires `>=3.11,<3.15`; the reference interpreter is
CPython 3.12 on Windows 11 (NFR-13), which is what the current `.venv` holds and what the acceptance
criteria are demonstrated on. Any interpreter in that range works — but an existing `.venv` is **not**
upgraded in place by changing this line: recreate it (`py -3.12 -m venv .venv`) and re-run `uv sync`, or the
environment and the declared floor will disagree silently. Dependencies are resolved by `uv` and pinned in
`uv.lock`.

```bash
uv sync --extra dev     # install runtime and dev dependencies
pytest                  # the full suite; must be green
ruff check .            # lint; must be clean
ruff check . --fix      # auto-fixable subset
mypy src                # strict type checking; must be clean
```

Run the application with `osint-scrapper` or `python -m osint_scrapper`. **Both open the GUI.** The console
script accepts exactly three arguments — `--config PATH`, `--log-level {debug,info,warning,error}`,
`--version` — and nothing else. There is no `investigate`, `sources` or `erase` subcommand, and no headless
run mode. Do not add one without changing the specification first.

**Headless test runs need Qt's offscreen platform plugin:**

```bash
# Windows (PowerShell)
$env:QT_QPA_PLATFORM = "offscreen"; pytest

# Linux and macOS
QT_QPA_PLATFORM=offscreen pytest
```

Most of the suite does not need it: the product is deliberately built so that the entire crawl runs
without a `QApplication`. Only the thin widget smoke tests do.

### Test rules that do not bend

**The test suite must never open a socket.** An autouse fixture in `tests/conftest.py` patches
`socket.socket` and `socket.create_connection` to raise. Parsers and the crawl are tested against saved
fixtures, and **no fixture may contain a real person's data** — use invented names on `example.com` /
`example.org`.

`tests/test_end_to_end.py` runs the whole chain — real crawl loop, real frontier, real URL
canonicalization, real robots policy, real rate limiter, real extraction pipeline, real aggregator, real
writers — over the committed fixture site in `tests/fixtures/site/`, faking only the `PageFetcher`, the
clock and the sleeper, and asserts on the emitted `report.json`, `report.csv`, `report_pages.csv`,
`report.xlsx`, `report.jsonl` and `report.md`. It is the only test that would catch a drift between what
an extractor puts in a `RawField` and what the aggregator expects; a change that keeps both sides
consistent with their own fakes still fails here. **Do not replace its real collaborators with stubs.**

## Architecture

Dependencies point inward only. Enforced by `tests/test_architecture_boundaries.py`, which parses every
module with `ast`; do not weaken those tests.

```
src/osint_scrapper/
  domain/          entities, value objects, business rules — standard library ONLY
    url.py           canonicalize(), in_scope(), the spider-trap guard
    target.py        CrawlTarget, CrawlSettings (bounds enforced here), Purpose, PurposeCategory
    crawl.py         PageStatus, PageOutcome, CrawlOutcome
    attributes.py    FieldName, ExtractionLayer, RawField, Provenance, Finding
    confidence.py    the layer base-score table, and nothing else
    report.py        SiteReport
    errors.py        DomainError hierarchy
  application/     use cases; standard library + domain only
    ports.py         every Protocol, plus FetchedPage, RobotsDecision, CrawlObserver,
                     CancellationToken, LinkExtractor, SitemapReader
    errors.py        InfrastructureError hierarchy (port contract failures)
    frontier.py      Frontier and VisitedSet — pure, stdlib deque and set
    crawl.py         CrawlSiteUseCase — the crawl loop. No I/O of its own
    aggregate.py     FindingAggregator — dedup and scoring. Pure, no I/O
    validation.py    ValidationPolicy and the per-field layer restriction
    export.py        ExportRunUseCase
    runs.py          ListRunsUseCase, EraseRunsUseCase
  infrastructure/  adapters; third-party packages live here
    config.py clock.py ids.py
    http/            user_agent.py robots.py rate_limit.py requests_fetcher.py
    discovery/       links.py sitemap.py security_txt.py
    extraction/      text.py pipeline.py schema_org.py jsonld.py microdata.py
                     semantic_html.py text_heuristics.py social.py technology.py
    validators/      email.py phone.py names.py address.py website.py social.py
                     company_id.py pgp.py technology.py
    writers/         rows.py sanitize.py json_writer.py csv_writer.py xlsx_writer.py
                     jsonl_writer.py markdown_writer.py
    ledger/          jsonl_ledger.py
  interfaces/      Qt lives HERE and nowhere else
    app.py           the SINGLE composition root; QApplication bootstrap
    launcher.py      argparse for --config / --log-level / --version
    main_window.py crawl_pane.py runs_pane.py settings_pane.py
    export_dialog.py about_dialog.py
    models.py        QAbstractTableModel subclasses
    view_models.py   plain-Python presentation logic, testable with no QApplication
    worker.py        the crawl worker, QtCrawlObserver, QtCancellationToken
```

Rules that reviews check, beyond the general ones in `.claude/rules/`:

- **`PySide6` is confined to `src/osint_scrapper/interfaces/`.** No module under `domain/`, `application/`
  or `infrastructure/` may import it in any form. This is the rule that keeps the whole product testable
  without a `QApplication`, and it is enforced by the boundary test.
- **`interfaces/app.py` is the only place anything is wired.** Use cases and adapters receive their
  collaborators through their constructors. No module-level singletons (module-level `logging` loggers
  excepted).
- **The GUI thread never performs network I/O, HTML parsing, or anything that can exceed 100 ms.** The
  crawl runs on a worker thread and reports through the `CrawlObserver` port; the Qt adapter turns those
  calls into queued signals. Widgets are touched from the GUI thread only. Progress signals are batched.
- **Cancellation is cooperative**, via the `CancellationToken` port checked between fetches.
  `QThread.terminate()` is forbidden — Stop must always leave a consistent, exportable partial report.
- **`RequestsPageFetcher` owns the robots policy and the rate limiter.** The crawl use case receives a
  `PageFetcher` and nothing else — never a `Session`, a `RobotsPolicy` or a `RateLimiter`. This is the
  mechanism that makes robots.txt and rate limiting unforgettable by future code.
- **The fetcher handles redirects one hop at a time, itself.** It does not delegate to `requests`. This is
  load-bearing: it is what makes per-hop robots evaluation and scope checking on redirects possible.
- **No branching on a page's identity or a field's name** to decide behavior in `application/`. Field
  handling is driven by data — `ALLOWED_LAYERS`, the validator mapping, the `FieldName` declaration order.
- **Presentation logic belongs in `view_models.py`**, not in widget subclasses. A widget that computes
  something is a widget that cannot be tested.
- Parsers raise `SelectorNotFoundError` naming the selector and the URL. Never return a half-filled
  record, never a sentinel, never a bare `except`.

## Crawl and compliance constraints

Legality is a design driver here, not a footnote — and crawling a whole site is materially heavier traffic
than v0.1.0's handful of requests, so these numbers are part of the contract:

- **Public data only.** No bypassed authentication, no paywall circumvention, no vulnerability
  exploitation. `GET` only, never any other HTTP method.
- **`robots.txt` is evaluated per URL and again on every redirect hop**, fail-closed. The decision table
  lives in `infrastructure/http/robots.py`; a 404 allows, deliberately, and every ambiguous outcome denies.
  There is no setting, menu item or environment variable that disables it. A `robots.txt` refusal on the
  target itself means the run does not start at all — no run directory, no ledger entry, no requests.
- **Rate limiting with a floor of 0.5 s that nothing lowers.** The effective interval is
  `max(configured, host Crawl-delay, 0.5)`. Concurrency is capped at 4 (default 2) and cannot raise the
  request rate, because the limiter gates request *starts*, not completions.
- **The crawl is bounded**: 200 pages and depth 3 by default; **2000 pages and depth 10 maximum**, enforced
  in `CrawlSettings.__post_init__` so a config file cannot smuggle a larger value past the interface.
- **Scope confinement**: the crawl never leaves the target's host (plus its subdomains when enabled). An
  off-scope redirect is refused, not followed. Off-site links are recorded only when they are social
  profiles, and are never fetched.
- **Abort thresholds**: 3 consecutive 429, 10 consecutive failures, or a >50 % error rate after 20 fetches
  each abort the crawl with a named outcome and a complete, exportable partial report.
- **An honest `User-Agent`.** `build_user_agent()` refuses any browser token, and no control, config key,
  environment variable or argument can set one.
- **GDPR.** A purpose is mandatory and validated before any HTTP request, including `robots.txt`; only the
  nine fields in `FieldName` are ever collected; the Runs pane provides erasure. Retention is recorded and
  never auto-enforced.
- **Free text is trusted only when it self-validates.** Email, phone and company identifier may come from
  text heuristics because each can be independently checked (RFC parse, libphonenumber validity, checksum).
  Person names, postal addresses, organization names, social profiles, PGP key URLs and technologies come
  only from the top three extraction layers. This one rule replaces v0.1.0's scattered per-field
  exceptions; do not carve out another.
- **Provenance on every finding**: source URL, UTC timestamp, extraction layer, and a `raw_value` capped at
  200 characters. A `Finding` with empty provenance raises at construction.

**Confidence semantics changed, and the change is deliberate.** Findings carry two independent numbers —
`extraction_confidence` (the layer that produced the value; a label, never arithmetic) and `page_support`
(distinct URLs it appeared on; an integer count). **There is no blended score anywhere, and there must not
be.** v0.1.0's formula rewarded independent *sources* agreeing; with one site there are none, so a blended
number would look like the old one, be read like the old one, and mean nothing. Page support is not
corroboration — one site repeating itself is one publisher speaking once, loudly. Do not reintroduce a
combined score, and do not reintroduce `identity_unconfirmed`: with no name being matched there is no
homonym risk to flag.

If a request would require crossing one of these lines, raise it with the user before implementing.

## Data output format

Under `<output-dir>/<run_id>/`, with `<output-dir>` defaulting to `./runs`:

- `report.json` — canonical, a superset of the others. Top-level keys, in order: `schema_version`, `run`,
  `target`, `settings`, `statistics`, `findings`, `pages`. **No key outside that schema is ever written.**
- `report.csv` / `report_pages.csv` — one row per provenance entry, `utf-8-sig`, CRLF.
- `report.xlsx` — sheets `Run`, `Findings`, `Pages`, `Compliance`, in that order; the `Findings` header
  matches `report.csv` cell for cell.
- `report.jsonl` — one finding × provenance entry per line, LF, no BOM, no formula guard.
- `report.md` — the human deliverable. No raw HTML is ever emitted.
- `<output-dir>/index.jsonl` — append-only run ledger, holding the target host in plaintext.

**JSON is always written and cannot be deselected** — it is the canonical record and everything else is
derived from it.

**Ordering is deterministic and computed from sort keys, never from arrival order.** This is a hard
requirement, because concurrent fetching makes arrival order nondeterministic. Findings sort by `FieldName`
declaration order, then confidence descending, then support descending, then value; pages by depth then
URL; provenance by URL then timestamp, truncated to 10 entries *after* sorting.

CSV and XLSX cells beginning `=`, `+`, `-`, `@`, TAB or CR get a leading apostrophe against spreadsheet
formula injection. Response bodies, page HTML and free page text are **never** persisted; only the short
`raw_value` that produced an accepted finding is kept.

**`runs/` is git-ignored and must stay that way — it contains collected personal data.**

## Licensing

The project's own code is **MIT**. It links **Qt via PySide6 under the LGPLv3**, which was the deciding
factor in choosing PySide6 over PyQt6 (PyQt6 is GPLv3-or-commercial only, and linking an MIT application
against it would relicense the distributed work). The obligations are real but bounded, and they are
spelled out in `THIRD_PARTY_LICENSES.md`.

Two consequences for anyone working here:

- The **About dialog must state that Qt is used under the LGPLv3** and link to `THIRD_PARTY_LICENSES.md`.
  That is a licence obligation, not decoration; do not remove it.
- **Packaging into a frozen single-file binary is a licence-relevant change**, because it would add a
  relinking obligation under the LGPLv3. Do not do it as a convenience; raise it first.

## Rules

These are binding for all work in this repository:

@.claude/rules/project.md
@.claude/rules/architecture.md
@.claude/rules/dependencies.md
@.claude/rules/documentation.md

Rule 3 in particular is not optional here: **never assert a library API or a licence from memory.** Every
external claim in `docs/SPEC.md` and `THIRD_PARTY_LICENSES.md` carries a verification date, and new ones
are expected to do the same.
