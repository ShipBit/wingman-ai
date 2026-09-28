"""Standalone dashboard: python -m skills.sc_accountant.erp_launcher."""

from __future__ import annotations
import argparse
import logging
from pathlib import Path
import threading
import webbrowser

if __package__:
    from .erp import ERP
    from .erp_feed import capture_once
    from .erp_web import ERPServer
else:
    from erp import ERP
    from erp_feed import capture_once
    from erp_web import ERPServer


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local personal Star Citizen ERP")
    parser.add_argument(
        "--data-dir", type=Path, required=True, help="Folder for erp.sqlite3"
    )
    parser.add_argument("--port", type=int, default=7863)
    parser.add_argument(
        "--reader-db", type=Path, help="New SC_LogReader SQLite event database"
    )
    parser.add_argument(
        "--mode", choices=("simple", "advanced"), help="Explicitly select a view"
    )
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error("Port must be between 1024 and 65535")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    engine = ERP(args.data_dir / "erp.sqlite3")
    stop = threading.Event()
    worker = None
    server = ERPServer(engine, port=args.port)

    def capture():
        while not stop.is_set():
            delay = 15
            try:
                page = capture_once(engine, args.reader_db)
                if page.get("has_more"):
                    delay = 0.1
            except Exception as exc:
                engine.set_feed_error(str(exc)[:300])
            stop.wait(delay)

    try:
        if args.mode:
            engine.command("set_mode", {"mode": args.mode})
        server.start()
        if args.reader_db:
            worker = threading.Thread(
                target=capture, name="erp-reader-feed", daemon=True
            )
            worker.start()
        logging.getLogger(__name__).info("Personal ERP: %s", server.url)
        if not args.no_browser:
            webbrowser.open(server.url)
        while not stop.wait(1):
            pass
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        if worker:
            worker.join()
        server.stop()
        engine.close()


if __name__ == "__main__":
    main()
