#!/usr/bin/env python
"""Developer harness — exercise one piece of Jarvis at a time from a terminal.

    python tools/devcli.py info
    python tools/devcli.py permissions
    python tools/devcli.py icons ./out
    python tools/devcli.py say "good morning"

Later phases add: ``listen`` (wake + STT), ``clap-tune`` (threshold calibration),
``chat`` (model + voice), ``devices`` (audio device list).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running straight from a checkout without installing.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jarvis import APP_NAME, BUNDLE_ID, __version__  # noqa: E402
from jarvis.config import ConfigError, load_or_seed  # noqa: E402
from jarvis.events import State  # noqa: E402
from jarvis.platform_adapters.detect import make_adapter  # noqa: E402
from jarvis.secrets import anthropic_key, elevenlabs_key  # noqa: E402


def cmd_info(args: argparse.Namespace) -> int:
    adapter = make_adapter(args.platform)
    print(f"{APP_NAME} {__version__}  ({BUNDLE_ID})")
    print(f"  adapter        {adapter.name}")
    print(f"  python         {sys.version.split()[0]}")
    print(f"  frozen         {getattr(sys, 'frozen', False)}")
    print()
    print(f"  config dir     {adapter.config_dir()}")
    print(f"  cache dir      {adapter.cache_dir()}")
    print(f"  log dir        {adapter.log_dir()}")
    print(f"  autostart      {'on' if adapter.autostart_enabled() else 'off'}"
          f"  (supported: {adapter.autostart_supported})")
    print(f"  automation     {adapter.supports_automation}")

    try:
        cfg = load_or_seed(adapter.config_dir())
    except ConfigError as exc:
        print(f"\n  CONFIG ERROR\n{exc}")
        return 1

    print()
    print(f"  config file    {cfg.source_path}")
    print(f"  personality    {cfg.personality_path}")
    print(f"  model          {cfg.llm.model}  effort={cfg.llm.effort}"
          f"  fast={cfg.llm.fast_mode}  fallbacks={cfg.llm.refusal_fallbacks}")
    print(f"  stt            {cfg.stt.backend}:{cfg.stt.model}")
    print(f"  tts            {cfg.tts.backend}  voice={cfg.tts.voice or '(default)'}")
    print(f"  cancel         {cfg.cancel.phrases}")

    print()
    key, source = anthropic_key()
    print(f"  anthropic key  {'set' if key else 'not set'}  via {source}")
    if not key:
        print("                 (the SDK will try an `ant auth login` profile)")
    key, source = elevenlabs_key()
    print(f"  elevenlabs key {'set' if key else 'not set'}  via {source}")
    return 0


def cmd_permissions(args: argparse.Namespace) -> int:
    adapter = make_adapter(args.platform)
    warnings = adapter.preflight()
    if not warnings:
        print("No permission problems detected.")
        return 0
    print(f"{len(warnings)} issue(s):\n")
    for w in warnings:
        print(f"  - {w}")
    print("\nSee packaging/macos/PERMISSIONS.md for the walkthrough.")
    return 1


def cmd_icons(args: argparse.Namespace) -> int:
    from jarvis.ui import icons

    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    for state in State:
        path = out / f"{state.value}.png"
        icons.render(state, args.size).save(path)
        print(f"  {path}  {icons.STATE_COLOURS[state]}")
    return 0


def cmd_say(args: argparse.Namespace) -> int:
    """Push one command through the engine without the tray."""
    import asyncio

    from jarvis.engine import Engine
    from jarvis.events import Command

    adapter = make_adapter(args.platform)
    cfg = load_or_seed(adapter.config_dir())
    engine = Engine(cfg, adapter)

    async def run() -> None:
        task = asyncio.create_task(engine.run())
        await asyncio.sleep(0)
        engine.submit_soon(Command(text=args.text))
        await asyncio.sleep(0.2)
        engine.request_stop()
        await task

    asyncio.run(run())
    return 0


def cmd_tray(args: argparse.Namespace) -> int:
    """Run the real app. Ctrl-C or the Quit item to stop."""
    from jarvis.__main__ import main

    return main([])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="devcli", description=__doc__)
    parser.add_argument("--platform", default=None, help="force an adapter")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("info", help="paths, config summary, credentials").set_defaults(
        func=cmd_info
    )
    sub.add_parser("permissions", help="run the platform preflight").set_defaults(
        func=cmd_permissions
    )
    sub.add_parser("tray", help="run the full app").set_defaults(func=cmd_tray)

    p = sub.add_parser("icons", help="dump the state icons as PNGs")
    p.add_argument("outdir")
    p.add_argument("--size", type=int, default=128)
    p.set_defaults(func=cmd_icons)

    p = sub.add_parser("say", help="push one command through the engine")
    p.add_argument("text")
    p.set_defaults(func=cmd_say)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    import logging

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
