"""Avvio del servizio dell'agente: python -m agent_service."""

import argparse
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m agent_service", description="Servizio HTTP dell'agente.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--quiet", action="store_true", help="solo avvisi, senza log degli accessi")
    args = parser.parse_args()

    # Librerie caricate dopo l'analisi degli argomenti: --help resta immediato
    import uvicorn
    from dotenv import load_dotenv

    from agent_service.app import create_app
    from agent_service.startup import build_agent
    from assistant.__main__ import configure_logging, quiet_library_warnings
    from assistant.config import ConfigError, load_settings
    from assistant.mcp_client import MCPConnectionError
    from assistant.notes import NotesConnectionError

    # Con stdout/stderr rediretti Windows può usare cp1252: forza UTF-8 per non rompere "→" e "…"
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    load_dotenv()
    quiet_library_warnings()
    try:
        settings = load_settings(os.environ)
        level = "WARNING" if args.quiet else settings.log_level
        configure_logging(level)
        agent, close = build_agent(settings, ROOT)
    except (ConfigError, MCPConnectionError, NotesConnectionError) as error:
        print(error, file=sys.stderr)
        return 1
    try:
        logging.getLogger("assistant").info("[api] agente in ascolto su http://%s:%d", args.host, args.port)
        uvicorn.run(create_app(agent), host=args.host, port=args.port, log_level=level.lower(),
                    access_log=not args.quiet)
    finally:
        close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
