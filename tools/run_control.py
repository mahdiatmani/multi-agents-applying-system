import threading

_running = threading.Event()
_running.set()  # not paused by default
_stop = threading.Event()


class StopRequested(BaseException):
    """Raised at a node boundary when /api/stop was hit, so the graph loop unwinds cleanly.

    Inherits from BaseException (not Exception) so the many `except Exception:` blocks
    sprinkled through the form-fill code don't accidentally swallow the stop signal."""


def pause() -> None:
    _running.clear()


def resume() -> None:
    _running.set()


def is_paused() -> bool:
    return not _running.is_set()


def request_stop() -> None:
    _stop.set()
    _running.set()  # also unblock any waiter in wait_if_paused


def clear_stop() -> None:
    _stop.clear()


def is_stopping() -> bool:
    return _stop.is_set()


def wait_if_paused(check_interval: float = 1.0) -> bool:
    """Block until resumed OR a stop is requested. Returns True if we actually waited.

    Safe to call from any worker thread. The web server flips the Event via /api/pause and
    /api/resume; nodes call this at the top of their work so a paused run halts before doing
    any browser work. If /api/stop fires while paused, this returns immediately."""
    if _running.is_set():
        return False
    while not _running.is_set() and not _stop.is_set():
        _running.wait(timeout=check_interval)
    return True


def checkpoint(node_name: str = "") -> None:
    """Block while paused; raise StopRequested if a stop was requested."""
    wait_if_paused()
    if _stop.is_set():
        raise StopRequested(f"stop requested before {node_name}" if node_name else "stop requested")
