"""Avvio del server MCP in stdio: python -m lab_server."""

import logging
import os
import sys
from collections.abc import Mapping
from pathlib import Path

from lab_server.preferences import parse_preferences
from lab_server.server import create_server

logger = logging.getLogger("lab_server")


def server_timezone(env: Mapping[str, str], root: Path) -> tuple[str, Path]:
    """Fuso predefinito del server (dalle preferenze, altrimenti DEFAULT_TIMEZONE) e percorso del file."""
    path = Path(env.get("PREFERENCES_FILE", "").strip() or "config/preferenze.json")
    if not path.is_absolute():
        path = root / path
    fallback = env.get("DEFAULT_TIMEZONE", "").strip() or "Europe/Rome"
    # Il server legge il file all'avvio e l'host lo rilegge dalla resource poco dopo:
    # i due valori coincidono, salvo modifiche al file durante l'avvio.
    try:
        text, reason = path.read_text(encoding="utf-8-sig"), ""
    except (OSError, UnicodeDecodeError) as error:
        text, reason = None, str(error)
    preferences, warnings = parse_preferences(text, fallback, reason)
    for warning in warnings:
        logger.debug("preferenze: %s", warning)
    return preferences.fuso_orario, path


def main() -> None:
    debug = os.environ.get("LOG_LEVEL", "").strip().upper() == "DEBUG"
    # Con stdio lo stdout è riservato al protocollo: i log vanno su stderr
    logging.basicConfig(level=logging.DEBUG if debug else logging.WARNING, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    timezone, path = server_timezone(os.environ, Path(__file__).resolve().parent.parent)
    create_server(timezone, preferences_file=path).run(show_banner=False)


if __name__ == "__main__":
    main()
