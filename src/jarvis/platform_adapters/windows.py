"""Windows adapter.

This exists so the engine can be developed and tested on Windows. macOS is the ship
target; this is the test rig. It is a genuine implementation, not a stub — if it were
stubbed it would not catch the bugs it is here to catch.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

from jarvis import APP_NAME
from jarvis.events import State
from jarvis.platform_adapters.base import MenuItem, PlatformAdapter, TrayHandle, TraySpec
from jarvis.ui import icons

log = logging.getLogger(__name__)

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE = APP_NAME

# Suppress the console window that subprocess would otherwise flash up.
_NO_WINDOW = 0x08000000


class WindowsTray(TrayHandle):
    """pystray-backed tray icon."""

    def __init__(self, spec: TraySpec, cache_dir: Path) -> None:
        import pystray

        self._pystray = pystray
        self._spec = spec
        self._cache_dir = cache_dir
        self._state = State.IDLE
        self._items = {item.id: item for item in spec.items}
        self._icon = pystray.Icon(
            name=spec.app_name,
            icon=icons.render(State.IDLE, 64),
            title=self._tooltip(State.IDLE),
            menu=self._build_menu(),
        )

    def _tooltip(self, state: State) -> str:
        return f"{self._spec.app_name} — {icons.STATE_LABELS[state]}"

    def _build_menu(self):
        pystray = self._pystray
        entries = []
        for item in self._spec.items:
            if item.checkable:
                entries.append(
                    pystray.MenuItem(
                        item.label,
                        self._wrap(item),
                        checked=lambda _i, _id=item.id: self._items[_id].checked,
                        enabled=item.enabled,
                    )
                )
            else:
                entries.append(
                    pystray.MenuItem(item.label, self._wrap(item), enabled=item.enabled)
                )
            if item.separator_after:
                entries.append(pystray.Menu.SEPARATOR)
        return pystray.Menu(*entries)

    def _wrap(self, item: MenuItem):
        def handler(_icon=None, _item=None) -> None:
            if item.callback is None:
                return
            try:
                item.callback()
            except Exception:
                log.exception("menu item %s raised", item.id)

        return handler

    def run(self) -> None:
        self._icon.run()

    def stop(self) -> None:
        try:
            self._icon.stop()
        except Exception:
            log.exception("failed to stop tray")

    def set_state(self, state: State) -> None:
        if state is self._state:
            return
        self._state = state
        try:
            self._icon.icon = icons.render(state, 64)
            self._icon.title = self._tooltip(state)
        except Exception:
            log.exception("failed to update tray icon")

    def set_checked(self, item_id: str, checked: bool) -> None:
        item = self._items.get(item_id)
        if item is None:
            return
        item.checked = checked
        try:
            self._icon.update_menu()
        except Exception:
            log.exception("failed to refresh tray menu")


class WindowsAdapter(PlatformAdapter):
    name = "windows"
    supports_automation = False

    # -- paths --

    def _base(self, env: str, fallback: str) -> Path:
        root = os.environ.get(env) or str(Path.home() / fallback)
        return Path(root) / APP_NAME

    def config_dir(self) -> Path:
        return self._base("APPDATA", "AppData/Roaming")

    def cache_dir(self) -> Path:
        return self._base("LOCALAPPDATA", "AppData/Local") / "cache"

    def log_dir(self) -> Path:
        return self._base("LOCALAPPDATA", "AppData/Local") / "logs"

    # -- launching --

    def launch_app(self, name: str) -> None:
        # `start` is a cmd builtin, hence shell=True. The empty "" is the window
        # title argument, which start requires before a quoted target.
        result = subprocess.run(
            f'start "" "{name}"',
            shell=True,
            capture_output=True,
            text=True,
            creationflags=_NO_WINDOW,
        )
        if result.returncode != 0:
            raise OSError(f"could not launch {name!r}: {result.stderr.strip()}")

    def open_url(self, url: str) -> None:
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"refusing to open non-http URL: {url!r}")
        os.startfile(url)  # noqa: S606 — the scheme is checked above

    def reveal_in_file_manager(self, path: Path) -> None:
        subprocess.run(
            ["explorer", "/select,", str(path)],
            capture_output=True,
            creationflags=_NO_WINDOW,
        )

    # -- observing --

    def capture_screen(self) -> bytes:
        import io

        import mss

        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[0])  # monitors[0] is the full virtual screen

        from PIL import Image

        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def notify(self, title: str, body: str) -> None:
        # Deliberately minimal: a real toast needs winrt, which is a heavy dependency
        # for the test rig. The macOS adapter does this properly.
        log.info("NOTIFY %s: %s", title, body)

    # -- autostart --

    @property
    def autostart_supported(self) -> bool:
        return True

    def _launch_command(self) -> str:
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}"'
        return f'"{sys.executable}" -m jarvis'

    def autostart_enabled(self) -> bool:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
                value, _ = winreg.QueryValueEx(key, _RUN_VALUE)
                return bool(value)
        except FileNotFoundError:
            return False
        except OSError:
            log.exception("could not read autostart registry value")
            return False

    def autostart_enable(self) -> None:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, _RUN_VALUE, 0, winreg.REG_SZ, self._launch_command())
        log.info("autostart enabled")

    def autostart_disable(self) -> None:
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, _RUN_VALUE)
        except FileNotFoundError:
            pass
        log.info("autostart disabled")

    # -- UI --

    def make_tray(self, spec: TraySpec) -> TrayHandle:
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("the tray must be created on the main thread")
        return WindowsTray(spec, self.cache_dir())
