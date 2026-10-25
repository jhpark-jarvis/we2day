"""Request-local, fixed-label timings; no request contents or identifiers."""

from collections import defaultdict
from contextvars import ContextVar
from functools import wraps
from threading import Lock
from time import perf_counter


class Timings:
    def __init__(self):
        self.values = defaultdict(float)
        self.lock = Lock()

    def add(self, label: str, elapsed: float):
        with self.lock:
            self.values[label] += elapsed * 1000

    def header(self):
        with self.lock:
            return ", ".join(f"{key};dur={value:.1f}" for key, value in sorted(self.values.items()))


current_timings: ContextVar[Timings | None] = ContextVar("request_timings", default=None)


def timed(label: str):
    if label not in {"auth", "data", "storage", "image"}:
        raise ValueError("Use a fixed timing category")

    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            metrics = current_timings.get()
            start = perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                if metrics is not None:
                    metrics.add(label, perf_counter() - start)

        return wrapped

    return decorate
