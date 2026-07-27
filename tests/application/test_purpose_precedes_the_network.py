"""AC-UI-2: nothing reaches the wire before the purpose validates.

FR-9 makes a stated purpose the precondition of a crawl, and SPEC 7.2.2 is
explicit that *no* HTTP request — "not even ``robots.txt``" — may precede it.
That guarantee had no test. It is worth one even though it holds structurally,
because the way it holds is easy to delete by accident: a :class:`Purpose` is
validated in ``__post_init__``, so an invalid one cannot be constructed and can
therefore never be handed to ``CrawlSiteUseCase.execute``. Move that check into
a factory, or add a second construction path that skips it, and the guarantee
evaporates with no other test noticing.

The counting session below is the real one used everywhere else in the suite:
it records every URL requested, ``robots.txt`` included.
"""

from __future__ import annotations

import pytest

from osint_scrapper.domain.errors import InvalidPurposeError
from osint_scrapper.domain.target import (
    MINIMUM_PURPOSE_NOTE_LENGTH,
    CrawlSettings,
    Purpose,
    PurposeCategory,
    resolve_target,
)
from tests.conftest import FakeHttpSession, RecordingObserver
from tests.site_fixture import ORIGIN, site_routes
from tests.wiring import build_crawl, build_fetcher, crawl_clocks

TOO_SHORT = "x" * (MINIMUM_PURPOSE_NOTE_LENGTH - 1)


def test_the_minimum_note_length_is_the_value_the_spec_names() -> None:
    """SPEC 7.2.2 fixes the guard at 16 characters."""
    assert MINIMUM_PURPOSE_NOTE_LENGTH == 16


@pytest.mark.parametrize(
    "note",
    [
        pytest.param("", id="empty"),
        pytest.param("   ", id="whitespace only"),
        pytest.param(TOO_SHORT, id="one character short"),
        pytest.param(f"  {TOO_SHORT}  ", id="padded to length with whitespace"),
    ],
)
def test_an_unexplained_other_purpose_cannot_be_constructed(note: str) -> None:
    """The note is measured after stripping, so padding cannot buy length."""
    with pytest.raises(InvalidPurposeError):
        Purpose(category=PurposeCategory.OTHER, note=note)


def test_an_invalid_purpose_leaves_the_network_completely_untouched() -> None:
    """AC-UI-2 with a counting session: zero requests, robots.txt included.

    The crawl is assembled exactly as ``interfaces/app.py`` assembles it and is
    driven right up to the purpose. Because the purpose refuses to exist,
    ``execute`` is never reached and the session records nothing at all — which
    is the only observation that distinguishes "validated first" from
    "validated somewhere along the way".
    """
    session = FakeHttpSession(site_routes())
    target = resolve_target(ORIGIN, include_subdomains=True)
    clock, sleeper = crawl_clocks()
    fetcher = build_fetcher(session, target, clock, sleeper)
    use_case = build_crawl(fetcher, RecordingObserver(), clock, sleeper)

    with pytest.raises(InvalidPurposeError):
        use_case.execute(
            target,
            CrawlSettings(),
            Purpose(category=PurposeCategory.OTHER, note=TOO_SHORT),
        )

    assert session.requested == []
    assert fetcher.requests_made == 0


def test_a_valid_purpose_lets_the_same_crawl_proceed() -> None:
    """The negative half: the assembly above is otherwise ready to run.

    Without this, the assertion above would also pass if the chain were simply
    broken, which is the failure mode a "nothing happened" test invites.
    """
    session = FakeHttpSession(site_routes())
    target = resolve_target(ORIGIN, include_subdomains=True)
    clock, sleeper = crawl_clocks()
    fetcher = build_fetcher(session, target, clock, sleeper)
    use_case = build_crawl(fetcher, RecordingObserver(), clock, sleeper)

    use_case.execute(
        target, CrawlSettings(), Purpose(category=PurposeCategory.DUE_DILIGENCE)
    )

    assert f"{ORIGIN}/robots.txt" in session.requested
    assert fetcher.requests_made > 0
