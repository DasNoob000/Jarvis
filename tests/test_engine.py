"""State machine and cancellation.

Cancellation is the part most likely to rot, so it is tested with a handler that
blocks the way a real model call or a long tool run would.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from jarvis.config import Config
from jarvis.engine import Engine
from jarvis.events import Cancel, Command, State, StateChanged
from jarvis.platform_adapters.base import PlatformAdapter, TrayHandle, TraySpec


class FakeAdapter(PlatformAdapter):
    """Enough adapter to run the engine, and nothing more."""

    name = "fake"

    def __init__(self, warnings: list[str] | None = None) -> None:
        self._warnings = warnings or []
        self.launched: list[str] = []
        self.opened: list[str] = []

    def config_dir(self) -> Path:
        return Path("/tmp/jarvis-test")

    def cache_dir(self) -> Path:
        return Path("/tmp/jarvis-test/cache")

    def log_dir(self) -> Path:
        return Path("/tmp/jarvis-test/logs")

    def launch_app(self, name: str) -> None:
        self.launched.append(name)

    def open_url(self, url: str) -> None:
        self.opened.append(url)

    def reveal_in_file_manager(self, path: Path) -> None: ...

    def capture_screen(self) -> bytes:
        return b"\x89PNG\r\n\x1a\n"

    def notify(self, title: str, body: str) -> None: ...

    @property
    def autostart_supported(self) -> bool:
        return False

    def autostart_enabled(self) -> bool:
        return False

    def autostart_enable(self) -> None: ...

    def autostart_disable(self) -> None: ...

    def make_tray(self, spec: TraySpec) -> TrayHandle:
        raise NotImplementedError

    def preflight(self) -> list[str]:
        return self._warnings


@pytest.fixture
def engine() -> Engine:
    return Engine(config=Config(), adapter=FakeAdapter())


async def _run_engine(engine: Engine) -> asyncio.Task[None]:
    task = asyncio.create_task(engine.run())
    await asyncio.sleep(0)  # let it reach the first await
    return task


async def test_starts_idle_and_stops_cleanly(engine: Engine) -> None:
    task = await _run_engine(engine)
    assert engine.state is State.IDLE
    engine.request_stop()
    await asyncio.wait_for(task, timeout=2)


async def test_command_invokes_the_handler(engine: Engine) -> None:
    seen: list[str] = []

    async def handler(text: str) -> None:
        seen.append(text)

    engine.set_activation_handler(handler)
    task = await _run_engine(engine)

    engine.submit_soon(Command(text="what time is it"))
    await asyncio.sleep(0.05)

    assert seen == ["what time is it"]
    engine.request_stop()
    await asyncio.wait_for(task, timeout=2)


async def test_cancel_aborts_work_in_flight(engine: Engine) -> None:
    started = asyncio.Event()
    finished = False
    cleaned_up = False

    async def handler(text: str) -> None:
        nonlocal finished, cleaned_up
        started.set()
        try:
            await asyncio.sleep(10)  # stands in for a model call or a long tool
            finished = True
        except asyncio.CancelledError:
            cleaned_up = True
            raise

    engine.set_activation_handler(handler)
    task = await _run_engine(engine)

    engine.submit_soon(Command(text="do something slow"))
    await asyncio.wait_for(started.wait(), timeout=2)
    assert engine.busy

    engine.submit_soon(Cancel(phrase="cancel"))
    await asyncio.sleep(0.05)

    assert cleaned_up, "the handler was never given a chance to clean up"
    assert not finished
    assert not engine.busy
    assert engine.state is State.IDLE

    engine.request_stop()
    await asyncio.wait_for(task, timeout=2)


async def test_a_second_command_is_dropped_while_busy(engine: Engine) -> None:
    calls: list[str] = []
    started = asyncio.Event()

    async def handler(text: str) -> None:
        calls.append(text)
        started.set()
        await asyncio.sleep(5)

    engine.set_activation_handler(handler)
    task = await _run_engine(engine)

    engine.submit_soon(Command(text="first"))
    await asyncio.wait_for(started.wait(), timeout=2)
    engine.submit_soon(Command(text="second"))
    await asyncio.sleep(0.05)

    assert calls == ["first"]

    engine.submit_soon(Cancel())
    await asyncio.sleep(0.05)
    engine.request_stop()
    await asyncio.wait_for(task, timeout=2)


async def test_handler_failure_is_reported_not_fatal(engine: Engine) -> None:
    async def handler(text: str) -> None:
        raise RuntimeError("the microphone caught fire")

    engine.set_activation_handler(handler)
    task = await _run_engine(engine)

    engine.submit_soon(Command(text="boom"))
    await asyncio.sleep(0.05)

    assert engine.state is State.ERROR
    assert not task.done(), "one bad activation must not kill the engine"

    engine.request_stop()
    await asyncio.wait_for(task, timeout=2)


async def test_state_changes_are_published(engine: Engine) -> None:
    seen: list[State] = []
    engine.bus.on_event(
        lambda e: seen.append(e.state) if isinstance(e, StateChanged) else None
    )

    async def handler(text: str) -> None:
        engine.set_state(State.THINKING)
        engine.set_state(State.SPEAKING)

    engine.set_activation_handler(handler)
    task = await _run_engine(engine)
    engine.submit_soon(Command(text="hello"))
    await asyncio.sleep(0.05)

    assert State.THINKING in seen and State.SPEAKING in seen
    assert seen[-1] is State.IDLE  # always returns to idle

    engine.request_stop()
    await asyncio.wait_for(task, timeout=2)


async def test_preflight_warnings_are_surfaced() -> None:
    engine = Engine(
        config=Config(), adapter=FakeAdapter(warnings=["Microphone access is denied."])
    )
    failures: list[str] = []
    engine.bus.on_event(
        lambda e: failures.append(getattr(e, "message", "")) if hasattr(e, "message") else None
    )
    task = await _run_engine(engine)
    await asyncio.sleep(0.05)

    assert any("Microphone" in f for f in failures)

    engine.request_stop()
    await asyncio.wait_for(task, timeout=2)
