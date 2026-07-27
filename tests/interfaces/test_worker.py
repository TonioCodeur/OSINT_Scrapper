"""The threading contract: batching, cancellation, and a live event loop.

The fake use case here is deliberately hostile — it blocks, it spins, it raises
— because those are the three things the worker has to survive without either
freezing the interface or losing the report.
"""

from __future__ import annotations

import threading
import time

import pytest
from PySide6.QtCore import QObject, QTimer

from osint_scrapper.domain.crawl import CrawlOutcome, PageStatus
from osint_scrapper.domain.errors import SeedRefusedError
from osint_scrapper.domain.target import CrawlSettings, Purpose, PurposeCategory
from osint_scrapper.interfaces.worker import (
    PAGE_BATCH_SIZE,
    CrawlRequest,
    QtCancellationToken,
    QtCrawlObserver,
    run_in_background,
)
from tests.interfaces.conftest import make_finding, make_page, make_report, make_target

REQUEST = CrawlRequest(
    target=make_target(),
    settings=CrawlSettings(max_pages=10),
    purpose=Purpose(category=PurposeCategory.SELF_AUDIT, note=""),
)


class FakeUseCase:
    """Stands in for ``CrawlSiteUseCase`` without touching a network or a file."""

    def __init__(self, observer, cancellation, behaviour="complete", gate=None) -> None:
        self.observer = observer
        self.cancellation = cancellation
        self.behaviour = behaviour
        self.gate = gate

    def execute(self, target, settings, purpose):
        self.observer.crawl_started(target, settings)
        if self.behaviour == "raise":
            raise ValueError("a defect, not a page failure")
        if self.behaviour == "refuse":
            raise SeedRefusedError(
                url="https://example.com/",
                reason="robots_disallow",
                detail="the target itself is disallowed",
                robots_url="https://example.com/robots.txt",
            )
        if self.behaviour == "block" and self.gate is not None:
            self.gate.wait(timeout=10)
        if self.behaviour == "spin":
            while not self.cancellation.is_cancelled():
                time.sleep(0.005)
            report = make_report(outcome=CrawlOutcome.STOPPED_BY_OPERATOR)
            self.observer.crawl_finished(report)
            return report

        self.observer.page_finished(make_page())
        self.observer.frontier_changed(3, 1)
        self.observer.findings_updated((make_finding(),))
        report = make_report()
        self.observer.crawl_finished(report)
        return report


def factory_for(behaviour: str = "complete", gate: threading.Event | None = None):
    """A ``CrawlUseCaseFactory`` that builds the fake above."""

    def build(*, request, observer, cancellation):
        del request
        return FakeUseCase(observer, cancellation, behaviour, gate)

    return build


# ------------------------------------------------------------- cancellation


def test_the_token_starts_uncancelled_and_stays_cancelled() -> None:
    token = QtCancellationToken()
    assert not token.is_cancelled()
    token.cancel()
    assert token.is_cancelled()
    assert token.is_cancelled()


def test_the_token_can_be_set_from_another_thread() -> None:
    token = QtCancellationToken()
    thread = threading.Thread(target=token.cancel)
    thread.start()
    thread.join()
    assert token.is_cancelled()


# ----------------------------------------------------------------- batching


class Recorder(QObject):
    """Counts how many times each signal fired, and with what."""

    def __init__(self, observer: QtCrawlObserver) -> None:
        super().__init__()
        self.page_signals: list[tuple] = []
        self.finding_signals: list[tuple] = []
        observer.pages_batched.connect(self.page_signals.append)
        observer.findings_snapshot.connect(self.finding_signals.append)


def test_page_outcomes_are_batched_rather_than_signalled_one_by_one(qapp) -> None:
    observer = QtCrawlObserver()
    recorder = Recorder(observer)
    for index in range(PAGE_BATCH_SIZE):
        observer.page_finished(make_page(url=f"https://example.com/{index}"))

    assert len(recorder.page_signals) == 1
    assert len(recorder.page_signals[0]) == PAGE_BATCH_SIZE


def test_five_hundred_pages_do_not_produce_five_hundred_signals(qapp) -> None:
    observer = QtCrawlObserver()
    recorder = Recorder(observer)
    for index in range(500):
        observer.page_finished(make_page(url=f"https://example.com/{index}"))

    assert len(recorder.page_signals) < 50
    delivered = sum(len(batch) for batch in recorder.page_signals)
    assert delivered >= 500 - PAGE_BATCH_SIZE


def test_the_remainder_of_a_batch_is_flushed_before_the_run_is_announced(qapp) -> None:
    observer = QtCrawlObserver()
    recorder = Recorder(observer)
    finished: list[object] = []
    observer.run_finished.connect(finished.append)

    observer.page_finished(make_page())
    observer.crawl_finished(make_report())

    assert sum(len(batch) for batch in recorder.page_signals) == 1
    assert len(finished) == 1


def test_findings_snapshots_are_throttled_and_the_last_one_always_arrives(qapp) -> None:
    observer = QtCrawlObserver()
    recorder = Recorder(observer)
    for support in range(1, 40):
        observer.findings_updated((make_finding(page_support=support),))
    observer.crawl_finished(make_report())

    assert len(recorder.finding_signals) <= 3
    assert recorder.finding_signals[-1][0].page_support == 39


# ---------------------------------------------------------------- the run


def test_a_completed_run_delivers_every_signal_and_the_report(qtbot, controllers) -> None:
    controller = controllers(factory_for())
    pages: list[tuple] = []
    findings: list[tuple] = []
    frontier: list[tuple[int, int]] = []
    controller.pages_batched.connect(pages.append)
    controller.findings_snapshot.connect(findings.append)
    controller.frontier_sized.connect(lambda q, d: frontier.append((q, d)))

    with qtbot.waitSignal(controller.finished, timeout=5000) as caught:
        controller.start(REQUEST)

    assert caught.args[0].outcome is CrawlOutcome.COMPLETED
    assert pages and pages[0][0].status is PageStatus.OK
    assert findings and findings[0][0].value == "contact@example.com"
    assert frontier == [(3, 1)]


def test_a_seed_refusal_is_reported_as_a_refusal_and_not_as_a_crash(qtbot, controllers) -> None:
    controller = controllers(factory_for("refuse"))
    with qtbot.waitSignal(controller.refused, timeout=5000) as caught:
        controller.start(REQUEST)
    refusal = caught.args[0]
    assert isinstance(refusal, SeedRefusedError)
    assert refusal.reason == "robots_disallow"


def test_an_unexpected_exception_reaches_the_gui_thread_instead_of_vanishing(
    qtbot, controllers
) -> None:
    controller = controllers(factory_for("raise"))
    with qtbot.waitSignal(controller.failed, timeout=5000) as caught:
        controller.start(REQUEST)
    assert isinstance(caught.args[0], ValueError)


def test_stop_ends_a_running_crawl_promptly_and_keeps_the_report(qtbot, controllers) -> None:
    controller = controllers(factory_for("spin"))
    with qtbot.waitSignal(controller.run_started, timeout=5000):
        controller.start(REQUEST)

    started = time.monotonic()
    with qtbot.waitSignal(controller.finished, timeout=5000) as caught:
        controller.stop()
    elapsed = time.monotonic() - started

    assert caught.args[0].outcome is CrawlOutcome.STOPPED_BY_OPERATOR
    assert elapsed < 2.0


def test_the_event_loop_keeps_running_while_a_crawl_blocks(qtbot, controllers) -> None:
    """AC-UI-1: a blocked crawl must not block the GUI thread.

    The counter is driven by a ``QTimer``, so it can only advance if the event
    loop is still delivering events while the use case sits on its gate. A
    counter the test increments itself would advance even from a frozen loop.
    """
    gate = threading.Event()
    controller = controllers(factory_for("block", gate))
    with qtbot.waitSignal(controller.run_started, timeout=5000):
        controller.start(REQUEST)

    ticks: list[int] = []
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(len(ticks)))
    timer.start()
    try:
        qtbot.waitUntil(lambda: len(ticks) >= 5, timeout=5000)
    finally:
        timer.stop()
    assert controller.is_running(), "the crawl must still be blocked on its gate"

    with qtbot.waitSignal(controller.finished, timeout=5000):
        gate.set()


def test_the_crawl_does_not_run_on_the_gui_thread(qtbot, controllers) -> None:
    seen: list[int] = []
    gui_thread = threading.get_ident()

    def build(*, request, observer, cancellation):
        del request
        return _ThreadReporting(observer, cancellation, seen)

    controller = controllers(build)
    with qtbot.waitSignal(controller.finished, timeout=5000):
        controller.start(REQUEST)

    assert seen and seen[0] != gui_thread


class _ThreadReporting:
    def __init__(self, observer, cancellation, seen) -> None:
        self.observer = observer
        self.cancellation = cancellation
        self.seen = seen

    def execute(self, target, settings, purpose):
        self.seen.append(threading.get_ident())
        report = make_report()
        self.observer.crawl_finished(report)
        return report


def test_starting_twice_is_a_defect_and_says_so(qtbot, controllers) -> None:
    gate = threading.Event()
    controller = controllers(factory_for("block", gate))
    with qtbot.waitSignal(controller.run_started, timeout=5000):
        controller.start(REQUEST)
    with pytest.raises(RuntimeError):
        controller.start(REQUEST)
    with qtbot.waitSignal(controller.finished, timeout=5000):
        gate.set()


def test_shutdown_cancels_and_joins_without_terminating_the_thread(qtbot, controllers) -> None:
    controller = controllers(factory_for("spin"))
    with qtbot.waitSignal(controller.run_started, timeout=5000):
        controller.start(REQUEST)
    controller.shutdown()
    assert not controller.is_running()


# -------------------------------------------------------- background tasks


def test_a_background_task_delivers_its_result_to_the_gui_thread(qtbot) -> None:
    owner = QObject()
    results: list[object] = []
    signals = run_in_background(owner, lambda: 21 * 2, results.append, results.append)
    qtbot.waitUntil(lambda: bool(results), timeout=5000)
    assert results == [42]
    assert signals.parent() is owner


def test_a_background_task_reports_its_failure_rather_than_dying_quietly(qtbot) -> None:
    owner = QObject()
    failures: list[BaseException] = []

    def explode() -> None:
        raise OSError("the directory is not writable")

    run_in_background(owner, explode, lambda _: None, failures.append)
    qtbot.waitUntil(lambda: bool(failures), timeout=5000)
    assert isinstance(failures[0], OSError)
