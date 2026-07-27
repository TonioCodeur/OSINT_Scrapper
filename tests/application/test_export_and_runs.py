"""Export as its own operator action, and the Runs pane's use cases."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from osint_scrapper.application.errors import ExportFailedError
from osint_scrapper.application.export import ExportRunUseCase
from osint_scrapper.application.ports import LedgerEntry
from osint_scrapper.application.runs import EraseRunsUseCase, ListRunsUseCase
from osint_scrapper.domain.attributes import ExtractionLayer, FieldName, Finding, Provenance
from osint_scrapper.domain.crawl import CrawlOutcome, PageOutcome, PageStatus
from osint_scrapper.domain.report import SiteReport
from osint_scrapper.domain.target import CrawlSettings, Purpose, PurposeCategory, resolve_target
from osint_scrapper.infrastructure.writers.json_reader import JsonReportLoader
from tests.conftest import FrozenClock, InMemoryLedger, RecordingRemover
from tests.wiring import build_exporter

MOMENT = datetime(2026, 7, 27, 14, 2, 11, tzinfo=UTC)
ALL_FORMATS = ("json", "csv", "xlsx", "jsonl", "md")


def report(run_id: str = "r-testrun1") -> SiteReport:
    return SiteReport(
        run_id=run_id,
        target=resolve_target("example.com", include_subdomains=True),
        settings=CrawlSettings(),
        purpose=Purpose(category=PurposeCategory.SELF_AUDIT),
        started_at=MOMENT,
        finished_at=MOMENT,
        outcome=CrawlOutcome.COMPLETED,
        outcome_detail=None,
        tool_name="osint-scrapper",
        tool_version="0.2.0",
        user_agent="OSINT-Scrapper/0.2.0 (+https://example.org; contact: a@b.example)",
        findings=(
            Finding(
                field=FieldName.EMAIL,
                value="contact@example.com",
                extraction_confidence=0.9,
                page_support=1,
                occurrence_count=1,
                first_seen_url="https://example.com/",
                provenance=(
                    Provenance(
                        source_url="https://example.com/",
                        collected_at=MOMENT,
                        extraction_layer=ExtractionLayer.STRUCTURED_DATA,
                        raw_value="contact@example.com",
                    ),
                ),
            ),
        ),
        pages=(PageOutcome("https://example.com/", 0, PageStatus.OK, None, 200, "text/html", 1),),
        pages_fetched=1,
        requests_made=2,
    )


def test_json_is_written_even_when_it_was_not_selected(tmp_path: Path) -> None:
    """AC-EXPORT-5: the canonical record always exists."""
    ledger = InMemoryLedger()
    written = build_exporter(ledger).execute(report(), ["md"], tmp_path)
    names = {path.name for path in written}
    assert "report.json" in names
    assert "report.md" in names
    assert "report.csv" not in names


def test_exporting_indexes_the_run_in_the_ledger(tmp_path: Path) -> None:
    """SPEC 9.7: the ledger is what makes the Runs pane possible without a database."""
    ledger = InMemoryLedger()
    build_exporter(ledger).execute(report(), ALL_FORMATS, tmp_path)
    entry = ledger.entries[0]
    assert entry.target_host == "example.com"
    assert entry.purpose_category == "self_audit"
    assert entry.findings_count == 1
    assert "report.json" in entry.files


def test_the_destination_chooser_copies_and_keeps_the_canonical_copy(tmp_path: Path) -> None:
    """SPEC 7.8: the run directory always keeps its own copy."""
    elsewhere = tmp_path / "elsewhere"
    build_exporter(InMemoryLedger()).execute(report(), ["json"], tmp_path, copy_to=elsewhere)
    assert (tmp_path / "r-testrun1" / "report.json").is_file()
    assert (elsewhere / "report.json").is_file()


def test_one_failing_writer_costs_only_its_own_file(tmp_path: Path) -> None:
    """SPEC 7.8: a file that fails names itself, and the others still succeed."""

    class BrokenWriter:
        @property
        def format_name(self) -> str:
            return "csv"

        def write(self, report_: SiteReport, destination_dir: Path) -> tuple[Path, ...]:
            del report_, destination_dir
            raise OSError("the disk is full")

    from osint_scrapper.infrastructure.writers.json_writer import JsonReportWriter

    exporter = ExportRunUseCase(
        (JsonReportWriter(), BrokenWriter()), InMemoryLedger(), JsonReportLoader()
    )
    with pytest.raises(ExportFailedError) as failure:
        exporter.execute(report(), ["json", "csv"], tmp_path)
    assert [path.name for path in failure.value.written] == ["report.json"]
    assert failure.value.failures == (("csv", "the disk is full"),)
    assert (tmp_path / "r-testrun1" / "report.json").is_file()


def test_re_export_reproduces_the_files_byte_for_byte(tmp_path: Path) -> None:
    """AC-EXPORT-6, and it issues no HTTP request because there is no fetcher here."""
    ledger = InMemoryLedger()
    exporter = build_exporter(ledger)
    first = exporter.execute(report(), ALL_FORMATS, tmp_path)
    before = {path.name: path.read_bytes() for path in first if path.suffix != ".xlsx"}

    exporter.re_export("r-testrun1", ALL_FORMATS, tmp_path)
    after = {
        name: (tmp_path / "r-testrun1" / name).read_bytes()
        for name in before
    }
    assert after == before
    assert len(ledger.entries) == 1, "a re-export must not append a second ledger line"


def test_a_run_summary_carries_everything_the_runs_pane_shows() -> None:
    """SPEC 7.4: the view computes nothing."""
    ledger = InMemoryLedger()
    ledger.record(_entry("r-old", MOMENT - timedelta(days=40)))
    ledger.record(_entry("r-new", MOMENT - timedelta(days=1)))
    remover = RecordingRemover(sizes={"runs/r-old": 1024})
    summaries = ListRunsUseCase(ledger, remover, FrozenClock(MOMENT)).execute()

    assert [summary.run_id for summary in summaries] == ["r-new", "r-old"]
    assert summaries[1].expired is True
    assert summaries[1].size_bytes == 1024
    assert summaries[0].expired is False
    assert summaries[0].days_remaining == 29


def test_erasing_removes_the_directory_and_the_ledger_line() -> None:
    """AC-LEGAL-4 and AC-UI-8."""
    ledger = InMemoryLedger()
    ledger.record(_entry("r-one", MOMENT))
    remover = RecordingRemover()
    erased = EraseRunsUseCase(ledger, remover, FrozenClock(MOMENT)).execute(frozenset({"r-one"}))
    assert erased.removed_run_ids == ("r-one",)
    assert remover.removed == [Path("runs/r-one")]
    assert ledger.entries == []


def test_erasing_an_unknown_run_reports_nothing_matched_rather_than_failing() -> None:
    """AC-UI-8: the operator asked for the data to be gone, and it is gone."""
    erased = EraseRunsUseCase(InMemoryLedger(), RecordingRemover(), FrozenClock()).execute(
        frozenset({"r-missing"})
    )
    assert erased.is_empty()


def test_delete_expired_only_touches_runs_past_their_retention() -> None:
    """SPEC FR-18: nothing is deleted automatically; this is one deliberate action."""
    ledger = InMemoryLedger()
    ledger.record(_entry("r-old", MOMENT - timedelta(days=40)))
    ledger.record(_entry("r-new", MOMENT - timedelta(days=1)))
    erased = EraseRunsUseCase(ledger, RecordingRemover(), FrozenClock(MOMENT)).execute_expired()
    assert erased.removed_run_ids == ("r-old",)
    assert [entry.run_id for entry in ledger.entries] == ["r-new"]


def test_the_canonical_export_is_valid_json_with_a_trailing_newline(tmp_path: Path) -> None:
    build_exporter(InMemoryLedger()).execute(report(), ["json"], tmp_path)
    raw = (tmp_path / "r-testrun1" / "report.json").read_text(encoding="utf-8")
    assert raw.endswith("\n")
    assert json.loads(raw)["run"]["run_id"] == "r-testrun1"


def _entry(run_id: str, created_at: datetime) -> LedgerEntry:
    return LedgerEntry(
        run_id=run_id,
        target_host="example.com",
        target_url="https://example.com/",
        purpose_category="self_audit",
        purpose_note="",
        created_at=created_at,
        retention_days=30,
        directory=f"runs/{run_id}",
        pages_fetched=3,
        findings_count=4,
        files=("report.json",),
    )
