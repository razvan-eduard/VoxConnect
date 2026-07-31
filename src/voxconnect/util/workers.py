"""Runs blocking calls (httpx, etc.) off the Qt GUI thread and marshals the
result back via signals.

`WorkerSignals` is constructed on the calling (GUI) thread inside `_Runnable`,
so its Qt thread-affinity is the GUI thread; when `run()` executes on a pool
thread and emits, Qt's AutoConnection queues delivery back to the GUI thread
automatically — no manual moveToThread bookkeeping needed by callers.

`QRunnable` is not a `QObject`, so `signals` has no C++ parent keeping it
alive — its lifetime is pure Python refcounting. Once `run_in_background`
returns, its local `runnable` variable goes out of scope, and nothing else
holds a Python reference to it while the pool thread is still executing
`run()`; PySide's GC can then delete the `signals` QObject out from under a
still-running background thread, which surfaces as "RuntimeError: Signal
source has been deleted" on whichever `emit()` loses the race — a real crash
observed in testing, not a hypothetical. `_IN_FLIGHT` keeps a strong
reference to every runnable until its own result/error signal has actually
fired, at which point cleanup runs on the GUI thread (same queued-delivery
guarantee as any other connected slot) and it's safe to drop.
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

_IN_FLIGHT: set["_Runnable"] = set()


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(str)


class _Runnable(QRunnable):
    def __init__(self, fn: Callable[[], Any]):
        super().__init__()
        self.fn = fn
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            value = self.fn()
        except Exception as exc:  # noqa: BLE001 - reported to caller, not raised
            self.signals.error.emit(str(exc))
        else:
            self.signals.result.emit(value)


def run_in_background(
    fn: Callable[[], Any],
    *,
    on_result: Callable[[Any], None] | None = None,
    on_error: Callable[[str], None] | None = None,
) -> None:
    runnable = _Runnable(fn)
    _IN_FLIGHT.add(runnable)

    def _cleanup(*_args: Any) -> None:
        _IN_FLIGHT.discard(runnable)

    if on_result is not None:
        runnable.signals.result.connect(on_result)
    if on_error is not None:
        runnable.signals.error.connect(on_error)
    runnable.signals.result.connect(_cleanup)
    runnable.signals.error.connect(_cleanup)
    QThreadPool.globalInstance().start(runnable)
