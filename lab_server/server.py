"""Server MCP: registra gli strumenti del laboratorio con FastMCP."""

import logging
from collections.abc import Callable
from datetime import datetime

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from lab_server.clock import current_time, utc_now

logger = logging.getLogger("lab_server")


def create_server(default_timezone: str, now: Callable[[], datetime] = utc_now) -> FastMCP:
    mcp = FastMCP("Strumenti del laboratorio")

    @mcp.tool
    def get_current_time(timezone: str | None = None) -> str:
        """Restituisce data e ora attuali in un fuso orario.

        Il parametro timezone è un nome IANA (es. Europe/Rome, Asia/Tokyo).
        Se omesso, si usa il fuso orario predefinito.
        """
        try:
            result = current_time(timezone, default_timezone, now)
        except ValueError as error:
            # ToolError: il client riceve un errore MCP, non un risultato di successo
            raise ToolError(str(error)) from None
        logger.debug("get_current_time(timezone=%s) → %s", timezone, result)
        return result

    return mcp
