"""Thread-safe dialogs between worker threads and the Tk event loop.

Worker threads (diagnostics, fix execution) call :meth:`submit` and block.
The Tk ``after`` loop calls :meth:`poll` on the UI thread, which shows the
dialog through the installed handler and releases the worker with the answer.
"""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable

DialogHandler = Callable[[str, Any], Any]


class DialogBridge:
    """Marshal dialog requests from worker threads to the Tk thread."""

    def __init__(self) -> None:
        self._pending: "queue.Queue[dict[str, Any]]" = queue.Queue()
        self.handler: DialogHandler | None = None
        self._ui_thread = threading.main_thread()

    def submit(self, kind: str, payload: Any = None, *, timeout: float | None = None) -> Any:
        """Ask the UI thread a question; blocks the calling worker until answered.

        A call from the UI thread itself is answered inline (it cannot wait
        for its own ``poll``), which keeps such calls from deadlocking.
        """

        if threading.current_thread() is self._ui_thread:
            return self.answer_directly(kind, payload)
        box: dict[str, Any] = {
            "kind": kind,
            "payload": payload,
            "event": threading.Event(),
            "result": None,
        }
        self._pending.put(box)
        if not box["event"].wait(timeout):
            box["result"] = None
        return box["result"]

    def poll(self) -> None:
        """Answer every pending request; called from the Tk ``after`` loop."""

        while True:
            try:
                box = self._pending.get_nowait()
            except queue.Empty:
                return
            if self.handler is None:
                box["result"] = None
            else:
                try:
                    box["result"] = self.handler(box["kind"], box["payload"])
                except Exception:
                    box["result"] = None
            box["event"].set()

    def answer_directly(self, kind: str, payload: Any = None) -> Any:
        """Answer a request inline without a worker thread (UI-thread caller)."""

        if self.handler is None:
            return None
        try:
            return self.handler(kind, payload)
        except Exception:
            return None
