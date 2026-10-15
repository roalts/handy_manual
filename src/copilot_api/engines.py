"""A small pool of answer engines: one engine (and its database connection) per concurrent ask."""
import queue
import threading
from collections.abc import Callable
from contextlib import contextmanager

from copilot_contracts import AnswerEngine


class EnginePool:
    def __init__(self, factory: Callable[[], AnswerEngine], size: int) -> None:
        """Build one engine now; more are built on demand, up to `size`."""
        self._factory = factory
        self._size = size
        self._idle: queue.LifoQueue[AnswerEngine] = queue.LifoQueue()
        self._built = 0
        self._lock = threading.Lock()
        self._idle.put(self._new())

    def _new(self) -> AnswerEngine:
        """Build an engine and count it against the pool size."""
        engine = self._factory()
        self._built += 1
        return engine

    @contextmanager
    def engine(self):
        """Lend an idle engine, building one below the limit, else waiting for one to return."""
        try:
            engine = self._idle.get_nowait()
        except queue.Empty:
            with self._lock:
                engine = self._new() if self._built < self._size else None
            if engine is None:
                engine = self._idle.get()
        try:
            yield engine
        finally:
            self._idle.put(engine)
