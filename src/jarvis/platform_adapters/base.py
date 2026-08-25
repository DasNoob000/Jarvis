"""The OS seam.

Everything Jarvis needs from the operating system goes through this interface. The
rule the rest of the codebase obeys:

    Nothing outside ``jarvis.platform_adapters`` may import a platform-specific
    module (rumps, pyobjc, pystray, winreg, mss, ...).

``tests/test_import_boundary.py`` enforces it. The point is that the engine — audio,
STT, the model loop, TTS — runs and is testable anywhere, and the only code that has
to be debugged on a Mac is the ~200 lines in ``macos.py`` plus the plist.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from jarvis.events import State


# --- Tray / menu-bar model ---------------------------------------------------


@dataclass
class MenuItem:
    """One row in the menu-bar menu.

    ``callback`` is invoked on the UI thread. It must return immediately — push work
    onto the engine rather than doing it here.
    """

    id: str
    label: str
    callback: Callable[[], None] | None = None
    checkable: bool = False
    checked: bool = False
    enabled: bool = True
    separator_after: bool = False


@dataclass
class TraySpec:
    app_name: str
    items: list[MenuItem] = field(default_factory=list)


class TrayHandle(abc.ABC):
    """A live menu-bar presence.

    ``run()`` blocks the main thread until ``stop()`` — both rumps and pystray insist
    on owning the main thread, which is why the engine lives on its own thread.
    """

    @abc.abstractmethod
    def run(self) -> None:
        """Enter the native UI run loop. Blocks. Main thread only."""

    @abc.abstractmethod
    def stop(self) -> None:
        """Tear down the UI and let ``run()`` return. Callable from any thread."""

    @abc.abstractmethod
    def set_state(self, state: State) -> None:
        """Update the icon and status line. Callable from any thread."""

    @abc.abstractmethod
    def set_checked(self, item_id: str, checked: bool) -> None:
        """Update a checkable item. Callable from any thread."""


# --- The adapter -------------------------------------------------------------


class PlatformAdapter(abc.ABC):
    """What the engine is allowed to ask the operating system for."""

    name: str = "unknown"

    # -- paths --

    @abc.abstractmethod
    def config_dir(self) -> Path:
        """Per-user config directory. Created by the caller, not here."""

    @abc.abstractmethod
    def cache_dir(self) -> Path:
        """Per-user cache directory, for generated icons and model downloads."""

    @abc.abstractmethod
    def log_dir(self) -> Path: ...

    # -- launching things --

    @abc.abstractmethod
    def launch_app(self, name: str) -> None:
        """Bring up an application by user-visible name. Raises OSError on failure."""

    @abc.abstractmethod
    def open_url(self, url: str) -> None:
        """Open a URL in the default browser."""

    @abc.abstractmethod
    def reveal_in_file_manager(self, path: Path) -> None:
        """Show a file in Finder / Explorer."""

    # -- observing things --

    @abc.abstractmethod
    def capture_screen(self) -> bytes:
        """A PNG of the main display.

        Raises PermissionError if the OS has not granted screen capture, so the
        caller can tell the user which panel to open rather than showing a black
        rectangle to the model.
        """

    @abc.abstractmethod
    def notify(self, title: str, body: str) -> None:
        """A system notification. Best-effort; never raises."""

    # -- automation --

    def run_automation(self, script: str) -> str:
        """Run an OS automation script (AppleScript on macOS).

        Default: unsupported. Adapters override. Callers must check
        ``supports_automation`` first — and the model never reaches this directly
        unless the user has enabled it in config.
        """
        raise NotImplementedError(f"{self.name} has no automation backend")

    supports_automation: bool = False

    # -- autostart --

    @property
    @abc.abstractmethod
    def autostart_supported(self) -> bool: ...

    @abc.abstractmethod
    def autostart_enabled(self) -> bool: ...

    @abc.abstractmethod
    def autostart_enable(self) -> None: ...

    @abc.abstractmethod
    def autostart_disable(self) -> None: ...

    # -- UI --

    @abc.abstractmethod
    def make_tray(self, spec: TraySpec) -> TrayHandle: ...

    # -- permissions --

    def preflight(self) -> list[str]:
        """Warnings about permissions that look missing.

        Advisory only: on macOS most TCC grants cannot be queried without triggering
        the prompt, so this reports what it can and stays quiet otherwise.
        """
        return []
