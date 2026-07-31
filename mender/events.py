"""A tiny append-only event log that the dashboard tails.

The heal loop runs in a worker thread and blocks on subprocesses; the web layer
is async. Rather than bridge those two worlds with queues and locks, the loop
appends to a sequence-numbered list and the SSE endpoint polls for anything
newer than the sequence it last sent. Cheap, thread-safe by virtue of the GIL
plus one lock, and it means a browser opening late still gets the whole story.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Event:
    """One thing that happened, in order."""

    seq: int
    kind: str
    at: float
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"seq": self.seq, "kind": self.kind, "at": self.at, **self.data}


class EventLog:
    """Ordered, bounded, thread-safe."""

    def __init__(self, capacity: int = 2000) -> None:
        self._events: list[Event] = []
        self._lock = threading.Lock()
        self._seq = 0
        self._capacity = capacity

    def emit(self, kind: str, **data: Any) -> Event:
        with self._lock:
            self._seq += 1
            event = Event(seq=self._seq, kind=kind, at=time.time(), data=data)
            self._events.append(event)
            if len(self._events) > self._capacity:
                del self._events[: len(self._events) - self._capacity]
            return event

    def since(self, seq: int) -> list[Event]:
        with self._lock:
            return [event for event in self._events if event.seq > seq]

    def latest_seq(self) -> int:
        with self._lock:
            return self._seq

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


# The process-wide log. The loop writes to it, the server reads from it.
LOG = EventLog()
