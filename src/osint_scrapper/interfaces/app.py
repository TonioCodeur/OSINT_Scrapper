"""The single composition root (SPEC NFR-3, AC-ARCH-5).

Every concrete adapter in the product is constructed here and injected through a
constructor. No widget builds a session, a fetcher, a writer or a use case for
itself; no module-level singleton exists; and the only thing the rest of
``interfaces/`` knows about infrastructure is the shape of the callables handed
to it.

One subtlety worth stating, because it looks like an exception and is not: the
crawl use case is built **per run**, since it holds per-run state and its fetcher
is scoped to one target. The factory that builds it is created here, closing over
every collaborator; the worker calls that factory and constructs nothing itself.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from osint_scrapper import PRODUCT_TOKEN, TOOL_NAME, __version__
from osint_scrapper.application.crawl import CrawlSiteUseCase
from osint_scrapper.application.export import ExportRunUseCase
from osint_scrapper.application.ports import CancellationToken, CrawlObserver, ResultWriter
from osint_scrapper.application.runs import EraseRunsUseCase, ListRunsUseCase
from osint_scrapper.application.validation import ValidationPolicy
from osint_scrapper.domain.attributes import FieldName
from osint_scrapper.domain.report import SiteReport
from osint_scrapper.infrastructure.clock import SystemClock, SystemMonotonicClock, SystemSleeper
from osint_scrapper.infrastructure.config import (
    AppConfig,
    load_config,
    save_config,
    writable_config_path,
)
from osint_scrapper.infrastructure.discovery.links import HtmlLinkExtractor
from osint_scrapper.infrastructure.discovery.security_txt import RfcSecurityTxtReader
from osint_scrapper.infrastructure.discovery.sitemap import BeautifulSoupSitemapReader
from osint_scrapper.infrastructure.extraction.jsonld import JsonLdExtractor
from osint_scrapper.infrastructure.extraction.microdata import MicrodataExtractor
from osint_scrapper.infrastructure.extraction.pipeline import ExtractionPipeline
from osint_scrapper.infrastructure.extraction.semantic_html import SemanticHtmlExtractor
from osint_scrapper.infrastructure.extraction.technology import TechnologyExtractor
from osint_scrapper.infrastructure.extraction.text_heuristics import (
    DeobfuscatedTextExtractor,
    TextHeuristicExtractor,
)
from osint_scrapper.infrastructure.http.rate_limit import HARD_FLOOR_SECONDS, PerHostRateLimiter
from osint_scrapper.infrastructure.http.requests_fetcher import (
    FetchPolicy,
    RequestsPageFetcher,
    RequestsRobotsTransport,
    build_session,
)
from osint_scrapper.infrastructure.http.robots import RobotsTxtPolicy
from osint_scrapper.infrastructure.http.user_agent import build_user_agent
from osint_scrapper.infrastructure.ids import UuidRunIdGenerator
from osint_scrapper.infrastructure.ledger.jsonl_ledger import (
    FilesystemDirectoryRemover,
    JsonlRunLedger,
)
from osint_scrapper.infrastructure.validators.address import PostalAddressValidator
from osint_scrapper.infrastructure.validators.company_id import CompanyIdentifierValidator
from osint_scrapper.infrastructure.validators.email import EmailValidator
from osint_scrapper.infrastructure.validators.names import PersonNameValidator
from osint_scrapper.infrastructure.validators.organization import OrganizationValidator
from osint_scrapper.infrastructure.validators.pgp import PgpKeyUrlValidator
from osint_scrapper.infrastructure.validators.phone import PhoneValidator
from osint_scrapper.infrastructure.validators.social import SocialProfileValidator
from osint_scrapper.infrastructure.validators.technology import TechnologyValidator
from osint_scrapper.infrastructure.writers.csv_writer import CsvReportWriter
from osint_scrapper.infrastructure.writers.json_reader import JsonReportLoader
from osint_scrapper.infrastructure.writers.json_writer import JsonReportWriter
from osint_scrapper.infrastructure.writers.jsonl_writer import JsonlReportWriter
from osint_scrapper.infrastructure.writers.markdown_writer import MarkdownReportWriter
from osint_scrapper.infrastructure.writers.xlsx_writer import XlsxReportWriter
from osint_scrapper.interfaces.crawl_pane import CrawlPane
from osint_scrapper.interfaces.export_dialog import ExportJob
from osint_scrapper.interfaces.main_window import MainWindow
from osint_scrapper.interfaces.runs_pane import RunsPane
from osint_scrapper.interfaces.settings_pane import SettingsPane
from osint_scrapper.interfaces.view_models import CrawlFormState, ExportSelection, RunRow
from osint_scrapper.interfaces.worker import (
    CrawlController,
    CrawlRequest,
    drain_background_tasks,
)

logger = logging.getLogger(__name__)

ORGANIZATION_NAME: Final = "OSINT_scrapper"
"""Only ever used as the ``QSettings`` scope for window geometry."""

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[3]
LICENSES_FILE: Final = REPOSITORY_ROOT / "THIRD_PARTY_LICENSES.md"
README_FILE: Final = REPOSITORY_ROOT / "README.md"

NO_CONTACT_USER_AGENT: Final = (
    "not computed yet — set a contact email in Settings before crawling"
)


def build_pipeline() -> ExtractionPipeline:
    """Assemble the extraction layers, highest authority first (SPEC 8.2)."""
    return ExtractionPipeline(
        [
            JsonLdExtractor(),
            MicrodataExtractor(),
            SemanticHtmlExtractor(),
            TechnologyExtractor(),
            TextHeuristicExtractor(),
            DeobfuscatedTextExtractor(),
        ]
    )


def build_validation_policy() -> ValidationPolicy:
    """One validator per field. A value with no validator can never be exported."""
    return ValidationPolicy(
        {
            FieldName.EMAIL: EmailValidator(),
            FieldName.PHONE: PhoneValidator(),
            FieldName.POSTAL_ADDRESS: PostalAddressValidator(),
            FieldName.PERSON_NAME: PersonNameValidator(),
            FieldName.ORGANIZATION_NAME: OrganizationValidator(),
            FieldName.SOCIAL_PROFILE: SocialProfileValidator(),
            FieldName.PGP_KEY_URL: PgpKeyUrlValidator(),
            FieldName.COMPANY_IDENTIFIER: CompanyIdentifierValidator(),
            FieldName.TECHNOLOGY: TechnologyValidator(),
        }
    )


def build_writers() -> tuple[ResultWriter, ...]:
    """Every writer the export dialog can select. JSON is never optional."""
    return (
        JsonReportWriter(),
        CsvReportWriter(),
        XlsxReportWriter(),
        JsonlReportWriter(),
        MarkdownReportWriter(),
    )


def user_agent_for(config: AppConfig) -> str:
    """The honest User-Agent this configuration would send, or a stand-in.

    Nothing here can produce a browser token: ``build_user_agent`` refuses one,
    and no control anywhere in the interface feeds it an arbitrary string.
    """
    if not config.contact_email:
        return NO_CONTACT_USER_AGENT
    return build_user_agent(PRODUCT_TOKEN, __version__, config.project_url, config.contact_email)


def default_form_state(config: AppConfig) -> CrawlFormState:
    """The Crawl pane's opening values, taken from the configuration file."""
    return CrawlFormState(
        purpose_category=config.purpose_category,
        purpose_note=config.purpose_note,
        max_pages=config.max_pages,
        max_depth=config.max_depth,
        request_interval_seconds=config.request_interval_seconds,
        concurrent_requests=config.concurrent_requests,
        include_subdomains=config.include_subdomains,
        follow_sitemap=config.follow_sitemap,
        phone_region=config.phone_region,
        retention_days=config.retention_days,
        contact_email=config.contact_email,
    )


class CrawlUseCaseBuilder:
    """Builds one crawl use case per run, from collaborators fixed at startup.

    This is the composition root's arm inside the worker thread. It is a class
    rather than a closure only so that its dependencies are visible in one place
    and testable by substitution.
    """

    def __init__(
        self,
        config: AppConfig,
        pipeline: ExtractionPipeline,
        validation: ValidationPolicy,
        user_agent: str,
    ) -> None:
        self._config = config
        self._pipeline = pipeline
        self._validation = validation
        self._user_agent = user_agent

    def __call__(
        self,
        *,
        request: CrawlRequest,
        observer: CrawlObserver,
        cancellation: CancellationToken,
    ) -> CrawlSiteUseCase:
        """Wire one run. Every HTTP object is per-run, because the scope is."""
        clock = SystemClock()
        session = build_session(self._user_agent, self._config.max_retries)
        robots_policy = RobotsTxtPolicy(
            RequestsRobotsTransport(session, self._config.timeout_seconds), clock
        )
        rate_limiter = PerHostRateLimiter(SystemMonotonicClock(), SystemSleeper())
        policy = FetchPolicy(
            product_token=PRODUCT_TOKEN,
            configured_interval_seconds=request.settings.request_interval_seconds,
            timeout_seconds=self._config.timeout_seconds,
            max_pages=request.settings.max_pages,
            scope=request.target.scope,
        )
        fetcher = RequestsPageFetcher(
            session=session,
            robots_policy=robots_policy,
            rate_limiter=rate_limiter,
            clock=clock,
            policy=policy,
        )
        return CrawlSiteUseCase(
            fetcher=fetcher,
            pipeline=self._pipeline,
            validation=self._validation,
            link_extractor=HtmlLinkExtractor(),
            sitemap_reader=BeautifulSoupSitemapReader(),
            security_txt_reader=RfcSecurityTxtReader(),
            clock=clock,
            sleeper=SystemSleeper(),
            id_generator=UuidRunIdGenerator(),
            observer=observer,
            cancellation=cancellation,
            tool_name=TOOL_NAME,
            tool_version=__version__,
            user_agent=self._user_agent,
        )


def build_main_window(config: AppConfig, settings: QSettings) -> MainWindow:
    """Construct every adapter, every use case and every pane, exactly once."""
    output_directory = config.output_directory
    user_agent = user_agent_for(config)

    clock = SystemClock()
    ledger = JsonlRunLedger(output_directory)
    remover = FilesystemDirectoryRemover()
    exporter = ExportRunUseCase(
        writers=build_writers(), ledger=ledger, loader=JsonReportLoader()
    )
    list_runs = ListRunsUseCase(ledger, remover, clock)
    erase_runs = EraseRunsUseCase(ledger, remover, clock)

    controller = CrawlController(
        CrawlUseCaseBuilder(config, build_pipeline(), build_validation_policy(), user_agent)
    )
    selection = ExportSelection.from_names(config.formats)

    crawl_pane = CrawlPane(
        controller=controller,
        defaults=default_form_state(config),
        user_agent=user_agent,
        hard_floor_seconds=HARD_FLOOR_SECONDS,
    )

    def export_job_for_report(report: SiteReport) -> ExportJob:
        return ExportJob(
            run_id=report.run_id,
            default_directory=output_directory / report.run_id,
            run=lambda formats, copy_to: exporter.execute(
                report, formats, output_directory, copy_to
            ),
        )

    def export_job_for_row(row: RunRow) -> ExportJob:
        return ExportJob(
            run_id=row.run_id,
            default_directory=Path(row.directory),
            run=lambda formats, copy_to: exporter.re_export(
                row.run_id, formats, output_directory, copy_to
            ),
        )

    runs_pane = RunsPane(list_runs, erase_runs, export_job_for_row, selection)
    settings_pane = SettingsPane(
        config=config,
        save_config=save_config,
        writable_config_path=writable_config_path,
        user_agent_for=lambda project_url, contact: build_user_agent(
            PRODUCT_TOKEN, __version__, project_url, contact
        ),
    )

    return MainWindow(
        crawl_pane=crawl_pane,
        runs_pane=runs_pane,
        settings_pane=settings_pane,
        crawl_controller=controller,
        export_job_for_report=export_job_for_report,
        user_agent_for=user_agent_for,
        default_selection=selection,
        output_directory=output_directory,
        tool_name=TOOL_NAME,
        version=__version__,
        licenses_path=LICENSES_FILE,
        readme_path=README_FILE,
        settings=settings,
    )


def run(argv: Sequence[str], config_path: Path | None) -> int:
    """Start the graphical application and return the process exit code."""
    application = QApplication(list(argv))
    application.setApplicationName(TOOL_NAME)
    application.setApplicationVersion(__version__)
    application.setOrganizationName(ORGANIZATION_NAME)

    config = load_config(config_path)
    settings = QSettings(ORGANIZATION_NAME, TOOL_NAME)
    window = build_main_window(config, settings)

    application.aboutToQuit.connect(window.save_layout)
    application.aboutToQuit.connect(window.shutdown_crawl)
    application.aboutToQuit.connect(drain_background_tasks)
    window.show()
    return int(application.exec())
