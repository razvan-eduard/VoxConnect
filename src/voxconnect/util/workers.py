"""Runs blocking calls (httpx, etc.) off the Qt GUI thread and marshals the
result back via signals.

`WorkerSignals` is constructed on the calling (GUI) thread inside `_Runnable`,
so its Qt thread-affinity is the GUI thread; when `run()` executes on a pool
thread and emits, Qt's AutoConnection queues delivery back to the GUI thread
automatically — no manual moveToThread bookkeeping needed by callers.
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


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
    if on_result is not None:
        runnable.signals.result.connect(on_result)
    if on_error is not None:
        runnable.signals.error.connect(on_error)
    QThreadPool.globalInstance().start(runnable)
