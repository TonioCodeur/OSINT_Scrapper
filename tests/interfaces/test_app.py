"""The composition root.

If this file passes, every adapter the product ships can actually be built and
injected. It is the cheapest possible guard against the wiring drifting away
from the modules it wires, and it opens no socket: the fetcher, the session and
the robots policy are built per run, inside the factory, and this test only
proves the factory exists and is callable.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from osint_scrapper.domain.attributes import ExtractionLayer, FieldName
from osint_scrapper.infrastructure.config import AppConfig
from osint_scrapper.interfaces import app
from osint_scrapper.interfaces.launcher import build_parser

CONTACT = "nobody@example.org"


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    return AppConfig(contact_email=CONTACT, output_directory=tmp_path / "runs")


def test_every_field_has_a_validator() -> None:
    policy = app.build_validation_policy()
    for field in FieldName:
        assert policy.accepts_field(field)


def test_the_pipeline_is_assembled_from_the_layer_extractors() -> None:
    """SPEC 8.2: every shipped extractor is wired, highest authority first.

    A pipeline missing a layer still builds and still returns candidates, so
    only the composition itself can prove the wiring did not silently shrink.
    """
    pipeline = app.build_pipeline()
    extractors = pipeline._extractors
    assert [type(extractor).__name__ for extractor in extractors] == [
        "JsonLdExtractor",
        "MicrodataExtractor",
        "SemanticHtmlExtractor",
        "TechnologyExtractor",
        "TextHeuristicExtractor",
        "DeobfuscatedTextExtractor",
    ]
    assert {extractor.layer for extractor in extractors} == {
        ExtractionLayer.STRUCTURED_DATA,
        ExtractionLayer.SEMANTIC_HTML,
        ExtractionLayer.TEXT_HEURISTIC,
        ExtractionLayer.TEXT_HEURISTIC_DEOBFUSCATED,
    }


def test_every_export_format_has_a_writer() -> None:
    names = {writer.format_name for writer in app.build_writers()}
    assert names == {"json", "csv", "xlsx", "jsonl", "md"}


def test_the_user_agent_is_computed_and_never_typed(config: AppConfig) -> None:
    user_agent = app.user_agent_for(config)
    assert "OSINT-Scrapper" in user_agent
    assert CONTACT in user_agent
    for token in ("Mozilla", "Chrome", "Safari", "Firefox"):
        assert token not in user_agent


def test_without_a_contact_email_the_user_agent_is_a_stand_in() -> None:
    assert app.user_agent_for(AppConfig()) == app.NO_CONTACT_USER_AGENT


def test_the_form_defaults_come_from_the_configuration_file(config: AppConfig) -> None:
    state = app.default_form_state(config)
    assert state.contact_email == CONTACT
    assert state.max_pages == config.max_pages
    assert state.phone_region == config.phone_region


def test_the_whole_window_can_be_built_from_a_configuration(
    qtbot, tmp_path: Path, config: AppConfig
) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = app.build_main_window(config, settings)
    qtbot.addWidget(window)
    try:
        assert window.windowTitle().startswith("osint-scrapper")
        assert window.statusBar() is not None
    finally:
        window.shutdown_crawl()


def test_the_launcher_accepts_exactly_the_three_specified_arguments() -> None:
    parser = build_parser()
    options = {action.dest for action in parser._actions}
    assert options == {"help", "config", "log_level", "version"}


def test_the_launcher_has_no_target_and_no_purpose_argument() -> None:
    parser = build_parser()
    flags = {flag for action in parser._actions for flag in action.option_strings}
    assert "--target" not in flags
    assert "--purpose" not in flags
    assert "--user-agent" not in flags
