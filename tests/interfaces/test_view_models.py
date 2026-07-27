"""The presentation logic, tested without Qt.

Not one test in this file constructs a ``QApplication``. That is the point of
``view_models`` existing at all: every rule the interface follows is a plain
function over plain data, so it can be pinned down here rather than poked at
through a widget.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from osint_scrapper.application.runs import RunSummary
from osint_scrapper.domain.attributes import ExtractionLayer, FieldName
from osint_scrapper.domain.crawl import CrawlOutcome, PageStatus
from osint_scrapper.interfaces import view_models as vm
from tests.interfaces.conftest import make_finding, make_page, make_report

CONTACT = "nobody@example.org"


def form(**overrides: object) -> vm.CrawlFormState:
    """A form state that is valid unless a test breaks it deliberately."""
    defaults: dict[str, object] = {
        "target_text": "example.com",
        "contact_email": CONTACT,
        "purpose_category": vm.PurposeCategory.SELF_AUDIT,
    }
    defaults.update(overrides)
    return vm.CrawlFormState(**defaults)  # type: ignore[arg-type]


# --------------------------------------------------------------- target hint


def test_empty_target_is_not_valid_and_explains_the_two_accepted_shapes() -> None:
    hint = form(target_text="").target_hint()
    assert not hint.is_valid
    assert "example.com" in hint.message
    assert "http://" in hint.message


def test_valid_target_hint_names_the_resolved_url_and_the_scope_host() -> None:
    hint = form(target_text="example.com").target_hint()
    assert hint.is_valid
    assert hint.target is not None
    assert hint.target.target_url == "https://example.com/"
    assert "example.com" in hint.message
    assert "subdomains" in hint.message


def test_target_hint_without_subdomains_does_not_promise_them() -> None:
    hint = form(target_text="example.com", include_subdomains=False).target_hint()
    assert hint.is_valid
    assert "subdomains" not in hint.message


def test_invalid_target_reports_the_domain_error_verbatim() -> None:
    hint = form(target_text="mailto:someone@example.org").target_hint()
    assert not hint.is_valid
    assert hint.severity is vm.Severity.ERROR
    assert hint.message


# ------------------------------------------------------------------- purpose


def test_purpose_other_requires_a_note_of_sixteen_characters() -> None:
    state = form(purpose_category=vm.PurposeCategory.OTHER, purpose_note="too short")
    assert state.purpose_problem() is not None
    assert not state.start_button_state(vm.RunState.IDLE).enabled


def test_purpose_other_accepts_a_long_enough_note() -> None:
    state = form(
        purpose_category=vm.PurposeCategory.OTHER,
        purpose_note="regulatory filing review",
    )
    assert state.purpose_problem() is None
    assert state.start_button_state(vm.RunState.IDLE).enabled


def test_named_purposes_need_no_note() -> None:
    assert form(purpose_category=vm.PurposeCategory.JOURNALISM).purpose_problem() is None


def test_every_purpose_category_has_a_label() -> None:
    assert set(vm.PURPOSE_LABELS) == set(vm.PurposeCategory)


# ------------------------------------------------------------- start button


def test_start_is_disabled_without_a_contact_email_and_the_tooltip_says_so() -> None:
    state = form(contact_email=None).start_button_state(vm.RunState.IDLE)
    assert not state.enabled
    assert "contact email" in state.tooltip.lower()


def test_start_is_disabled_without_a_target_and_the_tooltip_names_the_target() -> None:
    state = form(target_text="").start_button_state(vm.RunState.IDLE)
    assert not state.enabled
    assert "domain" in state.tooltip.lower()


def test_start_is_disabled_when_the_purpose_note_is_missing() -> None:
    state = form(purpose_category=vm.PurposeCategory.OTHER, purpose_note="").start_button_state(
        vm.RunState.IDLE
    )
    assert not state.enabled
    assert "note" in state.tooltip.lower()


def test_the_contact_email_is_reported_before_the_target() -> None:
    state = form(contact_email=None, target_text="")
    assert "contact email" in (state.blocking_problem() or "").lower()


def test_start_becomes_stop_while_a_crawl_runs() -> None:
    state = form().start_button_state(vm.RunState.RUNNING)
    assert state.enabled
    assert state.text == "Stop crawl"


def test_stopping_disables_the_button_rather_than_offering_a_second_stop() -> None:
    state = form().start_button_state(vm.RunState.STOPPING)
    assert not state.enabled
    assert state.text == "Stopping…"


def test_a_finished_run_can_be_started_again() -> None:
    assert form().start_button_state(vm.RunState.FINISHED).enabled


# ----------------------------------------------------------- domain objects


def test_the_form_builds_the_three_domain_objects_a_run_needs() -> None:
    state = form(max_pages=42, max_depth=2, phone_region="be")
    assert state.to_target().scope_host == "example.com"
    assert state.to_settings().max_pages == 42
    assert state.to_purpose().category is vm.PurposeCategory.SELF_AUDIT


def test_settings_beyond_the_domain_bounds_are_refused_by_the_domain() -> None:
    from osint_scrapper.domain.errors import InvalidCrawlSettingsError

    with pytest.raises(InvalidCrawlSettingsError):
        form(max_pages=99999).to_settings()


# ------------------------------------------------------------ finding rows


def test_findings_are_ordered_by_field_then_confidence_then_support_then_value() -> None:
    rows = vm.finding_rows(
        [
            make_finding(field=FieldName.TECHNOLOGY, value="WordPress 6.5", confidence=0.75),
            make_finding(value="zoe@example.com", confidence=0.90, page_support=1),
            make_finding(value="alice@example.com", confidence=0.90, page_support=1),
            make_finding(value="footer@example.com", confidence=0.90, page_support=9),
            make_finding(value="text@example.com", confidence=0.50),
        ]
    )
    assert [row.value for row in rows] == [
        "footer@example.com",
        "alice@example.com",
        "zoe@example.com",
        "text@example.com",
        "WordPress 6.5",
    ]


def test_the_row_order_matches_the_declaration_order_of_field_name() -> None:
    assert list(vm.FIELD_ORDER) == list(FieldName)
    assert set(vm.FIELD_LABELS) == set(FieldName)


def test_a_finding_row_names_the_highest_layer_that_produced_it() -> None:
    row = vm.finding_row(make_finding(layer=ExtractionLayer.WELL_KNOWN))
    assert row.extraction_layer is ExtractionLayer.WELL_KNOWN
    assert str(ExtractionLayer.WELL_KNOWN) in row.cells()[2]


def test_a_finding_row_tooltip_carries_the_metadata_the_columns_cannot_hold() -> None:
    row = vm.finding_row(make_finding(metadata={"email_kind": "role"}))
    assert "email_kind: role" in row.tooltip()


def test_the_row_key_is_field_and_value_so_updates_land_on_the_same_row() -> None:
    first = vm.finding_row(make_finding(page_support=1))
    second = vm.finding_row(make_finding(page_support=40))
    assert first.key == second.key


# --------------------------------------------------------------- page rows


def test_page_rows_are_numbered_from_the_offset_they_are_given() -> None:
    rows = vm.page_rows([make_page(), make_page(url="https://example.com/a")], first_number=7)
    assert [row.number for row in rows] == [7, 8]


def test_the_status_code_is_shown_verbatim_in_its_own_cell() -> None:
    row = vm.page_rows([make_page(status=PageStatus.SKIPPED_ROBOTS)])[0]
    assert row.cells()[2] == "skipped_robots"


def test_every_page_status_has_a_severity() -> None:
    assert set(vm.STATUS_SEVERITY) == set(PageStatus)


def test_a_failed_page_reads_as_an_error_and_a_skip_does_not() -> None:
    assert vm.STATUS_SEVERITY[PageStatus.TRANSPORT_ERROR] is vm.Severity.ERROR
    assert vm.STATUS_SEVERITY[PageStatus.SKIPPED_EXTENSION] is vm.Severity.INFO


# ---------------------------------------------------------------- progress


def test_the_tracker_counts_fetched_skipped_and_failed_pages_apart() -> None:
    tracker = vm.CrawlProgressTracker(budget=200)
    tracker.record(
        [
            make_page(status=PageStatus.OK),
            make_page(status=PageStatus.NO_FINDINGS),
            make_page(status=PageStatus.SKIPPED_ROBOTS),
            make_page(status=PageStatus.HTTP_ERROR),
            make_page(status=PageStatus.SKIPPED_BUDGET, depth=3),
        ]
    )
    view = tracker.view(elapsed_seconds=65)
    assert (view.fetched, view.skipped, view.errors, view.depth) == (2, 2, 1, 3)


def test_the_progress_label_has_the_exact_shape_the_specification_fixes() -> None:
    tracker = vm.CrawlProgressTracker(budget=200)
    tracker.record([make_page()])
    tracker.set_queued(17)
    text = tracker.view(elapsed_seconds=61).text()
    assert text == "fetched 1/200 · queued 17 · depth 0 · skipped 0 · errors 0 · elapsed 01:01"


def test_the_bar_is_an_upper_bound_and_never_exceeds_a_hundred() -> None:
    tracker = vm.CrawlProgressTracker(budget=2)
    tracker.record([make_page(), make_page(), make_page()])
    assert tracker.view(0).percent() == 100


def test_elapsed_grows_an_hours_field_only_when_it_needs_one() -> None:
    assert vm.format_elapsed(9) == "00:09"
    assert vm.format_elapsed(605) == "10:05"
    assert vm.format_elapsed(3725) == "1:02:05"


# ----------------------------------------------------------------- banners


def test_every_crawl_outcome_has_a_severity_and_a_plain_english_sentence() -> None:
    assert set(vm.OUTCOME_SENTENCES) == set(CrawlOutcome)
    assert set(vm.OUTCOME_SEVERITY) == set(CrawlOutcome)


def test_an_abort_reads_as_a_warning_and_a_defect_reads_as_an_error() -> None:
    assert vm.outcome_banner(CrawlOutcome.ABORTED_RATE_LIMITED).severity is vm.Severity.WARNING
    assert vm.outcome_banner(CrawlOutcome.FAILED).severity is vm.Severity.ERROR


def test_a_stopped_run_is_told_that_its_partial_report_survives() -> None:
    banner = vm.outcome_banner(CrawlOutcome.STOPPED_BY_OPERATOR)
    assert "exportable" in banner.message


def test_a_seed_refusal_says_nothing_was_written_and_nothing_was_requested() -> None:
    banner = vm.seed_refusal_banner("robots_disallow", "https://example.com/")
    assert banner.severity is vm.Severity.ERROR
    assert "did not start" in banner.message
    assert "https://example.com/" in banner.text()


def test_the_compliance_banner_names_the_user_agent_the_floor_and_the_scope() -> None:
    text = vm.compliance_banner_text(
        "OSINT-Scrapper/0.2.0 (+https://example.org; contact: nobody@example.org)",
        1.0,
        0.5,
        "example.com",
        include_subdomains=True,
    )
    assert "OSINT-Scrapper/0.2.0" in text
    assert "robots.txt: honored" in text
    assert "floor 0.5 s" in text
    assert "example.com +subdomains" in text


# -------------------------------------------------------------- status bar


def test_the_status_bar_says_what_the_specification_says_it_says() -> None:
    tracker = vm.CrawlProgressTracker(budget=200)
    tracker.record([make_page()])
    assert vm.status_bar_text(vm.RunState.IDLE, None, 0) == "Idle"
    assert "47" not in vm.status_bar_text(vm.RunState.RUNNING, tracker.view(0), 0)
    running = vm.status_bar_text(vm.RunState.RUNNING, tracker.view(0), 0)
    assert running.startswith("Crawling — 1/200")
    assert vm.status_bar_text(vm.RunState.FINISHED, None, 1) == "Completed — 1 finding"
    assert vm.status_bar_text(vm.RunState.FINISHED, None, 63) == "Completed — 63 findings"


# ------------------------------------------------------------------- runs


def summary(**overrides: object) -> RunSummary:
    values: dict[str, object] = {
        "run_id": "r-0000test",
        "target_host": "example.com",
        "target_url": "https://example.com/",
        "purpose_category": "self_audit",
        "purpose_note": "",
        "created_at": datetime(2026, 7, 20, 9, 0, tzinfo=UTC),
        "retention_days": 30,
        "directory": "runs/r-0000test",
        "pages_fetched": 12,
        "findings_count": 4,
        "files": ("report.json",),
        "size_bytes": 2048,
        "days_remaining": 23,
        "expired": False,
    }
    values.update(overrides)
    return RunSummary(**values)  # type: ignore[arg-type]


def test_runs_are_listed_newest_first() -> None:
    rows = vm.run_rows(
        [
            summary(run_id="r-old", created_at=datetime(2026, 1, 1, tzinfo=UTC)),
            summary(run_id="r-new", created_at=datetime(2026, 7, 1, tzinfo=UTC)),
        ]
    )
    assert [row.run_id for row in rows] == ["r-new", "r-old"]


def test_a_run_row_renders_the_seven_columns_of_the_specification() -> None:
    row = vm.run_rows([summary()])[0]
    assert len(row.cells()) == len(vm.RUN_HEADERS)
    assert row.cells()[1] == "example.com"
    assert row.cells()[5] == "2.0 KiB"
    assert row.cells()[6] == "23 days left"


def test_an_expired_run_says_so_rather_than_showing_a_negative_number() -> None:
    row = vm.run_rows([summary(days_remaining=0, expired=True)])[0]
    assert row.expired
    assert row.retention_text().startswith("expired")


def test_one_day_left_is_not_pluralized() -> None:
    assert vm.run_rows([summary(days_remaining=1)])[0].retention_text() == "1 day left"


# --------------------------------------------------------------- deletion


def test_the_confirmation_names_every_directory_and_counts_the_findings() -> None:
    rows = vm.run_rows([summary(), summary(run_id="r-two", directory="runs/r-two")])
    message = vm.delete_confirmation(rows, deleting_all=False).message()
    assert "runs/r-0000test" in message
    assert "runs/r-two" in message
    assert "8 collected finding(s)" in message
    assert "DELETE" not in message


def test_deleting_everything_demands_the_typed_word() -> None:
    confirmation = vm.delete_confirmation(vm.run_rows([summary()]), deleting_all=True)
    assert confirmation.requires_typed_word
    assert "Type DELETE" in confirmation.message()


def test_deleting_nothing_says_nothing_matched_rather_than_failing() -> None:
    confirmation = vm.delete_confirmation((), deleting_all=True)
    assert not confirmation.requires_typed_word
    assert "Nothing matched" in confirmation.message()


# ---------------------------------------------------------------- exports


def test_json_is_always_written_and_is_never_part_of_the_choice() -> None:
    assert vm.ExportSelection(csv=False, xlsx=False).format_names() == ("json",)


def test_the_export_selection_is_read_from_the_configured_formats() -> None:
    selection = vm.ExportSelection.from_names(["json", "csv", "md"])
    assert selection.csv and selection.markdown
    assert not selection.xlsx and not selection.jsonl
    assert selection.format_names() == ("json", "csv", "md")


def test_markdown_is_accepted_under_either_spelling() -> None:
    assert vm.ExportSelection.from_names(["markdown"]).markdown


# ------------------------------------------------------------- clipboard


def test_selected_rows_copy_as_tsv_with_a_header() -> None:
    payload = vm.rows_to_tsv(("Field", "Value"), [["Email", "contact@example.com"]])
    assert payload == "Field\tValue\nEmail\tcontact@example.com"


def test_a_value_containing_a_tab_cannot_break_the_clipboard_payload() -> None:
    payload = vm.rows_to_tsv(("Value",), [["a\tb\nc"]])
    assert payload.splitlines()[1] == "a b c"


# --------------------------------------------------------------- summary


def test_the_report_summary_separates_fetched_skipped_and_failed_pages() -> None:
    report = make_report(
        pages=(
            make_page(status=PageStatus.OK),
            make_page(status=PageStatus.SKIPPED_ROBOTS),
            make_page(status=PageStatus.TRANSPORT_ERROR),
        )
    )
    text = vm.report_summary(report)
    assert "1 pages fetched, 1 skipped, 1 failed" in text


def test_sizes_are_human_readable() -> None:
    assert vm.format_size(512) == "512 B"
    assert vm.format_size(1536) == "1.5 KiB"
    assert vm.format_size(5 * 1024 * 1024) == "5.0 MiB"


def test_timestamps_are_rfc_3339_utc_with_a_z() -> None:
    assert vm.format_timestamp(datetime(2026, 7, 27, 14, 2, 11, tzinfo=UTC)) == (
        "2026-07-27T14:02:11Z"
    )
