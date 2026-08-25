"""py2app build script.

    cd packaging/macos
    python setup_py2app.py py2app          # release build
    python setup_py2app.py py2app -A       # alias build: fast, but not distributable

The alias build symlinks your source tree into the bundle, so edits take effect
without rebuilding. Use it for everything except the final artefact — note that TCC
permissions are keyed to the bundle, so an alias build and a release build are
treated as the same app and share their grants.

Every Info.plist key below has a reason; see PERMISSIONS.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

from setuptools import setup

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from jarvis import BUNDLE_ID, __version__  # noqa: E402

APP_NAME = "Jarvis"

PLIST = {
    "CFBundleName": APP_NAME,
    "CFBundleDisplayName": APP_NAME,
    "CFBundleIdentifier": BUNDLE_ID,
    "CFBundleVersion": __version__,
    "CFBundleShortVersionString": __version__,
    "CFBundleExecutable": APP_NAME,
    "NSHumanReadableCopyright": "",
    "LSMinimumSystemVersion": "13.0",
    # Jarvis has a Dock icon and a menu-bar item. Set LSUIElement to True if you
    # would rather it lived only in the menu bar.
    "LSUIElement": False,
    # Needed so the app can keep running with no window open.
    "NSSupportsAutomaticTermination": False,
    "NSSupportsSuddenTermination": False,
    # --- TCC usage descriptions -------------------------------------------------
    # These strings are shown verbatim in the permission dialogs. If a key is
    # missing, macOS kills the process instead of prompting, which looks like a
    # random crash. Write them for the user, not for the developer.
    "NSMicrophoneUsageDescription": (
        "Jarvis listens for a double clap to wake, and records your spoken command "
        "afterwards. Audio is transcribed on this Mac and is not uploaded."
    ),
    "NSSpeechRecognitionUsageDescription": (
        "Jarvis converts your speech to text so it can act on what you say."
    ),
    "NSAppleEventsUsageDescription": (
        "Jarvis controls other applications on your behalf — opening apps and asking "
        "them to do things you have requested."
    ),
    # Reserved for later phases; declared now so adding them does not require a
    # rebuild-and-reprompt cycle.
    "NSDesktopFolderUsageDescription": (
        "Jarvis reads files on your Desktop only when you ask it to."
    ),
    "NSDocumentsFolderUsageDescription": (
        "Jarvis reads files in your Documents folder only when you ask it to."
    ),
    "NSDownloadsFolderUsageDescription": (
        "Jarvis reads files in your Downloads folder only when you ask it to."
    ),
    # NOTE: Screen Recording and Accessibility have NO Info.plist usage-description
    # key. macOS generates those prompts itself and they are granted manually in
    # System Settings. See PERMISSIONS.md.
}

OPTIONS = {
    "plist": PLIST,
    "packages": ["jarvis", "certifi", "anthropic", "pydantic", "rumps"],
    "includes": ["jarvis.platform_adapters.macos"],
    # Never let the Windows adapter get pulled into a Mac bundle.
    "excludes": [
        "jarvis.platform_adapters.windows",
        "pystray",
        "mss",
        "tkinter",
        "pytest",
    ],
    "resources": [str(ROOT / "config")],
    "iconfile": str(Path(__file__).parent / "Jarvis.icns")
    if (Path(__file__).parent / "Jarvis.icns").exists()
    else None,
    "argv_emulation": False,  # breaks under launchd, and we take no file arguments
    "semi_standalone": False,
    "site_packages": True,
    "strip": True,
}

# py2app rejects a None iconfile rather than ignoring it.
if OPTIONS["iconfile"] is None:
    del OPTIONS["iconfile"]

setup(
    name=APP_NAME,
    version=__version__,
    app=[str(ROOT / "src" / "jarvis" / "__main__.py")],
    data_files=[],
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
