"""Entry point.

Sequence matters: the UI toolkit must end up owning the main thread, and it never
gives it back, so everything else is started first.
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading

from jarvis import APP_NAME, __version__
from jarvis.config import ConfigError, load_or_seed
from jarvis.engine import Engine, EngineThread
from jarvis.events import Command, EventBus
from jarvis.logging_setup import configure as configure_logging
from jarvis.platform_adapters.detect import UnsupportedPlatform, make_adapter
from jarvis.ui.menu import TrayController

log = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="jarvis", description=f"{APP_NAME} assistant")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--no-tray",
        action="store_true",
        help="run headless; useful over SSH and in CI",
    )
    parser.add_argument(
        "--platform",
        default=None,
        help="force an adapter (darwin|win32); for testing",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        help="override general.log_level from the config",
    )
    parser.add_argument(
        "--say",
        default=None,
        metavar="TEXT",
        help="submit one command at startup and exit when it finishes",
    )
    return parser.parse_args(argv)


def _fail(message: str) -> int:
    print(f"{APP_NAME}: {message}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    try:
        adapter = make_adapter(args.platform)
    except UnsupportedPlatform as exc:
        return _fail(str(exc))

    try:
        config = load_or_seed(adapter.config_dir())
    except ConfigError as exc:
        return _fail(str(exc))

    log_file = configure_logging(
        adapter.log_dir(),
        level=args.log_level or config.general.log_level,
        console=not getattr(sys, "frozen", False),
    )
    log.info("%s %s starting on %s", APP_NAME, __version__, adapter.name)
    log.info("config: %s", config.source_path)
    log.info("logs:   %s", log_file)

    bus = EventBus()
    engine = Engine(config=config, adapter=adapter, bus=bus)
    engine_thread = EngineThread(engine)

    stopping = threading.Event()
    controller: TrayController | None = None

    def shutdown() -> None:
        if stopping.is_set():
            return
        stopping.set()
        log.info("shutting down")
        engine_thread.stop()
        if controller is not None and controller.tray is not None:
            controller.tray.stop()

    engine_thread.start()

    if args.say:
        engine_thread.submit(Command(text=args.say))

    if args.no_tray:
        try:
            # Headless: idle until interrupted.
            while not stopping.is_set():
                threading.Event().wait(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            shutdown()
        return 0

    controller = TrayController(
        adapter=adapter,
        engine_thread=engine_thread,
        config=config,
        log_file=log_file,
        on_quit=shutdown,
    )
    bus.on_event(controller.on_event)

    try:
        tray = controller.build()
    except Exception as exc:
        log.exception("could not create the tray")
        shutdown()
        return _fail(f"could not create the menu-bar item: {exc}")

    try:
        tray.run()  # blocks on the main thread until stop()
    except KeyboardInterrupt:
        pass
    finally:
        shutdown()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
