# OSINT_scrapper

A desktop application that crawls one website you name — by domain or by page URL — extracts the OSINT
information that site publishes, and exports it, fully attributed, in the format you choose.

Version 0.2.0. Built with Python and Qt (PySide6). Windows, Linux and macOS.

> **Upgrading from 0.1.0?** This is a different product. v0.1.0 searched for a named *person* across four
> vetted sources from the command line. v0.2.0 crawls a *site* from a graphical interface. There is no
> `investigate`, `sources` or `erase` subcommand any more, and no `--given-name`. See
> [`docs/MIGRATION.md`](docs/MIGRATION.md).

## What this tool does

You give it a target — `example.com`, or `https://example.com/about` — and a purpose. It then:

1. reads the site's `robots.txt` and refuses to start if the target itself is disallowed;
2. crawls the site breadth-first from that entry point, staying inside the host you named, one polite
   request at a time, until it runs out of pages or hits the budget you set;
3. extracts published contact and identity information from each page;
4. deduplicates everything into a list of findings, each carrying every URL it was seen on and the exact
   moment it was collected;
5. writes the result to JSON, CSV, Excel, JSONL and Markdown.

```
target → scope → crawl (frontier · robots · rate limit) → extract → validate → aggregate → export
```

**Nine things are extracted**, and nothing else:

| Field | What it is |
|---|---|
| `email` | Published email addresses, flagged `role` when they are a shared mailbox (`contact@`, `info@`, `dpo@`, …) |
| `phone` | Phone numbers, validated and stored in E.164 |
| `postal_address` | Postal addresses, **only** from structured markup — never guessed from prose |
| `person_name` | Names the site publishes, as it publishes them; a job title rides along as metadata |
| `organization_name` | Whose site this is |
| `social_profile` | Full profile URLs on known platforms. Recorded, **never visited** |
| `pgp_key_url` | Where the site publishes a public key. The key itself is not fetched |
| `company_identifier` | SIREN, SIRET, EU VAT, RCS — checksum-verified |
| `technology` | The `generator` meta tag and two response headers. That is all |

**What it is not:**

- **Not a person search.** There is no name to type in. You point it at a site.
- **Not a web spider.** It never leaves the host you named. Off-site links are recorded only when they
  are social profiles, and even then they are never requested.
- **Not a technology fingerprinter.** Three sources, no signature database, no JavaScript analysis.
- **Not a vulnerability scanner.** It issues `GET` and nothing else, and never probes a path that is not
  linked, listed in a sitemap, or one of two well-known files.
- **Not a command-line tool.** The console script opens the window.

## Legal use

**Intended uses.** Auditing a site you own or operate. Vendor and pre-contract due diligence. Journalism.
Academic or statistical research. Authorized security assessments carried out under a written scope.

**Not for.** Stalking, harassment or doxxing. Profiling people who have not consented and for whom you
have no other lawful basis. Building marketing or recruiting lists. Any collection you cannot justify.

**The duties are yours, not the tool's.** Under the GDPR you are the controller. No tool can establish
your lawful basis, keep you inside your stated purpose, decide what is proportionate to collect, or answer
the access and erasure requests a data subject may send you. This tool helps you keep records; it does not
make you compliant.

**What the tool enforces mechanically:**

- A **purpose is required** before a crawl can start, and no HTTP request — not even `robots.txt` — is
  issued until it validates.
- **`robots.txt` is evaluated for every single URL, and again for every redirect hop**, fail-closed. There
  is no setting, menu item or environment variable that disables it.
- A **rate-limit floor of 0.5 seconds** that nothing can lower, and a host's own `Crawl-delay` always wins
  when it is longer.
- A **bounded crawl**: at most 2000 pages and at most 10 levels deep, whatever you type in the boxes.
- **Bounded concurrency**: at most 4 requests in flight, 2 by default.
- **Scope confinement**: the crawl cannot leave the host you named, and a redirect that tries to is
  refused rather than followed.
- An **honest `User-Agent`**. Browser impersonation is refused at the point the string is built; there is
  no way to override it.
- **Per-finding provenance**: every exported value carries its source URL, its UTC collection timestamp
  and the extraction layer that produced it.
- **Abort thresholds**: repeated `429`, a run of failures, or a high error rate stop the crawl rather than
  escalating against a host that is clearly struggling.
- **One-click erasure** of any run, from the Runs screen.

**What it cannot enforce — read this part.**

*Whether your declared purpose is lawful.* Picking `due_diligence` from a list takes one click, and so did
typing sixteen characters into a box. Neither the tool nor any tool can verify your lawful basis. What it
can do is make the assertion unavoidable, explicit and permanently recorded in every export, and that is
what it does.

*Whether the site's terms of service permit crawling.* **`robots.txt` is a machine-readable signal, not a
contract.** A site can allow a path in `robots.txt` and forbid automated collection in its terms of use,
and the two documents do not know about each other. v0.1.0 shipped a closed list of four sources whose
terms had been read and dated; v0.2.0 crawls whatever you type, so there is nothing left to pre-vet.
**Reading the target's terms of service is your job, and the tool does not pretend otherwise.**

## Install

Requires **Python 3.11 or newer**. Developed and tested on 3.12 on Windows 11.

```bash
git clone https://github.com/TonioCodeur/OSINT_Scrapper
cd OSINT_scrapper

# With uv (recommended: uv.lock is committed, so this is reproducible)
uv sync --extra dev

# Or with pip
python -m venv .venv
.venv/Scripts/activate      # Windows
source .venv/bin/activate   # Linux and macOS
pip install -e ".[dev]"
```

Then launch it:

```bash
osint-scrapper
```

`python -m osint_scrapper` does the same thing. Both open the window. The console script accepts exactly
three arguments and no others:

| Argument | Meaning |
|---|---|
| `--config PATH` | Load this configuration file instead of searching the default locations |
| `--log-level {debug,info,warning,error}` | Log verbosity. Logs go to `stderr`, never into the interface |
| `--version` | Print the version and exit |

There is no headless run mode. If you want one, open an issue rather than reaching for a flag that does
not exist.

**Direct runtime dependencies.** Exact resolved versions live in the committed `uv.lock`; licences and the
full dependency tree are in [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md).

| Package | Why |
|---|---|
| `PySide6` | The Qt binding. Chosen over PyQt6 because PySide6 offers an LGPLv3 option and PyQt6 does not — see [Third-party licences](#third-party-licences) |
| `requests` | HTTP client. Ships its own type annotations, so no stub package is installed |
| `beautifulsoup4` | HTML parsing on the standard-library `html.parser` backend: no compiled dependency, identical results on every platform |
| `phonenumbers` | Phone parsing and validation. A regex on this field would export false positives as fact |
| `email-validator` | Email validation, with DNS deliverability checks disabled |
| `openpyxl` | XLSX writing. No standard-library alternative |

Development tools: `pytest`, `pytest-qt`, `ruff`, `mypy`.

## Configure

Copy `osint-scrapper.toml.example` to `osint-scrapper.toml`, or use the **Settings** pane, which writes
the same file.

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

**A contact email is required.** Without one the **Start crawl** button stays disabled and the Settings
pane says why. It goes into the `User-Agent` of every request, so that an administrator who sees your
traffic in their logs can reach a human. That is the entire point of identifying yourself honestly.

**Search order:** `--config <path>`, then `./osint-scrapper.toml`, then
`$XDG_CONFIG_HOME/osint-scrapper/config.toml` (falling back to `~/.config/...`).

**Environment variables:** `OSINT_SCRAPPER_CONTACT_EMAIL`, `OSINT_SCRAPPER_PROJECT_URL`,
`OSINT_SCRAPPER_OUTPUT_DIR`.

**Precedence:** what you set in the interface > environment variable > configuration file > built-in
default.

**Out-of-range values are clamped, and the clamp is reported.** A configuration file asking for
`max_pages = 99999` becomes 2000 and the Settings pane tells you it happened. The bounds are not
suggestions and the file cannot smuggle a larger value past the interface.

Window size, splitter positions and table column widths are stored separately by Qt, per machine.
Everything that affects a crawl or an export lives in the TOML file and nowhere else.

## Usage

The window has three panes — **Crawl**, **Runs** and **Settings** — plus a menu bar (*File*, *Run*,
*Help*) and a status bar. Switching panes never interrupts a running crawl.

### Starting a crawl

In the **Crawl** pane:

| Control | Default | Notes |
|---|---|---|
| **Target** | — | `example.com` or `https://example.com/about`. A bare domain becomes `https://…`; the tool never silently falls back to `http://`, so type the full `http://` URL if you need it. A hint line shows the resolved URL and the scope host it derived |
| **Purpose** | your last used | Required. Six choices; see below |
| **Purpose note** | your last used | Optional — **required, and at least 16 characters, when Purpose is `other`** |
| **Max pages** | 200 | 1 – 2000 |
| **Max depth** | 3 | 0 – 10. The target page is depth 0 |
| **Request interval (s)** | 1.0 | 0.5 – 60.0. The minimum *is* the hard floor; the control cannot go below it |
| **Concurrent requests** | 2 | 1 – 4 |
| **Include subdomains** | on | See [Scope](#scope-what-gets-crawled-and-what-does-not) |
| **Follow sitemap** | on | |
| **Phone region** | `FR` | ISO 3166-1 alpha-2. The region phone numbers are parsed against |

The four limit controls sit in a **Crawl limits** group that is expanded by default. They are compliance
controls, not advanced options, and hiding them would be dishonest about what the application is about to
do on your behalf.

**Start crawl** stays disabled until the target and the purpose are both valid; its tooltip says which one
is missing.

### The purpose

Pick one:

| Value | Meaning |
|---|---|
| `security_assessment` | Authorized security assessment with a written scope |
| `due_diligence` | Vendor, supplier or pre-contract due diligence |
| `journalism` | Journalistic research |
| `self_audit` | Auditing a site you own or operate |
| `academic_research` | Academic or statistical research |
| `other` | Anything else — a note of at least 16 characters is required |

Both the category and the note are written into every export and into the run ledger. The purpose stays
visible next to the Start button and is never hidden behind a dialog you dismiss once and forget.

*Why a list and not a text box?* v0.1.0 required 16 characters of free text before every run. In a
graphical tool that is friction you meet several times an hour, and friction of that kind does not produce
thoughtful answers — it produces `aaaaaaaaaaaaaaaa`, which is worse than nothing because it manufactures
evidence of deliberation that never happened. A short controlled vocabulary keeps both things that
mattered (you must state a basis; it is permanently recorded) and produces records you can actually
compare across runs. The 16-character rule survives exactly where it earns its keep: on `other`.

### While it runs

**Start** becomes **Stop**. There is deliberately no Pause — a paused crawl holds connections open while
doing no work, which is worse manners than stopping and starting again.

Four things are live:

- **Progress** — a bar against your page budget, plus the authoritative label:
  `fetched N/BUDGET · queued Q · depth D · skipped S · errors E · elapsed mm:ss`. The bar is an upper
  bound, not an estimate: a crawl that runs out of pages finishes early, and that is a normal, good
  outcome.
- **Findings** — a sortable table, `Field · Value · Extraction · Pages · First seen`, filling in as the
  crawl goes. Rows update in place as the page count for a value grows. `Ctrl+C` copies the selection.
- **Page log** — `# · Depth · Status · URL · Detail`, filterable by status. The status codes are the exact
  machine values that appear in the exports, so what you read on screen is what you can grep for later.
- **A compliance banner** that cannot be dismissed, showing the User-Agent in use, that `robots.txt` is
  being honoured, the effective interval and its floor, and the crawl scope. It is on screen the whole
  time traffic is going out.

**Stop** is cooperative: in-flight requests finish or time out, nothing is killed mid-write, and the
partial result is a real report you can export. It is recorded as `stopped_by_operator`.

### Errors

Three tiers, deliberately:

- **A page failed** → a row in the page log with its status code. No dialog, no sound. Partial failure is
  normal in scraping; treating it as an event would just teach you to click *OK* reflexively.
- **The run cannot continue** → an inline banner at the top of the pane with the reason code, the URL and
  a plain sentence. Used for a `robots.txt` refusal on the target, an unreachable target, bad
  configuration, and each abort threshold. It never covers the log — that is the moment you most need to
  read it.
- **A bug** → a modal with the exception type and a **Copy details** button. It is the only modal in the
  product you did not ask for, and it exists so that defects are loud. Whatever was collected is still
  exportable.

### Exporting

**Run → Export…**, or the button on the completion strip, or **Re-export…** from the Runs pane.

Tick the formats you want. **JSON is always written and cannot be unticked** — it is the canonical record
and everything else is derived from it. Choose a destination if you want a copy somewhere else; the run
directory always keeps its own.

Re-exporting a finished run issues **zero** HTTP requests. Deciding you also wanted Excel does not mean
crawling the site again.

### Managing what you have collected

The **Runs** pane lists every run: date, target host, purpose, pages, findings, size, and days of
retention remaining. Runs past their declared retention are highlighted.

- **Open folder** — the run directory in your file manager.
- **Re-export…** — more formats, no new requests.
- **Delete** — removes the run directory and its ledger line, after a confirmation that names the exact
  directories and how many findings will be destroyed.
- **Delete expired** — the same, for everything past retention.

Nothing is ever deleted automatically. The tool records a retention period and shows you when it lapses;
the decision stays yours.

## How it works

### Scope: what gets crawled, and what does not

The **scope host** is your target's host with a leading `www.` removed. A URL is in scope when its host is
that host, its port matches, and:

- **Include subdomains on** (the default) — the scope host or anything ending in `.` + the scope host. So
  `example.com` reaches `blog.example.com`.
- **Include subdomains off** — the scope host or its `www.` twin, and nothing else.

Three consequences worth knowing before you point it at something:

- **Scope goes down, never up.** Target `docs.example.com` and you will not reach `example.com`. If you
  want the whole domain, type the domain.
- **No public suffix list is consulted.** Confinement is defined by the host you actually typed, which is
  narrower than "the same registrable domain" and therefore always safe: `foo.co.uk` can never reach
  `bar.co.uk`, and no list has to be downloaded to make that true.
- **Off-site links are never fetched.** An external `href` is offered to the social-profile extractor; if
  it is a profile on a known platform it becomes a finding, otherwise it is dropped. You will not get a
  dump of every outbound link on the site, and the tool will not quietly wander onto a third party's
  servers.

A redirect that tries to leave the scope is recorded as `off_scope_redirect` and **not followed**. That is
the rule that stops one misconfigured redirect from turning a site crawl into an internet crawl.

### The crawl

**Breadth-first**, so shallow pages come first — which is where contact and legal information lives. One
modification: URLs whose path looks like a high-value page (`contact`, `mentions-legales`, `legal`,
`impressum`, `about`, `a-propos`, `team`, `equipe`, `privacy`, `security`, `presse`, and friends) jump to
the front of the queue at their own depth. This never adds a request — it only reorders a queue that
already contained the URL — so a crawl that runs out of budget still comes back with the pages that
matter.

**Every URL is canonicalized** before it can enter the queue, so the same page is never fetched twice:
scheme and host lower-cased, host punycoded, default ports dropped, `.` and `..` resolved, duplicate
slashes collapsed, **fragments always dropped**, tracking and session parameters (`utm_*`, `gclid`,
`fbclid`, `phpsessid`, …) removed, and the remaining query parameters sorted so `?a=1&b=2` and `?b=2&a=1`
are one URL and not two.

Two deliberate non-normalizations: **path case is preserved** (paths are case-sensitive on most servers)
and **a trailing slash is significant** (`/a` and `/a/` are different URLs). In practice servers redirect
one to the other and the duplicate collapses on its own, because it is the *final* URL after redirects
that enters the visited set — the tool does not have to guess.

A **spider-trap guard** rejects URLs with more than 20 path segments, a segment repeated more than four
times, more than 10 query parameters, or a length over 2048 characters — the shapes that infinite
calendars and faceted-search pages produce.

**Discovery** beyond page links, done once at the start:

- `Sitemap:` lines in `robots.txt`, which is being fetched anyway.
- `/sitemap.xml`, if `robots.txt` declared none and *Follow sitemap* is on. At most 5 sitemap documents,
  at most 500 URLs from each, index files followed one level only, documents over 10 MiB abandoned.
- `/.well-known/security.txt` (RFC 9116). A `mailto:` `Contact:` becomes an email, a `tel:` `Contact:`
  becomes a phone, `Encryption:` becomes a PGP key URL. Those URLs are contacts, not crawl targets, and
  are not queued.

**What is fetched.** HTML and XHTML, plus plain text for `security.txt` and XML for sitemaps. URLs ending
in a known binary or asset extension (`.pdf`, `.jpg`, `.zip`, `.css`, `.js`, `.woff2`, and about forty
others) are **never requested at all** — but they still appear in the page log as `skipped_extension`, so
you can see that `/rapport-annuel.pdf` exists without the tool having downloaded it. Anything else whose
`Content-Type` turns out not to be parseable has its body discarded unread. Responses over 5 MiB are
abandoned.

Every page's fate is one of seventeen status codes, and all of them appear in the log and in the exports:
`ok`, `no_findings`, `skipped_robots`, `skipped_extension`, `skipped_content_type`, `skipped_off_scope`,
`skipped_budget`, `skipped_depth`, `url_rejected_shape`, `credentials_in_url`, `off_scope_redirect`,
`too_many_redirects`, `too_large`, `rate_limited`, `http_error`, `transport_error`, `parse_error`.

**Partial failure is normal.** One page failing degrades that page only. The crawl continues and the log
says exactly what happened, rather than quietly returning less.

### Extraction layers

Five layers run over each page. Each finding records the best layer that produced it.

| Layer | Reads | Confidence |
|---|---|---|
| `well_known` | `/.well-known/security.txt` fields (RFC 9116) | 0.95 |
| `structured_data` | schema.org JSON-LD and microdata: `Organization`, `Person`, `PostalAddress`, `ContactPoint`, `sameAs` | 0.90 |
| `semantic_html` | `mailto:` / `tel:` links, `<address>`, microformats and legacy vCard classes, `<meta name="author">`, `<meta name="generator">`, `<link rel="author">`, `<link rel="me">`, `<link rel="pgpkey">`, and two response headers | 0.75 |
| `text_heuristic` | Email patterns, `phonenumbers` matches, and company identifiers over the visible text | 0.50 |
| `text_heuristic_deobfuscated` | Addresses the site published as `name [at] domain [dot] com`, `(at)`, ` AT `, `＠`, `﹫` | 0.40 |

Visible text is the document after `<script>`, `<style>`, `<noscript>`, `<template>` and comments are
removed. De-obfuscation reads text the site chose to display; it defeats naive address harvesters, not
access control. Only the listed separators are rewritten, and only when the result then passes email
validation — it never guesses a domain.

### One rule about free text

> **A value may be extracted from prose only if something independent can confirm it is well-formed.**

Three fields qualify: **email** (it must parse as a real address), **phone** (libphonenumber must call it
valid), and **company identifier** (SIREN and SIRET must pass their checksum, VAT numbers their country's
format). A candidate that fails is discarded, not exported with a lower score.

The other six — postal addresses, person names, organization names, social profiles, PGP key URLs and
technologies — come **only** from the top three layers, never from prose.

This is not caution for its own sake. A crawl of 200 pages of text contains hundreds of capitalized word
pairs and dozens of number-and-street patterns. Without a checkable invariant, a text-layer extractor for
those fields does not find facts — it manufactures them, at volume, and attaches a confidence number to
each one. That is the single worst thing this product could do, so it does not do it.

### Reading `extraction_confidence` and `page_support`

Every finding carries **two numbers, and they are not combined**:

- **`extraction_confidence`** — one of `0.95`, `0.90`, `0.75`, `0.50`, `0.40`. It answers *how was this
  obtained*, nothing else. It is a label, not a probability, and no arithmetic is ever done on it. A value
  found in JSON-LD scores 0.90 whether it appeared on one page or four hundred, because the extraction was
  equally sound either way.
- **`page_support`** — a whole number: on how many distinct pages of this site the value appeared. It is
  left as an integer precisely so that nobody mistakes it for a probability.

**High support means site-wide** — a footer, a contact block — and identifies the *organization*. **Support
of 1 means page-local** — a specific person, a specific department. Neither is better; they answer
different questions.

**Support is not corroboration.** v0.1.0 raised a score when several *independent sources* agreed, which
is a meaningful thing for independent sources to do. Here there is one source. A phone number on forty
pages of one website is not forty confirmations — it is **one publisher speaking once, loudly**. The tool
reports how loudly and leaves the inference to you, rather than laundering repetition into a number that
looks like certainty.

There is no blended score anywhere in any export, and no `identity_unconfirmed` flag: with no name being
matched, there is no homonym risk to warn you about.

Values are deduplicated on a normalized key, so the same email seen on forty pages is one finding with
forty pages of support — never forty rows. Provenance is capped at 10 entries per finding to keep reports
readable, while the page and occurrence counts always tell you the true totals.

## Compliance behavior

### robots.txt

Fetched with the tool's own User-Agent and timeout, cached per `(scheme, host, port)` for at most 24
hours, matched on the product token `OSINT-Scrapper`.

**It is evaluated for every URL, not once per host** — path-level rules make a host-level decision
meaningless. And it is evaluated **again on every redirect hop**, before the hop is followed, because
otherwise a `302` from an allowed path into a disallowed one would be a way around the check. Five hops
maximum.

| Result of fetching `/robots.txt` | Decision |
|---|---|
| 2xx, body parseable | Follow the parsed rules |
| 3xx, up to 5 hops, then 2xx | Follow the final body's rules |
| 401 or 403 | **Deny** — the host is refusing us |
| **404**, and other 4xx | **Allow** |
| 5xx | **Deny** |
| Timeout, DNS, TLS, connection reset | **Deny** |
| Body larger than 512 KiB | **Deny** |
| Body not decodable, or unparseable | **Deny** |
| More than 5 redirects, or a loop | **Deny** |

**The 404 divergence, stated openly.** A 404 is treated as *allow*. It is a definitive answer from the
host — "there is no robots.txt" — not an ambiguity; it is what RFC 9309 §2.3.1.3 prescribes; and it is
what Python's own `RobotFileParser` implements. Treating it as a denial would make the tool unable to read
the legal-notice page of most small sites. Everything genuinely *ambiguous* — unreachable, malformed,
oversized, refused — denies.

**If `robots.txt` disallows your target itself, the run does not start.** No run directory, no ledger
entry, no requests. There is no override control anywhere in the product, and adding one would be a
defect.

### Rate limiting

The minimum interval between two request *starts* to the host is
`max(your setting, the host's Crawl-delay, 0.5 s)`. It is a floor. Nothing lowers it — not the
configuration file, not the interface, not an environment variable.

**Concurrency, and why the number is 2.** Because the limiter gates request *starts*, running more workers
**cannot** increase the load on the host: at a 1-second interval the tool makes one request per second no
matter how many workers exist. Concurrency only hides latency. Against a site answering in 2 seconds, one
worker wastes half the permitted budget waiting; two workers use the interval you actually configured. Two
is enough to saturate any interval against any response time under twice that interval, which covers
essentially every real site. More workers buy nothing but open connections, so the maximum is 4. Set it to
1 if you want the simplest possible traffic shape.

### Backing off, and knowing when to stop

**429** — `Retry-After` is honoured up to 120 seconds; without it, backoff is 2 s, 4 s, 8 s with jitter.
**Three consecutive 429s abort the crawl**, and a `Retry-After` above 120 seconds aborts immediately.
Repeated 429 is the host telling you to stop; continuing is how integrations get banned.

**5xx** — up to 3 retries with exponential backoff and jitter, capped at 30 seconds. After that the page
is recorded `http_error` and the crawl continues. Other 4xx are recorded and never retried.

Four thresholds abort a crawl, and each still produces a complete, exportable report of everything
collected up to that point:

| Trigger | Outcome |
|---|---|
| 3 consecutive `429`, or a `Retry-After` over 120 s | `aborted_rate_limited` |
| 10 consecutive failures of any kind | `aborted_host_unhealthy` |
| Over 50 % failures after at least 20 fetches | `aborted_error_rate` |
| You pressed Stop | `stopped_by_operator` |

### User-Agent

```
OSINT-Scrapper/0.2.0 (+https://github.com/TonioCodeur/OSINT_Scrapper; contact: you@example.org)
```

There is no control, configuration key, environment variable or command-line argument that sets an
arbitrary User-Agent. The one function that builds it refuses any string containing `Mozilla`,
`AppleWebKit`, `Chrome`, `Chromium`, `Safari`, `Firefox`, `Gecko` or `Edg`, case-insensitively. This tool
identifies itself; it does not defeat bot detection.

The tool issues **`GET` and nothing else**, ever.

## Output formats

Everything a run writes lives under `<output-dir>/<run_id>/`, `./runs/<run_id>/` by default. Timestamps
are RFC 3339 UTC with a `Z` suffix.

**Ordering is deterministic** and computed from sort keys, never from the order pages happened to come
back — findings by field, then confidence, then support, then value; pages by depth then URL. Two runs
over the same site produce the same file layout, and a crawl with 2 workers produces the same ordering as
one with 1.

### `report.json` — canonical

A superset of every other format. UTF-8, `indent=2`, keys in a fixed order rather than sorted, trailing
newline. No key outside this schema is ever written.

```json
{
  "schema_version": "2.0",
  "run":        { "run_id": "…", "started_at": "…", "finished_at": "…",
                  "outcome": "completed", "outcome_detail": null,
                  "purpose_category": "due_diligence", "purpose_note": "",
                  "retention_days": 30,
                  "tool": { "name": "…", "version": "…", "user_agent": "…" } },
  "target":     { "entered_value": "example.com", "target_url": "https://example.com/",
                  "scope_host": "example.com", "include_subdomains": true },
  "settings":   { "max_pages": 200, "max_depth": 3, "request_interval_seconds": 1.0,
                  "concurrent_requests": 2, "follow_sitemap": true, "phone_region": "FR" },
  "statistics": { "pages_fetched": 147, "requests_made": 152, "pages_skipped": 38,
                  "pages_failed": 5, "findings_count": 63 },
  "findings":   [ { "field": "email", "value": "…",
                    "extraction_confidence": 0.9, "page_support": 41,
                    "occurrence_count": 78, "first_seen_url": "…",
                    "metadata": { "email_kind": "role" },
                    "provenance": [ { "source_url": "…", "collected_at": "…",
                                      "extraction_layer": "…", "raw_value": "…" } ] } ],
  "pages":      [ { "url": "…", "depth": 0, "status": "ok", "detail": null,
                    "http_status": 200, "content_type": "text/html",
                    "findings_count": 6 } ]
}
```

### `report.csv` and `report_pages.csv`

One row **per provenance entry**, so every row is independently attributable. Written with `utf-8-sig`
(the BOM is what makes Excel read accented values correctly), CRLF line endings and minimal quoting.

`report.csv`:

```
run_id, purpose_category, purpose_note, retention_days,
target_entered, target_url, scope_host,
field, value, email_kind, extraction_confidence, page_support, occurrence_count, first_seen_url,
source_url, extraction_layer, raw_value, collected_at,
tool_name, tool_version
```

`report_pages.csv`:

```
run_id, url, depth, status, detail, http_status, content_type, findings_count
```

`email_kind` is empty for every field but `email`. The other per-field metadata (`number_type`, `platform`,
`scheme`, `role`) is in the JSON and JSONL exports; giving each a column would produce a wide sheet that is
mostly empty.

### `report.xlsx`

Four sheets, in this order:

1. **`Run`** — key/value: identifiers, timings, outcome, purpose, tool, target, settings, statistics.
2. **`Findings`** — header identical, cell for cell, to `report.csv`.
3. **`Pages`** — header identical to `report_pages.csv`.
4. **`Compliance`** — the User-Agent, that robots.txt was honoured, the robots URL, the effective interval
   and its floor, concurrency, how many pages robots skipped, retention and purpose. This sheet exists so
   that the compliance posture of a run is a first-class artifact an auditor can read without parsing JSON.

Headers are bold; confidences are floats and counts are integers.

### `report.jsonl`

One JSON object per line, UTF-8, LF endings, no BOM. Each line is one finding × provenance entry with the
same fields as a CSV row, plus the full `metadata` object — `email_kind` is not repeated at the top level,
because `metadata` already carries it. Numbers stay numbers, values containing
newlines need no quoting, and the file streams and appends — which is why it exists alongside CSV rather
than instead of it.

### `report.md`

The human deliverable: a summary table, findings grouped by field, the page log, and a compliance section.
Values have `|`, backticks and backslashes escaped, `<` and `>` entity-escaped, `[` and `]` escaped so no
scraped value can render as a link, and newlines flattened. **No raw HTML is ever emitted**, so a Markdown
renderer cannot be made to execute anything a crawled site published.

### Formula-injection guard

Any CSV or XLSX cell whose first character is `=`, `+`, `-`, `@`, a tab or a carriage return is written
with a leading apostrophe. These files carry text scraped from hundreds of third-party pages straight into
a spreadsheet, so this is mandatory rather than optional. It does not apply to JSONL or Markdown, which
are not spreadsheets and where mangling a value would corrupt the format.

## Privacy and retention

**What is stored.** Only the nine fields, their normalized values, and per-finding provenance: source URL,
UTC timestamp, extraction layer, and the short raw string that produced the value (capped at 200
characters). Plus the page log, the run settings and your declared purpose.

**What is never stored.** Page HTML. Response bodies. Free page text. None of it touches disk, at any
point, in any format. A test enforces this.

**Where it lives.** `./runs/<run_id>/` by default, plus an append-only ledger at `runs/index.jsonl` with
one line per run — target host, purpose, counts, retention. `runs/` is git-ignored and must stay that way:
it holds collected personal data.

The ledger records the target host in plaintext. v0.1.0 hashed its subject key, because the index of *who
has been investigated* is itself personal data. Here the target is a hostname, the report sitting in the
very same directory contains it in full, and the Runs pane has to be able to show you what you crawled
without opening every file on disk — so hashing it would buy nothing and cost the feature. Where a
hostname *is* personal data, the remedy is the one the GDPR actually asks for: delete the run, which is one
click away in that same pane.

**Retention is declared, not enforced.** Every export records the retention period you configured (30 days
by default). The tool never deletes anything by itself. The Runs pane shows what has lapsed and gives you
**Delete expired**; you decide.

**Erasure.** Deleting a run removes its directory and rewrites the ledger without its lines. If someone
sends you an erasure request, that is the mechanism — and because every finding carries its source URL and
timestamp, you can also tell them exactly what you hold and where it came from.

## Development

```bash
uv sync --extra dev

pytest                  # the full suite
ruff check .            # lint
ruff check . --fix      # the auto-fixable subset
mypy src                # strict type checking
```

Headless GUI tests need Qt's offscreen platform plugin:

```bash
# Windows (PowerShell)
$env:QT_QPA_PLATFORM = "offscreen"; pytest

# Linux and macOS
QT_QPA_PLATFORM=offscreen pytest
```

**The test suite makes zero network calls.** An autouse fixture patches `socket.socket` and
`socket.create_connection` to raise, so an accidental request fails loudly instead of silently succeeding.

**Fixture policy.** Parsers and the whole crawl are tested against committed fixtures — chiefly
`tests/fixtures/site/`, a small invented website exercising robots allow and deny, a redirect chain, an
off-scope redirect, a sitemap, a `security.txt`, a spider trap and an obfuscated email. **No fixture may
contain a real person's data.** Invented values on `example.com` / `example.org` only.

**Architecture is enforced by tests, not by convention.** `tests/test_architecture_boundaries.py` parses
every module with `ast` and fails if `domain/` imports anything outside the standard library, if
`application/` imports anything outside the standard library and the inner layers, or if **`PySide6`
appears anywhere outside `src/osint_scrapper/interfaces/`**. That last rule is what keeps the entire
product testable without ever constructing a `QApplication`, and it is why the crawl can be driven
end-to-end in a test with no window on screen.

**The GUI thread never does I/O.** Network requests, parsing and export all run on a worker thread and
report back through signals. Cancellation is cooperative — a token checked between fetches — and
`QThread.terminate()` is forbidden, because it can leave a half-written file and would break the promise
that Stop always yields an exportable report.

`tests/test_end_to_end.py` runs the whole chain over the committed fixture site — real crawl loop, real
canonicalization, real robots policy, real extractors, real writers — faking only the page fetcher, the
clock and the sleeper, and asserts on all six emitted files. It is the only test that catches drift
between what an extractor emits and what the aggregator expects. **Do not replace its collaborators with
stubs.**

## Limitations

- **Parsers break when sites change their markup.** That is inherent to scraping. This tool fails loudly
  when it happens — naming the selector and the URL, and recording `parse_error` for that page — instead
  of returning a plausible-looking empty result.
- **JavaScript-rendered content is invisible.** There is no browser engine here. A site that builds its
  contact page in the client will look empty, and the tool cannot tell you that is what happened. This is
  a deliberate trade: a headless browser would multiply the load placed on the target and the attack
  surface of this application.
- **Free-text names and postal addresses are not extracted, deliberately.** See
  [One rule about free text](#one-rule-about-free-text). Missing a name is recoverable; exporting a wrong
  address as fact is not.
- **`extraction_confidence` is a label, not a probability.** A value at 0.90 is not "90 % likely to be
  correct". It means schema.org markup published it.
- **`page_support` is not corroboration.** One site repeating itself is one publisher speaking once,
  loudly.
- **`robots.txt` is not the terms of service.** Reading the target's terms is your job.
- **The tool sees only what a site chooses to publish.** It bypasses no authentication, no paywall and no
  bot detection. An empty result means "nothing public was found here", not "this organization has no
  online presence".
- **A crawl is a snapshot.** Nothing is re-fetched within a run, there is no resume after an interruption,
  and there is no diff between two runs of the same site.
- **One site per run.** Crawling several targets means several runs.
- **Out of scope for this version:** authenticated crawling, proxy rotation or bot-detection evasion,
  CAPTCHA handling, scheduled or background runs, a database, a server or web interface, a technology
  signature database, OpenPGP key parsing, and ODS, HTML or PDF export.

## Third-party licences

Full detail, and the obligations that come with redistribution, are in
[`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md). In short:

**This application's own source code is MIT.** It uses **Qt** through **PySide6**, under the **GNU Lesser
General Public License version 3**. PySide6 was chosen over PyQt6 for exactly this reason: PySide6 offers
an LGPLv3 option, and Riverbank Computing state that *"Unlike Qt, PyQt is not available under the LGPL"* —
linking an MIT application against PyQt6 under the GPLv3 would relicense the distributed work.

If you only run this tool, you have nothing to do. **If you redistribute it**, the LGPLv3 asks you to keep
Qt dynamically linked and replaceable, to pass on the licence text, and to tell your users that Qt is used
— all of which are spelled out, concretely, in that file. Freezing the application into a single-file
binary is a licence-relevant change and is not something to do casually.
