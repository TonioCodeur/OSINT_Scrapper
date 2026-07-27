"""Building the real chain for tests, with only the HTTP transport faked.

This mirrors what ``interfaces/app.py`` composes. Keeping it in one place is
what lets the end-to-end test use real collaborators everywhere and still be
readable (AC-E2E-1).
"""

from __future__ import annotations

from osint_scrapper import PRODUCT_TOKEN, TOOL_NAME, __version__
from osint_scrapper.application.crawl import CrawlSiteUseCase
from osint_scrapper.application.export import ExportRunUseCase
from osint_scrapper.application.ports import (
    CancellationToken,
    Clock,
    CrawlObserver,
    ResultWriter,
    RunLedger,
    Sleeper,
)
from osint_scrapper.application.validation import ValidationPolicy
from osint_scrapper.domain.attributes import FieldName
from osint_scrapper.domain.target import CrawlTarget
from osint_scrapper.infrastructure.discovery.links import HtmlLinkExtractor
from osint_scrapper.infrastructure.discovery.security_txt import RfcSecurityTxtReader
from osint_scrapper.infrastructure.discovery.sitemap import BeautifulSoupSitemapReader
from osint_scrapper.infrastructure.extraction.jsonld import JsonLdExtractor
from osint_scrapper.infrastructure.extraction.microdata import MicrodataExtractor
from osint_scrapper.infrastructure.extraction.pipeline import ExtractionPipeline, PageExtractor
from osint_scrapper.infrastructure.extraction.semantic_html import SemanticHtmlExtractor
from osint_scrapper.infrastructure.extraction.technology import TechnologyExtractor
from osint_scrapper.infrastructure.extraction.text_heuristics import (
    DeobfuscatedTextExtractor,
    TextHeuristicExtractor,
)
from osint_scrapper.infrastructure.http.rate_limit import PerHostRateLimiter
from osint_scrapper.infrastructure.http.requests_fetcher import (
    FetchPolicy,
    RequestsPageFetcher,
    RequestsRobotsTransport,
)
from osint_scrapper.infrastructure.http.robots import RobotsTxtPolicy
from osint_scrapper.infrastructure.http.user_agent import build_user_agent
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
from tests.conftest import (
    FakeClock,
    FakeIdGenerator,
    FakeMonotonicClock,
    FakeSleeper,
    FrozenClock,
    NeverCancelled,
)

USER_AGENT = build_user_agent(PRODUCT_TOKEN, __version__, "https://example.org/tool", "a@b.example")


def build_validation_policy() -> ValidationPolicy:
    """Every field validator this product ships, keyed by field."""
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


def build_pipeline() -> ExtractionPipeline:
    """The five extraction layers, in precedence order."""
    extractors: list[PageExtractor] = [
        JsonLdExtractor(),
        MicrodataExtractor(),
        SemanticHtmlExtractor(),
        TechnologyExtractor(),
        TextHeuristicExtractor(),
        DeobfuscatedTextExtractor(),
    ]
    return ExtractionPipeline(extractors)


def build_writers() -> tuple[ResultWriter, ...]:
    """Every export writer, JSON first."""
    return (
        JsonReportWriter(),
        CsvReportWriter(),
        XlsxReportWriter(),
        JsonlReportWriter(),
        MarkdownReportWriter(),
    )


def build_fetcher(
    session: object,
    target: CrawlTarget,
    clock: Clock,
    sleeper: Sleeper,
    max_pages: int = 200,
    interval_seconds: float = 1.0,
) -> RequestsPageFetcher:
    """The real fetcher, with the real robots policy and the real rate limiter.

    The limiter gets its own sleeper and its own monotonic clock so that the
    crawl's sleeper records only what the crawl itself decided to wait for. The
    limiter's own behaviour is asserted directly in its unit test (AC-NET-4).
    """
    del sleeper
    transport = RequestsRobotsTransport(session)  # type: ignore[arg-type]
    monotonic = FakeMonotonicClock()
    return RequestsPageFetcher(
        session=session,  # type: ignore[arg-type]
        robots_policy=RobotsTxtPolicy(transport, clock),
        rate_limiter=PerHostRateLimiter(monotonic, FakeSleeper(monotonic)),
        clock=clock,
        policy=FetchPolicy(
            product_token=PRODUCT_TOKEN,
            configured_interval_seconds=interval_seconds,
            max_pages=max_pages,
            scope=target.scope,
        ),
    )


def build_crawl(
    fetcher: RequestsPageFetcher,
    observer: CrawlObserver,
    clock: Clock,
    sleeper: Sleeper,
    cancellation: CancellationToken | None = None,
    run_id: str = "r-testrun1",
) -> CrawlSiteUseCase:
    """The real use case, with every real collaborator."""
    return CrawlSiteUseCase(
        fetcher=fetcher,
        pipeline=build_pipeline(),
        validation=build_validation_policy(),
        link_extractor=HtmlLinkExtractor(),
        sitemap_reader=BeautifulSoupSitemapReader(),
        security_txt_reader=RfcSecurityTxtReader(),
        clock=clock,
        sleeper=sleeper,
        id_generator=FakeIdGenerator(run_id),
        observer=observer,
        cancellation=cancellation or NeverCancelled(),
        tool_name=TOOL_NAME,
        tool_version=__version__,
        user_agent=USER_AGENT,
        jitter=lambda: 0.0,
    )


def build_exporter(ledger: RunLedger) -> ExportRunUseCase:
    """The real export use case with every writer and the real loader."""
    return ExportRunUseCase(build_writers(), ledger, JsonReportLoader())


def crawl_clocks(frozen: bool = False) -> tuple[Clock, FakeSleeper]:
    """A clock and a sleeper for a crawl; frozen when timestamps must not drift."""
    clock: Clock = FrozenClock() if frozen else FakeClock()
    return clock, FakeSleeper()
