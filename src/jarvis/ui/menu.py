"""The menu-bar menu, and the bridge that keeps the icon in sync with the engine.

Menu callbacks run on the UI thread and must return immediately — they post to the
engine rather than doing work themselves.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from jarvis.config import Config
from jarvis.engine import EngineThread
from jarvis.events import Event, StateChanged
from jarvis.platform_adapters.base import MenuItem, PlatformAdapter, TrayHandle, TraySpec

log = logging.getLogger(__name__)

ITEM_CANCEL = "cancel"
ITEM_AUTOSTART = "autostart"
ITEM_CONFIG = "config"
ITEM_LOGS = "logs"
ITEM_QUIT = "quit"


class TrayController:
    """Owns the tray and mirrors engine state into it."""

    def __init__(
        self,
        adapter: PlatformAdapter,
        engine_thread: EngineThread,
        config: Config,
        log_file: Path,
        on_quit: Callable[[], None],
    ) -> None:
        self.adapter = adapter
        self.engine_thread = engine_thread
        self.config = config
        self.log_file = log_file
        self._on_quit = on_quit
        self.tray: TrayHandle | None = None

    # -- menu actions --

    def _cancel(self) -> None:
        self.engine_thread.cancel(source="menu")

    def _toggle_autostart(self) -> None:
        if not self.adapter.autostart_supported:
            return
        try:
            if self.adapter.autostart_enabled():
                self.adapter.autostart_disable()
            else:
                self.adapter.autostart_enable()
        except Exception as exc:
            log.exception("autostart toggle failed")
            self.adapter.notify("Jarvis", f"Could not change autostart: {exc}")
        finally:
            if self.tray is not None:
                self.tray.set_checked(ITEM_AUTOSTART, self.adapter.autostart_enabled())

    def _reveal_config(self) -> None:
        path = self.config.source_path
        if path is None:
            return
        try:
            self.adapter.reveal_in_file_manager(path)
        except Exception:
            log.exception("could not reveal config")

    def _reveal_logs(self) -> None:
        try:
            self.adapter.reveal_in_file_manager(self.log_file)
        except Exception:
            log.exception("could not reveal logs")

    # -- construction --

    def build(self) -> TrayHandle:
        items = [
            MenuItem(ITEM_CANCEL, "Cancel Current Task", self._cancel, separator_after=True),
            MenuItem(
                ITEM_AUTOSTART,
                "Start at Login",
                self._toggle_autostart,
                checkable=True,
                checked=self.adapter.autostart_supported
                and self.adapter.autostart_enabled(),
                enabled=self.adapter.autostart_supported,
            ),
            MenuItem(ITEM_CONFIG, "Reveal Config File", self._reveal_config),
            MenuItem(ITEM_LOGS, "Reveal Log File", self._reveal_logs, separator_after=True),
            MenuItem(ITEM_QUIT, "Quit Jarvis", self._on_quit),
        ]
        spec = TraySpec(app_name="Jarvis", items=items)
        self.tray = self.adapter.make_tray(spec)
        return self.tray

    # -- engine -> UI --

    def on_event(self, event: Event) -> None:
        """Synchronous bus observer. Called on the engine thread; must not block."""
        if isinstance(event, StateChanged) and self.tray is not None:
            self.tray.set_state(event.state)
