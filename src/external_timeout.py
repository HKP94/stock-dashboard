"""Helpers for hard-bounding synchronous external calls."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from contextlib import contextmanager
import signal
import threading
from typing import Callable, TypeVar

T = TypeVar("T")


class ExternalCallTimeout(TimeoutError):
    """Raised when an external dependency call exceeds its hard deadline."""


@contextmanager
def _signal_timeout(seconds: float):
    if seconds <= 0:
        yield
        return

    old_handler = signal.getsignal(signal.SIGALRM)
    old_timer = signal.setitimer(signal.ITIMER_REAL, seconds)

    def _handler(signum, frame):  # type: ignore[unused-argument]
        raise ExternalCallTimeout(f"external call timed out after {seconds:.1f}s")

    signal.signal(signal.SIGALRM, _handler)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
        if old_timer[0] > 0 or old_timer[1] > 0:
            signal.setitimer(signal.ITIMER_REAL, old_timer[0], old_timer[1])


def run_with_timeout(seconds: float, func: Callable[..., T], *args, **kwargs) -> T:
    """Run a blocking callable with a hard timeout.

    Prefer a signal-based deadline on the main thread (works in CI/Linux, local macOS).
    Fall back to a non-blocking executor shutdown in other contexts.
    """
    if seconds <= 0:
        return func(*args, **kwargs)

    if threading.current_thread() is threading.main_thread():
        with _signal_timeout(seconds):
            return func(*args, **kwargs)

    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(func, *args, **kwargs)
    try:
        return future.result(timeout=seconds)
    except FutureTimeout as exc:
        future.cancel()
        raise ExternalCallTimeout(f"external call timed out after {seconds:.1f}s") from exc
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
