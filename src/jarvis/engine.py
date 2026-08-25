"""The engine: state machine and activation lifecycle.

Phase 1 wires up the skeleton — state transitions, the event bus, thread-safe entry
points from the UI, and cancellation. The audio pipeline (Phase 2) and the model loop
(Phase 3) plug into ``_handle_activation`` without changing anything here.

Threading contract:

* ``Engine`` and everything it awaits live on one asyncio loop, on one thread.
* ``EngineThread`` owns that thread and is the only thing the UI touches.
* Every method on ``EngineThread`` is safe to call from the main (UI) thread.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Awaitable, Callable

from jarvis.config import Config
from jarvis.events import Cancel, Command, Event, EventBus, Failed, State, StateChanged
from jarvis.platform_adapters.base import PlatformAdapter

log = logging.getLogger(__name__)

# An activation is one wake-to-answer cycle. Phase 3 replaces this signature's body.
ActivationHandler = Callable[[str], Awaitable[None]]


class Engine:
    def __init__(
        self,
        config: Config,
        adapter: PlatformAdapter,
        bus: EventBus | None = None,
    ) -> None:
        self.config = config
        self.adapter = adapter
        self.bus = bus or EventBus()

        self._state = State.IDLE
        self._stop = asyncio.Event()
        self._inbox: asyncio.Queue[Event] = asyncio.Queue()

        # The task servicing the current activation. Cancelling it is how the cancel
        # phrase aborts work already in flight, at whatever await point it has reached.
        self._activation: asyncio.Task[None] | None = None
        self._handler: ActivationHandler | None = None

    # -- state --

    @property
    def state(self) -> State:
        return self._state

    def set_state(self, state: State, detail: str = "") -> None:
        if state is self._state:
            return
        log.debug("state %s -> %s %s", self._state, state, detail)
        self._state = state
        self.bus.publish(StateChanged(state=state, detail=detail))

    @property
    def busy(self) -> bool:
        return self._activation is not None and not self._activation.done()

    # -- wiring --

    def set_activation_handler(self, handler: ActivationHandler) -> None:
        """Install what actually happens when a command arrives.

        Kept injectable so Phase 2 can test the state machine with a fake handler
        before the model exists.
        """
        self._handler = handler

    # -- lifecycle --

    async def run(self) -> None:
        log.info("engine started (%s adapter)", self.adapter.name)
        self.set_state(State.IDLE)

        for warning in self.adapter.preflight():
            log.warning("preflight: %s", warning)
            self.bus.publish(Failed(where="permissions", message=warning))

        try:
            while not self._stop.is_set():
                event = await self._next_event()
                if event is None:
                    continue
                await self._dispatch(event)
        finally:
            await self._abort_activation("shutdown")
            log.info("engine stopped")

    async def _next_event(self) -> Event | None:
        """Wait for an event or for shutdown, whichever comes first."""
        getter = asyncio.ensure_future(self._inbox.get())
        stopper = asyncio.ensure_future(self._stop.wait())
        done, pending = await asyncio.wait(
            {getter, stopper}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        if getter in done:
            return getter.result()
        return None

    async def _dispatch(self, event: Event) -> None:
        if isinstance(event, Cancel):
            await self._abort_activation(event.source)
            return

        if isinstance(event, Command):
            if self.busy:
                log.info("dropping command while busy: %r", event.text)
                return
            self._activation = asyncio.create_task(self._run_activation(event.text))
            return

        log.debug("unhandled event %r", event)

    async def _run_activation(self, text: str) -> None:
        try:
            if self._handler is None:
                # Phase 1 placeholder. Phase 3 installs the real handler.
                self.set_state(State.THINKING)
                log.info("no activation handler installed; would process: %r", text)
                await asyncio.sleep(0)
            else:
                await self._handler(text)
        except asyncio.CancelledError:
            log.info("activation cancelled")
            raise
        except Exception as exc:
            log.exception("activation failed")
            self.bus.publish(Failed(where="activation", message=str(exc)))
            self.set_state(State.ERROR, detail=str(exc))
        finally:
            if self._state is not State.ERROR:
                self.set_state(State.IDLE)

    async def _abort_activation(self, reason: str) -> None:
        task = self._activation
        if task is None or task.done():
            return
        log.info("cancelling activation (%s)", reason)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        finally:
            self._activation = None
            self.set_state(State.IDLE)

    def request_stop(self) -> None:
        self._stop.set()

    # -- inbox --

    def submit_soon(self, event: Event) -> None:
        """Enqueue an event. Loop-thread only; the UI uses EngineThread.submit."""
        self._inbox.put_nowait(event)


class EngineThread:
    """Runs an Engine on its own thread and its own event loop.

    The UI toolkit owns the main thread and never gives it back, so this is not
    optional. Every public method here is callable from the UI thread.
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="jarvis-engine", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(timeout=10):
            raise RuntimeError("engine thread failed to start")

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        self._ready.set()
        try:
            loop.run_until_complete(self.engine.run())
        except Exception:
            log.exception("engine thread died")
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                loop.close()

    def submit(self, event: Event) -> None:
        """Post an event to the engine from any thread."""
        loop = self._loop
        if loop is None or loop.is_closed():
            log.warning("dropping %r: engine loop not running", event)
            return
        loop.call_soon_threadsafe(self.engine.submit_soon, event)

    def cancel(self, source: str = "menu") -> None:
        self.submit(Cancel(source=source))

    def stop(self, timeout: float = 5.0) -> None:
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self.engine.request_stop)
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                log.warning("engine thread did not stop within %.1fs", timeout)
