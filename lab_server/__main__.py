"""Avvio del server MCP in stdio: python -m lab_server."""

import logging
import os
import sys

from lab_server.server import create_server


def main() -> None:
    debug = os.environ.get("LOG_LEVEL", "").strip().upper() == "DEBUG"
    # Con stdio lo stdout è riservato al protocollo: i log vanno su stderr
    logging.basicConfig(level=logging.DEBUG if debug else logging.WARNING, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    default_timezone = os.environ.get("DEFAULT_TIMEZONE", "").strip() or "Europe/Rome"
    create_server(default_timezone).run(show_banner=False)


if __name__ == "__main__":
    main()
