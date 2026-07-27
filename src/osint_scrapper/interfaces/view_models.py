"""Presentation logic, in plain Python, with no Qt and no I/O.

Every decision the interface makes about *what to show* lives here: how a
finding becomes a table row, when the Start button is enabled and what its
tooltip says, how a :class:`CrawlOutcome` becomes one plain English sentence,
how a run's retention is rendered. Widgets in the sibling modules do nothing but
move these values into Qt objects.

The split is deliberate and is what makes the interface reviewable: this module
is tested directly, exhaustively, and without ever constructing a
``QApplication`` (SPEC NFR-2, AC-UI-4).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum, StrEnum
from typing import Final

from osint_scrapper.application.runs import RunSummary
from osint_scrapper.domain.attributes import ExtractionLayer, FieldName, Finding
from osint_scrapper.domain.crawl import CrawlOutcome, PageOutcome, PageStatus
from osint_scrapper.domain.errors import DomainError
from osint_scrapper.domain.report import SiteReport
from osint_scrapper.domain.target import (
    CrawlSettings,
    CrawlTarget,
    Purpose,
    PurposeCategory,
    resolve_target,
)

FIELD_ORDER: Final[Mapping[FieldName, int]] = {
    field: index for index, field in enumerate(FieldName)
}
"""``FieldName`` declaration order, the primary sort key of every view (SPEC 9.1.1)."""

FIELD_LABELS: Final[Mapping[FieldName, str]] = {
    FieldName.EMAIL: "Email",
    FieldName.PHONE: "Phone",
    FieldName.POSTAL_ADDRESS: "Postal address",
    FieldName.PERSON_NAME: "Person name",
    FieldName.ORGANIZATION_NAME: "Organization name",
    FieldName.SOCIAL_PROFILE: "Social profile",
    FieldName.PGP_KEY_URL: "PGP key URL",
    FieldName.COMPANY_IDENTIFIER: "Company identifier",
    FieldName.TECHNOLOGY: "Technology",
}

PURPOSE_LABELS: Final[Mapping[PurposeCategory, str]] = {
    PurposeCategory.SECURITY_ASSESSMENT: "Authorized security assessment with a written scope",
    PurposeCategory.DUE_DILIGENCE: "Vendor, supplier or pre-contract due diligence",
    PurposeCategory.JOURNALISM: "Journalistic research",
    PurposeCategory.SELF_AUDIT: "Auditing a site we own or operate",
    PurposeCategory.ACADEMIC_RESEARCH: "Academic or statistical research",
    PurposeCategory.OTHER: "Other — a note is required",
}

LAYER_LABELS: Final[Mapping[ExtractionLayer, str]] = {
    ExtractionLayer.WELL_KNOWN: "Well-known file (RFC 9116)",
    ExtractionLayer.STRUCTURED_DATA: "Structured markup (JSON-LD, microdata)",
    ExtractionLayer.SEMANTIC_HTML: "Semantic HTML",
    ExtractionLayer.TEXT_HEURISTIC: "Visible text, self-validating value only",
    ExtractionLayer.TEXT_HEURISTIC_DEOBFUSCATED: "De-obfuscated visible text",
}

MINIMUM_OTHER_NOTE_LENGTH: Final = 16
"""The v1.0 free-text guard, kept for exactly the case that needs it (SPEC 7.2.2)."""


class Severity(StrEnum):
    """How a row or a banner should read. Colour is chosen by the widget layer."""

    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


class RunState(Enum):
    """The state machine behind the Start/Stop button and the status bar."""

    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FINISHED = "finished"

    @property
    def is_busy(self) -> bool:
        """Whether a crawl is in flight, so the form must stay read-only."""
        return self in {RunState.STARTING, RunState.RUNNING, RunState.STOPPING}


STATUS_SEVERITY: Final[Mapping[PageStatus, Severity]] = {
    PageStatus.OK: Severity.SUCCESS,
    PageStatus.NO_FINDINGS: Severity.INFO,
    PageStatus.SKIPPED_ROBOTS: Severity.WARNING,
    PageStatus.SKIPPED_EXTENSION: Severity.INFO,
    PageStatus.SKIPPED_CONTENT_TYPE: Severity.INFO,
    PageStatus.SKIPPED_OFF_SCOPE: Severity.INFO,
    PageStatus.SKIPPED_BUDGET: Severity.INFO,
    PageStatus.SKIPPED_DEPTH: Severity.INFO,
    PageStatus.URL_REJECTED_SHAPE: Severity.WARNING,
    PageStatus.CREDENTIALS_IN_URL: Severity.WARNING,
    PageStatus.OFF_SCOPE_REDIRECT: Severity.WARNING,
    PageStatus.TOO_MANY_REDIRECTS: Severity.WARNING,
    PageStatus.TOO_LARGE: Severity.WARNING,
    PageStatus.RATE_LIMITED: Severity.ERROR,
    PageStatus.HTTP_ERROR: Severity.ERROR,
    PageStatus.TRANSPORT_ERROR: Severity.ERROR,
    PageStatus.PARSE_ERROR: Severity.ERROR,
}

FAILURE_STATUSES: Final[frozenset[PageStatus]] = frozenset(
    {
        PageStatus.RATE_LIMITED,
        PageStatus.HTTP_ERROR,
        PageStatus.TRANSPORT_ERROR,
        PageStatus.PARSE_ERROR,
        PageStatus.TOO_MANY_REDIRECTS,
    }
)

FETCHED_STATUSES: Final[frozenset[PageStatus]] = frozenset(
    {PageStatus.OK, PageStatus.NO_FINDINGS}
)

OUTCOME_SEVERITY: Final[Mapping[CrawlOutcome, Severity]] = {
    CrawlOutcome.COMPLETED: Severity.SUCCESS,
    CrawlOutcome.BUDGET_EXHAUSTED: Severity.INFO,
    CrawlOutcome.DEPTH_EXHAUSTED: Severity.INFO,
    CrawlOutcome.STOPPED_BY_OPERATOR: Severity.INFO,
    CrawlOutcome.ABORTED_RATE_LIMITED: Severity.WARNING,
    CrawlOutcome.ABORTED_HOST_UNHEALTHY: Severity.WARNING,
    CrawlOutcome.ABORTED_ERROR_RATE: Severity.WARNING,
    CrawlOutcome.FAILED: Severity.ERROR,
}

OUTCOME_SENTENCES: Final[Mapping[CrawlOutcome, str]] = {
    CrawlOutcome.COMPLETED: "The frontier was exhausted: every in-scope page was visited.",
    CrawlOutcome.BUDGET_EXHAUSTED: (
        "The page budget was reached. Raise Max pages to go further, "
        "or accept this as the polite ceiling you set."
    ),
    CrawlOutcome.DEPTH_EXHAUSTED: (
        "Every page within the depth limit was visited. Raise Max depth to go deeper."
    ),
    CrawlOutcome.STOPPED_BY_OPERATOR: (
        "You stopped the crawl. Everything collected before the stop is complete and exportable."
    ),
    CrawlOutcome.ABORTED_RATE_LIMITED: (
        "The site asked us repeatedly to slow down, so the crawl stopped rather than escalate. "
        "Raise the request interval and try again later."
    ),
    CrawlOutcome.ABORTED_HOST_UNHEALTHY: (
        "The site stopped answering. The crawl stopped rather than keep hammering a host "
        "that is already struggling."
    ),
    CrawlOutcome.ABORTED_ERROR_RATE: (
        "More than half of the requests failed. The crawl stopped because the results would "
        "not be trustworthy. Check the page log for the failing status."
    ),
    CrawlOutcome.FAILED: (
        "The run failed with an unexpected error. Whatever was collected before the failure "
        "is still exportable."
    ),
}


@dataclass(frozen=True)
class Banner:
    """One run-level message: the second of the three error tiers (SPEC 7.5)."""

    severity: Severity
    title: str
    message: str
    detail: str | None = None

    def text(self) -> str:
        """The banner rendered as one string, for a plain label or a test."""
        parts = [f"{self.title} — {self.message}"]
        if self.detail:
            parts.append(self.detail)
        return "\n".join(parts)


@dataclass(frozen=True)
class ButtonState:
    """Whether a control is usable, what it says, and why it is not usable."""

    enabled: bool
    text: str
    tooltip: str


@dataclass(frozen=True)
class TargetHint:
    """The live hint under the target box: what will be crawled, or what is wrong."""

    target: CrawlTarget | None
    message: str
    severity: Severity

    @property
    def is_valid(self) -> bool:
        """Whether the entered value resolved to a crawlable target."""
        return self.target is not None


@dataclass(frozen=True)
class FindingRow:
    """One row of the findings table (SPEC 7.3, region 2)."""

    key: tuple[str, str]
    """``(field, value)`` — the identity a live update matches on."""

    field: FieldName
    field_label: str
    value: str
    extraction_layer: ExtractionLayer
    extraction_confidence: float
    page_support: int
    occurrence_count: int
    first_seen_url: str
    metadata: Mapping[str, str]

    def sort_key(self) -> tuple[int, float, int, str]:
        """The canonical order of SPEC 9.1.1, so the view agrees with the export."""
        return (
            FIELD_ORDER[self.field],
            -self.extraction_confidence,
            -self.page_support,
            self.value,
        )

    def cells(self) -> tuple[str, str, str, str, str]:
        """The five displayed cells: Field, Value, Extraction, Pages, First seen."""
        return (
            self.field_label,
            self.value,
            str(self.extraction_layer),
            str(self.page_support),
            self.first_seen_url,
        )

    def tooltip(self) -> str:
        """The full detail a truncated cell hides, including per-field metadata."""
        lines = [
            f"{self.field_label}: {self.value}",
            f"Extraction: {LAYER_LABELS[self.extraction_layer]} "
            f"({self.extraction_layer}, confidence {self.extraction_confidence:.2f})",
            f"Seen on {self.page_support} page(s), {self.occurrence_count} observation(s)",
            f"First seen: {self.first_seen_url}",
        ]
        lines.extend(f"{name}: {value}" for name, value in sorted(self.metadata.items()))
        return "\n".join(lines)


FINDING_HEADERS: Final[tuple[str, ...]] = ("Field", "Value", "Extraction", "Pages", "First seen")


@dataclass(frozen=True)
class PageRow:
    """One row of the page log (SPEC 7.3, region 3)."""

    number: int
    depth: int
    status: PageStatus
    url: str
    detail: str
    http_status: int | None
    content_type: str | None
    findings_count: int

    @property
    def severity(self) -> Severity:
        """How loudly this row should read."""
        return STATUS_SEVERITY[self.status]

    def cells(self) -> tuple[str, str, str, str, str]:
        """The five displayed cells. The status code is shown verbatim (SPEC 7.3)."""
        return (str(self.number), str(self.depth), str(self.status), self.url, self.detail)

    def tooltip(self) -> str:
        """Everything the row carries, including what the columns cannot hold."""
        lines = [self.url, f"Status: {self.status}", f"Depth: {self.depth}"]
        if self.http_status is not None:
            lines.append(f"HTTP status: {self.http_status}")
        if self.content_type:
            lines.append(f"Content-Type: {self.content_type}")
        lines.append(f"Findings on this page: {self.findings_count}")
        if self.detail:
            lines.append(self.detail)
        return "\n".join(lines)


PAGE_HEADERS: Final[tuple[str, ...]] = ("#", "Depth", "Status", "URL", "Detail")


@dataclass(frozen=True)
class RunRow:
    """One row of the Runs pane (SPEC 7.4)."""

    run_id: str
    created_at: datetime
    target_host: str
    purpose_category: str
    purpose_note: str
    pages_fetched: int
    findings_count: int
    size_bytes: int
    retention_days: int
    days_remaining: int
    directory: str

    @property
    def expired(self) -> bool:
        """Whether the declared retention period has already elapsed (SPEC FR-18)."""
        return self.days_remaining <= 0

    def cells(self) -> tuple[str, str, str, str, str, str, str]:
        """Date, Target host, Purpose, Pages, Findings, Size, Retention."""
        return (
            format_timestamp(self.created_at),
            self.target_host,
            self.purpose_category,
            str(self.pages_fetched),
            str(self.findings_count),
            format_size(self.size_bytes),
            self.retention_text(),
        )

    def retention_text(self) -> str:
        """How long this run has left, in the operator's words."""
        if self.days_remaining <= 0:
            return f"expired ({self.retention_days} d declared)"
        if self.days_remaining == 1:
            return "1 day left"
        return f"{self.days_remaining} days left"


RUN_HEADERS: Final[tuple[str, ...]] = (
    "Date",
    "Target host",
    "Purpose",
    "Pages",
    "Findings",
    "Size",
    "Retention",
)


@dataclass(frozen=True)
class ProgressView:
    """The authoritative progress label of SPEC 7.3, region 1."""

    fetched: int
    budget: int
    queued: int
    depth: int
    skipped: int
    errors: int
    elapsed_seconds: float

    def text(self) -> str:
        """The label. It says "budget", never "estimated", because it is a ceiling."""
        return (
            f"fetched {self.fetched}/{self.budget} · queued {self.queued} · "
            f"depth {self.depth} · skipped {self.skipped} · errors {self.errors} · "
            f"elapsed {format_elapsed(self.elapsed_seconds)}"
        )

    def percent(self) -> int:
        """Where the determinate bar sits. The bar is an upper bound, not a forecast."""
        if self.budget <= 0:
            return 0
        return min(100, round(100 * self.fetched / self.budget))


SKIPPED_STATUSES: Final[frozenset[PageStatus]] = frozenset(
    {
        PageStatus.SKIPPED_ROBOTS,
        PageStatus.SKIPPED_EXTENSION,
        PageStatus.SKIPPED_CONTENT_TYPE,
        PageStatus.SKIPPED_OFF_SCOPE,
        PageStatus.SKIPPED_BUDGET,
        PageStatus.SKIPPED_DEPTH,
        PageStatus.URL_REJECTED_SHAPE,
        PageStatus.CREDENTIALS_IN_URL,
        PageStatus.OFF_SCOPE_REDIRECT,
        PageStatus.TOO_LARGE,
    }
)


class CrawlProgressTracker:
    """Accumulates page outcomes into the progress numbers of SPEC 7.3.

    It is fed the same batches the page log receives, so the label and the log
    can never disagree, and it is plain Python so the arithmetic is tested
    without a widget.
    """

    def __init__(self, budget: int) -> None:
        self._budget = budget
        self._fetched = 0
        self._skipped = 0
        self._errors = 0
        self._deepest = 0
        self._queued = 0

    def record(self, outcomes: Iterable[PageOutcome]) -> None:
        """Fold one batch of outcomes into the counters."""
        for outcome in outcomes:
            self._deepest = max(self._deepest, outcome.depth)
            if outcome.status in FETCHED_STATUSES:
                self._fetched += 1
            elif outcome.status in FAILURE_STATUSES:
                self._errors += 1
            elif outcome.status in SKIPPED_STATUSES:
                self._skipped += 1

    def set_queued(self, queued: int) -> None:
        """Record the frontier size last reported by the crawl."""
        self._queued = queued

    def view(self, elapsed_seconds: float) -> ProgressView:
        """The current numbers, ready to render."""
        return ProgressView(
            fetched=self._fetched,
            budget=self._budget,
            queued=self._queued,
            depth=self._deepest,
            skipped=self._skipped,
            errors=self._errors,
            elapsed_seconds=elapsed_seconds,
        )


@dataclass(frozen=True)
class CrawlFormState:
    """Every value the Crawl pane's controls hold, as plain data.

    The widgets read their values into this, ask it what is allowed, and act on
    the answer. Nothing here knows that Qt exists.
    """

    target_text: str = ""
    purpose_category: PurposeCategory = PurposeCategory.DUE_DILIGENCE
    purpose_note: str = ""
    max_pages: int = 200
    max_depth: int = 3
    request_interval_seconds: float = 1.0
    concurrent_requests: int = 2
    include_subdomains: bool = True
    follow_sitemap: bool = True
    phone_region: str = "FR"
    retention_days: int = 30
    contact_email: str | None = None

    def target_hint(self) -> TargetHint:
        """Resolve the typed target, or explain why it cannot be resolved."""
        entered = self.target_text.strip()
        if not entered:
            return TargetHint(
                None,
                "Enter a domain such as example.com, or a full page URL. "
                "A bare domain is crawled over https; type http:// explicitly if you need it.",
                Severity.INFO,
            )
        try:
            target = resolve_target(entered, include_subdomains=self.include_subdomains)
        except DomainError as invalid:
            return TargetHint(None, str(invalid), Severity.ERROR)
        scope = (
            f"{target.scope_host} and its subdomains"
            if target.include_subdomains
            else target.scope_host
        )
        return TargetHint(target, f"Will crawl {target.target_url} · scope: {scope}", Severity.INFO)

    def purpose_problem(self) -> str | None:
        """Why the declared purpose is not acceptable yet, or ``None``."""
        note = self.purpose_note.strip()
        if self.purpose_category == PurposeCategory.OTHER and len(note) < MINIMUM_OTHER_NOTE_LENGTH:
            missing = MINIMUM_OTHER_NOTE_LENGTH - len(note)
            return (
                f"Purpose 'other' needs a note of at least {MINIMUM_OTHER_NOTE_LENGTH} "
                f"characters; {missing} more to go."
            )
        return None

    def blocking_problem(self) -> str | None:
        """The one thing standing between the operator and a crawl, or ``None``.

        Ordered so the tooltip names the obstacle the operator can fix first
        (SPEC AC-UI-1). The contact email comes first because FR-20 refuses the
        run outright without it, and no control in this pane can supply it.
        """
        if not self.contact_email:
            return (
                "Set a contact email in Settings first: the User-Agent this tool sends "
                "must carry an address the site owner can answer."
            )
        if not self.target_hint().is_valid:
            return self.target_hint().message
        return self.purpose_problem()

    def start_button_state(self, state: RunState) -> ButtonState:
        """What the primary button says and whether it can be pressed."""
        if state is RunState.STOPPING:
            return ButtonState(
                False,
                "Stopping…",
                "Finishing the requests already in flight; nothing is killed mid-write.",
            )
        if state.is_busy:
            return ButtonState(
                True,
                "Stop crawl",
                "Stop after the requests in flight finish. The partial report stays exportable.",
            )
        problem = self.blocking_problem()
        if problem is not None:
            return ButtonState(False, "Start crawl", problem)
        return ButtonState(True, "Start crawl", "Start crawling the target above.")

    def to_target(self) -> CrawlTarget:
        """Build the domain target. Raises ``DomainError`` if the text is invalid."""
        return resolve_target(
            self.target_text.strip(), include_subdomains=self.include_subdomains
        )

    def to_purpose(self) -> Purpose:
        """Build the domain purpose. Raises ``DomainError`` if the note is too short."""
        return Purpose(category=self.purpose_category, note=self.purpose_note.strip())

    def to_settings(self) -> CrawlSettings:
        """Build the domain settings. The domain re-checks every bound of SPEC 5.5."""
        return CrawlSettings(
            max_pages=self.max_pages,
            max_depth=self.max_depth,
            request_interval_seconds=self.request_interval_seconds,
            concurrent_requests=self.concurrent_requests,
            include_subdomains=self.include_subdomains,
            follow_sitemap=self.follow_sitemap,
            phone_region=self.phone_region.strip().upper(),
            retention_days=self.retention_days,
        )


LAYER_ORDER: Final[Mapping[ExtractionLayer, int]] = {
    ExtractionLayer.TEXT_HEURISTIC_DEOBFUSCATED: 0,
    ExtractionLayer.TEXT_HEURISTIC: 1,
    ExtractionLayer.SEMANTIC_HTML: 2,
    ExtractionLayer.STRUCTURED_DATA: 3,
    ExtractionLayer.WELL_KNOWN: 4,
}
"""Authority order, used to name the layer that earned the finding's confidence."""


def finding_row(finding: Finding) -> FindingRow:
    """Turn one domain finding into its row."""
    layer = max(
        (entry.extraction_layer for entry in finding.provenance),
        key=lambda item: LAYER_ORDER[item],
    )
    return FindingRow(
        key=(str(finding.field), finding.value),
        field=finding.field,
        field_label=FIELD_LABELS[finding.field],
        value=finding.value,
        extraction_layer=layer,
        extraction_confidence=finding.extraction_confidence,
        page_support=finding.page_support,
        occurrence_count=finding.occurrence_count,
        first_seen_url=finding.first_seen_url,
        metadata=dict(finding.metadata),
    )


def finding_rows(findings: Iterable[Finding]) -> tuple[FindingRow, ...]:
    """Every finding as a row, in the canonical export order of SPEC 9.1.1."""
    return tuple(sorted((finding_row(item) for item in findings), key=FindingRow.sort_key))


def page_rows(outcomes: Iterable[PageOutcome], first_number: int = 1) -> tuple[PageRow, ...]:
    """Number a batch of page outcomes for the log, continuing from ``first_number``."""
    return tuple(
        PageRow(
            number=first_number + offset,
            depth=outcome.depth,
            status=outcome.status,
            url=outcome.url,
            detail=outcome.detail or "",
            http_status=outcome.http_status,
            content_type=outcome.content_type,
            findings_count=outcome.findings_count,
        )
        for offset, outcome in enumerate(outcomes)
    )


def compliance_banner_text(
    user_agent: str,
    effective_interval_seconds: float,
    hard_floor_seconds: float,
    scope_host: str,
    include_subdomains: bool,
) -> str:
    """The non-dismissible honest-disclosure line of SPEC 7.3, region 4."""
    scope = f"{scope_host} +subdomains" if include_subdomains else scope_host
    return (
        f"User-Agent: {user_agent} · robots.txt: honored on every request and every "
        f"redirect hop · interval: {effective_interval_seconds:.1f} s "
        f"(floor {hard_floor_seconds:.1f} s) · scope: {scope}"
    )


def outcome_banner(outcome: CrawlOutcome, detail: str | None = None) -> Banner:
    """One plain English sentence for how a run ended (SPEC 7.5, tier 2)."""
    return Banner(
        severity=OUTCOME_SEVERITY[outcome],
        title=str(outcome),
        message=OUTCOME_SENTENCES[outcome],
        detail=detail,
    )


def seed_refusal_banner(reason: str, detail: str) -> Banner:
    """The run did not start at all: the seed itself was refused (SPEC 5.10)."""
    return Banner(
        severity=Severity.ERROR,
        title=reason,
        message=(
            "The crawl did not start, so nothing was written and no request was made "
            "for any page of this site."
        ),
        detail=detail,
    )


def status_bar_text(
    state: RunState, progress: ProgressView | None, findings_count: int
) -> str:
    """The one-line state of SPEC 7.1."""
    if state is RunState.IDLE:
        return "Idle"
    if state is RunState.STARTING:
        return "Starting — checking robots.txt for the target"
    if state is RunState.STOPPING:
        return "Stopping — waiting for the requests in flight"
    if state is RunState.RUNNING and progress is not None:
        return f"Crawling — {progress.fetched}/{progress.budget} pages"
    plural = "" if findings_count == 1 else "s"
    return f"Completed — {findings_count} finding{plural}"


@dataclass(frozen=True)
class RunLedgerView:
    """What the Runs pane needs about one recorded run.

    The ledger is infrastructure and the size on disk is a filesystem fact;
    both are gathered off the GUI thread and handed here as plain data, which
    is what lets :func:`run_rows` be tested with no files and no ledger.
    """

    run_id: str
    target_host: str
    purpose_category: str
    purpose_note: str
    created_at: datetime
    retention_days: int
    directory: str
    pages_fetched: int
    findings_count: int
    size_bytes: int


def run_rows(summaries: Sequence[RunSummary]) -> tuple[RunRow, ...]:
    """Every recorded run as a row, newest first (SPEC 7.4).

    ``days_remaining`` and ``expired`` are computed by the application layer and
    read here as given: retention is a compliance fact, not a presentation one,
    and two implementations of the same subtraction is one too many.
    """
    rows = [
        RunRow(
            run_id=summary.run_id,
            created_at=summary.created_at,
            target_host=summary.target_host,
            purpose_category=summary.purpose_category,
            purpose_note=summary.purpose_note,
            pages_fetched=summary.pages_fetched,
            findings_count=summary.findings_count,
            size_bytes=summary.size_bytes,
            retention_days=summary.retention_days,
            days_remaining=summary.days_remaining,
            directory=summary.directory,
        )
        for summary in summaries
    ]
    rows.sort(key=lambda row: (row.created_at, row.run_id), reverse=True)
    return tuple(rows)


@dataclass(frozen=True)
class ExportSelection:
    """Which formats the export dialog will write.

    JSON is not a choice: it is the canonical record, so it is always present
    and the checkbox that shows it is disabled (SPEC FR-31, AC-EXPORT-5).
    """

    csv: bool = True
    xlsx: bool = True
    jsonl: bool = False
    markdown: bool = False

    @classmethod
    def from_names(cls, names: Iterable[str]) -> ExportSelection:
        """Build a selection from the ``[output].formats`` list of the config file."""
        wanted = {name.strip().lower() for name in names}
        return cls(
            csv="csv" in wanted,
            xlsx="xlsx" in wanted,
            jsonl="jsonl" in wanted,
            markdown=bool({"md", "markdown"} & wanted),
        )

    def format_names(self) -> tuple[str, ...]:
        """The formats to write, JSON first and always present."""
        names = ["json"]
        if self.csv:
            names.append("csv")
        if self.xlsx:
            names.append("xlsx")
        if self.jsonl:
            names.append("jsonl")
        if self.markdown:
            names.append("md")
        return tuple(names)


@dataclass(frozen=True)
class DeleteConfirmation:
    """What a deletion is about to destroy, spelled out before it happens (SPEC 7.4)."""

    directories: tuple[str, ...]
    findings_count: int
    requires_typed_word: bool

    def message(self) -> str:
        """The confirmation text, naming every directory it will remove."""
        if not self.directories:
            return "Nothing matched. No run was deleted."
        plural = "" if len(self.directories) == 1 else "s"
        lines = [
            f"Permanently delete {len(self.directories)} run{plural}, "
            f"destroying {self.findings_count} collected finding(s).",
            "",
            "These directories will be removed:",
        ]
        lines.extend(f"  {directory}" for directory in self.directories)
        lines.append("")
        lines.append("The ledger will be rewritten without these runs. This cannot be undone.")
        if self.requires_typed_word:
            lines.append("")
            lines.append("Type DELETE below to confirm.")
        return "\n".join(lines)


def delete_confirmation(rows: Sequence[RunRow], deleting_all: bool) -> DeleteConfirmation:
    """Build the confirmation for the selected runs."""
    return DeleteConfirmation(
        directories=tuple(row.directory for row in rows),
        findings_count=sum(row.findings_count for row in rows),
        requires_typed_word=deleting_all and bool(rows),
    )


def report_summary(report: SiteReport) -> str:
    """A one-paragraph description of a finished run, for the completion strip."""
    fetched = sum(1 for page in report.pages if page.status in FETCHED_STATUSES)
    failed = sum(1 for page in report.pages if page.status in FAILURE_STATUSES)
    skipped = len(report.pages) - fetched - failed
    return (
        f"Run {report.run_id} · {len(report.findings)} findings · "
        f"{fetched} pages fetched, {skipped} skipped, {failed} failed · "
        f"{report.requests_made} requests"
    )


def rows_to_tsv(headers: Sequence[str], rows: Iterable[Sequence[str]]) -> str:
    """Render selected rows as TSV for the clipboard (SPEC 7.3, region 2).

    Tabs and newlines inside a value are replaced by spaces: a clipboard payload
    whose own separators appear inside a cell is not pasteable anywhere.
    """
    lines = ["\t".join(headers)]
    lines.extend("\t".join(_flatten(cell) for cell in row) for row in rows)
    return "\n".join(lines)


def _flatten(value: str) -> str:
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")


def format_elapsed(seconds: float) -> str:
    """``mm:ss``, or ``h:mm:ss`` once a crawl passes an hour."""
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_size(size_bytes: int) -> str:
    """A human-readable size for the Runs pane."""
    size = float(size_bytes)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            precision = 0 if unit == "B" else 1
            return f"{size:.{precision}f} {unit}"
        size /= 1024
    raise AssertionError("unreachable: the loop returns on its last unit")


def format_timestamp(moment: datetime) -> str:
    """RFC 3339 UTC with a ``Z`` suffix, the same shape every export uses."""
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
