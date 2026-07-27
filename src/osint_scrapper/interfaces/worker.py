"""Everything that keeps work off the GUI thread (SPEC 7.6).

Three pieces, and the reasoning behind each:

* :class:`QtCancellationToken` implements the ``CancellationToken`` port with a
  :class:`threading.Event`. Setting it is a memory write from the GUI thread;
  the crawl reads it between fetches. ``QThread.terminate`` is never used and
  never will be — it can strand a half-written file and would destroy the
  guarantee of FR-8 that a stopped run is still a consistent, exportable one.
* :class:`QtCrawlObserver` implements the ``CrawlObserver`` port and turns its
  calls into Qt signals. It **batches**: page outcomes are held until 25 have
  accumulated or 100 ms have passed, findings snapshots until 250 ms have
  passed. A crawl that skips two thousand URLs therefore repaints the log a few
  dozen times, not two thousand (NFR-11).
* :class:`CrawlController` owns the ``QThread``. The crawl itself is built by a
  factory handed down from the composition root, so this module constructs no
  adapter and knows no concrete type.

Cross-thread traffic is signals only. No widget is touched from the worker
thread, and nothing in this module imports a widget.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event
from time import monotonic
from typing import Any, Final, Protocol

from PySide6.QtCore import (
    QObject,
    QRunnable,
    QThread,
    QThreadPool,
    Signal,
    SignalInstance,
    Slot,
)
from shiboken6 import isValid

from osint_scrapper.application.crawl import CrawlSiteUseCase
from osint_scrapper.application.ports import CancellationToken, CrawlObserver
from osint_scrapper.domain.attributes import Finding
from osint_scrapper.domain.crawl import PageOutcome
from osint_scrapper.domain.errors import SeedRefusedError
from osint_scrapper.domain.report import SiteReport
from osint_scrapper.domain.target import CrawlSettings, CrawlTarget, Purpose

logger = logging.getLogger(__name__)

PAGE_BATCH_SIZE: Final = 25
"""How many page outcomes may accumulate before the log is updated."""

PAGE_FLUSH_SECONDS: Final = 0.1
"""How long a page outcome may wait before the log is updated anyway."""

FINDINGS_FLUSH_SECONDS: Final = 0.25
"""How often the findings table may be refreshed while a crawl runs."""

THREAD_SHUTDOWN_MILLISECONDS: Final = 30_000
"""How long the application waits for a worker thread at quit before giving up."""


class QtCancellationToken:
    """A cooperative cancellation flag, safe to set from any thread."""

    def __init__(self) -> None:
        self._cancelled = Event()

    def cancel(self) -> None:
        """Ask the crawl to stop. Returns immediately; the crawl drains itself."""
        self._cancelled.set()

    def is_cancelled(self) -> bool:
        """Whether the operator has pressed Stop."""
        return self._cancelled.is_set()


@dataclass(frozen=True)
class CrawlRequest:
    """One operator instruction, already validated by the domain."""

    target: CrawlTarget
    settings: CrawlSettings
    purpose: Purpose


class CrawlUseCaseFactory(Protocol):
    """Builds one crawl use case per run.

    The use case holds per-run state and its fetcher is scoped to one target, so
    a fresh one is built for every run. The factory itself is created once, in
    ``interfaces/app.py``, which is what keeps the composition root single even
    though the construction happens later.
    """

    def __call__(
        self,
        *,
        request: CrawlRequest,
        observer: CrawlObserver,
        cancellation: CancellationToken,
    ) -> CrawlSiteUseCase:
        """Return a use case wired for this run."""
        ...


class QtCrawlObserver(QObject):
    """The ``CrawlObserver`` port, implemented as batched Qt signals."""

    run_started = Signal(object, object)
    """``(CrawlTarget, CrawlSettings)`` — emitted once, before the first request."""

    pages_batched = Signal(object)
    """``tuple[PageOutcome, ...]`` — one batch of page log rows."""

    findings_snapshot = Signal(object)
    """``tuple[Finding, ...]`` — the current snapshot of every finding."""

    frontier_sized = Signal(int, int)
    """``(queued, deepest_depth)`` — the frontier size behind the progress label."""

    run_finished = Signal(object)
    """``SiteReport`` — emitted once, after every batch has been flushed."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pending: list[PageOutcome] = []
        self._pending_findings: tuple[Finding, ...] | None = None
        self._last_page_flush = monotonic()
        self._last_findings_flush = monotonic()

    def crawl_started(self, target: CrawlTarget, settings: CrawlSettings) -> None:
        """Announce the run that is about to begin."""
        self._last_page_flush = monotonic()
        self._last_findings_flush = monotonic()
        self.run_started.emit(target, settings)

    def page_finished(self, outcome: PageOutcome) -> None:
        """Buffer one page outcome, flushing when the batch is due."""
        self._pending.append(outcome)
        due = monotonic() - self._last_page_flush >= PAGE_FLUSH_SECONDS
        if len(self._pending) >= PAGE_BATCH_SIZE or due:
            self._flush_pages()

    def findings_updated(self, findings: tuple[Finding, ...]) -> None:
        """Buffer the latest findings snapshot, flushing at most four times a second."""
        self._pending_findings = findings
        if monotonic() - self._last_findings_flush >= FINDINGS_FLUSH_SECONDS:
            self._flush_findings()

    def frontier_changed(self, queued: int, deepest_depth: int) -> None:
        """Report the frontier size, which no other call carries."""
        self.frontier_sized.emit(queued, deepest_depth)

    def crawl_finished(self, report: SiteReport) -> None:
        """Flush everything still buffered, then announce the finished run."""
        self._flush_pages()
        self._flush_findings()
        self.run_finished.emit(report)

    def _flush_pages(self) -> None:
        self._last_page_flush = monotonic()
        if not self._pending:
            return
        batch = tuple(self._pending)
        self._pending.clear()
        self.pages_batched.emit(batch)

    def _flush_findings(self) -> None:
        self._last_findings_flush = monotonic()
        if self._pending_findings is None:
            return
        findings = self._pending_findings
        self._pending_findings = None
        self.findings_snapshot.emit(findings)


class CrawlWorker(QObject):
    """Runs one crawl on a worker thread and reports how it ended."""

    finished = Signal(object)
    """``SiteReport`` — every terminal outcome, including the four aborts."""

    refused = Signal(object)
    """``SeedRefusedError`` — the run never started, so nothing was written."""

    failed = Signal(object)
    """``BaseException`` — a defect. It becomes the only unsolicited modal (SPEC 7.5)."""

    def __init__(
        self,
        factory: CrawlUseCaseFactory,
        request: CrawlRequest,
        observer: QtCrawlObserver,
        cancellation: CancellationToken,
    ) -> None:
        super().__init__(None)
        self._factory = factory
        self._request = request
        self._observer = observer
        self._cancellation = cancellation

    @Slot()
    def run(self) -> None:
        """Build the use case and execute it. Called on the worker thread only."""
        try:
            use_case = self._factory(
                request=self._request,
                observer=self._observer,
                cancellation=self._cancellation,
            )
            report = use_case.execute(
                self._request.target, self._request.settings, self._request.purpose
            )
        except SeedRefusedError as refusal:
            logger.info("seed refused: %s", refusal)
            self.refused.emit(refusal)
        except Exception as failure:  # noqa: BLE001
            # A worker thread that lets an exception escape dies silently and the
            # interface waits forever. SPEC 7.5 tier 3 requires the opposite: the
            # defect must reach the GUI thread and be loud. The type is preserved
            # and shown; nothing is swallowed.
            logger.exception("crawl failed with an unexpected error")
            self.failed.emit(failure)
        else:
            self.finished.emit(report)


class CrawlController(QObject):
    """Owns the worker thread and re-exports the worker's signals.

    Lives on the GUI thread. It is the only object that starts, stops and joins
    a thread, so no widget has to know a thread exists.
    """

    run_started = Signal(object, object)
    pages_batched = Signal(object)
    findings_snapshot = Signal(object)
    frontier_sized = Signal(int, int)
    finished = Signal(object)
    refused = Signal(object)
    failed = Signal(object)

    def __init__(self, factory: CrawlUseCaseFactory, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._factory = factory
        self._thread: QThread | None = None
        self._worker: CrawlWorker | None = None
        self._observer: QtCrawlObserver | None = None
        self._cancellation: QtCancellationToken | None = None
        self._running = False

    def is_running(self) -> bool:
        """Whether a crawl is in flight.

        Tracked as a flag rather than read off the thread: once the thread has
        been handed to ``deleteLater`` its wrapper may already be invalid, and
        a liveness check must not be the thing that raises.
        """
        return self._running

    def start(self, request: CrawlRequest) -> None:
        """Begin a crawl on a fresh worker thread.

        Raises:
            RuntimeError: a crawl is already running. The interface prevents this
                by disabling Start, so reaching it is a defect, not a user error.
        """
        if self.is_running():
            raise RuntimeError("a crawl is already running")

        # Parented to the controller on purpose: C++ ownership then belongs to
        # Qt, so dropping the Python attribute below can never destroy a thread
        # that is still emitting. Its lifetime ends at deleteLater, not at a
        # refcount.
        thread = QThread(self)
        thread.setObjectName("osint-crawl")
        observer = QtCrawlObserver()
        cancellation = QtCancellationToken()
        worker = CrawlWorker(self._factory, request, observer, cancellation)
        observer.moveToThread(thread)
        worker.moveToThread(thread)

        observer.run_started.connect(self.run_started)
        observer.pages_batched.connect(self.pages_batched)
        observer.findings_snapshot.connect(self.findings_snapshot)
        observer.frontier_sized.connect(self.frontier_sized)
        worker.finished.connect(self.finished)
        worker.refused.connect(self.refused)
        worker.failed.connect(self.failed)
        for signal in (worker.finished, worker.refused, worker.failed):
            signal.connect(self._retire)
        thread.started.connect(worker.run)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(observer.deleteLater)
        thread.finished.connect(self._on_thread_finished)

        self._thread = thread
        self._worker = worker
        self._observer = observer
        self._cancellation = cancellation
        self._running = True
        thread.start()

    def stop(self) -> None:
        """Ask the running crawl to stop. Returns at once; the crawl drains itself."""
        if self._cancellation is not None:
            self._cancellation.cancel()

    def shutdown(self) -> None:
        """Cancel and join the worker thread. Called once, when the window closes."""
        self.stop()
        thread = self._thread
        if thread is None:
            return
        thread.quit()
        if not thread.wait(THREAD_SHUTDOWN_MILLISECONDS):
            logger.warning("the crawl thread did not finish within the shutdown timeout")
        self._release()

    @Slot(object)
    def _retire(self, outcome: object) -> None:
        """Ask the thread's event loop to exit once the run has reported."""
        del outcome
        self._running = False
        if self._thread is not None:
            self._thread.quit()

    @Slot()
    def _on_thread_finished(self) -> None:
        """Release the thread and its passengers, once Qt has finished with them."""
        self._release()

    def _release(self) -> None:
        """Hand the finished thread back to Qt and forget it.

        Two lifetime rules are being obeyed here, and both were learned the
        hard way:

        * ``deleteLater`` rather than a dropped reference, because this runs
          from inside the thread's own ``finished`` signal and destroying an
          object while it is emitting is a use-after-free. The parent set in
          :meth:`start` keeps the C++ object alive until the deferred delete.
        * the worker and the observer are **not** dropped here. Qt is already
          deleting them through ``deleteLater`` as the thread winds down;
          releasing the Python reference in the same moment would race that
          deletion from the wrong thread. They are replaced on the next run,
          when nothing is in flight.
        """
        self._running = False
        self._cancellation = None
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.deleteLater()


class TaskSignals(QObject):
    """The result channel of one background task."""

    succeeded = Signal(object)
    failed = Signal(object)


class BackgroundTask(QRunnable):
    """One short-lived job run on the global thread pool.

    Exports, run listings, deletions and configuration writes all touch the
    filesystem. None of them would take long, and that is exactly why the 100 ms
    rule is stated as an absolute (SPEC 7.6): nobody should have to re-derive
    the threshold per feature.
    """

    def __init__(self, work: Callable[[], Any], signals: TaskSignals) -> None:
        super().__init__()
        self._work = work
        self._signals = signals

    def run(self) -> None:
        """Execute the job and report through the signals object."""
        try:
            result = self._work()
        except Exception as failure:  # noqa: BLE001
            # Same reasoning as CrawlWorker.run: a pool thread must not die
            # silently. The exception is handed to the GUI thread intact.
            logger.debug("background task failed", exc_info=failure)
            self._emit(self._signals.failed, failure)
        else:
            self._emit(self._signals.succeeded, result)

    def _emit(self, signal: SignalInstance, payload: Any) -> None:
        """Deliver a result, unless the widget that asked for it is gone.

        A pane can be closed while its export or its ledger read is still in
        flight. Emitting into a destroyed receiver raises from inside a pool
        thread, where nothing can handle it; there is nobody left to tell, so
        the result is dropped and logged rather than turned into a crash.
        """
        if not isValid(self._signals):
            logger.debug("dropping a background result: its owner is gone")
            return
        try:
            signal.emit(payload)
        except RuntimeError:
            logger.debug("dropping a background result: its owner went away mid-emit")


def drain_background_tasks(timeout_milliseconds: int = THREAD_SHUTDOWN_MILLISECONDS) -> bool:
    """Wait for every background task to finish.

    Called when the application quits. An export is a file write: letting the
    process exit while one is in flight is exactly how a half-written report
    ends up on disk, which FR-8 forbids for the crawl and common sense forbids
    for everything else.
    """
    return bool(QThreadPool.globalInstance().waitForDone(timeout_milliseconds))


def run_in_background(
    owner: QObject,
    work: Callable[[], Any],
    on_success: Callable[[Any], None],
    on_failure: Callable[[BaseException], None],
) -> TaskSignals:
    """Run ``work`` off the GUI thread and deliver its result back to it.

    ``owner`` parents the signals object, which is what keeps it alive after the
    runnable itself has been deleted by the pool.
    """
    signals = TaskSignals(owner)
    signals.succeeded.connect(on_success)
    signals.failed.connect(on_failure)
    QThreadPool.globalInstance().start(BackgroundTask(work, signals))
    return signals
