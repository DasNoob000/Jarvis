"""Assistant state and the event bus the modules talk over.

Nothing in here imports anything platform-specific, and nothing in here blocks.
"""

from __future__ import annotations

import asyncio
import enum
from dataclasses import dataclass, field
from typing import Any, Callable


class State(enum.Enum):
    """What Jarvis is doing right now. Drives the menu-bar icon."""

    IDLE = "idle"            # listening for a clap, nothing else
    LISTENING = "listening"  # awake, recording the command
    THINKING = "thinking"    # waiting on the model
    SPEAKING = "speaking"    # reading a reply aloud
    ACTING = "acting"        # running a tool
    ERROR = "error"          # mic gone, API unreachable — degraded but alive

    def __str__(self) -> str:
        return self.value


# --- Events ------------------------------------------------------------------
# Deliberately plain dataclasses. They cross thread boundaries, so they must stay
# trivially picklable and free of live handles.


@dataclass(frozen=True, slots=True)
class Event:
    """Base class. Subclasses carry the payload."""


@dataclass(frozen=True, slots=True)
class Wake(Event):
    """The clap detector fired."""

    confidence: float = 1.0
    source: str = "clap"


@dataclass(frozen=True, slots=True)
class Utterance(Event):
    """A complete spoken command, transcribed."""

    text: str
    duration_s: float = 0.0


@dataclass(frozen=True, slots=True)
class Cancel(Event):
    """The cancel phrase was heard, or the user hit Cancel in the menu."""

    phrase: str = ""
    source: str = "voice"


@dataclass(frozen=True, slots=True)
class StateChanged(Event):
    state: State
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Spoke(Event):
    """Jarvis said something. Carried for logging and the transcript view."""

    text: str


@dataclass(frozen=True, slots=True)
class Failed(Event):
    """Something broke in a way the user should know about."""

    where: str
    message: str
    recoverable: bool = True


@dataclass(frozen=True, slots=True)
class Command(Event):
    """A typed command, from the dev CLI or a menu item — bypasses wake and STT."""

    text: str


class EventBus:
    """A fan-out async bus.

    Subscribers get their own queue, so a slow one cannot stall a fast one. Publish
    is non-blocking and drops into full queues rather than applying backpressure —
    an audio pipeline that stalls waiting on a UI subscriber is worse than a
    dropped status update.
    """

    def __init__(self, maxsize: int = 256) -> None:
        self._maxsize = maxsize
        self._queues: list[asyncio.Queue[Event]] = []
        self._sync_handlers: list[Callable[[Event], None]] = []

    def subscribe(self) -> asyncio.Queue[Event]:
        q: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._maxsize)
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Event]) -> None:
        if q in self._queues:
            self._queues.remove(q)

    def on_event(self, handler: Callable[[Event], None]) -> None:
        """Register a synchronous observer.

        Called inline during publish, so it must not block. The tray uses this to
        mirror state into the menu bar.
        """
        self._sync_handlers.append(handler)

    def publish(self, event: Event) -> None:
        for q in self._queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass
        for handler in self._sync_handlers:
            try:
                handler(event)
            except Exception:  # a broken observer must not take the bus down
                import logging

                logging.getLogger(__name__).exception("event handler raised")
