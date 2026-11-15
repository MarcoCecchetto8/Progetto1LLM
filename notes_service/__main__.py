"""Avvio del servizio delle note con uvicorn."""

import argparse
import logging
from pathlib import Path

import uvicorn

from notes_service.app import create_app

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "notes.db"


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m notes_service", description="Servizio HTTP delle note.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="file SQLite delle note")
    parser.add_argument("--quiet", action="store_true", help="solo avvisi, senza log degli accessi")
    args = parser.parse_args()

    level = logging.WARNING if args.quiet else logging.INFO
    # stderr: stdout non si usa per i log
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run(
        create_app(args.db),
        host=args.host,
        port=args.port,
        log_level=logging.getLevelName(level).lower(),
        access_log=not args.quiet,
    )


if __name__ == "__main__":
    main()
