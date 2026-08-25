"""The rule that makes the engine testable off a Mac.

Platform-specific modules may only be imported from ``jarvis.platform_adapters``. If
this test fails, something leaked — move it behind the adapter rather than relaxing
the list.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "jarvis"
ALLOWED_DIR = SRC / "platform_adapters"

FORBIDDEN_ROOTS = {
    # macOS
    "rumps",
    "objc",
    "Quartz",
    "AVFoundation",
    "ApplicationServices",
    "Foundation",
    "AppKit",
    "Cocoa",
    "CoreGraphics",
    # Windows
    "pystray",
    "winreg",
    "win32api",
    "win32gui",
    "win32com",
    "mss",
    "comtypes",
}


def _python_files() -> list[Path]:
    return [
        p
        for p in SRC.rglob("*.py")
        if ALLOWED_DIR not in p.parents and p.parent != ALLOWED_DIR
    ]


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    return roots


@pytest.mark.parametrize("path", _python_files(), ids=lambda p: p.name)
def test_no_platform_imports_outside_adapters(path: Path) -> None:
    leaked = _imported_roots(path) & FORBIDDEN_ROOTS
    assert not leaked, (
        f"{path.relative_to(SRC)} imports {sorted(leaked)}, which is platform-specific. "
        f"Put it behind jarvis.platform_adapters instead."
    )


def test_the_test_can_actually_see_the_source() -> None:
    # Guard against the parametrisation silently collecting nothing.
    assert len(_python_files()) > 5
