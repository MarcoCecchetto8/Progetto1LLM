"""Avvio del back-end delle chat con uvicorn."""

import argparse
import logging
import os
import re
import sys

import psycopg
import uvicorn
from dotenv import load_dotenv

from assistant.agent_http import AgentHTTPClient
from backend_service.app import create_app
from backend_service.store import PostgresChatStore, StoreUnavailable

DEFAULT_AGENT_URL = "http://127.0.0.1:8001"


def _without_password(url: str) -> str:
    return re.sub(r"(://[^:/@\s]*):[^@\s]*@", r"\1@", url)


_SQLSTATE_HINTS = {
    "28P01": " Le variabili POSTGRES_* di .env valgono solo alla prima creazione del volume pgdata.",
    "3D000": " Le variabili POSTGRES_* di .env valgono solo alla prima creazione del volume pgdata.",
}


def _detail(error: Exception) -> str:
    """Causa originale di psycopg (prima riga: nomina utente e indirizzo, mai la password) e, se noto, un suggerimento."""
    cause = error.__cause__ if isinstance(error.__cause__, psycopg.Error) else error
    lines = str(cause).strip().splitlines()
    text = f" Dettaglio: {lines[0].strip()}" if lines and lines[0].strip() else ""
    sqlstate = getattr(cause, "sqlstate", None)
    return text + _SQLSTATE_HINTS.get(sqlstate, "")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m backend_service", description="Back-end HTTP delle chat.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8002)
    parser.add_argument("--quiet", action="store_true", help="solo avvisi, senza log degli accessi")
    args = parser.parse_args()

    load_dotenv()
    level = logging.WARNING if args.quiet else logging.INFO
    # stderr: stdout non si usa per i log
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("Manca DATABASE_URL: copia .env.example in .env e impostala "
              "(per esempio postgresql://lab:cambiami@127.0.0.1:5433/lab).", file=sys.stderr)
        raise SystemExit(1)
    try:
        store = PostgresChatStore(url)
    except (StoreUnavailable, psycopg.Error) as error:
        print(f"Il database non risponde all'indirizzo {_without_password(url)}: "
              f"avvia PostgreSQL con docker compose up -d db.{_detail(error)}", file=sys.stderr)
        raise SystemExit(1) from None

    agent = AgentHTTPClient(os.environ.get("BACKEND_AGENT_URL", "").strip() or DEFAULT_AGENT_URL)
    uvicorn.run(
        create_app(store, agent),
        host=args.host,
        port=args.port,
        log_level=logging.getLevelName(level).lower(),
        access_log=not args.quiet,
    )


if __name__ == "__main__":
    main()
