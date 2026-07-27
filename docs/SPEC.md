# OSINT_scrapper — Product Specification (cahier des charges)

**Status:** approved for implementation
**Owner:** @PO
**Implementers:** @DB (domain / application / infrastructure) · @DF (interfaces, Qt)
**Reviewer:** @LT
**Version:** 2.0 — 2026-07-27 — supersedes v1.0 in full
**Language of the repository:** English. Spec, README, code, comments, docstrings, log messages and every
label, tooltip and message in the graphical interface are English, with no exceptions.

v1.0 specified a CLI that searched for a **named natural person** across four vetted sources. That product
is withdrawn. This document specifies a different product and is binding on its own terms; where it
disagrees with v1.0, v1.0 is wrong. `docs/MIGRATION.md` is the demolition plan.

Where this document states a verified fact, the verification is dated. Where it states an assumption, it
says so. Nothing here was written from memory about a third-party API or licence.

---

## 1. Product definition

A **desktop application** that crawls a single website the operator names — by domain or by page URL —
and extracts the OSINT information that site publishes, then exports it, fully attributed, in the formats
the operator chooses.

```
target (domain or URL) → scope → crawl (frontier · robots · rate limit) → extract → validate
                        → aggregate → report → export
```

Each stage is a separate module and a separate test target. The stages of Rule 0 are all present; what
changed is that **source selection became scope definition** and **fetch became a crawl**.

### 1.1 What this product is

- A polite, bounded, single-site crawler with a hard page budget and a hard depth limit.
- An extractor that turns pages into attributed findings: contact points, published identities,
  organization identifiers, social profiles and site technology.
- An exporter to JSON, CSV, XLSX, JSONL and Markdown.
- A local, single-user Qt desktop application. No server, no account, no telemetry.

### 1.2 What this product is not

- **Not a person search.** There is no subject, no name input, no cross-source identity resolution and no
  homonym problem. The operator names a *site*, not a human.
- **Not a web-wide spider.** It never leaves the scope host (§5.3). Off-site links are recorded when they
  are social profiles and discarded otherwise; they are never fetched.
- **Not a technology fingerprinter.** It reads `<meta name="generator">` and two response headers. It does
  not ship a signature database, does not fetch or analyse JavaScript, and does not probe for versions.
- **Not a vulnerability scanner.** It issues `GET` only, never guesses paths outside the documented
  discovery set (§5.6), and never sends a request designed to elicit an error.
- **Not a CLI.** See §4.

---

## 2. Functional requirements

### 2.1 Target and scope

- **FR-1** The operator supplies one **target**: either a bare domain (`example.com`) or an absolute page
  URL (`https://example.com/about`). A bare domain is normalized to `https://<domain>/`. The application
  never falls back to `http://`; if the operator needs plain HTTP they type the full `http://` URL, and the
  interface says so.
- **FR-2** From the target the application derives a **scope host** (§5.3). Every URL it fetches must be in
  scope. Out-of-scope URLs are recorded and never requested.
- **FR-3** The crawl is bounded by a **page budget** and a **maximum depth**, both surfaced in the
  interface, both defaulted, both hard-capped by a maximum the operator cannot exceed (§5.5).

### 2.2 Crawl

- **FR-4** The crawl is breadth-first from the target, with a documented priority boost for high-value
  paths (§5.4). Discovery sources are: links in fetched pages, `Sitemap:` directives in `robots.txt`,
  `/sitemap.xml`, and `/.well-known/security.txt` (§5.6).
- **FR-5** Every URL is canonicalized before it enters the frontier or the visited set, by the exact rules
  of §5.2. The same resource is never fetched twice in one run.
- **FR-6** Only the content types of §5.7 are parsed. Anything else is either not requested at all (known
  binary extension) or requested and discarded unparsed, and recorded as such.
- **FR-7** A failure on one page degrades that page only. The crawl continues. The page log records why,
  with a machine-stable status code (§5.9). The run is aborted only by the thresholds of §5.10, and an
  aborted run still produces a complete, exportable report of everything collected before the abort.
- **FR-8** The operator can stop a running crawl at any time. Stopping is cooperative: in-flight requests
  are allowed to finish or time out, nothing is killed mid-write, and the partial report is exportable and
  marked `stopped_by_operator`.

### 2.3 Legal and compliance requirements (first-class, not advisory)

Crawling a whole site is materially heavier traffic than v1.0's handful of requests. Every rule below is
mechanical; none is a review step, a disclaimer, or a setting the operator can turn off.

- **FR-9 — Mandatory purpose.** A crawl cannot start without a purpose. The purpose is a **required
  selection from a controlled vocabulary** plus an optional note; the note becomes mandatory (≥ 16
  characters after stripping) when the selection is `other` (§7.2.2). Both values are written into every
  export. Rationale and the trade-off considered are in §7.2.2.
- **FR-10 — robots.txt enforced in code, fail-closed, per URL, per hop.** Every content request is gated by
  a `robots.txt` evaluation **for that exact URL**, and again **for the target of every redirect hop**
  (§6.2). The decision table is §6.2.2. There is no manual-review step, no configuration key, no menu item
  and no environment variable that disables or weakens the check.
- **FR-11 — Rate limiting with a floor nothing lowers.** The effective interval between two request
  *starts* to the scope host is `max(configured_interval, host_crawl_delay, HARD_FLOOR)` where
  `HARD_FLOOR = 0.5 s` (§6.3). The interface cannot set a configured interval below the hard floor, and a
  host's `Crawl-delay` always wins when it is larger.
- **FR-12 — Bounded concurrency.** At most **2** requests in flight against the scope host by default,
  configurable 1–4, hard maximum 4 (§6.4). The rate limiter remains the sole throughput governor.
- **FR-13 — Honest User-Agent.** Format unchanged from v1.0:
  `OSINT-Scrapper/<version> (+<project_url>; contact: <contact_email>)`. The builder rejects any candidate
  containing `Mozilla`, `AppleWebKit`, `Chrome`, `Chromium`, `Safari`, `Firefox`, `Gecko` or `Edg`
  (case-insensitive) and raises `DishonestUserAgentError`. There is no control, flag, config key or
  environment variable that sets an arbitrary User-Agent. The computed User-Agent is displayed read-only in
  Settings and in the compliance banner during every crawl.
- **FR-14 — Backoff and abort.** 429 and 5xx behaviour, retry counts, and the four abort thresholds are
  §5.10. Repeated 429 aborts the crawl; it never escalates.
- **FR-15 — Data minimization.** Only the fields enumerated in `FieldName` (§8.1) are extracted, stored or
  exported. Page HTML, response bodies and free page text are **never** persisted. The only raw text kept
  is the short `raw_value` that produced an accepted finding, capped at 200 characters.
- **FR-16 — Traceability at finding level.** Every exported value carries at least one provenance entry
  with `source_url` (the final URL after redirects), `collected_at` (RFC 3339, UTC, `Z`),
  `extraction_layer` and `raw_value`. A finding constructed with an empty provenance tuple raises.
- **FR-17 — Right to erasure, with a home in the interface.** A **Runs** screen lists every run and deletes
  runs on demand: the run directory and its ledger lines, with a confirmation that names the exact
  directories. It also offers "delete expired" for runs past the declared retention (§7.4).
- **FR-18 — Retention is recorded, not enforced.** Every export declares a retention period (default 30
  days). The application never deletes anything by itself; it shows expiry and gives the operator one
  click.
- **FR-19 — LGPL notice.** The application ships the licence text of every third-party component under
  `THIRD_PARTY_LICENSES.md`, and the **About** dialog states prominently that the application uses Qt via
  PySide6 under the LGPLv3 and links to that file. This is a licence obligation, not a courtesy (§3.1).
- **FR-20 — No crawl before configuration.** The application refuses to start a crawl until a valid contact
  email is configured, because the User-Agent must carry an honest contact. The Settings pane says why.

### 2.4 Extraction

- **FR-21** Extraction is layered with explicit precedence (§8.2). Every extracted value records the layer
  that produced it.
- **FR-22** Every value is validated before it can become a finding (§8.4). A value that fails validation
  is discarded and is never exported as fact.
- **FR-23** **Text heuristics are permitted only for self-validating values.** A value may be extracted
  from free page text only if an independent check can confirm it is well-formed: an email address
  (RFC-correct parse), a phone number (libphonenumber validity), or a company identifier (checksum). Person
  names, postal addresses, organization names, social profiles, PGP key URLs and technologies are
  extractable **only** from layers `well_known`, `structured_data` and `semantic_html`. This single rule
  replaces the ad-hoc per-field exceptions of v1.0 and is the reason no free-text address or name detector
  exists (§8.3).
- **FR-24** Values are deduplicated by `(field, dedup_value)`. The same email seen on forty pages is one
  finding with a page-support count of forty, not forty records (§8.5).
- **FR-25** Each finding reports two independent, separately meaningful numbers: `extraction_confidence`
  (how the value was obtained) and `page_support` (on how many distinct URLs it was seen). **No blended
  score is computed or exported** (§8.6).
- **FR-26** Conflicts do not exist in this product. Every field is multi-valued: a site legitimately
  publishes many emails, many people, many phone numbers. Nothing is dropped, nothing is "resolved", and
  the v1.0 `conflicts` machinery is deleted.

### 2.5 Interface

- **FR-27** The application is a Qt desktop application (§3.1, §7). There is no CLI product.
- **FR-28** The GUI thread never performs network I/O, HTML parsing or any operation that can exceed
  100 ms (§7.6).
- **FR-29** During a crawl the interface shows, live: progress against the budget, a findings table, a
  per-page log, and a non-dismissible compliance banner (§7.3).
- **FR-30** Errors are presented in three tiers — page-level rows, run-level inline banners, and modal
  dialogs reserved for programming errors only (§7.5). No modal ever interrupts a running crawl.

### 2.6 Export

- **FR-31** Formats: `json`, `csv`, `xlsx`, `jsonl`, `md`. JSON is always written and cannot be
  deselected — it is the canonical record. Schemas are fixed by §9.
- **FR-32** Every export is written under `<output-dir>/<run_id>/`. A completed run can be re-exported to
  additional formats from the Runs screen without re-crawling.
- **FR-33** Text originating from third-party pages is neutralized against spreadsheet formula injection in
  CSV and XLSX (§9.6).

### 2.7 Documentation

- **FR-34** `README.md` and `README.fr.md` are rewritten for v0.2.0 with the sections of §12. Both files
  are in their stated language; the repository's *source* stays English per the project rule, and
  `README.fr.md` is a translation of user-facing documentation only, never of code or comments.

---

## 3. Non-functional requirements

- **NFR-1 — Layering.** `domain/` imports only the Python standard library. `application/` imports only the
  standard library plus `osint_scrapper.domain` and `osint_scrapper.application`. Third-party packages
  appear only in `infrastructure/` and `interfaces/`.
- **NFR-2 — Qt is confined to `interfaces/`.** No module outside `src/osint_scrapper/interfaces/` may
  import `PySide6` in any form. Enforced by the same `ast`-based boundary test as NFR-1. This is what keeps
  the whole product testable without a `QApplication`.
- **NFR-3 — Ports and injection.** All I/O crosses a Protocol declared in `application/ports.py` and
  implemented in `infrastructure/` or `interfaces/`. Use cases receive collaborators through their
  constructor. No module-level singletons (module-level `logging` loggers excepted). Wiring happens exactly
  once, in `interfaces/app.py`.
- **NFR-4 — Typing.** Every public function and method carries type hints. `mypy --strict` passes on
  `src/`.
- **NFR-5 — Errors.** Typed exceptions derived from `DomainError` / `InfrastructureError`. No bare
  `except`, no sentinel return values, no swallowed exceptions.
- **NFR-6 — Tests run offline.** The suite makes zero network calls. The autouse fixture in
  `tests/conftest.py` patching `socket.socket` and `socket.create_connection` stays exactly as it is.
- **NFR-7 — Fixtures.** Parsers and the whole crawl are tested against committed fixtures. **No fixture may
  contain a real person's data** — invented values on `example.com` / `example.org` only.
- **NFR-8 — Loud parser failures.** A parser that cannot find the structure it was written for raises
  `SelectorNotFoundError` naming the selector and the URL. It never returns a half-filled record.
- **NFR-9 — Determinism.** Two runs over the same fixtures produce byte-identical exports except for
  `run_id` and timestamps. **Ordering is computed from sort keys, never from arrival order** — this is a
  hard requirement because §6.4 permits concurrent fetches (§9.1.1).
- **NFR-10 — Reproducible dependencies.** `pyproject.toml` plus the committed `uv.lock`. Versions are
  resolved at install time, not copied from this document.
- **NFR-11 — Responsiveness.** The interface repaints and responds to input throughout a crawl. Live
  tables are updated by batched signals, not one signal per row per repaint.
- **NFR-12 — Politeness ceiling.** A run issues at most `max_pages` content requests plus at most one
  `robots.txt` fetch per host key plus at most 5 sitemap documents. Nothing else.
- **NFR-13 — Windows first.** The development and reference platform is Windows 11 with CPython 3.12. The
  application must also run on Linux and macOS, but Windows is the platform the acceptance criteria are
  demonstrated on.

### 3.1 The Qt binding: PySide6

**Decision: PySide6.**

Verified 2026-07-27 from PyPI release metadata and the vendors' own licensing pages. **PySide6** — latest
6.11.1, released 2026-05-13, on a steady schedule tracking Qt itself (6.10.0 2025-10-08, 6.10.1 2025-11-20,
6.10.2 2026-02-02, 6.10.3 2026-04-02, 6.11.0 2026-03-23); declared licence `LGPL-3.0-only OR GPL-2.0-only
OR GPL-3.0-only` plus a commercial option; `requires-python <3.15,>=3.10`; Windows wheels for both
`win_amd64` and `win_arm64`; it is the Qt Company's own binding, it ships `.pyi` stub files generated by
`pyside6-genpyi`, and the project maintains a documented mypy-correctness effort — which matters directly
for NFR-4. **PyQt6** — latest 6.11.0, released 2026-03-30, also actively released, also with `win_amd64`
and `win_arm64` wheels; but Riverbank Computing state plainly that *"PyQt is dual licensed on all supported
platforms under the GNU GPL v3 and the Riverbank Commercial License"* and, decisively, *"Unlike Qt, PyQt is
not available under the LGPL."* This project is MIT-licensed. Linking an MIT application against PyQt6
under the GPLv3 would relicense the distributed work as GPLv3 and change what this repository is; buying a
Riverbank commercial licence to avoid that is not a cost a small tool should carry. PySide6's LGPLv3 option
permits an MIT application to use dynamically linked Qt, which is exactly what a pip-installed wheel is.
Both bindings are healthy and both would work technically; the licence is the whole decision, and the
typing story and first-party maintenance make it comfortable rather than merely acceptable.

**LGPLv3 obligations this project accepts** (verified against the Qt Company's LGPL obligations page,
2026-07-27), stated so @LT can check them rather than assume them:

1. Qt is used **dynamically linked** as installed by `pip`. The project must not vendor, statically link, or
   freeze Qt into a single-file binary without also shipping the relinking information the LGPLv3 requires.
   Any future packaging work (PyInstaller and friends) is therefore a **licence-relevant change** and must
   come back to this section.
2. The user must be able to replace the Qt libraries with their own build. A normal `pip install` layout
   satisfies this.
3. A copy of the LGPLv3 text must be provided and a prominent notice must state that the LGPL library is
   used. This is FR-19: `THIRD_PARTY_LICENSES.md` plus the About dialog.
4. Only Qt Essentials modules are used — `QtCore`, `QtGui`, `QtWidgets`. Add-on modules are out of scope; if
   one is ever needed, its individual licence must be checked first, because not every Qt module carries the
   same terms.

**Modules used:** `QtWidgets` only, no `QtQuick`/QML. A widget-based interface is a small number of tables,
forms and dialogs; QML would add a second language, a second toolchain and a rendering backend for no gain,
and it interacts badly with the "no logic in the view" rule.

**Testing Qt:** the presentation logic lives in plain-Python view models under `interfaces/` that are
testable with no `QApplication`. For the small residue that needs a real widget, `pytest-qt` (verified
2026-07-27: 4.5.0, 2025-07-01, MIT, supports PySide6) is a **dev** dependency, run with
`QT_QPA_PLATFORM=offscreen`. This is the documented headless path; @DB/@DF confirm it on the pinned
version before relying on it, and if it proves unreliable on Windows CI the fallback is to test view models
only and keep widget code trivially thin — which the architecture already requires.

### 3.2 Dependencies after the refactor

| Dependency | Status | Reason |
|---|---|---|
| `requests` | kept | The only HTTP client. Unchanged. |
| `beautifulsoup4` (`html.parser`) | kept | HTML parsing, and now also sitemap `<loc>` extraction (§5.6). |
| `phonenumbers` | kept | Phone validity is one of the three self-validating values of FR-23. |
| `email-validator` | kept | Same, for email. `check_deliverability=False` remains mandatory (NFR-6). |
| `openpyxl` | kept | XLSX. No stdlib alternative. |
| **`PySide6`** | **added** | §3.1. Replaces the CLI as the product's interface. |
| `pytest`, `ruff`, `mypy` | kept (dev) | Unchanged. |
| **`pytest-qt`** | **added (dev)** | Widget smoke tests only. §3.1. |
| `tldextract` | **rejected** | Verified 2026-07-27: it *"fetches the latest Public Suffix List on first use and caches it indefinitely"*. A surprise network call at import time is incompatible with NFR-6 and with a tool whose whole point is that every request is accounted for. Scope confinement is therefore defined without a public suffix list (§5.3), which is strictly narrower and needs no dependency. |
| `defusedxml` | **rejected** | Sitemaps are parsed by pulling `<loc>` text with the BeautifulSoup + `html.parser` stack already present, under a size cap. No XML entity resolution happens at all, so there is nothing for a hardened XML parser to harden. Rule 2 step 2: do not add a second parser. |
| `odfpy` (ODS export) | **rejected** | `openpyxl` already covers the spreadsheet deliverable; a second spreadsheet library for a format nobody asked for by name is exactly the gold-plating this refactor is cutting. |
| An HTML report writer | **rejected** | Markdown covers the human-readable deliverable. An HTML file that embeds strings scraped from third-party pages and is then opened in a browser is an active-content surface we would have to defend for no added value. |
| A PDF writer | **rejected** | Heavy dependency, no requirement. |

---

## 4. Entry point: the GUI is the product

**Decision: the CLI is deleted. No parallel headless product survives.**

The user asked for a graphical application. Keeping `investigate` / `sources` / `erase` as a second,
fully-supported surface would mean a second set of exit codes, a second rendering path, a second set of
acceptance criteria and a second thing to document and keep honest — a direct violation of "one reason to
change". `interfaces/cli.py` is deleted in full.

What survives is **not a CLI, it is the seam**: `CrawlSiteUseCase` and its ports are plain Python, take an
observer and a cancellation token, and are driven end to end by the test suite with no Qt present. Anyone
who needs headless operation imports the use case; that is a library capability, not a shipped command, and
it costs nothing because the architecture demands it anyway.

The console script `osint-scrapper` and `python -m osint_scrapper` both **launch the GUI**. They accept
exactly three arguments, parsed with stdlib `argparse`:

| Argument | Meaning |
|---|---|
| `--config PATH` | configuration file to load instead of the default search order (§7.7) |
| `--log-level {debug,info,warning,error}` | log verbosity; logs go to stderr, never into the interface's data views |
| `--version` | print the version and exit |

No `--target`, no `--purpose`, no headless run flag. If one is ever wanted, it comes back through this
specification first.

---

## 5. The crawl model

### 5.1 Vocabulary

- **Target** — what the operator typed, normalized to an absolute `https`/`http` URL (FR-1).
- **Scope host** — the host that defines confinement (§5.3).
- **Frontier** — the queue of canonical URLs not yet fetched, with their depth.
- **Visited set** — the set of canonical URLs already dequeued. Membership is checked before enqueue and
  again before fetch.
- **Depth** — 0 for the target, `n+1` for a URL first discovered on a page at depth `n`. URLs discovered
  through a sitemap or through `security.txt` enter at depth 1.

### 5.2 URL canonicalization

Canonicalization produces the **frontier key**. It is a pure function of a URL string and a base URL, lives
in `domain/url.py`, and uses only `urllib.parse` and `idna` encoding from the standard library. The
canonical form is also what is stored and exported as `source_url`, except that the exported value is the
**final URL after redirects**, canonicalized.

Applied in this order:

1. Resolve against the base URL (`urljoin`). Reject anything that is not `http` or `https` — `mailto:`,
   `tel:`, `javascript:`, `data:` and `ftp:` are extraction inputs or noise, never crawl targets.
2. Lower-case the scheme and the host.
3. Encode the host to its IDNA A-label (punycode). A host that fails IDNA encoding is rejected.
4. Remove the default port: `:80` for `http`, `:443` for `https`. Any other port is kept and is part of the
   scope check.
5. **Drop the fragment**, always and unconditionally.
6. Normalize the path: resolve `.` and `..` segments; collapse runs of `/` into one; percent-decode
   unreserved characters (`A–Z a–z 0–9 - . _ ~`) and re-encode everything else consistently in upper-case
   hex; an empty path becomes `/`. **Path case is preserved** — paths are case-sensitive on most servers,
   and folding them would merge distinct resources.
7. **A trailing slash is significant and is preserved.** `/a` and `/a/` are different frontier keys. In
   practice servers redirect one to the other, and because the redirect target is what enters the visited
   set (§6.2), the duplicate collapses on its own without us guessing.
8. Query string: drop the parameters whose lower-cased name is in
   `TRACKING_PARAMETERS = {utm_source, utm_medium, utm_campaign, utm_term, utm_content, utm_id, gclid,
   dclid, fbclid, msclkid, mc_cid, mc_eid, igshid, _ga, _gl, yclid, wbraid, gbraid}`
   or in `SESSION_PARAMETERS = {sid, sessionid, session_id, phpsessid, jsessionid, aspsessionid, cfid,
   cftoken, zenid}`. Sort the remaining parameters by `(name, value)` and re-encode. An empty result drops
   the `?` entirely. Sorting is what stops `?a=1&b=2` and `?b=2&a=1` from doubling the frontier.
9. Drop userinfo (`user:pass@`) if present, and record the URL as skipped with reason
   `credentials_in_url` — a URL carrying credentials is not public data.

**Spider-trap guard.** A canonical URL is rejected before enqueue, with reason `url_rejected_shape`, when:
more than 20 path segments; the same path segment repeated more than 4 times; more than 10 query
parameters after cleaning; or a total canonical length above 2048 characters.

### 5.3 Scope confinement

The **scope host** is the target URL's host with a single leading `www.` removed.

A canonical URL is **in scope** iff its scheme is `http`/`https`, its port matches the target's port, and:

- **Include subdomains ON (default):** `host == scope_host` **or** `host.endswith("." + scope_host)`.
- **Include subdomains OFF:** `host == scope_host` **or** `host == "www." + scope_host`.

Deliberate consequences, all of them chosen:

- No public suffix list is consulted, so there is no runtime download and no cache (§3.2). Confinement is
  defined by the host the operator actually named, which is **narrower** than registrable-domain
  confinement and therefore always safe. Seed `foo.co.uk` never reaches `bar.co.uk`; the PSL bug class does
  not exist here.
- Confinement goes **down, never up**. Seed `docs.example.com` does not reach `example.com`. If the
  operator wants the whole domain they type the domain. This is stated in the interface next to the
  checkbox.
- **Off-site links are never fetched.** An off-site `href` is offered to the social-profile extractor
  (§8.1); if it matches a known platform it becomes a `social_profile` finding, otherwise it is discarded
  entirely. The application does not emit a link dump of the open web.
- **A redirect that leaves the scope is not followed.** The hop is recorded as `off_scope_redirect` with
  both URLs and the crawl continues. This is the rule that stops a single misconfigured redirect from
  turning a site crawl into an internet crawl.

### 5.4 Frontier ordering

Breadth-first (FIFO), with one modification: a URL whose canonical **path** matches
`HIGH_VALUE_PATH_PATTERN` is pushed to the front of the queue at its own depth.

```
HIGH_VALUE_PATH_PATTERN = case- and accent-insensitive match on any of:
  mentions?-?legales?  |  legal(-notice)?  |  impressum  |  imprint  |  cgu  |  cgv  |  terms
  contact  |  nous-?contacter  |  contactez  |  about  |  a-?propos  |  qui-?sommes-?nous
  team  |  equipe  |  staff  |  people  |  direction  |  management  |  leadership
  privacy  |  confidentialite  |  rgpd  |  gdpr  |  donnees-?personnelles
  security  |  securite  |  press(e)?  |  media  |  investors?  |  relations-?investisseurs
```

Why: breadth-first already reaches shallow pages first, but a site with 300 blog posts linked from the
homepage would spend its whole budget on them before touching `/mentions-legales`. This list is exactly the
value that v1.0's `legal_notice` adapter carried, preserved as a **priority hint** rather than as a source
adapter. It never adds a request — it only reorders a queue that already contains the URL — and a
budget-truncated crawl therefore still returns the pages that matter.

### 5.5 Budget and depth

| Setting | Default | Minimum | Maximum the operator cannot exceed |
|---|---|---|---|
| `max_pages` | **200** | 1 | **2000** |
| `max_depth` | **3** | 0 | **10** |
| `request_interval_seconds` | **1.0** | **0.5** (hard floor) | 60.0 |
| `concurrent_requests` | **2** | 1 | **4** |
| `retention_days` | **30** | **1** | **3650** |

Both maxima are enforced in the **domain** (`CrawlSettings.__post_init__` raises
`InvalidCrawlSettingsError`), not only in the widget, so the config file cannot smuggle a larger value past
the interface.

Justification for the defaults: 200 pages at 1.0 s is a ~3.5-minute crawl and covers a typical small
business or association site in full — the sites whose legal-notice and contact pages are this product's
most defensible target. Depth 3 from a homepage reaches section pages and their children, which is where
contact information lives; deeper is archive territory. The maxima exist because "the operator named this
target, so it is their lawful basis" is a much heavier argument to carry at 2000 requests than at 5, and an
unbounded control would let a slip of the keyboard become an incident. 2000 pages at the 0.5 s floor is
~17 minutes of sustained polite traffic — a defensible ceiling for a deliberate, supervised, foreground
action, and above it the operator should be talking to the site owner instead.

The budget counts **every content request**, including sitemap documents and `security.txt`, and excludes
`robots.txt`.

### 5.6 Discovery

In addition to links found in fetched pages, three discovery sources run once, at the start:

1. **`robots.txt` `Sitemap:` directives.** `robots.txt` is fetched anyway for FR-10; its `Sitemap:` lines
   are read from the same body at no extra cost. (Verified 2026-07-27 against sitemaps.org: the directive
   is `Sitemap: <absolute URL>`, is independent of any `User-agent` group, and may appear multiple times.)
2. **`/sitemap.xml`**, fetched only when `robots.txt` declared no sitemap and "follow sitemap" is enabled.
3. **`/.well-known/security.txt`** (RFC 9116). Verified 2026-07-27 against RFC 9116: the well-known path is
   exactly `/.well-known/security.txt`; the media type is `text/plain` with `charset=utf-8`; the required
   fields are `Contact` and `Expires`; the optional fields are `Acknowledgments`, `Canonical`,
   `Encryption`, `Hiring`, `Policy` and `Preferred-Languages`; and the RFC itself says parsers may decline
   files larger than 32 KB, with fields longer than 2048 characters, or with more than 1000 lines — this
   product applies exactly those three limits and records `too_large` when they are exceeded.

**Sitemap parsing.** Verified 2026-07-27 against sitemaps.org: a sitemap file has root `<urlset>`, entries
`<url>`, and location `<loc>`; a sitemap index has root `<sitemapindex>`, entries `<sitemap>`, location
`<loc>`; the stated limits are 50 000 URLs and 50 MB uncompressed per file. This product is stricter and
does not honour those maxima:

- Document size cap **10 MiB**; larger is abandoned and recorded `too_large`.
- At most **500** `<loc>` values taken from any one sitemap document.
- At most **5** sitemap documents in a run.
- Sitemap-index recursion **one level only**.
- `<loc>` values are extracted with the existing BeautifulSoup + `html.parser` stack. No XML entity
  resolution happens at any point, which is why no XML hardening library is needed (§3.2).
- Every sitemap URL is canonicalized, scope-checked, robots-checked and budget-counted like any other. A
  sitemap listing off-site URLs gets those URLs dropped, silently to the frontier and visibly in the page
  log.

`security.txt` yields findings directly: `Contact:` values that are `mailto:` become `email`, values that
are `tel:` become `phone`, `https:` values become `social_profile` only if they match a known platform and
are otherwise ignored; `Encryption:` becomes `pgp_key_url`. All at layer `well_known`. `Contact:` URLs are
**not** added to the frontier — they are contacts, not crawl targets.

### 5.7 Content types

**Never requested at all** (rejected on the URL's extension, before any HTTP call):

```
.pdf .doc .docx .xls .xlsx .ppt .pptx .odt .ods .odp .rtf
.jpg .jpeg .png .gif .webp .avif .svg .ico .bmp .tif .tiff
.mp3 .mp4 .m4a .m4v .avi .mov .wmv .webm .ogg .ogv .wav .flac
.zip .gz .tar .tgz .bz2 .xz .7z .rar .dmg .exe .msi .iso .apk
.css .js .mjs .map .woff .woff2 .ttf .otf .eot
```

Recorded as `skipped_extension`. The URL still appears in the page log, so the operator can see that a
`/rapport-annuel.pdf` exists — the information is preserved without adding a field for it.

**Requested and parsed** when the response `Content-Type` media type is `text/html` or
`application/xhtml+xml`; plus `text/plain` for `/.well-known/security.txt`; plus `application/xml`,
`text/xml` or `application/rss+xml` for sitemap documents only.

**Requested and discarded unparsed** otherwise: the body is not read past the header, the connection is
released, and the URL is recorded `skipped_content_type` with the media type observed.

**Response size cap: 5 MiB.** The body is read in chunks and abandoned past the cap; the URL is recorded
`too_large`. Nothing partial is parsed.

### 5.8 Visited set and re-fetch

- The visited set holds canonical URLs. A URL is added when it is dequeued, before the request, so a
  concurrent worker cannot pick up the same URL.
- The **final** URL after redirects is also added to the visited set. A page reachable at three URLs that
  all redirect to one is fetched once and counted once.
- Nothing is ever re-fetched in a run. There is no retry-on-parse-failure and no conditional request; a run
  is a snapshot.

### 5.9 Per-page status codes

Machine-stable, exported verbatim, rendered by @DF with whatever iconography they choose:

| Status | Meaning |
|---|---|
| `ok` | fetched, parsed; findings may be zero |
| `no_findings` | fetched and parsed, nothing extractable — distinct from `ok` so the log is honest |
| `skipped_robots` | robots.txt disallowed this exact URL |
| `skipped_extension` | never requested; known binary extension (§5.7) |
| `skipped_content_type` | requested; media type not parseable (§5.7) |
| `skipped_off_scope` | discovered but out of scope; never requested |
| `skipped_budget` | discovered after the page budget was exhausted; never requested |
| `skipped_depth` | discovered beyond `max_depth`; never requested |
| `url_rejected_shape` | rejected by the spider-trap guard (§5.2) |
| `credentials_in_url` | URL carried userinfo; never requested |
| `off_scope_redirect` | a redirect hop left the scope; not followed |
| `too_many_redirects` | more than 5 hops, or a loop |
| `too_large` | body or document exceeded its cap |
| `rate_limited` | 429 after retries were exhausted |
| `http_error` | any other unusable status after retries |
| `transport_error` | timeout, DNS, TLS, connection reset |
| `parse_error` | the page was fetched but a parser raised `SelectorNotFoundError` |

### 5.10 Backoff and abort thresholds

**429 — Too Many Requests.** Honour `Retry-After` when present, capped at 120 s; if it exceeds 120 s, abort
immediately with `aborted_rate_limited` rather than sit idle holding a run open. Without `Retry-After`, back
off `2 s`, `4 s`, `8 s` with jitter. **After 3 consecutive 429 responses from the scope host, abort the
crawl** with `aborted_rate_limited`. Repeated 429 is the host telling us to stop; escalating past it is
exactly the behaviour `CLAUDE.md` forbids and is how integrations get banned.

**5xx.** Up to 3 retries with exponential backoff and jitter, `backoff_factor = 1.0`, capped at 30 s
(unchanged from v1.0 and already implemented). After retries, the URL is recorded `http_error` and the
crawl continues.

**4xx other than 429.** Recorded, never retried.

**Four abort thresholds**, each producing a named `CrawlOutcome` and a complete, exportable partial report:

| Threshold | Trigger | Outcome |
|---|---|---|
| Rate limit | 3 consecutive 429, or a `Retry-After` above 120 s | `aborted_rate_limited` |
| Host unhealthy | 10 consecutive fetch failures of any kind (5xx or transport) | `aborted_host_unhealthy` |
| Error rate | after at least 20 attempted fetches, the failure rate exceeds 50 % | `aborted_error_rate` |
| Operator | the operator pressed Stop | `stopped_by_operator` |

**"Attempted fetch" means a request that went out and whose outcome the host decided** — the statuses in
`FETCHED_STATUSES` and `FAILED_STATUSES`. A *skip* is this product declining to use a URL and moves none of
these counters: `skipped_robots`, `skipped_budget`, `skipped_content_type` and `off_scope_redirect` are
neither attempts nor failures. Counting a robots skip as a failed fetch would mean that the better a site
protects itself with `robots.txt`, the sooner we declare that site broken and abort — punishing exactly the
behaviour this product exists to honour, and mislabelling a healthy host in the exported outcome.

Plus the normal terminations: `completed` (frontier empty), `budget_exhausted`, `depth_exhausted`, and
`failed`, which an unexpected exception reaching the interface produces (§7.5 tier 3); whatever was
collected before it stays exportable.

**Seed refusal is not an abort, it is a refusal to start.** If `robots.txt` disallows the target URL
itself, or the target is unreachable, the run does not start, no run directory is created, no ledger entry
is written, and the interface shows the robots URL, the matched rule and the reason code. There is no
override control anywhere in the product.

---

## 6. Fetching

### 6.1 Composition

`RequestsPageFetcher` implements `PageFetcher` and internally holds the `RobotsPolicy` and the
`RateLimiter`. It is the only object in the product that reaches the network. The crawl use case receives a
`PageFetcher` and nothing else — never a `Session`, never a `RobotsPolicy`, never a `RateLimiter`. This is
what makes robots.txt and rate limiting unforgettable by future code, and @LT reviews for it.

The v1.0 fetcher took a `SourceDescriptor`. It now takes a `FetchPolicy` frozen dataclass
(`product_token`, `configured_interval_seconds`, `hard_floor_seconds`, `timeout_seconds`, `max_pages`,
`max_body_bytes`, `max_redirects`, `scope`), which is the same information without the person-search
vocabulary.

### 6.2 robots.txt

#### 6.2.1 Per URL, per hop

- Evaluated **for every content URL**, not once per host. Path-level rules mean a host decision is
  meaningless.
- Evaluated **again for the target of every redirect hop**, before following it. A page that is allowed but
  redirects into a disallowed path is not fetched. The v1.0 fetcher already re-gates each hop manually
  rather than delegating to `requests`' redirect handling; that behaviour is load-bearing and must survive
  the refactor unchanged.
- Maximum 5 hops; beyond that, `too_many_redirects`.
- A hop leaving the scope is `off_scope_redirect` (§5.3) and is not followed even if robots would allow it.
- The `robots.txt` body is parsed once per host key `(scheme, host, port)` and cached in memory for the run,
  TTL 24 h (RFC 9309). One host key means at most one `robots.txt` request per run in practice, since a
  crawl is confined to one site; a subdomain is a different host key and gets its own fetch and its own
  decision.
- The User-Agent token matched by `can_fetch()` is the product token `OSINT-Scrapper`, not the full
  User-Agent string.

#### 6.2.2 Decision table (fail-closed) — carried over unchanged

| Result of fetching `/robots.txt` | RFC 9309 says | **This project does** |
|---|---|---|
| 2xx, body parseable | Follow the parsed rules | Follow the parsed rules |
| 3xx, up to 5 hops, then 2xx | Follow at least 5 redirects | Follow up to 5 redirects, then evaluate the final body |
| 401 or 403 | (stdlib treats as full disallow) | **DENY** — the host is refusing us |
| Other 4xx, including 404 | Crawler MAY access any resource | **ALLOW** |
| 5xx | Crawler MUST assume complete disallow | **DENY** |
| Timeout, DNS failure, TLS failure, connection reset | — | **DENY** |
| Body larger than 512 KiB | Parse limit ≥ 500 KiB | **DENY** (treated as ambiguous) |
| Body not decodable as UTF-8 (with `surrogateescape`), or unparseable | — | **DENY** |
| More than 5 redirects, or a redirect loop | — | **DENY** |

The 404-allows divergence stands and is still deliberate: a 404 is a definitive answer from the host, it is
what RFC 9309 §2.3.1.3 prescribes, and it is what stdlib `RobotFileParser` implements. Everything genuinely
*ambiguous* denies. This matters more at 200 requests than it did at 5, and it is unchanged precisely
because the reasoning did not depend on volume.

`RobotsDecision` gains nothing and loses nothing: `allowed`, `reason`, `robots_url`, `crawl_delay`.

### 6.3 Rate limiting

- `PerHostRateLimiter` enforces a minimum interval between the **starts** of two requests to the same host,
  using an injected monotonic clock and an injected sleeper, so tests never really sleep. Unchanged.
- `effective_interval = max(configured_interval, robots_crawl_delay, robots_request_rate, HARD_FLOOR)` with
  `HARD_FLOOR = 0.5`. It is a floor. Nothing in the configuration file, the interface, the environment or a
  command-line argument can lower it, and a host's `Crawl-delay` of 10 s produces a 10 s interval no matter
  what the operator set.
- The limiter is **shared by all concurrent workers** (§6.4). It is the single throughput governor.
- Default configured interval 1.0 s. Default timeout 10.0 s connect and read.
- `GET` only. The application issues no other HTTP method, ever.

### 6.4 Concurrency

**2 requests in flight against the scope host by default; configurable 1–4; hard maximum 4.**

The reasoning, because the number needs one: the rate limiter gates request **starts**, so with an
effective interval of 1.0 s the product cannot exceed one request per second regardless of how many workers
exist. **Concurrency therefore cannot increase the load on the host** — it can only hide latency. On a site
answering in 2 s, one worker yields 0.5 req/s and wastes half the permitted budget waiting; two workers
yield the permitted 1 req/s. Two is enough to saturate any interval against any response time under twice
the interval, which covers essentially every real site. More workers buy nothing but open connections,
memory, and harder-to-reason-about cancellation, so the hard maximum is 4 and the default is 2. A single
worker remains available for operators who want the simplest possible traffic shape.

Consequences that must be honoured:

- Fetch completion order is **not** deterministic. Every ordering in every export is therefore computed
  from sort keys and never from arrival order (NFR-9, §9.1.1).
- The visited set and the frontier are guarded so two workers never take the same URL.
- Cancellation is checked between fetches, never inside one (§7.6).

---

## 7. Graphical interface specification

This section fixes behaviour and product decisions. It does **not** fix visual styling, spacing, colour,
iconography or layout aesthetics — @DF owns the visual craft and does not need permission for it.

### 7.1 Shell

A single `QMainWindow`. No MDI, no floating tool windows, no system tray.

- **Menu bar:** *File* (Settings…, Open output folder, Quit) · *Run* (Start crawl, Stop crawl, Export…) ·
  *Help* (Legal use, About).
- **Status bar:** the current state in one line (`Idle` · `Crawling — 47/200 pages` · `Stopped` ·
  `Completed — 63 findings`).
- **Central area:** three panes, selectable and switchable at any time — **Crawl**, **Runs**, **Settings**.
  Switching panes never interrupts a running crawl.
- Window geometry, splitter positions and table column widths are persisted with `QSettings`. **Everything
  else — every product setting — lives in `osint-scrapper.toml`** (§7.7). Two configuration stores is a
  smell; this split is the whole of it and it is deliberate: `QSettings` holds only what is meaningless
  outside this machine's window manager.

### 7.2 Crawl pane — before a run

#### 7.2.1 Controls

| Control | Widget | Default | Notes |
|---|---|---|---|
| Target | `QLineEdit` | empty | placeholder `example.com  or  https://example.com/about`. Validated live; a hint line below shows the resolved target URL and the derived scope host, or the reason it is invalid. |
| Purpose | `QComboBox` | last used, from config | required; §7.2.2 |
| Purpose note | `QLineEdit` | last used, from config | optional; **required and ≥ 16 characters when Purpose is `other`** |
| Max pages | `QSpinBox` | 200 | range 1–2000 |
| Max depth | `QSpinBox` | 3 | range 0–10 |
| Request interval (s) | `QDoubleSpinBox` | 1.0 | range 0.5–60.0, step 0.5. The minimum is the hard floor and the widget cannot go below it. |
| Concurrent requests | `QSpinBox` | 2 | range 1–4 |
| Include subdomains | `QCheckBox` | checked | label states the down-not-up rule of §5.3 |
| Follow sitemap | `QCheckBox` | checked | |
| Phone region | `QComboBox` | `FR` | ISO 3166-1 alpha-2; the region libphonenumber parses against |
| **Start crawl** | `QPushButton` (primary) | disabled | enabled only when target and purpose are valid; its tooltip states which one is missing |

The four limit controls sit in a group box titled **Crawl limits**, **expanded by default**. They are
compliance controls, not advanced options, and hiding them behind a disclosure triangle would be dishonest
about what the application is about to do.

#### 7.2.2 Purpose — the decision, and the trade-off

**Purpose stays mandatory. Its shape changes from a free-text box to a required choice plus an optional
note.**

The compliance value of v1.0's `--purpose` was twofold: it forced the operator to state a lawful basis
before any request, and it put that statement into the export where an audit can find it. The 16-character
minimum was a guard against `--purpose test`. In a GUI, a mandatory free-text box before every run is real,
recurring friction, and friction of that kind does not produce thoughtful answers — it produces
`aaaaaaaaaaaaaaaa`. A box that reliably collects garbage has negative compliance value: it manufactures
evidence of deliberation that did not happen.

A required selection from a controlled vocabulary keeps both of the original benefits, costs one click, and
produces *better* records than free text, because a controlled vocabulary is analysable and comparable
across runs while prose is not.

```
PurposeCategory:
  security_assessment      Authorized security assessment with a written scope
  due_diligence            Vendor, supplier or pre-contract due diligence
  journalism               Journalistic research
  self_audit               Auditing a site we own or operate
  academic_research        Academic or statistical research
  other                    Other — a note is required
```

Rules:

- A selection is required. There is no blank or default-empty entry; the combo box opens on the value from
  config, which is the operator's last used purpose.
- The note is free text, optional for the five named categories, **mandatory and ≥ 16 characters after
  stripping when `other` is selected**. This is where the v1.0 guard survives, aimed at exactly the case
  that needs it.
- Both `purpose_category` and `purpose_note` are written into every export and into the ledger.
- The purpose is **always visible, immediately next to the Start button**, never collapsed, never in a
  dialog the operator dismisses once and forgets. It persists across sessions in config, because re-typing
  it teaches nothing; what matters is that the operator sees what they are about to assert at the moment
  they assert it.
- No HTTP request of any kind — not even `robots.txt` — is issued before the purpose validates.

Honest statement of the residual risk, for the README: a controlled vocabulary makes it one click to assert
a purpose that is not true. So does a text box. Neither the tool nor any tool can verify the operator's
lawful basis; what the tool can do is make the assertion unavoidable, explicit and permanently recorded,
and that is what it does.

### 7.3 Crawl pane — during a run

Start becomes **Stop**. There is deliberately **no Pause**: a paused crawl holds connections and a partial
lock on the host's attention while doing no work, which is worse manners than stopping and starting again.

Four regions, all live:

1. **Progress.** A determinate `QProgressBar` against `max_pages`, plus an authoritative label:
   `fetched N/BUDGET · queued Q · depth D · skipped S · errors E · elapsed mm:ss`. The label is the truth;
   the bar is an upper bound, because a crawl that exhausts its frontier finishes early and that is normal,
   not an error. The interface says "budget", never "estimated".
2. **Findings table.** `QTableView` over a `QAbstractTableModel`, user-sortable, columns:
   `Field · Value · Extraction · Pages · First seen`. `Extraction` shows the layer name; `Pages` is
   `page_support`. Rows append as findings appear and update in place as `page_support` grows. Selection
   supports `Ctrl+C` copying the selected rows as TSV.
3. **Page log.** `QTableView`, columns: `# · Depth · Status · URL · Detail`. `Status` is the machine code
   of §5.9 verbatim — @DF may add an icon or colour, but the code stays visible and copyable, because it is
   what an operator quotes when asking why something was skipped. The log is filterable by status.
4. **Compliance banner.** A single non-dismissible line pinned above the log:
   `User-Agent: OSINT-Scrapper/0.2.0 (+…; contact: …) · robots.txt: honored · interval: 1.0 s (floor 0.5 s) · scope: example.com +subdomains`.
   It has no close button. It is the product's honest-disclosure surface and it is always on screen while
   traffic is going out.

### 7.4 Runs pane

A `QTableView` over the run ledger, newest first. Columns:
`Date · Target host · Purpose · Pages · Findings · Size · Retention`.

`Retention` shows days remaining, and rows past their declared retention are visually distinguished.

Actions: **Open folder** · **Re-export…** (opens the export dialog for a completed run without
re-crawling) · **Delete** (multi-select) · **Delete expired**.

Delete asks for confirmation in a dialog that **names the exact directories** it will remove and states the
number of findings that will be destroyed. "Delete all runs" additionally requires typing the word
`DELETE`. Deletion removes the run directory and rewrites the ledger without those lines. Nothing is
deleted automatically, ever (FR-18).

This pane is the home of FR-17 and FR-18. In a CLI those were the `erase` subcommand and a number in a
JSON file; in a GUI they are a screen an operator actually looks at, which is a genuine improvement in a
capability that matters.

### 7.5 Errors, in three tiers

1. **Page-level.** A row in the page log with its status code and detail. Never a dialog, never a sound,
   never a modal. Partial failure is normal (Rule 0) and treating it as an event would train operators to
   dismiss dialogs reflexively.
2. **Run-level.** An inline banner at the top of the Crawl pane: the reason code, the URL, and one plain
   English sentence saying what happened and what the operator can do. Used for seed robots denial, seed
   unreachable, invalid configuration, and each of the four abort thresholds. The pane stays interactive
   and the log stays readable underneath it — this is the moment an operator most needs to read the log,
   so nothing may cover it.
3. **Programming errors.** An unexpected exception reaching the GUI thread produces a modal with the
   exception type, the message, and a **Copy details** button; the run is marked `failed` and whatever was
   collected remains exportable. This tier exists so that a bug is loud. It is the only modal in the
   product that is not initiated by the operator.

No error is ever swallowed, and no error path produces an empty success.

### 7.6 Threading contract

**Rule: the GUI thread never performs network I/O, HTML parsing, or any operation that can exceed 100 ms.**
This is FR-28 and it is not negotiable; a Qt application that blocks its event loop is a broken application.

What this specification fixes:

- The crawl runs on a worker thread. The mechanism — a `QObject` worker moved with `moveToThread`, or
  `QThreadPool` with `QRunnable`, both of which are documented Qt for Python patterns — is **@DB and @DF's
  choice**, not a product decision.
- The crawl use case knows nothing about Qt. It reports progress through an injected **`CrawlObserver`**
  port declared in `application/ports.py` (§8.7). The Qt adapter implementing it lives in `interfaces/` and
  translates observer calls into signals. This is the mechanism behind NFR-2.
- Cross-thread communication is by **queued signals only**. Widgets are touched from the GUI thread and
  from nowhere else.
- Progress signals are **batched** — a signal per fetched page, not per discovered URL and never per parsed
  element (NFR-11).
- Cancellation is **cooperative**, through an injected `CancellationToken` port checked between fetches.
  `QThread.terminate()` is forbidden: it can leave a half-written file and destroys the guarantee of FR-8.
  Stop must always yield a consistent, exportable partial report.
- Export runs off the GUI thread too. For current data volumes it would be fast enough not to, but the
  100 ms rule is stated as an absolute so that nobody has to re-derive the threshold per feature.

### 7.7 Configuration

Loaded with `tomllib`; first file found wins: `--config <path>` → `./osint-scrapper.toml` →
`$XDG_CONFIG_HOME/osint-scrapper/config.toml` (falling back to `~/.config/...`). The Settings pane writes
the first path that is writable and says which one it wrote.

```toml
[http]
contact_email = "you@example.org"
project_url = "https://github.com/TonioCodeur/OSINT_Scrapper"
request_interval_seconds = 1.0
timeout_seconds = 10.0
max_retries = 3
concurrent_requests = 2

[crawl]
max_pages = 200
max_depth = 3
include_subdomains = true
follow_sitemap = true
phone_region = "FR"

[purpose]
category = "due_diligence"
note = ""

[output]
directory = "runs"
retention_days = 30
formats = ["json", "csv", "xlsx"]
```

Environment overrides: `OSINT_SCRAPPER_CONTACT_EMAIL`, `OSINT_SCRAPPER_PROJECT_URL`,
`OSINT_SCRAPPER_OUTPUT_DIR`. Precedence: interface control > environment > config file > built-in default.
`contact_email` is validated with `email-validator`; without it the Start button stays disabled and the
Settings pane says why (FR-20). Values outside the bounds of §5.5 are clamped to the bound, and the
Settings pane reports the clamp rather than silently accepting the file's value.

### 7.8 Export dialog

A `QDialog` opened from **Run → Export…**, from the completion strip, or from Runs → Re-export.

- Five checkboxes: **JSON** (checked and **disabled** — the canonical record always exists), CSV, XLSX,
  JSONL, Markdown. The remaining four default from `[output].formats`.
- A destination chooser defaulting to the run directory. Choosing a different directory copies the exports
  there; the run directory always keeps its own canonical copy.
- An **Open folder when done** checkbox.
- **Export** / **Cancel**. Export runs off the GUI thread and reports per-file success in the dialog before
  it closes. A file that fails to write names itself and its error; the others still succeed.
- **The dialog does not close itself on success.** This follows from the sentence above rather than
  contradicting it: a dialog that vanishes the moment the last file lands has reported nothing, and the
  per-file result is the whole point of writing one. Export completes, each file's outcome appears in the
  dialog, and the operator closes it when they have read it. The **Cancel** button becomes **Close** once a
  run has finished, so the remaining button never invites the operator to think the export can still be
  called off.

### 7.9 About and Help

- **About** — application name, version, a one-line description, and a prominent statement that the
  application uses Qt through PySide6 under the LGPLv3, with a link that opens `THIRD_PARTY_LICENSES.md`.
  This is FR-19 and satisfies obligation 3 of §3.1; it is not optional chrome.
- **Legal use** — opens the README's *Legal use* section, so the obligations an operator carries are one
  menu item away rather than buried in a file they may never open.

---

## 8. Domain and extraction model

### 8.1 Fields extracted

Nine fields. Each is justified individually, because FR-15 requires that data minimization be argued and
not assumed.

| `FieldName` | Allowed layers | Why this field exists |
|---|---|---|
| `email` | all five | The primary published contact artifact and the reason most operators run this tool. Self-validating (FR-23). `metadata["email_kind"]` is `role` when the local part is a known role account (`contact`, `info`, `dpo`, `rgpd`, `privacy`, `legal`, `support`, `sales`, `press`, `presse`, `jobs`, `recrutement`, `security`, `abuse`, `postmaster`, `noreply`, …) and `other` otherwise. A role mailbox is organizational, not personal, and an operator must be able to filter on that. |
| `phone` | all five | Published contact point. Self-validating through libphonenumber. `metadata["number_type"]` records `MOBILE` / `FIXED_LINE` / … |
| `postal_address` | `well_known`, `structured_data`, `semantic_html` | Legally-mandated on imprint pages across the EU; it is published to be read. **Never from free text** — regex address detection has a false-positive rate that is unacceptable for a field this sensitive, and a wrong address exported as fact is exactly the failure Rule 0 forbids. |
| `person_name` | `well_known`, `structured_data`, `semantic_html` | Replaces v1.0's `given_name`/`family_name`/`full_name` with one field holding the name as the site published it. Splitting names is a locale minefield the product gains nothing from. **Never from free text**: "capitalized word pairs in body text" is a false-positive machine. `metadata["role"]` carries a job title when the same structured node provided one — which is why `role` is not a separate field: an orphan row reading "CEO" attached to nobody is noise. |
| `organization_name` | `well_known`, `structured_data`, `semantic_html` | Identifies whose site this is. From `schema.org` `Organization.name`, `og:site_name`, h-card organization classes. |
| `social_profile` | `well_known`, `structured_data`, `semantic_html` | The highest-value artifact a site crawl produces, and it is explicitly published by the site. **Only full profile URLs on a known platform list** (`github.com`, `gitlab.com`, `linkedin.com`, `x.com`, `twitter.com`, `facebook.com`, `instagram.com`, `youtube.com`, `tiktok.com`, `bsky.app`, `mastodon.social` and hosts serving `rel="me"` Mastodon links, `t.me`, `wa.me`, `discord.gg`, `reddit.com`, `medium.com`, `stackoverflow.com`) — never a bare `@handle` from text, which is ambiguous across platforms. `metadata["platform"]` records which. **These URLs are recorded, never fetched** (§5.3). |
| `pgp_key_url` | `well_known`, `semantic_html` | Where the site publishes a public key: `security.txt` `Encryption:`, `<link rel="pgpkey">`, an `<a href>` ending `.asc`/`.gpg`/`.pgp`. The URL is the useful OSINT fact. The key is **not** fetched and **not** parsed — parsing OpenPGP packets would mean a new dependency for a fingerprint nobody asked for. |
| `company_identifier` | `structured_data`, `semantic_html`, `text_heuristic` | SIREN, SIRET, EU VAT number, RCS entry. The one field that turns "a website" into "a legally identified entity", which is the whole purpose of an imprint page. Permitted from text **because it is self-validating** (FR-23): SIREN/SIRET carry a Luhn checksum and EU VAT numbers have per-country format rules. A candidate that fails its checksum is discarded silently. `metadata["scheme"]` records `siren` / `siret` / `vat_eu` / `rcs`. |
| `technology` | `semantic_html` only | The only **non-personal** field, and the only one GDPR minimization does not constrain. Sources are exactly three: `<meta name="generator">`, the `X-Powered-By` response header, and the `Server` response header. **No signature database, no JavaScript analysis, no version probing** — that is a different product (§1.2). Bounded like this it costs one small extractor and answers a question every OSINT operator asks. |

Deleted from v1.0 and not replaced: `given_name`, `family_name`, `full_name` (folded into `person_name`),
`role` (now metadata), `website` (a whole-site crawl's outbound links are a link dump, not intelligence;
the meaningful subset is `social_profile`).

`FieldName` declaration order is load-bearing: it is the primary sort key of every export (§9.1.1). The
order is: `email`, `phone`, `postal_address`, `person_name`, `organization_name`, `social_profile`,
`pgp_key_url`, `company_identifier`, `technology`.

### 8.2 Extraction layers

The five-layer pipeline of v1.0 carries over **structurally and numerically unchanged**, with its top layer
repurposed. The base scores measure *how reliably the extraction mechanism produced the value*, which is a
property of markup, not of the product; nothing about crawling one site instead of four sources changes how
much a `mailto:` href is worth relative to a regex over body text. The `api` layer had no producer left
once the four source adapters were deleted, and `well_known` takes its place with a real one.

| Order | Layer | `ExtractionLayer` | What it reads | Base |
|---|---|---|---|---|
| 1 | Well-known file | `WELL_KNOWN` | `/.well-known/security.txt` fields, per RFC 9116 (§5.6) | **0.95** |
| 2 | Structured markup | `STRUCTURED_DATA` | `<script type="application/ld+json">` schema.org; microdata `itemscope`/`itemprop` | **0.90** |
| 3 | Semantic HTML | `SEMANTIC_HTML` | `<a href="mailto:">`, `<a href="tel:">`, `<address>`, microformats2 / legacy h-card classes, `<meta name="author">`, `<meta name="generator">`, `<link rel="author">`, `<link rel="me">`, `<link rel="pgpkey">`, response headers | **0.75** |
| 4 | Text heuristics | `TEXT_HEURISTIC` | Email pattern and `phonenumbers.PhoneNumberMatcher` and company-identifier patterns over visible text | **0.50** |
| 5 | De-obfuscated text | `TEXT_HEURISTIC_DEOBFUSCATED` | `name [at] domain [dot] com` and its variants, including `＠` / `﹫` | **0.40** |

Layer 5 rewrites only the documented separators, and only when the rewritten string then passes email
validation. It never guesses a domain. It reads text the site chose to publish; it defeats naive address
harvesters, not access control, and stays inside "public data only".

Visible text for layers 4–5 is the document text after removing `<script>`, `<style>`, `<noscript>`,
`<template>` and HTML comments. Unchanged.

### 8.3 The self-validation rule (FR-23)

> A value may be extracted from free page text **only if an independent check can confirm it is
> well-formed.**

Three fields qualify: `email` (RFC-correct parse), `phone` (libphonenumber validity), `company_identifier`
(checksum). Six do not, and are extractable only from layers 1–3.

This one rule replaces v1.0's scattered per-field carve-outs. It is falsifiable, it is testable
mechanically (`ALLOWED_LAYERS` in `application/validation.py`), and it explains itself: a crawl of 200
pages of prose will produce hundreds of capitalized word pairs and dozens of number-and-street patterns.
Without a checkable invariant, a text-layer extractor for those fields does not find facts — it
manufactures them, at volume, and exports them with a confidence number attached. That is the single
worst thing this product could do.

### 8.4 Validation

A candidate becomes a finding only by passing its validator. Failures are discarded and logged at `debug`.

- **Email** — `validate_email(candidate, check_deliverability=False)`; stored value is `.normalized`,
  lower-cased. `check_deliverability` **must** stay `False`: DNS lookups would break NFR-6 and probing MX
  records is outside this product's purpose. `email_kind` is assigned from the role-account list of §8.1.
- **Phone** — layers 1–3 use `phonenumbers.parse(value, region)`; layers 4–5 use
  `phonenumbers.PhoneNumberMatcher(visible_text, region)`, never a hand-written regex. Rejected unless
  `is_valid_number`. Stored as E.164. The region comes from the crawl settings, not from a subject.
- **Person name** — collapse whitespace; reject if longer than 80 characters, if it contains a digit, or if
  it contains no alphabetic character. Casing and diacritics preserved in the stored value.
- **Postal address** — components joined `", "` in the order `street, postal_code, locality, region,
  country`, empty components skipped, whitespace collapsed. Length 6–300.
- **Organization name** — whitespace collapsed, maximum 200 characters.
- **Social profile** — must parse as an absolute `https` URL whose host is on the platform list; normalized
  by lower-casing the host, stripping `www.`, stripping tracking parameters and a trailing `/`. A platform
  root with no profile path (`https://twitter.com/`) is rejected.
- **PGP key URL** — absolute `http`/`https` URL. Not fetched.
- **Company identifier** — digits stripped of spaces and dots; SIREN must be 9 digits passing Luhn; SIRET 14
  digits passing Luhn; EU VAT must match its country's documented format. **A candidate that fails its
  checksum is discarded**, never exported with a lower score.
- **Technology** — whitespace collapsed, maximum 100 characters, non-empty.

### 8.5 Deduplication

Key: `(field, dedup_value)`.

| Field | Dedup normalization |
|---|---|
| `email` | the validated `.normalized`, lower-cased |
| `phone` | E.164 |
| `person_name`, `organization_name` | NFKD-decomposed, combining marks stripped, lower-cased, whitespace collapsed |
| `postal_address` | lower-cased, runs of non-alphanumerics collapsed to one space, trimmed |
| `social_profile` | the normalized profile URL, lower-cased |
| `pgp_key_url` | scheme-and-`www.`-stripped, lower-cased, trailing `/` stripped |
| `company_identifier` | digits only, plus the scheme |
| `technology` | lower-cased, whitespace collapsed |

Accent folding builds the key only; the stored, exported value keeps its diacritics and casing (the
first-seen highest-layer variant wins). Two candidates with the same key merge into one finding whose
provenance is the union.

### 8.6 Confidence and support — the honest replacement for corroboration

v1.0's formula rewarded **independent sources** confirming a value: `base + 0.05 × (anchored_sources − 1)`,
with a 0.60 ceiling when nothing anchored the identity. In this product there is exactly one source. Every
term of that formula except `base` has lost its referent, and `identity_unconfirmed` describes a risk
(homonyms) that no longer exists because there is no name being matched. Keeping the formula and quietly
feeding it pages instead of sources would produce a number that looks like the old one, is read like the
old one, and means nothing.

**Decision: do not blend. Export two numbers, each of which means exactly one thing.**

```
extraction_confidence = max(LAYER_BASE_CONFIDENCE[p.extraction_layer] for p in provenance)
page_support          = number of DISTINCT canonical source_urls among provenance
occurrence_count      = total number of provenance entries
```

- **`extraction_confidence` ∈ {0.40, 0.50, 0.75, 0.90, 0.95}** — "how was this obtained". It is a
  discrete label, not a continuum, and no arithmetic is ever performed on it. A value in JSON-LD is 0.90
  whether it appears on one page or four hundred, because the *extraction* was equally sound either way.
- **`page_support` ∈ ℕ, ≥ 1** — "on how many distinct pages of this site did it appear". A count, not a
  score. It is left as an integer precisely so nobody can mistake it for a probability.
- **`occurrence_count`** — total observations including several layers on one page. Reported for
  completeness; it is `page_support` that carries signal.

How to read `page_support`, stated in the README so the number is not misused: high support means
**site-wide**, typically a footer or a contact block, which identifies the *organization*. Support of 1
means **page-local**, typically a specific person or a specific department. Neither is better; they answer
different questions. Support is emphatically **not** corroboration in the v1.0 sense — the same site
repeating itself is one publisher speaking once, loudly.

**Provenance is capped at 10 entries per finding**, kept in the deterministic order of §9.1.1, while
`page_support` and `occurrence_count` always record the true totals. This bounds a report where a footer
email appears on 400 pages without losing the fact that it did.

Deleted with the formula: `confidence`, `disputed`, `identity_unconfirmed`, `match_basis`, `MatchBasis`,
`ValueType`, `Conflict`, the whole `conflicts` export section, and the `?` legend in the human report.

### 8.7 Domain and ports after the refactor

```python
class FieldName(StrEnum):            # declaration order is the export sort order
    EMAIL = "email"
    PHONE = "phone"
    POSTAL_ADDRESS = "postal_address"
    PERSON_NAME = "person_name"
    ORGANIZATION_NAME = "organization_name"
    SOCIAL_PROFILE = "social_profile"
    PGP_KEY_URL = "pgp_key_url"
    COMPANY_IDENTIFIER = "company_identifier"
    TECHNOLOGY = "technology"

class ExtractionLayer(StrEnum):
    WELL_KNOWN = "well_known"
    STRUCTURED_DATA = "structured_data"
    SEMANTIC_HTML = "semantic_html"
    TEXT_HEURISTIC = "text_heuristic"
    TEXT_HEURISTIC_DEOBFUSCATED = "text_heuristic_deobfuscated"

class PurposeCategory(StrEnum):      # §7.2.2
    SECURITY_ASSESSMENT = "security_assessment"
    DUE_DILIGENCE = "due_diligence"
    JOURNALISM = "journalism"
    SELF_AUDIT = "self_audit"
    ACADEMIC_RESEARCH = "academic_research"
    OTHER = "other"

class PageStatus(StrEnum):           # §5.9, all seventeen values
    ...

class CrawlOutcome(StrEnum):
    COMPLETED = "completed"
    BUDGET_EXHAUSTED = "budget_exhausted"
    DEPTH_EXHAUSTED = "depth_exhausted"
    STOPPED_BY_OPERATOR = "stopped_by_operator"
    ABORTED_RATE_LIMITED = "aborted_rate_limited"
    ABORTED_HOST_UNHEALTHY = "aborted_host_unhealthy"
    ABORTED_ERROR_RATE = "aborted_error_rate"
    FAILED = "failed"
```

- `CrawlTarget` (frozen) — `entered_value`, `target_url`, `scope_host`, `include_subdomains`.
- `CrawlSettings` (frozen) — `max_pages`, `max_depth`, `request_interval_seconds`, `concurrent_requests`,
  `include_subdomains`, `follow_sitemap`, `phone_region`, `retention_days`. `__post_init__` enforces every
  bound of §5.5 and raises `InvalidCrawlSettingsError`.
- `Purpose` (frozen) — `category: PurposeCategory`, `note: str`. `__post_init__` enforces the ≥ 16-character
  note when the category is `OTHER`.
- `Provenance` (frozen) — `source_url`, `collected_at` (aware UTC), `extraction_layer`, `raw_value`
  (≤ 200 chars). Raises on a blank URL or a naive timestamp. **`source_id` and `match_basis` are gone.**
- `Finding` (frozen, replaces `Attribute`) — `field`, `value`, `extraction_confidence`, `page_support`,
  `occurrence_count`, `first_seen_url`, `metadata: Mapping[str, str]`,
  `provenance: tuple[Provenance, ...]` (non-empty, ≤ 10 — enforced in `__post_init__`).
- `RawField` (frozen, the extractor→application contract) — `field`, `raw_value`, `source_url`,
  `collected_at`, `extraction_layer`, `metadata`.
- `PageOutcome` (frozen) — `url`, `depth`, `status: PageStatus`, `detail: str | None`, `http_status: int |
  None`, `content_type: str | None`, `findings_count: int`.
- `SiteReport` (frozen, replaces `InvestigationReport` and `PersonProfile`) — `run_id`, `target`,
  `settings`, `purpose`, `started_at`, `finished_at`, `outcome: CrawlOutcome`, `outcome_detail`,
  `tool_name`, `tool_version`, `user_agent`, `findings: tuple[Finding, ...]`,
  `pages: tuple[PageOutcome, ...]`, `pages_fetched`, `requests_made`.

Ports in `application/ports.py`. Kept: `Clock`, `MonotonicClock`, `Sleeper`, `IdGenerator`, `RobotsPolicy`,
`RateLimiter`, `PageFetcher`, `ResultWriter`, `RunLedger`, `DirectoryRemover`, `FieldValidator`.
Deleted: `SourceAdapter`, `SourceRegistry`. New:

| Port | Surface | Implemented by |
|---|---|---|
| `CrawlObserver` | `crawl_started(target, settings)`; `page_finished(PageOutcome)`; `findings_updated(tuple[Finding, ...])`; `frontier_changed(queued, deepest_depth)`; `crawl_finished(SiteReport)` | `QtCrawlObserver` in `interfaces/`; `RecordingObserver` in tests |
| `CancellationToken` | `is_cancelled() -> bool` | `QtCancellationToken`; `NeverCancelled` in tests |
| `LinkExtractor` | `links(page: FetchedPage) -> tuple[str, ...]` | `HtmlLinkExtractor` |
| `SitemapReader` | `locations(document: FetchedPage) -> tuple[str, ...]` | `BeautifulSoupSitemapReader` |

**`frontier_changed` is the fifth method, and this table is the one that is right.** An earlier draft of
this section listed four while §7.3 fixed the progress label verbatim as
`fetched N/BUDGET · queued Q · depth D · …`. No other observer call carries `queued` or the deepest depth
reached: `page_finished` describes a URL that has left the frontier, and by the time `crawl_finished`
arrives the frontier is empty. The label was the binding requirement and the port was short one method, so
the port grew one — resolved in favour of §7.3, which is the operator-visible contract.

`FetchedPage` gains `headers: Mapping[str, str]` (lower-cased keys), required by the `technology`
extractor and by `Retry-After` handling. `PageFetcher.fetch` keeps its exception contract and adds nothing.

`ResultWriter.write(report: SiteReport, destination_dir: Path) -> tuple[Path, ...]` — the shape is
unchanged, only the report type differs.

---

## 9. Export schemas

All exports live in `<output-dir>/<run_id>/`. Timestamps are RFC 3339 UTC with a `Z` suffix, produced as
`datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")`. `run_id` keeps the `r-` prefix.

### 9.1 `report.json` — canonical, a superset of every other format

UTF-8, `ensure_ascii=False`, `indent=2`, key order exactly as written below (not sorted), trailing newline.
**No key outside this schema is ever written**, and a test asserts it (AC-EXPORT-4).

```json
{
  "schema_version": "2.0",
  "run": {
    "run_id": "r-8f3a2c19",
    "started_at": "2026-07-27T14:02:11Z",
    "finished_at": "2026-07-27T14:09:48Z",
    "outcome": "completed",
    "outcome_detail": null,
    "purpose_category": "due_diligence",
    "purpose_note": "",
    "retention_days": 30,
    "tool": {
      "name": "osint-scrapper",
      "version": "0.2.0",
      "user_agent": "OSINT-Scrapper/0.2.0 (+https://github.com/TonioCodeur/OSINT_Scrapper; contact: you@example.org)"
    }
  },
  "target": {
    "entered_value": "example.com",
    "target_url": "https://example.com/",
    "scope_host": "example.com",
    "include_subdomains": true
  },
  "settings": {
    "max_pages": 200,
    "max_depth": 3,
    "request_interval_seconds": 1.0,
    "concurrent_requests": 2,
    "follow_sitemap": true,
    "phone_region": "FR"
  },
  "statistics": {
    "pages_fetched": 147,
    "requests_made": 152,
    "pages_skipped": 38,
    "pages_failed": 5,
    "findings_count": 63
  },
  "findings": [
    {
      "field": "email",
      "value": "contact@example.com",
      "extraction_confidence": 0.9,
      "page_support": 41,
      "occurrence_count": 78,
      "first_seen_url": "https://example.com/",
      "metadata": { "email_kind": "role" },
      "provenance": [
        {
          "source_url": "https://example.com/",
          "collected_at": "2026-07-27T14:02:13Z",
          "extraction_layer": "structured_data",
          "raw_value": "contact@example.com"
        }
      ]
    }
  ],
  "pages": [
    {
      "url": "https://example.com/",
      "depth": 0,
      "status": "ok",
      "detail": null,
      "http_status": 200,
      "content_type": "text/html",
      "findings_count": 6
    },
    {
      "url": "https://example.com/private/",
      "depth": 1,
      "status": "skipped_robots",
      "detail": "robots_disallow — https://example.com/robots.txt denies /private/",
      "http_status": null,
      "content_type": null,
      "findings_count": 0
    }
  ]
}
```

#### 9.1.1 Deterministic ordering (NFR-9)

Because §6.4 permits concurrent fetches, **arrival order is never an ordering input anywhere.**

- `findings`: by `field` in `FieldName` declaration order, then `extraction_confidence` descending, then
  `page_support` descending, then `value` ascending.
- `provenance` within a finding: by `source_url` ascending, then `collected_at` ascending, then
  `extraction_layer` ascending. Truncation to 10 entries happens **after** this sort, so the retained
  entries are stable across runs.
- `pages`: by `depth` ascending, then `url` ascending. Not by fetch order.
- `first_seen_url` is the **lowest** canonical URL among the finding's provenance under this same sort —
  not the chronologically first, which would be nondeterministic.

### 9.2 `report.csv` and `report_pages.csv`

One row **per provenance entry**, so every row is fully attributed and the file is flat and
tool-friendly. `csv.writer`, file opened with `newline=""` and `encoding="utf-8-sig"` (the BOM is why Excel
reads accented values correctly), `lineterminator="\r\n"` (RFC 4180), `quoting=csv.QUOTE_MINIMAL`.

`report.csv` columns, in exactly this order:

```
run_id, purpose_category, purpose_note, retention_days,
target_entered, target_url, scope_host,
field, value, email_kind, extraction_confidence, page_support, occurrence_count, first_seen_url,
source_url, extraction_layer, raw_value, collected_at,
tool_name, tool_version
```

`email_kind` is empty for every field but `email`. Other per-field metadata (`number_type`, `platform`,
`scheme`, `role`) is present in JSON and JSONL; it is deliberately **not** given a column each, which would
produce a wide sheet that is mostly empty.

`report_pages.csv` columns:

```
run_id, url, depth, status, detail, http_status, content_type, findings_count
```

### 9.3 `report.xlsx`

`openpyxl`, `Workbook(write_only=True)`, exactly four sheets in this order:

1. **`Run`** — two columns (`key`, `value`); rows: `run_id`, `started_at`, `finished_at`, `outcome`,
   `outcome_detail`, `purpose_category`, `purpose_note`, `retention_days`, `tool_name`, `tool_version`,
   `user_agent`, `target_entered`, `target_url`, `scope_host`, `include_subdomains`, `max_pages`,
   `max_depth`, `request_interval_seconds`, `concurrent_requests`, `follow_sitemap`, `phone_region`,
   `pages_fetched`, `requests_made`, `pages_skipped`, `pages_failed`, `findings_count`.
2. **`Findings`** — header row identical, cell for cell, to `report.csv`.
3. **`Pages`** — header row identical, cell for cell, to `report_pages.csv`.
4. **`Compliance`** — two columns (`key`, `value`); rows: `user_agent`, `robots_txt_honored` (always
   `true`), `robots_txt_url`, `effective_interval_seconds`, `hard_floor_seconds`, `concurrent_requests`,
   `pages_skipped_by_robots`, `retention_days`, `purpose_category`, `purpose_note`. This sheet exists so
   that the compliance posture of a run is a first-class artifact an auditor can read without parsing JSON.

Header rows are bold, written as `WriteOnlyCell(ws, value=...)` with `cell.font = Font(bold=True)`.
`extraction_confidence` is written as a float; `page_support`, `occurrence_count`, `depth`, `http_status`
and every count as ints; every other cell as a string with the formula guard applied.

### 9.4 `report.jsonl`

One JSON object per line, UTF-8, LF line endings, no BOM. Each line is one **finding × provenance entry**,
with the same fields as a `report.csv` row plus the full `metadata` object — except that `email_kind` is
not repeated at the top level, because `metadata` already carries it and a machine format must not hold the
same fact twice. Numbers stay numbers, values
containing newlines need no quoting, and the file is appendable and streamable — which is the reason it
exists alongside CSV rather than instead of it. Line order follows §9.1.1. No formula guard applies:
JSONL is not a spreadsheet, and mangling values with an apostrophe would corrupt a machine format.

### 9.5 `report.md`

The human deliverable. Structure, in order:

```markdown
# OSINT report — example.com

| Run | r-8f3a2c19 |
| Target | https://example.com/ (scope: example.com, subdomains included) |
| Purpose | due_diligence |
| Started / finished | 2026-07-27T14:02:11Z → 2026-07-27T14:09:48Z |
| Outcome | completed |
| Pages fetched | 147 of a 200-page budget, depth 3 |
| Findings | 63 |

## Findings
### email
| Value | Extraction | Pages | First seen |
...one section per field, fields in declaration order, rows per §9.1.1

## Pages
| Depth | Status | URL | Detail |
...

## Compliance
- User-Agent: ...
- robots.txt honored on every request and every redirect hop; N pages skipped by robots
- Effective request interval: 1.0 s (hard floor 0.5 s)
- Retention declared: 30 days
```

Cell values have `|`, backticks and backslashes escaped, `<` and `>` entity-escaped, `[` and `]` escaped so
no scraped value can render as a link, and newlines replaced by a space. **No raw HTML is
ever emitted**, so a Markdown renderer cannot be made to execute anything a crawled site published.

### 9.6 Formula-injection guard

Any CSV or XLSX cell whose first character is one of `=`, `+`, `-`, `@`, TAB or CR is written prefixed with
a single apostrophe. Mandatory, unchanged from v1.0, and more necessary than before: these files now carry
text scraped from hundreds of third-party pages straight into a spreadsheet. Applies to CSV and XLSX only
(§9.4, §9.5).

### 9.7 Run ledger

`<output-dir>/index.jsonl`, append-only, one JSON object per line:

```json
{"run_id":"r-8f3a2c19","target_host":"example.com","target_url":"https://example.com/","purpose_category":"due_diligence","purpose_note":"","created_at":"2026-07-27T14:09:48Z","retention_days":30,"directory":"runs/r-8f3a2c19","pages_fetched":147,"findings_count":63,"files":["report.json","report.csv"]}
```

**`subject_key` is replaced by a plaintext `target_host`, and this is a deliberate reversal.** v1.0 hashed
the subject so the ledger never held a plaintext person's name — a real data-minimization win, because the
ledger sat next to reports that also held that name and the hash bought a cheap layer of separation. Here
the target is a *hostname*, generally not personal data; the report file in the very same directory
contains it in full; and the Runs screen must be able to show the operator what they crawled without
opening every report on disk. Hashing it would buy nothing and cost the feature. Where a hostname *is*
personal data (`jean-dupont.example`), the remedy is the same one GDPR actually asks for: delete the run,
which is one click away in the same screen.

**`runs/` stays git-ignored.** It holds collected personal data. This does not change and no exception
exists.

---

## 10. Project layout after the refactor

```
pyproject.toml            PySide6 added; console script now launches the GUI
uv.lock
README.md  README.fr.md   rewritten for v0.2.0
THIRD_PARTY_LICENSES.md   NEW — LGPLv3 obligation (FR-19)
CLAUDE.md                 updated to describe v0.2.0
docs/SPEC.md              this document
docs/MIGRATION.md         NEW — the demolition plan
osint-scrapper.toml.example
src/osint_scrapper/
  __init__.py             __version__ = "0.2.0"
  __main__.py             launches the GUI
  domain/                 stdlib ONLY
    url.py                NEW — canonicalize(), in_scope(), spider-trap guard (§5.2, §5.3)
    target.py             NEW — CrawlTarget, CrawlSettings, Purpose, PurposeCategory
    crawl.py              NEW — PageStatus, PageOutcome, CrawlOutcome
    attributes.py         REWRITTEN — FieldName, ExtractionLayer, RawField, Provenance, Finding
    confidence.py         REDUCED — the layer table only; no formula
    report.py             REWRITTEN — SiteReport
    errors.py             KEPT, minus InvalidSubjectError, plus InvalidTargetError,
                          InvalidCrawlSettingsError
    subject.py            DELETED
    profile.py            DELETED
    source.py             DELETED
  application/
    ports.py              REWRITTEN — CrawlObserver, CancellationToken, LinkExtractor,
                          SitemapReader added; SourceAdapter, SourceRegistry deleted
    errors.py             KEPT verbatim
    frontier.py           NEW — Frontier and VisitedSet, pure, stdlib deque + set
    crawl.py              NEW — CrawlSiteUseCase (replaces investigate.py)
    aggregate.py          NEW — FindingAggregator (replaces merge.py; no conflicts)
    validation.py         KEPT, reworked — ALLOWED_LAYERS now encodes FR-23; no Subject parameter
    export.py             NEW — ExportRunUseCase (export is now a separate operator action)
    runs.py               NEW — ListRunsUseCase, EraseRunsUseCase (replaces erase.py)
    investigate.py        DELETED
    merge.py              DELETED
    erase.py              DELETED
  infrastructure/
    config.py             EXTENDED — [crawl], [purpose], concurrent_requests, formats
    clock.py ids.py       KEPT verbatim
    http/
      user_agent.py       KEPT verbatim
      robots.py           KEPT verbatim
      rate_limit.py       KEPT, plus the 0.5 s hard floor
      requests_fetcher.py KEPT, reworked — FetchPolicy replaces SourceDescriptor;
                          headers exposed; body size cap; scope-aware redirect gating
    discovery/            NEW
      links.py            HtmlLinkExtractor
      sitemap.py          BeautifulSoupSitemapReader (§5.6)
      security_txt.py     RFC 9116 parser
    extraction/
      text.py             KEPT verbatim
      pipeline.py         KEPT, reworked — PageExtractor.extract loses the Subject parameter
      jsonld.py           KEPT, remapped to the new FieldName set
      microdata.py        KEPT, remapped
      semantic_html.py    KEPT, remapped; h-card person mapping reduced, mailto/tel kept
      schema_org.py       REWRITTEN — new vocabulary map, sameAs → social_profile
      text_heuristics.py  KEPT, region parameter instead of Subject; company-id patterns added
      social.py           NEW — platform list and profile-URL normalization
      technology.py       NEW — generator meta and two response headers
    validators/
      email.py            KEPT, reworked — role-account classification only, no Subject
      phone.py            KEPT — region parameter instead of Subject
      address.py          KEPT
      names.py            KEPT, renamed to person_name, no ValueType
      website.py          SPLIT — organization validator kept, website validator deleted
      social.py           NEW
      company_id.py       NEW — SIREN/SIRET Luhn, EU VAT formats
      pgp.py              NEW
      technology.py       NEW
      hints.py            DELETED — ValueType is gone
    writers/
      sanitize.py         KEPT verbatim
      rows.py             REWRITTEN — the new column schemas of §9
      json_writer.py      REWRITTEN — schema_version 2.0
      csv_writer.py       KEPT, new columns
      xlsx_writer.py      KEPT, four sheets
      jsonl_writer.py     NEW
      markdown_writer.py  NEW
    ledger/
      jsonl_ledger.py     KEPT, reworked — target_host replaces subject_key
    sources/              DELETED ENTIRELY (registry.py and all four adapters)
  interfaces/
    app.py                NEW — the SINGLE composition root; QApplication bootstrap
    launcher.py           NEW — argparse for --config / --log-level / --version (§4)
    main_window.py        NEW
    crawl_pane.py         NEW
    runs_pane.py          NEW
    settings_pane.py      NEW
    export_dialog.py      NEW
    about_dialog.py       NEW — FR-19
    models.py             NEW — QAbstractTableModel for findings and pages
    view_models.py        NEW — plain-Python presentation logic, testable without QApplication
    worker.py             NEW — the crawl worker, QtCrawlObserver, QtCancellationToken
    cli.py                DELETED
tests/
  conftest.py             the no-socket autouse fixture stays exactly as it is
  fixtures/
    site/                 NEW — a committed mini-site: index, contact, legal notice, team,
                          sitemap.xml, robots.txt, security.txt, an obfuscated-email page,
                          an off-scope link page, a redirect chain, a spider trap
    robots/               KEPT
    golden/               REWRITTEN
  domain/ application/ infrastructure/ interfaces/
  test_architecture_boundaries.py   extended with the no-PySide6-outside-interfaces rule
  test_end_to_end.py                REWRITTEN, same philosophy (§11, AC-E2E-1)
```

---

## 11. Acceptance criteria (@LT reviews against these)

### Architecture

- **AC-ARCH-1** A test walks every `.py` under `domain/`, parses it with `ast`, and asserts every imported
  root module is in `sys.stdlib_module_names` or is `osint_scrapper.domain`.
- **AC-ARCH-2** The same for `application/`, allowing stdlib plus `osint_scrapper.domain` and
  `osint_scrapper.application`.
- **AC-ARCH-3** **No module outside `src/osint_scrapper/interfaces/` imports `PySide6`.** The `ast` walk
  covers `import PySide6…`, `from PySide6…` and any dynamic `importlib` reference to the string.
- **AC-ARCH-4** No source-registry vocabulary survives: a test greps the whole of `src/` for
  `SourceDescriptor`, `SourceAdapter`, `source_id`, `match_basis`, `subject_key`, `PersonProfile` and
  `identity_unconfirmed` and fails on any hit.
- **AC-ARCH-5** The composition root is unique: `interfaces/app.py` is the only module that instantiates
  `RequestsPageFetcher`, `RobotsTxtPolicy`, `PerHostRateLimiter`, `CrawlSiteUseCase` or any `ResultWriter`.
- **AC-ARCH-6** `mypy --strict src/` and `ruff check .` pass clean.
- **AC-ARCH-7** `CrawlSiteUseCase` runs to completion in a test with a fake fetcher, a recording observer
  and a never-cancelled token, **with no `QApplication` ever constructed**.

### Crawl

- **AC-CRAWL-1** Canonicalization is tested against a table covering every rule of §5.2: fragment dropped,
  default port dropped, host lower-cased and IDNA-encoded, `.`/`..` resolved, duplicate slashes collapsed,
  path case preserved, trailing slash preserved, tracking and session parameters removed, remaining
  parameters sorted, userinfo rejected, and each of the four spider-trap rejections.
- **AC-CRAWL-2** Scope: with seed `https://www.example.com/`, `blog.example.com` is in scope with
  subdomains on and out with it off; `example.org` is always out; `notexample.com` is out (a suffix test
  that is not a label-boundary test would wrongly admit it); with seed `docs.example.com`, `example.com` is
  out.
- **AC-CRAWL-3** A crawl over the committed mini-site with `max_pages=5` fetches exactly 5 pages and marks
  the remaining discovered URLs `skipped_budget`. With `max_depth=1`, no depth-2 URL is fetched and each is
  marked `skipped_depth`.
- **AC-CRAWL-4** A page linking to `/contact` and to forty blog posts fetches `/contact` before any blog
  post, proving the §5.4 priority boost.
- **AC-CRAWL-5** A URL reachable at `/a`, `/a/` and `/a?utm_source=x` that all resolve to one final URL is
  fetched once and appears once in `pages`.
- **AC-CRAWL-6** `robots.txt` declaring two `Sitemap:` lines causes both to be read; a sitemap index is
  followed one level and no further; a sitemap with 900 `<loc>` entries contributes exactly 500; a sitemap
  document above 10 MiB is recorded `too_large` and contributes nothing.
- **AC-CRAWL-7** `/.well-known/security.txt` yields `email` from a `mailto:` `Contact:`, `phone` from a
  `tel:` `Contact:` and `pgp_key_url` from `Encryption:`, all at layer `well_known`, and none of those URLs
  enters the frontier.
- **AC-CRAWL-8** Every extension of §5.7 produces `skipped_extension` **with zero HTTP requests issued** —
  asserted with a counting fake fetcher. A `Content-Type: application/pdf` on an extensionless URL produces
  `skipped_content_type` with the body never parsed. A 6 MiB body produces `too_large`.
- **AC-CRAWL-9** A crawl with `concurrent_requests=2` over a fixture set produces exports byte-identical to
  the same crawl with `concurrent_requests=1`, modulo `run_id` and timestamps. This is the test that proves
  NFR-9 survives §6.4.

### Network compliance

- **AC-NET-1** `RobotsTxtPolicy` is tested against every row of §6.2.2: 200-allow, 200-disallow, 301→200,
  401, 403, 404, 500, timeout, 600 KiB body, undecodable body, redirect loop. Each asserts `allowed` **and**
  the `reason` code.
- **AC-NET-2** robots is evaluated **per URL**: with a `robots.txt` disallowing `/private/`, a crawl that
  discovers `/public/a` and `/private/b` fetches only the first and records `skipped_robots` with the
  matched path for the second.
- **AC-NET-3** robots is evaluated **per redirect hop**: an allowed `/go` that 302s to a disallowed
  `/private/x` issues no request for the target and records `skipped_robots`. A `/go` that 302s to
  `https://elsewhere.example/` records `off_scope_redirect` and does not follow. Six hops record
  `too_many_redirects`.
- **AC-NET-4** `PerHostRateLimiter` with an injected fake clock and fake sleeper (the test never really
  sleeps): two requests are separated by at least the effective interval; `Crawl-delay: 5` overrides a
  configured 1.0 s; a configured 0.1 s is raised to the 0.5 s hard floor; the limiter is shared across two
  concurrent workers so the combined rate never exceeds one start per interval.
- **AC-NET-5** `build_user_agent()` contains the tool name, version, project URL and contact email, and
  raises `DishonestUserAgentError` for every browser token. A test asserts that no config key, environment
  variable, CLI argument or widget can set a User-Agent.
- **AC-NET-6** Abort thresholds: three consecutive 429 abort with `aborted_rate_limited`; ten consecutive
  transport failures abort with `aborted_host_unhealthy`; a 60 % failure rate after 20 fetches aborts with
  `aborted_error_rate`; `Retry-After: 600` aborts immediately. Each produces a complete, exportable report
  containing every finding collected before the abort.
- **AC-NET-7** A `robots.txt` denying the target itself means the run does not start: no run directory, no
  ledger entry, zero content requests, and a run-level error carrying the robots URL and reason.

### Extraction

- **AC-EXTRACT-1** The same email in JSON-LD, in a `mailto:` href and in plain text on **one** page yields
  **one** finding with `extraction_confidence = 0.90`, `page_support = 1`, `occurrence_count = 3`.
- **AC-EXTRACT-2** The same email in the footer of forty crawled pages yields one finding with
  `page_support = 40`, `occurrence_count = 40`, exactly 10 provenance entries, and an unchanged
  `extraction_confidence`. **No blended score appears anywhere in any export.**
- **AC-EXTRACT-3** `jean [at] example [dot] com` yields `jean@example.com` at layer
  `text_heuristic_deobfuscated`, `extraction_confidence = 0.40`. A de-obfuscation that then fails email
  validation is discarded.
- **AC-EXTRACT-4** `+33 1 23 45 67 89` in visible text with region `FR` yields `+33123456789`; `+33 1 23` is
  rejected and absent from every export.
- **AC-EXTRACT-5** FR-23 is mechanical: for each of `postal_address`, `person_name`, `organization_name`,
  `social_profile`, `pgp_key_url` and `technology`, a raw candidate at layer `text_heuristic` or
  `text_heuristic_deobfuscated` is rejected by `ValidationPolicy` and never reaches a finding.
- **AC-EXTRACT-6** `contact@example.com` is `email_kind = role`; `j.martin@example.com` is
  `email_kind = other`.
- **AC-EXTRACT-7** A SIREN with a valid Luhn checksum in body text becomes a `company_identifier` with
  `metadata["scheme"] = "siren"`; the same digits with one changed is discarded and appears nowhere.
- **AC-EXTRACT-8** `<a href="https://github.com/exampleorg">` yields a `social_profile` with
  `metadata["platform"] = "github"`; `https://github.com/` alone is rejected; `@exampleorg` in body text
  yields nothing; **and a counting fake fetcher proves the social URL was never requested.**
- **AC-EXTRACT-9** `<meta name="generator" content="WordPress 6.5">` and an `X-Powered-By` header each
  yield a `technology` finding at layer `semantic_html`; nothing else on the page does.
- **AC-EXTRACT-10** A fixture with its expected structure removed makes the parser raise
  `SelectorNotFoundError` naming the selector and the URL; the page is recorded `parse_error`, the crawl
  continues, and **no partially-filled finding is emitted**.

### Interface

- **AC-UI-1** The Start button is disabled until both the target and the purpose validate; its tooltip
  names the missing one. With purpose `other` and a 10-character note it stays disabled.
- **AC-UI-2** No HTTP request of any kind — including `robots.txt` — is issued before the purpose
  validates, asserted with a counting fake fetcher.
- **AC-UI-3** Stop produces `outcome = "stopped_by_operator"` and a report that exports cleanly in all five
  formats. `QThread.terminate` appears nowhere in `src/` (grep test).
- **AC-UI-4** The interface remains responsive during a crawl: a view-model test drives 500 batched
  progress updates and asserts the model never processes them one signal per row, and a `pytest-qt` smoke
  test asserts the event loop processes user input while a fake crawl is running.
- **AC-UI-5** Every product setting round-trips through `osint-scrapper.toml`; `QSettings` is used **only**
  for window geometry and column widths (grep test on the `QSettings` call sites).
- **AC-UI-6** A config file declaring `max_pages = 99999` is clamped to 2000, the Settings pane reports the
  clamp, and `CrawlSettings` raises `InvalidCrawlSettingsError` if constructed directly with 99999.
- **AC-UI-7** The compliance banner is present and has no close button, and the About dialog names Qt,
  PySide6 and the LGPLv3 and resolves the link to `THIRD_PARTY_LICENSES.md`.
- **AC-UI-8** Runs pane: delete removes the run directory and its ledger lines; the confirmation names the
  directories; a second delete of the same run reports nothing matched rather than failing; "delete all"
  requires typing `DELETE`.

### Export

- **AC-EXPORT-1** `report.csv` column order matches §9.2 exactly; a value `=cmd()` is written `'=cmd()`;
  the file starts with a UTF-8 BOM and uses CRLF.
- **AC-EXPORT-2** `report.xlsx` has exactly the four sheets `Run`, `Findings`, `Pages`, `Compliance` in
  that order; the `Findings` header equals the `report.csv` header cell for cell; the `Pages` header equals
  the `report_pages.csv` header; the formula guard applies.
- **AC-EXPORT-3** `report.jsonl` has one object per line, LF endings, no BOM, no formula guard, and its
  line order matches §9.1.1. `report.md` contains no raw HTML and escapes `|` and backticks in values.
- **AC-EXPORT-4** A test compares the keys present in `report.json` against §9.1 and fails on any key
  outside it. No page HTML, no response body and no free page text is written to disk anywhere under
  `runs/`.
- **AC-EXPORT-5** JSON cannot be deselected in the export dialog, and a run directory always contains
  `report.json`.
- **AC-EXPORT-6** Re-export from the Runs pane produces the same files as the original export, byte for
  byte, without issuing a single HTTP request.

### Legal and privacy

- **AC-LEGAL-1** `purpose_category` and `purpose_note` appear in `report.json`, in every row of
  `report.csv`, in every line of `report.jsonl`, on the `Run` and `Compliance` sheets of `report.xlsx`, in
  `report.md`, and in the ledger.
- **AC-LEGAL-2** Every exported finding has at least one provenance entry with a non-empty `source_url` and
  a `collected_at` that parses as RFC 3339 UTC. Constructing a `Finding` with an empty provenance tuple
  raises, and so does constructing one with more than 10 entries.
- **AC-LEGAL-3** `raw_value` is never longer than 200 characters in any export.
- **AC-LEGAL-4** The ledger holds `target_host` in plaintext and holds no page content. Deleting a run
  removes the directory and rewrites the ledger without those lines.
- **AC-LEGAL-5** `runs/` is git-ignored; a test asserts the `.gitignore` entry exists.
- **AC-LEGAL-6** No fixture under `tests/fixtures/` contains a real person's data — reviewed by @LT;
  invented values on `example.com` / `example.org` only.

### End to end

- **AC-E2E-1** `tests/test_end_to_end.py` runs the whole chain — real `CrawlSiteUseCase`, real frontier,
  real canonicalization, real robots policy, real rate limiter, real extraction pipeline, real aggregator,
  real writers — over the committed mini-site under `tests/fixtures/site/`, faking **only** the
  `PageFetcher`, the clock and the sleeper, and asserts on the emitted `report.json`, `report.csv`,
  `report_pages.csv`, `report.xlsx`, `report.jsonl` and `report.md`. It is the only test that catches drift
  between what an extractor puts in a `RawField` and what the aggregator expects. **Its real collaborators
  must not be replaced with stubs.** The mini-site must exercise: robots allow and disallow, a redirect
  chain, an off-scope redirect, an off-scope link, a sitemap, a `security.txt`, a binary-extension link, a
  wrong-content-type response, a spider trap, an obfuscated email, and a page that raises
  `SelectorNotFoundError`.

### Documentation

- **AC-DOC-1** `README.md` contains every H2 section of §12, in order (grep-checked).
- **AC-DOC-2** `README.fr.md` has the same section structure; @LT checks that neither README describes a
  behaviour this specification does not state.
- **AC-DOC-3** `CLAUDE.md` is updated: repository state, build/lint/test commands, the module architecture
  of §10, the data output format of §9, and the Qt confinement rule of NFR-2.
- **AC-DOC-4** `THIRD_PARTY_LICENSES.md` exists and contains the LGPLv3 text or an exact pointer to it,
  plus one entry per runtime dependency with its licence.

---

## 12. README requirements (FR-34)

`README.md`, English, with these H2 sections in this order. `README.fr.md` mirrors them in French.

1. **What this tool does** — the pipeline in a paragraph; the nine fields; what it explicitly is not (§1.2).
2. **Legal use** — short and factual, no wall of disclaimers.
   - Intended: auditing a site you own, vendor and pre-contract due diligence, journalism, academic
     research, authorized security assessments with a written scope.
   - Not for: stalking, harassment, doxxing, unauthorized profiling, building marketing or recruiting
     lists, or any use for which the operator has no lawful basis.
   - GDPR duties the **operator** carries that no tool can discharge: lawful basis, purpose limitation,
     data minimization, answering access and erasure requests.
   - What the tool enforces mechanically: mandatory purpose, robots.txt fail-closed per URL and per redirect
     hop, a rate-limit floor nothing lowers, bounded concurrency, bounded budget and depth, an honest
     User-Agent with browser impersonation blocked, per-finding provenance and timestamps, and one-click
     erasure.
   - What it cannot enforce: whether the operator's declared purpose is lawful, and whether the site's own
     terms of service permit crawling — robots.txt is a machine-readable signal, not a contract. **The
     operator is responsible for reading the target's terms.** This replaces v1.0's per-source
     `terms_status`, which cannot exist when the target is arbitrary; say so plainly rather than implying a
     check that is not happening.
3. **Install** — Python ≥ 3.11, the install command, the lockfile, the resolved versions, and the Qt/LGPL
   note.
4. **Configure** — `osint-scrapper.toml`, why a contact email is required, precedence order.
5. **Usage** — a walkthrough of the three panes with the exact controls and their bounds.
6. **How it works** — scope, canonicalization, frontier and priority, budget and depth, discovery, the
   extraction-layer table, the self-validation rule, and **how to read `extraction_confidence` and
   `page_support`, including that support is not corroboration**.
7. **Compliance behavior** — the robots.txt decision table including the 404 divergence; per-hop
   evaluation; the interval floor; concurrency and why 2; the four abort thresholds; the User-Agent format
   and the impersonation ban.
8. **Output formats** — the five schemas with their exact column lists, the formula-injection guard, and
   the run ledger.
9. **Privacy and retention** — what is stored, what is never stored, where it lives, retention, and how to
   delete it.
10. **Development** — test, lint and type-check commands; the no-network rule; the no-real-personal-data
    fixture rule; the Qt-only-in-interfaces rule; how to run the GUI tests headless.
11. **Limitations** — parsers break when sites change their markup; JavaScript-rendered content is not seen,
    because no browser engine is used; free-text names and addresses are deliberately not extracted;
    `extraction_confidence` is a label, not a probability; `page_support` is not corroboration; the tool
    sees only what a site chooses to publish.
12. **Third-party licences** — pointer to `THIRD_PARTY_LICENSES.md` and the Qt/PySide6 LGPLv3 statement.

---

## 13. Out of scope for v0.2.0

Crawling more than one site per run · authenticated crawling of any kind · JavaScript rendering or any
headless browser · proxy rotation or bot-detection evasion · CAPTCHA handling · scheduled, recurring or
background runs · a database · a server, API or web interface · resuming an interrupted crawl · diffing two
runs of the same site · a technology signature database · OpenPGP key parsing · free-text person-name and
postal-address extraction · ODS, HTML and PDF export · RDFa extraction · face or image analysis ·
translation of source code, comments or log messages into any language other than English.
