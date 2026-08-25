"""macOS adapter — menu bar, LaunchAgent, screencapture, AppleScript, TCC preflight.

This is the one file that cannot be exercised on the development machine. It is kept
deliberately small and free of logic that belongs in the engine, so that the surface
you have to debug on the Mac is as narrow as possible.

Two macOS constraints drive the shape of it:

* ``rumps`` owns the main thread and is not thread-safe. Cross-thread updates are
  therefore queued and applied by a ``rumps.Timer`` running on the main thread,
  rather than poked in directly.
* Most TCC permissions cannot be queried without triggering their prompt. ``preflight``
  reports only what the frameworks will tell us for free, and stays quiet otherwise.
"""

from __future__ import annotations

import logging
import os
import plistlib
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from jarvis import APP_NAME, BUNDLE_ID
from jarvis.events import State
from jarvis.platform_adapters.base import MenuItem, PlatformAdapter, TrayHandle, TraySpec
from jarvis.ui import icons

log = logging.getLogger(__name__)

LAUNCH_AGENT_DIR = Path.home() / "Library" / "LaunchAgents"
LAUNCH_AGENT_PATH = LAUNCH_AGENT_DIR / f"{BUNDLE_ID}.plist"

_UI_POLL_SECONDS = 0.15


class MacTray(TrayHandle):
    """rumps-backed menu-bar item.

    ``set_state`` and ``set_checked`` are called from the engine thread. They only
    record intent; ``_pump`` applies it on the main thread.
    """

    def __init__(self, spec: TraySpec, cache_dir: Path) -> None:
        import rumps

        self._rumps = rumps
        self._spec = spec
        self._cache_dir = cache_dir
        self._items = {item.id: item for item in spec.items}

        self._lock = threading.Lock()
        self._applied_state = State.IDLE
        self._pending_state: State | None = State.IDLE
        self._pending_checks: dict[str, bool] = {}

        self._app = rumps.App(
            spec.app_name,
            title=None,
            icon=str(icons.icon_path(State.IDLE, cache_dir)),
            template=False,
            quit_button=None,  # quit is one of our own items, so we can shut down cleanly
        )

        self._status = rumps.MenuItem(f"Status: {icons.STATE_LABELS[State.IDLE]}")
        self._status.set_callback(None)  # a label, not a button
        self._app.menu.add(self._status)
        self._app.menu.add(rumps.separator)

        self._rumps_items: dict[str, object] = {}
        for item in spec.items:
            entry = rumps.MenuItem(item.label, callback=self._wrap(item))
            entry.state = 1 if (item.checkable and item.checked) else 0
            if not item.enabled:
                entry.set_callback(None)
            self._rumps_items[item.id] = entry
            self._app.menu.add(entry)
            if item.separator_after:
                self._app.menu.add(rumps.separator)

        self._timer = rumps.Timer(self._pump, _UI_POLL_SECONDS)

    def _wrap(self, item: MenuItem):
        def handler(_sender) -> None:
            if item.callback is None:
                return
            try:
                item.callback()
            except Exception:
                log.exception("menu item %s raised", item.id)

        return handler

    def _pump(self, _timer) -> None:
        """Apply queued cross-thread updates. Main thread only."""
        with self._lock:
            state = self._pending_state
            checks = self._pending_checks
            self._pending_state = None
            self._pending_checks = {}

        if state is not None and state is not self._applied_state:
            self._applied_state = state
            try:
                self._app.icon = str(icons.icon_path(state, self._cache_dir))
                self._status.title = f"Status: {icons.STATE_LABELS[state]}"
            except Exception:
                log.exception("failed to update menu bar")

        for item_id, checked in checks.items():
            entry = self._rumps_items.get(item_id)
            if entry is not None:
                entry.state = 1 if checked else 0

    def run(self) -> None:
        self._timer.start()
        self._app.run()

    def stop(self) -> None:
        try:
            self._timer.stop()
        except Exception:
            pass
        try:
            self._rumps.quit_application()
        except Exception:
            log.exception("failed to quit rumps application")

    def set_state(self, state: State) -> None:
        with self._lock:
            self._pending_state = state

    def set_checked(self, item_id: str, checked: bool) -> None:
        item = self._items.get(item_id)
        if item is None:
            return
        item.checked = checked
        with self._lock:
            self._pending_checks[item_id] = checked


class MacAdapter(PlatformAdapter):
    name = "macos"
    supports_automation = True

    # -- paths --

    def config_dir(self) -> Path:
        return Path.home() / "Library" / "Application Support" / APP_NAME

    def cache_dir(self) -> Path:
        return Path.home() / "Library" / "Caches" / BUNDLE_ID

    def log_dir(self) -> Path:
        return Path.home() / "Library" / "Logs" / APP_NAME

    # -- launching --

    def launch_app(self, name: str) -> None:
        result = subprocess.run(
            ["/usr/bin/open", "-a", name], capture_output=True, text=True
        )
        if result.returncode != 0:
            raise OSError(f"could not launch {name!r}: {result.stderr.strip()}")

    def open_url(self, url: str) -> None:
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"refusing to open non-http URL: {url!r}")
        result = subprocess.run(["/usr/bin/open", url], capture_output=True, text=True)
        if result.returncode != 0:
            raise OSError(f"could not open {url!r}: {result.stderr.strip()}")

    def reveal_in_file_manager(self, path: Path) -> None:
        subprocess.run(["/usr/bin/open", "-R", str(path)], capture_output=True)

    # -- observing --

    def capture_screen(self) -> bytes:
        if not self._screen_capture_authorised():
            raise PermissionError(
                "Screen Recording is not granted. Open System Settings > Privacy & "
                "Security > Screen & System Audio Recording and enable Jarvis, then "
                "restart the app."
            )

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            target = Path(tmp.name)
        try:
            # -x silences the shutter, -o omits window shadows, -C excludes the cursor.
            result = subprocess.run(
                ["/usr/sbin/screencapture", "-x", "-o", "-C", "-t", "png", str(target)],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0 or not target.exists():
                raise OSError(f"screencapture failed: {result.stderr.strip()}")
            return target.read_bytes()
        finally:
            target.unlink(missing_ok=True)

    def _screen_capture_authorised(self) -> bool:
        """True if we hold Screen Recording, or if we cannot tell.

        Failing open matters: a wrong 'no' would block a working feature, whereas a
        wrong 'yes' just means screencapture returns a wallpaper-only image and the
        model says it cannot see anything useful.
        """
        try:
            import Quartz

            return bool(Quartz.CGPreflightScreenCaptureAccess())
        except Exception:
            log.debug("could not preflight screen capture access", exc_info=True)
            return True

    def request_screen_capture_access(self) -> None:
        """Trigger the Screen Recording prompt. Called from the menu, not automatically."""
        try:
            import Quartz

            Quartz.CGRequestScreenCaptureAccess()
        except Exception:
            log.exception("could not request screen capture access")

    def notify(self, title: str, body: str) -> None:
        try:
            import rumps

            rumps.notification(title, "", body)
            return
        except Exception:
            log.debug("rumps notification failed, falling back to osascript")
        try:
            script = (
                f'display notification {_as_applescript_string(body)} '
                f'with title {_as_applescript_string(title)}'
            )
            subprocess.run(["/usr/bin/osascript", "-e", script], capture_output=True)
        except Exception:
            log.exception("notification failed")

    # -- automation --

    def run_automation(self, script: str) -> str:
        result = subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise OSError(f"osascript failed: {result.stderr.strip()}")
        return result.stdout.strip()

    # -- autostart --

    @property
    def autostart_supported(self) -> bool:
        return True

    def _program_arguments(self) -> list[str]:
        if getattr(sys, "frozen", False):
            # Inside a py2app bundle sys.executable is Contents/MacOS/<name>, which is
            # exactly the binary launchd should exec.
            return [sys.executable]
        return [sys.executable, "-m", "jarvis"]

    def autostart_enabled(self) -> bool:
        return LAUNCH_AGENT_PATH.exists()

    def autostart_enable(self) -> None:
        LAUNCH_AGENT_DIR.mkdir(parents=True, exist_ok=True)
        plist = {
            "Label": BUNDLE_ID,
            "ProgramArguments": self._program_arguments(),
            "RunAtLoad": True,
            # Jarvis is not a daemon: if the user quits it, it should stay quit.
            "KeepAlive": False,
            "ProcessType": "Interactive",
            "StandardOutPath": str(self.log_dir() / "launchagent.out.log"),
            "StandardErrorPath": str(self.log_dir() / "launchagent.err.log"),
        }
        self.log_dir().mkdir(parents=True, exist_ok=True)
        with LAUNCH_AGENT_PATH.open("wb") as fh:
            plistlib.dump(plist, fh)

        domain = f"gui/{os.getuid()}"
        result = subprocess.run(
            ["/bin/launchctl", "bootstrap", domain, str(LAUNCH_AGENT_PATH)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            # bootstrap is the modern verb but errors if already loaded; load -w is
            # the older one and is tolerated on every version that matters.
            subprocess.run(
                ["/bin/launchctl", "load", "-w", str(LAUNCH_AGENT_PATH)],
                capture_output=True,
            )
        log.info("LaunchAgent installed at %s", LAUNCH_AGENT_PATH)

    def autostart_disable(self) -> None:
        domain = f"gui/{os.getuid()}"
        subprocess.run(
            ["/bin/launchctl", "bootout", f"{domain}/{BUNDLE_ID}"], capture_output=True
        )
        subprocess.run(
            ["/bin/launchctl", "unload", "-w", str(LAUNCH_AGENT_PATH)],
            capture_output=True,
        )
        LAUNCH_AGENT_PATH.unlink(missing_ok=True)
        log.info("LaunchAgent removed")

    # -- UI --

    def make_tray(self, spec: TraySpec) -> TrayHandle:
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("the menu bar must be created on the main thread")
        return MacTray(spec, self.cache_dir())

    # -- permissions --

    def preflight(self) -> list[str]:
        warnings: list[str] = []

        status = self._microphone_status()
        if status == "denied":
            warnings.append(
                "Microphone access is denied. System Settings > Privacy & Security > "
                "Microphone."
            )
        elif status == "undetermined":
            log.info("microphone permission not yet requested; the prompt will appear")

        if not self._screen_capture_authorised():
            warnings.append(
                "Screen Recording is not granted; 'what's on my screen' will not work. "
                "System Settings > Privacy & Security > Screen & System Audio Recording."
            )

        if not self._accessibility_trusted():
            log.info("Accessibility not granted; only needed for app control later")

        if not getattr(sys, "frozen", False):
            warnings.append(
                "Running from source, not from Jarvis.app. Permissions will be "
                "attributed to your terminal, not to Jarvis."
            )

        return warnings

    def _microphone_status(self) -> str:
        try:
            import AVFoundation

            status = AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(
                AVFoundation.AVMediaTypeAudio
            )
        except Exception:
            log.debug("could not read microphone authorisation", exc_info=True)
            return "unknown"
        return {0: "undetermined", 1: "restricted", 2: "denied", 3: "authorised"}.get(
            int(status), "unknown"
        )

    def _accessibility_trusted(self) -> bool:
        try:
            from ApplicationServices import AXIsProcessTrusted

            return bool(AXIsProcessTrusted())
        except Exception:
            log.debug("could not read accessibility trust", exc_info=True)
            return True


def _as_applescript_string(value: str) -> str:
    """Quote a Python string for interpolation into AppleScript source."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
