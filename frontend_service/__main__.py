"""Avvio del front-end con uvicorn."""

import argparse
import logging
import os
import sys

import uvicorn
from dotenv import load_dotenv

from frontend_service.app import create_app

DEFAULT_BACKEND_URL = "http://127.0.0.1:8002"


def backend_url_from_env(value: str) -> str:
    """Indirizzo del back-end da FRONTEND_BACKEND_URL: vuoto, quello locale; senza barra finale."""
    value = value.strip()
    if not value:
        return DEFAULT_BACKEND_URL
    if not value.startswith(("http://", "https://")):
        raise ValueError(f"FRONTEND_BACKEND_URL non valida: {value!r} (deve iniziare con http:// o https://).")
    return value.rstrip("/")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m frontend_service", description="Front-end web della chat.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8003)
    parser.add_argument("--quiet", action="store_true", help="solo avvisi, senza log degli accessi")
    args = parser.parse_args()

    load_dotenv()
    level = logging.WARNING if args.quiet else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    try:
        url = backend_url_from_env(os.environ.get("FRONTEND_BACKEND_URL", ""))
    except ValueError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None

    uvicorn.run(
        create_app(url),
        host=args.host,
        port=args.port,
        log_level=logging.getLevelName(level).lower(),
        access_log=not args.quiet,
    )


if __name__ == "__main__":
    main()
