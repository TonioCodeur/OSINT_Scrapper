"""Configuration precedence and clamping, and the run ledger on disk."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from osint_scrapper.application.errors import ConfigurationError
from osint_scrapper.application.ports import LedgerEntry
from osint_scrapper.domain.errors import InvalidCrawlSettingsError
from osint_scrapper.domain.target import CrawlSettings, PurposeCategory
from osint_scrapper.infrastructure.config import (
    CONFIG_FILE_NAME,
    ENV_CONTACT_EMAIL,
    ENV_OUTPUT_DIR,
    AppConfig,
    load_config,
    save_config,
    writable_config_path,
)
from osint_scrapper.infrastructure.ledger.jsonl_ledger import (
    FilesystemDirectoryRemover,
    JsonlRunLedger,
)

MOMENT = datetime(2026, 7, 27, 14, 2, 11, tzinfo=UTC)

FULL_CONFIG = """
[http]
contact_email = "operator@example.org"
project_url = "https://example.org/tool"
request_interval_seconds = 2.0
timeout_seconds = 15.0
max_retries = 2
concurrent_requests = 3

[crawl]
max_pages = 400
max_depth = 5
include_subdomains = false
follow_sitemap = false
phone_region = "be"

[purpose]
category = "journalism"
note = "a stated reason"

[output]
directory = "elsewhere"
retention_days = 7
formats = ["json", "md"]
"""


def write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / CONFIG_FILE_NAME
    path.write_text(body, encoding="utf-8")
    return path


def test_every_documented_key_round_trips(tmp_path: Path) -> None:
    """AC-UI-5: every product setting lives in the TOML file, not in QSettings."""
    config = load_config(write_config(tmp_path, FULL_CONFIG))
    assert config.contact_email == "operator@example.org"
    assert config.request_interval_seconds == 2.0
    assert config.concurrent_requests == 3
    assert (config.max_pages, config.max_depth) == (400, 5)
    assert config.include_subdomains is False
    assert config.follow_sitemap is False
    assert config.phone_region == "BE"
    assert config.purpose_category is PurposeCategory.JOURNALISM
    assert config.purpose_note == "a stated reason"
    assert config.output_directory == Path("elsewhere")
    assert config.retention_days == 7
    assert config.formats == ("json", "md")
    assert config.clamps == ()


def test_a_value_outside_its_bounds_is_clamped_and_reported(tmp_path: Path) -> None:
    """AC-UI-6: the Settings pane must be able to show the clamp, so it is data."""
    config = load_config(
        write_config(
            tmp_path,
            "[crawl]\nmax_pages = 99999\nmax_depth = 42\n"
            "[http]\nconcurrent_requests = 9\nrequest_interval_seconds = 0.05\n",
        )
    )
    assert config.max_pages == 2000
    assert config.max_depth == 10
    assert config.concurrent_requests == 4
    assert config.request_interval_seconds == 0.5
    clamped = {clamp.key for clamp in config.clamps}
    assert clamped == {
        "max_pages",
        "max_depth",
        "concurrent_requests",
        "request_interval_seconds",
    }
    assert "99999" in str(next(c for c in config.clamps if c.key == "max_pages"))


def test_the_clamped_configuration_builds_settings_the_domain_accepts(tmp_path: Path) -> None:
    """AC-UI-6: and the same value constructed directly still raises."""
    config = load_config(write_config(tmp_path, "[crawl]\nmax_pages = 99999\n"))
    assert config.crawl_settings().max_pages == 2000
    with pytest.raises(InvalidCrawlSettingsError):
        CrawlSettings(max_pages=99999)


def test_an_unknown_purpose_category_is_reported_rather_than_crashing(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path, '[purpose]\ncategory = "spying"\n'))
    assert config.purpose_category is PurposeCategory.DUE_DILIGENCE
    assert config.clamps[0].key == "purpose.category"


def test_the_environment_overrides_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SPEC 7.7: interface control > environment > config file > default."""
    path = write_config(tmp_path, FULL_CONFIG)
    monkeypatch.setenv(ENV_CONTACT_EMAIL, "override@example.org")
    monkeypatch.setenv(ENV_OUTPUT_DIR, "from-env")
    config = load_config(path)
    assert config.contact_email == "override@example.org"
    assert config.output_directory == Path("from-env")


def test_a_run_cannot_start_without_a_contact_email() -> None:
    """SPEC FR-20: the tool will not put a User-Agent on the wire nobody can answer."""
    with pytest.raises(ConfigurationError):
        AppConfig().require_contact_email()
    with pytest.raises(ConfigurationError):
        AppConfig(contact_email="not-an-address").require_contact_email()
    assert AppConfig(contact_email="a@b.example").require_contact_email() == "a@b.example"


def test_a_missing_explicit_file_is_an_error_and_a_missing_default_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ConfigurationError):
        load_config(tmp_path / "absent.toml")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert load_config().contact_email is None


def test_a_malformed_file_says_so(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError):
        load_config(write_config(tmp_path, "this is not = = toml"))


def test_settings_are_written_back_where_the_pane_can_name_the_file(tmp_path: Path) -> None:
    """SPEC 7.7: the Settings pane writes the first writable path and says which."""
    path = writable_config_path(tmp_path / CONFIG_FILE_NAME)
    written = save_config(
        AppConfig(contact_email="a@b.example", purpose_category=PurposeCategory.JOURNALISM), path
    )
    assert written == path
    assert load_config(written).purpose_category is PurposeCategory.JOURNALISM


def test_the_ledger_holds_the_host_in_plaintext_and_no_page_content(tmp_path: Path) -> None:
    """AC-LEGAL-4, and SPEC 9.7's deliberate reversal from a hash."""
    ledger = JsonlRunLedger(tmp_path)
    ledger.record(_entry("r-one"))
    body = ledger.path.read_text(encoding="utf-8")
    assert '"target_host": "example.com"' in body
    assert "<html" not in body
    assert ledger.find(target_host="example.com")[0].run_id == "r-one"


def test_forgetting_rewrites_the_ledger_without_those_lines(tmp_path: Path) -> None:
    ledger = JsonlRunLedger(tmp_path)
    ledger.record(_entry("r-one"))
    ledger.record(_entry("r-two"))
    ledger.forget(frozenset({"r-one"}))
    assert [entry.run_id for entry in ledger.find()] == ["r-two"]


def test_a_corrupt_ledger_says_which_line_is_wrong(tmp_path: Path) -> None:
    ledger = JsonlRunLedger(tmp_path)
    ledger.record(_entry("r-one"))
    ledger.path.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(ConfigurationError) as failure:
        ledger.find()
    assert "line 1" in str(failure.value)


def test_the_remover_deletes_a_tree_and_measures_it(tmp_path: Path) -> None:
    run = tmp_path / "r-one"
    (run / "nested").mkdir(parents=True)
    (run / "report.json").write_text("{}", encoding="utf-8")
    (run / "nested" / "report.csv").write_text("a,b", encoding="utf-8")
    remover = FilesystemDirectoryRemover()
    assert remover.size_of(run) == 5
    removed = remover.remove_tree(run)
    assert run in removed
    assert not run.exists()
    assert remover.remove_tree(run) == ()
    assert remover.size_of(run) == 0


def _entry(run_id: str) -> LedgerEntry:
    return LedgerEntry(
        run_id=run_id,
        target_host="example.com",
        target_url="https://example.com/",
        purpose_category="due_diligence",
        purpose_note="",
        created_at=MOMENT,
        retention_days=30,
        directory=f"runs/{run_id}",
        pages_fetched=3,
        findings_count=4,
        files=("report.json",),
    )
