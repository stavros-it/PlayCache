"""Small Qt helpers shared by GUI modules."""
from __future__ import annotations

from PySide6.QtCore import QThread


def worker_is_running(worker: QThread | None) -> bool:
    """Return True if *worker* is a live QThread that is currently running.

    Workers wired as ``finished -> deleteLater`` have their C++ object
    destroyed while Python references may linger; touching such a wrapper
    raises ``RuntimeError: Internal C++ object already deleted``. This guard
    treats a destroyed worker as not running.
    """
    if worker is None:
        return False
    try:
        return worker.isRunning()
    except RuntimeError:
        return False
