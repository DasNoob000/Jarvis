"""Pick the adapter for this machine.

The imports are deliberately inside the branches: importing ``macos`` on Windows
would pull in rumps and fail, and vice versa.
"""

from __future__ import annotations

import sys

from jarvis.platform_adapters.base import PlatformAdapter


class UnsupportedPlatform(RuntimeError):
    pass


def make_adapter(override: str | None = None) -> PlatformAdapter:
    """Return the adapter for this platform.

    ``override`` is for tests and for forcing the Windows rig on a Mac.
    """
    target = override or sys.platform

    if target in ("darwin", "macos"):
        from jarvis.platform_adapters.macos import MacAdapter

        return MacAdapter()

    if target in ("win32", "windows", "cygwin"):
        from jarvis.platform_adapters.windows import WindowsAdapter

        return WindowsAdapter()

    raise UnsupportedPlatform(
        f"No adapter for {target!r}. Jarvis targets macOS; Windows is supported as a "
        f"development rig."
    )
