"""AC-NET-4 and AC-NET-5: the interval floor, and the ban on impersonation."""

from __future__ import annotations

import ast
import re
import threading
from pathlib import Path

import pytest

from osint_scrapper import PRODUCT_TOKEN, __version__
from osint_scrapper.infrastructure.http.rate_limit import (
    HARD_FLOOR_SECONDS,
    PerHostRateLimiter,
    effective_interval,
)
from osint_scrapper.infrastructure.http.user_agent import (
    BROWSER_TOKENS,
    DishonestUserAgentError,
    assert_honest,
    build_user_agent,
)
from tests.conftest import FakeMonotonicClock, FakeSleeper

HOST = "example.com"


def test_the_interval_is_a_floor_over_every_candidate() -> None:
    """SPEC FR-11: nothing lowers it, and the largest candidate always wins."""
    assert effective_interval(1.0, 5.0, None) == 5.0
    assert effective_interval(None, None) == HARD_FLOOR_SECONDS


def test_a_configured_interval_below_the_hard_floor_is_raised_to_it() -> None:
    """AC-NET-4: the hard floor is a permanent candidate of every computation."""
    assert effective_interval(0.1) == HARD_FLOOR_SECONDS
    assert HARD_FLOOR_SECONDS == 0.5


def test_a_host_crawl_delay_overrides_the_configured_interval() -> None:
    """AC-NET-4: a host asking for 5 s gets 5 s whatever the operator set."""
    assert effective_interval(1.0, 5.0) == 5.0


def test_two_requests_are_separated_by_at_least_the_interval() -> None:
    """AC-NET-4, with a fake clock and a fake sleeper: the test never really sleeps."""
    clock = FakeMonotonicClock()
    sleeper = FakeSleeper(clock)
    limiter = PerHostRateLimiter(clock, sleeper)
    limiter.acquire(HOST, 1.0)
    limiter.acquire(HOST, 1.0)
    assert sleeper.slept == [1.0]


def test_a_different_host_is_not_throttled_by_another_hosts_start() -> None:
    clock = FakeMonotonicClock()
    sleeper = FakeSleeper(clock)
    limiter = PerHostRateLimiter(clock, sleeper)
    limiter.acquire(HOST, 1.0)
    limiter.acquire("other.example", 1.0)
    assert sleeper.slept == []


def test_the_limiter_is_shared_safely_by_concurrent_workers() -> None:
    """AC-NET-4: the combined rate never exceeds one start per interval."""
    clock = FakeMonotonicClock()
    sleeper = FakeSleeper(clock)
    limiter = PerHostRateLimiter(clock, sleeper)
    workers = [threading.Thread(target=limiter.acquire, args=(HOST, 1.0)) for _ in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert len(sleeper.slept) == 3, "three of the four starts must have been spaced"
    assert sum(sleeper.slept) >= 3.0


def test_the_user_agent_carries_everything_an_operator_can_be_reached_through() -> None:
    """AC-NET-5."""
    agent = build_user_agent(PRODUCT_TOKEN, __version__, "https://example.org/x", "a@b.example")
    assert PRODUCT_TOKEN in agent
    assert __version__ in agent
    assert "https://example.org/x" in agent
    assert "a@b.example" in agent


@pytest.mark.parametrize("token", BROWSER_TOKENS)
def test_every_browser_token_is_refused(token: str) -> None:
    """AC-NET-5: this tool identifies itself honestly and does not defeat detection."""
    with pytest.raises(DishonestUserAgentError):
        assert_honest(f"Something/{token}/1.0")
    with pytest.raises(DishonestUserAgentError):
        build_user_agent(token.lower(), "1", "https://example.org", "a@b.example")


def test_no_configuration_surface_can_set_a_user_agent() -> None:
    """AC-NET-5: there is exactly one way to build one, and it refuses browsers.

    Every string literal in the configuration module is scanned, not only the
    ones bound to a name starting with ``ENV_``: renaming the constant must not
    be enough to reintroduce an environment variable that sets a User-Agent.
    """
    from osint_scrapper.infrastructure import config

    fields = set(config.AppConfig.__dataclass_fields__)
    assert not {name for name in fields if "user_agent" in name or "useragent" in name}

    source = Path(config.__file__).read_text(encoding="utf-8")
    literals = {
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    variable_names = {text for text in literals if re.fullmatch(r"[A-Z][A-Z0-9_]*", text)}
    assert variable_names, "the scan must actually see the module's constants"
    assert not {
        text for text in variable_names if "USER_AGENT" in text or "USERAGENT" in text
    }, "no environment variable may set a User-Agent"
