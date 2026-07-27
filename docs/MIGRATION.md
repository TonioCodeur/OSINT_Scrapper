# Migration — v0.1.0 (person-search CLI) → v0.2.0 (site-crawler Qt application)

**Owner:** @PO · **Executors:** @DB, @DF · **Reviewer:** @LT
**Companion to:** `docs/SPEC.md` v2.0, which is authoritative. Where this file and the specification
disagree, the specification wins.

This is the demolition plan. It says, per module, whether it is **kept**, **reworked**, **rewritten** or
**deleted**, and why. It is a work order, not a design document.

---

## 1. The one-paragraph summary

v0.1.0 answered "who is this named person, according to four vetted sources". v0.2.0 answers "what does
this website publish". The subject is gone, so everything that existed to describe, select, corroborate or
disambiguate a *person* is gone with it: `Subject`, `PersonProfile`, `SourceDescriptor`, the registry, the
four adapters, `MatchBasis`, `ValueType`, `Conflict`, `identity_unconfirmed` and the corroboration formula.
What survives is the part that was never about people: **the HTTP compliance stack, the extraction
pipeline, the writers' mechanics, and the run/erase lifecycle.** That is roughly 40 % of the code and it is
the 40 % that was hardest to get right.

Rough shape of the work: about 5 400 lines today; ~1 300 kept verbatim, ~1 600 reworked, ~1 700 deleted
outright, plus a new interfaces layer.

---

## 2. Order of work

Do it in this order. Each step leaves the suite green.

1. **Domain first.** New `domain/url.py`, `target.py`, `crawl.py`; rewrite `attributes.py`, `report.py`,
   reduce `confidence.py`; delete `subject.py`, `profile.py`, `source.py`. Nothing else compiles yet — that
   is expected and is why this step is first.
2. **Application.** New `frontier.py`, `crawl.py`, `aggregate.py`, `export.py`, `runs.py`; rewrite
   `ports.py` and `validation.py`; delete `investigate.py`, `merge.py`, `erase.py`.
3. **Infrastructure, compliance half.** Rework `requests_fetcher.py` (`FetchPolicy`, headers, body cap,
   scope-aware redirects) and `rate_limit.py` (hard floor). `robots.py`, `user_agent.py`, `clock.py`,
   `ids.py` are untouched.
4. **Infrastructure, extraction half.** New `discovery/`; remap the extractors to the new `FieldName` set;
   new validators; delete `sources/` entirely.
5. **Infrastructure, writers.** Rewrite `rows.py` and `json_writer.py`; add `jsonl_writer.py` and
   `markdown_writer.py`; rework `ledger`.
6. **End-to-end test and the mini-site fixture.** Build `tests/fixtures/site/` and get
   `test_end_to_end.py` green **before** any Qt code exists. This is the checkpoint that proves the product
   works headless, and it is the thing that makes the GUI a thin shell rather than a place for logic to
   hide.
7. **Interfaces.** `app.py`, then the panes. @DF owns this step; @DB is done after step 6 except for
   defects.

Steps 1–6 are @DB. Step 7 is @DF. Step 6 gates step 7: **no Qt code is written until the crawl passes
end to end without it.**

---

## 3. `domain/`

| Module | Verdict | Notes |
|---|---|---|
| `subject.py` | **DELETE** | `Subject`, `SubjectInput`, `MatchBasis`, `ValueType`, `derive_subject_key`, `SUBJECT_KEY_LENGTH` all go. There is no subject. **Salvage `fold()`** — the NFKD/lower/collapse folder — into `attributes.py` or a small `domain/text.py`; the deduplication keys of SPEC §8.5 still need it. |
| `profile.py` | **DELETE** | `PersonProfile` is keyed by `subject_key`. Replaced by `SiteReport.findings`. |
| `source.py` | **DELETE** | `SourceDescriptor`, `SourceKind`, `TermsStatus`, `COLLECTABLE_TERMS_STATUSES`. See §8 for why the terms-as-data mechanism does not carry over and what replaces it. |
| `attributes.py` | **REWRITE** | Keep the *shape*: a frozen value + provenance tuple with a non-empty invariant. Change: `Attribute` → `Finding` with `extraction_confidence` / `page_support` / `occurrence_count` / `first_seen_url`; drop `value_type`, `confidence`, `disputed`, `identity_unconfirmed`; drop `match_basis` from `Provenance` and `RawField`; add a 200-char cap on `raw_value` and a 10-entry cap on provenance; replace `FieldName` and repurpose the top `ExtractionLayer` member (`API` → `WELL_KNOWN`). Delete `Conflict`. |
| `confidence.py` | **REDUCE** | Keep `LAYER_BASE_CONFIDENCE` with its five values unchanged — they measure extraction mechanism, not product. Delete `CORROBORATION_BONUS`, `MAXIMUM_CONFIDENCE`, `UNCONFIRMED_IDENTITY_CEILING`, `ConfidenceAssessment` and `assess_confidence`. The replacement is a `max()` over a table, which does not need a module of its own but keeps one for the table's sake. |
| `report.py` | **REWRITE** | `SourceStatus` → `PageStatus` (17 members, SPEC §5.9); `SourceOutcome` → `PageOutcome`; `InvestigationReport` → `SiteReport`. `SUCCESSFUL_STATUSES` and `COMPLIANCE_REFUSAL_STATUSES` become `CrawlOutcome` groupings. |
| `errors.py` | **KEEP, adjust** | Drop `InvalidSubjectError`. Add `InvalidTargetError`, `InvalidCrawlSettingsError`. `MissingPurposeError`, `InvalidPurposeError`, `ValidationRejectedError`, `MissingProvenanceError` all survive unchanged. Drop `ForbiddenSourceError` with the registry. |
| `url.py` | **NEW** | SPEC §5.2 and §5.3, pure, `urllib.parse` only. This is the single densest new module and it deserves the largest table-driven test in the suite. |
| `target.py` | **NEW** | `CrawlTarget`, `CrawlSettings` (bounds enforced in `__post_init__`), `Purpose`, `PurposeCategory`. |
| `crawl.py` | **NEW** | `PageStatus`, `PageOutcome`, `CrawlOutcome`. |

---

## 4. `application/`

| Module | Verdict | Notes |
|---|---|---|
| `errors.py` | **KEEP VERBATIM** | `TransportError`, `HttpStatusError`, `RateLimitedError`, `RobotsDeniedError`, `PageBudgetExhaustedError`, `SelectorNotFoundError`, `ConfigurationError`. Zero person coupling. `SelectorNotFoundError(source_id, selector, url)` loses `source_id` and gains nothing — its message must still name the selector and the URL. |
| `ports.py` | **REWRITE** | Delete `SourceAdapter`, `SourceRegistry`, `PlannedRequest`, `InvestigationRequest`, `ValidatedValue.value_type`. Keep `Clock`, `MonotonicClock`, `Sleeper`, `IdGenerator`, `RobotsPolicy`, `RateLimiter`, `PageFetcher`, `ResultWriter`, `RunLedger`, `DirectoryRemover`, `FieldValidator` with their signatures adjusted to the new types. Add `CrawlObserver`, `CancellationToken`, `LinkExtractor`, `SitemapReader`. `FetchedPage` gains `headers`. `LedgerEntry.subject_key` → `target_host` plus the new counters. |
| `validation.py` | **REWORK** | `ALLOWED_LAYERS` stops being a one-field special case for `postal_address` and becomes the mechanical encoding of SPEC FR-23: six fields restricted to layers 1–3, three fields open to all five. `ValidationPolicy.validate` loses its `subject` parameter and gains `phone_region`. **Four of the six existing validators never read `subject` anyway** — this is a signature sweep, not a redesign. |
| `merge.py` | **REWRITE as `aggregate.py`** | Keep the accumulator idea and the dedup-key discipline. Delete `SINGLE_VALUED_FIELDS`, `_resolve_conflicts`, `_mark_disputed` and everything downstream of them; delete `CollectedField.source_id`. `_score` becomes `max(layer)` plus two counters (SPEC §8.6). This is the module where the honest-numbers decision lands, so it is the module @LT reads first. |
| `investigate.py` | **DELETE, replaced by `crawl.py`** | The orchestration *shape* — a per-unit failure boundary, a budget, export then ledger — is exactly right and should be copied. The *loop* is wrong: it iterates over sources, and the new one iterates over a frontier with a visited set, a depth, a cancellation check and an observer. Copy the shape, write the loop. `validate_purpose()` and `MINIMUM_PURPOSE_LENGTH` move to `domain/target.py` as `Purpose.__post_init__` and now apply only to the `other` category. `DryRunPlan` is deleted: a GUI crawl shows its plan live, which is strictly better than a dry-run flag. |
| `erase.py` | **REWRITE as `runs.py`** | The mechanism — find ledger entries, remove directories, rewrite the ledger — survives intact. The lookup path changes from `given_name + family_name → subject_key` to `run_id` or `target_host`. Add `ListRunsUseCase` for the Runs pane. |
| `frontier.py` | **NEW** | `Frontier` (FIFO `deque` with the §5.4 priority push) and `VisitedSet`. Pure, stdlib, and guarded for the concurrent case of §6.4. |
| `export.py` | **NEW** | Export becomes a separate operator action (re-export without re-crawling), so it becomes its own use case rather than a tail of the crawl. |

---

## 5. `infrastructure/http/` — keep almost everything

This is the layer the refactor should touch least. It was written to be forgettable-proof and it is.

| Module | Verdict | Notes |
|---|---|---|
| `user_agent.py` | **KEEP VERBATIM** | `BROWSER_TOKENS`, `assert_honest`, `build_user_agent`, `DishonestUserAgentError`. Not one character changes. |
| `robots.py` | **KEEP VERBATIM** | `RobotsTxtPolicy`, the fail-closed table, the per-host cache, `RobotsReason`, the 512 KiB cap, the 5-redirect limit. It was already crawler infrastructure; the crawler just arrived. One addition, purely additive: expose the `Sitemap:` directives already present in the parsed body so `discovery/` can read them without a second fetch (SPEC §5.6). |
| `rate_limit.py` | **KEEP, one addition** | `effective_interval(*candidates)` already takes a floor over candidates. Add `HARD_FLOOR = 0.5` as a permanent candidate so no configuration path can go below it (SPEC FR-11). `PerHostRateLimiter` must be safe to share across the concurrent workers of §6.4 — verify, and test it. |
| `requests_fetcher.py` | **REWORK, do not rewrite** | Four changes: (1) `SourceDescriptor` → `FetchPolicy`; (2) expose `headers` on `FetchedPage`; (3) stream the body and abandon past 5 MiB; (4) the manual per-hop redirect loop additionally checks scope and emits `off_scope_redirect`. **The manual redirect handling is load-bearing and must not be replaced by `requests`' own redirect following** — it is what makes robots evaluation per-hop possible, and it is the single most valuable thing in this file. |

---

## 6. `infrastructure/extraction/`

The pipeline structure survives. The *vocabulary* it maps onto does not.

| Module | Verdict | Notes |
|---|---|---|
| `text.py` | **KEEP VERBATIM** | `parse_html`, `visible_text`, `collapse`, `attribute_value`, `css_classes`. |
| `pipeline.py` | **KEEP, signature sweep** | `PageContent` is already generic. `PageExtractor.extract(content, subject, match_basis)` → `extract(content, context)` where `context` carries `phone_region`. Four of the five extractors already start with `del subject`; only `TextHeuristicExtractor` reads it, and only for `.region`. |
| `jsonld.py` | **KEEP, remap** | The JSON-LD walker is good generic code. Remap its output to the new `FieldName` set; add `sameAs` → `social_profile`; delete `_employer_of` (`worksFor` was a person→organization edge that no longer has a person to hang from). |
| `microdata.py` | **KEEP, remap** | Same. The nesting-scope logic is genuinely reusable; only the property map changes. |
| `schema_org.py` | **REWRITE** | The whole file is a schema.org → person/organization property map. New map: `Organization.name/email/telephone/address/vatID/taxID/leiCode/sameAs`, `PostalAddress.*`, `Person.name/jobTitle/sameAs`, `ContactPoint.*`. `join_address` and `normalize_property` survive as helpers. |
| `semantic_html.py` | **KEEP, reduce and extend** | `_scheme_links` (`mailto:`/`tel:`) is the most valuable part and is untouched. Reduce the h-card map to `p-name` → `person_name`, `p-org` → `organization_name`, `p-adr` → `postal_address`, `u-email`, `p-tel`. Add `<link rel="me">` and `rel="pgpkey">`, and `<a href>` ending `.asc`/`.gpg`/`.pgp`. |
| `text_heuristics.py` | **KEEP, extend** | `subject.region` → a plain `region: str`. Email and phone matching unchanged. Add company-identifier patterns — **and their checksums**, because SPEC FR-23 permits this field from text only because it self-validates. `deobfuscate()` untouched. |
| `social.py` | **NEW** | The platform host list and profile-URL normalization. |
| `technology.py` | **NEW** | `<meta name="generator">` plus the `X-Powered-By` and `Server` headers. Three sources, nothing more; resist every temptation to grow this into a fingerprinter. |

## 7. `infrastructure/validators/`

| Module | Verdict | Notes |
|---|---|---|
| `email.py` | **KEEP, simplify** | `validate_email(..., check_deliverability=False)` and `.normalized` unchanged. `classify_local_part(local_part, subject)` loses its `subject` argument: with no subject there is no name to match, so classification is the role-account list alone, and the result is `metadata["email_kind"]` rather than a `ValueType`. This is a simplification, not a loss — the person/organization split was never reliable and the role-account list is. |
| `phone.py` | **KEEP** | `subject` → `region: str`. Nothing else. |
| `address.py` | **KEEP VERBATIM** | It already ignores `subject`; just drop the parameter. |
| `names.py` | **KEEP, rename** | `NameValidator(field)` becomes the `person_name` validator; drop the hardcoded `ValueType.PERSONAL`. Length, digit and alphabetic rules unchanged. |
| `website.py` | **SPLIT** | Keep `OrganizationValidator` and `dedup_website` (the latter is reused for `pgp_key_url` and `social_profile` dedup). **Delete `WebsiteValidator`** — `website` is not a field any more. |
| `hints.py` | **DELETE** | `hinted_value_type` / `VALUE_TYPE_HINT_KEY`. `ValueType` is gone. |
| `social.py`, `company_id.py`, `pgp.py`, `technology.py` | **NEW** | `company_id.py` is the only one with real logic: SIREN/SIRET Luhn and EU VAT formats. |

## 8. `infrastructure/sources/` — deleted entirely

`registry.py`, `annuaire_entreprises.py`, `legal_notice.py`, `github_users.py`, `operator_page.py`, and
every fixture under `tests/fixtures/{annuaire_entreprises,github_users,legal_notice,operator_page}/`.

**Say this out loud, because it is the largest single loss and @LT will ask.** The registry enforced
`ForbiddenSourceError` for any source whose terms status was `forbidden` or `unverified` — a genuinely good
mechanism that made "we do not ship sources that forbid scraping" a compile-time-ish guarantee rather than
a promise. It cannot survive, and the reason is not laziness: it worked because the source set was **closed
and vetted in advance**. In v0.2.0 the target is whatever the operator types, so there is no descriptor to
attach a reviewed terms status to and nothing to refuse at registration. Pretending otherwise — a
`TermsStatus.UNVERIFIED` on every run, say — would be worse than removing it, because a status field that
is always the same value trains people to ignore it.

What replaces it is stated plainly rather than hidden:

- The mechanical guarantees stay mechanical and get *stronger*: robots.txt per URL and per redirect hop,
  a rate floor nothing lowers, bounded budget, bounded depth, bounded concurrency, scope confinement, an
  honest User-Agent that cannot be overridden, and four abort thresholds.
- The one thing that becomes the operator's responsibility — reading the target's terms of service — is
  named as theirs in the README's *Legal use* section and in SPEC §12.2. **robots.txt is a machine-readable
  signal, not a contract.** An honest sentence beats a status field that always reads `unverified`.

The `legal_notice` adapter's candidate-path list is not lost: it becomes `HIGH_VALUE_PATH_PATTERN` in
SPEC §5.4, where it reorders a queue instead of guessing URLs. That is a strict improvement — it never
issues a request for a path that does not exist.

## 9. `infrastructure/writers/`, `ledger/`, `config.py`

| Module | Verdict | Notes |
|---|---|---|
| `sanitize.py` | **KEEP VERBATIM** | `FORMULA_TRIGGERS`, `guard`. 21 lines that must not change. |
| `rows.py` | **REWRITE** | The column schema *is* the product. New `FINDING_COLUMNS`, `PAGE_COLUMNS`, `RUN_KEYS`, `COMPLIANCE_KEYS` per SPEC §9. `timestamp()` survives. |
| `json_writer.py` | **REWRITE** | `schema_version` `"1.0"` → `"2.0"`; the `subject` block becomes `target` + `settings` + `statistics`; `attributes` → `findings`; `conflicts` deleted; `sources` → `pages`. The key-order discipline and the "no key outside the schema" test both survive. |
| `csv_writer.py` | **KEEP** | Mechanics are column-agnostic. `utf-8-sig`, CRLF, `QUOTE_MINIMAL` unchanged. Second file renamed `report_sources.csv` → `report_pages.csv`. |
| `xlsx_writer.py` | **KEEP, extend** | `write_only=True`, bold headers via `WriteOnlyCell` unchanged. Three sheets become four: `Run`, `Findings`, `Pages`, `Compliance`. |
| `jsonl_writer.py`, `markdown_writer.py` | **NEW** | No new dependencies: `json` and string formatting. |
| `ledger/jsonl_ledger.py` | **KEEP, one field change** | `subject_key` → `target_host`, plus `pages_fetched` and `findings_count` for the Runs pane. `FilesystemDirectoryRemover` untouched. The reversal from a hash to plaintext is argued in SPEC §9.7 — do not re-litigate it in code review, litigate it there. |
| `config.py` | **KEEP, extend** | `AppConfig` gains `[crawl]`, `[purpose]`, `concurrent_requests` and `formats`. The TOML/env/default precedence and `require_contact_email()` are unchanged. Values outside the SPEC §5.5 bounds are clamped, and the clamp is reported. |
| `clock.py`, `ids.py` | **KEEP VERBATIM** | |

## 10. `interfaces/`

`cli.py` — **DELETED**, all 575 lines. But read it before deleting it: `build_pipeline()`,
`build_merger()`, `build_writers()` and the `_run_investigate` wiring block are a correct composition root
that happens to be wrapped in argparse. `interfaces/app.py` is that block with the argparse peeled off and
the collaborators handed to a worker instead of to `print()`.

What does **not** transfer:

- `_confirm()` calls `input()`. Replaced by a dialog.
- `render_report()`, `render_plan()` and `_render_descriptor()` return fixed-width plaintext. Replaced by
  table models and view models; the Markdown writer inherits the "render a report for a human" job.
- The six exit codes have no GUI equivalent. `EXIT_COMPLIANCE_REFUSAL` becomes the run-level error banner
  of SPEC §7.5 tier 2, which is the same information delivered where someone will read it.
- `InvestigatePersonUseCase.execute()` is one blocking call with no progress channel. This is precisely why
  `CrawlObserver` and `CancellationToken` exist, and it is the single largest addition the GUI forces on
  the application layer.

New modules per SPEC §10. The binding constraint for @DF: **`PySide6` may not be imported outside
`src/osint_scrapper/interfaces/`** (SPEC NFR-2, AC-ARCH-3), and presentation logic belongs in
`view_models.py` where it is testable without a `QApplication`.

## 11. `tests/`

- `conftest.py` — **the autouse `no_network` fixture stays exactly as it is.** `make_subject` is deleted;
  `make_page` gains `headers`. New fakes: `RecordingObserver`, `NeverCancelled`, `ManualCancellation`, and
  a `FakePageFetcher` that serves the mini-site by canonical URL and counts requests.
- `fixtures/annuaire_entreprises/`, `github_users/`, `legal_notice/`, `operator_page/` — **deleted**.
  Salvage the *markup patterns* into the new mini-site: `jsonld_person.html`, `microdata_organization.html`,
  `hcard_contact.html` and `obfuscated_contact.html` all exercise extractors that survive, so their HTML is
  worth carrying over even though their directory is not.
- `fixtures/robots/` — **kept unchanged**.
- `fixtures/site/` — **new**, and it is the centrepiece. It must exercise every branch listed in SPEC
  AC-E2E-1. No real person's data; invented values on `example.com` / `example.org` only.
- `fixtures/golden/report.json` — **regenerated** against schema 2.0.
- `test_architecture_boundaries.py` — **kept and extended** with AC-ARCH-3 (no PySide6 outside
  `interfaces/`) and AC-ARCH-4 (no surviving person-search vocabulary anywhere in `src/`). Do not weaken
  the existing assertions.
- `test_end_to_end.py` — **rewritten, same philosophy.** Real registry-free chain, real everything, fake
  only the `PageFetcher`, the clock and the sleeper. It remains the only test that catches drift between
  what an extractor emits and what the aggregator expects, and its collaborators must not be stubbed.

## 12. Repository root

| File | Action |
|---|---|
| `pyproject.toml` | Add `PySide6` and dev `pytest-qt`; drop nothing else; `version = "0.2.0"`; description rewritten; the console script now launches the GUI; classifiers `Environment :: Console` → `Environment :: X11 Applications :: Qt` and `Environment :: Win32 (MS Windows)`. |
| `uv.lock` | Regenerated by `uv sync --extra dev`. Commit it. |
| `THIRD_PARTY_LICENSES.md` | **NEW.** LGPLv3 obligation (SPEC FR-19, §3.1). One entry per runtime dependency with its licence, and the Qt/PySide6 statement. |
| `README.md`, `README.fr.md` | Rewritten to SPEC §12. |
| `CLAUDE.md` | Updated: repository state, the new module map, the new output format, and the Qt-confinement rule. |
| `osint-scrapper.toml.example` | Rewritten to SPEC §7.7. |
| `.gitignore` | **`runs/` stays ignored.** Verify it, and add a test (AC-LEGAL-5). |

## 13. What must not regress

Read this list before every review of this refactor.

1. `robots.txt` fail-closed, and now **per URL and per redirect hop**.
2. The rate-limit floor. Nothing lowers it, including the new concurrency.
3. The honest User-Agent, with no override path anywhere.
4. Mandatory purpose before any HTTP request, including `robots.txt`.
5. Per-finding provenance with a source URL and a UTC timestamp; empty provenance raises.
6. No response body, page HTML or free page text is ever written to disk.
7. The test suite never opens a socket, and no fixture holds a real person's data.
8. Parsers fail loudly and specifically; one page's failure never aborts the run.
9. Deterministic, byte-identical exports — now under concurrency, which is a new and harder version of an
   old promise.
10. The formula-injection guard on CSV and XLSX.
11. `runs/` git-ignored.
12. Every file in this repository is written in English.
